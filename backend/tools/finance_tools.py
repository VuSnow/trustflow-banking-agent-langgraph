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


@tool
def get_interest_rates(product_type: str = "SAVINGS", term_months: int = 0, channel: str = "ONLINE") -> dict:
    """Get current bank interest rates for savings or loan products.

    Use this to recommend savings/investment options based on user's available funds.
    Returns rates sorted by term. This is a deterministic lookup — no text2sql needed.

    Args:
        product_type: SAVINGS or LOAN.
        term_months: Specific term (1,3,6,12,24). Use 0 for all terms.
        channel: ONLINE, COUNTER, or ALL.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT product_code, product_name, term_months, annual_rate,
                           min_amount, channel
                    FROM interest_rates
                    WHERE product_type = %s AND status = 'ACTIVE'
                      AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                      AND effective_from <= CURRENT_DATE
                """
                params: list = [product_type.upper()]

                if term_months > 0:
                    query += " AND term_months = %s"
                    params.append(term_months)

                if channel.upper() != "ALL":
                    query += " AND (channel = %s OR channel = 'ALL')"
                    params.append(channel.upper())

                query += " ORDER BY term_months ASC NULLS FIRST, annual_rate DESC"
                cur.execute(query, params)
                rows = [dict(r) for r in cur.fetchall()]

                for r in rows:
                    r["annual_rate"] = float(r["annual_rate"])
                    r["min_amount"] = int(r["min_amount"]) if r["min_amount"] else 0

            if not rows:
                return {"status": "success", "rates": [], "message": "Không tìm thấy sản phẩm phù hợp."}
            return {"status": "success", "rates": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[FINANCE TOOL] get_interest_rates error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def get_account_balance(user_id: str) -> dict:
    """Get user's current account balances (payment + savings).

    Use this to know how much money the user has available for budgeting,
    savings recommendations, or daily spending calculations.

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
                    SELECT account_no, account_type, balance, available_balance, status
                    FROM accounts
                    WHERE cif_no = %s AND status = 'ACTIVE'
                    ORDER BY account_type, balance DESC
                    """,
                    (user_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]

            total_payment = sum(int(r["balance"]) for r in rows if r["account_type"] == "PAYMENT")
            total_savings = sum(int(r["balance"]) for r in rows if r["account_type"] == "SAVINGS")

            return {
                "status": "success",
                "accounts": [
                    {"account_no": r["account_no"], "type": r["account_type"], "balance": int(r["balance"])}
                    for r in rows
                ],
                "total_payment_balance": total_payment,
                "total_savings_balance": total_savings,
                "total_balance": total_payment + total_savings,
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[FINANCE TOOL] get_account_balance error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def calculate_budget(balance: int, days_remaining: int, fixed_expenses: int = 0) -> dict:
    """Calculate daily/weekly budget given balance and days until next income.

    Use this for ALL arithmetic — do NOT calculate numbers yourself.
    Call this AFTER getting balance from get_account_balance and determining days_remaining.

    Args:
        balance: Current available balance in VND (from get_account_balance).
        days_remaining: Days until next salary/income.
        fixed_expenses: Known upcoming fixed expenses (bills, rent) to subtract first. Default 0.
    """
    if days_remaining <= 0:
        return {"status": "failed", "message": "days_remaining must be > 0"}

    available = balance - fixed_expenses
    daily_budget = available // days_remaining
    weekly_budget = daily_budget * 7

    # Spending allocation suggestion (based on typical Vietnamese household ratios)
    food_pct = 0.45
    transport_pct = 0.20
    bills_pct = 0.15
    buffer_pct = 0.20

    return {
        "status": "success",
        "balance": balance,
        "fixed_expenses": fixed_expenses,
        "available_for_spending": available,
        "days_remaining": days_remaining,
        "daily_budget": daily_budget,
        "weekly_budget": weekly_budget,
        "monthly_equivalent": daily_budget * 30,
        "suggested_allocation": {
            "food_daily": int(daily_budget * food_pct),
            "transport_daily": int(daily_budget * transport_pct),
            "bills_daily": int(daily_budget * bills_pct),
            "buffer_daily": int(daily_budget * buffer_pct),
        },
        "warning": "CRITICALLY_LOW" if daily_budget < 50000 else "LOW" if daily_budget < 100000 else "OK",
    }


@tool
def calculate_savings_interest(principal: int, annual_rate: float, term_months: int) -> dict:
    """Calculate expected interest for a savings deposit.

    Use this for ALL interest calculations — do NOT calculate yourself.

    Args:
        principal: Amount to deposit in VND.
        annual_rate: Annual interest rate as percentage (e.g. 4.5 for 4.5%).
        term_months: Deposit term in months.
    """
    if principal <= 0 or annual_rate <= 0 or term_months <= 0:
        return {"status": "failed", "message": "All parameters must be positive."}

    # Simple interest (Vietnamese savings standard for < 12 months)
    interest = int(principal * (annual_rate / 100) * term_months / 12)
    total_at_maturity = principal + interest
    monthly_interest = interest // term_months

    return {
        "status": "success",
        "principal": principal,
        "annual_rate": annual_rate,
        "term_months": term_months,
        "total_interest": interest,
        "total_at_maturity": total_at_maturity,
        "monthly_interest": monthly_interest,
        "effective_monthly_rate": round(annual_rate / 12, 3),
    }


# Finance agent tools: text2sql for flexible queries + specialized deterministic tools
FINANCE_TOOLS = [
    text2sql_query,
    get_recurring_payments,
    get_interest_rates,
    get_account_balance,
    calculate_budget,
    calculate_savings_interest,
]
