"""Structured audit logging — writes to audit_logs table in PostgreSQL."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

import psycopg2

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


def write_audit_log(
    *,
    cif_no: str,
    event_type: str,
    actor: str = "system",
    event_payload: dict | None = None,
    action_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Write a structured audit event to the audit_logs table."""
    audit_id = str(uuid.uuid4())
    now = datetime.now().isoformat(timespec="seconds")
    payload = event_payload or {}
    if session_id:
        payload["session_id"] = session_id

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_logs (audit_id, action_id, cif_no, event_type, actor, event_payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (audit_id, action_id, cif_no, event_type, actor,
                     json.dumps(payload, ensure_ascii=False, default=str), now),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[AUDIT] Failed to write: {e}")
