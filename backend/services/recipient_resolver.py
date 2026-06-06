"""Recipient Resolver — deterministic SQL-based recipient lookup.

This is the ONLY path for resolving recipients in transaction flows.
No LLM, no Text2SQL, no natural language queries. Pure structured SQL.

Methods:
- find_by_name: fuzzy match saved beneficiaries
- find_last_transfer_recipient: most recent outgoing bank transfer
- find_by_account_no: direct account verification (internal/external)
- resolve_from_plan: resolve using structured RecipientResolutionPlan
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

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
        """Search saved beneficiaries by name (unaccent fuzzy match).

        Args:
            user_id: Customer cif_no.
            name_query: Partial name to search.
            max_results: Max candidates to return.

        Returns:
            List of matching beneficiary candidates.
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
        """Find counterparty from most recent successful outgoing BANK_TRANSFER.

        Filters: transaction_type=BANK_TRANSFER, direction=OUT, status=SUCCESS.
        """
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
        """Direct account lookup — internal (accounts table) or external (external_bank_accounts).

        Args:
            account_no: Full account number.
            bank_code: Bank code (e.g. SHB, VCB).

        Returns:
            RecipientCandidate if found and active, None otherwise.
        """
        if not account_no or not bank_code:
            return None

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if bank_code.upper() == CURRENT_BANK_CODE:
                        # Internal account
                        cur.execute(
                            """
                            SELECT c.full_name, a.account_no, a.status
                            FROM accounts a
                            JOIN customers c ON a.cif_no = c.cif_no
                            WHERE a.account_no = %s AND a.status = 'ACTIVE'
                            LIMIT 1
                            """,
                            (account_no,),
                        )
                        row = cur.fetchone()
                        if not row:
                            return None
                        return RecipientCandidate(
                            beneficiary_id=None,
                            name=row["full_name"],
                            account_no=row["account_no"],
                            account_no_masked=_mask_account(row["account_no"]),
                            bank_code=CURRENT_BANK_CODE,
                            bank_name="SHB",
                        )
                    else:
                        # External account
                        cur.execute(
                            """
                            SELECT account_holder_name, bank_name, status
                            FROM external_bank_accounts
                            WHERE account_no = %s AND bank_code = %s AND status = 'ACTIVE'
                            LIMIT 1
                            """,
                            (account_no, bank_code.upper()),
                        )
                        row = cur.fetchone()
                        if not row:
                            return None
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
            logger.error(f"[RECIPIENT_RESOLVER] find_by_account_no error: {e}")
            return None

    def verify_recipient(self, account_no: str, bank_code: str) -> dict:
        """Verify account exists and is active. Returns verification result dict.

        This is the mandatory verification step before moving to draft confirmation.
        """
        candidate = self.find_by_account_no(account_no, bank_code)
        if candidate:
            return {
                "status": "verified",
                "name": candidate.name,
                "account_no": candidate.account_no,
                "bank_code": candidate.bank_code,
                "bank_name": candidate.bank_name,
                "transfer_type": "intrabank" if bank_code.upper() == CURRENT_BANK_CODE else "interbank",
            }
        return {
            "status": "not_found",
            "account_no": account_no,
            "bank_code": bank_code,
        }

    def check_fraud_risk(self, account_no: str, bank_code: str = "") -> dict:
        """Check if recipient account has fraud reports."""
        if not account_no:
            return {"is_reported": False, "risk_level": "LOW", "report_count": 0}

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
                    params: list = [account_no]
                    if bank_code:
                        query += " AND bank_code = %s"
                        params.append(bank_code.upper())
                    query += " LIMIT 1"

                    cur.execute(query, params)
                    row = cur.fetchone()

                    if not row:
                        return {"is_reported": False, "risk_level": "LOW", "report_count": 0}

                    return {
                        "is_reported": True,
                        "risk_level": row[0],
                        "report_count": row[1] or 0,
                        "total_reported_amount": row[2] or 0,
                        "unique_reporter_count": row[3] or 0,
                        "report_status": row[4],
                    }
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] check_fraud_risk error: {e}")
            return {"is_reported": False, "risk_level": "LOW", "report_count": 0}

    def resolve_bank_code(self, bank_name: str) -> str | None:
        """Resolve bank name to bank code using known mapping."""
        mapping = {
            "vietcombank": "VCB",
            "vcb": "VCB",
            "techcombank": "TCB",
            "tcb": "TCB",
            "acb": "ACB",
            "bidv": "BIDV",
            "vietinbank": "CTG",
            "ctg": "CTG",
            "mb bank": "MBB",
            "mb": "MBB",
            "mbb": "MBB",
            "sacombank": "STB",
            "stb": "STB",
            "vpbank": "VPB",
            "vpb": "VPB",
            "tpbank": "TPB",
            "tpb": "TPB",
            "hdbank": "HDB",
            "hdb": "HDB",
            "shb": "SHB",
            "ocb": "OCB",
        }
        return mapping.get(bank_name.strip().lower())

    def _resolve_bank_name(self, bank_code: str | None) -> str:
        """Bank code → display name."""
        if not bank_code:
            return ""
        names = {
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
        return names.get(bank_code.upper(), bank_code)

    # ─── Plan-based resolution ────────────────────────────────────────────

    def resolve_from_plan(
        self, user_id: str, plan: RecipientResolutionPlan
    ) -> ResolutionResult:
        """Resolve recipient from structured RecipientResolutionPlan.

        Dispatches to the appropriate method based on plan.target:
        - saved_beneficiary → find_by_name with constraints
        - past_transaction → dynamic SQL on transactions table
        - direct_account → find_by_account_no with bank resolution
        - unknown → empty result

        Returns:
            ResolutionResult with candidates and optional copied fields.
        """
        if plan.target == "saved_beneficiary":
            return self._resolve_saved_beneficiary(user_id, plan)
        elif plan.target == "past_transaction":
            return self._resolve_past_transaction(user_id, plan)
        elif plan.target == "direct_account":
            return self._resolve_direct_account(plan)
        else:
            return ResolutionResult()

    def _resolve_saved_beneficiary(
        self, user_id: str, plan: RecipientResolutionPlan
    ) -> ResolutionResult:
        """Resolve from saved beneficiaries using plan constraints."""
        name_query = ""
        for c in plan.constraints:
            if c.field == "recipient_name" and c.operator in ("contains", "equals"):
                name_query = str(c.value)
                break

        if not name_query:
            return ResolutionResult()

        limit = plan.limit or 5
        candidates = self.find_by_name(user_id, name_query, max_results=limit)
        return ResolutionResult(candidates=candidates)

    def _resolve_past_transaction(
        self, user_id: str, plan: RecipientResolutionPlan
    ) -> ResolutionResult:
        """Resolve from transaction history using plan constraints.

        Builds a parameterized SQL query from QueryConstraints.
        Only allows safe fields/operators against transactions table.
        """
        ALLOWED_FIELDS = {
            "direction", "transaction_type", "status", "counterparty_name",
            "recipient_name", "note", "amount", "transaction_time",
        }
        # Map logical fields to actual DB columns
        FIELD_MAP = {
            "direction": "direction",
            "transaction_type": "transaction_type",
            "status": "status",
            "recipient_name": "counterparty_name",
            "note": "note",
            "amount": "amount",
            "transaction_time": "transaction_time",
        }

        where_clauses = ["cif_no = %s"]
        params: list = [user_id]

        for c in plan.constraints:
            if c.field not in ALLOWED_FIELDS:
                continue

            db_col = FIELD_MAP.get(c.field, c.field)

            if c.operator == "equals":
                where_clauses.append(f"{db_col} = %s")
                params.append(str(c.value))
            elif c.operator == "contains":
                where_clauses.append(f"unaccent(lower({db_col})) LIKE unaccent(lower(%s))")
                params.append(f"%{c.value}%")
            elif c.operator == "between" and isinstance(c.value, dict):
                start = c.value.get("start")
                end = c.value.get("end")
                if start and end:
                    where_clauses.append(f"{db_col} >= %s AND {db_col} < %s")
                    params.extend([start, end])
            elif c.operator == "gte":
                where_clauses.append(f"{db_col} >= %s")
                params.append(c.value)
            elif c.operator == "lte":
                where_clauses.append(f"{db_col} <= %s")
                params.append(c.value)
            elif c.operator == "recent":
                # Interpret "recent" as last 90 days
                cutoff = (date.today() - timedelta(days=90)).isoformat()
                where_clauses.append(f"{db_col} >= %s")
                params.append(cutoff)

        # Build ORDER BY from plan.sort
        order_parts = []
        SORT_FIELD_MAP = {
            "transaction_time": "transaction_time",
            "amount": "amount",
        }
        for s in (plan.sort or []):
            col = SORT_FIELD_MAP.get(s.field)
            if col:
                direction = "ASC" if s.direction == "asc" else "DESC"
                order_parts.append(f"{col} {direction}")
        order_clause = "ORDER BY " + ", ".join(order_parts) if order_parts else "ORDER BY transaction_time DESC"

        limit = plan.limit or 5
        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT counterparty_name, counterparty_account_no,
                   counterparty_bank_code, amount, note
            FROM transactions
            WHERE {where_sql}
            {order_clause}
            LIMIT %s
        """
        params.append(limit)

        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

                    if not rows:
                        return ResolutionResult()

                    candidates = []
                    copied_fields: dict = {}

                    for i, row in enumerate(rows):
                        if not row.get("counterparty_account_no"):
                            continue

                        bank_code = row.get("counterparty_bank_code") or ""
                        bank_name = self._resolve_bank_name(bank_code) if bank_code else ""
                        candidates.append(
                            RecipientCandidate(
                                beneficiary_id=None,
                                name=row.get("counterparty_name") or "",
                                account_no=row["counterparty_account_no"],
                                account_no_masked=_mask_account(row["counterparty_account_no"]),
                                bank_code=bank_code,
                                bank_name=bank_name,
                            )
                        )

                        # Copy fields from first matching transaction
                        if i == 0 and plan.copy_fields:
                            if "amount" in plan.copy_fields and row.get("amount"):
                                copied_fields["amount"] = int(row["amount"])
                            if "note" in plan.copy_fields and row.get("note"):
                                copied_fields["note"] = row["note"]

                    return ResolutionResult(
                        candidates=candidates,
                        copied_fields=copied_fields if copied_fields else None,
                    )
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[RECIPIENT_RESOLVER] resolve_past_transaction error: {e}")
            return ResolutionResult()

    def _resolve_direct_account(self, plan: RecipientResolutionPlan) -> ResolutionResult:
        """Resolve direct account from plan constraints."""
        account_no = ""
        bank_name = ""
        bank_code = ""

        for c in plan.constraints:
            if c.field == "account_no" and c.operator == "equals":
                account_no = str(c.value)
            elif c.field == "bank_name" and c.operator == "equals":
                bank_name = str(c.value)
            elif c.field == "bank_code" and c.operator == "equals":
                bank_code = str(c.value)

        # Resolve bank_code from bank_name if not provided
        if not bank_code and bank_name:
            resolved = self.resolve_bank_code(bank_name)
            if resolved:
                bank_code = resolved

        if not account_no or not bank_code:
            return ResolutionResult()

        candidate = self.find_by_account_no(account_no, bank_code)
        if candidate:
            return ResolutionResult(candidates=[candidate])

        # Account not verified in our DB but user gave explicit details
        return ResolutionResult(
            candidates=[
                RecipientCandidate(
                    beneficiary_id=None,
                    name="",
                    account_no=account_no,
                    account_no_masked=_mask_account(account_no),
                    bank_code=bank_code,
                    bank_name=bank_name or self._resolve_bank_name(bank_code),
                )
            ]
        )


@dataclass
class ResolutionResult:
    """Result from plan-based resolution.

    candidates: matched recipients (may be empty).
    copied_fields: fields to copy from resolved transaction (amount, note, etc.).
    """

    candidates: list[RecipientCandidate] = field(default_factory=list)
    copied_fields: dict | None = None
