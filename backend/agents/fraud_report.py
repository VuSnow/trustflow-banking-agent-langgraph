"""Fraud Report Agent — LangGraph implementation with tool-calling."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.transaction_tools import check_fraud_risk, text2sql_query
from backend.prompts.fraud_report import FRAUD_REPORT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)

FRAUD_TOOLS = [check_fraud_risk, text2sql_query]


def create_fraud_agent():
    """Create the fraud report agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.0,
    )

    agent = create_react_agent(
        model=llm,
        tools=FRAUD_TOOLS,
        prompt=SystemMessage(content=FRAUD_REPORT_SYSTEM_PROMPT),
    )
    return agent


async def run_fraud_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the fraud report agent and return structured output."""
    agent = create_fraud_agent()

    messages = []
    if history:
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("message", "")
            if role == "user" and content:
                messages.append(HumanMessage(content=content))
            elif role == "assistant" and content:
                messages.append(AIMessage(content=content))

    user_msg = f"[User cif_no: {user_id}]\n\n{message}"
    messages.append(HumanMessage(content=user_msg))

    try:
        config = get_trace_config(
            session_id=session_id,
            user_id=user_id,
            trace_name="fraud_agent",
        )
        config.setdefault("recursion_limit", 25)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = ""

        return _parse_fraud_output(raw_content)

    except Exception as e:
        logger.error(f"[FRAUD AGENT] Error: {e}", exc_info=True)
        return {
            "status": "clarification_needed",
            "message": "Xin lỗi, tôi không thể xử lý yêu cầu lúc này.",
            "data": {"error": str(e)},
        }


def _parse_fraud_output(raw: str) -> dict:
    """Parse fraud agent output."""
    try:
        content = raw.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        data = json.loads(content)
        status = data.get("status", "")

        if status == "draft_created":
            return {
                "status": "draft_ready",
                "message": data.get("message", "Xác nhận gửi báo cáo lừa đảo?"),
                "data": data,
            }
        elif status == "info_response":
            return {
                "status": "info_response",
                "message": data.get("message", ""),
                "data": data.get("data", data),
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
                "message": data.get("message", "Đã hủy."),
                "data": {},
            }
        else:
            return {"status": "info_response", "message": raw, "data": data}
    except (json.JSONDecodeError, TypeError):
        # LLM returned free text — likely a natural language response
        return {"status": "info_response", "message": raw or "Lỗi xử lý.", "data": {}}
