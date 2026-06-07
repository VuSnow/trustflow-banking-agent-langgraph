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

import hashlib
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
    CardDraft,
    CategoryPrediction,
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
from backend.services.bill_resolver import BillResolver
from backend.services.otp_service import otp_service
from backend.services.audit_log import write_audit_log
from backend.services.langfuse_trace import get_trace_config
from backend.agents.transaction import TransactionExtractor
from backend.agents.bill_payment import BillPaymentExtractor
from backend.agents.topup import TopUpExtractor
from backend.agents.card_operation import CardOperationExtractor
from backend.services.category_classifier import CategoryClassifier
from backend.prompts.intent import INTENT_SYSTEM_PROMPT, INTENT_USER_TEMPLATE

logger = logging.getLogger(__name__)

# ─── Singletons ───────────────────────────────────────────────────────────────

_recipient_resolver = RecipientResolver()
_validator = TransactionValidator()
_extractor = TransactionExtractor()
_bill_extractor = BillPaymentExtractor()
_bill_resolver = BillResolver()
_topup_extractor = TopUpExtractor()
_card_extractor = CardOperationExtractor()
_category_classifier = CategoryClassifier()
_flow_router = FlowRouter()


# ─── Intent Classifier ────────────────────────────────────────────────────────


async def _classify_intent(message: str) -> str | None:
    """Classify message into intent type using LLM.

    Returns composite key like 'TRANSACTION:TRANSFER_MONEY' or just task_type.
    Returns None for QA (no flow needed).
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
    # ─── Bill Payment Templates ───
    "bill_select_biller": (
        "Bạn có {count} tài khoản {type_name} đã đăng ký:\n\n"
        "{biller_list}\n\n"
        "Bạn muốn thanh toán cho tài khoản nào? (Nhập số thứ tự)"
    ),
    "bill_confirm_single": (
        "Hóa đơn {type_name} cần thanh toán:\n\n"
        "• Nhà cung cấp: {biller_name}\n"
        "• Mã khách hàng: {customer_bill_code}\n"
        "• Kỳ thanh toán: {bill_period}\n"
        "• Số tiền: {amount}\n"
        "• Hạn thanh toán: {due_date}\n\n"
        "Bạn xác nhận thanh toán không?"
    ),
    "bill_confirm_multiple": (
        "Bạn có {count} hóa đơn chưa thanh toán:\n\n"
        "{bill_list}\n\n"
        "Tổng cộng: {total}\n\n"
        "Bạn muốn thanh toán tất cả không?"
    ),
    "bill_otp_request": (
        "Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.\n"
        "Vui lòng nhập OTP để hoàn tất thanh toán.\n\n"
        "Thanh toán: {biller_name} — {amount}."
    ),
    "bill_success": (
        "Thanh toán thành công.\n\n"
        "Mã giao dịch: {ref}\n"
        "Thời gian: {time}\n"
        "Nhà cung cấp: {biller_name}\n"
        "Mã khách hàng: {customer_bill_code}\n"
        "Kỳ: {bill_period}\n"
        "Số tiền: {amount}\n"
        "Số dư còn lại: {balance}"
    ),
    "bill_no_unpaid": "Không có hóa đơn {type_name} chưa thanh toán.",
    "bill_no_registered": "Bạn chưa đăng ký tài khoản thanh toán hóa đơn nào. Vui lòng đăng ký tại quầy hoặc app.",
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
    # ─── Top-Up Templates ───
    "topup_confirm": (
        "Xác nhận nạp tiền:\n\n"
        "• Số điện thoại: {target}\n"
        "• Nhà mạng: {provider}\n"
        "• Số tiền: {amount}\n\n"
        "Bạn xác nhận nạp tiền không?"
    ),
    "topup_otp_request": (
        "Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.\n"
        "Vui lòng nhập OTP để hoàn tất nạp tiền.\n\n"
        "Nạp {amount} cho {target} ({provider})."
    ),
    "topup_success": (
        "Nạp tiền thành công.\n\n"
        "Mã giao dịch: {ref}\n"
        "Thời gian: {time}\n"
        "Số điện thoại: {target}\n"
        "Nhà mạng: {provider}\n"
        "Số tiền: {amount}\n"
        "Số dư còn lại: {balance}"
    ),
    "topup_need_phone": "Bạn muốn nạp tiền cho số điện thoại nào?",
    "topup_need_amount": "Bạn muốn nạp bao nhiêu cho số {target}?",
    "topup_invalid_phone": "Số điện thoại không hợp lệ. Vui lòng nhập số bắt đầu bằng 0 (10 chữ số).",
    "topup_amount_invalid": "Số tiền nạp phải từ 10,000 đến {max_amount} VND.",
    # ─── Category Templates ───
    "category_confirm": (
        "📂 Giao dịch này thuộc loại: **{predicted_name}**\n"
        "Đúng không? Hoặc chọn:\n"
        "{alternatives_list}\n"
        "(Gõ \"bỏ qua\" nếu không muốn phân loại)"
    ),
    "category_confirmed": "✅ Đã phân loại: **{category_name}**",
    "category_saved_default": "📂 Đã lưu phân loại: **{category_name}**",
    # ─── Card Operation Templates ───
    "card_list": (
        "Bạn có {count} thẻ:\n\n"
        "{card_list}\n\n"
        "Bạn muốn thao tác với thẻ nào? (Nhập số thứ tự)"
    ),
    "card_info": (
        "Thông tin thẻ:\n\n"
        "• Số thẻ: {masked_card_no}\n"
        "• Loại: {card_type}\n"
        "• Mạng: {card_network}\n"
        "• Trạng thái: {status}\n"
        "• Tài khoản liên kết: {account_no}"
    ),
    "card_lock_confirm": (
        "Xác nhận khóa tạm thời thẻ {masked_card_no} ({card_type} {card_network})?\n\n"
        "⚠️ Thẻ sẽ không thể sử dụng cho đến khi bạn mở khóa."
    ),
    "card_unlock_confirm": (
        "Xác nhận mở khóa thẻ {masked_card_no} ({card_type} {card_network})?"
    ),
    "card_report_lost_confirm": (
        "⚠️ **CẢNH BÁO**: Báo mất thẻ {masked_card_no} ({card_type} {card_network})?\n\n"
        "Hành động này là **VĨNH VIỄN** — thẻ sẽ bị vô hiệu hóa và không thể mở khóa lại.\n"
        "Bạn có chắc chắn không?"
    ),
    "card_lock_success": "✅ Đã khóa tạm thời thẻ {masked_card_no}.",
    "card_unlock_success": "✅ Đã mở khóa thẻ {masked_card_no}.",
    "card_report_lost_success": "✅ Đã báo mất thẻ {masked_card_no}. Thẻ đã bị vô hiệu hóa vĩnh viễn.",
    "card_unlock_otp_request": (
        "Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.\n"
        "Vui lòng nhập OTP để mở khóa thẻ {masked_card_no}."
    ),
    "card_not_found": "Không tìm thấy thẻ phù hợp. Vui lòng kiểm tra lại.",
    "card_invalid_status": "Thẻ đang ở trạng thái {status}, không thể {action}.",
    "card_need_operation": "Bạn muốn làm gì với thẻ? (Khóa thẻ / Mở khóa / Báo mất / Xem thông tin)",
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
        # If user abandons category confirmation → save predicted before routing
        _category_was_cleared = False
        if flow and flow.status == "WAITING_CATEGORY_CONFIRMATION" and flow.category_prediction:
            _category_classifier.update_category(
                flow.category_prediction.transaction_ref,
                flow.category_prediction.predicted_category_id,
            )
            logger.info(
                f"[CATEGORY] Auto-saved predicted={flow.category_prediction.predicted_code} "
                f"for ref={flow.category_prediction.transaction_ref} (user switched intent)"
            )
            flow = None  # clear the category flow
            _category_was_cleared = True

        intent = await _classify_intent(last_message)

        if intent is None:
            # QA — answer directly without starting flow
            from backend.agents.qa import run_qa_agent

            qa_result = await run_qa_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
            )
            result = {
                "response_message": qa_result["message"],
                "response_data": {"handled": True, "task_type": "QA"},
            }
            if _category_was_cleared:
                result["active_flow"] = None
            return result

        if intent and intent.startswith("TRANSACTION"):
            operation = intent.split(":")[-1] if ":" in intent else ""

            if operation == "BILL_PAYMENT":
                # Bill payment flow — use bill extractor
                bill_result = await _bill_extractor.process(
                    message=last_message,
                    user_id=state["user_id"],
                    current_bill_draft=None,
                    session_id=state["session_id"],
                )

                new_flow = FlowState(
                    flow_type="BILL_PAYMENT",
                    status="COLLECTING",
                    bill_draft=BillDraft(),
                )

                # Apply extraction to bill draft
                if bill_result.biller_type:
                    new_flow.bill_draft.biller_type = bill_result.biller_type
                if bill_result.alias_hint:
                    new_flow.bill_draft.alias = bill_result.alias_hint
                if bill_result.biller_name_hint:
                    new_flow.bill_draft.biller_name = bill_result.biller_name_hint

                return {
                    "active_flow": serialize_flow(new_flow),
                    "response_data": {
                        "agent_result": {
                            "biller_type": bill_result.biller_type,
                            "alias_hint": bill_result.alias_hint,
                            "biller_name_hint": bill_result.biller_name_hint,
                            "pay_all": bill_result.pay_all,
                            "interpretation": bill_result.interpretation,
                        }
                    },
                }

            if operation == "TOP_UP":
                # Top-up flow — use topup extractor
                topup_result = await _topup_extractor.process(
                    message=last_message,
                    user_id=state["user_id"],
                    current_draft=None,
                    session_id=state["session_id"],
                )

                new_flow = FlowState(
                    flow_type="TOP_UP",
                    status="COLLECTING",
                    topup_draft=TopUpDraft(),
                )

                # Apply extraction to topup draft
                if topup_result.topup_target:
                    new_flow.topup_draft.topup_target = topup_result.topup_target
                if topup_result.topup_provider:
                    new_flow.topup_draft.topup_provider = topup_result.topup_provider
                if topup_result.topup_type:
                    new_flow.topup_draft.topup_type = topup_result.topup_type
                if topup_result.amount:
                    new_flow.topup_draft.amount = topup_result.amount

                return {
                    "active_flow": serialize_flow(new_flow),
                    "response_data": {
                        "agent_result": {
                            "topup_target": topup_result.topup_target,
                            "topup_provider": topup_result.topup_provider,
                            "topup_type": topup_result.topup_type,
                            "amount": topup_result.amount,
                            "interpretation": topup_result.interpretation,
                        }
                    },
                }

            # Transaction flow (transfer money)
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
        elif intent == "CARD_OPERATION":
            # Card operation flow — use card extractor
            cards_context = _get_user_cards_context(state["user_id"])
            card_result = await _card_extractor.process(
                message=last_message,
                user_id=state["user_id"],
                cards_context=cards_context,
                session_id=state["session_id"],
            )

            new_flow = FlowState(
                flow_type="CARD_OPERATION",
                status="COLLECTING",
                card_draft=CardDraft(
                    operation=card_result.operation,
                    card_hint_last4=card_result.card_hint_last4,
                    card_hint_type=card_result.card_hint_type,
                    card_hint_network=card_result.card_hint_network,
                ),
            )

            return {
                "active_flow": serialize_flow(new_flow),
                "response_data": {
                    "agent_result": {
                        "operation": card_result.operation,
                        "card_hint_last4": card_result.card_hint_last4,
                        "card_hint_type": card_result.card_hint_type,
                        "card_hint_network": card_result.card_hint_network,
                        "interpretation": card_result.interpretation,
                    }
                },
            }

        elif intent == "FINANCE_ADVICE":
            from backend.agents.finance_advisor import run_finance_agent

            # Build history from messages for context
            history = []
            for msg in messages[:-1]:  # exclude current message
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        history.append({"role": "user", "message": msg.content})
                    elif msg.type == "ai" and msg.content:
                        history.append({"role": "assistant", "message": msg.content})

            finance_result = await run_finance_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
                history=history or None,
            )

            finance_data = finance_result.get("data") if isinstance(finance_result, dict) else None
            if not isinstance(finance_data, dict):
                finance_data = {}
            finance_data.setdefault("handled", True)
            finance_data.setdefault("task_type", "FINANCE_ADVICE")

            result = {
                "response_message": finance_result["message"],
                "response_data": finance_data,
            }
            if _category_was_cleared:
                result["active_flow"] = None
            return result

        elif intent == "DATA_QUERY":
            from backend.agents.data_query import run_data_query_agent

            # Build history from messages for context
            history = []
            for msg in messages[:-1]:  # exclude current message
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        history.append({"role": "user", "message": msg.content})
                    elif msg.type == "ai" and msg.content:
                        history.append({"role": "assistant", "message": msg.content})

            query_result = await run_data_query_agent(
                message=last_message,
                user_id=state["user_id"],
                session_id=state["session_id"],
                history=history or None,
            )

            query_data = query_result.get("data") if isinstance(query_result, dict) else None
            if not isinstance(query_data, dict):
                query_data = {}
            query_data.setdefault("handled", True)
            query_data.setdefault("task_type", "DATA_QUERY")

            result = {
                "response_message": query_result.get("message", "Không thể truy vấn dữ liệu lúc này."),
                "response_data": query_data,
            }
            if _category_was_cleared:
                result["active_flow"] = None
            return result

        else:
            # Non-supported intent
            result = {
                "response_message": "Hiện tôi hỗ trợ chuyển tiền, thanh toán hóa đơn, nạp tiền, quản lý thẻ, tra cứu thông tin, và tư vấn tài chính.",
                "response_data": {"handled": True},
            }
            if _category_was_cleared:
                result["active_flow"] = None
            return result

    elif action in ("CONTINUE_COLLECTING", "ANSWER_PENDING_QUESTION"):
        # Category confirmation — no LLM needed, handle in handle_flow_action
        if flow and flow.status == "WAITING_CATEGORY_CONFIRMATION":
            return {}

        # For card operation flows, re-extract with context
        if flow and flow.flow_type == "CARD_OPERATION":
            # If answering a pending question (e.g. picking card by number), skip LLM
            if action == "ANSWER_PENDING_QUESTION":
                return {}
            cards_context = _get_user_cards_context(state["user_id"])
            card_result = await _card_extractor.process(
                message=last_message,
                user_id=state["user_id"],
                cards_context=cards_context,
                session_id=state["session_id"],
            )
            if flow.card_draft is None:
                flow.card_draft = CardDraft()
            if card_result.operation:
                flow.card_draft.operation = card_result.operation
            if card_result.card_hint_last4:
                flow.card_draft.card_hint_last4 = card_result.card_hint_last4
            if card_result.card_hint_type:
                flow.card_draft.card_hint_type = card_result.card_hint_type
            if card_result.card_hint_network:
                flow.card_draft.card_hint_network = card_result.card_hint_network
            return {
                "active_flow": serialize_flow(flow),
                "response_data": {
                    "agent_result": {
                        "operation": card_result.operation,
                        "card_hint_last4": card_result.card_hint_last4,
                        "interpretation": card_result.interpretation,
                    }
                },
            }

        # For bill payment flows, no LLM needed — orchestrator handles directly
        if flow and flow.flow_type == "BILL_PAYMENT":
            return {}

        # For top-up flows, use topup extractor
        if flow and flow.flow_type == "TOP_UP":
            topup_result = await _topup_extractor.process(
                message=last_message,
                user_id=state["user_id"],
                current_draft=flow.topup_draft,
                session_id=state["session_id"],
            )
            # Apply extraction
            if flow.topup_draft is None:
                flow.topup_draft = TopUpDraft()
            if topup_result.topup_target:
                flow.topup_draft.topup_target = topup_result.topup_target
            if topup_result.topup_provider:
                flow.topup_draft.topup_provider = topup_result.topup_provider
            if topup_result.topup_type:
                flow.topup_draft.topup_type = topup_result.topup_type
            if topup_result.amount:
                flow.topup_draft.amount = topup_result.amount

            return {
                "active_flow": serialize_flow(flow),
                "response_data": {
                    "agent_result": {
                        "topup_target": topup_result.topup_target,
                        "topup_provider": topup_result.topup_provider,
                        "topup_type": topup_result.topup_type,
                        "amount": topup_result.amount,
                        "interpretation": topup_result.interpretation,
                    }
                },
            }

        # Run extractor with current draft context (transaction flows)
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
        # Bill payment doesn't support modify — cancel and restart
        if flow and flow.flow_type == "BILL_PAYMENT":
            return {
                "active_flow": None,
                "response_message": "Đã hủy. Bạn muốn thanh toán hóa đơn nào?",
            }

        # Top-up doesn't support modify — cancel and restart
        if flow and flow.flow_type == "TOP_UP":
            return {
                "active_flow": None,
                "response_message": "Đã hủy. Bạn muốn nạp tiền cho số nào?",
            }

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

    # ─── ANSWER_PENDING_QUESTION for category selection ───────────────
    if action == "ANSWER_PENDING_QUESTION" and flow and flow.status == "WAITING_CATEGORY_CONFIRMATION":
        category_choice = decision_data.get("data", {}).get("category_choice")
        if category_choice and flow.category_prediction:
            _category_classifier.update_category(
                flow.category_prediction.transaction_ref,
                category_choice["category_id"],
            )
            message = TEMPLATES["category_confirmed"].format(
                category_name=category_choice["name"]
            )
            return {
                "active_flow": None,
                "response_message": message,
            }

    # ─── CLASSIFY_NEW_INTENT / CONTINUE_COLLECTING / MODIFY_DRAFT ─────
    if action in ("CLASSIFY_NEW_INTENT", "CONTINUE_COLLECTING", "MODIFY_DRAFT", "ANSWER_PENDING_QUESTION"):
        if not flow:
            return {"response_message": "Hiện tôi chỉ hỗ trợ chuyển tiền, thanh toán hóa đơn, nạp tiền, và quản lý thẻ."}

        # ── Card Operation Flow ──
        if flow.flow_type == "CARD_OPERATION":
            flow, message = _handle_card_collecting(flow, user_id, response_data, action, decision_data)
            flow.updated_at = datetime.now()
            if flow.status == "COMPLETED":
                return {
                    "active_flow": None,
                    "response_message": message,
                }
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        # ── Bill Payment Flow ──
        if flow.flow_type == "BILL_PAYMENT":
            flow, message = _handle_bill_collecting(flow, user_id, response_data, action, decision_data)
            flow.updated_at = datetime.now()
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        # ── Top-Up Flow ──
        if flow.flow_type == "TOP_UP":
            flow, message = _handle_topup_collecting(flow, user_id, response_data)
            flow.updated_at = datetime.now()
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        # ── Transaction Flow ──
        if not flow.draft:
            return {"response_message": "Hiện tôi chỉ hỗ trợ chuyển tiền, thanh toán hóa đơn, hoặc nạp tiền."}

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

        # ── Category: WAITING_CATEGORY_CONFIRMATION → save predicted ──
        if flow.status == "WAITING_CATEGORY_CONFIRMATION" and flow.category_prediction:
            prediction = flow.category_prediction
            _category_classifier.update_category(
                prediction.transaction_ref, prediction.predicted_category_id
            )
            message = TEMPLATES["category_confirmed"].format(
                category_name=prediction.predicted_name
            )
            return {
                "active_flow": None,
                "response_message": message,
            }

        # ── Bill: WAITING_BILL_CONFIRMATION → OTP ──
        if flow.status == "WAITING_BILL_CONFIRMATION" and flow.flow_type == "BILL_PAYMENT":
            bill_draft = flow.bill_draft
            if not bill_draft or not bill_draft.bill_id:
                return {"response_message": "Thông tin hóa đơn không đầy đủ."}

            # Create OTP challenge (use bill_id as hash)
            summary_hash = hashlib.sha256(
                f"{bill_draft.bill_id}:{bill_draft.amount}:{bill_draft.customer_bill_code}".encode()
            ).hexdigest()[:32]

            challenge_id = otp_service.create_challenge(
                flow_id=flow.flow_id,
                user_id=user_id,
                summary_hash=summary_hash,
            )
            flow.otp_challenge_id = challenge_id
            flow.status = "WAITING_OTP"
            flow.pending_question = PendingQuestion(
                slot="otp",
                question="Nhập mã OTP",
                expected_type="otp",
            )
            flow.updated_at = datetime.now()

            message = TEMPLATES["bill_otp_request"].format(
                biller_name=bill_draft.biller_name or "?",
                amount=f"{bill_draft.amount:,.0f} VND" if bill_draft.amount else "?",
            )

            write_audit_log(
                cif_no=user_id,
                event_type="BILL_OTP_CHALLENGE_CREATED",
                actor="system",
                session_id=session_id,
                event_payload={"challenge_id": challenge_id, "bill_id": bill_draft.bill_id},
            )
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        # ── TopUp: WAITING_TOPUP_CONFIRMATION → OTP ──
        if flow.status == "WAITING_TOPUP_CONFIRMATION" and flow.flow_type == "TOP_UP":
            topup_draft = flow.topup_draft
            if not topup_draft or not topup_draft.topup_target or not topup_draft.amount:
                return {"response_message": "Thông tin nạp tiền không đầy đủ."}

            # Create OTP challenge
            summary_hash = hashlib.sha256(
                f"{topup_draft.topup_target}:{topup_draft.amount}:{topup_draft.topup_provider}".encode()
            ).hexdigest()[:32]

            challenge_id = otp_service.create_challenge(
                flow_id=flow.flow_id,
                user_id=user_id,
                summary_hash=summary_hash,
            )
            flow.otp_challenge_id = challenge_id
            flow.status = "WAITING_OTP"
            flow.pending_question = PendingQuestion(
                slot="otp",
                question="Nhập mã OTP",
                expected_type="otp",
            )
            flow.updated_at = datetime.now()

            message = TEMPLATES["topup_otp_request"].format(
                target=topup_draft.topup_target,
                provider=topup_draft.topup_provider or "?",
                amount=f"{topup_draft.amount:,.0f} VND",
            )

            write_audit_log(
                cif_no=user_id,
                event_type="TOPUP_OTP_CHALLENGE_CREATED",
                actor="system",
                session_id=session_id,
                event_payload={"challenge_id": challenge_id, "target": topup_draft.topup_target},
            )
            return {
                "active_flow": serialize_flow(flow),
                "response_message": message,
            }

        # ── Card: WAITING_CARD_CONFIRMATION → Execute or OTP ──
        if flow.status == "WAITING_CARD_CONFIRMATION" and flow.flow_type == "CARD_OPERATION":
            card_draft = flow.card_draft
            if not card_draft or not card_draft.card_id or not card_draft.operation:
                return {"response_message": "Thông tin thẻ không đầy đủ."}

            if card_draft.operation == "UNLOCK_CARD":
                # Unlock needs OTP
                summary_hash = hashlib.sha256(
                    f"{card_draft.card_id}:{card_draft.operation}".encode()
                ).hexdigest()[:32]
                challenge_id = otp_service.create_challenge(
                    flow_id=flow.flow_id,
                    user_id=user_id,
                    summary_hash=summary_hash,
                )
                flow.otp_challenge_id = challenge_id
                flow.status = "WAITING_OTP"
                flow.pending_question = PendingQuestion(
                    slot="otp",
                    question="Nhập mã OTP",
                    expected_type="otp",
                )
                flow.updated_at = datetime.now()
                message = TEMPLATES["card_unlock_otp_request"].format(
                    masked_card_no=card_draft.masked_card_no or "?",
                )
                write_audit_log(
                    cif_no=user_id,
                    event_type="CARD_OTP_CHALLENGE_CREATED",
                    actor="system",
                    session_id=session_id,
                    event_payload={"challenge_id": challenge_id, "operation": "UNLOCK_CARD"},
                )
                return {
                    "active_flow": serialize_flow(flow),
                    "response_message": message,
                }
            else:
                # LOCK_CARD and REPORT_LOST don't need OTP — execute directly
                exec_result = _execute_card_operation(card_draft, user_id, session_id)
                flow.status = "COMPLETED"
                flow.updated_at = datetime.now()
                return {
                    "active_flow": None,
                    "response_message": exec_result["message"],
                }

        if flow.status == "WAITING_RECIPIENT_CONFIRMATION":
            flow = await _handle_recipient_confirmed(flow, user_id)
            if flow.status == "CANCELLED":
                return {
                    "active_flow": None,
                    "response_message": TEMPLATES["fraud_block"],
                }
            message = _build_draft_summary_message(flow, user_id)
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

        # Compute summary hash based on flow type
        if flow.flow_type == "BILL_PAYMENT" and flow.bill_draft:
            bd = flow.bill_draft
            current_hash = hashlib.sha256(
                f"{bd.bill_id}:{bd.amount}:{bd.customer_bill_code}".encode()
            ).hexdigest()[:32]
        elif flow.flow_type == "TOP_UP" and flow.topup_draft:
            td = flow.topup_draft
            current_hash = hashlib.sha256(
                f"{td.topup_target}:{td.amount}:{td.topup_provider}".encode()
            ).hexdigest()[:32]
        elif flow.flow_type == "CARD_OPERATION" and flow.card_draft:
            cd = flow.card_draft
            current_hash = hashlib.sha256(
                f"{cd.card_id}:{cd.operation}".encode()
            ).hexdigest()[:32]
        else:
            current_hash = flow.draft.summary_hash()

        result = otp_service.validate(
            challenge_id=flow.otp_challenge_id,
            otp_input=otp_input,
            current_summary_hash=current_hash,
        )

        if result.valid:
            write_audit_log(
                cif_no=user_id,
                event_type="OTP_VALIDATED",
                actor="system",
                session_id=session_id,
                event_payload={"success": True},
            )

            if flow.flow_type == "BILL_PAYMENT":
                # Execute bill payment
                flow.status = "EXECUTING"
                exec_result = await _execute_bill_payment(flow, user_id, session_id)
                flow.status = "COMPLETED"
                flow.updated_at = datetime.now()
                return {
                    "active_flow": None,
                    "response_message": exec_result["message"],
                    "response_data": exec_result.get("data", {}),
                }
            elif flow.flow_type == "TOP_UP":
                # Execute top-up
                flow.status = "EXECUTING"
                exec_result = await _execute_topup(flow, user_id, session_id)
                flow.status = "COMPLETED"
                flow.updated_at = datetime.now()
                return {
                    "active_flow": None,
                    "response_message": exec_result["message"],
                    "response_data": exec_result.get("data", {}),
                }
            elif flow.flow_type == "CARD_OPERATION":
                # Execute card unlock after OTP
                exec_result = _execute_card_operation(flow.card_draft, user_id, session_id)
                flow.status = "COMPLETED"
                flow.updated_at = datetime.now()
                return {
                    "active_flow": None,
                    "response_message": exec_result["message"],
                }
            else:
                # Execute transaction
                flow.draft.idempotency_key = f"{flow.flow_id}:{flow.draft.confirmation_id}"
                flow.status = "EXECUTING"

                exec_result = await _execute_transaction(flow, user_id, session_id)
                flow.status = "COMPLETED"
                flow.updated_at = datetime.now()

            message = exec_result["message"]
            if flow.interrupted_intent:
                message += f"\n\nTiếp theo, tôi sẽ hỗ trợ bạn {_intent_display_name(flow.interrupted_intent.intent)}."

            # After successful TRANSACTION execution → predict category and ask user
            if exec_result.get("data", {}).get("executed") and flow.flow_type == "TRANSACTION":
                tx_ref = exec_result["data"].get("ref", "")
                category_result = await _predict_category(flow, user_id, tx_ref)
                if category_result:
                    # Transition to category confirmation
                    flow.status = "WAITING_CATEGORY_CONFIRMATION"
                    flow.category_prediction = CategoryPrediction(
                        transaction_ref=tx_ref,
                        predicted_category_id=category_result["predicted_category_id"],
                        predicted_code=category_result["predicted_code"],
                        predicted_name=category_result["predicted_name"],
                        confidence=category_result["confidence"],
                        alternatives=category_result["alternatives"],
                    )
                    flow.updated_at = datetime.now()

                    # Format category question
                    alternatives_list = "\n".join(
                        f"  {i+1}. {alt['name']}"
                        for i, alt in enumerate(category_result["alternatives"])
                    )
                    category_msg = TEMPLATES["category_confirm"].format(
                        predicted_name=category_result["predicted_name"],
                        alternatives_list=alternatives_list,
                    )

                    message += f"\n\n{category_msg}"
                    return {
                        "active_flow": serialize_flow(flow),
                        "response_message": message,
                        "response_data": exec_result.get("data", {}),
                    }

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

        # Category skip: save predicted value silently
        if flow.status == "WAITING_CATEGORY_CONFIRMATION" and flow.category_prediction:
            _category_classifier.update_category(
                flow.category_prediction.transaction_ref,
                flow.category_prediction.predicted_category_id,
            )
            message = TEMPLATES["category_saved_default"].format(
                category_name=flow.category_prediction.predicted_name
            )
            return {
                "active_flow": None,
                "response_message": message,
            }

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

            if flow.flow_type == "BILL_PAYMENT" and flow.bill_draft:
                amount_str = f"{flow.bill_draft.amount:,.0f} VND" if flow.bill_draft.amount else "?"
                name_str = flow.bill_draft.biller_name or "hóa đơn"
            elif flow.flow_type == "TOP_UP" and flow.topup_draft:
                amount_str = f"{flow.topup_draft.amount:,.0f} VND" if flow.topup_draft.amount else "?"
                name_str = flow.topup_draft.topup_target or "nạp tiền"
            elif flow.flow_type == "CARD_OPERATION" and flow.card_draft:
                amount_str = flow.card_draft.operation or "thao tác thẻ"
                name_str = flow.card_draft.masked_card_no or "thẻ"
            else:
                amount_str = f"{flow.draft.amount:,.0f} VND" if flow.draft and flow.draft.amount else "?"
                name_str = flow.draft.recipient_name if flow.draft else "?"

            message = TEMPLATES["interrupt_locked"].format(
                amount=amount_str,
                recipient_name=name_str,
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
            "WAITING_BILL_CONFIRMATION",
            "WAITING_TOPUP_CONFIRMATION",
            "WAITING_CARD_CONFIRMATION",
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
        return flow, _build_draft_summary_message(flow, user_id)

    return flow, "Đang xử lý..."


async def _handle_recipient_confirmed(flow: FlowState, user_id: str) -> FlowState:
    """After user confirms recipient: verify, fraud check, compute fee."""
    draft = flow.draft

    # Resolve bank_code from bank_name if code is missing/unknown
    if (not draft.recipient_bank_code or draft.recipient_bank_code.lower() == "unknown") and draft.recipient_bank_name:
        draft.recipient_bank_code = draft.recipient_bank_name.upper()

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


def _build_draft_summary_message(flow: FlowState, user_id: str = "") -> str:
    """Build transaction summary for user confirmation."""
    draft = flow.draft
    if not draft:
        return ""

    # Risk gauge (replaces simple text warning)
    from backend.services.risk_assessor import assess_transaction_risk, format_risk_gauge

    risk_result = assess_transaction_risk(
        user_id=user_id,
        recipient_account_no=draft.recipient_account_no or "",
        recipient_bank_code=draft.recipient_bank_code,
        amount=draft.amount,
        fraud_screening=draft.fraud_screening,
    )
    risk_gauge = format_risk_gauge(risk_result)

    warning = ""
    if risk_gauge:
        warning = risk_gauge + "\n\n"
    elif draft.fraud_screening and draft.fraud_screening.get("is_reported"):
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
        "BILL_PAYMENT": "thanh toán hóa đơn",
        "FRAUD_REPORT": "báo cáo lừa đảo",
        "CARD_OPERATION": "quản lý thẻ",
        "ACCOUNT_OPERATION": "quản lý tài khoản",
        "DATA_QUERY": "tra cứu thông tin",
        "QA": "hỏi đáp",
        "FINANCE_ADVICE": "tư vấn tài chính",
    }
    return names.get(intent, intent.lower())


# ─── Bill Payment Helpers ─────────────────────────────────────────────────────


def _handle_bill_collecting(
    flow: FlowState,
    user_id: str,
    response_data: dict,
    action: str,
    decision_data: dict,
) -> tuple[FlowState, str]:
    """Handle bill payment flow in COLLECTING / WAITING_BILLER_SELECTION state.

    Resolution logic:
    1. Query BillResolver with extracted filters
    2. If 0 billers: inform user
    3. If 1 biller with 1 unpaid bill: show confirmation
    4. If 1 biller with multiple bills: show list, ask confirm all
    5. If multiple billers: ask user to select
    """
    bill_draft = flow.bill_draft
    if not bill_draft:
        bill_draft = BillDraft()
        flow.bill_draft = bill_draft

    agent_result = response_data.get("agent_result", {})

    # Handle biller selection answer
    if action == "ANSWER_PENDING_QUESTION" and flow.pending_question:
        if flow.pending_question.slot == "biller_choice":
            choice = decision_data.get("data", {}).get("choice")
            if choice:
                bill_draft.biller_code = choice.get("biller_code")
                bill_draft.biller_name = choice.get("biller_name")
                bill_draft.biller_type = choice.get("biller_type")
                bill_draft.customer_bill_code = choice.get("customer_bill_code")
                bill_draft.alias = choice.get("alias")
                flow.pending_question = None

    # Apply fresh extraction if available
    if agent_result:
        if agent_result.get("biller_type"):
            bill_draft.biller_type = agent_result["biller_type"]
        if agent_result.get("alias_hint"):
            bill_draft.alias = agent_result["alias_hint"]
        if agent_result.get("biller_name_hint"):
            bill_draft.biller_name = agent_result["biller_name_hint"]

    pay_all = agent_result.get("pay_all", False)

    # If we already have a specific customer_bill_code (from selection), lookup bills directly
    if bill_draft.customer_bill_code:
        bills = _bill_resolver.lookup_unpaid_bills(
            [bill_draft.customer_bill_code],
            biller_code=bill_draft.biller_code,
        )
        if not bills:
            type_name = _biller_type_display(bill_draft.biller_type)
            flow.status = "COLLECTING"
            return flow, f"Không có hóa đơn {type_name} chưa thanh toán cho mã {bill_draft.customer_bill_code}."

        # Pick the first bill (most urgent by due_date)
        bill = bills[0]
        bill_draft.bill_id = bill.bill_id
        bill_draft.biller_code = bill.biller_code
        bill_draft.biller_name = bill.biller_name
        bill_draft.biller_type = bill.biller_type
        bill_draft.customer_bill_code = bill.customer_bill_code
        bill_draft.bill_period = bill.bill_period
        bill_draft.amount = bill.amount_due
        bill_draft.due_date = bill.due_date

        if len(bills) == 1:
            flow.status = "WAITING_BILL_CONFIRMATION"
            flow.pending_question = PendingQuestion(
                slot="bill_confirmation",
                question="Xác nhận thanh toán hóa đơn",
                expected_type="enum",
                options=[{"value": "confirm"}, {"value": "cancel"}],
            )
            message = TEMPLATES["bill_confirm_single"].format(
                type_name=_biller_type_display(bill.biller_type),
                biller_name=bill.biller_name,
                customer_bill_code=bill.customer_bill_code,
                bill_period=bill.bill_period,
                amount=f"{bill.amount_due:,.0f} VND",
                due_date=bill.due_date,
            )
            return flow, message
        else:
            # Multiple bills for same biller — sum them
            total = sum(b.amount_due for b in bills)
            bill_draft.amount = total
            # Store all bill IDs in candidates for batch payment
            bill_draft.candidates = [
                {
                    "bill_id": b.bill_id,
                    "bill_period": b.bill_period,
                    "amount_due": b.amount_due,
                    "due_date": b.due_date,
                }
                for b in bills
            ]
            flow.status = "WAITING_BILL_CONFIRMATION"
            flow.pending_question = PendingQuestion(
                slot="bill_confirmation",
                question="Xác nhận thanh toán hóa đơn",
                expected_type="enum",
                options=[{"value": "confirm"}, {"value": "cancel"}],
            )
            bill_list = "\n".join(
                f"  {i+1}. Kỳ {b.bill_period} — {b.amount_due:,.0f} VND (hạn {b.due_date})"
                for i, b in enumerate(bills)
            )
            message = TEMPLATES["bill_confirm_multiple"].format(
                count=len(bills),
                bill_list=bill_list,
                total=f"{total:,.0f} VND",
            )
            return flow, message

    # Full resolution: find billers + bills
    resolution = _bill_resolver.resolve(
        user_id=user_id,
        biller_type=bill_draft.biller_type,
        alias_hint=bill_draft.alias,
        biller_name_hint=bill_draft.biller_name,
        pay_all=pay_all,
    )

    if resolution.message:
        # No billers or no unpaid bills
        flow.status = "COLLECTING"
        return flow, resolution.message

    billers = resolution.billers
    unpaid_bills = resolution.unpaid_bills

    # Multiple billers of same type → ask user to select
    if len(billers) > 1 and not pay_all:
        flow.status = "COLLECTING"
        flow.pending_question = PendingQuestion(
            slot="biller_choice",
            question=f"Chọn tài khoản thanh toán",
            expected_type="recipient_choice",
            options=[
                {
                    "biller_code": b.biller_code,
                    "biller_name": b.biller_name,
                    "biller_type": b.biller_type,
                    "customer_bill_code": b.customer_bill_code,
                    "alias": b.alias,
                }
                for b in billers
            ],
        )
        type_name = _biller_type_display(bill_draft.biller_type)
        biller_list = "\n".join(
            f"  {i+1}. {b.biller_name} — {b.customer_bill_code}" + (f" ({b.alias})" if b.alias else "")
            for i, b in enumerate(billers)
        )
        message = TEMPLATES["bill_select_biller"].format(
            count=len(billers),
            type_name=type_name,
            biller_list=biller_list,
        )
        return flow, message

    # Single biller (or pay_all) → show bill confirmation
    if len(unpaid_bills) == 1:
        bill = unpaid_bills[0]
        bill_draft.bill_id = bill.bill_id
        bill_draft.biller_code = bill.biller_code
        bill_draft.biller_name = bill.biller_name
        bill_draft.biller_type = bill.biller_type
        bill_draft.customer_bill_code = bill.customer_bill_code
        bill_draft.bill_period = bill.bill_period
        bill_draft.amount = bill.amount_due
        bill_draft.due_date = bill.due_date

        flow.status = "WAITING_BILL_CONFIRMATION"
        flow.pending_question = PendingQuestion(
            slot="bill_confirmation",
            question="Xác nhận thanh toán hóa đơn",
            expected_type="enum",
            options=[{"value": "confirm"}, {"value": "cancel"}],
        )
        message = TEMPLATES["bill_confirm_single"].format(
            type_name=_biller_type_display(bill.biller_type),
            biller_name=bill.biller_name,
            customer_bill_code=bill.customer_bill_code,
            bill_period=bill.bill_period,
            amount=f"{bill.amount_due:,.0f} VND",
            due_date=bill.due_date,
        )
        return flow, message
    else:
        # Multiple bills
        # For single biller, pick first bill for primary draft
        bill = unpaid_bills[0]
        total = resolution.total_amount
        bill_draft.bill_id = bill.bill_id
        bill_draft.biller_code = bill.biller_code
        bill_draft.biller_name = bill.biller_name
        bill_draft.biller_type = bill.biller_type
        bill_draft.customer_bill_code = bill.customer_bill_code
        bill_draft.bill_period = bill.bill_period
        bill_draft.amount = total if pay_all else bill.amount_due
        bill_draft.due_date = bill.due_date
        bill_draft.candidates = [
            {
                "bill_id": b.bill_id,
                "biller_name": b.biller_name,
                "bill_period": b.bill_period,
                "amount_due": b.amount_due,
                "due_date": b.due_date,
            }
            for b in unpaid_bills
        ]

        flow.status = "WAITING_BILL_CONFIRMATION"
        flow.pending_question = PendingQuestion(
            slot="bill_confirmation",
            question="Xác nhận thanh toán hóa đơn",
            expected_type="enum",
            options=[{"value": "confirm"}, {"value": "cancel"}],
        )
        bill_list = "\n".join(
            f"  {i+1}. {b.biller_name} — kỳ {b.bill_period} — {b.amount_due:,.0f} VND (hạn {b.due_date})"
            for i, b in enumerate(unpaid_bills)
        )
        message = TEMPLATES["bill_confirm_multiple"].format(
            count=len(unpaid_bills),
            bill_list=bill_list,
            total=f"{total:,.0f} VND",
        )
        return flow, message


def _biller_type_display(biller_type: str | None) -> str:
    """Map biller type to Vietnamese display."""
    if not biller_type:
        return "hóa đơn"
    return {
        "ELECTRICITY": "điện",
        "WATER": "nước",
        "INTERNET": "internet",
        "PHONE_POSTPAID": "điện thoại trả sau",
    }.get(biller_type, "hóa đơn")


async def _execute_bill_payment(flow: FlowState, user_id: str, session_id: str) -> dict:
    """Execute bill payment via BillPaymentExecutor."""
    from backend.executor.bill_executor import BillPaymentExecutor

    bill_draft = flow.bill_draft
    executor = BillPaymentExecutor()

    exec_draft = {
        "bill_id": bill_draft.bill_id,
        "biller_code": bill_draft.biller_code,
        "customer_bill_code": bill_draft.customer_bill_code,
        "amount": bill_draft.amount,
    }

    result = await executor.execute(
        draft=exec_draft,
        user_id=user_id,
        session_id=session_id,
    )

    if result.success:
        message = TEMPLATES["bill_success"].format(
            ref=result.transaction_ref or "N/A",
            time=datetime.now().strftime("%d/%m/%Y %H:%M"),
            biller_name=bill_draft.biller_name or "?",
            customer_bill_code=bill_draft.customer_bill_code or "?",
            bill_period=bill_draft.bill_period or "?",
            amount=f"{bill_draft.amount:,.0f} VND" if bill_draft.amount else "?",
            balance=f"{result.balance_after:,.0f} VND" if result.balance_after else "?",
        )
        return {"message": message, "data": {"executed": True, "ref": result.transaction_ref}}
    else:
        return {
            "message": f"Thanh toán thất bại: {result.message}",
            "data": {"executed": False, "error": result.error_code},
        }


# ─── Top-Up Helpers ───────────────────────────────────────────────────────────


def _handle_topup_collecting(
    flow: FlowState,
    user_id: str,
    response_data: dict,
) -> tuple[FlowState, str]:
    """Handle top-up flow collecting state.

    Validation logic:
    1. Need topup_target (phone number)
    2. Need amount (10k-500k for phone, 10k-10M for wallet)
    3. Validate phone format
    4. If both present → show confirmation
    """
    import re

    topup_draft = flow.topup_draft
    if not topup_draft:
        topup_draft = TopUpDraft()
        flow.topup_draft = topup_draft

    # Apply agent_result if available
    agent_result = response_data.get("agent_result", {})
    if agent_result:
        if agent_result.get("topup_target"):
            topup_draft.topup_target = agent_result["topup_target"]
        if agent_result.get("topup_provider"):
            topup_draft.topup_provider = agent_result["topup_provider"]
        if agent_result.get("topup_type"):
            topup_draft.topup_type = agent_result["topup_type"]
        if agent_result.get("amount"):
            topup_draft.amount = agent_result["amount"]

    # Default type
    if not topup_draft.topup_type:
        topup_draft.topup_type = "phone"

    # Step 1: Need phone number?
    if not topup_draft.topup_target:
        flow.pending_question = PendingQuestion(
            slot="topup_target",
            question=TEMPLATES["topup_need_phone"],
            expected_type="text",
        )
        flow.status = "COLLECTING"
        return flow, TEMPLATES["topup_need_phone"]

    # Step 2: Validate phone format
    phone = topup_draft.topup_target.strip()
    if not re.match(r"^0\d{9}$", phone):
        flow.pending_question = PendingQuestion(
            slot="topup_target",
            question=TEMPLATES["topup_invalid_phone"],
            expected_type="text",
        )
        topup_draft.topup_target = None
        flow.status = "COLLECTING"
        return flow, TEMPLATES["topup_invalid_phone"]

    # Step 3: Detect provider from prefix if not set
    if not topup_draft.topup_provider:
        topup_draft.topup_provider = _detect_carrier(phone)

    # Step 4: Need amount?
    if not topup_draft.amount:
        message = TEMPLATES["topup_need_amount"].format(target=phone)
        flow.pending_question = PendingQuestion(
            slot="topup_amount",
            question=message,
            expected_type="amount",
        )
        flow.status = "COLLECTING"
        return flow, message

    # Step 5: Validate amount
    max_amount = 500_000 if topup_draft.topup_type == "phone" else 10_000_000
    if topup_draft.amount < 10_000 or topup_draft.amount > max_amount:
        message = TEMPLATES["topup_amount_invalid"].format(
            max_amount=f"{max_amount:,.0f}",
        )
        topup_draft.amount = None
        flow.pending_question = PendingQuestion(
            slot="topup_amount",
            question=message,
            expected_type="amount",
        )
        flow.status = "COLLECTING"
        return flow, message

    # Step 6: All valid → show confirmation
    flow.status = "WAITING_TOPUP_CONFIRMATION"
    flow.pending_question = PendingQuestion(
        slot="topup_confirmation",
        question="Xác nhận nạp tiền",
        expected_type="enum",
        options=[{"value": "confirm"}, {"value": "cancel"}],
    )
    message = TEMPLATES["topup_confirm"].format(
        target=phone,
        provider=topup_draft.topup_provider or "Không xác định",
        amount=f"{topup_draft.amount:,.0f} VND",
    )
    return flow, message


def _detect_carrier(phone: str) -> str:
    """Detect Vietnamese carrier from phone prefix."""
    prefix3 = phone[:3]
    prefix4 = phone[:4]

    # Viettel: 086, 096, 097, 098, 032-036
    if prefix3 in ("086", "096", "097", "098"):
        return "Viettel"
    if prefix4 in ("0320", "0321", "0322", "0323", "0324", "0325", "0326", "0327", "0328", "0329",
                   "0330", "0331", "0332", "0333", "0334", "0335", "0336", "0337", "0338", "0339",
                   "0340", "0341", "0342", "0343", "0344", "0345", "0346", "0347", "0348", "0349",
                   "0350", "0351", "0352", "0353", "0354", "0355", "0356", "0357", "0358", "0359",
                   "0360", "0361", "0362", "0363", "0364", "0365", "0366", "0367", "0368", "0369"):
        return "Viettel"

    # Mobifone: 089, 090, 093, 070-079
    if prefix3 in ("089", "090", "093"):
        return "Mobifone"
    if prefix3 in ("070", "071", "072", "073", "074", "075", "076", "077", "078", "079"):
        return "Mobifone"

    # Vinaphone: 088, 091, 094, 081-085
    if prefix3 in ("088", "091", "094"):
        return "Vinaphone"
    if prefix3 in ("081", "082", "083", "084", "085"):
        return "Vinaphone"

    # Vietnamobile: 092, 056, 058
    if prefix3 in ("092", "056", "058"):
        return "Vietnamobile"

    return "Không xác định"


async def _execute_topup(flow: FlowState, user_id: str, session_id: str) -> dict:
    """Execute top-up via TopUpExecutor."""
    from backend.executor.topup_executor import TopUpExecutor

    topup_draft = flow.topup_draft
    executor = TopUpExecutor()

    exec_draft = {
        "topup_target": topup_draft.topup_target,
        "topup_provider": topup_draft.topup_provider,
        "topup_type": topup_draft.topup_type or "phone",
        "amount": topup_draft.amount,
    }

    result = await executor.execute(
        draft=exec_draft,
        user_id=user_id,
        session_id=session_id,
    )

    if result.success:
        message = TEMPLATES["topup_success"].format(
            ref=result.transaction_ref or "N/A",
            time=datetime.now().strftime("%d/%m/%Y %H:%M"),
            target=topup_draft.topup_target or "?",
            provider=topup_draft.topup_provider or "?",
            amount=f"{topup_draft.amount:,.0f} VND" if topup_draft.amount else "?",
            balance=f"{result.balance_after:,.0f} VND" if result.balance_after else "?",
        )
        return {"message": message, "data": {"executed": True, "ref": result.transaction_ref}}
    else:
        return {
            "message": f"Nạp tiền thất bại: {result.message}",
            "data": {"executed": False, "error": result.error_code},
        }


# ─── Category Prediction Helper ──────────────────────────────────────────────


async def _predict_category(flow: FlowState, user_id: str, tx_ref: str) -> dict | None:
    """Predict category for a completed transaction.

    Returns prediction dict or None if prediction fails/not applicable.
    """
    draft = flow.draft
    if not draft:
        return None

    try:
        prediction = await _category_classifier.predict(
            user_id=user_id,
            description=draft.transfer_note or f"Chuyen tien cho {draft.recipient_name}",
            amount=draft.amount or 0,
            counterparty_name=draft.recipient_name,
            counterparty_account_no=draft.recipient_account_no,
            bank_code=draft.recipient_bank_code,
        )
        if prediction and prediction.get("predicted_category_id"):
            return prediction
    except Exception as e:
        logger.error(f"[CATEGORY] Prediction failed: {e}")

    return None


# ─── Card Operation Helpers ───────────────────────────────────────────────────


def _get_user_cards_context(user_id: str) -> str:
    """Get formatted list of user's cards for LLM context."""
    import psycopg2
    from backend.config import DATABASE_URL

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT card_id, masked_card_no, card_type, card_network, status
                    FROM cards WHERE cif_no = %s ORDER BY issued_at DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
                if not rows:
                    return "No cards found."
                lines = []
                for i, (card_id, masked, ctype, network, status) in enumerate(rows, 1):
                    lines.append(f"{i}. {masked} | {ctype} | {network} | {status} | id={card_id}")
                return "\n".join(lines)
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD] get_user_cards_context error: {e}")
        return "Error loading cards."


