"""Transaction Executor — executes transfers after OTP verification.

This is the ONLY layer that performs side effects (DB writes, balance changes).
No LLM involved — pure deterministic execution.
"""
from __future__ import annotations

import hashlib
import logging

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL
from backend.executor.banking_api import call_transfer_api
from backend.executor.models import ExecutionResult
from backend.services.audit_log import write_audit_log

logger = logging.getLogger(__name__)


class TransactionExecutor:
    """Execute verified transaction drafts via banking API."""

    async def execute(
        self,
        draft: dict,
        user_id: str,
        session_id: str,
    ) -> ExecutionResult:
        """Execute a transaction draft.

        Args:
            draft: Verified draft from transaction agent (contains account_no, bank_code, amount, etc.)
            user_id: Customer cif_no.
            session_id: For audit trail.

        Returns:
            ExecutionResult with success/failure details.
        """
        # 1. Resolve source account (user's primary PAYMENT account)
        source = self._get_primary_account(user_id)
        if not source:
            return ExecutionResult(
                success=False,
                error_code="NO_SOURCE_ACCOUNT",
                message="Không tìm thấy tài khoản thanh toán. Vui lòng liên hệ ngân hàng.",
            )

        # 2. Build idempotency key from draft contents (max 30 chars for DB column)
        raw_key = f"{session_id}:{draft.get('account_no')}:{draft.get('amount')}"
        idempotency_key = hashlib.sha256(raw_key.encode()).hexdigest()[:30]

        # 3. Call banking API
        api_response = await call_transfer_api(
            source_account=source["account_no"],
            dest_account=draft.get("account_no", ""),
            dest_bank_code=draft.get("bank_code", ""),
            amount=draft.get("amount", 0),
            transfer_type=draft.get("transfer_type", "interbank"),
            note=draft.get("note", "") or f"Chuyen tien cho {draft.get('recipient_name', '')}",
            idempotency_key=idempotency_key,
        )

        # 4. Handle response
        status = api_response.get("status", "SYSTEM_ERROR")

        if status == "SUCCESS":
            write_audit_log(
                cif_no=user_id,
                event_type="TRANSACTION_EXECUTED",
                actor="executor",
                session_id=session_id,
                event_payload={
                    "transaction_ref": api_response.get("transaction_ref"),
                    "amount": draft.get("amount"),
                    "recipient": draft.get("recipient_name"),
                    "dest_account": draft.get("account_no"),
                    "fee": api_response.get("fee", 0),
                    "balance_after": api_response.get("balance_after"),
                },
            )

            fee = api_response.get("fee", 0)
            balance_after = api_response.get("balance_after", 0)
            tx_ref = api_response.get("transaction_ref", "")

            message = (
                f"✅ Giao dịch thành công!\n"
                f"• Chuyển {draft.get('amount', 0):,.0f} VND cho {draft.get('recipient_name', '')}\n"
                f"• Tại {draft.get('bank_name', draft.get('bank_code', ''))}\n"
                f"• Mã giao dịch: {tx_ref}\n"
                f"• Phí: {fee:,.0f} VND\n"
                f"• Số dư còn lại: {balance_after:,.0f} VND"
            )

            return ExecutionResult(
                success=True,
                message=message,
                transaction_ref=tx_ref,
                fee=fee,
                balance_after=balance_after,
                data=api_response,
            )
        else:
            write_audit_log(
                cif_no=user_id,
                event_type="TRANSACTION_FAILED",
                actor="executor",
                session_id=session_id,
                event_payload={
                    "error_code": status,
                    "api_response": api_response,
                    "draft": draft,
                },
            )

            message = self._format_error(status, api_response)
            return ExecutionResult(
                success=False,
                error_code=status,
                message=message,
                data=api_response,
            )

    def _get_primary_account(self, user_id: str) -> dict | None:
        """Get user's primary PAYMENT account."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT account_no, balance, status
                        FROM accounts
                        WHERE cif_no = %s AND account_type = 'PAYMENT' AND status = 'ACTIVE'
                        ORDER BY balance DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[EXECUTOR] Get primary account error: {e}")
            return None

    def _format_error(self, status: str, response: dict) -> str:
        """Format user-friendly error message."""
        messages = {
            "INSUFFICIENT_FUNDS": response.get("message", "Số dư tài khoản không đủ."),
            "ACCOUNT_BLOCKED": response.get("message", "Tài khoản nguồn đang bị khóa."),
            "DAILY_LIMIT_EXCEEDED": response.get("message", "Vượt hạn mức giao dịch trong ngày."),
            "SOURCE_NOT_FOUND": "Không tìm thấy tài khoản nguồn.",
            "SYSTEM_ERROR": "Lỗi hệ thống. Vui lòng thử lại sau hoặc liên hệ hotline 1900xxxx.",
        }
        return f"❌ Giao dịch thất bại.\n{messages.get(status, response.get('message', 'Lỗi không xác định.'))}"
