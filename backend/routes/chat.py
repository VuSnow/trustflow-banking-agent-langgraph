"""FastAPI chat routes — integrates with LangGraph orchestrator."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from backend.graphs.orchestrator import compile_orchestrator
from backend.services.chat_session_store import ChatSessionStore
from backend.services.audit_log import write_audit_log
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Module-level state
chat_session_store: ChatSessionStore = None
orchestrator_graph = None


def init(store: ChatSessionStore):
    global chat_session_store, orchestrator_graph
    chat_session_store = store
    orchestrator_graph = compile_orchestrator()


# ─── Request/Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str


class ChatResponse(BaseModel):
    status: str
    message: str
    data: dict | None = None
    pending_action_id: str | None = None
    risk_tier: str | None = None
    auth_required: str | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    logger.info(f"[RECEIVED] user={request.user_id} msg={request.message}")

    # Ensure session exists
    try:
        chat_session_store.ensure_session(request.user_id, request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # Save user message
    chat_session_store.add_message(
        session_id=request.session_id,
        user_id=request.user_id,
        role="user",
        message=request.message,
    )

    # Build graph input — with checkpointing, we only need to send the new message.
    # The checkpointer restores full state (fsm_state, pending_draft, etc.) from thread_id.
    graph_input = {
        "messages": [HumanMessage(content=request.message)],
        "user_id": request.user_id,
        "session_id": request.session_id,
        "intent": "",
        "operation": None,
        "confidence": 0.0,
        "response_status": "",
        "response_message": "",
        "response_data": {},
        "fsm_state": "idle",
        "pending_draft": None,
        "pipeline_step": 0,
        "pipeline_results": [],
    }

    # Run the graph with thread_id for checkpointing
    try:
        config = get_trace_config(
            session_id=request.session_id,
            user_id=request.user_id,
            trace_name="orchestrator",
        )
        # thread_id enables checkpoint-based state persistence
        config.setdefault("configurable", {})
        config["configurable"]["thread_id"] = request.session_id
        config.setdefault("recursion_limit", 50)

        result = await orchestrator_graph.ainvoke(graph_input, config=config)
    except Exception as e:
        logger.error(f"[GRAPH] Error: {e}", exc_info=True)
        response = ChatResponse(
            status="error",
            message="Xin lỗi, đã xảy ra lỗi. Vui lòng thử lại.",
        )
        _save_response(request, response)
        return response

    # Extract response from graph state
    response_status = result.get("response_status", "info_response")
    response_message = result.get("response_message", "")
    response_data = result.get("response_data", {})
    new_fsm_state = result.get("fsm_state", "idle")

    # Map to API response
    risk_tier = None
    auth_required = None
    if response_status == "blocked":
        risk_tier = "RED"
    elif new_fsm_state == "waiting_otp":
        auth_required = "otp"
    elif new_fsm_state == "waiting_confirmation":
        auth_required = "confirm"

    response = ChatResponse(
        status=response_status,
        message=response_message,
        data=response_data if response_data else None,
        risk_tier=risk_tier,
        auth_required=auth_required,
    )

    _save_response(request, response)
    return response


def _save_response(request: ChatRequest, response: ChatResponse):
    """Save assistant response to chat history."""
    chat_session_store.add_message(
        session_id=request.session_id,
        user_id=request.user_id,
        role="assistant",
        message=response.message,
        data=response.model_dump(),
    )
