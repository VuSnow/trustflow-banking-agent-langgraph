"""Recipient Resolver — deterministic SQL-based recipient lookup.

This is the ONLY path for resolving recipients in transaction flows.
No LLM, no Text2SQL — pure structured SQL queries.

Methods:
- find_by_name: fuzzy match saved beneficiaries
- find_last_transfer_recipient: most recent outgoing BANK_TRANSFER
- find_by_account_no: direct account verification (internal/external)
- resolve_from_plan: execute a RecipientResolutionPlan
- check_fraud_risk: screen account for fraud reports
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL, CURRENT_BANK_CODE
from backend.models.flow import RecipientResolutionPlan, QueryConstraint

logger = logging.getLogger(__name__)


@dataclass
class RecipientCandidate:
    """A resolved recipient candidate from DB lookup."""

    beneficiary_id: str | None
    name: str
    account_no: str
    account_no_masked: str
    bank_code: str
    bank_name: str


@dataclass
class ResolutionResult:
    """Result of a resolve_from_plan call."""

    candidates: list[RecipientCandidate] = field(default_factory=list)
    copied_fields: dict = field(default_factory=dict)


def _mask_account(account_no: str) -> str:
    """Mask account number: show last 4 digits only."""
    if len(account_no) <= 4:
        return account_no
    return "****" + account_no[-4:]


class RecipientResolver:
    """Deterministic SQL recipient resolution — no LLM in this path."""

    def find_by_name(
        self, user_id: str, name_query: str, max_results: int = 5
    ) -> list[RecipientCandidate]:
        """Search saved beneficiaries by name (fuzzy match).

        Args:
            user_id: Customer cif_no.
            name_query: Partial name to search.
            max_results: Max candidates to return.
        """
        if not name_query or not user_id:
            return []

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT beneficiary_id, beneficiary_name, beneficiary_account_no,
                               beneficiary_bank_code, beneficiary_bank_name
                        FROM beneficiaries
                        WHERE cif_no = %s
                          AND unaccent(lower(beneficiary_name)) LIKE unaccent(lower(%s))
                        ORDER BY last_used_at DESC NULLS LAST
                        LIMIT %s
                        """,
                        (user_id, f"%{name_query}%", max_results),
                    )
                    rows = cur.fetchall()
                    return [
                        RecipientCandidate(
                            beneficiary_id=row["beneficiary_id"],
                            name=row["beneficiary_name"],
                            account_no=str(row["beneficiary_account_no"]),
                            account_no_masked=_mask_account(str(row["beneficiary_account_no"])),
                            bank_code=row["beneficiary_bank_code"],
                            bank_name=row["beneficiary_bank_name"] or row["beneficiary_bank_code"],
                        )
                        for row in rows
                    ]
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] find_by_name error: {e}")
            return []

    def find_last_transfer_recipient(self, user_id: str) -> RecipientCandidate | None:
        """Find counterparty from most recent successful outgoing BANK_TRANSFER."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT counterparty_name, counterparty_account_no,
                               counterparty_bank_code
                        FROM transactions
                        WHERE cif_no = %s
                          AND transaction_type = 'BANK_TRANSFER'
                          AND direction = 'OUT'
                          AND status = 'SUCCESS'
                        ORDER BY transaction_time DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if not row or not row["counterparty_account_no"]:
                        return None

                    bank_name = self._resolve_bank_name(row["counterparty_bank_code"])
                    return RecipientCandidate(
                        beneficiary_id=None,
                        name=row["counterparty_name"] or "",
                        account_no=row["counterparty_account_no"],
                        account_no_masked=_mask_account(row["counterparty_account_no"]),
                        bank_code=row["counterparty_bank_code"] or "",
                        bank_name=bank_name,
                    )
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] find_last_transfer error: {e}")
            return None

    def find_by_account_no(
        self, account_no: str, bank_code: str
    ) -> RecipientCandidate | None:
        """Verify account and get holder name. Routes internal vs external."""
        if not account_no or not bank_code:
            return None

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if bank_code.upper() == CURRENT_BANK_CODE:
                        cur.execute(
                            """
                            SELECT c.full_name, a.status
                            FROM accounts a
                            JOIN customers c ON a.cif_no = c.cif_no
                            WHERE a.account_no = %s
                            LIMIT 1
                            """,
                            (account_no,),
                        )
                        row = cur.fetchone()
                        if row and row["status"] == "ACTIVE":
                            return RecipientCandidate(
                                beneficiary_id=None,
                                name=row["full_name"],
                                account_no=account_no,
                                account_no_masked=_mask_account(account_no),
                                bank_code=CURRENT_BANK_CODE,
                                bank_name="SHB",
                            )
                    else:
                        cur.execute(
                            """
                            SELECT account_holder_name, bank_name, status
                            FROM external_bank_accounts
                            WHERE account_no = %s AND bank_code = %s
                            LIMIT 1
                            """,
                            (account_no, bank_code.upper()),
                        )
                        row = cur.fetchone()
                        if row and row["status"] == "ACTIVE":
                            return RecipientCandidate(
                                beneficiary_id=None,
                                name=row["account_holder_name"],
                                account_no=account_no,
                                account_no_masked=_mask_account(account_no),
                                bank_code=bank_code.upper(),
                                bank_name=row["bank_name"] or bank_code.upper(),
                            )
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] find_by_account error: {e}")
        return None

    def verify_recipient(self, account_no: str, bank_code: str) -> dict:
        """Verify recipient account. Returns status dict with transfer_type."""
        if not account_no or not bank_code:
            return {"status": "failed", "message": "Missing account_no or bank_code"}

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    if bank_code.upper() == CURRENT_BANK_CODE:
                        cur.execute(
                            "SELECT c.full_name, a.status "
                            "FROM accounts a JOIN customers c ON a.cif_no = c.cif_no "
                            "WHERE a.account_no = %s LIMIT 1",
                            (account_no,),
                        )
                        row = cur.fetchone()
                        if not row:
                            return {"status": "not_found"}
                        if row[1] != "ACTIVE":
                            return {"status": "inactive"}
                        return {
                            "status": "success",
                            "resolved_name": row[0],
                            "transfer_type": "intrabank",
                        }
                    else:
                        cur.execute(
                            "SELECT account_holder_name, bank_name, status "
                            "FROM external_bank_accounts "
                            "WHERE account_no = %s AND bank_code = %s LIMIT 1",
                            (account_no, bank_code.upper()),
                        )
                        row = cur.fetchone()
                        if not row:
                            return {"status": "not_found"}
                        if row[2] != "ACTIVE":
                            return {"status": "inactive"}
                        return {
                            "status": "success",
                            "resolved_name": row[0],
                            "transfer_type": "interbank",
                        }
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] verify error: {e}")
            return {"status": "failed", "message": str(e)}

    def check_fraud_risk(self, account_no: str, bank_code: str = "") -> dict:
        """Check if a recipient account has been reported for fraud."""
        if not account_no:
            return {"is_reported": False, "risk_level": "LOW"}

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    query = """
                        SELECT risk_level, valid_report_count, total_reported_amount,
                               unique_reporter_count
                        FROM reported_accounts
                        WHERE account_no = %s
                    """
                    params: list = [account_no]
                    if bank_code:
                        query += " AND bank_code = %s"
                        params.append(bank_code.upper())
                    query += " LIMIT 1"

                    cur.execute(query, params)
                    row = cur.fetchone()

                    if row:
                        return {
                            "is_reported": True,
                            "risk_level": row[0],
                            "report_count": row[1],
                            "total_reported_amount": row[2],
                            "unique_reporter_count": row[3],
                        }
                    return {"is_reported": False, "risk_level": "LOW"}
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] fraud check error: {e}")
            return {"is_reported": False, "risk_level": "LOW"}

    def resolve_from_plan(
        self, user_id: str, plan: RecipientResolutionPlan
    ) -> ResolutionResult:
        """Execute a structured RecipientResolutionPlan.

        Dispatches to the appropriate resolution method based on plan.target.
        """
        candidates = []
        copied_fields: dict = {}

        if plan.target == "saved_beneficiary":
            # Extract name constraint
            name_query = ""
            for c in plan.constraints:
                if c.field == "recipient_name":
                    name_query = str(c.value)
                    break
            if name_query:
                candidates = self.find_by_name(user_id, name_query, plan.limit)

        elif plan.target == "past_transaction":
            last = self.find_last_transfer_recipient(user_id)
            if last:
                candidates = [last]
                # Copy fields if requested
                if "amount" in plan.copy_fields or "note" in plan.copy_fields:
                    tx_data = self._get_last_transaction_data(user_id)
                    if tx_data:
                        if "amount" in plan.copy_fields:
                            copied_fields["amount"] = tx_data.get("amount")
                        if "note" in plan.copy_fields:
                            copied_fields["note"] = tx_data.get("note")

        elif plan.target == "direct_account":
            # Extract account_no and bank_code from constraints
            account_no = ""
            bank_code = ""
            for c in plan.constraints:
                if c.field == "account_no":
                    account_no = str(c.value)
                elif c.field == "bank_code":
                    bank_code = str(c.value)
            if account_no and bank_code:
                result = self.find_by_account_no(account_no, bank_code)
                if result:
                    candidates = [result]

        return ResolutionResult(candidates=candidates, copied_fields=copied_fields)

    def _get_last_transaction_data(self, user_id: str) -> dict | None:
        """Get amount/note from most recent outgoing BANK_TRANSFER."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT amount, note
                        FROM transactions
                        WHERE cif_no = %s
                          AND transaction_type = 'BANK_TRANSFER'
                          AND direction = 'OUT'
                          AND status = 'SUCCESS'
                        ORDER BY transaction_time DESC
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    return cur.fetchone()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] get_last_tx error: {e}")
            return None

    def _resolve_bank_name(self, bank_code: str | None) -> str:
        """Map bank_code to display name."""
        if not bank_code:
            return ""
        mapping = {
            "VCB": "Vietcombank",
            "TCB": "Techcombank",
            "ACB": "ACB",
            "BIDV": "BIDV",
            "CTG": "VietinBank",
            "MBB": "MB Bank",
            "STB": "Sacombank",
            "VPB": "VPBank",
            "TPB": "TPBank",
            "HDB": "HDBank",
            "SHB": "SHB",
            "OCB": "OCB",
        }
        return mapping.get(bank_code.upper(), bank_code)
