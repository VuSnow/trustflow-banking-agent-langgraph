"""Top-Up Executor — executes phone/wallet top-up after OTP verification."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL
from backend.executor.models import ExecutionResult
from backend.services.audit_log import write_audit_log

logger = logging.getLogger(__name__)


class TopUpExecutor:
    """Execute verified top-up drafts."""

    async def execute(
        self,
        draft: dict,
        user_id: str,
        session_id: str,
    ) -> ExecutionResult:
        """Execute a phone/wallet top-up.

        Args:
            draft: Verified draft with topup_target, amount, topup_provider, topup_type.
            user_id: Customer cif_no.
            session_id: For audit trail.
        """
        amount = int(draft.get("amount", 0))
        topup_target = draft.get("topup_target", "")
        topup_provider = draft.get("topup_provider", "")
        topup_type = draft.get("topup_type", "phone")

        if not amount or not topup_target:
            return ExecutionResult(
                success=False,
                error_code="INVALID_DRAFT",
                message="Thông tin nạp tiền không đầy đủ.",
            )

        # Validate amount limits
        max_amount = 500_000 if topup_type == "phone" else 10_000_000
        if amount < 10_000:
            return ExecutionResult(
                success=False,
                error_code="AMOUNT_TOO_LOW",
                message="Số tiền nạp tối thiểu là 10,000 VND.",
            )
        if amount > max_amount:
            return ExecutionResult(
                success=False,
                error_code="AMOUNT_TOO_HIGH",
                message=f"Số tiền nạp tối đa là {max_amount:,.0f} VND.",
            )

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    # 1. Get user's primary payment account
                    cur.execute(
                        """
                        SELECT account_no, balance FROM accounts
                        WHERE cif_no = %s AND account_type = 'PAYMENT' AND status = 'ACTIVE'
                        ORDER BY balance DESC LIMIT 1
                        """,
                        (user_id,),
                    )
                    source = cur.fetchone()
                    if not source:
                        return ExecutionResult(
                            success=False,
                            error_code="NO_SOURCE_ACCOUNT",
                            message="Không tìm thấy tài khoản thanh toán.",
                        )

                    source_account, balance = source[0], source[1]

                    # 2. Check balance
                    if balance < amount:
                        return ExecutionResult(
                            success=False,
                            error_code="INSUFFICIENT_FUNDS",
                            message=f"Số dư không đủ. Cần {amount:,.0f} VND, hiện có {balance:,.0f} VND.",
                        )

                    # 3. Execute: debit account + insert transaction
                    new_balance = balance - amount
                    now = datetime.now()
                    transaction_ref = f"TOPUP{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

                    # Debit
                    cur.execute(
                        "UPDATE accounts SET balance = %s WHERE account_no = %s",
                        (new_balance, source_account),
                    )

                    # Insert transaction
                    cur.execute(
                        """
                        INSERT INTO transactions (
                            transaction_id, transaction_ref, cif_no, account_no,
                            transaction_time, amount, currency, direction,
                            transaction_type, counterparty_account_no, counterparty_name,
                            channel, description, status, balance_after, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'VND', 'OUT', 'PHONE_TOPUP',
                                  %s, %s, 'MOBILE_APP', %s, 'SUCCESS', %s, %s)
                        """,
                        (
                            str(uuid.uuid4()), transaction_ref, user_id, source_account,
                            now, amount,
                            topup_target, topup_target,
                            f"Nap dien thoai {topup_provider} {topup_target}",
                            new_balance, now,
                        ),
                    )

                conn.commit()

                write_audit_log(
                    cif_no=user_id,
                    event_type="TOPUP_EXECUTED",
                    actor="executor",
                    session_id=session_id,
                    event_payload={
                        "transaction_ref": transaction_ref,
                        "topup_target": topup_target,
                        "topup_provider": topup_provider,
                        "amount": amount,
                        "balance_after": new_balance,
                    },
                )

                return ExecutionResult(
                    success=True,
                    message=(
                        f"✅ Nạp tiền thành công!\n"
                        f"• Số {topup_target} ({topup_provider})\n"
                        f"• Số tiền: {amount:,.0f} VND\n"
                        f"• Mã giao dịch: {transaction_ref}\n"
                        f"• Số dư còn lại: {new_balance:,.0f} VND"
                    ),
                    transaction_ref=transaction_ref,
                    fee=0,
                    balance_after=new_balance,
                )

            finally:
                conn.close()

        except Exception as e:
            logger.error(f"[TOPUP EXECUTOR] Error: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                error_code="SYSTEM_ERROR",
                message="Lỗi hệ thống khi nạp tiền. Vui lòng thử lại.",
            )
