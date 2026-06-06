"""LLM-based confirmation classifier."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.confirmation import CONFIRMATION_CLASSIFIER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def classify_confirmation(message: str, draft_summary: str | None = None) -> dict:
    """Classify user's response to a transaction confirmation prompt.

    Returns: {"classification": "CONFIRM|CANCEL|MODIFY|UNCLEAR", "reason": "..."}
    """
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)

    user_content = f"User response: {message}"
    if draft_summary:
        user_content = f"Transaction being confirmed: {draft_summary}\n\n{user_content}"

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        response = await llm.ainvoke([
            SystemMessage(content=CONFIRMATION_CLASSIFIER_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])
        raw = response.content
        data = json.loads(raw)
        classification = data.get("classification", "UNCLEAR").upper()
        if classification not in ("CONFIRM", "CANCEL", "MODIFY", "UNCLEAR"):
            classification = "UNCLEAR"
        logger.info(f"[CLASSIFIER] LLM: {classification} for '{message}'")
        return {"classification": classification, "reason": data.get("reason", "")}
    except Exception as e:
        logger.error(f"[CLASSIFIER] Error: {e}", exc_info=True)
        return {"classification": "UNCLEAR", "reason": f"classifier_error: {e}"}
