"""Bill Payment Extractor — pure LLM extraction, no tools, no SQL.

Architecture: "Agent Extracts, Orchestrator Acts"
- Extractor: identifies biller_type, alias/name hint from user message
- BillResolver (service): executes deterministic SQL to find billers + bills
- Orchestrator: manages flow transitions (selection → confirmation → OTP → execute)
"""
from __future__ import annotations

import json
import logging
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.models.flow import BillDraft
from backend.prompts.bill_payment import BILL_EXTRACT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


class BillExtractionResult:
    """Output of the bill payment extractor."""

    def __init__(
        self,
        biller_type: str | None = None,
        alias_hint: str | None = None,
        biller_name_hint: str | None = None,
        pay_all: bool = False,
        interpretation: str = "",
    ):
        self.biller_type = biller_type
        self.alias_hint = alias_hint
        self.biller_name_hint = biller_name_hint
        self.pay_all = pay_all
        self.interpretation = interpretation


class BillPaymentExtractor:
    """Pure LLM entity extraction for bill payment.

    Extracts:
    - biller_type: ELECTRICITY, WATER, INTERNET, PHONE_POSTPAID
    - alias_hint: user-specified alias like "nhà Hà Nội", "internet nhà"
    - biller_name_hint: specific biller like "EVN", "FPT"
    - pay_all: user wants to pay ALL unpaid bills
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
        current_bill_draft: BillDraft | None = None,
        session_id: str = "",
    ) -> BillExtractionResult:
        """Extract bill payment intent details from user message."""
        system_prompt = BILL_EXTRACT_SYSTEM_PROMPT.format(
            current_date=date.today().isoformat(),
        )

        user_prompt = self._build_user_prompt(message, current_bill_draft)

        try:
            config = get_trace_config(
                session_id=session_id,
                user_id=user_id,
                trace_name="bill_extractor",
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
            logger.error(f"[BILL EXTRACTOR] Error: {e}", exc_info=True)
            return BillExtractionResult(interpretation=f"Error: {e}")

    def _build_user_prompt(
        self, message: str, current_bill_draft: BillDraft | None
    ) -> str:
        parts = [f"User message: {message}"]

        if current_bill_draft:
            draft_info = []
            if current_bill_draft.biller_type:
                draft_info.append(f"biller_type: {current_bill_draft.biller_type}")
            if current_bill_draft.alias:
                draft_info.append(f"alias: {current_bill_draft.alias}")
            if current_bill_draft.biller_name:
                draft_info.append(f"biller_name: {current_bill_draft.biller_name}")
            if draft_info:
                parts.append(f"Current bill context: {', '.join(draft_info)}")

        return "\n".join(parts)

    def _parse_response(self, content: str) -> BillExtractionResult:
        """Parse LLM JSON output into BillExtractionResult."""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            data = json.loads(text)

            return BillExtractionResult(
                biller_type=data.get("biller_type"),
                alias_hint=data.get("alias_hint"),
                biller_name_hint=data.get("biller_name_hint"),
                pay_all=data.get("pay_all", False),
                interpretation=data.get("interpretation", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[BILL EXTRACTOR] Parse error: {e}, raw: {content[:200]}")
            return BillExtractionResult(interpretation=content[:200])
