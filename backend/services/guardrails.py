"""Hard guardrails — deterministic safety checks that LLM cannot override.

ALL transactions require OTP (standard banking practice in Vietnam).
Risk levels determine the warning message shown BEFORE OTP:
- LOW: Standard OTP (no warning)
- MEDIUM: Warning about suspicious reports + OTP
- HIGH: Strong fraud warning + OTP
- BLOCK: Transaction rejected outright
"""
from __future__ import annotations

import logging

from backend.config import MOCK_OTP_CODE

logger = logging.getLogger(__name__)


def check_transaction_guardrails(
    *,
    amount: int | None,
    fraud_screening: dict | None = None,
    otp_verified: bool = False,
) -> dict:
    """Evaluate hard guardrails for a transaction draft.

    Returns dict with: allowed, requires_otp, blocked, warning_message, reason, risk_level.
    """
    # Rule 1: BLOCK — fraud CRITICAL
    if fraud_screening and fraud_screening.get("is_reported"):
        risk_level = fraud_screening.get("risk_level", "LOW")

        if risk_level == "CRITICAL":
            logger.warning("[GUARDRAIL] BLOCK — fraud risk CRITICAL")
            return {
                "allowed": False,
                "blocked": True,
                "requires_otp": False,
                "warning_message": None,
                "reason": (
                    "⚠️ Tài khoản này đã bị cơ quan chức năng xác nhận là tài khoản lừa đảo. "
                    "Giao dịch không thể thực hiện."
                ),
                "risk_level": "BLOCK",
            }

    # Rule 2: All non-blocked transactions require OTP
    if otp_verified:
        return {"allowed": True, "blocked": False, "requires_otp": False,
                "warning_message": None, "reason": None, "risk_level": "LOW"}

    # Determine warning based on risk
    warning = None
    risk = "LOW"

    if fraud_screening and fraud_screening.get("is_reported"):
        risk_level = fraud_screening.get("risk_level", "LOW")
        if risk_level == "HIGH":
            risk = "HIGH"
            report_count = fraud_screening.get("report_count", 0)
            warning = (
                f"⚠️ CẢNH BÁO: Tài khoản nhận có {report_count} báo cáo nghi ngờ lừa đảo "
                f"với mức rủi ro CAO. Vui lòng cân nhắc kỹ trước khi tiếp tục."
            )
        elif risk_level == "MEDIUM":
            risk = "MEDIUM"
            report_count = fraud_screening.get("report_count", 0)
            warning = (
                f"⚠️ Lưu ý: Tài khoản nhận có {report_count} báo cáo đáng ngờ."
            )

    reason = "Vui lòng nhập mã OTP đã gửi đến số điện thoại của bạn để xác nhận giao dịch."
    if warning:
        reason = warning + "\n\n" + reason

    return {
        "allowed": False,
        "blocked": False,
        "requires_otp": True,
        "warning_message": warning,
        "reason": reason,
        "risk_level": risk,
    }


def validate_otp(otp_input: str) -> bool:
    """Validate OTP code (mock implementation)."""
    return otp_input.strip() == MOCK_OTP_CODE
