"""FastAPI chat routes — integrates with LangGraph orchestrator."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from backend.graphs.orchestrator import compile_orchestrator
from backend.services.chat_session_store import ChatSessionStore
from backend.services.langfuse_trace import get_trace_config
from backend.services.task_router import (
    CANCEL_ACTIVE_TASK,
    CLARIFY_TASK_SWITCH,
    DISMISS_RESUME_PROMPT,
    RESUME_ACTIVE_TASK,
    RESUME_OLD_TASK,
    SWITCH_TO_NEW_TASK,
    route_task_turn,
)
from backend.services.task_store import TaskStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Module-level state
chat_session_store: ChatSessionStore = None
task_store: TaskStore = None
orchestrator_graph = None


def init(store: ChatSessionStore, tasks: TaskStore | None = None):
    global chat_session_store, task_store, orchestrator_graph
    chat_session_store = store
    task_store = tasks or TaskStore()
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
    active_task_id: str | None = None
    active_task_type: str | None = None
    active_task_lifecycle: str | None = None
    suspended_tasks: list[dict] | None = None
    unfinished_tasks: list[dict] | None = None
    resume_prompt: bool = False
    task_switch: dict | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    logger.info(f"[RECEIVED] user={request.user_id} msg={request.message}")

    # Ensure session exists
    try:
        chat_session_store.ensure_session(request.user_id, request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    logger.debug("[CHAT] session ensured session_id=%s user_id=%s", request.session_id, request.user_id)

    # Save user message
    chat_session_store.add_message(
        session_id=request.session_id,
        user_id=request.user_id,
        role="user",
        message=request.message,
    )
    logger.debug("[CHAT] user_message_saved session_id=%s message_len=%d", request.session_id, len(request.message or ""))

    active_task = task_store.get_active_task(request.session_id)
    unfinished_before = task_store.list_unfinished_tasks(
        request.session_id,
        exclude_task_id=active_task["task_id"] if active_task else None,
    )
    logger.debug(
        "[TASK] loaded active_task_id=%s active_type=%s active_operation=%s fsm_state=%s unfinished_count=%d",
        active_task.get("task_id") if active_task else None,
        active_task.get("task_type") if active_task else None,
        active_task.get("operation") if active_task else None,
        active_task.get("fsm_state") if active_task else None,
        len(unfinished_before),
    )
    decision = await route_task_turn(
        message=request.message,
        active_task=active_task,
        unfinished_tasks=unfinished_before,
    )
    logger.debug("[TASK] route_decision=%s", decision.model_dump())

    if decision.action == CLARIFY_TASK_SWITCH:
        logger.debug("[TASK] clarify_switch active_task_id=%s", active_task.get("task_id") if active_task else None)
        response = _task_response(
            request=request,
            status="clarification_needed",
            message=decision.message or "Bạn muốn tiếp tục tác vụ hiện tại hay chuyển sang yêu cầu mới?",
            active_task=active_task,
            task_switch=decision.model_dump(),
        )
        _save_response(request, response)
        return response

    task_switch = None
    current_task = active_task

    if decision.action == CANCEL_ACTIVE_TASK and active_task:
        task_store.cancel_task(active_task["task_id"])
        task_store.set_active_task(request.session_id, None)
        unfinished = task_store.list_unfinished_tasks(request.session_id)
        logger.debug(
            "[TASK] cancelled active_task_id=%s unfinished_count=%d",
            active_task["task_id"],
            len(unfinished),
        )
        message = "Đã hủy tác vụ hiện tại."
        message = _append_resume_prompt(message, unfinished)
        response = _task_response(
            request=request,
            status="info_response",
            message=message,
            unfinished_tasks=unfinished,
            resume_prompt=bool(unfinished),
            task_switch=decision.model_dump(),
        )
        _save_response(request, response)
        return response

    if decision.action == DISMISS_RESUME_PROMPT:
        task_store.set_active_task(request.session_id, None)
        logger.debug("[TASK] dismissed_resume_prompt session_id=%s", request.session_id)
        response = _task_response(
            request=request,
            status="info_response",
            message="Đã giữ các tác vụ chưa hoàn tất ở trạng thái tạm dừng.",
            unfinished_tasks=task_store.list_unfinished_tasks(request.session_id),
            task_switch=decision.model_dump(),
        )
        _save_response(request, response)
        return response

    if decision.action == RESUME_OLD_TASK and decision.task_id:
        if active_task and active_task["task_id"] != decision.task_id:
            task_store.suspend_task(active_task["task_id"])
            logger.debug(
                "[TASK] suspended_previous_for_resume previous_task_id=%s resume_task_id=%s",
                active_task["task_id"],
                decision.task_id,
            )
        current_task = task_store.resume_task(request.session_id, decision.task_id) or task_store.get_task(decision.task_id)
        if current_task:
            task_store.set_active_task(request.session_id, current_task["task_id"])
        logger.debug(
            "[TASK] resumed_old task_id=%s found=%s fsm_state=%s",
            decision.task_id,
            bool(current_task),
            current_task.get("fsm_state") if current_task else None,
        )
        task_switch = decision.model_dump()
        response = _task_response(
            request=request,
            status="info_response",
            message=_resume_task_message(current_task),
            active_task=current_task,
            task_switch=task_switch,
        )
        _save_response(request, response)
        return response

    elif decision.action == SWITCH_TO_NEW_TASK:
        if active_task:
            task_store.suspend_task(active_task["task_id"])
            logger.debug("[TASK] suspended_active_for_switch task_id=%s", active_task["task_id"])
        current_task = task_store.create_task(
            session_id=request.session_id,
            user_id=request.user_id,
            task_type=decision.task_type or "UNKNOWN",
            operation=decision.operation,
            last_user_message=request.message,
        )
        logger.debug(
            "[TASK] switched_to_new task_id=%s task_type=%s operation=%s",
            current_task.get("task_id") if current_task else None,
            current_task.get("task_type") if current_task else decision.task_type,
            current_task.get("operation") if current_task else decision.operation,
        )
        task_switch = decision.model_dump()

    elif decision.action == RESUME_ACTIVE_TASK and active_task:
        current_task = active_task
        logger.debug("[TASK] resume_active task_id=%s fsm_state=%s", current_task["task_id"], current_task.get("fsm_state"))

    if not current_task:
        current_task = task_store.create_task(
            session_id=request.session_id,
            user_id=request.user_id,
            task_type=decision.task_type or "UNKNOWN",
            operation=decision.operation,
            last_user_message=request.message,
        )
        logger.debug(
            "[TASK] created_fallback task_id=%s task_type=%s operation=%s",
            current_task.get("task_id") if current_task else None,
            current_task.get("task_type") if current_task else decision.task_type,
            current_task.get("operation") if current_task else decision.operation,
        )

    fsm_state = current_task.get("fsm_state") or "idle"
    pending_draft = current_task.get("pending_draft")

    graph_input = {
        "messages": [HumanMessage(content=request.message)],
        "user_id": request.user_id,
        "session_id": request.session_id,
        "intent": current_task.get("task_type") if current_task.get("task_type") != "UNKNOWN" else "",
        "operation": current_task.get("operation"),
        "confidence": 0.0,
        "response_status": "",
        "response_message": "",
        "response_data": current_task.get("response_data") or {},
        "fsm_state": fsm_state,
        "pending_draft": pending_draft,
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
        config["configurable"]["thread_id"] = current_task["graph_thread_id"]
        config.setdefault("recursion_limit", 50)
        logger.debug(
            "[GRAPH] invoke task_id=%s thread_id=%s fsm_state=%s intent=%s operation=%s has_pending_draft=%s",
            current_task["task_id"],
            current_task["graph_thread_id"],
            fsm_state,
            graph_input["intent"],
            graph_input["operation"],
            bool(pending_draft),
        )

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
    final_intent = result.get("intent") or current_task.get("task_type") or "UNKNOWN"
    final_operation = result.get("operation") or current_task.get("operation")
    final_lifecycle = _infer_lifecycle(response_status, new_fsm_state)
    logger.debug(
        "[GRAPH] result task_id=%s response_status=%s fsm_state=%s final_intent=%s final_operation=%s lifecycle=%s response_data_keys=%s",
        current_task["task_id"],
        response_status,
        new_fsm_state,
        final_intent,
        final_operation,
        final_lifecycle,
        sorted(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
    )

    task_store.update_task_state(
        current_task["task_id"],
        task_type=final_intent or "UNKNOWN",
        operation=final_operation,
        lifecycle=final_lifecycle,
        fsm_state=new_fsm_state or "idle",
        pending_draft=result.get("pending_draft"),
        response_data=response_data,
        last_user_message=request.message,
        last_agent_message=response_message,
    )

    if final_lifecycle in ("completed", "cancelled"):
        task_store.set_active_task(request.session_id, None)
    else:
        task_store.set_active_task(request.session_id, current_task["task_id"])

    # Map to API response
    risk_tier = None
    auth_required = None
    if response_status == "blocked":
        risk_tier = "RED"
    elif new_fsm_state == "waiting_otp":
        auth_required = "otp"
    elif new_fsm_state == "waiting_confirmation":
        auth_required = "confirm"

    unfinished = []
    resume_prompt = False
    if final_lifecycle == "completed":
        unfinished = task_store.list_unfinished_tasks(
            request.session_id,
            exclude_task_id=current_task["task_id"],
        )
        if unfinished:
            response_message = _append_resume_prompt(response_message, unfinished)
            resume_prompt = True
        logger.debug(
            "[TASK] completion_check task_id=%s unfinished_count=%d resume_prompt=%s",
            current_task["task_id"],
            len(unfinished),
            resume_prompt,
        )

    refreshed_task = task_store.get_task(current_task["task_id"])
    response = ChatResponse(
        status=response_status,
        message=response_message,
        data=response_data if response_data else None,
        risk_tier=risk_tier,
        auth_required=auth_required,
        active_task_id=current_task["task_id"] if final_lifecycle == "active" else None,
        active_task_type=refreshed_task.get("task_type") if refreshed_task and final_lifecycle == "active" else None,
        active_task_lifecycle=final_lifecycle if final_lifecycle == "active" else None,
        suspended_tasks=_public_tasks(task_store.list_tasks(request.session_id, lifecycles=("suspended",))),
        unfinished_tasks=_public_tasks(unfinished) if unfinished else None,
        resume_prompt=resume_prompt,
        task_switch=task_switch,
    )

    _save_response(request, response)
    logger.debug(
        "[CHAT] response_saved session_id=%s status=%s active_task_id=%s resume_prompt=%s",
        request.session_id,
        response.status,
        response.active_task_id,
        response.resume_prompt,
    )
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
    logger.debug("[CHAT] assistant_message_saved session_id=%s status=%s", request.session_id, response.status)


def _infer_lifecycle(response_status: str, fsm_state: str) -> str:
    if response_status == "blocked":
        return "completed"
    if response_status == "info_response" and fsm_state == "idle":
        return "completed"
    if response_status in {"draft_ready", "clarification_needed", "needs_otp", "side_question"}:
        return "active"
    if fsm_state in {"waiting_confirmation", "waiting_otp", "waiting_category_confirm"}:
        return "active"
    return "active"


def _task_response(
    *,
    request: ChatRequest,
    status: str,
    message: str,
    active_task: dict | None = None,
    unfinished_tasks: list[dict] | None = None,
    resume_prompt: bool = False,
    task_switch: dict | None = None,
) -> ChatResponse:
    suspended = task_store.list_tasks(request.session_id, lifecycles=("suspended",))
    auth_required = None
    if active_task and active_task.get("fsm_state") == "waiting_otp":
        auth_required = "otp"
    elif active_task and active_task.get("fsm_state") == "waiting_confirmation":
        auth_required = "confirm"
    return ChatResponse(
        status=status,
        message=message,
        auth_required=auth_required,
        active_task_id=active_task.get("task_id") if active_task else None,
        active_task_type=active_task.get("task_type") if active_task else None,
        active_task_lifecycle=active_task.get("lifecycle") if active_task else None,
        suspended_tasks=_public_tasks(suspended),
        unfinished_tasks=_public_tasks(unfinished_tasks or []) or None,
        resume_prompt=resume_prompt,
        task_switch=task_switch,
    )


def _append_resume_prompt(message: str, unfinished_tasks: list[dict]) -> str:
    if not unfinished_tasks:
        return message
    lines = ["", "Bạn vẫn còn các tác vụ chưa hoàn tất:"]
    for index, task in enumerate(unfinished_tasks, start=1):
        summary = task.get("summary") or "Tác vụ chưa hoàn tất"
        state_text = _state_label(task.get("fsm_state", "idle"))
        lines.append(f"{index}. {summary} - {state_text}")
    lines.append("")
    lines.append("Bạn có muốn tiếp tục tác vụ nào không?")
    return (message or "").rstrip() + "\n" + "\n".join(lines)


def _resume_task_message(task: dict | None) -> str:
    if not task:
        return "Không tìm thấy tác vụ để tiếp tục."
    summary = task.get("summary") or "tác vụ đã tạm dừng"
    last_prompt = task.get("last_agent_message")
    if last_prompt:
        return f"Đã quay lại tác vụ: {summary}.\n\n{last_prompt}"
    return f"Đã quay lại tác vụ: {summary}. Bạn muốn tiếp tục không?"


def _state_label(fsm_state: str) -> str:
    labels = {
        "waiting_confirmation": "đang chờ xác nhận",
        "waiting_otp": "đang chờ OTP",
        "waiting_category_confirm": "đang chờ phân loại giao dịch",
        "idle": "đang chờ bổ sung thông tin",
    }
    return labels.get(fsm_state or "idle", "chưa hoàn tất")


def _public_tasks(tasks: list[dict]) -> list[dict]:
    return [
        {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "operation": task.get("operation"),
            "summary": task.get("summary"),
            "fsm_state": task.get("fsm_state"),
            "resume_hint": task.get("resume_hint"),
        }
        for task in tasks
    ]
