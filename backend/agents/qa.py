"""QA Agent — LangGraph ReAct implementation with LightRAG retrieval."""
from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.qa import QA_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config
from backend.tools.qa_tools import QA_TOOLS

logger = logging.getLogger(__name__)


def create_qa_agent():
    """Create the QA ReAct agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.2,
    )

    return create_react_agent(
        model=llm,
        tools=QA_TOOLS,
        prompt=SystemMessage(content=QA_SYSTEM_PROMPT),
    )


async def run_qa_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run QA agent and return a chat-compatible response."""
    agent = create_qa_agent()

    messages = []
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
            trace_name="qa_agent",
        )
        config.setdefault("recursion_limit", 25)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            answer = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            answer = ""

        return {
            "status": "info_response",
            "message": answer.strip() or "Tôi có thể hỗ trợ các câu hỏi về ngân hàng. Bạn muốn hỏi gì?",
            "data": {"task_type": "QA", "mode": "lightrag_react"},
        }
    except Exception as e:
        logger.warning(f"[QA] agent failed: {e}", exc_info=True)
        return {
            "status": "info_response",
            "message": "Tôi có thể hỗ trợ các câu hỏi về ngân hàng. Bạn muốn hỏi gì?",
            "data": {"task_type": "QA", "mode": "fallback"},
        }
