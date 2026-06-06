"""Bill Resolver — deterministic SQL-based bill lookup (no LLM, no tools).

Handles:
1. Find user's registered billers (filtered by type/alias/name)
2. Look up unpaid bills for matched billers
3. Aggregate for pay-all scenarios
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


@dataclass
class RegisteredBiller:
    """A user's registered biller account."""

    biller_code: str
    biller_name: str
    biller_type: str
    customer_bill_code: str
    alias: str | None = None


@dataclass
class UnpaidBill:
    """An unpaid bill ready for payment."""

    bill_id: str
    biller_code: str
    biller_name: str
    biller_type: str
    customer_bill_code: str
    bill_period: str
    amount_due: int
    due_date: str


@dataclass
class BillResolutionResult:
    """Result of bill resolution — billers found + unpaid bills."""

    billers: list[RegisteredBiller] = field(default_factory=list)
    unpaid_bills: list[UnpaidBill] = field(default_factory=list)
    total_amount: int = 0
    message: str | None = None


class BillResolver:
    """Deterministic bill resolution via SQL."""

    def get_registered_billers(
        self,
        user_id: str,
        biller_type: str | None = None,
        alias_hint: str | None = None,
        biller_name_hint: str | None = None,
    ) -> list[RegisteredBiller]:
        """Find user's registered biller accounts with optional filtering."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    query = """
                        SELECT b.biller_code, b.biller_name, b.biller_type,
                               cba.customer_bill_code, cba.alias
                        FROM customer_biller_accounts cba
                        JOIN billers b ON cba.biller_id = b.biller_id
                        WHERE cba.cif_no = %s AND cba.status = 'ACTIVE'
                    """
                    params: list[Any] = [user_id]

                    if biller_type:
                        query += " AND b.biller_type = %s"
                        params.append(biller_type)

                    query += " ORDER BY b.biller_type, b.biller_name"
                    cur.execute(query, params)
                    rows = cur.fetchall()

                billers = [
                    RegisteredBiller(
                        biller_code=r["biller_code"],
                        biller_name=r["biller_name"],
                        biller_type=r["biller_type"],
                        customer_bill_code=r["customer_bill_code"],
                        alias=r["alias"],
                    )
                    for r in rows
                ]

                # Post-filter by alias hint (fuzzy match)
                if alias_hint and billers:
                    hint_lower = alias_hint.lower()
                    matched = [
                        b for b in billers
                        if b.alias and hint_lower in b.alias.lower()
                    ]
                    if matched:
                        return matched

                # Post-filter by biller name hint
                if biller_name_hint and billers:
                    hint_lower = biller_name_hint.lower()
                    matched = [
                        b for b in billers
                        if hint_lower in b.biller_name.lower()
                           or hint_lower in b.biller_code.lower()
                    ]
                    if matched:
                        return matched

                return billers
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[BILL RESOLVER] get_registered_billers error: {e}")
            return []

    def lookup_unpaid_bills(
        self,
        customer_bill_codes: list[str],
        biller_code: str | None = None,
    ) -> list[UnpaidBill]:
        """Look up unpaid bills for given customer bill codes."""
        if not customer_bill_codes:
            return []

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    placeholders = ",".join(["%s"] * len(customer_bill_codes))
                    query = f"""
                        SELECT bl.bill_id, b.biller_code, b.biller_name, b.biller_type,
                               bl.customer_bill_code, bl.bill_period,
                               bl.amount_due, bl.due_date
                        FROM bills bl
                        JOIN billers b ON bl.biller_code = b.biller_code
                        WHERE bl.customer_bill_code IN ({placeholders})
                          AND bl.status = 'UNPAID'
                    """
                    params: list[Any] = list(customer_bill_codes)

                    if biller_code:
                        query += " AND bl.biller_code = %s"
                        params.append(biller_code)

                    query += " ORDER BY bl.due_date ASC"
                    cur.execute(query, params)
                    rows = cur.fetchall()

                return [
                    UnpaidBill(
                        bill_id=str(r["bill_id"]),
                        biller_code=r["biller_code"],
                        biller_name=r["biller_name"],
                        biller_type=r["biller_type"],
                        customer_bill_code=r["customer_bill_code"],
                        bill_period=r["bill_period"],
                        amount_due=int(r["amount_due"]),
                        due_date=str(r["due_date"]),
                    )
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[BILL RESOLVER] lookup_unpaid_bills error: {e}")
            return []

    def resolve(
        self,
        user_id: str,
        biller_type: str | None = None,
        alias_hint: str | None = None,
        biller_name_hint: str | None = None,
        pay_all: bool = False,
    ) -> BillResolutionResult:
        """Full resolution: find billers → lookup unpaid bills.

        Returns:
        - If exactly 1 unpaid bill: ready for confirmation
        - If multiple unpaid bills from one biller: list them
        - If multiple billers: needs user selection
        - If no billers/bills: informational message
        """
        # Step 1: Find registered billers
        billers = self.get_registered_billers(
            user_id=user_id,
            biller_type=biller_type if not pay_all else None,
            alias_hint=alias_hint,
            biller_name_hint=biller_name_hint,
        )

        if not billers:
            if biller_type:
                type_name = _biller_type_display(biller_type)
                msg = f"Bạn chưa đăng ký tài khoản thanh toán {type_name} nào."
            else:
                msg = "Bạn chưa đăng ký tài khoản thanh toán hóa đơn nào. Vui lòng đăng ký tại quầy hoặc app."
            return BillResolutionResult(message=msg)

        # Step 2: Lookup unpaid bills
        codes = [b.customer_bill_code for b in billers]
        unpaid_bills = self.lookup_unpaid_bills(codes)

        if not unpaid_bills:
            if biller_type:
                type_name = _biller_type_display(biller_type)
                msg = f"Không có hóa đơn {type_name} chưa thanh toán."
            else:
                msg = "Không có hóa đơn nào chưa thanh toán."
            return BillResolutionResult(billers=billers, message=msg)

        total = sum(b.amount_due for b in unpaid_bills)

        return BillResolutionResult(
            billers=billers,
            unpaid_bills=unpaid_bills,
            total_amount=total,
        )


def _biller_type_display(biller_type: str) -> str:
    """Map biller type to Vietnamese display."""
    return {
        "ELECTRICITY": "điện",
        "WATER": "nước",
        "INTERNET": "internet",
        "PHONE_POSTPAID": "điện thoại trả sau",
    }.get(biller_type, "hóa đơn")
