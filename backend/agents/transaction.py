"""Transaction Extractor — controlled extraction agent.

This agent ONLY:
- Understands user intent within transaction context
- Extracts entities (amount, recipient, note)
- Produces a structured RecipientResolutionPlan for the orchestrator
- Returns TransactionExtractionResult

It does NOT:
- Call tools directly (orchestrator handles resolution via RecipientResolver)
- Write SQL or natural language queries
- Confirm transactions
- Execute transfers
- Send OTP
- Decide flow transitions
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.models.flow import (
    TransactionDraft,
    PendingQuestion,
    RecipientResolutionPlan,
    TransactionExtractionResult,
)
from backend.prompts.transaction import TRANSACTION_EXTRACT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


def get_current_date_vn() -> str:
    """Get current date in Vietnam timezone (ISO format)."""
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()


# ─── Transaction Extractor ────────────────────────────────────────────────────

class TransactionExtractor:
    """Controlled extraction agent — LLM extracts, orchestrator acts.

    Receives: user message + current draft + pending question context.
    Returns: TransactionExtractionResult with extracted fields + resolution plan.
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
        current_draft: TransactionDraft | None,
        pending_question: PendingQuestion | None,
        session_id: str = "",
    ) -> TransactionExtractionResult:
        """Extract transaction fields from user message.

        Args:
            message: User's latest message.
            user_id: Customer cif_no (for context, not injected into prompt).
            current_draft: Current draft state (may be None).
            pending_question: What the system last asked (may be None).
            session_id: For tracing.

        Returns:
            TransactionExtractionResult with fields and resolution plan.
        """
        current_date = get_current_date_vn()
        system_prompt = TRANSACTION_EXTRACT_SYSTEM_PROMPT.format(current_date=current_date)
        user_content = self._build_user_prompt(message, current_draft, pending_question, current_date)

        try:
            config = get_trace_config(
                session_id=session_id,
                user_id=user_id,
                trace_name="transaction_extractor",
            )

            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ],
                config=config,
            )

            return self._parse_response(response.content)

        except Exception as e:
            logger.error(f"[TX_EXTRACTOR] Error: {e}", exc_info=True)
            return TransactionExtractionResult(
                interpretation=f"Error: {e}",
            )

    def _build_user_prompt(
        self,
        message: str,
        draft: TransactionDraft | None,
        pending_question: PendingQuestion | None,
        current_date: str,
    ) -> str:
        """Build the user message for LLM with context."""
        parts = [f"User message: {message}"]

        if draft:
            draft_dict = {
                k: v
                for k, v in draft.model_dump().items()
                if v is not None
                and k not in ("confirmation_id", "idempotency_key", "currency",
                              "fee", "total_debit", "source_account_no",
                              "source_account_no_masked", "fraud_screening")
            }
            if draft_dict:
                parts.append(f"Current draft: {json.dumps(draft_dict, ensure_ascii=False)}")
            else:
                parts.append("Current draft: null")
        else:
            parts.append("Current draft: null")

        if pending_question:
            pq_dict = pending_question.model_dump()
            parts.append(f"Pending question: {json.dumps(pq_dict, ensure_ascii=False)}")
        else:
            parts.append("Pending question: null")

        parts.append(f"Current date: {current_date}")

        return "\n".join(parts)

    def _parse_response(self, raw: str) -> TransactionExtractionResult:
        """Parse LLM JSON response into TransactionExtractionResult."""
        try:
            # Strip markdown fences if present
            content = raw.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                lines = [line for line in lines if not line.strip().startswith("```")]
                content = "\n".join(lines)

            data = json.loads(content)

            # Parse recipient_resolution_plan if present
            plan_data = data.get("recipient_resolution_plan")
            plan = None
            if plan_data:
                try:
                    plan = RecipientResolutionPlan.model_validate(plan_data)
                except Exception as e:
                    logger.warning(f"[TX_EXTRACTOR] Plan validation failed: {e}")
                    plan = None

            return TransactionExtractionResult(
                extracted_fields=data.get("extracted_fields", {}),
                recipient_resolution_plan=plan,
                missing_fields=data.get("missing_fields", []),
                interpretation=data.get("interpretation", ""),
            )

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[TX_EXTRACTOR] JSON parse failed: {e}, raw={raw[:200]}")
            return TransactionExtractionResult(
                interpretation=f"Parse error: {raw[:200] if raw else ''}",
            )


# ─── Legacy compatibility wrapper ────────────────────────────────────────────

async def run_transaction_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Legacy wrapper — delegates to TransactionExtractor.

    Returns dict compatible with old orchestrator interface.
    """
    extractor = TransactionExtractor()
    result = await extractor.process(
        message=message,
        user_id=user_id,
        current_draft=None,
        pending_question=None,
        session_id=session_id,
    )

    if result.recipient_resolution_plan:
        return {
            "status": "clarification_needed",
            "message": result.interpretation or "Đang xử lý...",
            "data": {
                "extracted_fields": result.extracted_fields,
                "recipient_resolution_plan": result.recipient_resolution_plan.model_dump(),
                "missing_fields": result.missing_fields,
            },
        }

    return {
        "status": "info_response",
        "message": result.interpretation or "Đã nhận thông tin.",
        "data": {
            "extracted_fields": result.extracted_fields,
            "missing_fields": result.missing_fields,
        },
    }

