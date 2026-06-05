"""Langfuse tracing integration for LangChain/LangGraph.

Langfuse 4.x reads config from environment variables:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

The CallbackHandler auto-reads these env vars.
"""
from __future__ import annotations

import os
import logging

from backend.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

logger = logging.getLogger(__name__)

_initialized = False


def _ensure_env():
    """Ensure Langfuse env vars are set for the SDK to pick up."""
    global _initialized
    if _initialized:
        return
    if LANGFUSE_PUBLIC_KEY:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", LANGFUSE_PUBLIC_KEY)
    if LANGFUSE_SECRET_KEY:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", LANGFUSE_SECRET_KEY)
    if LANGFUSE_HOST:
        os.environ.setdefault("LANGFUSE_HOST", LANGFUSE_HOST)
    _initialized = True


def get_langfuse_handler():
    """Get a Langfuse CallbackHandler. Returns None if not configured."""
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None

    _ensure_env()

    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:
        logger.warning(f"[LANGFUSE] Failed to init: {e}")
        return None


def get_trace_config(
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str = "chat",
) -> dict:
    """Build a LangChain RunnableConfig with Langfuse callback.

    Returns empty dict if Langfuse is not configured.
    """
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return {}

    _ensure_env()

    try:
        from langfuse.langchain import CallbackHandler
        handler = CallbackHandler(
            trace_context={
                "name": trace_name,
                "session_id": session_id,
                "user_id": user_id,
            }
        )
        return {
            "callbacks": [handler],
            "recursion_limit": 50,
        }
    except Exception as e:
        logger.warning(f"[LANGFUSE] Failed to create trace config: {e}")
        return {}
