"""Flow state models — source of truth for conversation flow control.

These models replace the flat fsm_state + pending_draft approach with
typed, structured state that supports:
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
    """Tracks what the system last asked the user.

    The router uses `expected_type` to interpret short user answers
    (e.g. "1", "ok", "123456") without calling LLM.
    """

    slot: str  # e.g. "recipient_choice", "recipient_confirmation", "otp"
    question: str
    expected_type: Literal["text", "amount", "enum", "recipient_choice", "otp"]
    options: list[dict] | None = None


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
    candidates: list[dict] | None = None


# ─── TopUpDraft ───────────────────────────────────────────────────────────────


class TopUpDraft(BaseModel):
    """Top-up draft — stores extracted top-up details."""

    topup_target: str | None = None
    topup_provider: str | None = None
    topup_type: str | None = None  # "phone" or "wallet"
    amount: int | None = None


# ─── CardDraft ────────────────────────────────────────────────────────────────


class CardDraft(BaseModel):
    """Card operation draft — stores target card and intended operation."""

    operation: Literal[
        "LOCK_CARD", "UNLOCK_CARD", "REPORT_LOST", "VIEW_CARD_INFO"
    ] | None = None
    card_id: str | None = None
    masked_card_no: str | None = None
    card_type: str | None = None  # DEBIT / CREDIT
    card_network: str | None = None  # VISA / MASTERCARD / NAPAS
    card_status: str | None = None  # ACTIVE / TEMP_LOCKED / LOST
    # Hints from user (before resolution)
    card_hint_last4: str | None = None
    card_hint_type: str | None = None
    card_hint_network: str | None = None
    # Multiple card candidates (for disambiguation)
    candidates: list[dict] | None = None


# ─── CategoryPrediction ───────────────────────────────────────────────────────


class CategoryPrediction(BaseModel):
    """LLM prediction for transaction category — stored post-execution."""

    transaction_ref: str
    predicted_category_id: str
    predicted_code: str
    predicted_name: str
    confidence: float = 0.5
    alternatives: list[dict] = Field(default_factory=list)  # [{category_id, code, name}]


# ─── TransactionDraft ─────────────────────────────────────────────────────────


class TransactionDraft(BaseModel):
    """Central transaction draft — progressively filled by agent + orchestrator.

    Agent extracts fields, orchestrator validates and enriches (fee, source).
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

    # Source account (enriched by backend)
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
    confirmation_id: str | None = None
    idempotency_key: str | None = None

    def summary_hash(self) -> str:
        """Hash of critical fields — binds OTP to draft state.

        If any critical field changes after OTP is issued, the hash won't match
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

    Stored so we can resume it after current flow completes/cancels.
    """

    intent: str
    original_message: str
    captured_at: datetime = Field(default_factory=datetime.now)


# ─── FlowState ────────────────────────────────────────────────────────────────


class FlowState(BaseModel):
    """Core flow state — single source of truth for active conversation flow.

    Each session has at most ONE active FlowState.
    Status transitions are ONLY done by orchestrator handle_flow_action_node.
    """

    flow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flow_type: Literal["TRANSACTION", "BILL_PAYMENT", "TOP_UP", "CARD_OPERATION"]

    status: Literal[
        "COLLECTING",
        "WAITING_BILLER_SELECTION",
        "WAITING_BILL_CONFIRMATION",
        "WAITING_TOPUP_CONFIRMATION",
        "WAITING_RECIPIENT_CONFIRMATION",
        "WAITING_DRAFT_CONFIRMATION",
        "WAITING_CARD_CONFIRMATION",
        "WAITING_OTP",
        "WAITING_CATEGORY_CONFIRMATION",
        "EXECUTING",
        "COMPLETED",
        "CANCELLED",
    ]

    draft: TransactionDraft | None = None
    bill_draft: BillDraft | None = None
    topup_draft: TopUpDraft | None = None
    card_draft: CardDraft | None = None
    category_prediction: CategoryPrediction | None = None
    pending_question: PendingQuestion | None = None
    interrupted_intent: InterruptedIntent | None = None

    otp_challenge_id: str | None = None
    otp_attempts: int = 0

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def lock_level(self) -> Literal["flexible", "limited", "locked"]:
        """Determines what user actions are allowed at current status.

        flexible: user can switch intent, provide info freely
        limited: user can confirm/cancel/modify only
        locked: user can only submit OTP or cancel
        """
        if self.status in ("WAITING_OTP", "EXECUTING"):
            return "locked"
        if self.status in (
            "WAITING_RECIPIENT_CONFIRMATION",
            "WAITING_DRAFT_CONFIRMATION",
            "WAITING_BILL_CONFIRMATION",
            "WAITING_TOPUP_CONFIRMATION",
            "WAITING_CARD_CONFIRMATION",
        ):
            return "limited"
        # WAITING_CATEGORY_CONFIRMATION is flexible — user can freely switch intent
        return "flexible"


# ─── Recipient Resolution Plan ────────────────────────────────────────────────


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
    operator: Literal["contains", "equals", "between", "gte", "lte", "recent"]
    value: str | int | dict


class SortRule(BaseModel):
    """Sort directive for resolution results."""

    field: Literal["transaction_time", "last_transfer_at", "amount"]
    direction: Literal["asc", "desc"] = "desc"


class RecipientResolutionPlan(BaseModel):
    """Structured plan for resolving a recipient.

    Transaction Agent maps user's natural language → this plan.
    RecipientResolver executes the plan via deterministic SQL.
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


# ─── TransactionExtractionResult ──────────────────────────────────────────────


class TransactionExtractionResult(BaseModel):
    """Full output of the Transaction Extractor agent."""

    extracted_fields: dict = Field(default_factory=dict)
    recipient_resolution_plan: RecipientResolutionPlan | None = None
    missing_fields: list[str] = Field(default_factory=list)
    interpretation: str = ""


# ─── Serialization helpers ────────────────────────────────────────────────────


def serialize_flow(flow: FlowState | None) -> dict | None:
    """FlowState → dict for LangGraph checkpoint storage."""
    if flow is None:
        return None
    return flow.model_dump(mode="json")


def deserialize_flow(data: dict | None) -> FlowState | None:
    """dict → FlowState from LangGraph checkpoint."""
    if data is None:
        return None
    try:
        return FlowState.model_validate(data)
    except Exception:
        return None