def _resolve_card(card_draft: CardDraft, user_id: str) -> dict | None:
    """Resolve card from hints. Returns card dict or None."""
    import psycopg2
    import psycopg2.extras
    from backend.config import DATABASE_URL

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                conditions = ["cif_no = %s"]
                params = [user_id]

                if card_draft.card_hint_last4:
                    conditions.append("masked_card_no LIKE %s")
                    params.append(f"%{card_draft.card_hint_last4}")
                if card_draft.card_hint_type:
                    conditions.append("card_type = %s")
                    params.append(card_draft.card_hint_type.upper())
                if card_draft.card_hint_network:
                    conditions.append("card_network = %s")
                    params.append(card_draft.card_hint_network.upper())

                where = " AND ".join(conditions)
                cur.execute(
                    f"SELECT card_id, masked_card_no, card_type, card_network, status, account_no "
                    f"FROM cards WHERE {where} ORDER BY issued_at DESC",
                    params,
                )
                rows = [dict(r) for r in cur.fetchall()]

                if len(rows) == 1:
                    rows[0]["card_id"] = str(rows[0]["card_id"])
                    return rows[0]
                elif len(rows) > 1:
                    for r in rows:
                        r["card_id"] = str(r["card_id"])
                    return {"multiple": True, "cards": rows}
                return None
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD] resolve_card error: {e}")
        return None


