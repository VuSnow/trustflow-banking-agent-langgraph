"""LightRAG tools for knowledge-base QA."""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from langchain_core.tools import tool

from backend.config import LIGHTRAG_SERVICE_URL

logger = logging.getLogger(__name__)

LIGHTRAG_CHUNK_TOP_K = 10
LIGHTRAG_KG_TOP_K = 25


@tool
async def query_lightrag(
    question: str,
    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = "mix",
    include_references: bool = True,
) -> dict:
    """Query the LightRAG knowledge base for banking QA information.

    Use this for policy, product, fee, interest-rate, process, and general
    banking knowledge questions. Ask one focused natural-language question at a
    time. If the user question has multiple parts, call this tool multiple
    times with narrower questions and combine the results.

    Args:
        question: Focused question to ask the LightRAG service.
        mode: LightRAG retrieval mode. Use "mix" by default.
        include_references: Whether to return source references.
    """
    if not question or len(question.strip()) < 3:
        return {"status": "failed", "message": "question must be at least 3 characters."}

    base_url = LIGHTRAG_SERVICE_URL.rstrip("/")
    payload = {
        "query": question.strip(),
        "mode": mode,
        "chunk_top_k": LIGHTRAG_CHUNK_TOP_K,
        "kg_top_k": LIGHTRAG_KG_TOP_K,
        "include_references": include_references,
        "include_chunk_content": False,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(f"{base_url}/query", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("[LightRAG] HTTP error: %s", exc)
        return {
            "status": "failed",
            "message": f"LightRAG returned HTTP {exc.response.status_code}.",
        }
    except httpx.RequestError as exc:
        logger.warning("[LightRAG] connection error: %s", exc)
        return {"status": "failed", "message": f"Cannot reach LightRAG service: {exc}"}
    except ValueError as exc:
        logger.warning("[LightRAG] invalid JSON response: %s", exc)
        return {"status": "failed", "message": "LightRAG returned an invalid JSON response."}

    answer = data.get("response", "")
    references = data.get("references") or []
    if not answer:
        return {
            "status": "not_found",
            "answer": "",
            "references": references,
            "message": "No relevant context found for the query.",
        }

    return {
        "status": "success",
        "answer": answer,
        "references": references,
        "mode": mode,
        "chunk_top_k": LIGHTRAG_CHUNK_TOP_K,
        "kg_top_k": LIGHTRAG_KG_TOP_K,
    }


QA_TOOLS = [query_lightrag]