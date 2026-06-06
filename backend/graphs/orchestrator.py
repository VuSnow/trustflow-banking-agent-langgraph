"""Main Orchestrator Graph — Controlled Agentic Workflow.

Architecture:
  route_node → dispatch_agent_node → handle_flow_action_node → format_response_node

Design principles:
- Agent (LLM) ONLY extracts entities and resolves information
- State transitions are deterministic (no LLM decides OTP/confirm/execute)
- FlowRouter uses status-first dispatch (locked > pending_question > limited > flexible)
- Response formatting uses templates, not LLM, for sensitive messages (money, accounts)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

from backend.config import OPENAI_API_KEY, OPENAI_MODEL, CURRENT_BANK_CODE
from backend.state import ChatState
from backend.models.flow import (
    FlowState,
    TransactionDraft,
    BillDraft,
    TopUpDraft,
    PendingQuestion,
    InterruptedIntent,
    serialize_flow,
    deserialize_flow,
)
from backend.services.flow_router import (
    FlowRouter,
    RouteDecision,
    RuleBasedConfirmationClassifier,
    IntentClassifierInterface,
    serialize_route_decision,
)
from backend.services.recipient_resolver import RecipientResolver, ResolutionResult, _mask_account
from backend.services.transaction_validator import TransactionValidator
from backend.services.otp_service import otp_service
from backend.services.audit_log import write_audit_log
from backend.services.langfuse_trace import get_trace_config
from backend.agents.transaction import TransactionExtractor
from backend.prompts.intent import INTENT_SYSTEM_PROMPT, INTENT_USER_TEMPLATE

logger = logging.getLogger(__name__)

# ─── Singletons ───────────────────────────────────────────────────────────────

_recipient_resolver = RecipientResolver()
_validator = TransactionValidator()
_extractor = TransactionExtractor()


# ─── Intent Classifier (LLM-based, used as fallback by router) ────────────────

class LLMIntentClassifier(IntentClassifierInterface):
    """LLM-based intent classifier — used by FlowRouter for new intent detection."""

    async def classify(self, message: str) -> str | None:
        """Classify message into intent type.

        Returns composite key like 'TRANSACTION:TRANSFER_MONEY' or 'TRANSACTION:BILL_PAYMENT'
        when operation is available, otherwise just task_type.
        """
        llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)

        try:
            response = await llm.ainvoke([
                SystemMessage(content=INTENT_SYSTEM_PROMPT),
                HumanMessage(content=INTENT_USER_TEMPLATE.format(message=message)),
            ])
            data = json.loads(response.content)
            task_type = data.get("task_type", "UNKNOWN")
            operation = data.get("operation")
            if task_type == "QA":
                return None  # QA is not a "flow" intent
            # Return composite for TRANSACTION sub-types
            if task_type == "TRANSACTION" and operation:
                return f"TRANSACTION:{operation}"
            return task_type
        except Exception as e:
            logger.warning(f"[INTENT_CLF] Error: {e}")
            return None


_intent_classifier = LLMIntentClassifier()
_confirmation_classifier = RuleBasedConfirmationClassifier()
_flow_router = FlowRouter(
    confirmation_classifier=_confirmation_classifier,
    intent_classifier=_intent_classifier,
)


# ─── Response Templates ───────────────────────────────────────────────────────

RESPONSE_TEMPLATES = {
    "recipient_candidates": (
        "Tôi tìm thấy {count} người tên \"{query}\":\n\n"
        "{candidates_list}\n\n"
        "Bạn muốn chuyển cho ai? (Nhập số thứ tự)"
    ),
    "recipient_confirm": (
        "Tôi tìm thấy người nhận:\n"
        "• Tên: {name}\n"
        "• Ngân hàng: {bank}\n"
        "• Số tài khoản: {masked_account}\n\n"
        "Đây có đúng là người bạn muốn chuyển không?"
    ),
    "draft_summary": (
        "Vui lòng kiểm tra thông tin giao dịch:\n\n"
        "Từ tài khoản: {source}\n"
        "Đến: {recipient_name}\n"
        "Ngân hàng: {bank}\n"
        "Số tài khoản: {masked_account}\n"
        "Số tiền: {amount}\n"
        "Phí giao dịch: {fee}\n"
        "Tổng tiền trừ: {total_debit}\n"
        "Nội dung: {note}\n\n"
        "Bạn xác nhận thực hiện giao dịch này chứ?"
    ),
    "otp_request": (
        "Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.\n"
        "Vui lòng nhập OTP để hoàn tất giao dịch.\n\n"
        "Giao dịch: chuyển {amount} đến {recipient_name}."
    ),
    "success_receipt": (
        "Giao dịch thành công.\n\n"
        "Mã giao dịch: {ref}\n"
        "Thời gian: {time}\n"
        "Từ tài khoản: {source}\n"
        "Người nhận: {recipient_name}\n"
        "Ngân hàng: {bank}\n"
        "Số tài khoản nhận: {masked_account}\n\n"
        "Số tiền chuyển: {amount}\n"
        "Phí giao dịch: {fee}\n"
        "Tổng tiền đã trừ: {total_debit}\n"
        "Số dư còn lại: {balance}"
    ),
    "otp_wrong": "Mã OTP không đúng. Còn {remaining} lần thử. Vui lòng nhập lại.",
    "otp_expired": "Mã OTP đã hết hạn. Vui lòng thực hiện lại giao dịch.",
    "otp_max_attempts": "Đã vượt quá số lần nhập OTP. Giao dịch đã bị hủy vì lý do bảo mật.",
    "otp_hash_mismatch": "Thông tin giao dịch đã thay đổi. Vui lòng xác nhận lại giao dịch.",
    "interrupt_locked": (
        "Bạn đang có giao dịch chờ xác thực OTP:\n\n"
        "Chuyển {amount} đến {recipient_name}\n"
        "Tổng tiền trừ: {total_debit}\n\n"
        "Để tiếp tục việc khác, bạn cần:\n"
        "1. Nhập OTP để hoàn tất giao dịch\n"
        "2. Hủy giao dịch này\n\n"
        "Bạn muốn nhập OTP hay hủy giao dịch?"
    ),
    "ask_switch": (
        "Bạn đang tạo giao dịch chuyển tiền. "
        "Bạn muốn hủy giao dịch này để chuyển sang {new_intent} không?"
    ),
    "cancelled": "Đã hủy giao dịch.",
    "cancelled_with_resume": (
        "Đã hủy giao dịch chuyển tiền.\n"
        "Bây giờ tôi sẽ hỗ trợ bạn {resumed_intent}."
    ),
    "ask_valid_otp": (
        "Vui lòng nhập mã OTP 6 số đã gửi đến điện thoại của bạn, "
        "hoặc nhập \"hủy\" để hủy giao dịch."
    ),
    "ask_confirm_or_cancel": (
        "Tôi chưa hiểu rõ. Bạn muốn xác nhận hay hủy giao dịch?"
    ),
    "need_recipient": "Bạn muốn chuyển tiền cho ai? Vui lòng cho tôi biết tên người nhận hoặc số tài khoản.",
    "need_amount": "Bạn muốn chuyển bao nhiêu tiền?",
    "recipient_not_found": (
        "Tôi không tìm thấy người nhận \"{query}\" trong danh sách.\n"
        "Vui lòng cung cấp số tài khoản và ngân hàng, hoặc kiểm tra lại tên."
    ),
    "fraud_warning_high": (
        "⚠️ CẢNH BÁO: Tài khoản nhận có {report_count} báo cáo nghi ngờ lừa đảo "
        "với mức rủi ro CAO. Vui lòng cân nhắc kỹ trước khi tiếp tục."
    ),
    "fraud_block": (
        "⚠️ Tài khoản này đã bị xác nhận là tài khoản lừa đảo. "
        "Giao dịch không thể thực hiện."
    ),
    "unsupported_flow": "Hiện tôi chỉ hỗ trợ chuyển tiền trong bản demo này.",
}


# ─── Node: route_node ─────────────────────────────────────────────────────────

async def route_node(state: ChatState) -> dict:
    """Deterministic routing based on flow state.

    This is the FIRST node — decides what action to take for this user message.
    """
    flow = deserialize_flow(state.get("active_flow"))
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    decision = await _flow_router.route(flow, last_message)

    logger.info(f"[ROUTE] action={decision.action} flow_status={flow.status if flow else 'none'}")

    return {"route_decision": serialize_route_decision(decision)}


# ─── Node: dispatch_agent_node ────────────────────────────────────────────────

async def dispatch_agent_node(state: ChatState) -> dict:
    """Dispatch to appropriate agent based on route decision.

    Only called when route_decision.action indicates agent work is needed:
    - CLASSIFY_NEW_INTENT → intent classifier + possibly start new flow
    - CONTINUE_COLLECTING → transaction extractor
    - ANSWER_PENDING_QUESTION → may need extractor for interpretation
    """
    decision_data = state.get("route_decision", {})
    action = decision_data.get("action", "")
    flow = deserialize_flow(state.get("active_flow"))
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    if action == "CLASSIFY_NEW_INTENT":
        # Classify intent and potentially start new flow
        intent = await _intent_classifier.classify(last_message)

        if intent is None:
            # QA intent — answer directly without starting a flow
            from backend.agents.qa import run_qa_agent
            qa_result = await run_qa_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
            )
            return {
                "response_message": qa_result["message"],
                "response_data": {"handled": True, "task_type": "QA"},
            }

        if intent == "TRANSACTION:BILL_PAYMENT":
            # Bill payment — deterministic state machine
            return await _handle_bill_new(last_message, state["user_id"], state["session_id"])

        if intent == "TRANSACTION:TOP_UP":
            # Top-up — LLM extraction + state machine
            return await _handle_topup_new(last_message, state["user_id"], state["session_id"])

        if intent and intent.startswith("TRANSACTION"):
            # Default to TRANSACTION for Phase 1, or if looks like transfer
            # Run extractor to get initial fields
            result = await _extractor.process(
                message=last_message,
                user_id=state["user_id"],
                current_draft=None,
                pending_question=None,
                session_id=state["session_id"],
            )

            # Start new flow
            new_flow = FlowState(
                flow_type="TRANSACTION",
                status="COLLECTING",
                draft=TransactionDraft(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # Apply extracted fields to draft
            new_flow = _apply_extraction_to_flow(new_flow, result)

            return {
                "active_flow": serialize_flow(new_flow),
                "response_data": {
                    "agent_result": {
                        "extracted_fields": result.extracted_fields,
                        "recipient_resolution_plan": (
                            result.recipient_resolution_plan.model_dump()
                            if result.recipient_resolution_plan else None
                        ),
                        "missing_fields": result.missing_fields,
                        "interpretation": result.interpretation,
                    }
                },
            }
        else:
            # Non-transaction intent — respond that only TRANSACTION is supported in Phase 1
            return {
                "response_message": RESPONSE_TEMPLATES["unsupported_flow"],
                "response_data": {"handled": True},
            }

    elif action == "CONTINUE_COLLECTING":
        # ─── BILL_PAYMENT multi-turn ─────────────────────────────────────
        if flow and flow.flow_type == "BILL_PAYMENT":
            return await _handle_bill_continue(flow, last_message, state["user_id"], state["session_id"])

        # ─── TOP_UP multi-turn ────────────────────────────────────────────
        if flow and flow.flow_type == "TOP_UP":
            return await _handle_topup_continue(flow, last_message, state["user_id"], state["session_id"])

        # ─── TRANSACTION collecting ──────────────────────────────────────
        # Run extractor with current draft context
        draft = flow.draft if flow else None
        pending_q = flow.pending_question if flow else None

        result = await _extractor.process(
            message=last_message,
            user_id=state["user_id"],
            current_draft=draft,
            pending_question=pending_q,
            session_id=state["session_id"],
        )

        # Apply to existing flow
        if flow:
            flow = _apply_extraction_to_flow(flow, result)

        return {
            "active_flow": serialize_flow(flow),
            "response_data": {
                "agent_result": {
                    "extracted_fields": result.extracted_fields,
                    "recipient_resolution_plan": (
                        result.recipient_resolution_plan.model_dump()
                        if result.recipient_resolution_plan else None
                    ),
                    "missing_fields": result.missing_fields,
                    "interpretation": result.interpretation,
                }
            },
        }

    elif action == "MODIFY_DRAFT":
        # User wants to modify — run extractor to get new values
        draft = flow.draft if flow else None
        result = await _extractor.process(
            message=last_message,
            user_id=state["user_id"],
            current_draft=draft,
            pending_question=None,
            session_id=state["session_id"],
        )

        if flow:
            flow = _apply_extraction_to_flow(flow, result)
            # Reset to COLLECTING so we re-resolve
            flow.status = "COLLECTING"
            flow.pending_question = None

        return {
            "active_flow": serialize_flow(flow),
            "response_data": {
                "agent_result": {
                    "extracted_fields": result.extracted_fields,
                    "recipient_resolution_plan": (
                        result.recipient_resolution_plan.model_dump()
                        if result.recipient_resolution_plan else None
                    ),
                    "missing_fields": result.missing_fields,
                },
            },
        }

    # For other actions (CONFIRM, CANCEL, SUBMIT_OTP, etc.)
    # dispatch_agent is a pass-through; handle_flow_action does the work
    return {}


# ─── Node: handle_flow_action_node ───────────────────────────────────────────

async def handle_flow_action_node(state: ChatState) -> dict:
    """Execute flow state transitions deterministically.

    This is where ALL sensitive transitions happen:
    - Recipient resolution + verification
    - Fee calculation
    - Draft confirmation assembly
    - OTP challenge creation
    - OTP validation
    - Transaction execution
    - Flow cancellation
    - Interrupted intent handling
    """
    decision_data = state.get("route_decision", {})
    action = decision_data.get("action", "")
    flow = deserialize_flow(state.get("active_flow"))
    response_data = state.get("response_data", {})
    user_id = state["user_id"]
    session_id = state["session_id"]

    # If response already handled (e.g. unsupported_flow, bill_payment, qa)
    if response_data.get("handled"):
        return {}
    if state.get("response_message"):
        return {}

    # ─── CLASSIFY_NEW_INTENT or CONTINUE_COLLECTING: resolve + advance ────
    if action in ("CLASSIFY_NEW_INTENT", "CONTINUE_COLLECTING", "MODIFY_DRAFT"):
        if not flow or not flow.draft:
            return {"response_message": RESPONSE_TEMPLATES["unsupported_flow"]}

        agent_result = response_data.get("agent_result", {})
        plan_data = agent_result.get("recipient_resolution_plan")

        # Step A: Handle resolution if plan provided
        if plan_data:
            from backend.models.flow import RecipientResolutionPlan
            plan = RecipientResolutionPlan.model_validate(plan_data)
            flow = _resolve_recipient_from_plan(flow, user_id, plan)

        # Step B: Determine next step based on draft completeness
        flow, message = _determine_next_step(flow, user_id)

        flow.updated_at = datetime.now()
        return {
            "active_flow": serialize_flow(flow),
            "response_message": message,
        }

    # ─── ANSWER_PENDING_QUESTION ──────────────────────────────────────────
    if action == "ANSWER_PENDING_QUESTION":
        data = decision_data.get("data", {})
        if flow and flow.pending_question:
            flow = _apply_pending_answer(flow, data)
            flow, message = _determine_next_step(flow, user_id)
            flow.updated_at = datetime.now()
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

    # ─── CONFIRM ──────────────────────────────────────────────────────────
    if action == "CONFIRM":
        if not flow:
            return {"response_message": "Không có giao dịch nào đang chờ xác nhận."}

        if flow.status == "WAITING_RECIPIENT_CONFIRMATION":
            # Verify recipient, compute fee, move to draft confirmation
            flow = await _handle_recipient_confirmed(flow, user_id)
            message = _build_draft_summary_message(flow)
            flow.updated_at = datetime.now()

            write_audit_log(
                cif_no=user_id,
                event_type="RECIPIENT_CONFIRMED",
                actor="user",
                session_id=session_id,
                event_payload={"recipient": flow.draft.recipient_name},
            )

            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        elif flow.status == "WAITING_DRAFT_CONFIRMATION":
            # Validate and create OTP challenge
            validation = _validator.validate_for_execution(flow.draft, user_id)
            if not validation.valid:
                message = "Không thể thực hiện giao dịch:\n" + "\n".join(f"• {e}" for e in validation.errors)
                return {"response_message": message}

            # Create OTP challenge bound to draft hash
            challenge_id = otp_service.create_challenge(
                flow_id=flow.flow_id,
                user_id=user_id,
                summary_hash=flow.draft.summary_hash(),
            )
            flow.otp_challenge_id = challenge_id
            flow.status = "WAITING_OTP"
            flow.pending_question = PendingQuestion(
                slot="otp",
                question="Nhập mã OTP",
                expected_type="otp",
            )
            flow.updated_at = datetime.now()

            message = RESPONSE_TEMPLATES["otp_request"].format(
                amount=f"{flow.draft.amount:,.0f} VND",
                recipient_name=flow.draft.recipient_name,
            )

            write_audit_log(
                cif_no=user_id,
                event_type="OTP_CHALLENGE_CREATED",
                actor="system",
                session_id=session_id,
                event_payload={"challenge_id": challenge_id},
            )

            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        elif flow.status == "WAITING_BILL_CONFIRMATION":
            # Execute bill payment directly (no OTP for bill payment)
            exec_result = await _execute_bill_payment(flow, user_id, session_id)
            flow.status = "COMPLETED"
            flow.updated_at = datetime.now()
            return {
                "active_flow": None,
                "response_message": exec_result["message"],
                "response_data": exec_result.get("data", {}),
            }

        elif flow.status == "WAITING_TOPUP_CONFIRMATION":
            # Execute top-up directly (no OTP for top-up)
            exec_result = await _execute_topup(flow, user_id, session_id)
            flow.status = "COMPLETED"
            flow.updated_at = datetime.now()
            return {
                "active_flow": None,
                "response_message": exec_result["message"],
                "response_data": exec_result.get("data", {}),
            }

    # ─── SUBMIT_OTP ───────────────────────────────────────────────────────
    if action == "SUBMIT_OTP":
        if not flow or not flow.otp_challenge_id:
            return {"response_message": "Không có giao dịch nào đang chờ OTP."}

        otp_input = decision_data.get("data", {}).get("otp", "")
        current_hash = flow.draft.summary_hash()

        result = otp_service.validate(
            challenge_id=flow.otp_challenge_id,
            otp_input=otp_input,
            current_summary_hash=current_hash,
        )

        if result.valid:
            # Execute transaction
            flow.draft.idempotency_key = f"{flow.flow_id}:{flow.draft.confirmation_id}"
            flow.status = "EXECUTING"

            write_audit_log(
                cif_no=user_id,
                event_type="OTP_VALIDATED",
                actor="system",
                session_id=session_id,
                event_payload={"success": True},
            )

            exec_result = await _execute_transaction(flow, user_id, session_id)
            flow.status = "COMPLETED"
            flow.updated_at = datetime.now()

            # Check for interrupted intent
            interrupted = flow.interrupted_intent
            message = exec_result["message"]

            if interrupted:
                message += f"\n\nTiếp theo, tôi sẽ hỗ trợ bạn {_intent_display_name(interrupted.intent)}."

            # Clear the flow
            return {
                "active_flow": None,  # Flow complete
                "response_message": message,
                "response_data": exec_result.get("data", {}),
            }
        else:
            # OTP failed
            flow.otp_attempts += 1
            flow.updated_at = datetime.now()

            write_audit_log(
                cif_no=user_id,
                event_type="OTP_FAILED",
                actor="system",
                session_id=session_id,
                event_payload={"reason": result.reason, "attempts": flow.otp_attempts},
            )

            if result.reason == "expired":
                flow.status = "CANCELLED"
                return {
                    "active_flow": None,
                    "response_message": RESPONSE_TEMPLATES["otp_expired"],
                }
            elif result.reason == "max_attempts":
                flow.status = "CANCELLED"
                return {
                    "active_flow": None,
                    "response_message": RESPONSE_TEMPLATES["otp_max_attempts"],
                }
            elif result.reason == "hash_mismatch":
                flow.status = "CANCELLED"
                return {
                    "active_flow": None,
                    "response_message": RESPONSE_TEMPLATES["otp_hash_mismatch"],
                }
            else:
                remaining = otp_service.get_remaining_attempts(flow.otp_challenge_id)
                message = RESPONSE_TEMPLATES["otp_wrong"].format(remaining=remaining)
                return {
                    "active_flow": serialize_flow(flow),
                    "response_message": message,
                }

    # ─── CANCEL_ACTIVE_FLOW ───────────────────────────────────────────────
    if action == "CANCEL_ACTIVE_FLOW":
        if not flow:
            return {"response_message": "Không có giao dịch nào để hủy."}

        # Invalidate OTP if exists
        if flow.otp_challenge_id:
            otp_service.invalidate(flow.otp_challenge_id)

        interrupted = flow.interrupted_intent

        write_audit_log(
            cif_no=user_id,
            event_type="FLOW_CANCELLED",
            actor="user",
            session_id=session_id,
            event_payload={"flow_id": flow.flow_id, "status_at_cancel": flow.status},
        )

        if interrupted:
            message = RESPONSE_TEMPLATES["cancelled_with_resume"].format(
                resumed_intent=_intent_display_name(interrupted.intent),
            )
        else:
            message = RESPONSE_TEMPLATES["cancelled"]

        return {
            "active_flow": None,
            "response_message": message,
        }

    # ─── INTERRUPT_LOCKED_FLOW ────────────────────────────────────────────
    if action == "INTERRUPT_LOCKED_FLOW":
        if flow:
            messages = state["messages"]
            last_msg = messages[-1].content if messages else ""
            flow.interrupted_intent = InterruptedIntent(
                intent=decision_data.get("interrupted_intent", ""),
                original_message=last_msg,
            )
            flow.updated_at = datetime.now()

            message = RESPONSE_TEMPLATES["interrupt_locked"].format(
                amount=f"{flow.draft.amount:,.0f} VND" if flow.draft and flow.draft.amount else "?",
                recipient_name=flow.draft.recipient_name if flow.draft else "?",
                total_debit=f"{flow.draft.total_debit:,.0f} VND" if flow.draft and flow.draft.total_debit else "?",
            )

            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

    # ─── ASK_SWITCH_OR_CANCEL ─────────────────────────────────────────────
    if action == "ASK_SWITCH_OR_CANCEL":
        new_intent = decision_data.get("interrupted_intent", "")
        message = RESPONSE_TEMPLATES["ask_switch"].format(
            new_intent=_intent_display_name(new_intent),
        )
        return {"response_message": message}

    # ─── ASK_VALID_INPUT ──────────────────────────────────────────────────
    if action == "ASK_VALID_INPUT":
        if flow and flow.status == "WAITING_OTP":
            message = RESPONSE_TEMPLATES["ask_valid_otp"]
        elif flow and flow.status in ("WAITING_RECIPIENT_CONFIRMATION", "WAITING_DRAFT_CONFIRMATION", "WAITING_BILL_CONFIRMATION", "WAITING_TOPUP_CONFIRMATION"):
            message = RESPONSE_TEMPLATES["ask_confirm_or_cancel"]
        else:
            message = "Tôi chưa hiểu rõ. Vui lòng thử lại."
        return {"response_message": message}

    return {}


# ─── Node: format_response_node ──────────────────────────────────────────────

async def format_response_node(state: ChatState) -> dict:
    """Final formatting — ensure response_message is set.

    In most cases, handle_flow_action already sets response_message.
    This node handles edge cases and ensures we always have a response.
    """
    message = state.get("response_message", "")
    if not message:
        message = "Tôi có thể giúp gì cho bạn?"
    return {"response_message": message}


# ─── Routing functions ────────────────────────────────────────────────────────

def after_route(state: ChatState) -> str:
    """Route after route_node — decide if we need agent or can handle directly."""
    decision_data = state.get("route_decision", {})
    action = decision_data.get("action", "")

    # Actions that need agent processing
    if action in ("CLASSIFY_NEW_INTENT", "CONTINUE_COLLECTING", "MODIFY_DRAFT"):
        return "dispatch_agent"

    # Actions that handle_flow_action can handle directly
    if action in (
        "CONFIRM", "CANCEL_ACTIVE_FLOW", "SUBMIT_OTP",
        "INTERRUPT_LOCKED_FLOW", "ASK_SWITCH_OR_CANCEL",
        "ASK_VALID_INPUT", "ANSWER_PENDING_QUESTION",
    ):
        return "handle_flow_action"

    # Default: respond directly
    return "respond"


# ─── Build the graph ──────────────────────────────────────────────────────────

def build_orchestrator_graph() -> StateGraph:
    """Build the main orchestrator StateGraph.

    Graph structure:
      route → [dispatch_agent → handle_flow_action → format_response]
            → [handle_flow_action → format_response]
            → [format_response]
    """
    graph = StateGraph(ChatState)

    # Add nodes
    graph.add_node("route", route_node)
    graph.add_node("dispatch_agent", dispatch_agent_node)
    graph.add_node("handle_flow_action", handle_flow_action_node)
    graph.add_node("format_response", format_response_node)

    # Entry point
    graph.set_entry_point("route")

    # Conditional edges from route
    graph.add_conditional_edges(
        "route",
        after_route,
        {
            "dispatch_agent": "dispatch_agent",
            "handle_flow_action": "handle_flow_action",
            "respond": "format_response",
        },
    )

    # Linear edges
    graph.add_edge("dispatch_agent", "handle_flow_action")
    graph.add_edge("handle_flow_action", "format_response")
    graph.add_edge("format_response", END)

    return graph


# ─── Checkpointer ────────────────────────────────────────────────────────────

_checkpointer = None


async def _create_checkpointer_async():
    """Create async PostgreSQL-backed checkpointer for durable flow state.

    Uses AsyncPostgresSaver so that active_flow (draft, pending_question, OTP state,
    interrupted_intent) survives server restarts.
    Falls back to MemorySaver only if PostgreSQL connection fails.
    """
    from backend.config import DATABASE_URL

    try:
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()
        logger.info("[CHECKPOINT] AsyncPostgresSaver initialized (durable)")
        return checkpointer
    except Exception as e:
        logger.warning(f"[CHECKPOINT] AsyncPostgresSaver failed ({e}), falling back to MemorySaver (non-durable)")
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


async def get_checkpointer():
    """Get or create the checkpointer singleton (async)."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = await _create_checkpointer_async()
    return _checkpointer


