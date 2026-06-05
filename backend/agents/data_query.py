"""Data Query Agent — delegates NL questions to text2sql-agent service."""
from __future__ import annotations

import logging

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import OPENAI_API_KEY, OPENAI_MODEL, TEXT2SQL_AGENT_URL

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """You are a helpful Vietnamese banking assistant.
Given the user's original question and the raw query results, provide a clear,
concise natural language answer in Vietnamese. Format numbers nicely.
If the data is empty, say you couldn't find matching data.
Do not mention SQL or database internals."""


async def run_data_query_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run data query via text2sql-agent and summarize results."""
    question = f"Với customer có cif_no = '{user_id}': {message}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TEXT2SQL_AGENT_URL}/query/execute",
                json={"question": question, "execute": True},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return {
            "status": "info_response",
            "message": f"Xin lỗi, không thể truy vấn dữ liệu (HTTP {e.response.status_code}).",
            "data": {"error": str(e)},
        }
    except httpx.RequestError as e:
        return {
            "status": "info_response",
            "message": "Xin lỗi, dịch vụ truy vấn đang không khả dụng.",
            "data": {"error": str(e)},
        }

    status = data.get("status")

    if status == "needs_clarification":
        questions = data.get("questions", ["Bạn có thể mô tả rõ hơn được không?"])
        return {
            "status": "clarification_needed",
            "message": "\n".join(f"- {q}" for q in questions),
            "data": {"questions": questions},
        }

    if status != "success":
        return {
            "status": "info_response",
            "message": f"Xin lỗi, không thể lấy dữ liệu: {data.get('error', 'Unknown error')}",
            "data": data,
        }

    # Summarize results with LLM
    results = data.get("results", [])
    sql = data.get("sql", "")

    summary = await _summarize_results(message, results)

    return {
        "status": "info_response",
        "message": summary,
        "data": {
            "task_type": "DATA_QUERY",
            "sql": sql,
            "results": results,
            "row_count": len(results),
        },
    }


async def _summarize_results(question: str, results: list) -> str:
    """Use LLM to create a natural language summary of query results."""
    if not results:
        return "Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn."

    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.2)
    try:
        import json
        results_str = json.dumps(results[:20], ensure_ascii=False, default=str)
        response = await llm.ainvoke([
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=f"Question: {question}\n\nResults:\n{results_str}"),
        ])
        return response.content.strip()
    except Exception as e:
        logger.warning(f"[DATA_QUERY] Summarization failed: {e}")
        # Fallback: return raw count
        return f"Tìm thấy {len(results)} kết quả."
