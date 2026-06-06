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
from dataclasses import dataclass
from typing import Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
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


# ─── Confirmation Classifier ─────────────────────────────────────────────────

_CONFIRM_PATTERNS = re.compile(
    r"^(ok|oke|okie|ừ|uh|ờ|đồng ý|xác nhận|yes|yep|đúng|chuyển đi|tiếp tục|được|chuẩn|confirm|y)$",
    re.IGNORECASE,
)

_CANCEL_PATTERNS = re.compile(
    r"^(không|hủy|huỷ|thôi|cancel|bỏ|dừng|no|nope|ko|k|huy)$",
    re.IGNORECASE,
)

_SKIP_CATEGORY_PATTERNS = re.compile(
    r"^(bỏ qua|skip|bỏ|không cần|thôi|ko cần)$",
    re.IGNORECASE,
)

_MODIFY_KEYWORDS = re.compile(
    r"(đổi|sửa|thay|chỉnh|modify|change|update|edit|giảm|tăng|bớt|thêm)",
    re.IGNORECASE,
)


async def classify_confirmation_llm(message: str) -> str:
    """LLM-based confirmation classifier for ambiguous cases."""
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)
    prompt = (
        "You are a confirmation classifier for a banking system.\n"
        "The user was shown a transaction summary and asked to confirm.\n"
        "Classify the user's response as exactly one of: CONFIRM, CANCEL, MODIFY, UNCLEAR.\n"
        "Rules:\n"
        "- CONFIRM: user agrees (ok, ừ, đồng ý, yes, xác nhận, chuyển đi)\n"
        "- CANCEL: user wants to stop (không, hủy, thôi, cancel, bỏ)\n"
        "- MODIFY: user wants to change something (đổi số tiền, sửa người nhận)\n"
        "- UNCLEAR: can't determine\n\n"
        "Reply with exactly one word: CONFIRM, CANCEL, MODIFY, or UNCLEAR."
    )
    try:
        response = await llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"User said: {message}"),
        ])
        result = response.content.strip().upper()
        if result in ("CONFIRM", "CANCEL", "MODIFY", "UNCLEAR"):
            return result
        return "UNCLEAR"
    except Exception:
        return "UNCLEAR"


# ─── FlowRouter ──────────────────────────────────────────────────────────────


