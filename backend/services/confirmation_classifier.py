"""LLM-based confirmation classifier."""
from __future__ import annotations

import json
import logging
import re

from langchain_openai import ChatOpenAI

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.confirmation import CONFIRMATION_CLASSIFIER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Rule-based patterns for unambiguous confirmations/cancellations
_CONFIRM_PATTERNS = re.compile(
    r"^\s*(ok|oke|ừ|ờ|đúng|đồng ý|xác nhận|yes|có|được|chuẩn|tiếp tục|làm đi|gửi đi|ok luôn)"
    r"(\s+(chuyển|chuyển đi|luôn|đi|rồi))?\s*[.!]?\s*$",
    re.IGNORECASE,
)
_CONFIRM_EXACT = {
    "chuyển đi", "chuyển luôn", "chuyển đi đi", "ok chuyển đi",
    "ừ chuyển đi", "oke chuyển đi", "đúng rồi", "đúng rồi chuyển đi",
}
_CANCEL_PATTERNS = re.compile(
    r"^\s*(không|hủy|thôi|dừng|cancel|bỏ|bỏ đi|không chuyển|hủy giao dịch)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def _rule_based_classify(message: str) -> str | None:
    """Quick rule-based classification for unambiguous messages.

    Returns classification string or None if LLM should decide.
    """
    msg = message.strip().lower().rstrip(".!")
    if msg in _CONFIRM_EXACT or _CONFIRM_PATTERNS.match(message):
        return "CONFIRM"
    if _CANCEL_PATTERNS.match(message):
        return "CANCEL"
    return None


async def classify_confirmation(message: str, draft_summary: str | None = None) -> dict:
    """Classify user's response to a transaction confirmation prompt.

    Returns: {"classification": "CONFIRM|CANCEL|MODIFY|UNCLEAR", "reason": "..."}
    """
    # Fast rule-based check for unambiguous patterns
    rule_result = _rule_based_classify(message)
    if rule_result:
        logger.info(f"[CLASSIFIER] Rule-based: {rule_result} for '{message}'")
        return {"classification": rule_result, "reason": "rule_based_match"}

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
        return {"classification": classification, "reason": data.get("reason", "")}
    except Exception as e:
        logger.error(f"[CLASSIFIER] Error: {e}", exc_info=True)
        return {"classification": "UNCLEAR", "reason": f"classifier_error: {e}"}