async def compile_orchestrator():
    """Compile the orchestrator graph with async PostgreSQL checkpointing."""
    graph = build_orchestrator_graph()
    checkpointer = await get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


# ─── Helper functions ─────────────────────────────────────────────────────────

def _apply_extraction_to_flow(flow: FlowState, result) -> FlowState:
    """Apply extractor result to flow draft."""
    if not flow.draft:
        flow.draft = TransactionDraft()

    fields = result.extracted_fields or {}

    if fields.get("amount") is not None:
        flow.draft.amount = fields["amount"]
    if fields.get("recipient_query"):
        flow.draft.recipient_query = fields["recipient_query"]
    if fields.get("recipient_account_no"):
        flow.draft.recipient_account_no = fields["recipient_account_no"]
    if fields.get("recipient_bank_name"):
        flow.draft.recipient_bank_name = fields["recipient_bank_name"]
    if fields.get("transfer_note"):
        flow.draft.transfer_note = fields["transfer_note"]

    return flow


def _apply_pending_answer(flow: FlowState, answer_data: dict) -> FlowState:
    """Apply a pending question answer to the flow."""
    if not flow.pending_question:
        return flow

    slot = flow.pending_question.slot

    if slot == "recipient_choice" and "choice" in answer_data:
        choice = answer_data["choice"]
        if flow.draft:
            flow.draft.recipient_id = choice.get("beneficiary_id") or choice.get("id")
            flow.draft.recipient_name = choice.get("name")
            flow.draft.recipient_account_no = choice.get("account_no")
            flow.draft.recipient_account_no_masked = choice.get("account_no_masked")
            flow.draft.recipient_bank_code = choice.get("bank_code")
            flow.draft.recipient_bank_name = choice.get("bank_name")
        flow.pending_question = None

    elif slot == "amount" and "amount" in answer_data:
        if flow.draft:
            flow.draft.amount = answer_data["amount"]
        flow.pending_question = None

    elif slot == "recipient_query" and "text" in answer_data:
        if flow.draft:
            flow.draft.recipient_query = answer_data["text"]
        flow.pending_question = None

    else:
        flow.pending_question = None

    return flow


