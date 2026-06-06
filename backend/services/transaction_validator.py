"""Transaction Draft Validator — deterministic validation at each state transition.

Called by handle_flow_action_node BEFORE transitioning state.
If validation fails, the transition is blocked and user gets a clear error.

Separated from orchestrator to keep node logic thin.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psycopg2

from backend.config import DATABASE_URL, CURRENT_BANK_CODE
from backend.models.flow import TransactionDraft

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of draft validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─── Limits (configurable) ────────────────────────────────────────────────────

MIN_TRANSFER_AMOUNT = 10_000  # 10,000 VND
MAX_TRANSFER_AMOUNT = 500_000_000  # 500M VND per transaction
MAX_DAILY_TRANSFER = 2_000_000_000  # 2B VND per day


class TransactionValidator:
    """Deterministic validation — called before each state transition."""

    def validate_for_recipient_confirmation(self, draft: TransactionDraft) -> ValidationResult:
        """Check: recipient resolved enough to ask user for confirmation.

        Required: recipient_name, recipient_account_no, recipient_bank_code.
        """
        errors = []

        if not draft.recipient_name:
            errors.append("Thiếu tên người nhận.")
        if not draft.recipient_account_no:
            errors.append("Thiếu số tài khoản người nhận.")
        if not draft.recipient_bank_code:
            errors.append("Thiếu mã ngân hàng người nhận.")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_for_draft_confirmation(self, draft: TransactionDraft) -> ValidationResult:
        """Check: all fields ready to show full transaction summary.

        Required: amount, source_account, recipient_verified, fee computed.
        """
        errors = []
        warnings = []

        # Recipient must be verified
        if not draft.recipient_verified:
            errors.append("Người nhận chưa được xác minh.")

        # Amount
        amount_result = self.validate_amount(draft.amount)
        errors.extend(amount_result.errors)
        warnings.extend(amount_result.warnings)

        # Source account
        if not draft.source_account_no:
            errors.append("Chưa xác định tài khoản nguồn.")

        # Fee should be computed
        if draft.fee is None:
            errors.append("Chưa tính phí giao dịch.")

        if draft.total_debit is None:
            errors.append("Chưa tính tổng tiền trừ.")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_for_execution(self, draft: TransactionDraft, user_id: str) -> ValidationResult:
        """Final validation before executing — includes balance check.

        Required: all fields + sufficient balance + within limits + fraud != CRITICAL.
        """
        errors = []
        warnings = []

        # Basic field check
        draft_result = self.validate_for_draft_confirmation(draft)
        errors.extend(draft_result.errors)

        # Fraud risk
        if draft.fraud_screening:
            risk = draft.fraud_screening.get("risk_level", "LOW")
            if risk == "CRITICAL":
                errors.append("Tài khoản nhận bị đánh dấu lừa đảo mức CRITICAL. Không thể thực hiện.")
            elif risk == "HIGH":
                warnings.append(
                    f"Tài khoản nhận có {draft.fraud_screening.get('report_count', 0)} "
                    f"báo cáo nghi ngờ lừa đảo (mức rủi ro CAO)."
                )

        # Balance check
        if draft.total_debit and draft.source_account_no:
            balance_result = self.validate_balance(user_id, draft.total_debit)
            errors.extend(balance_result.errors)

        # Idempotency key must exist at execution
        if not draft.confirmation_id:
            errors.append("Thiếu confirmation_id.")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_amount(self, amount: int | None) -> ValidationResult:
        """Validate transfer amount against min/max limits."""
        errors = []
        warnings = []

        if amount is None:
            errors.append("Chưa có số tiền chuyển.")
            return ValidationResult(valid=False, errors=errors)

        if amount < MIN_TRANSFER_AMOUNT:
            errors.append(f"Số tiền tối thiểu là {MIN_TRANSFER_AMOUNT:,.0f} VND.")
        elif amount > MAX_TRANSFER_AMOUNT:
            errors.append(f"Số tiền vượt hạn mức {MAX_TRANSFER_AMOUNT:,.0f} VND/giao dịch.")

        if amount >= 50_000_000:
            warnings.append("Giao dịch trên 50 triệu VND sẽ được giám sát bổ sung.")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_balance(self, user_id: str, total_debit: int) -> ValidationResult:
        """Check source account has sufficient balance."""
        errors = []

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT balance FROM accounts
                        WHERE cif_no = %s AND account_type = 'PAYMENT' AND status = 'ACTIVE'
                        ORDER BY balance DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        errors.append("Không tìm thấy tài khoản thanh toán.")
                    elif row[0] < total_debit:
                        errors.append(
                            f"Số dư không đủ. Cần {total_debit:,.0f} VND, "
                            f"hiện có {row[0]:,.0f} VND."
                        )
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[VALIDATOR] balance check error: {e}")
            errors.append("Không thể kiểm tra số dư. Vui lòng thử lại.")

        return ValidationResult(valid=len(errors) == 0, errors=errors)
