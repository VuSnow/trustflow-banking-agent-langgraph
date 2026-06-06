"""Flow Router — deterministic routing with LLM as fallback only.

Design principle: status-first dispatch, then pending_question match,
then confirmation classify, then intent classify. LLM is NEVER the
primary router for sensitive transitions.

Router order:
1. No active flow → CLASSIFY_NEW_INTENT
2. WAITING_OTP → only OTP/cancel/interrupt
3. Has pending_question → try structural match
4. WAITING_*_CONFIRMATION → confirm/cancel/modify
5. COLLECTING → continue or detect intent switch
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from backend.models.flow import FlowState, PendingQuestion

logger = logging.getLogger(__name__)


# ─── RouteDecision ────────────────────────────────────────────────────────────

@dataclass
class RouteDecision:
    """Output of the router — tells orchestrator what action to take."""

    action: Literal[
        "CLASSIFY_NEW_INTENT",
        "CONTINUE_COLLECTING",
        "ANSWER_PENDING_QUESTION",
        "CONFIRM",
        "CANCEL_ACTIVE_FLOW",
        "MODIFY_DRAFT",
        "SUBMIT_OTP",
        "INTERRUPT_LOCKED_FLOW",
        "ASK_SWITCH_OR_CANCEL",
        "ASK_VALID_INPUT",
    ]
    data: dict | None = None
    interrupted_intent: str | None = None


def serialize_route_decision(decision: RouteDecision) -> dict:
    """RouteDecision → dict for ChatState."""
    return {
        "action": decision.action,
        "data": decision.data,
        "interrupted_intent": decision.interrupted_intent,
    }


# ─── Confirmation Classifier Interface ───────────────────────────────────────


class ConfirmationClassifierInterface:
    """Interface for confirmation/cancel/modify classification.

    Implementations can be rule-based, LLM-based, or hybrid.
    """

    async def classify(self, message: str) -> str:
        """Classify message as CONFIRM, CANCEL, MODIFY, or UNCLEAR."""
        raise NotImplementedError

    async def is_cancel(self, message: str) -> bool:
        """Quick check if message is a cancellation."""
        raise NotImplementedError


class IntentClassifierInterface:
    """Interface for new intent classification."""

    async def classify(self, message: str) -> str | None:
        """Classify message into intent type or None if unclear."""
        raise NotImplementedError


# ─── LLM-based confirmation classifier ────────────────────────────────────────


class RuleBasedConfirmationClassifier(ConfirmationClassifierInterface):
    """LLM-based confirmation classifier — handles all languages and variants."""

    _SYSTEM_PROMPT = (
        "You are a confirmation classifier for a banking transaction system.\n"
        "The user has just been shown a transaction summary (amount, recipient, fee).\n"
        "The system is now waiting for them to: confirm (proceed), cancel (stop), or modify (change details).\n\n"
        "Rules:\n"
        "- CONFIRM: user agrees to proceed. Examples: ok, ừ, đồng ý, yes, xác nhận, chuyển đi, tiếp tục, được, chuẩn.\n"
        "- CANCEL: user wants to stop/abort. Examples: không, hủy, huỷ, thôi, cancel, bỏ, dừng.\n"
        "- MODIFY: user wants to change a detail (amount, recipient, bank, etc.).\n"
        "- UNCLEAR: ambiguous, unrelated, or a question (e.g. asking about fees).\n\n"
        "Output ONLY the single word: CONFIRM, CANCEL, MODIFY, or UNCLEAR. Nothing else."
    )

    async def classify(self, message: str) -> str:
        from langchain_core.messages import SystemMessage, HumanMessage
        from langchain_openai import ChatOpenAI
        from backend.config import OPENAI_API_KEY, OPENAI_MODEL

        llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)
        try:
            response = await llm.ainvoke([
                SystemMessage(content=self._SYSTEM_PROMPT),
                HumanMessage(content=message),
            ])
            result = response.content.strip().upper()
            if result not in ("CONFIRM", "CANCEL", "MODIFY", "UNCLEAR"):
                result = "UNCLEAR"
            logger.info(f"[CONFIRMATION_CLF] LLM: {result} for '{message}'")
            return result
        except Exception as e:
            logger.error(f"[CONFIRMATION_CLF] Error: {e}", exc_info=True)
            return "UNCLEAR"

    async def is_cancel(self, message: str) -> bool:
        return (await self.classify(message)) == "CANCEL"


# ─── Flow Router ──────────────────────────────────────────────────────────────

class FlowRouter:
    """Deterministic routing based on flow state. LLM is fallback only.

    Status-first dispatch ensures sensitive transitions (OTP, confirmation)
    are NEVER misrouted by LLM classification errors.
    """

    def __init__(
        self,
        confirmation_classifier: ConfirmationClassifierInterface,
        intent_classifier: IntentClassifierInterface,
    ):
        self._confirm_clf = confirmation_classifier
        self._intent_clf = intent_classifier

    async def route(self, flow: FlowState | None, user_message: str) -> RouteDecision:
        """Main routing entry point.

        Args:
            flow: Current active flow (None if no flow active).
            user_message: Latest user message text.

        Returns:
            RouteDecision telling orchestrator what to do next.
        """
        # 1. No active flow → classify fresh
        if flow is None:
            return RouteDecision(action="CLASSIFY_NEW_INTENT")

        # 2. Status-first: WAITING_OTP is LOCKED
        if flow.status == "WAITING_OTP":
            return await self._route_waiting_otp(flow, user_message)

        # 3. Has pending question → try structural match
        if flow.pending_question:
            matched = self._try_match_pending(flow.pending_question, user_message)
            if matched:
                return RouteDecision(action="ANSWER_PENDING_QUESTION", data=matched)

        # 4. LIMITED states → confirm/cancel/modify
        if flow.status in ("WAITING_RECIPIENT_CONFIRMATION", "WAITING_DRAFT_CONFIRMATION", "WAITING_BILL_CONFIRMATION", "WAITING_TOPUP_CONFIRMATION"):
            return await self._route_limited(flow, user_message)

        # 4b. WAITING_BILLER_SELECTION → user is picking from a list, treat as COLLECTING
        if flow.status == "WAITING_BILLER_SELECTION":
            return RouteDecision(action="CONTINUE_COLLECTING")

        # 5. COLLECTING (flexible) → continue or detect intent switch
        if flow.status == "COLLECTING":
            return await self._route_collecting(flow, user_message)

        # Fallback
        return RouteDecision(action="ASK_VALID_INPUT")

    async def _route_waiting_otp(self, flow: FlowState, msg: str) -> RouteDecision:
        """LOCKED state — only OTP, cancel, or interrupt storage."""
        # Check if it looks like OTP
        if self._looks_like_otp(msg):
            return RouteDecision(action="SUBMIT_OTP", data={"otp": msg.strip()})

        # Purely numeric but wrong length → likely a mis-typed OTP, not an intent
        if msg.strip().isdigit():
            return RouteDecision(action="ASK_VALID_INPUT")

        # Check cancel
        if await self._confirm_clf.is_cancel(msg):
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")

        # Check if it's a new intent → save as interrupted
        new_intent = await self._intent_clf.classify(msg)
        if new_intent and new_intent != flow.flow_type:
            return RouteDecision(
                action="INTERRUPT_LOCKED_FLOW",
                interrupted_intent=new_intent,
            )

        # Default: ask for valid OTP or cancel
        return RouteDecision(action="ASK_VALID_INPUT")

    async def _route_limited(self, flow: FlowState, msg: str) -> RouteDecision:
        """LIMITED state — user can confirm, cancel, or request modification."""
        result = await self._confirm_clf.classify(msg)

        if result == "CONFIRM":
            return RouteDecision(action="CONFIRM")
        if result == "CANCEL":
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")
        if result == "MODIFY":
            return RouteDecision(action="MODIFY_DRAFT")

        # UNCLEAR — ask for clear input
        return RouteDecision(action="ASK_VALID_INPUT")

    async def _route_collecting(self, flow: FlowState, msg: str) -> RouteDecision:
        """FLEXIBLE state — detect intent switch or continue collecting info."""
        intent = await self._intent_clf.classify(msg)

        # Same intent or unclear → continue collecting
        # Intent may be composite (e.g. "TRANSACTION:TRANSFER_MONEY"), check prefix match
        if intent is None or intent == "UNKNOWN":
            return RouteDecision(action="CONTINUE_COLLECTING")
        if intent == flow.flow_type or intent.startswith(f"{flow.flow_type}:"):
            return RouteDecision(action="CONTINUE_COLLECTING")

        # Different intent detected → ask user, don't auto-switch
        return RouteDecision(action="ASK_SWITCH_OR_CANCEL", interrupted_intent=intent)

    def _try_match_pending(self, pq: PendingQuestion, msg: str) -> dict | None:
        """Structural matching based on expected_type — no LLM needed.

        Returns matched data dict if message answers the pending question,
        None if it doesn't match (fallback to other routing).
        """
        if pq.expected_type == "recipient_choice" and pq.options:
            # User answers "1", "2", or matches a name
            clean = msg.strip()
            if clean.isdigit():
                idx = int(clean) - 1
                if 0 <= idx < len(pq.options):
                    return {"choice": pq.options[idx], "index": idx}
            # Fuzzy name match against options
            for i, opt in enumerate(pq.options):
                opt_name = opt.get("name", "").lower()
                if opt_name and opt_name in msg.lower():
                    return {"choice": opt, "index": i}
            return None

        if pq.expected_type == "otp":
            if self._looks_like_otp(msg):
                return {"otp": msg.strip()}
            return None

        if pq.expected_type == "amount":
            amount = self._parse_amount(msg)
            return {"amount": amount} if amount else None

        if pq.expected_type == "text":
            # Any non-empty text is a valid answer
            if msg.strip():
                return {"text": msg.strip()}
            return None

        # enum type → let _route_limited handle via confirmation classifier
        return None

    def _looks_like_otp(self, msg: str) -> bool:
        """Structural check: OTP is 4-8 digits."""
        clean = msg.strip()
        return clean.isdigit() and 4 <= len(clean) <= 8

    def _parse_amount(self, msg: str) -> int | None:
        """Parse Vietnamese amount expressions.

        Handles: k/nghìn/ngàn (×1000), tr/triệu/củ (×1M), tỷ (×1B).
        """
        text = msg.strip().lower().replace(",", "").replace(".", "")
        patterns = [
            (r"(\d+)\s*(?:tỷ|ty)", 1_000_000_000),
            (r"(\d+)\s*(?:tr|triệu|trieu|củ|cu)", 1_000_000),
            (r"(\d+)\s*(?:k|nghìn|nghin|ngàn|ngan)", 1_000),
            (r"^(\d+)$", 1),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, text)
            if m:
                return int(m.group(1)) * multiplier
        return None
