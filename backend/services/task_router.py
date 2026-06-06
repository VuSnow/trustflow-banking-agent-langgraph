"""Global task routing before entering the domain FSM."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re

from backend.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

RESUME_ACTIVE_TASK = "RESUME_ACTIVE_TASK"
SWITCH_TO_NEW_TASK = "SWITCH_TO_NEW_TASK"
RESUME_OLD_TASK = "RESUME_OLD_TASK"
CANCEL_ACTIVE_TASK = "CANCEL_ACTIVE_TASK"
CLARIFY_TASK_SWITCH = "CLARIFY_TASK_SWITCH"
DISMISS_RESUME_PROMPT = "DISMISS_RESUME_PROMPT"


@dataclass
class TaskRouteDecision:
    action: str
    task_type: str | None = None
    operation: str | None = None
    task_id: str | None = None
    reason: str = ""
    message: str | None = None

    def model_dump(self) -> dict:
        return {
            "action": self.action,
            "task_type": self.task_type,
            "operation": self.operation,
            "task_id": self.task_id,
            "reason": self.reason,
            "message": self.message,
        }


def _emit(decision: TaskRouteDecision) -> TaskRouteDecision:
    logger.debug("[TASK ROUTER] decision=%s", decision.model_dump())
    return decision


_CONFIRM_WORDS = {
    "ok", "oke", "ừ", "ờ", "đúng", "đúng rồi", "đồng ý", "xác nhận",
    "yes", "có", "tiếp tục", "làm đi", "chuyển đi",
}
_CANCEL_WORDS = {"không", "hủy", "huỷ", "thôi", "dừng", "cancel", "bỏ qua"}
_OTP_RE = re.compile(r"^\s*\d{4,8}\s*$")


async def route_task_turn(
    *,
    message: str,
    active_task: dict | None,
    unfinished_tasks: list[dict],
) -> TaskRouteDecision:
    """Decide whether the message belongs to the active task or another task."""
    normalized = _normalize(message)
    logger.debug(
        "[TASK ROUTER] start active_task_id=%s active_type=%s active_operation=%s fsm_state=%s unfinished_count=%d message_len=%d",
        active_task.get("task_id") if active_task else None,
        active_task.get("task_type") if active_task else None,
        active_task.get("operation") if active_task else None,
        active_task.get("fsm_state") if active_task else None,
        len(unfinished_tasks),
        len(message or ""),
    )

    if not active_task:
        return _route_without_active_task(normalized, unfinished_tasks)

    fsm_state = active_task.get("fsm_state") or "idle"

    # Keep crisp confirmations and OTP-like values on the active task.
    if fsm_state == "waiting_category_confirm" and (
        normalized.isdigit() or normalized in _CONFIRM_WORDS or normalized in _CANCEL_WORDS
    ):
        return _emit(TaskRouteDecision(action=RESUME_ACTIVE_TASK, reason="category_reply"))

    if normalized in _CANCEL_WORDS:
        return _emit(TaskRouteDecision(
            action=CANCEL_ACTIVE_TASK,
            task_id=active_task["task_id"],
            reason="user_cancelled_active_task",
        ))

    if _asks_to_resume(normalized) and unfinished_tasks:
        return _emit(TaskRouteDecision(
            action=RESUME_OLD_TASK,
            task_id=unfinished_tasks[0]["task_id"],
            reason="explicit_resume_previous_task",
        ))

    if fsm_state == "waiting_otp" and _OTP_RE.match(normalized):
        return _emit(TaskRouteDecision(action=RESUME_ACTIVE_TASK, reason="otp_like_input"))
    if fsm_state == "waiting_confirmation" and normalized in _CONFIRM_WORDS:
        return _emit(TaskRouteDecision(action=RESUME_ACTIVE_TASK, reason="confirmation_reply"))

    new_intent = infer_task_type(normalized)
    if new_intent and _is_different_task(new_intent, active_task):
        return _emit(TaskRouteDecision(
            action=SWITCH_TO_NEW_TASK,
            task_type=new_intent[0],
            operation=new_intent[1],
            task_id=active_task["task_id"],
            reason="clear_new_use_case",
        ))

    if _looks_like_side_question(normalized) and fsm_state in {"waiting_confirmation", "waiting_otp"}:
        return await _llm_fallback_or_clarify(message, active_task)

    return _emit(TaskRouteDecision(action=RESUME_ACTIVE_TASK, reason="default_active_task"))


def infer_task_type(message: str) -> tuple[str, str | None] | None:
    msg = _normalize(message)
    if any(k in msg for k in ("lừa đảo", "lua dao", "fraud", "scam", "bị lừa", "bi lua", "báo cáo")):
        return ("FRAUD_REPORT", None)
    if any(k in msg for k in ("nạp tiền", "nạp điện thoại", "nap tien", "top up", "topup", "nạp ví")):
        return ("TRANSACTION", "TOP_UP")
    if any(k in msg for k in ("hóa đơn", "hoa don", "thanh toán điện", "thanh toan dien", "tiền điện")):
        return ("TRANSACTION", "BILL_PAYMENT")
    if any(k in msg for k in ("chuyển", "chuyen", "gửi tiền", "gui tien", "transfer")):
        return ("TRANSACTION", "TRANSFER_MONEY")
    if any(k in msg for k in ("thẻ", "the ", "card", "visa", "mastercard", "khóa thẻ", "mở khóa thẻ")):
        return ("CARD_OPERATION", None)
    if any(k in msg for k in ("tài khoản", "tai khoan", "mở tài khoản", "đóng tài khoản", "số dư")):
        return ("ACCOUNT_OPERATION", None)
    if any(k in msg for k in ("chi tiêu", "ngân sách", "tiết kiệm", "tư vấn tài chính")):
        return ("FINANCE_ADVICE", None)
    return None


def _route_without_active_task(normalized: str, unfinished_tasks: list[dict]) -> TaskRouteDecision:
    if normalized in _CANCEL_WORDS:
        return _emit(TaskRouteDecision(action=DISMISS_RESUME_PROMPT, reason="dismiss_resume_prompt"))
    if unfinished_tasks and normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(unfinished_tasks):
            return _emit(TaskRouteDecision(
                action=RESUME_OLD_TASK,
                task_id=unfinished_tasks[index]["task_id"],
                reason="resume_by_number",
            ))
    if unfinished_tasks and _asks_to_resume(normalized):
        return _emit(TaskRouteDecision(
            action=RESUME_OLD_TASK,
            task_id=unfinished_tasks[0]["task_id"],
            reason="explicit_resume_previous_task",
        ))
    inferred = infer_task_type(normalized)
    if inferred:
        return _emit(TaskRouteDecision(
            action=SWITCH_TO_NEW_TASK,
            task_type=inferred[0],
            operation=inferred[1],
            reason="new_task_without_active_task",
        ))
    return _emit(TaskRouteDecision(action=SWITCH_TO_NEW_TASK, task_type="UNKNOWN", reason="default_new_task"))


def _is_different_task(new_intent: tuple[str, str | None], active_task: dict) -> bool:
    new_type, new_operation = new_intent
    active_type = active_task.get("task_type") or "UNKNOWN"
    active_operation = active_task.get("operation")
    if active_type == "UNKNOWN":
        return False
    if new_type != active_type:
        return True
    return bool(new_operation and active_operation and new_operation != active_operation)


def _asks_to_resume(message: str) -> bool:
    return any(k in message for k in ("quay lại", "quay lai", "tiếp tục", "tiep tuc", "lúc nãy", "luc nay"))


def _looks_like_side_question(message: str) -> bool:
    return "?" in message or len(message.split()) >= 5


def _clarify_message(active_task: dict) -> str:
    summary = active_task.get("summary") or "tác vụ hiện tại"
    return (
        f"Tôi đang giữ tác vụ: {summary}. "
        "Bạn muốn tiếp tục tác vụ này hay chuyển sang yêu cầu mới?"
    )


def _normalize(message: str) -> str:
    return (message or "").strip().lower()


async def _llm_fallback_or_clarify(message: str, active_task: dict) -> TaskRouteDecision:
    if not OPENAI_API_KEY:
        return _clarify_decision(active_task, "missing_openai_api_key")

    try:
        logger.debug("[TASK ROUTER] llm_fallback active_task_id=%s", active_task.get("task_id"))
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)
        response = await llm.ainvoke([
            SystemMessage(content=_ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps({
                "message": message,
                "active_task": {
                    "task_type": active_task.get("task_type"),
                    "operation": active_task.get("operation"),
                    "fsm_state": active_task.get("fsm_state"),
                    "summary": active_task.get("summary"),
                },
            }, ensure_ascii=False)),
        ])
        data = json.loads(response.content)
        action = data.get("action")
        logger.debug("[TASK ROUTER] llm_fallback action=%s reason=%s", action, data.get("reason"))
        if action == SWITCH_TO_NEW_TASK:
            task_type = data.get("task_type") or "UNKNOWN"
            operation = data.get("operation")
            return _emit(TaskRouteDecision(
                action=SWITCH_TO_NEW_TASK,
                task_type=task_type,
                operation=operation,
                task_id=active_task["task_id"],
                reason="llm_fallback_new_task",
            ))
        if action == RESUME_ACTIVE_TASK:
            return _emit(TaskRouteDecision(action=RESUME_ACTIVE_TASK, reason="llm_fallback_active_task"))
    except Exception as exc:
        logger.warning("[TASK ROUTER] LLM fallback failed: %s", exc)

    return _clarify_decision(active_task, "llm_fallback_unclear")


def _clarify_decision(active_task: dict, reason: str) -> TaskRouteDecision:
    return _emit(TaskRouteDecision(
        action=CLARIFY_TASK_SWITCH,
        task_id=active_task["task_id"],
        reason=reason,
        message=_clarify_message(active_task),
    ))


_ROUTER_SYSTEM_PROMPT = """You route one user message in a Vietnamese banking chatbot.

The user may be in the middle of an active task. Decide whether the message is a reply to that active task or a clear switch to a new use case.

Return valid JSON only:
{
  "action": "RESUME_ACTIVE_TASK | SWITCH_TO_NEW_TASK | CLARIFY_TASK_SWITCH",
  "task_type": "TRANSACTION | CARD_OPERATION | ACCOUNT_OPERATION | FRAUD_REPORT | DATA_QUERY | QA | FINANCE_ADVICE | UNKNOWN",
  "operation": "TRANSFER_MONEY | BILL_PAYMENT | TOP_UP | REPORT_FRAUD | CHECK_ACCOUNT_RISK | null",
  "reason": "short reason"
}

Use SWITCH_TO_NEW_TASK only when the user clearly asks for a different banking use case.
Use RESUME_ACTIVE_TASK when the message is likely an answer, confirmation, OTP, correction, or continuation of the active task.
Use CLARIFY_TASK_SWITCH when unclear.
"""
