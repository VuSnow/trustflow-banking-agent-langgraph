"""Transaction Validator — validates draft before OTP/execution.

Checks:
- Amount within limits
- Source account has sufficient balance
- Recipient account is verified
- No critical fraud flag
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psycopg2

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Business rules
MIN_TRANSFER_AMOUNT = 10_000  # 10k VND
MAX_TRANSFER_AMOUNT = 500_000_000  # 500M VND
MAX_DAILY_TRANSFER = 1_000_000_000  # 1B VND


@dataclass
class ValidationResult:
    """Result of transaction validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class TransactionValidator:
    """Validates a TransactionDraft before OTP challenge creation."""

    def validate_for_execution(self, draft, user_id: str) -> ValidationResult:
        """Run all validation checks on a draft.

        Args:
            draft: TransactionDraft instance.
            user_id: Customer cif_no.

        Returns:
            ValidationResult with errors/warnings.
        """
        errors = []
        warnings = []

        # 1. Amount checks
        if not draft.amount:
            errors.append("Chưa có số tiền giao dịch.")
        elif draft.amount < MIN_TRANSFER_AMOUNT:
            errors.append(
                f"Số tiền tối thiểu là {MIN_TRANSFER_AMOUNT:,.0f} VND."
            )
        elif draft.amount > MAX_TRANSFER_AMOUNT:
            errors.append(
                f"Số tiền vượt hạn mức {MAX_TRANSFER_AMOUNT:,.0f} VND/giao dịch."
            )

        # 2. Recipient verified
        if not draft.recipient_verified:
            errors.append("Tài khoản người nhận chưa được xác minh.")

        if not draft.recipient_account_no:
            errors.append("Thiếu số tài khoản người nhận.")

        # 3. Fraud block
        if draft.fraud_screening:
            risk = draft.fraud_screening.get("risk_level", "LOW")
            if risk == "CRITICAL":
                errors.append("Tài khoản nhận đã bị đánh dấu lừa đảo.")
            elif risk == "HIGH":
                warnings.append("Tài khoản nhận có cảnh báo rủi ro cao.")

        # 4. Source account balance
        if draft.source_account_no and draft.amount:
            balance = self._get_balance(user_id, draft.source_account_no)
            total_debit = draft.amount + (draft.fee or 0)
            if balance is not None and balance < total_debit:
                errors.append(
                    f"Số dư không đủ. Cần {total_debit:,.0f} VND, hiện có {balance:,.0f} VND."
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _get_balance(self, user_id: str, account_no: str) -> int | None:
        """Get current balance of an account."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT balance FROM accounts WHERE cif_no = %s AND account_no = %s LIMIT 1",
                        (user_id, account_no),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[VALIDATOR] balance check error: {e}")
            return None
