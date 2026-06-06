"""Flow state models — source of truth for conversation flow control.

These models replace the flat fsm_state + pending_draft approach with
a structured, typed flow state that supports:
- Multi-step transaction flows with clear state transitions
- Pending questions with expected answer types
- Interrupted intent storage for locked flows
- Draft lifecycle with hash-based OTP binding
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ─── PendingQuestion ──────────────────────────────────────────────────────────

class PendingQuestion(BaseModel):
    """Tracks what the system last asked — enables context-aware routing.

    The router uses `expected_type` to interpret short user answers
    (e.g. "1", "ok", "123456") without calling LLM.
    """

    slot: str  # e.g. "recipient_choice", "recipient_confirmation", "draft_confirmation", "otp"
    question: str  # The actual text shown to user
    expected_type: Literal["text", "amount", "enum", "recipient_choice", "otp"]
    options: list[dict] | None = None  # For recipient_choice / enum


# ─── BillDraft ────────────────────────────────────────────────────────────────

class BillDraft(BaseModel):
    """Bill payment draft — stores selected bill details for execution."""

    bill_id: str | None = None
    biller_code: str | None = None
    biller_name: str | None = None
    biller_type: str | None = None
    customer_bill_code: str | None = None
    bill_period: str | None = None
    amount: int | None = None
    due_date: str | None = None
    alias: str | None = None

    # Candidates stored during selection phase
    candidates: list[dict] | None = None


# ─── TopUpDraft ────────────────────────────────────────────────────────────────

class TopUpDraft(BaseModel):
    """Top-up draft — stores extracted top-up details."""

    topup_target: str | None = None       # Phone number or wallet ID
    topup_provider: str | None = None     # Viettel/Mobifone/Vinaphone/etc.
    topup_type: str | None = None         # "phone" or "wallet"
    amount: int | None = None


# ─── TransactionDraft ─────────────────────────────────────────────────────────

class TransactionDraft(BaseModel):
    """Central transaction draft — only agent/orchestrator can update.

    Agent extracts fields, orchestrator validates and enriches (fee, source account).
    LLM never sets confirmation_id, idempotency_key, or otp_challenge_id.
    """

    transaction_type: Literal["INTERNAL_TRANSFER", "INTERBANK_TRANSFER"] | None = None

    amount: int | None = None
    currency: str = "VND"

    # Recipient info (progressively filled)
    recipient_query: str | None = None
    recipient_id: str | None = None
    recipient_name: str | None = None
    recipient_bank_code: str | None = None
    recipient_bank_name: str | None = None
    recipient_account_no: str | None = None
    recipient_account_no_masked: str | None = None

    # Source account (enriched by backend, not agent)
    source_account_no: str | None = None
    source_account_no_masked: str | None = None

    transfer_note: str | None = None

    # Fee (computed by backend at WAITING_DRAFT_CONFIRMATION)
    fee: int | None = None
    total_debit: int | None = None

    # Verification flags
    recipient_verified: bool = False
    fraud_screening: dict | None = None

    # Lifecycle-managed IDs (NEVER set by LLM)
    confirmation_id: str | None = None  # Created at WAITING_DRAFT_CONFIRMATION
    idempotency_key: str | None = None  # Created at EXECUTING

    def summary_hash(self) -> str:
        """Hash of critical fields — binds OTP challenge to draft state.

        If any critical field changes after OTP is issued, hash won't match
        and the OTP challenge is invalidated.
        """
        raw = (
            f"{self.amount}:{self.recipient_account_no}:"
            f"{self.recipient_bank_code}:{self.source_account_no}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─── InterruptedIntent ────────────────────────────────────────────────────────

class InterruptedIntent(BaseModel):
    """Intent user raised while a locked flow was active.

    NOT a suspended flow — it's an intent that couldn't be executed because
    the current flow requires completion (OTP) or explicit cancellation first.
    """

    intent: str
    original_message: str
    captured_at: datetime = Field(default_factory=datetime.now)


# ─── FlowState ────────────────────────────────────────────────────────────────

class FlowState(BaseModel):
    """Core flow state — replaces flat fsm_state + pending_draft.

    Each active conversation has at most ONE FlowState.
    The flow progresses through statuses via deterministic transitions
    in handle_flow_action_node — never by LLM decision.
    """

    flow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flow_type: Literal["TRANSACTION", "BILL_PAYMENT", "TOP_UP"]

    status: Literal[
        "COLLECTING",
        "WAITING_BILLER_SELECTION",
        "WAITING_BILL_CONFIRMATION",
        "WAITING_TOPUP_CONFIRMATION",
        "WAITING_RECIPIENT_CONFIRMATION",
        "WAITING_DRAFT_CONFIRMATION",
        "WAITING_OTP",
        "EXECUTING",
        "COMPLETED",
        "CANCELLED",
    ]

    draft: TransactionDraft | None = None
    bill_draft: BillDraft | None = None
    topup_draft: TopUpDraft | None = None
    pending_question: PendingQuestion | None = None
    interrupted_intent: InterruptedIntent | None = None

    otp_challenge_id: str | None = None
    otp_attempts: int = 0

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def lock_level(self) -> Literal["flexible", "limited", "locked"]:
        """Computed from status — determines what user actions are allowed.

        flexible: user can switch intent, provide info freely
        limited: user can confirm/cancel/modify only
        locked: user can only submit OTP or cancel
        """
        if self.status in ("WAITING_OTP", "EXECUTING"):
            return "locked"
        if self.status in ("WAITING_RECIPIENT_CONFIRMATION", "WAITING_DRAFT_CONFIRMATION"):
            return "limited"
        return "flexible"


# ─── Recipient Resolution Plan ────────────────────────────────────────────────
# Structured query plan that Transaction Agent outputs.
# RecipientResolver converts this into SQL/Text2SQL calls.
# Agent never writes SQL — only produces this plan.


class QueryConstraint(BaseModel):
    """A single filter constraint for recipient resolution."""

    field: Literal[
        "recipient_name",
        "account_no",
        "bank_name",
        "bank_code",
        "transaction_time",
        "amount",
        "note",
        "direction",
        "transaction_type",
        "status",
    ]
    operator: Literal[
        "contains",
        "equals",
        "between",
        "gte",
        "lte",
        "recent",
    ]
    value: str | int | dict


class SortRule(BaseModel):
    """Sort directive for resolution results."""

    field: Literal["transaction_time", "last_transfer_at", "amount"]
    direction: Literal["asc", "desc"] = "desc"


class RecipientResolutionPlan(BaseModel):
    """Structured plan for resolving a recipient.

    Transaction Agent maps user's natural language → this plan.
    RecipientResolver executes the plan via SQL/Text2SQL.
    """

    target: Literal[
        "saved_beneficiary",
        "past_transaction",
        "direct_account",
        "unknown",
    ]

    constraints: list[QueryConstraint] = Field(default_factory=list)
    sort: list[SortRule] = Field(default_factory=list)
    limit: int = 5

    copy_fields: list[Literal["recipient", "amount", "note", "bank"]] = Field(
        default_factory=list
    )

    needs_user_confirmation: bool = True
    needs_user_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 0.0


class TransactionExtractionResult(BaseModel):
    """Full output of the Transaction Extractor agent.

    Replaces the old dataclass TransactionAgentResult.
    """

    extracted_fields: dict = Field(default_factory=dict)
    recipient_resolution_plan: RecipientResolutionPlan | None = None
    missing_fields: list[str] = Field(default_factory=list)
    interpretation: str = ""


# ─── Serialization helpers ────────────────────────────────────────────────────
# LangGraph checkpoint requires JSON-serializable state.
# These helpers bridge typed FlowState ↔ dict for ChatState storage.


def serialize_flow(flow: FlowState | None) -> dict | None:
    """FlowState → dict for LangGraph checkpoint storage."""
    if flow is None:
        return None
    return flow.model_dump(mode="json")


def deserialize_flow(data: dict | None) -> FlowState | None:
    """dict from LangGraph checkpoint → FlowState."""
    if data is None:
        return None
    return FlowState.model_validate(data)