def _resolve_recipient_from_plan(
    flow: FlowState, user_id: str, plan: "RecipientResolutionPlan"
) -> FlowState:
    """Call RecipientResolver based on structured RecipientResolutionPlan."""
    if not flow.draft:
        return flow

    result = _recipient_resolver.resolve_from_plan(user_id, plan)

    # Apply copied fields (amount/note from past transaction)
    if result.copied_fields:
        if "amount" in result.copied_fields and result.copied_fields["amount"]:
            flow.draft.amount = result.copied_fields["amount"]
        if "note" in result.copied_fields and result.copied_fields["note"]:
            flow.draft.transfer_note = result.copied_fields["note"]

    # Apply resolution results
    candidates = result.candidates

    if len(candidates) == 1:
        c = candidates[0]
        flow.draft.recipient_id = c.beneficiary_id
        flow.draft.recipient_name = c.name
        flow.draft.recipient_account_no = c.account_no
        flow.draft.recipient_account_no_masked = c.account_no_masked
        flow.draft.recipient_bank_code = c.bank_code
        flow.draft.recipient_bank_name = c.bank_name
    elif len(candidates) > 1:
        # Multiple candidates — set pending question for user choice
        flow.pending_question = PendingQuestion(
            slot="recipient_choice",
            question=f"Tìm thấy {len(candidates)} người",
            expected_type="recipient_choice",
            options=[
                {
                    "beneficiary_id": c.beneficiary_id,
                    "name": c.name,
                    "account_no": c.account_no,
                    "account_no_masked": c.account_no_masked,
                    "bank_code": c.bank_code,
                    "bank_name": c.bank_name,
                }
                for c in candidates
            ],
        )
    # else: 0 results — handled in _determine_next_step

    return flow