def _handle_card_collecting(
    flow: FlowState,
    user_id: str,
    response_data: dict,
    action: str,
    decision_data: dict,
) -> tuple[FlowState, str]:
    """Handle card operation flow in COLLECTING state.

    Returns (updated_flow, response_message).
    """
    card_draft = flow.card_draft
    if not card_draft:
        card_draft = CardDraft()
        flow.card_draft = card_draft

    # Apply extraction results
    agent_result = response_data.get("agent_result", {})
    if agent_result:
        if agent_result.get("operation"):
            card_draft.operation = agent_result["operation"]
        if agent_result.get("card_hint_last4"):
            card_draft.card_hint_last4 = agent_result["card_hint_last4"]
        if agent_result.get("card_hint_type"):
            card_draft.card_hint_type = agent_result["card_hint_type"]
        if agent_result.get("card_hint_network"):
            card_draft.card_hint_network = agent_result["card_hint_network"]

    # Handle card selection from list
    if action == "ANSWER_PENDING_QUESTION":
        choice_data = decision_data.get("data", {}).get("choice")
        if choice_data and choice_data.get("card_id"):
            card_draft.card_id = choice_data["card_id"]
            card_draft.masked_card_no = choice_data.get("masked_card_no")
            card_draft.card_type = choice_data.get("card_type")
            card_draft.card_network = choice_data.get("card_network")
            card_draft.card_status = choice_data.get("status")

    # Step 1: Need operation?
    if not card_draft.operation:
        flow.pending_question = PendingQuestion(
            slot="card_operation",
            question=TEMPLATES["card_need_operation"],
            expected_type="text",
        )
        return flow, TEMPLATES["card_need_operation"]

    # Step 2: Resolve card
    if not card_draft.card_id:
        resolved = _resolve_card(card_draft, user_id)
        if resolved is None:
            flow.status = "COMPLETED"
            return flow, TEMPLATES["card_not_found"]
        elif resolved.get("multiple"):
            # Multiple cards — ask user to choose
            cards = resolved["cards"]
            card_draft.candidates = cards
            card_list = "\n".join(
                f"  {i+1}. {c['masked_card_no']} ({c['card_type']} {c['card_network']}) — {c['status']}"
                for i, c in enumerate(cards)
            )
            flow.pending_question = PendingQuestion(
                slot="card_choice",
                question="Chọn thẻ",
                expected_type="enum",
                options=[
                    {"card_id": str(c["card_id"]), "masked_card_no": c["masked_card_no"],
                     "card_type": c["card_type"], "card_network": c["card_network"],
                     "status": c["status"]}
                    for c in cards
                ],
            )
            return flow, TEMPLATES["card_list"].format(
                count=len(cards),
                card_list=card_list,
            )
        else:
            # Single card resolved
            card_draft.card_id = resolved["card_id"]
            card_draft.masked_card_no = resolved["masked_card_no"]
            card_draft.card_type = resolved["card_type"]
            card_draft.card_network = resolved["card_network"]
            card_draft.card_status = resolved["status"]

    # Step 3: VIEW_CARD_INFO — just return info (no confirmation needed)
    if card_draft.operation == "VIEW_CARD_INFO":
        flow.status = "COMPLETED"
        return flow, TEMPLATES["card_info"].format(
            masked_card_no=card_draft.masked_card_no or "?",
            card_type=card_draft.card_type or "?",
            card_network=card_draft.card_network or "?",
            status=card_draft.card_status or "?",
            account_no=_get_card_account_no(card_draft.card_id) or "?",
        )

    # Step 4: Validate card status for operation
    status_valid, error_msg = _validate_card_status(card_draft)
    if not status_valid:
        flow.status = "COMPLETED"
        return flow, error_msg

    # Step 5: Ask confirmation
    if card_draft.operation == "LOCK_CARD":
        message = TEMPLATES["card_lock_confirm"].format(
            masked_card_no=card_draft.masked_card_no or "?",
            card_type=card_draft.card_type or "",
            card_network=card_draft.card_network or "",
        )
    elif card_draft.operation == "UNLOCK_CARD":
        message = TEMPLATES["card_unlock_confirm"].format(
            masked_card_no=card_draft.masked_card_no or "?",
            card_type=card_draft.card_type or "",
            card_network=card_draft.card_network or "",
        )
    elif card_draft.operation == "REPORT_LOST":
        message = TEMPLATES["card_report_lost_confirm"].format(
            masked_card_no=card_draft.masked_card_no or "?",
            card_type=card_draft.card_type or "",
            card_network=card_draft.card_network or "",
        )
    else:
        message = "Xác nhận thao tác?"

    flow.status = "WAITING_CARD_CONFIRMATION"
    flow.pending_question = None
    return flow, message


