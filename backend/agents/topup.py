"""Top-Up Extractor — pure LLM extraction for phone/wallet top-up.

Architecture: "Agent Extracts, Orchestrator Acts"
- Extractor: identifies phone number, amount, provider, type
- Orchestrator: validates, confirms, handles OTP, executes via TopUpExecutor
"""
from __future__ import annotations

import json
import logging
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.models.flow import TopUpDraft
from backend.prompts.topup import TOPUP_EXTRACT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


class TopUpExtractionResult:
    """Output of the top-up extractor."""

    def __init__(
        self,
        topup_target: str | None = None,
        topup_provider: str | None = None,
        topup_type: str | None = None,
        amount: int | None = None,
        interpretation: str = "",
    ):
        self.topup_target = topup_target
        self.topup_provider = topup_provider
        self.topup_type = topup_type
        self.amount = amount
        self.interpretation = interpretation


class TopUpExtractor:
    """Pure LLM entity extraction for top-up.

    Extracts:
    - topup_target: phone number (10 digits starting with 0) or wallet ID
    - topup_provider: Viettel, Mobifone, Vinaphone, Vietnamobile, MoMo, ZaloPay
    - topup_type: "phone" or "wallet"
    - amount: in VND
    """

    def __init__(self):
        self._llm = ChatOpenAI(
            model=OPENAI_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=0.0,
        )

    async def process(
        self,
        message: str,
        user_id: str,
        current_draft: TopUpDraft | None = None,
        session_id: str = "",
    ) -> TopUpExtractionResult:
        """Extract top-up intent details from user message."""
        system_prompt = TOPUP_EXTRACT_SYSTEM_PROMPT

        user_prompt = self._build_user_prompt(message, current_draft)

        try:
            config = get_trace_config(
                session_id=session_id,
                user_id=user_id,
                trace_name="topup_extractor",
            )
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
                config=config,
            )
            return self._parse_response(response.content)
        except Exception as e:
            logger.error(f"[TOPUP EXTRACTOR] Error: {e}", exc_info=True)
            return TopUpExtractionResult(interpretation=f"Error: {e}")

    def _build_user_prompt(self, message: str, current_draft: TopUpDraft | None) -> str:
        parts = [f"User message: {message}"]

        if current_draft:
            draft_info = []
            if current_draft.topup_target:
                draft_info.append(f"phone: {current_draft.topup_target}")
            if current_draft.topup_provider:
                draft_info.append(f"provider: {current_draft.topup_provider}")
            if current_draft.amount:
                draft_info.append(f"amount: {current_draft.amount}")
            if current_draft.topup_type:
                draft_info.append(f"type: {current_draft.topup_type}")
            if draft_info:
                parts.append(f"Current draft: {', '.join(draft_info)}")

        return "\n".join(parts)

    def _parse_response(self, content: str) -> TopUpExtractionResult:
        """Parse LLM JSON output into TopUpExtractionResult."""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            data = json.loads(text)

            return TopUpExtractionResult(
                topup_target=data.get("topup_target"),
                topup_provider=data.get("topup_provider"),
                topup_type=data.get("topup_type", "phone"),
                amount=data.get("amount"),
                interpretation=data.get("interpretation", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[TOPUP EXTRACTOR] Parse error: {e}, raw: {content[:200]}")
            return TopUpExtractionResult(interpretation=content[:200])
