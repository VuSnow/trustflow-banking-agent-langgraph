"""Card operation tools — LangChain tool wrappers for CardOperationAgent.

Tools:
1. get_user_cards: List all cards belonging to user
2. get_card_detail: Get card detail by card_id or last4 digits
3. lock_card: Lock a card
4. unlock_card: Unlock a card
5. report_lost_card: Mark card as LOST
6. set_card_control: Toggle card controls
7. change_card_limit: Change a card limit
8. get_card_transactions: Get recent card transactions
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from langchain_core.tools import tool

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


@tool
def get_user_cards(user_id: str) -> dict:
    """List all cards belonging to a user. Returns masked card info.

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
                    SELECT card_id, masked_card_no, card_type, card_network,
                           account_no, status, credit_limit, available_limit, issued_at
                    FROM cards WHERE cif_no = %s ORDER BY issued_at DESC
                    """,
                    (user_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    r["card_id"] = str(r["card_id"])
            return {"status": "success", "cards": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD TOOL] get_user_cards error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def get_card_detail(user_id: str, card_id: str = "", last4: str = "", card_type: str = "") -> dict:
    """Get full card detail including controls and limits.

    Args:
        user_id: Customer cif_no.
        card_id: UUID of the card (optional if last4 given).
        last4: Last 4 digits of card number (optional if card_id given).
        card_type: Filter by card type (DEBIT/CREDIT, optional).
    """
    if not user_id:
        return {"status": "failed", "message": "user_id is required."}
    if not card_id and not last4:
        return {"status": "failed", "message": "card_id or last4 is required."}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                conditions = ["c.cif_no = %s"]
                params: list[Any] = [user_id]

                if card_id:
                    conditions.append("c.card_id = %s::uuid")
                    params.append(card_id)
                elif last4:
                    conditions.append("c.masked_card_no LIKE %s")
                    params.append(f"%{last4}")

                if card_type:
                    conditions.append("c.card_type = %s")
                    params.append(card_type.upper())

                where = " AND ".join(conditions)
                cur.execute(
                    f"""
                    SELECT c.card_id, c.masked_card_no, c.card_type, c.card_network,
                           c.account_no, c.status, c.credit_limit, c.available_limit,
                           cc.online_payment_enabled, cc.international_payment_enabled,
                           cc.atm_withdrawal_enabled, cc.pos_payment_enabled, cc.contactless_enabled
                    FROM cards c
                    LEFT JOIN card_controls cc ON c.card_id = cc.card_id
                    WHERE {where}
                    """,
                    params,
                )
                rows = [dict(r) for r in cur.fetchall()]

            if not rows:
                return {"status": "not_found", "message": "Không tìm thấy thẻ phù hợp."}
            if len(rows) == 1:
                card = rows[0]
                card["card_id"] = str(card["card_id"])
                return {"status": "success", "card": card}

            for r in rows:
                r["card_id"] = str(r["card_id"])
            return {"status": "multiple", "message": f"Tìm thấy {len(rows)} thẻ.", "cards": rows}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD TOOL] get_card_detail error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def lock_card(user_id: str, card_id: str) -> dict:
    """Lock (temporarily freeze) a card. Card must be ACTIVE.

    Args:
        user_id: Customer cif_no.
        card_id: UUID of the card to lock.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM cards WHERE card_id = %s::uuid AND cif_no = %s",
                    (card_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return {"status": "not_found", "message": "Thẻ không tồn tại hoặc không thuộc về bạn."}
                if row[0] != "ACTIVE":
                    return {"status": "failed", "message": f"Thẻ đang ở trạng thái {row[0]}, không thể khóa."}

                cur.execute(
                    "UPDATE cards SET status = 'TEMP_LOCKED' WHERE card_id = %s::uuid",
                    (card_id,),
                )
            conn.commit()
            return {"status": "success", "message": "Thẻ đã được khóa tạm thời.", "new_status": "TEMP_LOCKED"}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD TOOL] lock_card error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def unlock_card(user_id: str, card_id: str) -> dict:
    """Unlock a temporarily locked card. Card must be TEMP_LOCKED.

    Args:
        user_id: Customer cif_no.
        card_id: UUID of the card to unlock.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM cards WHERE card_id = %s::uuid AND cif_no = %s",
                    (card_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return {"status": "not_found", "message": "Thẻ không tồn tại hoặc không thuộc về bạn."}
                if row[0] != "TEMP_LOCKED":
                    return {"status": "failed", "message": f"Thẻ đang ở trạng thái {row[0]}, không thể mở khóa."}

                cur.execute(
                    "UPDATE cards SET status = 'ACTIVE' WHERE card_id = %s::uuid",
                    (card_id,),
                )
            conn.commit()
            return {"status": "success", "message": "Thẻ đã được mở khóa.", "new_status": "ACTIVE"}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD TOOL] unlock_card error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


@tool
def report_lost_card(user_id: str, card_id: str) -> dict:
    """Report a card as lost. This is PERMANENT — card cannot be unlocked.

    Args:
        user_id: Customer cif_no.
        card_id: UUID of the card to report lost.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM cards WHERE card_id = %s::uuid AND cif_no = %s",
                    (card_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return {"status": "not_found", "message": "Thẻ không tồn tại."}
                if row[0] in ("LOST", "CANCELLED"):
                    return {"status": "failed", "message": f"Thẻ đã ở trạng thái {row[0]}."}

                cur.execute(
                    "UPDATE cards SET status = 'LOST' WHERE card_id = %s::uuid",
                    (card_id,),
                )
            conn.commit()
            return {"status": "success", "message": "Đã báo mất thẻ. Thẻ đã bị vô hiệu hóa vĩnh viễn.", "new_status": "LOST"}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[CARD TOOL] report_lost_card error: {e}")
        return {"status": "failed", "message": f"Database error: {e}"}


CARD_TOOLS = [get_user_cards, get_card_detail, lock_card, unlock_card, report_lost_card]
