"""Main Orchestrator Graph — Controlled Agentic Workflow.

Architecture:
  route_node → dispatch_agent_node → handle_flow_action_node → format_response_node

Design principles:
- Agent (LLM) ONLY extracts entities and resolves information
- State transitions are deterministic (no LLM decides OTP/confirm/execute)
- FlowRouter uses status-first dispatch (locked > pending_question > limited > flexible)
- Response formatting uses templates for sensitive messages (money, accounts)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
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
    RecipientResolutionPlan,
    serialize_flow,
    deserialize_flow,
)
from backend.services.flow_router import (
    FlowRouter,
    RouteDecision,
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
_flow_router = FlowRouter()


# ─── Intent Classifier ────────────────────────────────────────────────────────


async def _classify_intent(messages: list[BaseMessage]) -> str | None:
    """Classify message into intent type using LLM.

    Returns composite key like 'TRANSACTION:TRANSFER_MONEY' or just task_type.
    Returns None for QA (no flow needed).
    """
    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)

    try:
        current_message = messages[-1].content if messages else ""
        prompt_messages = [SystemMessage(content=INTENT_SYSTEM_PROMPT)]
        prompt_messages.extend(messages[:-1][-8:])
        prompt_messages.append(
            HumanMessage(content=INTENT_USER_TEMPLATE.format(message=current_message))
        )
        response = await llm.ainvoke(prompt_messages)
        data = json.loads(response.content)
        task_type = data.get("task_type", "UNKNOWN")
        operation = data.get("operation")
        if task_type == "QA":
            return None
        if task_type == "TRANSACTION" and operation:
            return f"TRANSACTION:{operation}"
        return task_type
    except Exception as e:
        logger.warning(f"[INTENT_CLF] Error: {e}")
        return None


# ─── Response Templates ───────────────────────────────────────────────────────

TEMPLATES = {
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
        "Chuyển {amount} đến {recipient_name}\n\n"
        "Để tiếp tục việc khác, bạn cần:\n"
        "1. Nhập OTP để hoàn tất giao dịch\n"
        "2. Hủy giao dịch này\n\n"
        "Bạn muốn nhập OTP hay hủy giao dịch?"
    ),
    "cancelled": "Đã hủy giao dịch.",
    "ask_valid_otp": (
        "Vui lòng nhập mã OTP 6 số đã gửi đến điện thoại của bạn, "
        "hoặc nhập \"hủy\" để hủy giao dịch."
    ),
    "ask_confirm_or_cancel": "Tôi chưa hiểu rõ. Bạn muốn xác nhận hay hủy giao dịch?",
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
}


# ─── Node: route_node ─────────────────────────────────────────────────────────


async def route_node(state: ChatState) -> dict:
    """Deterministic routing based on flow state."""
    flow = deserialize_flow(state.get("active_flow"))
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    decision = await _flow_router.route(flow, last_message)

    logger.info(
        f"[ROUTE] action={decision.action} flow_status={flow.status if flow else 'none'}"
    )

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
        intent = await _classify_intent(messages)

        if intent is None:
            # QA — answer directly without starting flow
            from backend.agents.qa import run_qa_agent

            qa_history = _serialize_message_history(messages[:-1])
            qa_result = await run_qa_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
                history=qa_history,
            )
            return {
                "response_message": qa_result["message"],
                "response_data": {"handled": True, "task_type": "QA"},
            }

        if intent == "FRAUD_REPORT":
            from backend.agents.fraud_report import run_fraud_agent

            fraud_history = _serialize_message_history(messages[:-1])
            fraud_result = await run_fraud_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
                history=fraud_history,
            )
            return {
                "response_message": fraud_result["message"],
                "response_data": {
                    "handled": True,
                    "task_type": "FRAUD_REPORT",
                    "agent_result": fraud_result,
                },
            }

        if intent and intent.startswith("TRANSACTION"):
            # Run extractor for initial fields
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
            )
            new_flow = _apply_extraction_to_flow(new_flow, result)

            return {
                "active_flow": serialize_flow(new_flow),
                "response_data": {
                    "agent_result": {
                        "extracted_fields": result.extracted_fields,
                        "recipient_resolution_plan": (
                            result.recipient_resolution_plan.model_dump()
                            if result.recipient_resolution_plan
                            else None
                        ),
                        "missing_fields": result.missing_fields,
                        "interpretation": result.interpretation,
                    }
                },
            }
        else:
            # Non-transaction intent — respond that only TRANSACTION supported in Phase 1
            return {
                "response_message": "Hiện tôi chỉ hỗ trợ chuyển tiền trong bản demo này.",
                "response_data": {"handled": True},
            }

    elif action in ("CONTINUE_COLLECTING", "ANSWER_PENDING_QUESTION"):
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

        if flow:
            flow = _apply_extraction_to_flow(flow, result)

        return {
            "active_flow": serialize_flow(flow),
            "response_data": {
                "agent_result": {
                    "extracted_fields": result.extracted_fields,
                    "recipient_resolution_plan": (
                        result.recipient_resolution_plan.model_dump()
                        if result.recipient_resolution_plan
                        else None
                    ),
                    "missing_fields": result.missing_fields,
                    "interpretation": result.interpretation,
                }
            },
        }

    elif action == "MODIFY_DRAFT":
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
            flow.status = "COLLECTING"
            flow.pending_question = None

        return {
            "active_flow": serialize_flow(flow),
            "response_data": {
                "agent_result": {
                    "extracted_fields": result.extracted_fields,
                    "recipient_resolution_plan": (
                        result.recipient_resolution_plan.model_dump()
                        if result.recipient_resolution_plan
                        else None
                    ),
                    "missing_fields": result.missing_fields,
                },
            },
        }

    # For other actions, dispatch is a pass-through
    return {}


# ─── Node: handle_flow_action_node ───────────────────────────────────────────


async def handle_flow_action_node(state: ChatState) -> dict:
    """Execute flow state transitions deterministically.

    All sensitive transitions happen here:
    - Recipient resolution + verification
    - Fee calculation
    - Draft confirmation assembly
    - OTP challenge creation / validation
    - Transaction execution
    - Flow cancellation
    """
    decision_data = state.get("route_decision", {})
    action = decision_data.get("action", "")
    flow = deserialize_flow(state.get("active_flow"))
    response_data = state.get("response_data", {})
    user_id = state["user_id"]
    session_id = state["session_id"]

    # If response already handled (QA, unsupported)
    if response_data.get("handled"):
        return {}
    if state.get("response_message"):
        return {}

    # ─── CLASSIFY_NEW_INTENT / CONTINUE_COLLECTING / MODIFY_DRAFT ─────
    if action in ("CLASSIFY_NEW_INTENT", "CONTINUE_COLLECTING", "MODIFY_DRAFT", "ANSWER_PENDING_QUESTION"):
        if not flow or not flow.draft:
            return {"response_message": "Hiện tôi chỉ hỗ trợ chuyển tiền trong bản demo này."}

        agent_result = response_data.get("agent_result", {})
        plan_data = agent_result.get("recipient_resolution_plan")

        # Step A: Resolve recipient if plan provided
        if plan_data:
            plan = RecipientResolutionPlan.model_validate(plan_data)
            flow = _resolve_recipient_from_plan(flow, user_id, plan)

        # Step B: Determine next step based on draft completeness
        flow, message = _determine_next_step(flow, user_id)

        flow.updated_at = datetime.now()
        return {
            "active_flow": serialize_flow(flow),
            "response_message": message,
        }

    # ─── CONFIRM ──────────────────────────────────────────────────────
    if action == "CONFIRM":
        if not flow:
            return {"response_message": "Không có giao dịch nào đang chờ xác nhận."}

        if flow.status == "WAITING_RECIPIENT_CONFIRMATION":
            flow = await _handle_recipient_confirmed(flow, user_id)
            if flow.status == "CANCELLED":
                return {
                    "active_flow": None,
                    "response_message": TEMPLATES["fraud_block"],
                }
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
            validation = _validator.validate_for_execution(flow.draft, user_id)
            if not validation.valid:
                message = "Không thể thực hiện giao dịch:\n" + "\n".join(
                    f"• {e}" for e in validation.errors
                )
                return {"response_message": message}

            # Create OTP challenge
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

            message = TEMPLATES["otp_request"].format(
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

    # ─── SUBMIT_OTP ───────────────────────────────────────────────────
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

            message = exec_result["message"]
            if flow.interrupted_intent:
                message += f"\n\nTiếp theo, tôi sẽ hỗ trợ bạn {_intent_display_name(flow.interrupted_intent.intent)}."

            return {
                "active_flow": None,
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
                return {
                    "active_flow": None,
                    "response_message": TEMPLATES["otp_expired"],
                }
            elif result.reason == "max_attempts":
                return {
                    "active_flow": None,
                    "response_message": TEMPLATES["otp_max_attempts"],
                }
            elif result.reason == "hash_mismatch":
                return {
                    "active_flow": None,
                    "response_message": TEMPLATES["otp_hash_mismatch"],
                }
            else:
                remaining = otp_service.get_remaining_attempts(flow.otp_challenge_id)
                message = TEMPLATES["otp_wrong"].format(remaining=remaining)
                return {
                    "active_flow": serialize_flow(flow),
                    "response_message": message,
                }

    # ─── CANCEL_ACTIVE_FLOW ───────────────────────────────────────────
    if action == "CANCEL_ACTIVE_FLOW":
        if not flow:
            return {"response_message": "Không có giao dịch nào để hủy."}

        if flow.otp_challenge_id:
            otp_service.invalidate(flow.otp_challenge_id)

        write_audit_log(
            cif_no=user_id,
            event_type="FLOW_CANCELLED",
            actor="user",
            session_id=session_id,
            event_payload={"flow_id": flow.flow_id, "status_at_cancel": flow.status},
        )

        return {
            "active_flow": None,
            "response_message": TEMPLATES["cancelled"],
        }

    # ─── INTERRUPT_LOCKED_FLOW ────────────────────────────────────────
    if action == "INTERRUPT_LOCKED_FLOW":
        if flow:
            messages = state["messages"]
            last_msg = messages[-1].content if messages else ""
            flow.interrupted_intent = InterruptedIntent(
                intent=decision_data.get("interrupted_intent", ""),
                original_message=last_msg,
            )
            flow.updated_at = datetime.now()

            message = TEMPLATES["interrupt_locked"].format(
                amount=f"{flow.draft.amount:,.0f} VND" if flow.draft and flow.draft.amount else "?",
                recipient_name=flow.draft.recipient_name if flow.draft else "?",
            )
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

    # ─── ASK_VALID_INPUT ──────────────────────────────────────────────
    if action == "ASK_VALID_INPUT":
        if flow and flow.status == "WAITING_OTP":
            return {"response_message": TEMPLATES["ask_valid_otp"]}
        elif flow and flow.status in (
            "WAITING_RECIPIENT_CONFIRMATION",
            "WAITING_DRAFT_CONFIRMATION",
        ):
            return {"response_message": TEMPLATES["ask_confirm_or_cancel"]}
        return {"response_message": "Tôi chưa hiểu rõ. Vui lòng thử lại."}

    return {}


# ─── Node: format_response_node ──────────────────────────────────────────────


async def format_response_node(state: ChatState) -> dict:
    """Final formatting — ensure response_message is always set."""
    message = state.get("response_message", "")
    if not message:
        message = "Tôi có thể giúp gì cho bạn?"
    return {"response_message": message}


# ─── Routing function ─────────────────────────────────────────────────────────


def after_route(state: ChatState) -> str:
    """Route after route_node — decide if we need agent or can handle directly."""
    decision_data = state.get("route_decision", {})
    action = decision_data.get("action", "")

    # Actions that need agent processing
    if action in ("CLASSIFY_NEW_INTENT", "CONTINUE_COLLECTING", "MODIFY_DRAFT", "ANSWER_PENDING_QUESTION"):
        return "dispatch_agent"

    # Actions that handle_flow_action can handle directly
    if action in (
        "CONFIRM",
        "CANCEL_ACTIVE_FLOW",
        "SUBMIT_OTP",
        "INTERRUPT_LOCKED_FLOW",
        "ASK_VALID_INPUT",
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

    graph.add_node("route", route_node)
    graph.add_node("dispatch_agent", dispatch_agent_node)
    graph.add_node("handle_flow_action", handle_flow_action_node)
    graph.add_node("format_response", format_response_node)

    graph.set_entry_point("route")

    graph.add_conditional_edges(
        "route",
        after_route,
        {
            "dispatch_agent": "dispatch_agent",
            "handle_flow_action": "handle_flow_action",
            "respond": "format_response",
        },
    )

    graph.add_edge("dispatch_agent", "handle_flow_action")
    graph.add_edge("handle_flow_action", "format_response")
    graph.add_edge("format_response", END)

    return graph


# ─── Checkpointer ────────────────────────────────────────────────────────────

_checkpointer = None


async def _create_checkpointer_async():
    """Create async PostgreSQL-backed checkpointer.

    Falls back to MemorySaver if PostgreSQL connection fails.
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
        logger.warning(
            f"[CHECKPOINT] AsyncPostgresSaver failed ({e}), falling back to MemorySaver"
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


async def get_checkpointer():
    """Get or create the checkpointer singleton (async)."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = await _create_checkpointer_async()
    return _checkpointer


async def compile_orchestrator():
    """Compile the orchestrator graph with async checkpointing."""
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
    if fields.get("recipient_bank_code"):
        flow.draft.recipient_bank_code = fields["recipient_bank_code"]
    if fields.get("transfer_note"):
        flow.draft.transfer_note = fields["transfer_note"]

    return flow


def _resolve_recipient_from_plan(
    flow: FlowState, user_id: str, plan: RecipientResolutionPlan
) -> FlowState:
    """Call RecipientResolver based on structured RecipientResolutionPlan."""
    if not flow.draft:
        return flow

    result = _recipient_resolver.resolve_from_plan(user_id, plan)

    # For direct_account with empty constraints, fallback to draft fields
    if plan.target == "direct_account" and not result.candidates:
        if flow.draft.recipient_account_no and flow.draft.recipient_bank_code:
            candidate = _recipient_resolver.find_by_account_no(
                flow.draft.recipient_account_no, flow.draft.recipient_bank_code
            )
            if candidate:
                result.candidates = [candidate]

    # For saved_beneficiary with empty constraints, fallback to recipient_query
    if plan.target == "saved_beneficiary" and not result.candidates:
        query = flow.draft.recipient_query
        if query:
            result.candidates = _recipient_resolver.find_by_name(user_id, query)

    # Apply copied fields (amount/note from past transaction)
    if result.copied_fields:
        if result.copied_fields.get("amount"):
            flow.draft.amount = result.copied_fields["amount"]
        if result.copied_fields.get("note"):
            flow.draft.transfer_note = result.copied_fields["note"]

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

    return flow


def _determine_next_step(flow: FlowState, user_id: str) -> tuple[FlowState, str]:
    """Determine the next step based on draft completeness."""
    if not flow.draft:
        return flow, "Hiện tôi chỉ hỗ trợ chuyển tiền trong bản demo này."

    draft = flow.draft

    # If pending question already set by resolver, format it
    if flow.pending_question and flow.pending_question.slot == "recipient_choice":
        options = flow.pending_question.options or []
        candidates_list = "\n".join(
            f"  {i + 1}. {opt['name']} — {opt['bank_name']} — {opt['account_no_masked']}"
            for i, opt in enumerate(options)
        )
        message = TEMPLATES["recipient_candidates"].format(
            count=len(options),
            query=draft.recipient_query or "?",
            candidates_list=candidates_list,
        )
        flow.status = "COLLECTING"
        return flow, message

    # No recipient at all?
    if not draft.recipient_account_no and not draft.recipient_name:
        if draft.recipient_query:
            message = TEMPLATES["recipient_not_found"].format(query=draft.recipient_query)
        else:
            message = TEMPLATES["need_recipient"]

        flow.pending_question = PendingQuestion(
            slot="recipient_query",
            question=message,
            expected_type="text",
        )
        flow.status = "COLLECTING"
        return flow, message

    # No amount?
    if not draft.amount:
        message = TEMPLATES["need_amount"]
        flow.pending_question = PendingQuestion(
            slot="amount",
            question=message,
            expected_type="amount",
        )
        flow.status = "COLLECTING"
        return flow, message

    # Have recipient (account or name) + amount → ask recipient confirmation
    if draft.recipient_account_no and not draft.recipient_verified:
        # If we have account but no name yet, show what we have
        display_name = draft.recipient_name or draft.recipient_account_no
        flow.status = "WAITING_RECIPIENT_CONFIRMATION"
        flow.pending_question = PendingQuestion(
            slot="recipient_confirmation",
            question="Xác nhận người nhận",
            expected_type="enum",
            options=[{"value": "confirm"}, {"value": "cancel"}],
        )
        message = TEMPLATES["recipient_confirm"].format(
            name=display_name,
            bank=draft.recipient_bank_name or draft.recipient_bank_code or "?",
            masked_account=draft.recipient_account_no_masked or _mask_account(draft.recipient_account_no),
        )
        return flow, message

    # Already verified
    if draft.recipient_verified and draft.amount:
        return flow, _build_draft_summary_message(flow)

    return flow, "Đang xử lý..."


async def _handle_recipient_confirmed(flow: FlowState, user_id: str) -> FlowState:
    """After user confirms recipient: verify, fraud check, compute fee."""
    draft = flow.draft

    # Verify via banking API
    verification = _recipient_resolver.verify_recipient(
        draft.recipient_account_no, draft.recipient_bank_code
    )

    if verification.get("status") == "success":
        draft.recipient_verified = True
        draft.recipient_name = verification.get("resolved_name", draft.recipient_name)
        draft.transaction_type = (
            "INTERNAL_TRANSFER"
            if verification.get("transfer_type") == "intrabank"
            else "INTERBANK_TRANSFER"
        )
    else:
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
        draft.recipient_account_no, draft.recipient_bank_code
    )
    draft.fraud_screening = fraud

    if fraud.get("risk_level") == "CRITICAL":
        flow.status = "CANCELLED"
        return flow

    # Source account
    source = _get_primary_account(user_id)
    if source:
        draft.source_account_no = source["account_no"]
        draft.source_account_no_masked = _mask_account(source["account_no"])

    # Fee
    if draft.transaction_type == "INTERBANK_TRANSFER":
        draft.fee = 5500
    else:
        draft.fee = 0
    draft.total_debit = (draft.amount or 0) + (draft.fee or 0)

    # Confirmation ID
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
    """Build transaction summary for user confirmation."""
    draft = flow.draft
    if not draft:
        return ""

    warning = ""
    if draft.fraud_screening and draft.fraud_screening.get("is_reported"):
        risk = draft.fraud_screening.get("risk_level", "LOW")
        if risk == "HIGH":
            warning = TEMPLATES["fraud_warning_high"].format(
                report_count=draft.fraud_screening.get("report_count", 0),
            ) + "\n\n"

    message = warning + TEMPLATES["draft_summary"].format(
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
        message = TEMPLATES["success_receipt"].format(
            ref=result.transaction_ref or "N/A",
            time=datetime.now().strftime("%d/%m/%Y %H:%M"),
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


def _serialize_message_history(messages: list[BaseMessage]) -> list[dict]:
    """Convert LangChain messages into the fraud agent history shape."""
    history: list[dict] = []
    for msg in messages:
        role = "assistant"
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            msg_type = msg.__class__.__name__.lower()
            if "human" in msg_type:
                role = "user"

        content = getattr(msg, "content", "")
        if content:
            history.append({"role": role, "message": content})
    return history
