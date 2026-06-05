"""Finance advisor tools — delegates to text2sql_query for flexible data retrieval.

Instead of hardcoded SQL with keyword-based date parsing, the finance agent
uses text2sql_query (which handles natural language date ranges) and a
recurring payments aggregator.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from langchain_core.tools import tool

from backend.config import DATABASE_URL
from backend.tools.transaction_tools import text2sql_query

logger = logging.getLogger(__name__)


@tool
def get_recurring_payments(user_id: str, lookback_days: int = 90) -> dict:
    """Identify recurring/subscription payments from transaction history.

    Looks for repeated payments to the same counterparty with similar amounts.
    Use this to detect subscriptions, rent, or habitual payments.

    Args:
        user_id: Customer cif_no.
        lookback_days: Number of days to look back (default 90 for pattern detection).
    """
    if not user_id:
        return {"status": "failed", "message": "user_id is required."}

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT counterparty_name, COUNT(*) as tx_count,
                           AVG(amount) as avg_amount, SUM(amount) as total,
                           MIN(transaction_time) as first_seen,
                           MAX(transaction_time) as last_seen
                    FROM transactions
                    WHERE cif_no = %s AND direction = 'OUT' AND status = 'SUCCESS'
                      AND transaction_time >= %s AND counterparty_name IS NOT NULL
                    GROUP BY counterparty_name
                    HAVING COUNT(*) >= 2
                    ORDER BY COUNT(*) DESC
                    LIMIT 15
                    """,
                    (user_id, cutoff),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        return {"status": "failed", "message": f"Database error: {e}"}

    recurring = []
    for r in rows:
        recurring.append({
            "counterparty": r["counterparty_name"],
            "frequency": r["tx_count"],
            "avg_amount": int(r["avg_amount"]),
            "total_spent": int(r["total"]),
            "first_seen": str(r["first_seen"])[:10] if r["first_seen"] else None,
            "last_seen": str(r["last_seen"])[:10] if r["last_seen"] else None,
        })

    return {
        "status": "success",
        "recurring_payments": recurring,
        "count": len(recurring),
    }


# Finance agent uses text2sql_query (from transaction_tools) for flexible
# data retrieval + get_recurring_payments for pattern detection
FINANCE_TOOLS = [text2sql_query, get_recurring_payments]
