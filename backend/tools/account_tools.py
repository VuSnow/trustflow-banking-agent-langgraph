"""Account operation tools — LangChain tool wrappers for AccountOperationAgent.

Tools:
1. get_user_accounts: List all accounts belonging to user
2. get_account_detail: Get full account detail
3. list_account_products: List available account products
"""
from __future__ import annotations

import logging
from typing import Any

import psycopg2
import psycopg2.extras
from langchain_core.tools import tool

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


@tool
def get_user_accounts(user_id: str) -> dict:
    """List all bank accounts belonging to a user.

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
                    SELECT account_id, account_no, account_type, currency,
                           balance, available_balance, status, is_primary,
                           nickname, opened_at
                    FROM accounts WHERE cif_no = %s
                    ORDER BY is_primary DESC, opened_at ASC
                    """,
                    (user_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    r["account_id"] = str(r["account_id"])
            return {"status": "success", "accounts": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ACCOUNT TOOL] get_user_accounts error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def get_account_detail(user_id: str, account_no: str = "", account_id: str = "") -> dict:
    """Get full account detail. Validates ownership.

    Args:
        user_id: Customer cif_no.
        account_no: Account number (optional if account_id given).
        account_id: Account UUID (optional if account_no given).
    """
    if not user_id:
        return {"status": "failed", "message": "user_id is required."}
    if not account_no and not account_id:
        return {"status": "failed", "message": "account_no or account_id is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if account_id:
                    cur.execute(
                        """
                        SELECT account_id, account_no, account_type, currency,
                               balance, available_balance, status, is_primary, nickname, opened_at
                        FROM accounts WHERE account_id = %s::uuid AND cif_no = %s
                        """,
                        (account_id, user_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT account_id, account_no, account_type, currency,
                               balance, available_balance, status, is_primary, nickname, opened_at
                        FROM accounts WHERE account_no = %s AND cif_no = %s
                        """,
                        (account_no, user_id),
                    )
                row = cur.fetchone()
            if not row:
                return {"status": "not_found", "message": "Không tìm thấy tài khoản."}
            result = dict(row)
            result["account_id"] = str(result["account_id"])
            return {"status": "success", "account": result}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ACCOUNT TOOL] get_account_detail error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def list_account_products() -> dict:
    """List available account products that can be opened."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT product_code, product_name, account_type, currency,
                           monthly_fee, opening_fee, description
                    FROM account_products WHERE is_active = true
                    ORDER BY product_code
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
            return {"status": "success", "products": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ACCOUNT TOOL] list_account_products error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


ACCOUNT_TOOLS = [get_user_accounts, get_account_detail, list_account_products]
