"""Fraud report tools for FraudReportAgent."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from langchain_core.tools import tool

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

RISK_SCORES = {
    "LOW": Decimal("0.25"),
    "MEDIUM": Decimal("0.50"),
    "HIGH": Decimal("0.75"),
    "CRITICAL": Decimal("0.95"),
}


@tool
def save_fraud_report_incident(
    reporter_cif_no: str,
    reported_account_no: str,
    reported_bank_code: str,
    contact_channel: str,
    aftermath: str,
    reason_text: str,
    has_evidence: bool,
    fraud_type: str = "OTHER",
    transaction_ref: str = "",
    reported_amount: int = 0,
    reported_customer_cif: str = "",
) -> dict:
    """Persist a fraud report and update aggregate account risk.

    Args:
        reporter_cif_no: CIF of the customer submitting the report.
        reported_account_no: Account number being reported.
        reported_bank_code: Bank code for the reported account.
        contact_channel: Channel where the scammer contacted the user.
        aftermath: What happened after the incident.
        reason_text: User's description of the incident.
        has_evidence: Whether the user has screenshots/proof.
        fraud_type: Fraud category, default OTHER.
        transaction_ref: Optional related transaction reference.
        reported_amount: Optional fallback amount lost when no transaction is verified.
        reported_customer_cif: Optional linked CIF for the reported account holder.
    """
    payload = {
        "reporter_cif_no": reporter_cif_no,
        "reported_account_no": reported_account_no,
        "reported_bank_code": reported_bank_code,
        "contact_channel": contact_channel,
        "aftermath": aftermath,
        "reason_text": reason_text,
        "has_evidence": has_evidence,
        "fraud_type": fraud_type,
        "transaction_ref": transaction_ref,
        "reported_amount": reported_amount,
        "reported_customer_cif": reported_customer_cif,
    }
    return _save_fraud_report_incident(payload)


def _save_fraud_report_incident(payload: dict[str, Any]) -> dict:
    validation_error = _validate_payload(payload)
    if validation_error:
        return {"status": "failed", "message": validation_error}

    reporter_cif_no = _clean(payload["reporter_cif_no"])
    reported_account_no = _clean(payload["reported_account_no"])
    reported_bank_code = _clean(payload["reported_bank_code"]).upper()
    contact_channel = _clean(payload["contact_channel"]).upper()
    aftermath = _clean(payload["aftermath"]).upper()
    reason_text = _clean(payload["reason_text"])
    fraud_type = _clean(payload.get("fraud_type") or "OTHER").upper() or "OTHER"
    transaction_ref = _clean(payload.get("transaction_ref"))
    reported_customer_cif = _clean(payload.get("reported_customer_cif")) or None
    has_evidence = _as_bool(payload["has_evidence"])
    fallback_amount = _as_non_negative_int(payload.get("reported_amount"))

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                tx = _get_verified_transaction(
                    cur=cur,
                    transaction_ref=transaction_ref,
                    reporter_cif_no=reporter_cif_no,
                    reported_account_no=reported_account_no,
                    reported_bank_code=reported_bank_code,
                )

                cur.execute(
                    """
                    SELECT COUNT(*) AS report_count
                    FROM fraud_reports
                    WHERE reported_account_no = %s
                      AND reported_bank_code = %s
                      AND status <> 'REJECTED'
                    """,
                    (reported_account_no, reported_bank_code),
                )
                existing_report_count = int(cur.fetchone()["report_count"] or 0)
                existing_reported_amount = _load_existing_reported_amount(
                    cur, reported_account_no, reported_bank_code
                )

                if tx:
                    incident_amount = int(tx["amount"] or 0)
                    confidence_score = _calculate_verified_confidence(
                        transaction_time=tx["transaction_time"],
                        fraud_type=fraud_type,
                        aftermath=aftermath,
                        has_evidence=has_evidence,
                    )
                    stored_transaction_ref = tx["transaction_ref"]
                else:
                    incident_amount = fallback_amount
                    confidence_score = _calculate_unverified_confidence(
                        has_evidence=has_evidence,
                        existing_report_count=existing_report_count,
                        reason_text=reason_text,
                    )
                    stored_transaction_ref = None

                report_status = "VALIDATED" if confidence_score >= 80 else "SUBMITTED"
                report_id = str(uuid.uuid4())
                now = datetime.now()

                cur.execute(
                    """
                    INSERT INTO fraud_reports (
                        report_id, reporter_cif_no, transaction_ref,
                        reported_account_no, reported_bank_code, reported_customer_cif,
                        fraud_type, contact_channel, aftermath, reason_text,
                        has_evidence, confidence_score, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        report_id,
                        reporter_cif_no,
                        stored_transaction_ref,
                        reported_account_no,
                        reported_bank_code,
                        reported_customer_cif,
                        fraud_type,
                        contact_channel,
                        aftermath,
                        reason_text,
                        has_evidence,
                        confidence_score,
                        report_status,
                        now,
                    ),
                )

                aggregate = _load_account_aggregate(cur, reported_account_no, reported_bank_code)
                total_reported_amount = existing_reported_amount + incident_amount
                risk_level = _calculate_account_risk_level(
                    report_count=int(aggregate["valid_report_count"] or 0),
                    unique_reporters=int(aggregate["unique_reporter_count"] or 0),
                    avg_confidence=int(aggregate["avg_confidence_score"] or 0),
                )
                risk_score = RISK_SCORES[risk_level]

                cur.execute(
                    """
                    INSERT INTO reported_accounts (
                        reported_account_id, account_no, bank_code, linked_customer_cif,
                        valid_report_count, unique_reporter_count, total_reported_amount,
                        avg_confidence_score, risk_score, risk_level, status,
                        first_reported_at, last_reported_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s)
                    ON CONFLICT (account_no, bank_code)
                    DO UPDATE SET
                        linked_customer_cif = COALESCE(EXCLUDED.linked_customer_cif, reported_accounts.linked_customer_cif),
                        valid_report_count = EXCLUDED.valid_report_count,
                        unique_reporter_count = EXCLUDED.unique_reporter_count,
                        total_reported_amount = EXCLUDED.total_reported_amount,
                        avg_confidence_score = EXCLUDED.avg_confidence_score,
                        risk_score = EXCLUDED.risk_score,
                        risk_level = EXCLUDED.risk_level,
                        status = EXCLUDED.status,
                        first_reported_at = EXCLUDED.first_reported_at,
                        last_reported_at = EXCLUDED.last_reported_at
                    """,
                    (
                        str(uuid.uuid4()),
                        reported_account_no,
                        reported_bank_code,
                        reported_customer_cif,
                        int(aggregate["valid_report_count"] or 0),
                        int(aggregate["unique_reporter_count"] or 0),
                        total_reported_amount,
                        int(aggregate["avg_confidence_score"] or 0),
                        risk_score,
                        risk_level,
                        aggregate["first_reported_at"],
                        aggregate["last_reported_at"],
                    ),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.error("[FRAUD TOOL] save_fraud_report_incident error: %s", e, exc_info=True)
        return {"status": "failed", "message": f"Database error: {e}"}

    warning = _account_warning(risk_level)
    return {
        "status": "saved",
        "report_id": report_id,
        "account_risk_level": risk_level,
        "account_warning": warning,
    }


def _validate_payload(payload: dict[str, Any]) -> str | None:
    required = (
        "reporter_cif_no",
        "reported_account_no",
        "reported_bank_code",
        "contact_channel",
        "aftermath",
        "reason_text",
    )
    for field in required:
        if not _clean(payload.get(field)):
            return f"{field} is required."
    if "has_evidence" not in payload or payload.get("has_evidence") is None:
        return "has_evidence is required."
    return None


def _get_verified_transaction(
    *,
    cur,
    transaction_ref: str,
    reporter_cif_no: str,
    reported_account_no: str,
    reported_bank_code: str,
) -> dict | None:
    if not transaction_ref:
        return None

    cur.execute(
        """
        SELECT transaction_ref, amount, transaction_time,
               counterparty_account_no, counterparty_bank_code
        FROM transactions
        WHERE transaction_ref = %s
          AND cif_no = %s
          AND direction = 'OUT'
          AND status = 'SUCCESS'
        LIMIT 1
        """,
        (transaction_ref, reporter_cif_no),
    )
    row = cur.fetchone()
    if not row:
        return None

    if _clean(row["counterparty_account_no"]) != reported_account_no:
        return None
    if _clean(row["counterparty_bank_code"]).upper() != reported_bank_code:
        return None
    return dict(row)


def _load_account_aggregate(cur, account_no: str, bank_code: str) -> dict:
    cur.execute(
        """
        SELECT
            COUNT(*) AS valid_report_count,
            COUNT(DISTINCT reporter_cif_no) AS unique_reporter_count,
            COALESCE(AVG(confidence_score), 0)::int AS avg_confidence_score,
            MIN(created_at) AS first_reported_at,
            MAX(created_at) AS last_reported_at
        FROM fraud_reports
        WHERE reported_account_no = %s
          AND reported_bank_code = %s
          AND status <> 'REJECTED'
        """,
        (account_no, bank_code),
    )
    return dict(cur.fetchone())


def _load_existing_reported_amount(cur, account_no: str, bank_code: str) -> int:
    cur.execute(
        """
        SELECT total_reported_amount
        FROM reported_accounts
        WHERE account_no = %s AND bank_code = %s
        LIMIT 1
        """,
        (account_no, bank_code),
    )
    row = cur.fetchone()
    if not row:
        return 0
    return int(row["total_reported_amount"] or 0)


def _calculate_verified_confidence(
    *,
    transaction_time: Any,
    fraud_type: str,
    aftermath: str,
    has_evidence: bool,
) -> int:
    score = 40
    age_days = _transaction_age_days(transaction_time)
    if age_days is not None and age_days <= 30:
        score += 20
    if fraud_type and fraud_type.upper() != "OTHER":
        score += 15
    if aftermath and aftermath.upper() != "OTHER":
        score += 15
    if has_evidence:
        score += 10
    return min(score, 100)


def _calculate_unverified_confidence(
    *,
    has_evidence: bool,
    existing_report_count: int,
    reason_text: str,
) -> int:
    score = 50
    if has_evidence:
        score += 20
    score += existing_report_count * 10
    if len(reason_text) > 50:
        score += 10
    if len(reason_text) < 20:
        score -= 10
    score -= 20
    return max(30, min(score, 100))


def _calculate_account_risk_level(
    *,
    report_count: int,
    unique_reporters: int,
    avg_confidence: int,
) -> str:
    if report_count >= 5 or avg_confidence >= 80:
        return "CRITICAL"
    if 3 <= report_count <= 4 and unique_reporters >= 3:
        return "HIGH"
    if report_count == 2:
        return "MEDIUM"
    return "LOW"


def _transaction_age_days(value: Any) -> int | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return (datetime.now() - value.replace(tzinfo=None)).days
    try:
        return (datetime.now() - datetime.fromisoformat(str(value))).days
    except ValueError:
        return None


def _account_warning(risk_level: str) -> str | None:
    if risk_level == "CRITICAL":
        return (
            "Tài khoản liên quan đến sự việc này đã bị đánh dấu rủi ro CRITICAL. "
            "Người dùng khác cần được cảnh báo không giao dịch với tài khoản này."
        )
    if risk_level == "HIGH":
        return (
            "Tài khoản liên quan đến sự việc này đã bị đánh dấu rủi ro HIGH. "
            "Người dùng khác cần được cảnh báo mạnh trước khi giao dịch."
        )
    return None


def _as_non_negative_int(value: Any) -> int:
    try:
        normalized = str(value or 0).replace(",", "").replace("_", "").strip()
        return max(0, int(normalized))
    except (TypeError, ValueError):
        return 0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "co", "có"}
    return bool(value)


def _clean(value: Any) -> str:
    return str(value or "").strip()