class FlowRouter:
    """Deterministic flow router — decides action per user turn."""

    async def route(self, flow: FlowState | None, message: str) -> RouteDecision:
        """Route user message based on current flow state.

        Priority:
        1. No flow → new intent
        2. Locked (WAITING_OTP) → OTP or cancel only
        3. Limited (confirmations) → confirm/cancel/modify
        4. Category confirmation (flexible, soft ask)
        5. Flexible (COLLECTING) → continue or detect switch
        """
        msg = message.strip()

        # 1. No active flow
        if flow is None:
            return RouteDecision(action="CLASSIFY_NEW_INTENT")

        # 2. Locked: WAITING_OTP
        if flow.status == "WAITING_OTP":
            return self._route_otp(msg)

        # 3. Limited: confirmation states
        if flow.status in (
            "WAITING_RECIPIENT_CONFIRMATION",
            "WAITING_DRAFT_CONFIRMATION",
            "WAITING_BILL_CONFIRMATION",
            "WAITING_TOPUP_CONFIRMATION",
            "WAITING_CARD_CONFIRMATION",
        ):
            return await self._route_confirmation(msg)

        # 4. Category confirmation (post-execution soft ask)
        if flow.status == "WAITING_CATEGORY_CONFIRMATION":
            return self._route_category_confirmation(msg, flow)

        # 5. Flexible: COLLECTING
        if flow.status == "COLLECTING":
            # Check if pending question can be answered structurally
            if flow.pending_question:
                structural = self._try_structural_answer(flow.pending_question, msg)
                if structural:
                    return structural

            # Check for cancel
            if _CANCEL_PATTERNS.match(msg):
                return RouteDecision(action="CANCEL_ACTIVE_FLOW")

            # Continue collecting
            return RouteDecision(action="CONTINUE_COLLECTING")

        # Default
        return RouteDecision(action="CONTINUE_COLLECTING")

    def _route_otp(self, msg: str) -> RouteDecision:
        """Route in WAITING_OTP state — only OTP or cancel."""
        # Cancel
        if _CANCEL_PATTERNS.match(msg):
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")

        # OTP: exactly 6 digits
        if re.match(r"^\d{6}$", msg):
            return RouteDecision(action="SUBMIT_OTP", data={"otp": msg})

        # Anything else that's not OTP-like
        if re.match(r"^\d+$", msg) and len(msg) != 6:
            return RouteDecision(action="ASK_VALID_INPUT")

        # Could be a new intent — interrupt
        return RouteDecision(action="INTERRUPT_LOCKED_FLOW", interrupted_intent=msg)

    async def _route_confirmation(self, msg: str) -> RouteDecision:
        """Route in confirmation states — confirm/cancel/modify."""
        # Fast rule-based check
        if _CONFIRM_PATTERNS.match(msg):
            return RouteDecision(action="CONFIRM")
        if _CANCEL_PATTERNS.match(msg):
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")
        if _MODIFY_KEYWORDS.search(msg):
            return RouteDecision(action="MODIFY_DRAFT")

        # Ambiguous — use LLM classifier
        classification = await classify_confirmation_llm(msg)
        if classification == "CONFIRM":
            return RouteDecision(action="CONFIRM")
        elif classification == "CANCEL":
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")
        elif classification == "MODIFY":
            return RouteDecision(action="MODIFY_DRAFT")
        else:
            return RouteDecision(action="ASK_VALID_INPUT")

    def _route_category_confirmation(self, msg: str, flow: FlowState) -> RouteDecision:
        """Route in WAITING_CATEGORY_CONFIRMATION — soft ask, user can freely switch.

        - Confirm → save predicted category
        - Number selection → save user's chosen alternative
        - Skip → save predicted category silently
        - Anything else → save predicted category + treat as new intent
        """
        # User confirms the predicted category
        if _CONFIRM_PATTERNS.match(msg):
            return RouteDecision(action="CONFIRM")

        # User says skip/bỏ qua
        if _SKIP_CATEGORY_PATTERNS.match(msg):
            return RouteDecision(action="CANCEL_ACTIVE_FLOW")

        # User picks an alternative by number (e.g., "2", "3")
        if re.match(r"^\d+$", msg):
            idx = int(msg) - 1
            prediction = flow.category_prediction
            if prediction and prediction.alternatives and 0 <= idx < len(prediction.alternatives):
                return RouteDecision(
                    action="ANSWER_PENDING_QUESTION",
                    data={"category_choice": prediction.alternatives[idx]},
                )
            # Invalid number → treat as new intent
            return RouteDecision(action="CLASSIFY_NEW_INTENT")

        # Anything else → user switched topic, save predicted and route new intent
        return RouteDecision(action="CLASSIFY_NEW_INTENT")

    def _try_structural_answer(
        self, pending: PendingQuestion, msg: str
    ) -> RouteDecision | None:
        """Try to answer a pending question without LLM."""
        if pending.expected_type in ("recipient_choice", "enum"):
            # Expecting a number like "1", "2", "3"
            if re.match(r"^\d+$", msg):
                idx = int(msg) - 1
                options = pending.options or []
                if 0 <= idx < len(options):
                    return RouteDecision(
                        action="ANSWER_PENDING_QUESTION",
                        data={"choice": options[idx]},
                    )
            return None

        if pending.expected_type == "amount":
            # Try to parse amount from message
            amount = self._parse_amount(msg)
            if amount:
                return RouteDecision(
                    action="ANSWER_PENDING_QUESTION",
                    data={"amount": amount},
                )
            return None

        if pending.expected_type == "otp":
            if re.match(r"^\d{6}$", msg):
                return RouteDecision(action="SUBMIT_OTP", data={"otp": msg})
            return None

        return None

    def _parse_amount(self, msg: str) -> int | None:
        """Try to parse Vietnamese amount expressions."""
        msg = msg.strip().lower().replace(",", "").replace(".", "")

        # Direct number
        if re.match(r"^\d+$", msg):
            val = int(msg)
            if val >= 1000:
                return val
            return None

        # Multiplier patterns
        patterns = [
            (r"(\d+)\s*(tr|triệu|trieu|củ|cu)", 1_000_000),
            (r"(\d+)\s*(k|nghìn|nghin|nghìn|ngàn|ngan)", 1_000),
            (r"(\d+)\s*(tỷ|ty)", 1_000_000_000),
        ]
        for pattern, multiplier in patterns:
            m = re.search(pattern, msg)
            if m:
                return int(m.group(1)) * multiplier

        return None
