"""PostgreSQL-backed chat session and message history store."""
from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL


class ChatSessionStore:
    """PostgreSQL-backed chat session and message history."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self.dsn)

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def create_session(self, user_id: str, title: str | None = None, session_id: str | None = None) -> dict:
        session_id = session_id or str(uuid4())
        now = self._now()
        title = title or f"Session {session_id[:8]}"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_sessions (session_id, user_id, title, status, created_at, updated_at, last_message_at)
                    VALUES (%s, %s, %s, 'active', %s, %s, %s)
                    """,
                    (session_id, user_id, title, now, now, now),
                )
            conn.commit()
            return self.get_session(session_id)
        finally:
            conn.close()

    def ensure_session(self, user_id: str, session_id: str) -> dict:
        existing = self.get_session(session_id)
        if existing:
            if existing["user_id"] != user_id:
                raise ValueError("session_id does not belong to the supplied user_id")
            return existing
        return self.create_session(user_id=user_id, session_id=session_id)

    def get_session(self, session_id: str) -> dict | None:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT s.session_id, s.user_id, s.title, s.status, s.created_at, s.updated_at,
                           COALESCE(COUNT(m.id), 0) AS message_count,
                           MAX(m.created_at) AS last_message_at
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.session_id
                    WHERE s.session_id = %s
                    GROUP BY s.session_id LIMIT 1
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_sessions(self, user_id: str) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT s.session_id, s.user_id, s.title, s.status, s.created_at, s.updated_at,
                           COALESCE(COUNT(m.id), 0) AS message_count,
                           MAX(m.created_at) AS last_message_at
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.session_id
                    WHERE s.user_id = %s
                    GROUP BY s.session_id
                    ORDER BY COALESCE(MAX(m.created_at), s.updated_at) DESC
                    """,
                    (user_id,),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def add_message(self, *, session_id: str, user_id: str, role: str, message: str, data: dict | None = None) -> None:
        conn = self._connect()
        now = self._now()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (session_id, user_id, role, message, data_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (session_id, user_id, role, message,
                     json.dumps(data, ensure_ascii=False, default=str) if data else None, now),
                )
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = %s, last_message_at = %s WHERE session_id = %s",
                    (now, now, session_id),
                )
            conn.commit()
        finally:
            conn.close()

    def get_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT role, message, data_json as data, created_at
                    FROM chat_messages WHERE session_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
            return rows
        finally:
            conn.close()

    # ─── Transaction state (stored in session metadata) ───────────────────

    def get_transaction_state(self, session_id: str) -> dict | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT transaction_state FROM chat_sessions WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return None
        finally:
            conn.close()

    def set_transaction_state(self, session_id: str, state: dict) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE chat_sessions SET transaction_state = %s WHERE session_id = %s",
                    (json.dumps(state, ensure_ascii=False, default=str), session_id),
                )
            conn.commit()
        finally:
            conn.close()

    def clear_transaction_state(self, session_id: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE chat_sessions SET transaction_state = NULL WHERE session_id = %s",
                    (session_id,),
                )
            conn.commit()
        finally:
            conn.close()
