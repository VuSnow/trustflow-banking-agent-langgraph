"""Transaction Category Classifier — LLM-based prediction with history context.

Predicts category for newly executed transfers using:
1. User's past categorization for the same counterparty (from DB)
2. LLM classification with full context (description, amount, history)
All categories loaded dynamically from transaction_categories table.
"""
from __future__ import annotations

import json
import logging

import psycopg2
import psycopg2.extras
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from backend.config import DATABASE_URL, OPENAI_API_KEY, OPENAI_MODEL
from backend.prompts.category_confirmation import (
    CATEGORY_CLASSIFICATION_SYSTEM_PROMPT,
    CATEGORY_CLASSIFICATION_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


class CategoryClassifier:
    """Predict transaction category using LLM + history context."""

    def get_eligible_categories(self, direction: str = "OUT") -> list[dict]:
        """Load categories from DB, filtered by direction context."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if direction == "OUT":
                        cur.execute(
                            "SELECT category_id, category_code, category_name, category_group "
                            "FROM transaction_categories "
                            "WHERE category_group NOT IN ('INCOME') "
                            "ORDER BY category_group, category_name"
                        )
                    else:
                        cur.execute(
                            "SELECT category_id, category_code, category_name, category_group "
                            "FROM transaction_categories "
                            "ORDER BY category_group, category_name"
                        )
                    return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[CATEGORY] Load categories error: {e}")
            return []

    async def predict(
        self,
        user_id: str,
        description: str = "",
        amount: int = 0,
        counterparty_name: str | None = None,
        counterparty_account_no: str | None = None,
        bank_code: str | None = None,
    ) -> dict:
        """Predict category using LLM with history context.

        Returns:
            {
                "predicted_code": "FAMILY_TRANSFER",
                "predicted_name": "Chuyen khoan gia dinh",
                "predicted_category_id": "...",
                "confidence": 0.85,
                "alternatives": [{"category_id", "code", "name"}, ...]
            }
        """
        eligible = self.get_eligible_categories("OUT")
        if not eligible:
            return self._default_response(eligible)

        # Load history with this counterparty
        history = self._get_counterparty_history(user_id, counterparty_name, counterparty_account_no)

        # Build context for LLM
        categories_list = "\n".join(
            f"- {c['category_code']}: {c['category_name']} ({c['category_group']})"
            for c in eligible
        )

        if history:
            history_context = "\n".join(
                f"- {h['transaction_time']}: {h['description']} | {h['amount']:,} VND | category: {h['category_code']}"
                for h in history
            )
        else:
            history_context = "No previous transactions with this counterparty."

        user_prompt = CATEGORY_CLASSIFICATION_USER_TEMPLATE.format(
            categories_list=categories_list,
            description=description or "(không có)",
            amount=f"{amount:,}" if amount else "0",
            counterparty_name=counterparty_name or "(không rõ)",
            counterparty_account_no=counterparty_account_no or "(không rõ)",
            bank_code=bank_code or "(không rõ)",
            history_context=history_context,
        )

        # Call LLM
        try:
            llm = ChatOpenAI(
                model=OPENAI_MODEL,
                api_key=OPENAI_API_KEY,
                temperature=0.0,
            )
            response = await llm.ainvoke([
                SystemMessage(content=CATEGORY_CLASSIFICATION_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])

            result = json.loads(response.content.strip())
            predicted_code = result.get("predicted_code", "TRANSFER")
            confidence = result.get("confidence", 0.5)
        except Exception as e:
            logger.error(f"[CATEGORY] LLM prediction error: {e}")
            # Fallback: use most recent history category or TRANSFER
            if history:
                predicted_code = history[0]["category_code"]
                confidence = 0.7
            else:
                predicted_code = "TRANSFER"
                confidence = 0.5

        # Resolve predicted category details
        predicted = None
        for cat in eligible:
            if cat["category_code"] == predicted_code:
                predicted = cat
                break

        if not predicted:
            # Fallback to TRANSFER if LLM returned invalid code
            for cat in eligible:
                if cat["category_code"] == "TRANSFER":
                    predicted = cat
                    break
            confidence = 0.5

        # Build alternatives: exclude predicted, limit to 5
        alternatives = [
            {"category_id": c["category_id"], "code": c["category_code"], "name": c["category_name"]}
            for c in eligible
            if c["category_code"] != predicted["category_code"]
        ][:5]

        return {
            "predicted_code": predicted["category_code"],
            "predicted_name": predicted["category_name"],
            "predicted_category_id": predicted["category_id"],
            "confidence": confidence,
            "alternatives": alternatives,
        }

    def _get_counterparty_history(
        self,
        user_id: str,
        counterparty_name: str | None,
        counterparty_account_no: str | None,
    ) -> list[dict]:
        """Get last 5 transactions with this counterparty for context."""
        if not counterparty_name and not counterparty_account_no:
            return []
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if counterparty_account_no:
                        cur.execute(
                            """
                            SELECT t.transaction_time, t.description, t.amount,
                                   tc.category_code, tc.category_name
                            FROM transactions t
                            JOIN transaction_categories tc ON t.category_id = tc.category_id
                            WHERE t.cif_no = %s
                              AND t.counterparty_account_no = %s
                              AND t.direction = 'OUT' AND t.status = 'SUCCESS'
                            ORDER BY t.transaction_time DESC
                            LIMIT 5
                            """,
                            (user_id, counterparty_account_no),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT t.transaction_time, t.description, t.amount,
                                   tc.category_code, tc.category_name
                            FROM transactions t
                            JOIN transaction_categories tc ON t.category_id = tc.category_id
                            WHERE t.cif_no = %s
                              AND t.counterparty_name = %s
                              AND t.direction = 'OUT' AND t.status = 'SUCCESS'
                            ORDER BY t.transaction_time DESC
                            LIMIT 5
                            """,
                            (user_id, counterparty_name),
                        )
                    rows = cur.fetchall()
                    return [
                        {
                            "transaction_time": str(r["transaction_time"])[:16],
                            "description": r["description"] or "",
                            "amount": int(r["amount"]),
                            "category_code": r["category_code"],
                            "category_name": r["category_name"],
                        }
                        for r in rows
                    ]
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[CATEGORY] History lookup error: {e}")
            return []

    def update_category(self, transaction_ref: str, category_id: str) -> bool:
        """Update transaction category in DB after user confirmation."""
        try:
            conn = psycopg2.connect(DATABASE_URL)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE transactions SET category_id = %s WHERE transaction_ref = %s",
                        (category_id, transaction_ref),
                    )
                    conn.commit()
                    return cur.rowcount > 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[CATEGORY] Update error: {e}")
            return False

    def _default_response(self, eligible: list[dict]) -> dict:
        """Return default TRANSFER prediction when something fails."""
        transfer_cat = None
        for c in eligible:
            if c.get("category_code") == "TRANSFER":
                transfer_cat = c
                break
        return {
            "predicted_code": "TRANSFER",
            "predicted_name": transfer_cat["category_name"] if transfer_cat else "Chuyen khoan",
            "predicted_category_id": transfer_cat["category_id"] if transfer_cat else None,
            "confidence": 0.5,
            "alternatives": [],
        }


category_classifier = CategoryClassifier()
