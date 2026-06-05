"""Main Orchestrator Graph — LangGraph StateGraph implementation.

Replaces the manual orchestrator + pipeline + FSM logic with a single
LangGraph StateGraph that handles:
1. Intent classification (router node)
2. Domain agent dispatch (conditional edges)
3. FSM states: confirmation & OTP (graph nodes with conditional routing)
4. Guardrails (node before confirmation)

Flow:
  classify_intent → route_to_agent → [domain_agent] → check_draft → guardrails → confirm → otp → execute
                                                     → info_response (terminal)
                                                     → clarification (terminal, waits for next input)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.state import ChatState
from backend.prompts.intent import INTENT_SYSTEM_PROMPT, INTENT_USER_TEMPLATE
from backend.agents.transaction import run_transaction_agent
from backend.agents.card_operation import run_card_agent
from backend.agents.account_operation import run_account_agent
from backend.agents.fraud_report import run_fraud_agent
from backend.agents.bill_payment import run_bill_agent
from backend.agents.topup import run_topup_agent
from backend.agents.finance_advisor import run_finance_agent
from backend.agents.qa import run_qa_agent
from backend.agents.data_query import run_data_query_agent
from backend.services.guardrails import check_transaction_guardrails, validate_otp
from backend.services.confirmation_classifier import classify_confirmation
from backend.services.audit_log import write_audit_log

logger = logging.getLogger(__name__)


# ─── Node functions ───────────────────────────────────────────────────────────

async def classify_intent_node(state: ChatState) -> dict:
    """Classify user intent using LLM."""
    # If already in FSM state, skip classification
    if state.get("fsm_state") in ("waiting_confirmation", "waiting_otp"):
        return {}

    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.0)

    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    # Build context with recent history
    chat_messages = [SystemMessage(content=INTENT_SYSTEM_PROMPT)]
    for msg in messages[-10:]:
        if isinstance(msg, HumanMessage):
            chat_messages.append(msg)
        elif isinstance(msg, AIMessage):
            chat_messages.append(msg)

    chat_messages.append(HumanMessage(content=INTENT_USER_TEMPLATE.format(message=last_message)))

    try:
        response = await llm.ainvoke(chat_messages)
        data = json.loads(response.content)
        logger.info(f"[INTENT] {data}")
        return {
            "intent": data.get("task_type", "QA"),
            "operation": data.get("operation"),
            "confidence": data.get("confidence", 0.0),
        }
    except Exception as e:
        logger.error(f"[INTENT] Error: {e}")
        return {"intent": "QA", "operation": None, "confidence": 0.0}


async def transaction_agent_node(state: ChatState) -> dict:
    """Run transaction agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_transaction_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def bill_agent_node(state: ChatState) -> dict:
    """Run bill payment agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_bill_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def topup_agent_node(state: ChatState) -> dict:
    """Run top-up agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_topup_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def card_agent_node(state: ChatState) -> dict:
    """Run card operation agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_card_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def qa_agent_node(state: ChatState) -> dict:
    """Run QA agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    result = await run_qa_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def data_query_agent_node(state: ChatState) -> dict:
    """Run data query agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_data_query_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def finance_agent_node(state: ChatState) -> dict:
    """Run finance advisor agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_finance_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def account_agent_node(state: ChatState) -> dict:
    """Run account operation agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_account_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def fraud_agent_node(state: ChatState) -> dict:
    """Run fraud report agent."""
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    history = _messages_to_history(messages[:-1])
    result = await run_fraud_agent(
        message=last_message,
        user_id=state["user_id"],
        session_id=state["session_id"],
        history=history,
    )

    return {
        "response_status": result["status"],
        "response_message": result["message"],
        "response_data": result.get("data", {}),
    }


async def guardrails_node(state: ChatState) -> dict:
    """Apply guardrails to the draft and determine FSM state."""
    data = state.get("response_data", {})
    fraud_screening = data.get("fraud_screening")
    amount = data.get("amount")

    guardrail_result = check_transaction_guardrails(
        amount=amount,
        fraud_screening=fraud_screening,
    )

    write_audit_log(
        cif_no=state["user_id"],
        event_type="GUARDRAIL_EVALUATED",
        actor="guardrail",
        session_id=state["session_id"],
        event_payload={"result": guardrail_result, "draft": data},
    )

    if guardrail_result["blocked"]:
        return {
            "response_status": "blocked",
            "response_message": guardrail_result["reason"],
            "fsm_state": "idle",
            "pending_draft": None,
        }

    # Transaction requires confirmation then OTP
    confirmation_msg = state.get("response_message", "")
    if guardrail_result.get("warning_message"):
        confirmation_msg = guardrail_result["warning_message"] + "\n\n" + confirmation_msg

    return {
        "fsm_state": "waiting_confirmation",
        "pending_draft": data,
        "response_message": confirmation_msg + "\n\nBạn có muốn tiếp tục không?",
    }


async def confirmation_node(state: ChatState) -> dict:
    """Handle user confirmation response.

    If user asks an unrelated question (classified as UNCLEAR and looks like
    a new intent), route back to classify_intent while preserving the pending draft.
    """
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""
    draft = state.get("pending_draft", {})

    draft_summary = (
        f"{draft.get('amount', '?'):,} VND → {draft.get('recipient_name', '?')} "
        f"({draft.get('account_no', '?')}) @ {draft.get('bank_name', '?')}"
    )

    result = await classify_confirmation(last_message, draft_summary=draft_summary)
    classification = result["classification"]

    write_audit_log(
        cif_no=state["user_id"],
        event_type="CONFIRMATION_CLASSIFIED",
        actor="classifier",
        session_id=state["session_id"],
        event_payload={"classification": classification, "reason": result.get("reason", "")},
    )

    if classification == "CONFIRM":
        return {
            "fsm_state": "waiting_otp",
            "response_status": "needs_otp",
            "response_message": "Vui lòng nhập mã OTP đã gửi đến số điện thoại của bạn.",
        }
    elif classification == "CANCEL":
        return {
            "fsm_state": "idle",
            "pending_draft": None,
            "response_status": "info_response",
            "response_message": "Đã hủy giao dịch.",
        }
    elif classification == "MODIFY":
        return {
            "fsm_state": "idle",
            "pending_draft": None,
            "response_status": "info_response",
            "response_message": "Đã hủy giao dịch. Vui lòng cho tôi biết bạn muốn thay đổi gì.",
        }
    else:  # UNCLEAR — check if it's a side question
        # If the message is long or looks like a new question, handle it
        # while keeping the draft pending
        if _looks_like_new_intent(last_message):
            return {
                "fsm_state": "waiting_confirmation",  # keep draft alive
                "response_status": "side_question",
                "response_message": last_message,  # will be re-routed
            }
        return {
            "response_status": "clarification_needed",
            "response_message": (
                "Tôi chưa hiểu rõ. Bạn muốn xác nhận hay hủy giao dịch?\n"
                f"(Giao dịch đang chờ: {draft_summary})"
            ),
        }


async def otp_node(state: ChatState) -> dict:
    """Handle OTP verification. On success, execute via appropriate Executor."""
    from backend.executor.transaction_executor import TransactionExecutor
    from backend.executor.bill_executor import BillPaymentExecutor
    from backend.executor.topup_executor import TopUpExecutor

    messages = state["messages"]
    last_message = messages[-1].content if messages else ""

    if validate_otp(last_message):
        write_audit_log(
            cif_no=state["user_id"],
            event_type="OTP_VALIDATED",
            actor="system",
            session_id=state["session_id"],
            event_payload={"success": True},
        )

        draft = state.get("pending_draft", {})
        action = draft.get("action", draft.get("operation", ""))

        # Route to appropriate executor
        if action == "BILL_PAYMENT":
            executor = BillPaymentExecutor()
        elif action == "TOP_UP":
            executor = TopUpExecutor()
        else:
            executor = TransactionExecutor()

        result = await executor.execute(
            draft=draft,
            user_id=state["user_id"],
            session_id=state["session_id"],
        )

        if result.success:
            return {
                "fsm_state": "executed",
                "response_status": "info_response",
                "response_message": result.message,
                "response_data": {"executed": True, "transaction_ref": result.transaction_ref, **result.data},
            }
        else:
            return {
                "fsm_state": "idle",
                "pending_draft": None,
                "response_status": "info_response",
                "response_message": result.message,
                "response_data": {"executed": False, "error_code": result.error_code},
            }
    else:
        write_audit_log(
            cif_no=state["user_id"],
            event_type="OTP_FAILED",
            actor="system",
            session_id=state["session_id"],
            event_payload={"success": False},
        )
        return {
            "response_status": "needs_otp",
            "response_message": "Mã OTP không đúng. Vui lòng nhập lại.",
        }


# ─── Routing functions ────────────────────────────────────────────────────────

def route_by_fsm_state(state: ChatState) -> str:
    """Route based on current FSM state (handles re-entry for confirmation/OTP)."""
    fsm = state.get("fsm_state", "idle")
    if fsm == "waiting_confirmation":
        return "confirmation"
    elif fsm == "waiting_otp":
        return "otp"
    else:
        return "classify_intent"


async def entry_node(state: ChatState) -> dict:
    """Entry node — pass-through to enable conditional routing."""
    return {}


def route_by_intent(state: ChatState) -> str:
    """Route to appropriate domain agent based on classified intent."""
    intent = state.get("intent", "QA")
    operation = state.get("operation", "")

    # TRANSACTION intent splits by operation
    if intent == "TRANSACTION":
        if operation == "BILL_PAYMENT":
            return "bill_agent"
        if operation == "TOP_UP":
            return "topup_agent"
        return "transaction_agent"

    routing = {
        "CARD_OPERATION": "card_agent",
        "ACCOUNT_OPERATION": "account_agent",
        "FRAUD_REPORT": "fraud_agent",
        "DATA_QUERY": "data_query_agent",
        "QA": "qa_agent",
        "FINANCE_ADVICE": "finance_agent",
    }
    return routing.get(intent, "qa_agent")


def route_after_agent(state: ChatState) -> str:
    """Route after domain agent completes — check if draft needs guardrails."""
    status = state.get("response_status", "")
    if status == "draft_ready":
        return "guardrails"
    else:
        return END


def route_after_confirmation(state: ChatState) -> str:
    """Route after confirmation classification."""
    fsm = state.get("fsm_state", "idle")
    status = state.get("response_status", "")
    if fsm == "waiting_otp":
        return END  # Response already set, wait for next input
    elif status == "side_question":
        return "classify_intent"  # Handle side question while keeping draft
    elif status == "clarification_needed":
        return END  # Ask again
    else:
        return END  # Cancelled or other


def route_after_otp(state: ChatState) -> str:
    """Route after OTP validation."""
    fsm = state.get("fsm_state", "")
    if fsm == "executed":
        return END
    else:
        return END  # Failed OTP, ask again


# ─── Build the graph ──────────────────────────────────────────────────────────

def build_orchestrator_graph() -> StateGraph:
    """Build the main orchestrator StateGraph."""
    graph = StateGraph(ChatState)

    # Add nodes
    graph.add_node("entry", entry_node)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("transaction_agent", transaction_agent_node)
    graph.add_node("bill_agent", bill_agent_node)
    graph.add_node("topup_agent", topup_agent_node)
    graph.add_node("card_agent", card_agent_node)
    graph.add_node("account_agent", account_agent_node)
    graph.add_node("fraud_agent", fraud_agent_node)
    graph.add_node("qa_agent", qa_agent_node)
    graph.add_node("data_query_agent", data_query_agent_node)
    graph.add_node("finance_agent", finance_agent_node)
    graph.add_node("guardrails", guardrails_node)
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("otp", otp_node)

    # Entry point — check FSM state first
    graph.set_entry_point("entry")

    # Entry dispatches based on FSM state
    graph.add_conditional_edges(
        "entry",
        route_by_fsm_state,
        {
            "classify_intent": "classify_intent",
            "confirmation": "confirmation",
            "otp": "otp",
        },
    )

    # After intent classification, route to domain agent
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "transaction_agent": "transaction_agent",
            "bill_agent": "bill_agent",
            "topup_agent": "topup_agent",
            "card_agent": "card_agent",
            "account_agent": "account_agent",
            "fraud_agent": "fraud_agent",
            "qa_agent": "qa_agent",
            "data_query_agent": "data_query_agent",
            "finance_agent": "finance_agent",
        },
    )

    # After domain agents, check if we need guardrails
    graph.add_conditional_edges("transaction_agent", route_after_agent, {"guardrails": "guardrails", END: END})
    graph.add_conditional_edges("bill_agent", route_after_agent, {"guardrails": "guardrails", END: END})
    graph.add_conditional_edges("topup_agent", route_after_agent, {"guardrails": "guardrails", END: END})
    graph.add_conditional_edges("card_agent", route_after_agent, {"guardrails": "guardrails", END: END})
    graph.add_conditional_edges("account_agent", route_after_agent, {"guardrails": "guardrails", END: END})
    graph.add_edge("fraud_agent", END)
    graph.add_edge("qa_agent", END)
    graph.add_edge("data_query_agent", END)
    graph.add_edge("finance_agent", END)

    # Guardrails → END (sets FSM state for next invocation)
    graph.add_edge("guardrails", END)

    # Confirmation → END or side_question → classify_intent
    graph.add_conditional_edges(
        "confirmation",
        route_after_confirmation,
        {END: END, "classify_intent": "classify_intent"},
    )

    # OTP → END
    graph.add_conditional_edges("otp", route_after_otp, {END: END})

    return graph


def _create_checkpointer():
    """Create a PostgreSQL checkpointer for state persistence.

    Uses AsyncPostgresSaver for async compatibility with FastAPI/uvicorn.
    Falls back to MemorySaver if PostgreSQL connection fails.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from backend.config import DATABASE_URL
        import psycopg

        # Setup tables (sync, one-time)
        setup_conn = psycopg.connect(DATABASE_URL, autocommit=True)
        saver = PostgresSaver(setup_conn)
        saver.setup()
        setup_conn.close()
        logger.info("[CHECKPOINT] PostgreSQL tables ready")

        # For async runtime, use MemorySaver since AsyncPostgresSaver
        # requires async context manager which doesn't fit compile() pattern.
        # State is still persisted via chat_session_store for FSM.
        from langgraph.checkpoint.memory import MemorySaver
        logger.info("[CHECKPOINT] Using MemorySaver for runtime (tables created in PG for future use)")
        return MemorySaver()
    except Exception as e:
        logger.warning(f"[CHECKPOINT] Failed to init: {e}. Using MemorySaver.")
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


