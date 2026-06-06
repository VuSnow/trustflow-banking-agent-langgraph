"""OTP Service — challenge creation, validation, and lifecycle management.

Design:
- OTP is bound to a draft summary_hash. If draft changes, OTP is invalid.
- Max 3 attempts. After that, challenge is expired.
- Uses MOCK_OTP_CODE from config for demo (no real SMS).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.config import MOCK_OTP_CODE

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
OTP_TTL_SECONDS = 300  # 5 minutes


@dataclass
class OTPChallenge:
    """A single OTP challenge bound to a flow."""

    challenge_id: str
    flow_id: str
    user_id: str
    summary_hash: str
    otp_code: str
    attempts: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    expired: bool = False


@dataclass
class OTPValidationResult:
    """Result of OTP validation."""

    valid: bool
    reason: str | None = None  # "expired", "max_attempts", "hash_mismatch", "wrong_code"


class OTPService:
    """In-memory OTP challenge store (demo/dev).

    For production, replace with Redis or DB-backed store.
    """

    def __init__(self):
        self._challenges: dict[str, OTPChallenge] = {}

    def create_challenge(
        self, flow_id: str, user_id: str, summary_hash: str
    ) -> str:
        """Create a new OTP challenge bound to the draft hash.

        Returns challenge_id.
        """
        challenge_id = str(uuid.uuid4())
        challenge = OTPChallenge(
            challenge_id=challenge_id,
            flow_id=flow_id,
            user_id=user_id,
            summary_hash=summary_hash,
            otp_code=MOCK_OTP_CODE,
        )
        self._challenges[challenge_id] = challenge
        logger.info(
            f"[OTP] Created challenge={challenge_id} flow={flow_id} user={user_id}"
        )
        return challenge_id

    def validate(
        self,
        challenge_id: str,
        otp_input: str,
        current_summary_hash: str,
    ) -> OTPValidationResult:
        """Validate OTP input against challenge.

        Checks:
        1. Challenge exists and is not expired
        2. TTL not exceeded
        3. Draft hash matches (prevents post-OTP draft tampering)
        4. OTP code matches
        5. Attempt count not exceeded
        """
        challenge = self._challenges.get(challenge_id)
        if not challenge or challenge.expired:
            return OTPValidationResult(valid=False, reason="expired")

        # TTL check
        elapsed = (datetime.now() - challenge.created_at).total_seconds()
        if elapsed > OTP_TTL_SECONDS:
            challenge.expired = True
            return OTPValidationResult(valid=False, reason="expired")

        # Hash integrity check
        if challenge.summary_hash != current_summary_hash:
            challenge.expired = True
            return OTPValidationResult(valid=False, reason="hash_mismatch")

        # Attempt limit check
        challenge.attempts += 1
        if challenge.attempts > MAX_ATTEMPTS:
            challenge.expired = True
            return OTPValidationResult(valid=False, reason="max_attempts")

        # Code check
        if otp_input.strip() != challenge.otp_code:
            if challenge.attempts >= MAX_ATTEMPTS:
                challenge.expired = True
                return OTPValidationResult(valid=False, reason="max_attempts")
            return OTPValidationResult(valid=False, reason="wrong_code")

        # Success
        challenge.expired = True  # One-time use
        logger.info(f"[OTP] Validated challenge={challenge_id}")
        return OTPValidationResult(valid=True)

    def get_remaining_attempts(self, challenge_id: str) -> int:
        """Get remaining attempts for a challenge."""
        challenge = self._challenges.get(challenge_id)
        if not challenge:
            return 0
        return max(0, MAX_ATTEMPTS - challenge.attempts)

    def invalidate(self, challenge_id: str) -> None:
        """Invalidate a challenge (e.g. on flow cancellation)."""
        challenge = self._challenges.get(challenge_id)
        if challenge:
            challenge.expired = True
            logger.info(f"[OTP] Invalidated challenge={challenge_id}")


# Module-level singleton
otp_service = OTPService()
