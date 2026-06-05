"""Bill Payment Executor — executes bill payments after OTP verification."""
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


class BillPaymentExecutor:
    """Execute verified bill payment drafts."""

    async def execute(
        self,
        draft: dict,
        user_id: str,
        session_id: str,
    ) -> ExecutionResult:
        """Execute a bill payment.

        Args:
            draft: Verified draft with bill_id, biller_code, customer_bill_code, amount.
            user_id: Customer cif_no.
            session_id: For audit trail.
        """
        bill_id = draft.get("bill_id")
        amount = int(draft.get("amount", 0))
        biller_code = draft.get("biller_code", "")
        customer_bill_code = draft.get("customer_bill_code", "")

        if not bill_id or not amount:
            return ExecutionResult(
                success=False,
                error_code="INVALID_DRAFT",
                message="Thông tin hóa đơn không đầy đủ.",
            )

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    # 1. Get user's primary account
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

                    # 3. Check bill still unpaid
                    cur.execute(
                        "SELECT status, amount_due FROM bills WHERE bill_id = %s",
                        (bill_id,),
                    )
                    bill_row = cur.fetchone()
                    if not bill_row:
                        return ExecutionResult(
                            success=False,
                            error_code="BILL_NOT_FOUND",
                            message="Hóa đơn không tồn tại.",
                        )
                    if bill_row[0] != "UNPAID":
                        return ExecutionResult(
                            success=False,
                            error_code="BILL_ALREADY_PAID",
                            message="Hóa đơn này đã được thanh toán.",
                        )

                    # 4. Execute: debit account, mark bill paid, insert transaction
                    new_balance = balance - amount
                    now = datetime.now()
                    transaction_ref = f"BILL{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

                    # Debit
                    cur.execute(
                        "UPDATE accounts SET balance = %s WHERE account_no = %s",
                        (new_balance, source_account),
                    )

                    # Mark bill paid
                    cur.execute(
                        "UPDATE bills SET status = 'PAID', paid_at = %s WHERE bill_id = %s",
                        (now, bill_id),
                    )

                    # Insert transaction
                    cur.execute(
                        """
                        INSERT INTO transactions (
                            transaction_id, transaction_ref, cif_no, account_no,
                            transaction_time, amount, currency, direction,
                            transaction_type, counterparty_name,
                            channel, description, status, balance_after, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'VND', 'OUT', 'BILL_PAYMENT',
                                  %s, 'MOBILE_APP', %s, 'SUCCESS', %s, %s)
                        """,
                        (
                            str(uuid.uuid4()), transaction_ref, user_id, source_account,
                            now, amount, biller_code,
                            f"Thanh toan hoa don {biller_code} {customer_bill_code}",
                            new_balance, now,
                        ),
                    )

                conn.commit()

                write_audit_log(
                    cif_no=user_id,
                    event_type="BILL_PAYMENT_EXECUTED",
                    actor="executor",
                    session_id=session_id,
                    event_payload={
                        "transaction_ref": transaction_ref,
                        "bill_id": bill_id,
                        "biller_code": biller_code,
                        "amount": amount,
                        "balance_after": new_balance,
                    },
                )

                return ExecutionResult(
                    success=True,
                    message=(
                        f"✅ Thanh toán hóa đơn thành công!\n"
                        f"• {draft.get('biller_name', biller_code)} — kỳ {draft.get('bill_period', '')}\n"
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
            logger.error(f"[BILL EXECUTOR] Error: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                error_code="SYSTEM_ERROR",
                message="Lỗi hệ thống khi thanh toán hóa đơn. Vui lòng thử lại.",
            )
