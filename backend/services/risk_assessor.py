"""Transaction risk assessment — calculates composite risk score.

Signals:
1. Reported account (from reported_accounts table)
2. Reported customer (from reported_customers table)
3. Unusual amount (> 5x user's average outgoing)
4. First-time recipient (never transacted before)
5. Unusual hour (0h-5h)

Returns a score 0.0–1.0 and risk level for UI display.
"""
from __future__ import annotations

from html import escape
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


def assess_transaction_risk(
    *,
    user_id: str,
    recipient_account_no: str,
    recipient_bank_code: str | None = None,
    amount: int | None = None,
    fraud_screening: dict | None = None,
) -> dict:
    """Calculate composite risk score for a transaction.

    Args:
        user_id: Sender's cif_no.
        recipient_account_no: Recipient account number.
        recipient_bank_code: Recipient bank code (optional).
        amount: Transaction amount in VND.
        fraud_screening: Pre-computed fraud screening result (from check_fraud_risk).

    Returns:
        {
            "score": 0.0–1.0,
            "level": "SAFE" | "MEDIUM" | "HIGH",
            "signals": ["signal_description", ...],
        }
    """
    score = 0.0
    signals: list[str] = []

    # Signal 1: Reported account (from pre-computed fraud screening)
    if fraud_screening and fraud_screening.get("is_reported"):
        risk_level = fraud_screening.get("risk_level", "LOW")
        report_count = fraud_screening.get("report_count", 0)
        if risk_level == "CRITICAL":
            score += 0.6
            signals.append(f"Tài khoản nhận bị xác nhận lừa đảo ({report_count} báo cáo)")
        elif risk_level == "HIGH":
            score += 0.45
            signals.append(f"Tài khoản nhận có {report_count} báo cáo nghi ngờ gian lận")
        elif risk_level in ("MEDIUM", "WATCH"):
            score += 0.2
            signals.append(f"Tài khoản nhận đang được theo dõi ({report_count} báo cáo)")

    try:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                # Signal 2: Reported customer linked to this account
                if recipient_bank_code and recipient_bank_code.upper() == "SHB":
                    cur.execute(
                        """
                        SELECT rc.risk_score, rc.risk_level
                        FROM reported_customers rc
                        JOIN accounts a ON a.cif_no = rc.cif_no
                        WHERE a.account_no = %s AND rc.status = 'ACTIVE'
                        LIMIT 1
                        """,
                        (recipient_account_no,),
                    )
                    row = cur.fetchone()
                    if row:
                        cust_risk = float(row[0]) if row[0] else 0
                        score += min(cust_risk * 0.3, 0.3)
                        signals.append(f"Chủ tài khoản nhận có mức rủi ro {row[1]}")

                # Signal 3: Unusual amount (> 5x average)
                if amount and amount > 0:
                    cur.execute(
                        """
                        SELECT AVG(amount) FROM transactions
                        WHERE cif_no = %s AND direction = 'OUT' AND status = 'SUCCESS'
                          AND transaction_time >= NOW() - INTERVAL '90 days'
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                    avg_amount = float(row[0]) if row and row[0] else 0
                    if avg_amount > 0 and amount > avg_amount * 5:
                        ratio = min(amount / avg_amount / 10, 1.0)  # cap at 1.0
                        score += ratio * 0.15
                        signals.append(
                            f"Số tiền cao bất thường (gấp {amount / avg_amount:.1f}x trung bình)"
                        )

                # Signal 4: First-time recipient
                cur.execute(
                    """
                    SELECT COUNT(*) FROM transactions
                    WHERE cif_no = %s AND direction = 'OUT' AND status = 'SUCCESS'
                      AND counterparty_account_no = %s
                    """,
                    (user_id, recipient_account_no),
                )
                row = cur.fetchone()
                if row and row[0] == 0:
                    score += 0.08
                    signals.append("Người nhận chưa từng giao dịch trước đây")

        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[RISK_ASSESSOR] DB error: {e}")

    # Signal 5: Unusual hour (0h-5h)
    current_hour = datetime.now().hour
    if 0 <= current_hour < 5:
        score += 0.07
        signals.append("Giao dịch vào khung giờ bất thường (0h-5h)")

    # Cap and classify
    score = min(score, 1.0)
    score = round(score, 2)

    if score >= 0.6:
        level = "HIGH"
    elif score >= 0.3:
        level = "MEDIUM"
    else:
        level = "SAFE"

    return {
        "score": score,
        "level": level,
        "signals": signals,
    }


def format_risk_gauge(risk_result: dict) -> str:
    """Format risk assessment as a smooth visual risk gauge.

    Only returns content if level is MEDIUM or HIGH (score >= 0.3).
    Returns empty string for SAFE transactions.
    """
    score = risk_result["score"]
    level = risk_result["level"]
    signals = risk_result["signals"]

    if level == "SAFE":
        return ""

    score_pct = int(round(score * 100))

    if level == "HIGH":
        label = "RỦI RO CAO"
        level_class = "high"
        level_message = "cao"
    else:
        label = "RỦI RO TRUNG BÌNH"
        level_class = "medium"
        level_message = "trung bình"

    # Keep thumb inside track so the handle stays visible at 0% and 100%.
    clamped_pct = max(2, min(score_pct, 98))

    signal_html = ""
    if signals:
        signal_items = "".join(f"<li>{escape(signal)}</li>" for signal in signals)
        signal_html = f'<ul class="risk-gauge-card__signals">{signal_items}</ul>'

    gauge = (
        f'<section class="risk-gauge-card risk-gauge-card--{level_class}">'
        f'<div class="risk-gauge-card__header">'
        f'<h4 class="risk-gauge-card__title">Phân Tích Rủi Ro Giao Dịch</h4>'
        f'<span class="risk-gauge-card__chip">{label}</span>'
        f"</div>"
        f'<div class="risk-gauge-card__score-title">Điểm rủi ro</div>'
        f'<div class="risk-gauge-card__score-row">'
        f'<span class="risk-gauge-card__score-label">Thang đo rủi ro</span>'
        f'<span class="risk-gauge-card__score-value">{score:.2f} điểm</span>'
        f"</div>"
        f'<div class="risk-meter">'
        f'<div class="risk-meter__bar" aria-hidden="true"></div>'
        f'<div class="risk-meter__thumb" style="left: {clamped_pct}%" aria-hidden="true"></div>'
        f"</div>"
        f'<div class="risk-meter__legend">'
        f"<span>An toàn</span>"
        f"<span>Trung bình</span>"
        f"<span>Nguy hiểm</span>"
        f"</div>"
        f"{signal_html}"
        f'<p class="risk-gauge-card__question">Tôi phát hiện rủi ro {level_message}, bạn có muốn giao dịch tiếp không?</p>'
        f"</section>"
    )
    return gauge
