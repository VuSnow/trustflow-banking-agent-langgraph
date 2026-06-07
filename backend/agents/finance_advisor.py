"""Finance Advisor Agent — LangGraph implementation with analysis tools and memory."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
import re
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
import psycopg2
import psycopg2.extras

from backend.config import OPENAI_API_KEY, OPENAI_MODEL, DATABASE_URL
from backend.tools.finance_tools import FINANCE_TOOLS
from backend.prompts.finance_advisor import get_finance_advisor_prompt
from backend.services.langfuse_trace import get_trace_config
from backend.services.agent_memory import AgentMemoryStore

logger = logging.getLogger(__name__)
DEFAULT_CURRENCY = "VND"

memory_store = AgentMemoryStore()


def create_finance_agent():
    """Create the finance advisor agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.3,
    )

    agent = create_react_agent(
        model=llm,
        tools=FINANCE_TOOLS,
        prompt=SystemMessage(content=get_finance_advisor_prompt()),
    )
    return agent


async def run_finance_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the finance advisor agent with memory context injection."""
    agent = create_finance_agent()

    # Load previous finance memory for context
    finance_memory = memory_store.get_domain(user_id, "finance", session_id=session_id)

    messages = []

    # Inject memory context if available
    if finance_memory:
        memory_text = "Previous finance context (use to avoid re-querying):\n"
        for key, value in finance_memory.items():
            memory_text += f"- {key}: {json.dumps(value, ensure_ascii=False, default=str)}\n"
        messages.append(SystemMessage(content=memory_text))

    if history:
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("message", "")
            if role == "user" and content:
                messages.append(HumanMessage(content=content))
            elif role == "assistant" and content:
                messages.append(AIMessage(content=content))

    user_msg = f"[User cif_no: {user_id}]\n\n{message}"
    messages.append(HumanMessage(content=user_msg))

    try:
        config = get_trace_config(
            session_id=session_id,
            user_id=user_id,
            trace_name="finance_advisor",
        )
        config.setdefault("recursion_limit", 20)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = "Xin lỗi, không thể phân tích tài chính lúc này."

        if _needs_response_repair(message, raw_content):
            raw_content = await _repair_incomplete_response(
                question=message,
                draft_response=raw_content,
                result=result,
            )

        visualizations = _build_finance_visualizations(
            question=message,
            user_id=user_id,
            result=result,
            currency=DEFAULT_CURRENCY,
        )

        # Keep narrative summary aligned with the exact same dataset used for charts.
        summary_from_dataset = _build_summary_from_visualizations(
            question=message,
            visualizations=visualizations,
            currency=DEFAULT_CURRENCY,
        )
        if summary_from_dataset:
            raw_content = summary_from_dataset

        response_data = {
            "task_type": "FINANCE_ADVICE",
            "handled": True,
            "currency": DEFAULT_CURRENCY,
        }
        if visualizations:
            response_data["visualizations"] = visualizations

        # Save key insights to memory for follow-up questions
        _save_memory_from_response(user_id, session_id, message, raw_content, result)

        return {
            "status": "info_response",
            "message": raw_content,
            "data": response_data,
        }

    except Exception as e:
        logger.error(f"[FINANCE AGENT] Error: {e}", exc_info=True)
        return {
            "status": "info_response",
            "message": "Xin lỗi, tôi không thể phân tích chi tiêu lúc này. Vui lòng thử lại.",
            "data": {"error": str(e)},
        }


def _build_finance_visualizations(
    *, question: str, user_id: str, result: dict[str, Any], currency: str
) -> list[dict[str, Any]]:
    """Build chart specs for frontend rendering.

    Phase 1: Infer chart specs from tool outputs.
    Phase 2: Intent-aware deterministic SQL fallback for stable chart coverage.
    """
    charts: list[dict[str, Any]] = []

    # Phase 2 (deterministic, intent-aware) first for predictable chart quality.
    try:
        charts.extend(_build_intent_visualizations(question=question, user_id=user_id, currency=currency))
    except Exception as e:
        logger.warning(f"[FINANCE] Failed to build intent visualizations: {e}")

    # Phase 1 fallback from tool payloads if deterministic layer returned nothing.
    if not charts:
        try:
            charts.extend(_build_tool_based_visualizations(result=result, currency=currency))
        except Exception as e:
            logger.warning(f"[FINANCE] Failed to build tool-based visualizations: {e}")

    # Deduplicate by (type, title) and cap for UI readability.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chart in charts:
        chart_type = str(chart.get("type") or "")
        title = str(chart.get("title") or "")
        signature = (chart_type, title)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(chart)

    return unique[:2]


def _build_summary_from_visualizations(
    *, question: str, visualizations: list[dict[str, Any]], currency: str
) -> str:
    """Build deterministic summary text from chart datasets.

    This guarantees text and chart consistency.
    """
    if not visualizations:
        return ""

    comparison_chart = next(
        (c for c in visualizations if isinstance(c, dict) and c.get("type") == "bar-grouped"),
        None,
    )
    if comparison_chart:
        return _summary_from_comparison_chart(comparison_chart, currency)

    line_chart = next(
        (c for c in visualizations if isinstance(c, dict) and c.get("type") == "line"),
        None,
    )
    top_category_chart = next(
        (
            c
            for c in visualizations
            if isinstance(c, dict)
            and (c.get("id") == "top-spending-categories" or c.get("type") == "bar")
        ),
        None,
    )
    return _summary_from_overview_charts(line_chart, top_category_chart, currency)


def _summary_from_comparison_chart(chart: dict[str, Any], currency: str) -> str:
    labels = [str(x) for x in (chart.get("labels") or [])]
    series = chart.get("series") or []
    if len(series) < 2:
        return ""

    first_name = str(series[0].get("name") or "Kỳ 1")
    second_name = str(series[1].get("name") or "Kỳ 2")
    first_vals = [int(v or 0) for v in (series[0].get("values") or [])]
    second_vals = [int(v or 0) for v in (series[1].get("values") or [])]

    total_first = sum(first_vals)
    total_second = sum(second_vals)
    delta_total = total_second - total_first

    rows: list[tuple[str, int, int, int]] = []
    for i, label in enumerate(labels):
        first_val = first_vals[i] if i < len(first_vals) else 0
        second_val = second_vals[i] if i < len(second_vals) else 0
        rows.append((label, second_val - first_val, first_val, second_val))

    top_increase = max(rows, key=lambda x: x[1], default=None) if rows else None
    top_decrease = min(rows, key=lambda x: x[1], default=None) if rows else None

    non_essential_tokens = ("giải", "mua", "ăn", "di chuyển", "entertain")
    cut_candidate = None
    for label, _, _, second_val in sorted(rows, key=lambda x: x[3], reverse=True):
        low = label.lower()
        if any(token in low for token in non_essential_tokens):
            cut_candidate = (label, second_val)
            break

    lines = [
        f"So sánh chi tiêu giữa {first_name} và {second_name} (cùng dataset với biểu đồ):",
        "",
        f"- Tổng chi tiêu {first_name}: {_format_money(total_first, currency)}",
        f"- Tổng chi tiêu {second_name}: {_format_money(total_second, currency)}",
        f"- Chênh lệch ({second_name} - {first_name}): {_format_signed_money(delta_total, currency)}",
        "",
    ]

    if total_first == 0 or total_second == 0:
        missing_period = first_name if total_first == 0 else second_name
        lines.append(f"- Lưu ý: {missing_period} chưa có dữ liệu chi tiêu trong dataset hiện tại.")

    if top_increase and top_increase[1] > 0:
        lines.append(
            f"- Khoản tăng mạnh nhất: {top_increase[0]} ({_format_signed_money(top_increase[1], currency)})."
        )
    elif top_increase:
        lines.append("- Không có danh mục tăng rõ rệt trong kỳ so sánh này.")

    if top_decrease and top_decrease[1] < 0:
        lines.append(
            f"- Khoản giảm mạnh nhất: {top_decrease[0]} ({_format_signed_money(top_decrease[1], currency)})."
        )

    if cut_candidate and cut_candidate[1] > 0:
        lines.append(
            f"- Gợi ý cắt giảm trước: {cut_candidate[0]} (~{_format_money(cut_candidate[1], currency)} ở {second_name})."
        )

    lines.append("")
    lines.append("Đây chỉ là tham khảo, không phải tư vấn tài chính chuyên nghiệp.")
    return "\n".join(lines)


def _summary_from_overview_charts(
    line_chart: dict[str, Any] | None,
    bar_chart: dict[str, Any] | None,
    currency: str,
) -> str:
    lines: list[str] = []

    income_total = 0
    expense_total = 0

    if line_chart and isinstance(line_chart, dict):
        labels = [str(x) for x in (line_chart.get("labels") or [])]
        series = line_chart.get("series") or []
        income_series = _find_series(series, ("thu", "income"))
        expense_series = _find_series(series, ("chi", "expense", "spend"))

        if income_series:
            income_total = sum(int(v or 0) for v in (income_series.get("values") or []))
        if expense_series:
            expense_total = sum(int(v or 0) for v in (expense_series.get("values") or []))

        if income_series or expense_series:
            lines.extend(
                [
                    "Tổng quan thu chi (cùng dataset với biểu đồ):",
                    "",
                    f"- Tổng thu nhập: {_format_money(income_total, currency)}",
                    f"- Tổng chi tiêu: {_format_money(expense_total, currency)}",
                    f"- Chênh lệch ròng: {_format_signed_money(income_total - expense_total, currency)}",
                ]
            )

            if expense_series and len(expense_series.get("values") or []) >= 2 and labels:
                vals = [int(v or 0) for v in (expense_series.get("values") or [])]
                last = vals[-1]
                prev = vals[-2]
                diff = last - prev
                last_label = labels[-1] if len(labels) >= 1 else "kỳ gần nhất"
                prev_label = labels[-2] if len(labels) >= 2 else "kỳ trước"
                lines.append(
                    f"- Xu hướng chi tiêu gần nhất ({last_label} so với {prev_label}): {_format_signed_money(diff, currency)}."
                )

            lines.append("")

    if bar_chart and isinstance(bar_chart, dict):
        labels = [str(x) for x in (bar_chart.get("labels") or [])]
        series = bar_chart.get("series") or []
        values = []
        if series:
            values = [int(v or 0) for v in (series[0].get("values") or [])]

        if labels and values:
            lines.append("Top danh mục chi tiêu:")
            for idx, (label, value) in enumerate(zip(labels[:5], values[:5]), start=1):
                lines.append(f"{idx}. {label}: {_format_money(value, currency)}")
            lines.append("")

    if not lines:
        return ""

    lines.append("Đây chỉ là tham khảo, không phải tư vấn tài chính chuyên nghiệp.")
    return "\n".join(lines)


def _find_series(series_list: list[Any], name_tokens: tuple[str, ...]) -> dict[str, Any] | None:
    for item in series_list or []:
        name = str(item.get("name") or "").lower()
        if any(token in name for token in name_tokens):
            return item
    return series_list[0] if series_list else None


def _format_money(value: int | float, currency: str) -> str:
    amount = int(round(float(value or 0)))
    if currency == "VND":
        return f"{amount:,.0f}".replace(",", ".") + " VND"
    return f"{amount:,.0f}".replace(",", ".")


def _format_signed_money(value: int | float, currency: str) -> str:
    amount = int(round(float(value or 0)))
    sign = "+" if amount > 0 else ""
    return f"{sign}{_format_money(amount, currency)}"


def _build_intent_visualizations(*, question: str, user_id: str, currency: str) -> list[dict[str, Any]]:
    """Generate chart specs from deterministic SQL per question intent."""
    q = (question or "").lower()
    charts: list[dict[str, Any]] = []
    lookback_months = _resolve_lookback_months(question, default_months=6)
    lookback_days = max(30, lookback_months * 30)

    is_comparison = "so sánh" in q and "tháng" in q
    asks_spending_overview = any(
        token in q for token in ("thu chi", "3 tháng", "danh mục", "tổng thu", "tổng chi")
    )
    asks_recurring = any(token in q for token in ("lặp lại", "định kỳ", "subscription", "recurring"))

    if is_comparison:
        first_month, second_month = _resolve_comparison_months(question)
        rows = _query_monthly_category_comparison(
            user_id=user_id,
            first_month_start=first_month,
            second_month_start=second_month,
            limit=8,
        )
        if rows:
            first_label = first_month.strftime("%m/%Y")
            second_label = second_month.strftime("%m/%Y")
            labels = [str(r.get("category_name") or "Khác") for r in rows]
            first_vals = [int(r.get("first_month_amount") or 0) for r in rows]
            second_vals = [int(r.get("second_month_amount") or 0) for r in rows]
            charts.append(
                {
                    "id": "month-comparison-categories",
                    "type": "bar-grouped",
                    "title": "So sánh chi tiêu theo danh mục",
                    "subtitle": f"{first_label} so với {second_label}",
                    "currency": currency,
                    "labels": labels,
                    "series": [
                        {"name": first_label, "values": first_vals},
                        {"name": second_label, "values": second_vals},
                    ],
                }
            )

    if asks_spending_overview and not is_comparison:
        cashflow_rows = _query_monthly_cashflow(user_id=user_id, months=lookback_months)
        if cashflow_rows:
            labels = [str(r.get("month")) for r in cashflow_rows]
            income_vals = [int(r.get("income") or 0) for r in cashflow_rows]
            expense_vals = [int(r.get("expense") or 0) for r in cashflow_rows]
            if any(v > 0 for v in income_vals + expense_vals):
                charts.append(
                    {
                        "id": "cashflow-trend",
                        "type": "line",
                        "title": "Xu hướng thu chi theo tháng",
                        "subtitle": f"{lookback_months} tháng gần nhất",
                        "currency": currency,
                        "labels": labels,
                        "series": [
                            {"name": "Thu nhập", "values": income_vals},
                            {"name": "Chi tiêu", "values": expense_vals},
                        ],
                    }
                )

        top_category_rows = _query_top_spending_categories(
            user_id=user_id,
            lookback_days=lookback_days,
            limit=8,
        )
        if top_category_rows:
            labels = [str(r.get("category_name") or "Khác") for r in top_category_rows]
            values = [int(r.get("total_spent") or 0) for r in top_category_rows]
            if any(v > 0 for v in values):
                charts.append(
                    {
                        "id": "top-spending-categories",
                        "type": "bar",
                        "title": "Top danh mục chi tiêu",
                        "subtitle": f"{lookback_days} ngày gần nhất",
                        "currency": currency,
                        "labels": labels,
                        "series": [{"name": "Chi tiêu", "values": values}],
                    }
                )

    if asks_recurring:
        recurring_rows = _query_recurring(user_id=user_id, lookback_days=120, limit=8)
        if recurring_rows:
            labels = [str(r.get("counterparty_name") or "N/A") for r in recurring_rows]
            freq = [int(r.get("frequency") or 0) for r in recurring_rows]
            charts.append(
                {
                    "id": "recurring-payments",
                    "type": "bar",
                    "title": "Khoản chi lặp lại",
                    "subtitle": "Theo số lần giao dịch",
                    "unit": "count",
                    "labels": labels,
                    "series": [{"name": "Số lần", "values": freq}],
                }
            )

    return charts


def _resolve_comparison_months(question: str) -> tuple[datetime, datetime]:
    """Resolve two months for comparison from Vietnamese question text.

    Examples:
    - "so sánh tháng 4 với tháng 5" -> 04/current_year and 05/current_year
    - "so sánh tháng 12 năm 2025 với tháng 1 năm 2026" -> exact pair
    - fallback -> current month vs previous month
    """
    q = (question or "").lower()
    matches = re.findall(r"tháng\s*(\d{1,2})(?:\s*năm\s*(\d{4}))?", q)

    resolved: list[datetime] = []
    current_year = datetime.now().year
    for month_text, year_text in matches:
        month = int(month_text)
        if month < 1 or month > 12:
            continue
        year = int(year_text) if year_text else current_year
        resolved.append(datetime(year=year, month=month, day=1))

    if len(resolved) >= 2:
        return resolved[0], resolved[1]

    now = datetime.now().replace(day=1)
    prev = (now - timedelta(days=1)).replace(day=1)
    return now, prev


def _resolve_lookback_months(question: str, default_months: int = 6) -> int:
    """Resolve lookback window in months from Vietnamese question text."""
    q = (question or "").lower()
    match = re.search(r"(\d{1,2})\s*tháng", q)
    if match:
        months = int(match.group(1))
        return max(1, min(months, 12))

    if "quý" in q:
        return 3
    if "năm" in q:
        return 12
    return max(1, min(default_months, 12))


def _build_tool_based_visualizations(*, result: dict[str, Any], currency: str) -> list[dict[str, Any]]:
    """Infer chart specs from text2sql/tool payloads when deterministic layer is unavailable."""
    charts: list[dict[str, Any]] = []
    tool_payloads = _extract_tool_payloads(result)

    for payload in tool_payloads:
        content = payload.get("content")
        if not isinstance(content, dict):
            continue
        rows = content.get("rows")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue

        keys = {str(k).lower() for k in rows[0].keys()}

        if "month" in keys and ("income" in keys or "expense" in keys):
            labels = [str(r.get("month")) for r in rows]
            income_vals = [int(r.get("income") or 0) for r in rows]
            expense_vals = [int(r.get("expense") or 0) for r in rows]
            charts.append(
                {
                    "id": "tool-cashflow-trend",
                    "type": "line",
                    "title": "Xu hướng thu chi",
                    "currency": currency,
                    "labels": labels,
                    "series": [
                        {"name": "Thu nhập", "values": income_vals},
                        {"name": "Chi tiêu", "values": expense_vals},
                    ],
                }
            )
            continue

        category_key = "category_name" if "category_name" in keys else None
        amount_key = next((k for k in ("total_spent", "total_amount", "amount") if k in keys), None)
        if category_key and amount_key:
            labels = [str(r.get(category_key) or "Khác") for r in rows[:8]]
            values = [int(r.get(amount_key) or 0) for r in rows[:8]]
            charts.append(
                {
                    "id": "tool-category-breakdown",
                    "type": "bar",
                    "title": "Phân bổ chi tiêu theo danh mục",
                    "currency": currency,
                    "labels": labels,
                    "series": [{"name": "Chi tiêu", "values": values}],
                }
            )

    return charts


def _query_monthly_cashflow(*, user_id: str, months: int = 6) -> list[dict[str, Any]]:
    query = """
        SELECT
            to_char(date_trunc('month', transaction_time), 'YYYY-MM') AS month,
            COALESCE(SUM(amount) FILTER (WHERE direction = 'IN' AND status = 'SUCCESS'), 0) AS income,
            COALESCE(SUM(amount) FILTER (WHERE direction = 'OUT' AND status = 'SUCCESS'), 0) AS expense
        FROM transactions
        WHERE cif_no = %s
          AND transaction_time >= date_trunc('month', CURRENT_DATE) - (%s::int - 1) * interval '1 month'
        GROUP BY 1
        ORDER BY 1
    """
    return _run_select(query, (user_id, months))


def _query_top_spending_categories(*, user_id: str, lookback_days: int = 90, limit: int = 8) -> list[dict[str, Any]]:
    query = """
        SELECT
            COALESCE(tc.category_name, '(không phân loại)') AS category_name,
            COALESCE(SUM(t.amount), 0) AS total_spent
        FROM transactions t
        LEFT JOIN transaction_categories tc ON tc.category_id = t.category_id
        WHERE t.cif_no = %s
          AND t.direction = 'OUT'
          AND t.status = 'SUCCESS'
          AND t.transaction_time >= CURRENT_DATE - %s * interval '1 day'
        GROUP BY 1
        ORDER BY total_spent DESC
        LIMIT %s
    """
    return _run_select(query, (user_id, lookback_days, limit))


def _query_monthly_category_comparison(
    *,
    user_id: str,
    first_month_start: datetime,
    second_month_start: datetime,
    limit: int = 8,
) -> list[dict[str, Any]]:
    query = """
        WITH monthly AS (
            SELECT
                date_trunc('month', t.transaction_time)::date AS month_start,
                COALESCE(tc.category_name, '(không phân loại)') AS category_name,
                SUM(t.amount) AS total_amount
            FROM transactions t
            LEFT JOIN transaction_categories tc ON tc.category_id = t.category_id
            WHERE t.cif_no = %s
              AND t.direction = 'OUT'
              AND t.status = 'SUCCESS'
              AND date_trunc('month', t.transaction_time) IN (
                  %s::date,
                  %s::date
              )
            GROUP BY 1, 2
        ),
        pivoted AS (
            SELECT
                category_name,
                SUM(CASE WHEN month_start = %s::date THEN total_amount ELSE 0 END) AS first_month_amount,
                SUM(CASE WHEN month_start = %s::date THEN total_amount ELSE 0 END) AS second_month_amount
            FROM monthly
            GROUP BY category_name
        )
        SELECT
            category_name,
            COALESCE(first_month_amount, 0) AS first_month_amount,
            COALESCE(second_month_amount, 0) AS second_month_amount,
            COALESCE(first_month_amount, 0) - COALESCE(second_month_amount, 0) AS delta_amount
        FROM pivoted
        ORDER BY GREATEST(COALESCE(first_month_amount, 0), COALESCE(second_month_amount, 0)) DESC
        LIMIT %s
    """
    first_date = first_month_start.date().isoformat()
    second_date = second_month_start.date().isoformat()
    return _run_select(query, (user_id, first_date, second_date, first_date, second_date, limit))


def _query_recurring(*, user_id: str, lookback_days: int = 120, limit: int = 8) -> list[dict[str, Any]]:
    query = """
        SELECT
            counterparty_name,
            COUNT(*) AS frequency,
            COALESCE(SUM(amount), 0) AS total_spent
        FROM transactions
        WHERE cif_no = %s
          AND direction = 'OUT'
          AND status = 'SUCCESS'
          AND counterparty_name IS NOT NULL
          AND transaction_time >= CURRENT_DATE - %s * interval '1 day'
        GROUP BY counterparty_name
        HAVING COUNT(*) >= 2
        ORDER BY frequency DESC, total_spent DESC
        LIMIT %s
    """
    return _run_select(query, (user_id, lookback_days, limit))


def _run_select(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute a read-only SQL query for visualization data."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.warning(f"[FINANCE] Visualization query failed: {e}")
        return []
    finally:
        conn.close()


def _needs_response_repair(question: str, response: str) -> bool:
    """Detect incomplete/dangling finance answers that should be rewritten."""
    q = (question or "").lower()
    r = (response or "").lower()

    dangling_markers = [
        "tôi sẽ tiếp tục truy vấn",
        "sẽ tiếp tục truy vấn",
        "tôi sẽ cần",
        "cần thêm dữ liệu",
        "đang truy vấn",
        "đợi tôi",
    ]
    if any(marker in r for marker in dangling_markers):
        return True

    # Comparison questions should include a concrete increase/decrease conclusion.
    if "so sánh" in q:
        has_comparison_outcome = any(
            token in r for token in ("tăng", "giảm", "cao hơn", "thấp hơn", "chênh lệch")
        )
        if not has_comparison_outcome:
            return True

    return False


def _extract_tool_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract compact tool payloads from LangGraph messages for response repair."""
    payloads: list[dict[str, Any]] = []
    for msg in result.get("messages", []):
        if not (hasattr(msg, "type") and msg.type == "tool"):
            continue

        content = msg.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                content = {"raw": content[:1000]}

        payloads.append(
            {
                "tool": msg.name if hasattr(msg, "name") else "unknown",
                "content": _compact_tool_result(content) if isinstance(content, dict) else content,
            }
        )

    return payloads[:8]


