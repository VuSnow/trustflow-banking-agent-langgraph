"""Fraud Report Agent — LangGraph implementation with tool-calling."""
from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from backend.config import DATABASE_URL, OPENAI_API_KEY, OPENAI_MODEL
from backend.tools.fraud_tools import save_fraud_report_incident
from backend.tools.transaction_tools import check_fraud_risk, text2sql_query
from backend.prompts.fraud_report import FRAUD_REPORT_SYSTEM_PROMPT
from backend.services.langfuse_trace import get_trace_config

logger = logging.getLogger(__name__)

FRAUD_TOOLS = [check_fraud_risk, text2sql_query, save_fraud_report_incident]


def create_fraud_agent():
    """Create the fraud report agent graph."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.0,
    )

    agent = create_react_agent(
        model=llm,
        tools=FRAUD_TOOLS,
        prompt=SystemMessage(content=FRAUD_REPORT_SYSTEM_PROMPT),
    )
    return agent


async def run_fraud_agent(
    message: str,
    user_id: str,
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    """Run the fraud report agent and return structured output."""
    agent = create_fraud_agent()

    messages = []
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
            trace_name="fraud_agent",
        )
        config.setdefault("recursion_limit", 25)
        result = await agent.ainvoke({"messages": messages}, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            last_msg = final_messages[-1]
            raw_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        else:
            raw_content = ""

        return _parse_fraud_output(raw_content)

    except Exception as e:
        logger.error(f"[FRAUD AGENT] Error: {e}", exc_info=True)
        return {
            "status": "clarification_needed",
            "message": "Xin lỗi, tôi không thể xử lý yêu cầu lúc này.",
            "data": {"error": str(e)},
        }


def _parse_fraud_output(raw: str) -> dict:
    """Parse fraud agent output."""
    try:
        content = raw.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        data = json.loads(content)
        status = data.get("status", "")

        if status == "draft_created":
            return {
                "status": "draft_ready",
                "message": data.get("message", "Xác nhận gửi báo cáo lừa đảo?"),
                "data": data,
            }
        elif status == "info_response":
            message = data.get("message", "")
            if data.get("operation") == "CHECK_ACCOUNT_RISK":
                message = _ensure_account_risk_table(message, data)
            return {
                "status": "info_response",
                "message": message,
                "data": data.get("data", data),
            }
        elif status == "needs_clarification":
            message = data.get("message", "Vui lòng cung cấp thêm thông tin.")
            return {
                "status": "clarification_needed",
                "message": _ensure_clarification_table(message, data),
                "data": data,
            }
        elif status == "cancelled":
            return {
                "status": "info_response",
                "message": data.get("message", "Đã hủy."),
                "data": {},
            }
        else:
            return {"status": "info_response", "message": raw, "data": data}
    except (json.JSONDecodeError, TypeError):
        # LLM returned free text — likely a natural language response
        return {"status": "info_response", "message": raw or "Lỗi xử lý.", "data": {}}


def _ensure_clarification_table(message: str, data: dict) -> str:
    """Ensure fraud-report intake prompts render as a user-facing Markdown table."""
    if "|" in (message or ""):
        return message

    missing_fields = data.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []

    if not missing_fields and _looks_like_incident_intake(message):
        missing_fields = [
            "reported_account_no",
            "reported_bank_code",
            "reported_amount",
            "contact_channel",
            "aftermath",
            "reason_text",
            "has_evidence",
        ]

    if not missing_fields:
        return message

    rows = "\n".join(_missing_field_table_row(field) for field in missing_fields)
    return (
        f"{message}\n\n"
        "| Thông tin cần cung cấp | Bắt buộc? | Ghi chú |\n"
        "|---|---|---|\n"
        f"{rows}"
    )


def _ensure_account_risk_table(message: str, data: dict) -> str:
    """Ensure account-risk answers always include a user-facing Markdown table."""
    if "|" in (message or ""):
        return message

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return message

    payload = _enrich_account_risk_payload(payload)
    account_no = _display_value(payload.get("account_no"))
    bank_code = _display_value(payload.get("bank_code"), fallback="Không xác định")
    is_reported = bool(payload.get("is_reported"))
    risk_level = _display_value(payload.get("risk_level"), fallback="LOW")
    report_count = _display_value(payload.get("report_count"), fallback="0")
    unique_reporter_count = _display_value(payload.get("unique_reporter_count"), fallback="0")
    total_reported_amount = _format_vnd(payload.get("total_reported_amount"))

    if is_reported:
        status_text = "Đã có báo cáo liên quan đến lừa đảo"
    else:
        status_text = "Chưa tìm thấy báo cáo lừa đảo trong dữ liệu hiện tại"

    table = (
        "| Thông tin | Kết quả |\n"
        "|---|---|\n"
        f"| Số tài khoản | {account_no} |\n"
        f"| Ngân hàng | {bank_code} |\n"
        f"| Tình trạng | {status_text} |\n"
        f"| Mức rủi ro | {risk_level} |\n"
        f"| Số báo cáo đã ghi nhận | {report_count} |\n"
        f"| Số người báo cáo khác nhau | {unique_reporter_count} |\n"
        f"| Tổng số tiền đã được báo cáo | {total_reported_amount} |"
    )

    return f"{message}\n\n{table}" if message else table


def _enrich_account_risk_payload(payload: dict) -> dict:
    """Fill missing account-risk fields from reported_accounts when the LLM omits them."""
    account_no = str(payload.get("account_no") or "").strip()
    if not account_no:
        return payload

    missing_details = (
        not payload.get("bank_code")
        or payload.get("report_count") is None
        or payload.get("unique_reporter_count") is None
        or payload.get("total_reported_amount") is None
    )
    if not missing_details:
        return payload

    try:
        import psycopg2

        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bank_code, risk_level, valid_report_count,
                           unique_reporter_count, total_reported_amount, status
                    FROM reported_accounts
                    WHERE account_no = %s
                    ORDER BY valid_report_count DESC, last_reported_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (account_no,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[FRAUD AGENT] risk table enrichment failed: %s", exc)
        return payload

    if not row:
        return payload

    enriched = dict(payload)
    enriched.setdefault("bank_code", row[0])
    enriched.setdefault("risk_level", row[1])
    enriched.setdefault("report_count", row[2])
    enriched.setdefault("unique_reporter_count", row[3])
    enriched.setdefault("total_reported_amount", row[4])
    enriched.setdefault("account_status", row[5])
    enriched["is_reported"] = True
    return enriched


def _display_value(value: object, fallback: str = "Không có") -> str:
    text = str(value or "").strip()
    return text or fallback


def _format_vnd(value: object) -> str:
    try:
        amount = int(str(value or "0").replace(",", "").strip())
    except ValueError:
        amount = 0
    return f"{amount:,} VND".replace(",", ".")


def _looks_like_incident_intake(message: str) -> bool:
    normalized = (message or "").lower()
    return "báo cáo lừa đảo" in normalized and "cung cấp" in normalized


def _missing_field_table_row(field: object) -> str:
    label, required, note = _friendly_missing_field(field)
    return f"| {label} | {required} | {note} |"


def _friendly_missing_field(field: object) -> tuple[str, str, str]:
    """Map internal or plain missing-field text to safe Vietnamese table content."""
    text = str(field or "").strip()
    labels = {
        "reported_account_no": ("Số tài khoản bị báo cáo", "Có", "Tài khoản nhận tiền hoặc tài khoản nghi ngờ"),
        "Số tài khoản bị báo cáo": ("Số tài khoản bị báo cáo", "Có", "Tài khoản nhận tiền hoặc tài khoản nghi ngờ"),
        "reported_bank_code": ("Ngân hàng của tài khoản đó", "Có", "Ví dụ: SHB, VCB, VPB"),
        "Ngân hàng của tài khoản đó": ("Ngân hàng của tài khoản đó", "Có", "Ví dụ: SHB, VCB, VPB"),
        "reported_amount": ("Số tiền bị mất", "Không bắt buộc", "Nếu bạn nhớ hoặc có trong giao dịch"),
        "Số tiền bị mất, nếu biết": ("Số tiền bị mất", "Không bắt buộc", "Nếu bạn nhớ hoặc có trong giao dịch"),
        "contact_channel": ("Kênh liên lạc", "Có", "Ví dụ: Zalo, Facebook, điện thoại"),
        "Kênh liên lạc mà kẻ lừa đảo đã dùng": ("Kênh liên lạc", "Có", "Ví dụ: Zalo, Facebook, điện thoại"),
        "aftermath": ("Hậu quả của sự việc", "Có", "Ví dụ: mất tiền, bị chặn liên lạc"),
        "Hậu quả của sự việc": ("Hậu quả của sự việc", "Có", "Ví dụ: mất tiền, bị chặn liên lạc"),
        "reason_text": ("Mô tả ngắn gọn về sự việc", "Có", "Tóm tắt điều đã xảy ra"),
        "Mô tả ngắn gọn về sự việc": ("Mô tả ngắn gọn về sự việc", "Có", "Tóm tắt điều đã xảy ra"),
        "has_evidence": ("Bằng chứng", "Có", "Cho biết bạn có ảnh chụp, tin nhắn, biên lai... hay không"),
        "Bạn có bằng chứng hay không": ("Bằng chứng", "Có", "Cho biết bạn có ảnh chụp, tin nhắn, biên lai... hay không"),
        "fraud_type": ("Loại lừa đảo", "Không bắt buộc", "Ví dụ: giả mạo, đầu tư giả, lừa chuyển tiền"),
        "transaction_ref": ("Mã giao dịch liên quan", "Không bắt buộc", "Nếu có trong lịch sử giao dịch"),
        "reported_customer_cif": ("Thông tin chủ tài khoản bị báo cáo nếu biết", "Không bắt buộc", "Chỉ cung cấp nếu bạn biết"),
    }
    return labels.get(text, (text, "Cần bổ sung", ""))