def _determine_next_step(flow: FlowState, user_id: str) -> tuple[FlowState, str]:
    """Determine the next step and build appropriate response message.

    Based on draft completeness, moves flow forward or asks for more info.
    """
    if not flow.draft:
        return flow, RESPONSE_TEMPLATES["unsupported_flow"]

    draft = flow.draft

    # If there's already a pending question (set by resolver), use it
    if flow.pending_question:
        if flow.pending_question.slot == "recipient_choice":
            options = flow.pending_question.options or []
            candidates_list = "\n".join(
                f"  {i+1}. {opt['name']} — {opt['bank_name']} — {opt['account_no_masked']}"
                for i, opt in enumerate(options)
            )
            message = RESPONSE_TEMPLATES["recipient_candidates"].format(
                count=len(options),
                query=draft.recipient_query or "?",
                candidates_list=candidates_list,
            )
            flow.status = "COLLECTING"
            return flow, message

    # Check: do we have recipient info?
    if not draft.recipient_account_no and not draft.recipient_name:
        # No recipient at all
        if draft.recipient_query:
            # We tried to resolve but found nothing
            message = RESPONSE_TEMPLATES["recipient_not_found"].format(
                query=draft.recipient_query,
            )
        else:
            message = RESPONSE_TEMPLATES["need_recipient"]

        flow.pending_question = PendingQuestion(
            slot="recipient_query",
            question=message,
            expected_type="text",
        )
        flow.status = "COLLECTING"
        return flow, message

    # Check: do we have amount?
    if not draft.amount:
        message = RESPONSE_TEMPLATES["need_amount"]
        flow.pending_question = PendingQuestion(
            slot="amount",
            question=message,
            expected_type="amount",
        )
        flow.status = "COLLECTING"
        return flow, message

    # We have recipient + amount → move to recipient confirmation
    if draft.recipient_account_no and draft.recipient_name and not draft.recipient_verified:
        flow.status = "WAITING_RECIPIENT_CONFIRMATION"
        flow.pending_question = PendingQuestion(
            slot="recipient_confirmation",
            question="Xác nhận người nhận",
            expected_type="enum",
            options=[{"value": "confirm"}, {"value": "cancel"}],
        )
        message = RESPONSE_TEMPLATES["recipient_confirm"].format(
            name=draft.recipient_name,
            bank=draft.recipient_bank_name or draft.recipient_bank_code or "?",
            masked_account=draft.recipient_account_no_masked or _mask_account(draft.recipient_account_no),
        )
        return flow, message

    # If recipient already verified (e.g. after MODIFY_DRAFT re-collected)
    if draft.recipient_verified and draft.amount:
        # Should already be at WAITING_DRAFT_CONFIRMATION, rebuild
        return flow, _build_draft_summary_message(flow)

    return flow, "Đang xử lý..."