async def _repair_incomplete_response(
    *, question: str, draft_response: str, result: dict[str, Any]
) -> str:
    """Rewrite unfinished responses into a complete final advisory answer."""
    try:
        tool_payloads = _extract_tool_payloads(result)
        tool_payloads_text = json.dumps(tool_payloads, ensure_ascii=False, default=str)
        if len(tool_payloads_text) > 12000:
            tool_payloads_text = tool_payloads_text[:12000] + " ...<truncated>"

        reviewer = ChatOpenAI(
            model=OPENAI_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=0.1,
        )

        review_prompt = [
            SystemMessage(
                content=(
                    "Bạn là lớp kiểm định chất lượng phản hồi tài chính. "
                    "Hãy tạo câu trả lời CUỐI CÙNG hoàn chỉnh cho người dùng từ dữ liệu tool."
                    "\nQuy tắc bắt buộc:"
                    "\n- Trả lời tiếng Việt."
                    "\n- Không lặp cùng một block số liệu."
                    "\n- Không để câu dang dở như 'tôi sẽ tiếp tục truy vấn'."
                    "\n- Nếu là câu hỏi so sánh, phải nêu rõ khoản tăng/giảm và kết luận ngắn."
                    "\n- Nếu dữ liệu thiếu, nêu thiếu gì và đưa kết luận tạm thời rõ ràng."
                    "\n- Kết thúc với câu: 'Đây chỉ là tham khảo, không phải tư vấn tài chính chuyên nghiệp.'"
                )
            ),
            HumanMessage(
                content=(
                    f"Câu hỏi người dùng:\n{question}\n\n"
                    f"Bản nháp hiện tại:\n{draft_response}\n\n"
                    f"Kết quả tool:\n{tool_payloads_text}"
                )
            ),
        ]
        fixed = await reviewer.ainvoke(review_prompt)
        fixed_content = fixed.content if hasattr(fixed, "content") else str(fixed)
        fixed_content = (fixed_content or "").strip()
        return fixed_content or draft_response
    except Exception as e:
        logger.warning(f"[FINANCE] Failed to repair incomplete response: {e}")
        return draft_response


