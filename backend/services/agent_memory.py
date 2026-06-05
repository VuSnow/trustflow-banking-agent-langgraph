"""Agent memory service — read/write/expire memory for advisory agents.

Only advisory agents (finance) should write memory.
Execution agents (transaction, bill, fraud) must NOT use cached memory.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


class AgentMemoryStore:
    """PostgreSQL-backed memory store for advisory agents."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self.dsn)

    def get(self, user_id: str, domain: str, memory_key: str, session_id: str | None = None) -> dict | None:
        """Get a memory entry. Returns None if not found or expired."""
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT memory_value, computed_at, expires_at
                    FROM agent_memory
                    WHERE user_id = %s AND domain = %s AND memory_key = %s
                      AND (session_id = %s OR session_id IS NULL)
                      AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    (user_id, domain, memory_key, session_id),
                )
                row = cur.fetchone()
            if row:
                value = row["memory_value"]
                if isinstance(value, str):
                    value = json.loads(value)
                return {
                    "value": value,
                    "computed_at": str(row["computed_at"]),
                    "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
                }
            return None
        finally:
            conn.close()

    def get_domain(self, user_id: str, domain: str, session_id: str | None = None) -> dict:
        """Get all memory entries for a user+domain. Returns dict of key→value."""
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT memory_key, memory_value, computed_at
                    FROM agent_memory
                    WHERE user_id = %s AND domain = %s
                      AND (session_id = %s OR session_id IS NULL)
                      AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY computed_at DESC
                    """,
                    (user_id, domain, session_id),
                )
                rows = cur.fetchall()
            result = {}
            for row in rows:
                key = row["memory_key"]
                if key not in result:  # latest first due to ORDER BY
                    value = row["memory_value"]
                    if isinstance(value, str):
                        value = json.loads(value)
                    result[key] = value
            return result
        finally:
            conn.close()

    def save(
        self,
        user_id: str,
        domain: str,
        memory_key: str,
        memory_value: dict,
        session_id: str | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        """Save or update a memory entry (upsert)."""
        now = datetime.now()
        expires_at = (now + timedelta(hours=ttl_hours)) if ttl_hours else None

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (user_id, session_id, domain, memory_key, memory_value, computed_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, session_id, domain, memory_key)
                    DO UPDATE SET memory_value = EXCLUDED.memory_value,
                                  computed_at = EXCLUDED.computed_at,
                                  expires_at = EXCLUDED.expires_at
                    """,
                    (user_id, session_id, domain, memory_key,
                     json.dumps(memory_value, ensure_ascii=False, default=str),
                     now, expires_at),
                )
            conn.commit()
        finally:
            conn.close()

    def delete(self, user_id: str, domain: str, memory_key: str, session_id: str | None = None) -> None:
        """Delete a specific memory entry."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_memory
                    WHERE user_id = %s AND domain = %s AND memory_key = %s
                      AND (session_id = %s OR (%s IS NULL AND session_id IS NULL))
                    """,
                    (user_id, domain, memory_key, session_id, session_id),
                )
            conn.commit()
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count deleted."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_memory WHERE expires_at < now()")
                count = cur.rowcount
            conn.commit()
            return count
        finally:
            conn.close()
