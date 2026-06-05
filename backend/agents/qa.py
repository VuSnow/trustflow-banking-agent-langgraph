"""QA Agent — simple LLM call, no tools needed."""
from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.qa import QA_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def run_qa_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run QA agent — direct LLM response, no tools."""
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.2)

    try:
        response = await llm.ainvoke([
            SystemMessage(content=QA_SYSTEM_PROMPT),
            HumanMessage(content=message),
        ])
        answer = response.content.strip()
        return {
            "status": "info_response",
            "message": answer,
            "data": {"task_type": "QA", "mode": "llm"},
        }
    except Exception as e:
        logger.warning(f"[QA] LLM failed: {e}")
        return {
            "status": "info_response",
            "message": "Tôi có thể hỗ trợ các câu hỏi về ngân hàng. Bạn muốn hỏi gì?",
            "data": {"task_type": "QA", "mode": "fallback"},
        }
