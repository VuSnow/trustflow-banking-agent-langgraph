"""Durable task state for task switching inside a chat session."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import uuid4

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL


logger = logging.getLogger(__name__)

ACTIVE_LIFECYCLES = {"active", "suspended"}
TERMINAL_LIFECYCLES = {"completed", "cancelled", "expired"}


class TaskStore:
    """PostgreSQL-backed task lifecycle store."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or DATABASE_URL
        self._ensure_schema()

    def _connect(self):
        return psycopg2.connect(self.dsn)

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    ALTER TABLE chat_sessions
                    ADD COLUMN IF NOT EXISTS active_task_id UUID DEFAULT NULL
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_tasks (
                        task_id UUID PRIMARY KEY,
                        session_id VARCHAR(100) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                        user_id VARCHAR(20) NOT NULL,
                        task_type VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
                        operation VARCHAR(80),
                        lifecycle VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (lifecycle IN ('active', 'suspended', 'completed', 'cancelled', 'expired')),
                        fsm_state VARCHAR(50) NOT NULL DEFAULT 'idle',
                        graph_thread_id VARCHAR(220) NOT NULL UNIQUE,
                        pending_draft JSONB,
                        response_data JSONB,
                        last_user_message TEXT,
                        last_agent_message TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT now(),
                        updated_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversation_tasks_session_lifecycle
                    ON conversation_tasks(session_id, lifecycle, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversation_tasks_user_updated
                    ON conversation_tasks(user_id, updated_at DESC)
                    """
                )
            conn.commit()
            logger.debug("[TASK STORE] schema ensured")
        finally:
            conn.close()

    def _row_to_task(self, row) -> dict | None:
        if not row:
            return None
        task = dict(row)
        task["task_id"] = str(task["task_id"])
        for key in ("pending_draft", "response_data"):
            value = task.get(key)
            if isinstance(value, str):
                task[key] = json.loads(value)
        task["summary"] = summarize_task(task)
        task["resume_hint"] = resume_hint(task)
        return task

    def create_task(
        self,
        *,
        session_id: str,
        user_id: str,
        task_type: str = "UNKNOWN",
        operation: str | None = None,
        last_user_message: str | None = None,
    ) -> dict:
        task_id = str(uuid4())
        graph_thread_id = f"{session_id}:{task_id}"
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_tasks (
                        task_id, session_id, user_id, task_type, operation, lifecycle,
                        fsm_state, graph_thread_id, last_user_message, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'active', 'idle', %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (task_id, session_id, user_id, task_type or "UNKNOWN", operation,
                     graph_thread_id, last_user_message, now, now),
                )
                row = cur.fetchone()
                cur.execute(
                    "UPDATE chat_sessions SET active_task_id = %s, updated_at = %s WHERE session_id = %s",
                    (task_id, now, session_id),
                )
            conn.commit()
            task = self._row_to_task(row)
            logger.debug(
                "[TASK STORE] created task_id=%s session_id=%s user_id=%s task_type=%s operation=%s",
                task.get("task_id") if task else task_id,
                session_id,
                user_id,
                task_type or "UNKNOWN",
                operation,
            )
            return task
        finally:
            conn.close()

    def get_task(self, task_id: str) -> dict | None:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM conversation_tasks WHERE task_id = %s", (task_id,))
                return self._row_to_task(cur.fetchone())
        finally:
            conn.close()

    def get_active_task(self, session_id: str) -> dict | None:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT t.*
                    FROM chat_sessions s
                    JOIN conversation_tasks t ON t.task_id = s.active_task_id
                    WHERE s.session_id = %s AND t.lifecycle = 'active'
                    """,
                    (session_id,),
                )
                return self._row_to_task(cur.fetchone())
        finally:
            conn.close()

    def list_tasks(self, session_id: str, *, lifecycles: tuple[str, ...] | None = None) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if lifecycles:
                    cur.execute(
                        """
                        SELECT * FROM conversation_tasks
                        WHERE session_id = %s AND lifecycle = ANY(%s)
                        ORDER BY updated_at DESC
                        """,
                        (session_id, list(lifecycles)),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM conversation_tasks
                        WHERE session_id = %s
                        ORDER BY updated_at DESC
                        """,
                        (session_id,),
                    )
                return [self._row_to_task(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def list_unfinished_tasks(self, session_id: str, *, exclude_task_id: str | None = None) -> list[dict]:
        tasks = self.list_tasks(session_id, lifecycles=("active", "suspended"))
        return [t for t in tasks if not exclude_task_id or t["task_id"] != exclude_task_id]

    def update_task_state(
        self,
        task_id: str,
        *,
        task_type: str | None = None,
        operation: str | None = None,
        lifecycle: str | None = None,
        fsm_state: str | None = None,
        pending_draft: dict | None = None,
        response_data: dict | None = None,
        last_user_message: str | None = None,
        last_agent_message: str | None = None,
    ) -> dict | None:
        fields = ["updated_at = %s"]
        values: list[object] = [datetime.now()]
        optional = {
            "task_type": task_type,
            "operation": operation,
            "lifecycle": lifecycle,
            "fsm_state": fsm_state,
            "pending_draft": json.dumps(pending_draft, ensure_ascii=False, default=str) if pending_draft is not None else None,
            "response_data": json.dumps(response_data, ensure_ascii=False, default=str) if response_data is not None else None,
            "last_user_message": last_user_message,
            "last_agent_message": last_agent_message,
        }
        for key, value in optional.items():
            if value is not None:
                fields.append(f"{key} = %s")
                values.append(value)
        values.append(task_id)

        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE conversation_tasks SET {', '.join(fields)} WHERE task_id = %s RETURNING *",
                    tuple(values),
                )
                row = cur.fetchone()
            conn.commit()
            task = self._row_to_task(row)
            logger.debug(
                "[TASK STORE] updated task_id=%s lifecycle=%s fsm_state=%s task_type=%s operation=%s fields=%s",
                task_id,
                task.get("lifecycle") if task else lifecycle,
                task.get("fsm_state") if task else fsm_state,
                task.get("task_type") if task else task_type,
                task.get("operation") if task else operation,
                [key for key, value in optional.items() if value is not None],
            )
            return task
        finally:
            conn.close()

    def suspend_task(self, task_id: str) -> dict | None:
        task = self.update_task_state(task_id, lifecycle="suspended")
        logger.debug("[TASK STORE] suspended task_id=%s", task_id)
        return task

    def complete_task(self, task_id: str) -> dict | None:
        task = self.update_task_state(task_id, lifecycle="completed", fsm_state="idle")
        logger.debug("[TASK STORE] completed task_id=%s", task_id)
        return task

    def cancel_task(self, task_id: str) -> dict | None:
        task = self.update_task_state(task_id, lifecycle="cancelled", fsm_state="idle")
        logger.debug("[TASK STORE] cancelled task_id=%s", task_id)
        return task

    def resume_task(self, session_id: str, task_id: str) -> dict | None:
        now = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE conversation_tasks
                    SET lifecycle = 'active', updated_at = %s
                    WHERE task_id = %s AND session_id = %s AND lifecycle = 'suspended'
                    RETURNING *
                    """,
                    (now, task_id, session_id),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE chat_sessions SET active_task_id = %s, updated_at = %s WHERE session_id = %s",
                        (task_id, now, session_id),
                    )
            conn.commit()
            task = self._row_to_task(row)
            logger.debug(
                "[TASK STORE] resumed task_id=%s session_id=%s found=%s",
                task_id,
                session_id,
                bool(task),
            )
            return task
        finally:
            conn.close()

    def set_active_task(self, session_id: str, task_id: str | None) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE chat_sessions SET active_task_id = %s, updated_at = %s WHERE session_id = %s",
                    (task_id, datetime.now(), session_id),
                )
            conn.commit()
            logger.debug("[TASK STORE] set_active session_id=%s task_id=%s", session_id, task_id)
        finally:
            conn.close()


