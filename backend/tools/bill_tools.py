"""Bill payment tools — LangChain tool wrappers.

Tools:
1. get_registered_billers: List user's registered biller accounts
2. lookup_unpaid_bills: Find unpaid bills for a customer bill code
3. pay_bill: Execute bill payment (after confirmation)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from langchain_core.tools import tool

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


@tool
def get_registered_billers(user_id: str) -> dict:
    """List all registered biller accounts for a user.

    Returns biller code, name, type (ELECTRICITY/WATER/INTERNET/etc.),
    customer bill code, and alias.

    Args:
        user_id: Customer cif_no.
    """
    if not user_id:
        return {"status": "failed", "message": "user_id is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT b.biller_code, b.biller_name, b.biller_type,
                           cba.customer_bill_code, cba.alias
                    FROM customer_biller_accounts cba
                    JOIN billers b ON cba.biller_id = b.biller_id
                    WHERE cba.cif_no = %s AND cba.status = 'ACTIVE'
                    ORDER BY b.biller_type, b.biller_name
                    """,
                    (user_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
            return {"status": "success", "billers": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[BILL TOOL] get_registered_billers error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def lookup_unpaid_bills(customer_bill_code: str, biller_code: str = "") -> dict:
    """Look up unpaid bills for a specific customer bill code.

    Returns bill period, amount due, due date for each unpaid bill.

    Args:
        customer_bill_code: The customer's bill code (e.g. PD867472238).
        biller_code: Optional biller code to filter (e.g. EVN_CENTRAL).
    """
    if not customer_bill_code:
        return {"status": "failed", "message": "customer_bill_code is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT bl.bill_id, b.biller_code, b.biller_name, b.biller_type,
                           bl.customer_bill_code, bl.bill_period,
                           bl.amount_due, bl.due_date, bl.status
                    FROM bills bl
                    JOIN billers b ON bl.biller_code = b.biller_code
                    WHERE bl.customer_bill_code = %s AND bl.status = 'UNPAID'
                """
                params: list[Any] = [customer_bill_code]
                if biller_code:
                    query += " AND bl.biller_code = %s"
                    params.append(biller_code)
                query += " ORDER BY bl.due_date ASC"

                cur.execute(query, params)
                rows = [dict(r) for r in cur.fetchall()]
                # Convert types for JSON serialization
                for r in rows:
                    r["amount_due"] = float(r["amount_due"])
                    r["due_date"] = str(r["due_date"])

            if not rows:
                return {
                    "status": "no_bills",
                    "message": f"Không có hóa đơn chưa thanh toán cho mã {customer_bill_code}.",
                }
            return {"status": "success", "bills": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[BILL TOOL] lookup_unpaid_bills error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


BILL_TOOLS = [get_registered_billers, lookup_unpaid_bills]