def _save_memory_from_response(
    user_id: str, session_id: str, question: str, response: str, result: dict
) -> None:
    """Extract and save useful context from agent response to memory.

    Saves a compact summary — not the full response text.
    """
    try:
        # Extract tool results from messages for memory
        tool_summaries = []
        for msg in result.get("messages", []):
            if hasattr(msg, "type") and msg.type == "tool":
                content = msg.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if isinstance(content, dict) and content.get("status") == "success":
                    tool_summaries.append({
                        "tool": msg.name if hasattr(msg, "name") else "unknown",
                        "result_summary": _compact_tool_result(content),
                    })

        if tool_summaries:
            memory_store.save(
                user_id=user_id,
                domain="finance",
                memory_key="last_analysis",
                memory_value={
                    "question": question[:200],
                    "tool_results": tool_summaries[:5],  # cap at 5
                },
                session_id=session_id,
                ttl_hours=2,  # expire after 2 hours
            )
    except Exception as e:
        logger.warning(f"[FINANCE] Failed to save memory: {e}")


def _compact_tool_result(result: dict) -> dict:
    """Compact a tool result to save space in memory. Keep only key metrics."""
    compact = {}
    # Keep scalar values and small lists
    for key, value in result.items():
        if key in ("status", "sql"):
            continue
        if isinstance(value, (int, float, str, bool)):
            compact[key] = value
        elif isinstance(value, list) and len(value) <= 10:
            compact[key] = value
        elif isinstance(value, dict):
            compact[key] = value
    return compact
