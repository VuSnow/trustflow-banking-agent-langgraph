"""Card Operation Extractor — pure LLM entity extraction for card operations.

Design principle: Agent ONLY extracts what card + what operation.
Orchestrator resolves card, validates, asks confirmation, and executes.
NO tools, NO SQL — just structured extraction from user's message.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.card_operation import CARD_EXTRACT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


@dataclass
class CardExtractionResult:
    """Output from card operation extraction."""

    operation: str | None = None  # LOCK_CARD, UNLOCK_CARD, REPORT_LOST, VIEW_CARD_INFO
    card_hint_last4: str | None = None  # "4223"
    card_hint_type: str | None = None  # "DEBIT" / "CREDIT"
    card_hint_network: str | None = None  # "VISA" / "MASTERCARD" / "NAPAS"
    interpretation: str = ""


class CardOperationExtractor:
    """Extract card operation intent and card hints from user message."""

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
        cards_context: str = "",
        session_id: str = "",
    ) -> CardExtractionResult:
        """Extract operation and card hints from user's message.

        Args:
            message: User's message
            user_id: Customer CIF
            cards_context: Formatted list of user's cards (for disambiguation)
            session_id: For tracing
        """
        user_prompt = f"User cards:\n{cards_context}\n\nUser message: {message}"

        try:
            config = get_trace_config(
                session_id=session_id,
                user_id=user_id,
                trace_name="card_extractor",
            )
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=CARD_EXTRACT_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ],
                config=config,
            )

            raw = response.content.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines)

            data = json.loads(raw)

            return CardExtractionResult(
                operation=data.get("operation"),
                card_hint_last4=data.get("card_hint_last4"),
                card_hint_type=data.get("card_hint_type"),
                card_hint_network=data.get("card_hint_network"),
                interpretation=data.get("interpretation", ""),
            )

        except Exception as e:
            logger.error(f"[CARD_EXTRACTOR] Error: {e}", exc_info=True)
            return CardExtractionResult(interpretation=f"Error: {e}")