# Module-level checkpointer (singleton)
_checkpointer = None


def get_checkpointer():
    """Get or create the checkpointer singleton."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _create_checkpointer()
    return _checkpointer


def compile_orchestrator():
    """Compile the orchestrator graph with checkpointing."""
    graph = build_orchestrator_graph()
    checkpointer = get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


# ─── Helper functions ─────────────────────────────────────────────────────────

def _messages_to_history(messages: list) -> list[dict]:
    """Convert LangChain messages to simple history dicts."""
    history = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "message": msg.content})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "message": msg.content})
    return history


def _format_success_message(draft: dict) -> str:
    """Format transaction success message."""
    amount = draft.get("amount", 0)
    recipient = draft.get("recipient_name", "")
    bank = draft.get("bank_name", "")
    return (
        f"✅ Giao dịch thành công! Đã chuyển {amount:,.0f} VND cho {recipient} tại {bank}."
    )


def _looks_like_new_intent(message: str) -> bool:
    """Heuristic: does this message look like a new question rather than a confirmation reply?

    Short replies (1-3 words) are likely confirmation attempts.
    Longer messages or those containing question marks are likely side questions.
    """
    msg = message.strip()
    word_count = len(msg.split())
    if word_count <= 3:
        return False
    if "?" in msg or "không" in msg.lower() and word_count > 5:
        return True
    if word_count >= 6:
        return True
    return False
