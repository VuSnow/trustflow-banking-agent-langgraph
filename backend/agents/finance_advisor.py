"""Finance Advisor Agent — LangGraph implementation with analysis tools."""
from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.finance_tools import FINANCE_TOOLS
from backend.prompts.finance_advisor import get_finance_advisor_prompt
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)


def create_finance_agent():
    """Create the finance advisor agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.3,
    )

    agent = create_react_agent(
        model=llm,
        tools=FINANCE_TOOLS,
        prompt=SystemMessage(content=get_finance_advisor_prompt()),
    )
    return agent


async def run_finance_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the finance advisor agent and return natural language advice."""
    agent = create_finance_agent()

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
            trace_name="finance_advisor",
        )
        config.setdefault("recursion_limit", 15)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = "Xin lỗi, không thể phân tích tài chính lúc này."

        return {
            "status": "info_response",
            "message": raw_content,
            "data": {"task_type": "FINANCE_ADVICE"},
        }

    except Exception as e:
        logger.error(f"[FINANCE AGENT] Error: {e}", exc_info=True)
        return {
            "status": "info_response",
            "message": "Xin lỗi, tôi không thể phân tích chi tiêu lúc này. Vui lòng thử lại.",
            "data": {"error": str(e)},
        }