async def _handle_recipient_confirmed(flow: FlowState, user_id: str) -> FlowState:
    """After user confirms recipient: verify, check fraud, compute fee, build summary."""
    draft = flow.draft

    # Verify recipient
    verification = _recipient_resolver.verify_recipient(
        draft.recipient_account_no,
        draft.recipient_bank_code,
    )

    if verification["status"] == "verified":
        draft.recipient_verified = True
        draft.recipient_name = verification["name"]  # Official name from bank
        draft.transaction_type = (
            "INTERNAL_TRANSFER" if verification.get("transfer_type") == "intrabank"
            else "INTERBANK_TRANSFER"
        )
    else:
        # Verification failed — shouldn't happen normally but handle gracefully
        draft.recipient_verified = False
        flow.status = "COLLECTING"
        flow.pending_question = PendingQuestion(
            slot="recipient_query",
            question="Không thể xác minh tài khoản. Vui lòng kiểm tra lại.",
            expected_type="text",
        )
        return flow

    # Fraud screening
    fraud = _recipient_resolver.check_fraud_risk(
        draft.recipient_account_no,
        draft.recipient_bank_code,
    )
    draft.fraud_screening = fraud

    if fraud.get("risk_level") == "CRITICAL":
        flow.status = "CANCELLED"
        return flow

    # Resolve source account
    source = _get_primary_account(user_id)
    if source:
        draft.source_account_no = source["account_no"]
        draft.source_account_no_masked = _mask_account(source["account_no"])

    # Compute fee
    if draft.transaction_type == "INTERBANK_TRANSFER":
        draft.fee = 5500  # Standard interbank fee
    else:
        draft.fee = 0

    draft.total_debit = (draft.amount or 0) + (draft.fee or 0)

    # Set confirmation_id
    draft.confirmation_id = str(uuid.uuid4())

    # Move to draft confirmation
    flow.status = "WAITING_DRAFT_CONFIRMATION"
    flow.pending_question = PendingQuestion(
        slot="draft_confirmation",
        question="Xác nhận giao dịch",
        expected_type="enum",
        options=[{"value": "confirm"}, {"value": "cancel"}],
    )

    return flow