def summarize_task(task: dict) -> str:
    data = task.get("pending_draft") or task.get("response_data") or {}
    task_type = task.get("task_type") or "UNKNOWN"
    operation = task.get("operation") or data.get("operation") or data.get("action") or ""

    if task_type == "TRANSACTION" or operation == "TRANSFER_MONEY":
        amount = _money(data.get("amount"))
        recipient = data.get("recipient_name") or data.get("account_no") or "người nhận chưa rõ"
        return f"Chuyển {amount} cho {recipient}" if amount else f"Chuyển tiền cho {recipient}"
    if operation == "BILL_PAYMENT":
        amount = _money(data.get("amount"))
        biller = data.get("biller_name") or data.get("biller_code") or "hóa đơn"
        return f"Thanh toán {biller} {amount}".strip()
    if operation == "TOP_UP" or task_type == "TOP_UP":
        amount = _money(data.get("amount"))
        target = data.get("topup_target") or "số/ví chưa rõ"
        return f"Nạp {amount} cho {target}" if amount else f"Nạp tiền cho {target}"
    if task_type == "CARD_OPERATION":
        card = data.get("masked_card_no") or data.get("card_id") or "thẻ"
        return f"{operation or 'Thao tác thẻ'} {card}".strip()
    if task_type == "ACCOUNT_OPERATION":
        target = data.get("account_no") or data.get("product_name") or "tài khoản"
        return f"{operation or 'Thao tác tài khoản'} {target}".strip()
    if task_type == "FRAUD_REPORT":
        acct = data.get("reported_account_no") or data.get("account_no") or "tài khoản"
        bank = data.get("reported_bank_code") or data.get("bank_code") or ""
        return f"Báo cáo/kiểm tra lừa đảo {acct} {bank}".strip()
    return task.get("last_user_message") or task_type or "Tác vụ chưa hoàn tất"


def resume_hint(task: dict) -> str:
    task_type = task.get("task_type")
    if task_type == "TRANSACTION":
        return "Nhập số thứ tự hoặc 'tiếp tục chuyển tiền'"
    if task_type == "FRAUD_REPORT":
        return "Nhập số thứ tự hoặc 'tiếp tục báo cáo lừa đảo'"
    return "Nhập số thứ tự để tiếp tục"


def _money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.0f} VND"
    except (TypeError, ValueError):
        return str(value)