def _validate_card_status(card_draft: CardDraft) -> tuple[bool, str]:
    """Validate card status is compatible with operation."""
    status = card_draft.card_status
    op = card_draft.operation

    if op == "LOCK_CARD" and status != "ACTIVE":
        return False, TEMPLATES["card_invalid_status"].format(status=status, action="khóa")
    if op == "UNLOCK_CARD" and status != "TEMP_LOCKED":
        return False, TEMPLATES["card_invalid_status"].format(status=status, action="mở khóa")
    if op == "REPORT_LOST" and status in ("LOST", "CANCELLED"):
        return False, TEMPLATES["card_invalid_status"].format(status=status, action="báo mất")

    return True, ""


def _get_card_account_no(card_id: str) -> str | None:
    """Get account_no linked to a card."""
    import psycopg2
    from backend.config import DATABASE_URL

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT account_no FROM cards WHERE card_id = %s::uuid", (card_id,))
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        return None


def _execute_card_operation(card_draft: CardDraft, user_id: str, session_id: str) -> dict:
    """Execute card operation (lock/unlock/report_lost)."""
    from backend.tools.card_tools import lock_card, unlock_card, report_lost_card

    card_id = card_draft.card_id
    operation = card_draft.operation

    if operation == "LOCK_CARD":
        result = lock_card.invoke({"user_id": user_id, "card_id": card_id})
        if result.get("status") == "success":
            write_audit_log(
                cif_no=user_id,
                event_type="CARD_LOCKED",
                actor="user",
                session_id=session_id,
                event_payload={"card_id": card_id},
            )
            return {"message": TEMPLATES["card_lock_success"].format(
                masked_card_no=card_draft.masked_card_no or "?"
            )}
        return {"message": result.get("message", "Không thể khóa thẻ.")}

    elif operation == "UNLOCK_CARD":
        result = unlock_card.invoke({"user_id": user_id, "card_id": card_id})
        if result.get("status") == "success":
            write_audit_log(
                cif_no=user_id,
                event_type="CARD_UNLOCKED",
                actor="user",
                session_id=session_id,
                event_payload={"card_id": card_id},
            )
            return {"message": TEMPLATES["card_unlock_success"].format(
                masked_card_no=card_draft.masked_card_no or "?"
            )}
        return {"message": result.get("message", "Không thể mở khóa thẻ.")}

    elif operation == "REPORT_LOST":
        result = report_lost_card.invoke({"user_id": user_id, "card_id": card_id})
        if result.get("status") == "success":
            write_audit_log(
                cif_no=user_id,
                event_type="CARD_REPORTED_LOST",
                actor="user",
                session_id=session_id,
                event_payload={"card_id": card_id},
            )
            return {"message": TEMPLATES["card_report_lost_success"].format(
                masked_card_no=card_draft.masked_card_no or "?"
            )}
        return {"message": result.get("message", "Không thể báo mất thẻ.")}

    return {"message": "Thao tác không hợp lệ."}
