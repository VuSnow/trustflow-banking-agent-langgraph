"""Transaction Agent — LangGraph implementation with tool-calling.

Uses LangGraph's create_react_agent pattern for the ReAct loop,
replacing the manual iteration loop from the original implementation.
"""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.transaction_tools import TRANSACTION_TOOLS
from backend.prompts.transaction import TRANSACTION_AGENT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


def create_transaction_agent():
    """Create the transaction agent graph using LangGraph's prebuilt ReAct agent."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.0,
    )

    agent = create_react_agent(
        model=llm,
        tools=TRANSACTION_TOOLS,
        prompt=SystemMessage(content=TRANSACTION_AGENT_SYSTEM_PROMPT),
    )
    return agent


async def run_transaction_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the transaction agent and return structured output.

    Returns:
        dict with keys: status, message, data
    """
    agent = create_transaction_agent()

    # Build messages from history
    messages = []
    if history:
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("message", "")
            if role == "user" and content:
                messages.append(HumanMessage(content=content))
            elif role == "assistant" and content:
                messages.append(AIMessage(content=content))

    # Current message with user context injected
    user_msg = f"[User cif_no: {user_id}]\n\n{message}"
    messages.append(HumanMessage(content=user_msg))

    try:
        config = get_trace_config(
            session_id=session_id,
            user_id=user_id,
            trace_name="transaction_agent",
        )
        config.setdefault("recursion_limit", 25)
        result = await agent.ainvoke({"messages": messages}, config=config)
        # Extract final AI message
        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = ""

        return _parse_agent_output(raw_content)

    except Exception as e:
        logger.error(f"[TX AGENT] Error: {e}", exc_info=True)
        error_msg = str(e)
        if "recursion" in error_msg.lower():
            msg = "Xin lỗi, yêu cầu này quá phức tạp. Vui lòng cung cấp thêm thông tin (số tài khoản, ngân hàng)."
        else:
            msg = "Xin lỗi, tôi không thể xử lý yêu cầu này lúc này. Vui lòng thử lại."
        return {
            "status": "clarification_needed",
            "message": msg,
            "data": {"error": error_msg},
        }


def _parse_agent_output(raw: str) -> dict:
    """Parse the agent's final response into structured output."""
    try:
        # Strip markdown fences if present
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
                "message": _format_draft_message(data),
                "data": data,
            }
        elif status == "needs_clarification":
            return {
                "status": "clarification_needed",
                "message": data.get("message", "Vui lòng cung cấp thêm thông tin."),
                "data": data,
            }
        elif status == "needs_confirmation":
            return {
                "status": "clarification_needed",
                "message": data.get("message", "Vui lòng xác nhận."),
                "data": data,
            }
        elif status == "cancelled":
            return {
                "status": "info_response",
                "message": data.get("message", "Đã hủy giao dịch."),
                "data": {"operation": "TRANSACTION_CANCELLED"},
            }
        else:
            return {
                "status": "info_response",
                "message": data.get("message", raw),
                "data": data,
            }
    except (json.JSONDecodeError, TypeError):
        # LLM returned free text
        return {
            "status": "clarification_needed",
            "message": raw or "Vui lòng cung cấp thêm thông tin.",
            "data": {},
        }


def _format_draft_message(data: dict) -> str:
    """Format a human-readable draft confirmation message."""
    amount = data.get("amount", 0)
    recipient = data.get("recipient_name", "?")
    account = data.get("account_no", "?")
    bank = data.get("bank_name") or data.get("bank_code", "?")
    note = data.get("note", "")

    msg = (
        f"Xác nhận chuyển {amount:,.0f} VND cho {recipient} "
        f"({account}) tại {bank}."
    )
    if note:
        msg += f"\nNội dung: {note}"
    return msg
