"""Mock Banking API client.

Simulates a core banking API for transfers. In production, this would
be replaced with actual HTTP calls to the bank's transfer API.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

import psycopg2

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Transfer fees (mock)
INTRABANK_FEE = 0
INTERBANK_FEE_UNDER_5M = 5500
INTERBANK_FEE_5M_TO_50M = 11000
INTERBANK_FEE_OVER_50M = 22000


def _calculate_fee(amount: int, transfer_type: str) -> int:
    """Calculate transfer fee based on amount and type."""
    if transfer_type == "intrabank":
        return INTRABANK_FEE
    # Interbank fees
    if amount < 5_000_000:
        return INTERBANK_FEE_UNDER_5M
    elif amount <= 50_000_000:
        return INTERBANK_FEE_5M_TO_50M
    else:
        return INTERBANK_FEE_OVER_50M


async def call_transfer_api(
    *,
    source_account: str,
    dest_account: str,
    dest_bank_code: str,
    amount: int,
    transfer_type: str = "interbank",
    note: str = "",
    idempotency_key: str = "",
) -> dict:
    """Simulate a banking transfer API call.

    Checks:
    1. Source account exists and is ACTIVE
    2. Sufficient balance (amount + fee)
    3. Daily limit not exceeded

    Returns API response dict with status and details.
    """
    fee = _calculate_fee(amount, transfer_type)
    total_debit = amount + fee

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                # 1. Check source account
                cur.execute(
                    "SELECT balance, status FROM accounts WHERE account_no = %s",
                    (source_account,),
                )
                row = cur.fetchone()
                if not row:
                    return {
                        "status": "SOURCE_NOT_FOUND",
                        "message": f"Tài khoản nguồn {source_account} không tồn tại.",
                    }

                balance, status = row[0], row[1]

                if status != "ACTIVE":
                    return {
                        "status": "ACCOUNT_BLOCKED",
                        "message": f"Tài khoản nguồn đang ở trạng thái {status}. Vui lòng liên hệ ngân hàng.",
                    }

                # 2. Check balance
                if balance < total_debit:
                    return {
                        "status": "INSUFFICIENT_FUNDS",
                        "message": (
                            f"Số dư không đủ. Cần {total_debit:,.0f} VND "
                            f"(gồm phí {fee:,.0f}), hiện có {balance:,.0f} VND."
                        ),
                        "balance_available": balance,
                        "amount_needed": total_debit,
                    }

                # 3. Check daily limit (sum of today's OUT transactions)
                cur.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) FROM transactions
                    WHERE account_no = %s AND direction = 'OUT' AND status = 'SUCCESS'
                    AND transaction_time::date = CURRENT_DATE
                    """,
                    (source_account,),
                )
                daily_total = cur.fetchone()[0]
                daily_limit = 500_000_000  # 500M VND daily limit

                if daily_total + amount > daily_limit:
                    return {
                        "status": "DAILY_LIMIT_EXCEEDED",
                        "message": (
                            f"Vượt hạn mức giao dịch trong ngày. "
                            f"Đã sử dụng {daily_total:,.0f}/{daily_limit:,.0f} VND."
                        ),
                        "daily_used": daily_total,
                        "daily_limit": daily_limit,
                    }

                # 4. Idempotency check
                if idempotency_key:
                    cur.execute(
                        "SELECT transaction_ref FROM transactions WHERE external_reference = %s LIMIT 1",
                        (idempotency_key,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return {
                            "status": "SUCCESS",
                            "transaction_ref": existing[0],
                            "message": "Giao dịch đã được thực hiện trước đó.",
                            "amount": amount,
                            "fee": fee,
                            "balance_after": balance,  # no change
                            "duplicate": True,
                        }

                # 5. Execute transfer — debit source
                new_balance = balance - total_debit
                transaction_ref = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
                now = datetime.now()

                cur.execute(
                    "UPDATE accounts SET balance = %s WHERE account_no = %s",
                    (new_balance, source_account),
                )

                # 6. Insert transaction record
                cur.execute(
                    """
                    INSERT INTO transactions (
                        transaction_id, transaction_ref, cif_no, account_no,
                        transaction_time, amount, currency, direction,
                        transaction_type, counterparty_account_no, counterparty_bank_code,
                        counterparty_name, channel, description, status,
                        balance_after, external_reference, created_at
                    ) VALUES (
                        %s, %s,
                        (SELECT cif_no FROM accounts WHERE account_no = %s),
                        %s, %s, %s, 'VND', 'OUT', 'BANK_TRANSFER',
                        %s, %s, %s, 'MOBILE_APP', %s, 'SUCCESS', %s, %s, %s
                    )
                    """,
                    (
                        str(uuid.uuid4()), transaction_ref,
                        source_account, source_account,
                        now, amount,
                        dest_account, dest_bank_code, note or f"Chuyen tien",
                        note or f"Chuyen tien toi {dest_account}",
                        new_balance, idempotency_key or None, now,
                    ),
                )

            conn.commit()

            logger.info(
                f"[EXECUTOR] Transfer SUCCESS: {source_account} → {dest_account} "
                f"amount={amount} fee={fee} ref={transaction_ref}"
            )

            return {
                "status": "SUCCESS",
                "transaction_ref": transaction_ref,
                "amount": amount,
                "fee": fee,
                "balance_after": new_balance,
                "timestamp": now.isoformat(timespec="seconds"),
            }

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"[EXECUTOR] API error: {e}", exc_info=True)
        return {
            "status": "SYSTEM_ERROR",
            "message": "Lỗi hệ thống. Vui lòng thử lại sau hoặc liên hệ ngân hàng.",
        }
