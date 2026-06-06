"""State definitions for LangGraph graphs.

All graph state is defined as TypedDict with Annotated fields for
LangGraph's state management and checkpointing.
"""
from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


# ─── Chat-level state (top-level graph) ──────────────────────────────────────

class ChatState(TypedDict):
    """Top-level state for the main orchestration graph.

    Key design:
    - active_flow: serialized FlowState (the ONLY source of truth for flow control)
    - route_decision: per-turn routing output from FlowRouter
    - response_message / response_data: per-turn output for chat response
    """

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str

    # Flow control — serialized FlowState (LangGraph needs JSON-serializable)
    active_flow: dict | None

    # Per-turn routing output — serialized RouteDecision
    route_decision: dict | None

    # Per-turn response output
    response_message: str
    response_data: dict[str, Any]
