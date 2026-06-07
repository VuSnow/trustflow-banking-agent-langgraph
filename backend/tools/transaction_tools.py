"""Transaction tools — LangChain tool wrappers for TransactionAgent.

Tools:
1. text2sql_query: NL question → text2sql-agent for DB lookups
2. verify_recipient: Account verification (internal/external)
3. check_fraud_risk: Fraud screening
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import psycopg2
from langchain_core.tools import tool

from backend.config import DATABASE_URL, CURRENT_BANK_CODE, TEXT2SQL_AGENT_URL

logger = logging.getLogger(__name__)


@tool
async def text2sql_query(question: str, user_id: str = "") -> dict:
    """Send a natural language question to the banking database to look up information.

    Use this to: find beneficiaries by name/alias, find recent transactions,
    resolve temporal references ('tháng trước', 'lần trước', 'người lần trước'),
    find bank_code from bank name, find candidates matching partial info,
    check transaction history for a specific recipient.
    The question should be in Vietnamese and describe what you need.
    Do NOT write SQL — just ask the question naturally.

    Args:
        question: Natural language question about the banking database.
        user_id: Customer cif_no for context injection.
    """
    if not question:
        return {"status": "failed", "message": "question is required."}

    if user_id and user_id not in question:
        question = f"{question} (user cif_no: {user_id})"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TEXT2SQL_AGENT_URL}/query/execute",
                json={"question": question, "execute": True},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"status": "failed", "message": f"HTTP {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"status": "failed", "message": f"Connection error: {e}"}

    status = data.get("status")
    if status == "success":
        rows = data.get("results") or []
        return {
            "status": "success",
            "rows": rows,
            "row_count": data.get("row_count", len(rows)),
            "sql": data.get("sql", ""),
        }
    elif status == "needs_clarification":
        return {
            "status": "needs_clarification",
            "message": "\n".join(data.get("questions", ["Cần thêm thông tin."])),
        }
    elif status == "blocked":
        return {"status": "failed", "message": data.get("reason", "Query blocked.")}
    else:
        return {"status": "failed", "message": data.get("error", "Unknown error.")}


@tool
def verify_recipient(account_no: str, bank_code: str) -> dict:
    """Verify a recipient account and get the official holder name.

    Routes internally (SHB) or externally (inter-bank/Napas) based on bank_code.
    MANDATORY verification step before creating a draft.

    Args:
        account_no: The recipient account number.
        bank_code: The bank code (e.g. VCB, TCB, SHB).
    """
    if not account_no:
        return {"status": "failed", "message": "account_no is required."}
    if not bank_code:
        return {"status": "failed", "message": "bank_code is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                if bank_code.upper() == CURRENT_BANK_CODE:
                    cur.execute(
                        "SELECT c.full_name, a.status "
                        "FROM accounts a "
                        "JOIN customers c ON a.cif_no = c.cif_no "
                        "WHERE a.account_no = %s LIMIT 1",
                        (account_no,),
                    )
                    row = cur.fetchone()
                    if row:
                        if row[1] != "ACTIVE":
                            return {
                                "status": "inactive",
                                "message": f"Tài khoản {account_no} tại {CURRENT_BANK_CODE} không hoạt động (status: {row[1]}).",
                                "account_no": account_no,
                                "bank_code": CURRENT_BANK_CODE,
                            }
                        return {
                            "status": "success",
                            "resolved_name": row[0],
                            "bank_code": CURRENT_BANK_CODE,
                            "bank_name": "SHB",
                            "account_status": row[1],
                            "account_no": account_no,
                            "transfer_type": "intrabank",
                        }
                    else:
                        return {
                            "status": "not_found",
                            "message": f"Không tìm thấy tài khoản {account_no} tại {CURRENT_BANK_CODE}.",
                            "account_no": account_no,
                            "bank_code": bank_code,
                        }
                else:
                    cur.execute(
                        "SELECT account_holder_name, bank_name, status "
                        "FROM external_bank_accounts "
                        "WHERE account_no = %s AND bank_code = %s LIMIT 1",
                        (account_no, bank_code.upper()),
                    )
                    row = cur.fetchone()
                    if row:
                        if row[2] != "ACTIVE":
                            return {
                                "status": "inactive",
                                "message": f"Tài khoản {account_no} tại {bank_code} không hoạt động.",
                                "account_no": account_no,
                                "bank_code": bank_code,
                            }
                        return {
                            "status": "success",
                            "resolved_name": row[0],
                            "bank_code": bank_code.upper(),
                            "bank_name": row[1],
                            "account_status": row[2],
                            "account_no": account_no,
                            "transfer_type": "interbank",
                        }
                    else:
                        return {
                            "status": "not_found",
                            "message": f"Không tìm thấy tài khoản {account_no} tại {bank_code}.",
                            "account_no": account_no,
                            "bank_code": bank_code,
                        }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[verify_recipient] error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def check_fraud_risk(account_no: str, bank_code: str = "") -> dict:
    """Check if a recipient account has been reported for fraud.

    Queries reported_accounts table for risk assessment.
    This can be called directly for user risk-check questions, or after
    recipient verification in the transfer flow.

    Args:
        account_no: The recipient account number to screen.
        bank_code: The bank code (optional, for more precise lookup).
    """
    if not account_no:
        return {"status": "failed", "message": "account_no is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT risk_level, valid_report_count, total_reported_amount,
                           unique_reporter_count, status
                    FROM reported_accounts
                    WHERE account_no = %s
                """
                params: list[Any] = [account_no]
                if bank_code:
                    query += " AND bank_code = %s"
                    params.append(bank_code.upper())
                query += " LIMIT 1"

                cur.execute(query, params)
                row = cur.fetchone()

                if row:
                    return {
                        "status": "found",
                        "is_reported": True,
                        "risk_level": row[0],
                        "report_count": row[1],
                        "total_reported_amount": row[2],
                        "unique_reporter_count": row[3],
                        "account_status": row[4],
                        "account_no": account_no,
                        "bank_code": bank_code,
                    }
                else:
                    return {
                        "status": "clean",
                        "is_reported": False,
                        "risk_level": "LOW",
                        "account_no": account_no,
                        "bank_code": bank_code,
                    }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[check_fraud_risk] error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


# All transaction tools for the agent
TRANSACTION_TOOLS = [text2sql_query, verify_recipient, check_fraud_risk]