def _build_draft_summary_message(flow: FlowState) -> str:
    """Build the full transaction summary for user confirmation."""
    draft = flow.draft
    if not draft:
        return ""

    # Add fraud warning if applicable
    warning = ""
    if draft.fraud_screening and draft.fraud_screening.get("is_reported"):
        risk = draft.fraud_screening.get("risk_level", "LOW")
        if risk == "HIGH":
            warning = RESPONSE_TEMPLATES["fraud_warning_high"].format(
                report_count=draft.fraud_screening.get("report_count", 0),
            ) + "\n\n"
        elif risk == "CRITICAL":
            return RESPONSE_TEMPLATES["fraud_block"]

    message = warning + RESPONSE_TEMPLATES["draft_summary"].format(
        source=draft.source_account_no_masked or "?",
        recipient_name=draft.recipient_name or "?",
        bank=draft.recipient_bank_name or draft.recipient_bank_code or "?",
        masked_account=draft.recipient_account_no_masked or "?",
        amount=f"{draft.amount:,.0f} VND" if draft.amount else "?",
        fee=f"{draft.fee:,.0f} VND" if draft.fee is not None else "?",
        total_debit=f"{draft.total_debit:,.0f} VND" if draft.total_debit else "?",
        note=draft.transfer_note or "Chuyển tiền",
    )

    return message


async def _execute_transaction(flow: FlowState, user_id: str, session_id: str) -> dict:
    """Execute the transaction via TransactionExecutor."""
    from backend.executor.transaction_executor import TransactionExecutor

    draft = flow.draft
    executor = TransactionExecutor()

    # Build executor-compatible draft dict
    exec_draft = {
        "account_no": draft.recipient_account_no,
        "bank_code": draft.recipient_bank_code,
        "bank_name": draft.recipient_bank_name,
        "recipient_name": draft.recipient_name,
        "amount": draft.amount,
        "transfer_type": "intrabank" if draft.transaction_type == "INTERNAL_TRANSFER" else "interbank",
        "note": draft.transfer_note or f"Chuyen tien cho {draft.recipient_name}",
        "action": "TRANSFER_MONEY",
    }

    result = await executor.execute(
        draft=exec_draft,
        user_id=user_id,
        session_id=session_id,
    )

    if result.success:
        from datetime import datetime as dt
        message = RESPONSE_TEMPLATES["success_receipt"].format(
            ref=result.transaction_ref or "N/A",
            time=dt.now().strftime("%d/%m/%Y %H:%M"),
            source=draft.source_account_no_masked or "?",
            recipient_name=draft.recipient_name or "?",
            bank=draft.recipient_bank_name or draft.recipient_bank_code or "?",
            masked_account=draft.recipient_account_no_masked or "?",
            amount=f"{draft.amount:,.0f} VND" if draft.amount else "?",
            fee=f"{draft.fee:,.0f} VND" if draft.fee is not None else "0 VND",
            total_debit=f"{draft.total_debit:,.0f} VND" if draft.total_debit else "?",
            balance=f"{result.balance_after:,.0f} VND" if result.balance_after else "?",
        )
        return {"message": message, "data": {"executed": True, "ref": result.transaction_ref}}
    else:
        return {
            "message": f"Giao dịch thất bại: {result.message}",
            "data": {"executed": False, "error": result.error_code},
        }


def _get_primary_account(user_id: str) -> dict | None:
    """Get user's primary payment account."""
    import psycopg2
    from backend.config import DATABASE_URL

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_no, balance
                    FROM accounts
                    WHERE cif_no = %s AND account_type = 'PAYMENT' AND status = 'ACTIVE'
                    ORDER BY balance DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if row:
                    return {"account_no": row[0], "balance": row[1]}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ORCHESTRATOR] get_primary_account error: {e}")
    return None


def _intent_display_name(intent: str) -> str:
    """Map intent code to Vietnamese display name."""
    names = {
        "TRANSACTION": "chuyển tiền",
        "FRAUD_REPORT": "báo cáo lừa đảo",
        "CARD_OPERATION": "quản lý thẻ",
        "ACCOUNT_OPERATION": "quản lý tài khoản",
        "DATA_QUERY": "tra cứu thông tin",
        "QA": "hỏi đáp",
        "FINANCE_ADVICE": "tư vấn tài chính",
    }
    return names.get(intent, intent.lower())


# ─── Bill Payment State Machine ───────────────────────────────────────────────

