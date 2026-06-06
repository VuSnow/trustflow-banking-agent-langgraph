"""FastAPI chat routes — integrates with LangGraph orchestrator."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from backend.graphs.orchestrator import compile_orchestrator, get_checkpointer
from backend.models.flow import deserialize_flow
from backend.services.chat_session_store import ChatSessionStore
from backend.services.audit_log import write_audit_log
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Module-level state
chat_session_store: ChatSessionStore = None
orchestrator_graph = None


def init(store: ChatSessionStore):
    global chat_session_store
    chat_session_store = store
    # Graph compiled lazily on first request (needs async for PostgresSaver)


async def _get_graph():
    """Lazy-initialize orchestrator graph with async checkpointer."""
    global orchestrator_graph
    if orchestrator_graph is None:
        orchestrator_graph = await compile_orchestrator()
    return orchestrator_graph


# ─── Request/Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str


class ChatResponse(BaseModel):
    status: str
    message: str
    data: dict | None = None
    flow_status: str | None = None
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

    # Restore active_flow from checkpoint
    checkpointer = await get_checkpointer()

    active_flow = None
    thread_config = {"configurable": {"thread_id": request.session_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(thread_config)
        if checkpoint_tuple and checkpoint_tuple.checkpoint.get("channel_values"):
            active_flow = checkpoint_tuple.checkpoint["channel_values"].get("active_flow")
    except Exception:
        pass

    graph_input = {
        "messages": [HumanMessage(content=request.message)],
        "user_id": request.user_id,
        "session_id": request.session_id,
        "active_flow": active_flow,
        "route_decision": None,
        "response_message": "",
        "response_data": {},
    }

    # Run the graph with thread_id for checkpointing
    try:
        config = get_trace_config(
            session_id=request.session_id,
            user_id=request.user_id,
            trace_name="orchestrator",
        )
        config.setdefault("configurable", {})
        config["configurable"]["thread_id"] = request.session_id
        config.setdefault("recursion_limit", 25)

        graph = await _get_graph()
        result = await graph.ainvoke(graph_input, config=config)
    except Exception as e:
        logger.error(f"[GRAPH] Error: {e}", exc_info=True)
        response = ChatResponse(
            status="error",
            message="Xin lỗi, đã xảy ra lỗi. Vui lòng thử lại.",
        )
        _save_response(request, response)
        return response

    # Extract response from graph state
    response_message = result.get("response_message", "")
    response_data = result.get("response_data", {})
    result_flow = deserialize_flow(result.get("active_flow"))

    # Determine status and auth_required from flow state
    flow_status = None
    auth_required = None
    status = "success"

    if result_flow:
        flow_status = result_flow.status
        if result_flow.status == "WAITING_OTP":
            auth_required = "otp"
        elif result_flow.status in ("WAITING_RECIPIENT_CONFIRMATION", "WAITING_DRAFT_CONFIRMATION"):
            auth_required = "confirm"
        elif result_flow.status == "COLLECTING":
            status = "collecting"
    else:
        status = "completed" if response_data.get("executed") else "success"

    response = ChatResponse(
        status=status,
        message=response_message,
        data=response_data if response_data else None,
        flow_status=flow_status,
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
