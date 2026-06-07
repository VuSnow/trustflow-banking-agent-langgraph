"""Finance planning agent for payday-based allocation guidance."""
from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from typing import Any

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)
DEFAULT_CURRENCY = "VND"

_SALARY_PATTERN = r"(luong|lương|salary|payroll|thu\s*nhap|thu\s*nhập|tien\s*luong|tiền\s*lương)"
_COMPANY_PATTERN = r"(cong\s*ty|công\s*ty|cty|company|corp|ltd|inc)"
_ESSENTIAL_TOKENS = (
    "thue",
    "thuê",
    "dien",
    "điện",
    "nuoc",
    "nước",
    "internet",
    "an",
    "ăn",
    "sieu thi",
    "siêu thị",
    "xang",
    "xăng",
    "di chuyen",
    "di chuyển",
    "hoc",
    "học",
    "vien phi",
    "viện phí",
    "bao hiem",
    "bảo hiểm",
    "tra no",
    "trả nợ",
)


def _get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


async def run_finance_planning_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Create a spending allocation plan until next salary date."""
    del session_id  # reserved for future tracing/memory if needed

    try:
        balances = _fetch_balances(user_id)
        if not balances["accounts"]:
            return {
                "status": "info_response",
                "message": "Hiện chưa tìm thấy tài khoản hoạt động để lập kế hoạch chi tiêu.",
                "data": {
                    "task_type": "FINANCE_PLANNING",
                    "handled": True,
                    "currency": DEFAULT_CURRENCY,
                    "total_available_balance": 0,
                },
            }

        total_available = balances["total_available_balance"]

        salary_day = _extract_salary_day(message)
        salary_source = "user"

        if salary_day is None and history:
            for item in reversed(history[-8:]):
                if item.get("role") != "user":
                    continue
                salary_day = _extract_salary_day(item.get("message", ""))
                if salary_day is not None:
                    salary_source = "history"
                    break

        inferred_confidence = 0.0
        inferred_detail: dict[str, Any] | None = None
        if salary_day is None:
            salary_day, inferred_confidence, inferred_detail = _infer_salary_day_from_db(user_id)
            if salary_day is not None:
                salary_source = "inferred"

        if salary_day is None:
            return {
                "status": "info_response",
                "message": (
                    f"Hiện bạn có khoảng {_format_money(total_available)} khả dụng. "
                    "Mình chưa xác định chắc chắn ngày nhận lương từ lịch sử giao dịch gần đây. "
                    "Bạn thường nhận lương vào ngày mấy hằng tháng (1-31) để mình lập kế hoạch đến kỳ lương tiếp theo?"
                ),
                "data": {
                    "task_type": "FINANCE_PLANNING",
                    "handled": True,
                    "currency": DEFAULT_CURRENCY,
                    "needs_salary_day": True,
                    "total_available_balance": total_available,
                },
            }

        next_salary_date, days_remaining = _get_next_salary_date(salary_day)
        spending_snapshot = _fetch_spending_snapshot(user_id)

        daily_budget = max(total_available // days_remaining, 0)
        weekly_budget = daily_budget * 7

        essential_daily_baseline = spending_snapshot["essential_daily_baseline"]
        if essential_daily_baseline > 0:
            essential_budget = min(total_available, int(round(essential_daily_baseline * days_remaining * 1.1)))
        else:
            essential_budget = int(total_available * 0.6)
        flexible_budget = max(total_available - essential_budget, 0)
        daily_flexible_budget = max(flexible_budget // days_remaining, 0)

        message_text = _build_planning_message(
            total_available=total_available,
            salary_day=salary_day,
            salary_source=salary_source,
            inferred_confidence=inferred_confidence,
            next_salary_date=next_salary_date,
            days_remaining=days_remaining,
            daily_budget=daily_budget,
            weekly_budget=weekly_budget,
            essential_budget=essential_budget,
            flexible_budget=flexible_budget,
            daily_flexible_budget=daily_flexible_budget,
            spending_snapshot=spending_snapshot,
        )

        response_data: dict[str, Any] = {
            "task_type": "FINANCE_PLANNING",
            "handled": True,
            "currency": DEFAULT_CURRENCY,
            "salary_day": salary_day,
            "salary_day_source": salary_source,
            "next_salary_date": next_salary_date.isoformat(),
            "days_until_salary": days_remaining,
            "total_available_balance": total_available,
            "daily_budget": daily_budget,
            "weekly_budget": weekly_budget,
            "essential_budget": essential_budget,
            "flexible_budget": flexible_budget,
            "daily_flexible_budget": daily_flexible_budget,
            "top_categories": spending_snapshot["top_categories"],
        }
        if inferred_detail:
            response_data["salary_inference_detail"] = inferred_detail

        return {
            "status": "info_response",
            "message": message_text,
            "data": response_data,
        }

    except Exception as exc:
        logger.error("[FINANCE_PLANNING] Error: %s", exc, exc_info=True)
        return {
            "status": "info_response",
            "message": "Xin lỗi, mình chưa thể lập kế hoạch tài chính lúc này. Bạn vui lòng thử lại sau.",
            "data": {
                "task_type": "FINANCE_PLANNING",
                "error": str(exc),
            },
        }


def _extract_salary_day(text: str) -> int | None:
    if not text:
        return None

    normalized = text.strip().lower()

    patterns = [
        r"(?:ngay|ngày|mung|mùng)\s*(\d{1,2})",
        r"(?:luong|lương).*?(?:ngay|ngày)?\s*(\d{1,2})",
        r"(\d{1,2})\s*(?:hang|hằng|hàng)\s*thang",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            day = int(match.group(1))
            if 1 <= day <= 31:
                return day

    exact_number = re.fullmatch(r"\s*(\d{1,2})\s*", normalized)
    if exact_number:
        day = int(exact_number.group(1))
        if 1 <= day <= 31:
            return day

    return None


def _infer_salary_day_from_db(user_id: str) -> tuple[int | None, float, dict[str, Any] | None]:
    query = """
        WITH income_tx AS (
            SELECT
                transaction_time::date AS tx_date,
                EXTRACT(DAY FROM transaction_time)::int AS salary_day,
                amount,
                LOWER(COALESCE(counterparty_name, '')) AS cp_name,
                LOWER(COALESCE(description, '')) AS tx_desc
            FROM transactions
            WHERE cif_no = %s
              AND direction = 'IN'
              AND status = 'SUCCESS'
              AND transaction_time >= CURRENT_DATE - INTERVAL '180 days'
        ), scored AS (
            SELECT
                salary_day,
                COUNT(*)::int AS tx_count,
                COUNT(DISTINCT date_trunc('month', tx_date))::int AS month_count,
                AVG(amount)::bigint AS avg_amount,
                SUM(
                    CASE
                        WHEN cp_name ~ %s OR tx_desc ~ %s OR cp_name ~ %s OR tx_desc ~ %s THEN 1
                        ELSE 0
                    END
                )::int AS keyword_hits
            FROM income_tx
            GROUP BY salary_day
        )
        SELECT salary_day, tx_count, month_count, avg_amount, keyword_hits
        FROM scored
        ORDER BY keyword_hits DESC, month_count DESC, tx_count DESC, avg_amount DESC
        LIMIT 1
    """

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (user_id, _SALARY_PATTERN, _SALARY_PATTERN, _COMPANY_PATTERN, _COMPANY_PATTERN),
            )
            row = cur.fetchone()

    if not row:
        return None, 0.0, None

    salary_day = int(row.get("salary_day") or 0)
    tx_count = int(row.get("tx_count") or 0)
    month_count = int(row.get("month_count") or 0)
    avg_amount = int(row.get("avg_amount") or 0)
    keyword_hits = int(row.get("keyword_hits") or 0)

    if not (1 <= salary_day <= 31):
        return None, 0.0, None

    confidence = 0.0
    if keyword_hits >= 2 and month_count >= 2:
        confidence = 0.90
    elif keyword_hits >= 1 and month_count >= 2:
        confidence = 0.80
    elif month_count >= 3 and tx_count >= 3 and avg_amount >= 2_000_000:
        confidence = 0.65
    elif month_count >= 4 and tx_count >= 4 and avg_amount >= 1_000_000:
        confidence = 0.55

    if confidence < 0.60:
        return None, confidence, {
            "salary_day": salary_day,
            "tx_count": tx_count,
            "month_count": month_count,
            "avg_amount": avg_amount,
            "keyword_hits": keyword_hits,
            "confidence": confidence,
        }

    return salary_day, confidence, {
        "salary_day": salary_day,
        "tx_count": tx_count,
        "month_count": month_count,
        "avg_amount": avg_amount,
        "keyword_hits": keyword_hits,
        "confidence": confidence,
    }


def _fetch_balances(user_id: str) -> dict[str, Any]:
    query = """
        SELECT
            account_no,
            account_type,
            currency,
            COALESCE(balance, 0)::bigint AS balance,
            COALESCE(available_balance, 0)::bigint AS available_balance
        FROM accounts
        WHERE cif_no = %s
          AND status = 'ACTIVE'
        ORDER BY available_balance DESC
    """

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (user_id,))
            rows = cur.fetchall() or []

    accounts = [
        {
            "account_no": row.get("account_no"),
            "account_type": row.get("account_type"),
            "currency": row.get("currency") or DEFAULT_CURRENCY,
            "balance": int(row.get("balance") or 0),
            "available_balance": int(row.get("available_balance") or 0),
        }
        for row in rows
    ]

    total_balance = sum(item["balance"] for item in accounts)
    total_available = sum(item["available_balance"] for item in accounts)

    return {
        "accounts": accounts,
        "total_balance": total_balance,
        "total_available_balance": total_available,
    }


def _fetch_spending_snapshot(user_id: str) -> dict[str, Any]:
    totals_query = """
        SELECT
            COALESCE(SUM(CASE WHEN transaction_time >= CURRENT_DATE - INTERVAL '30 days' THEN amount ELSE 0 END), 0)::bigint AS total_out_30d,
            COALESCE(SUM(amount), 0)::bigint AS total_out_90d
        FROM transactions
        WHERE cif_no = %s
          AND direction = 'OUT'
          AND status = 'SUCCESS'
          AND transaction_time >= CURRENT_DATE - INTERVAL '90 days'
    """

    categories_query = """
        SELECT
            COALESCE(NULLIF(TRIM(tc.category_name), ''), NULLIF(TRIM(t.description), ''), 'Khác') AS category_name,
            SUM(t.amount)::bigint AS total_spent
        FROM transactions t
        LEFT JOIN transaction_categories tc ON tc.category_id = t.category_id
        WHERE t.cif_no = %s
          AND t.direction = 'OUT'
          AND t.status = 'SUCCESS'
          AND t.transaction_time >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY 1
        ORDER BY total_spent DESC
        LIMIT 6
    """

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(totals_query, (user_id,))
            total_row = cur.fetchone() or {}

            cur.execute(categories_query, (user_id,))
            categories_rows = cur.fetchall() or []

    total_out_30d = int(total_row.get("total_out_30d") or 0)
    total_out_90d = int(total_row.get("total_out_90d") or 0)

    top_categories: list[dict[str, Any]] = []
    essential_total = 0
    for row in categories_rows:
        category_name = str(row.get("category_name") or "Khác")
        total_spent = int(row.get("total_spent") or 0)
        top_categories.append(
            {
                "category_name": category_name,
                "total_spent": total_spent,
                "share": round((total_spent / total_out_90d) * 100, 1) if total_out_90d > 0 else 0.0,
            }
        )

        low = category_name.lower()
        if any(token in low for token in _ESSENTIAL_TOKENS):
            essential_total += total_spent

    essential_daily_baseline = int(round(essential_total / 90)) if essential_total > 0 else 0
    avg_daily_spend_30d = int(round(total_out_30d / 30)) if total_out_30d > 0 else 0

    return {
        "total_out_30d": total_out_30d,
        "total_out_90d": total_out_90d,
        "avg_daily_spend_30d": avg_daily_spend_30d,
        "essential_daily_baseline": essential_daily_baseline,
        "top_categories": top_categories,
    }


def _get_next_salary_date(salary_day: int, today: date | None = None) -> tuple[date, int]:
    today = today or date.today()
    clamped_day = max(1, min(31, salary_day))

    year, month = today.year, today.month
    current_month_day = min(clamped_day, monthrange(year, month)[1])
    candidate = date(year, month, current_month_day)

    if candidate <= today:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        next_month_day = min(clamped_day, monthrange(year, month)[1])
        candidate = date(year, month, next_month_day)

    days_remaining = max((candidate - today).days, 1)
    return candidate, days_remaining


def _build_planning_message(
    *,
    total_available: int,
    salary_day: int,
    salary_source: str,
    inferred_confidence: float,
    next_salary_date: date,
    days_remaining: int,
    daily_budget: int,
    weekly_budget: int,
    essential_budget: int,
    flexible_budget: int,
    daily_flexible_budget: int,
    spending_snapshot: dict[str, Any],
) -> str:
    lines = [
        f"Hiện bạn có khoảng {_format_money(total_available)} khả dụng trong tài khoản.",
    ]

    if salary_source == "inferred":
        lines.append(
            f"Mình suy luận ngày nhận lương là khoảng ngày {salary_day} hằng tháng "
            f"(độ tin cậy {int(inferred_confidence * 100)}%)."
        )
    elif salary_source == "history":
        lines.append(f"Mình dùng ngày lương bạn đã nêu trước đó: ngày {salary_day} hằng tháng.")
    else:
        lines.append(f"Mình dùng ngày lương bạn cung cấp: ngày {salary_day} hằng tháng.")

    lines.extend(
        [
            f"Kỳ lương gần nhất dự kiến vào {next_salary_date.strftime('%d/%m/%Y')} (còn {days_remaining} ngày).",
            "",
            "Gợi ý phân bổ đến ngày nhận lương:",
            f"- Trần chi mỗi ngày: {_format_money(daily_budget)}.",
            f"- Trần chi mỗi tuần: {_format_money(weekly_budget)}.",
            f"- Nhóm chi thiết yếu (ước lượng): {_format_money(essential_budget)} cho cả kỳ.",
            f"- Nhóm chi linh hoạt: {_format_money(flexible_budget)} cho cả kỳ (~{_format_money(daily_flexible_budget)}/ngày).",
        ]
    )

    avg_daily_spend_30d = int(spending_snapshot.get("avg_daily_spend_30d") or 0)
    if avg_daily_spend_30d > 0:
        if avg_daily_spend_30d > daily_budget:
            lines.append(
                f"- 30 ngày gần nhất bạn chi trung bình {_format_money(avg_daily_spend_30d)}/ngày, "
                "cao hơn mức trần hiện tại. Nên giảm các khoản linh hoạt ngay từ tuần đầu."
            )
        else:
            lines.append(
                f"- 30 ngày gần nhất bạn chi trung bình {_format_money(avg_daily_spend_30d)}/ngày, "
                "đang nằm trong ngưỡng an toàn của kế hoạch này."
            )

    top_categories = spending_snapshot.get("top_categories") or []
    if top_categories:
        lines.append("")
        lines.append("3 nhóm chi lớn gần đây:")
        for item in top_categories[:3]:
            lines.append(
                f"- {item['category_name']}: {_format_money(int(item['total_spent']))} "
                f"({item['share']}% chi tiêu 90 ngày)."
            )

    lines.append("")
    lines.append("Khuyến nghị nhanh: ưu tiên giữ quỹ dự phòng, hoãn mua sắm không cấp thiết và rà soát khoản chi top 1 để cắt 10-15% trong kỳ này.")

    return "\n".join(lines)


def _format_money(value: int) -> str:
    return f"{value:,.0f}".replace(",", ".") + f" {DEFAULT_CURRENCY}"
