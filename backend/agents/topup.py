"""Top-Up Agent — LangGraph implementation (no tools needed, pure LLM extraction)."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.topup import TOPUP_AGENT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


async def run_topup_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the top-up agent.

    Top-up is simple extraction — no tools needed. LLM extracts phone + amount
    from user message and validates format.
    """
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)

    messages = [SystemMessage(content=TOPUP_AGENT_SYSTEM_PROMPT)]

    if history:
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("message", "")
            if role == "user" and content:
                messages.append(HumanMessage(content=content))
            elif role == "assistant" and content:
                messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=message))

    try:
        config = get_trace_config(
            session_id=session_id,
            user_id=user_id,
            trace_name="topup_agent",
        )

        response = await llm.ainvoke(messages, config=config)
        raw = response.content.strip()
        return _parse_topup_output(raw)

    except Exception as e:
        logger.error(f"[TOPUP AGENT] Error: {e}", exc_info=True)
        return {
            "status": "clarification_needed",
            "message": "Xin lỗi, tôi không thể xử lý yêu cầu nạp tiền lúc này.",
            "data": {"error": str(e)},
        }


def _parse_topup_output(raw: str) -> dict:
    """Parse top-up agent output."""
    try:
        content = raw.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        data = json.loads(content)
        status = data.get("status", "")

        if status == "draft_created":
            amount = data.get("amount", 0)
            target = data.get("topup_target", "")
            provider = data.get("topup_provider", "")
            return {
                "status": "draft_ready",
                "message": data.get("message", f"Xác nhận nạp {amount:,.0f} VND cho {target} ({provider})?"),
                "data": data,
            }
        elif status == "needs_clarification":
            return {
                "status": "clarification_needed",
                "message": data.get("message", "Vui lòng cung cấp thêm thông tin."),
                "data": data,
            }
        elif status == "cancelled":
            return {
                "status": "info_response",
                "message": data.get("message", "Đã hủy nạp tiền."),
                "data": {},
            }
        else:
            return {"status": "info_response", "message": raw, "data": data}
    except (json.JSONDecodeError, TypeError):
        return {"status": "clarification_needed", "message": raw or "Lỗi xử lý.", "data": {}}
