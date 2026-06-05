"""Bill Payment Agent — LangGraph implementation with tool-calling."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.bill_tools import BILL_TOOLS
from backend.prompts.bill_payment import BILL_PAYMENT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


def create_bill_agent():
    """Create the bill payment agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.0,
    )

    agent = create_react_agent(
        model=llm,
        tools=BILL_TOOLS,
        prompt=SystemMessage(content=BILL_PAYMENT_SYSTEM_PROMPT),
    )
    return agent


async def run_bill_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the bill payment agent and return structured output."""
    agent = create_bill_agent()

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
            trace_name="bill_agent",
        )
        config.setdefault("recursion_limit", 25)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = ""

        return _parse_bill_output(raw_content)

    except Exception as e:
        logger.error(f"[BILL AGENT] Error: {e}", exc_info=True)
        return {
            "status": "clarification_needed",
            "message": "Xin lỗi, tôi không thể xử lý yêu cầu thanh toán hóa đơn lúc này.",
            "data": {"error": str(e)},
        }


def _parse_bill_output(raw: str) -> dict:
    """Parse bill agent output."""
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
            return {
                "status": "draft_ready",
                "message": data.get("message", f"Xác nhận thanh toán {amount:,.0f} VND?"),
                "data": data,
            }
        elif status == "info_response":
            return {
                "status": "info_response",
                "message": data.get("message", ""),
                "data": data,
            }
        elif status == "needs_clarification":
            return {
                "status": "clarification_needed",
                "message": data.get("message", "Vui lòng cung cấp thêm thông tin."),
                "data": data,
            }
        else:
            return {"status": "info_response", "message": raw, "data": data}
    except (json.JSONDecodeError, TypeError):
        return {"status": "info_response", "message": raw or "Lỗi xử lý.", "data": {}}
