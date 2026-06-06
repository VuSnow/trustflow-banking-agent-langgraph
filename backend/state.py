"""State definitions for LangGraph graphs.

All graph state is defined as TypedDict with Annotated fields for
LangGraph's state management and checkpointing.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


# ─── Chat-level state (top-level graph) ──────────────────────────────────────

class ChatState(TypedDict):
    """Top-level state for the main orchestration graph."""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    # Orchestrator output
    intent: str  # QA, TRANSACTION, DATA_QUERY, etc.
    operation: str | None
    confidence: float
    # Domain agent output
    response_status: str  # draft_ready, clarification_needed, info_response
    response_message: str
    response_data: dict[str, Any]
    # FSM state
    fsm_state: str  # idle, waiting_confirmation, waiting_otp, executed, waiting_category_confirm
    pending_draft: dict[str, Any] | None
    # Pipeline
    pipeline_step: int
    pipeline_results: list[dict[str, Any]]


# ─── Transaction agent state ─────────────────────────────────────────────────

class TransactionState(TypedDict):
    """State for the transaction agent subgraph."""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    # Resolution results
    draft: dict[str, Any] | None
    fraud_screening: dict[str, Any] | None
    verification: dict[str, Any] | None
    # Final output
    status: str
    output_message: str
    output_data: dict[str, Any]


# ─── Card operation state ─────────────────────────────────────────────────────

class CardOperationState(TypedDict):
    """State for the card operation agent subgraph."""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    draft: dict[str, Any] | None
    status: str
    output_message: str
    output_data: dict[str, Any]


# ─── Guardrail result ─────────────────────────────────────────────────────────

class GuardrailResult(TypedDict):
    allowed: bool
    requires_otp: bool
    blocked: bool
    warning_message: str | None
    reason: str | None
    risk_level: str | None  # LOW, MEDIUM, HIGH, BLOCK
