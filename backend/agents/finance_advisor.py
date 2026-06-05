"""Finance Advisor Agent — LangGraph implementation with analysis tools and memory."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.finance_tools import FINANCE_TOOLS
from backend.prompts.finance_advisor import get_finance_advisor_prompt
from backend.services.langfuse_trace import get_trace_config
from backend.services.agent_memory import AgentMemoryStore

logger = logging.getLogger(__name__)

memory_store = AgentMemoryStore()


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
    """Run the finance advisor agent with memory context injection."""
    agent = create_finance_agent()

    # Load previous finance memory for context
    finance_memory = memory_store.get_domain(user_id, "finance", session_id=session_id)

    messages = []

    # Inject memory context if available
    if finance_memory:
        memory_text = "Previous finance context (use to avoid re-querying):\n"
        for key, value in finance_memory.items():
            memory_text += f"- {key}: {json.dumps(value, ensure_ascii=False, default=str)}\n"
        messages.append(SystemMessage(content=memory_text))

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
        config.setdefault("recursion_limit", 20)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = "Xin lỗi, không thể phân tích tài chính lúc này."

        # Save key insights to memory for follow-up questions
        _save_memory_from_response(user_id, session_id, message, raw_content, result)

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


def _save_memory_from_response(
    user_id: str, session_id: str, question: str, response: str, result: dict
) -> None:
    """Extract and save useful context from agent response to memory.

    Saves a compact summary — not the full response text.
    """
    try:
        # Extract tool results from messages for memory
        tool_summaries = []
        for msg in result.get("messages", []):
            if hasattr(msg, "type") and msg.type == "tool":
                content = msg.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if isinstance(content, dict) and content.get("status") == "success":
                    tool_summaries.append({
                        "tool": msg.name if hasattr(msg, "name") else "unknown",
                        "result_summary": _compact_tool_result(content),
                    })

        if tool_summaries:
            memory_store.save(
                user_id=user_id,
                domain="finance",
                memory_key="last_analysis",
                memory_value={
                    "question": question[:200],
                    "tool_results": tool_summaries[:5],  # cap at 5
                },
                session_id=session_id,
                ttl_hours=2,  # expire after 2 hours
            )
    except Exception as e:
        logger.warning(f"[FINANCE] Failed to save memory: {e}")


def _compact_tool_result(result: dict) -> dict:
    """Compact a tool result to save space in memory. Keep only key metrics."""
    compact = {}
    # Keep scalar values and small lists
    for key, value in result.items():
        if key in ("status", "sql"):
            continue
        if isinstance(value, (int, float, str, bool)):
            compact[key] = value
        elif isinstance(value, list) and len(value) <= 10:
            compact[key] = value
        elif isinstance(value, dict):
            compact[key] = value
    return compact