async def _handle_bill_new(message: str, user_id: str, session_id: str) -> dict:
    """Handle new bill payment intent — fetch billers, decide next state."""
    from backend.tools.bill_tools import get_registered_billers, lookup_unpaid_bills
    from backend.models.flow import BillDraft

    result = get_registered_billers.invoke({"user_id": user_id})

    if result.get("status") != "success" or not result.get("billers"):
        return {
            "response_message": "Bạn chưa đăng ký tài khoản thanh toán hóa đơn nào. Vui lòng đăng ký tại quầy hoặc app.",
            "response_data": {"handled": True, "task_type": "BILL_PAYMENT"},
        }

    billers = result["billers"]

    # Filter by biller type if user specified (e.g. "hóa đơn điện")
    bill_type = _detect_bill_type(message)
    if bill_type:
        filtered = [b for b in billers if b.get("biller_type") == bill_type]
        if filtered:
            billers = filtered

    # Lookup unpaid bills for each candidate
    candidates = []
    for b in billers:
        bills_result = lookup_unpaid_bills.invoke({
            "customer_bill_code": b["customer_bill_code"],
            "biller_code": b.get("biller_code", ""),
        })
        unpaid = None
        if bills_result.get("status") == "success" and bills_result.get("bills"):
            unpaid = bills_result["bills"][0]  # Take the most urgent (earliest due)
        candidates.append({
            "biller_name": b["biller_name"],
            "biller_code": b.get("biller_code", ""),
            "biller_type": b.get("biller_type", ""),
            "customer_bill_code": b["customer_bill_code"],
            "alias": b.get("alias", ""),
            "unpaid_bill": unpaid,
        })

    # Only 1 candidate → auto-select
    if len(candidates) == 1:
        return _bill_select_candidate(candidates[0], user_id)

    # Multiple → ask user to choose
    flow = FlowState(
        flow_type="BILL_PAYMENT",
        status="WAITING_BILLER_SELECTION",
        bill_draft=BillDraft(candidates=candidates),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    msg = _format_bill_candidates(candidates)
    return {
        "active_flow": serialize_flow(flow),
        "response_message": msg,
        "response_data": {"handled": True, "task_type": "BILL_PAYMENT"},
    }


async def _handle_bill_continue(flow: FlowState, message: str, user_id: str, session_id: str) -> dict:
    """Handle user's follow-up in a bill payment flow."""

    if flow.status == "WAITING_BILLER_SELECTION":
        # User is selecting a biller from the list
        candidates = flow.bill_draft.candidates if flow.bill_draft else []
        selected = _match_bill_candidate(message, candidates)

        if selected is None:
            msg = "Tôi không nhận ra lựa chọn. " + _format_bill_candidates(candidates)
            return {
                "active_flow": serialize_flow(flow),
                "response_message": msg,
            }

        return _bill_select_candidate(selected, user_id)

    if flow.status == "WAITING_BILL_CONFIRMATION":
        # User confirms or cancels the bill payment
        # This is handled by the confirmation classifier in _route_limited
        # If we reach here, it means it's unclear — ask again
        bd = flow.bill_draft
        msg = (
            f"Xác nhận thanh toán hóa đơn {bd.biller_name} "
            f"kỳ {bd.bill_period}: {bd.amount:,.0f} VND?\n"
            "Trả lời 'ok' để thanh toán hoặc 'hủy' để bỏ."
        )
        return {
            "active_flow": serialize_flow(flow),
            "response_message": msg,
        }

    # Fallback
    return {
        "active_flow": None,
        "response_message": "Đã hủy thanh toán hóa đơn.",
    }


def _bill_select_candidate(candidate: dict, user_id: str) -> dict:
    """Select a biller candidate and present bill for confirmation."""
    from backend.models.flow import BillDraft

    unpaid = candidate.get("unpaid_bill")
    if not unpaid:
        return {
            "active_flow": None,
            "response_message": f"Không có hóa đơn chưa thanh toán cho {candidate['biller_name']} ({candidate.get('alias', candidate['customer_bill_code'])}).",
            "response_data": {"handled": True, "task_type": "BILL_PAYMENT"},
        }

    amount = int(unpaid["amount_due"])
    bill_draft = BillDraft(
        bill_id=unpaid.get("bill_id"),
        biller_code=candidate.get("biller_code"),
        biller_name=candidate["biller_name"],
        biller_type=candidate.get("biller_type"),
        customer_bill_code=candidate["customer_bill_code"],
        bill_period=unpaid.get("bill_period", ""),
        amount=amount,
        due_date=unpaid.get("due_date", ""),
        alias=candidate.get("alias", ""),
    )

    flow = FlowState(
        flow_type="BILL_PAYMENT",
        status="WAITING_BILL_CONFIRMATION",
        bill_draft=bill_draft,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    alias_part = f" ({bill_draft.alias})" if bill_draft.alias else ""
    msg = (
        f"Hóa đơn {bill_draft.biller_name}{alias_part}:\n"
        f"• Mã KH: {bill_draft.customer_bill_code}\n"
        f"• Kỳ: {bill_draft.bill_period}\n"
        f"• Số tiền: {amount:,.0f} VND\n"
        f"• Hạn thanh toán: {bill_draft.due_date}\n\n"
        f"Bạn muốn thanh toán hóa đơn này không?"
    )

    return {
        "active_flow": serialize_flow(flow),
        "response_message": msg,
        "response_data": {"handled": True, "task_type": "BILL_PAYMENT"},
    }


def _format_bill_candidates(candidates: list[dict]) -> str:
    """Format candidate list for display."""
    lines = ["Bạn có các tài khoản hóa đơn sau. Bạn muốn thanh toán cho tài khoản nào?\n"]
    for i, c in enumerate(candidates, 1):
        alias_part = f" ({c['alias']})" if c.get("alias") else ""
        line = f"{i}. {c['biller_name']} — Mã KH: {c['customer_bill_code']}{alias_part}"
        unpaid = c.get("unpaid_bill")
        if unpaid:
            amount = int(unpaid["amount_due"])
            period = unpaid.get("bill_period", "")
            line += f" — Hóa đơn kỳ {period}: {amount:,.0f} VND"
        else:
            line += " — Không có hóa đơn chưa thanh toán"
        lines.append(line)
    lines.append("\nVui lòng chọn số thứ tự hoặc tên tài khoản.")
    return "\n".join(lines)


def _match_bill_candidate(message: str, candidates: list[dict]) -> dict | None:
    """Match user's selection against candidates.

    Supports: number ("1", "2"), alias ("nhà hà nội"), biller name, customer_bill_code.
    Uses accent-stripped comparison for Vietnamese text.
    """
    import unicodedata

    def _norm(s: str) -> str:
        """Strip accents and lowercase for comparison."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', s.lower())
            if unicodedata.category(c) != 'Mn'
        )

    msg = message.strip()
    msg_norm = _norm(msg)

    # Try numeric selection
    if msg.isdigit():
        idx = int(msg) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
        return None

    # Try matching by alias, biller_name, or customer_bill_code
    for c in candidates:
        alias = _norm(c.get("alias") or "")
        biller_name = _norm(c.get("biller_name") or "")
        bill_code = (c.get("customer_bill_code") or "").lower()

        if alias and (alias in msg_norm or msg_norm in alias):
            return c
        if biller_name and (biller_name in msg_norm or msg_norm in biller_name):
            return c
        if bill_code and bill_code in msg_norm:
            return c
    return None


def _detect_bill_type(message: str) -> str | None:
    """Detect bill type from user message."""
    msg = message.lower()
    if any(w in msg for w in ["điện", "evn"]):
        return "ELECTRICITY"
    if any(w in msg for w in ["nước", "water"]):
        return "WATER"
    if any(w in msg for w in ["internet", "mạng", "wifi"]):
        return "INTERNET"
    if any(w in msg for w in ["điện thoại", "phone", "di động"]):
        return "PHONE"
    return None


async def _execute_bill_payment(flow: FlowState, user_id: str, session_id: str) -> dict:
    """Execute bill payment via BillPaymentExecutor."""
    from backend.executor.bill_executor import BillPaymentExecutor

    bd = flow.bill_draft
    draft = {
        "bill_id": bd.bill_id,
        "biller_code": bd.biller_code,
        "biller_name": bd.biller_name,
        "customer_bill_code": bd.customer_bill_code,
        "bill_period": bd.bill_period,
        "amount": bd.amount,
    }

    executor = BillPaymentExecutor()
    result = await executor.execute(draft=draft, user_id=user_id, session_id=session_id)

    if result.success:
        return {"message": result.message, "data": {"executed": True, "ref": result.transaction_ref}}
    else:
        return {"message": result.message, "data": {"executed": False, "error": result.error_code}}


# ─── Top-Up State Machine ────────────────────────────────────────────────────

async def _handle_topup_new(message: str, user_id: str, session_id: str) -> dict:
    """Handle new top-up intent — extract target + amount via LLM."""
    from backend.agents.topup import run_topup_agent

    result = await run_topup_agent(message=message, user_id=user_id, session_id=session_id)
    return _topup_result_to_state(result)


async def _handle_topup_continue(flow: FlowState, message: str, user_id: str, session_id: str) -> dict:
    """Handle follow-up in top-up flow — extract missing fields."""
    from backend.agents.topup import run_topup_agent

    # Build history from existing draft so LLM knows what's already collected
    history = []
    td = flow.topup_draft
    if td:
        # Simulate prior context so LLM doesn't re-ask
        context_parts = []
        if td.topup_target:
            context_parts.append(f"số điện thoại: {td.topup_target}")
        if td.topup_provider:
            context_parts.append(f"nhà mạng: {td.topup_provider}")
        if td.amount:
            context_parts.append(f"số tiền: {td.amount:,.0f} VND")
        if context_parts:
            history.append({"role": "assistant", "message": f"Đã có thông tin: {', '.join(context_parts)}. Cần thêm gì?"})

    result = await run_topup_agent(message=message, user_id=user_id, session_id=session_id, history=history)

    # Merge with existing draft
    if result.get("status") == "draft_ready" and result.get("data"):
        data = result["data"]
        if td:
            td.topup_target = data.get("topup_target") or td.topup_target
            td.topup_provider = data.get("topup_provider") or td.topup_provider
            td.topup_type = data.get("topup_type") or td.topup_type
            td.amount = data.get("amount") or td.amount

    return _topup_result_to_state(result, existing_flow=flow)


def _topup_result_to_state(result: dict, existing_flow: FlowState | None = None) -> dict:
    """Convert topup agent result to orchestrator state update."""
    status = result.get("status", "")
    data = result.get("data", {})

    if status == "draft_ready":
        # All info extracted — present for confirmation
        td = TopUpDraft(
            topup_target=data.get("topup_target"),
            topup_provider=data.get("topup_provider", ""),
            topup_type=data.get("topup_type", "phone"),
            amount=int(data.get("amount", 0)),
        )

        flow = FlowState(
            flow_type="TOP_UP",
            status="WAITING_TOPUP_CONFIRMATION",
            topup_draft=td,
            created_at=existing_flow.created_at if existing_flow else datetime.now(),
            updated_at=datetime.now(),
        )

        provider_part = f" ({td.topup_provider})" if td.topup_provider else ""
        msg = (
            f"Xác nhận nạp tiền:\n"
            f"• Số điện thoại: {td.topup_target}{provider_part}\n"
            f"• Số tiền: {td.amount:,.0f} VND\n\n"
            f"Bạn muốn nạp tiền không?"
        )

        return {
            "active_flow": serialize_flow(flow),
            "response_message": msg,
            "response_data": {"handled": True, "task_type": "TOP_UP"},
        }

    elif status == "clarification_needed":
        # Missing info — keep collecting
        flow = existing_flow or FlowState(
            flow_type="TOP_UP",
            status="COLLECTING",
            topup_draft=TopUpDraft(
                topup_target=data.get("topup_target"),
                topup_provider=data.get("topup_provider"),
                topup_type=data.get("topup_type"),
                amount=int(data["amount"]) if data.get("amount") else None,
            ),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        if not existing_flow:
            # New flow — set draft from partial data
            pass
        flow.updated_at = datetime.now()

        return {
            "active_flow": serialize_flow(flow),
            "response_message": result.get("message", "Vui lòng cung cấp thêm thông tin."),
            "response_data": {"handled": True, "task_type": "TOP_UP"},
        }

    else:
        # info_response or cancelled — no flow needed
        return {
            "active_flow": None,
            "response_message": result.get("message", "Đã hủy nạp tiền."),
            "response_data": {"handled": True, "task_type": "TOP_UP"},
        }


async def _execute_topup(flow: FlowState, user_id: str, session_id: str) -> dict:
    """Execute top-up via TopUpExecutor."""
    from backend.executor.topup_executor import TopUpExecutor

    td = flow.topup_draft
    draft = {
        "topup_target": td.topup_target,
        "topup_provider": td.topup_provider,
        "topup_type": td.topup_type or "phone",
        "amount": td.amount,
    }

    executor = TopUpExecutor()
    result = await executor.execute(draft=draft, user_id=user_id, session_id=session_id)

    if result.success:
        return {"message": result.message, "data": {"executed": True, "ref": result.transaction_ref}}
    else:
        return {"message": result.message, "data": {"executed": False, "error": result.error_code}}
