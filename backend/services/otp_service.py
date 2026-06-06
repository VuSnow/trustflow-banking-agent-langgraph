"""OTP Service — challenge lifecycle with transaction hash binding.

Design:
- OTP challenge is bound to a summary_hash of the transaction draft
- If draft is modified after OTP issuance, hash won't match → challenge invalid
- Supports retry limits and expiry
- Phase 1: in-memory store with mock OTP code
- Phase 3: PostgreSQL-backed with real SMS integration
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.config import MOCK_OTP_CODE

logger = logging.getLogger(__name__)


@dataclass
class OTPChallenge:
    """An active OTP challenge bound to a specific draft state."""

    challenge_id: str
    flow_id: str
    user_id: str
    summary_hash: str
    otp_code: str
    created_at: datetime
    expires_at: datetime
    max_attempts: int
    attempts: int = 0
    validated: bool = False


@dataclass
class OTPValidationResult:
    """Result of OTP validation attempt."""

    valid: bool
    reason: str | None = None  # "expired", "max_attempts", "hash_mismatch", "wrong_code"


class OTPService:
    """OTP challenge lifecycle — bound to transaction summary hash.

    Phase 1: In-memory store, mock OTP code.
    Phase 3: Replace with DB-backed store + real SMS.
    """

    def __init__(self):
        # In-memory store for Phase 1
        self._challenges: dict[str, OTPChallenge] = {}

    def create_challenge(
        self,
        flow_id: str,
        user_id: str,
        summary_hash: str,
        expires_in: timedelta = timedelta(minutes=5),
        max_attempts: int = 3,
    ) -> str:
        """Create OTP challenge bound to draft hash.

        Args:
            flow_id: Current flow identifier.
            user_id: Customer cif_no.
            summary_hash: Hash of critical draft fields (amount, account, bank).
            expires_in: Challenge validity duration.
            max_attempts: Max wrong attempts before invalidation.

        Returns:
            challenge_id for later validation.
        """
        challenge_id = str(uuid.uuid4())
        now = datetime.now()

        challenge = OTPChallenge(
            challenge_id=challenge_id,
            flow_id=flow_id,
            user_id=user_id,
            summary_hash=summary_hash,
            otp_code=MOCK_OTP_CODE,  # Phase 1: mock; Phase 3: random 6-digit
            created_at=now,
            expires_at=now + expires_in,
            max_attempts=max_attempts,
        )

        self._challenges[challenge_id] = challenge

        logger.info(
            f"[OTP] Challenge created: {challenge_id} for flow={flow_id} "
            f"user={user_id} hash={summary_hash[:8]}..."
        )

        return challenge_id

    def validate(
        self,
        challenge_id: str,
        otp_input: str,
        current_summary_hash: str,
    ) -> OTPValidationResult:
        """Validate OTP + verify draft hasn't been tampered (hash match).

        Args:
            challenge_id: The challenge to validate against.
            otp_input: User-provided OTP code.
            current_summary_hash: Recomputed hash from current draft state.

        Returns:
            OTPValidationResult indicating success or failure reason.
        """
        challenge = self._challenges.get(challenge_id)

        if not challenge:
            logger.warning(f"[OTP] Challenge not found: {challenge_id}")
            return OTPValidationResult(valid=False, reason="challenge_not_found")

        # Check expiry
        if datetime.now() > challenge.expires_at:
            logger.warning(f"[OTP] Challenge expired: {challenge_id}")
            self._challenges.pop(challenge_id, None)
            return OTPValidationResult(valid=False, reason="expired")

        # Check max attempts
        if challenge.attempts >= challenge.max_attempts:
            logger.warning(f"[OTP] Max attempts reached: {challenge_id}")
            self._challenges.pop(challenge_id, None)
            return OTPValidationResult(valid=False, reason="max_attempts")

        # Check hash mismatch (draft was modified after OTP issued)
        if challenge.summary_hash != current_summary_hash:
            logger.warning(
                f"[OTP] Hash mismatch: expected={challenge.summary_hash[:8]}, "
                f"got={current_summary_hash[:8]}"
            )
            self._challenges.pop(challenge_id, None)
            return OTPValidationResult(valid=False, reason="hash_mismatch")

        # Validate OTP code
        challenge.attempts += 1
        if otp_input.strip() != challenge.otp_code:
            remaining = challenge.max_attempts - challenge.attempts
            logger.info(f"[OTP] Wrong code. Attempts: {challenge.attempts}/{challenge.max_attempts}")
            if remaining <= 0:
                self._challenges.pop(challenge_id, None)
                return OTPValidationResult(valid=False, reason="max_attempts")
            return OTPValidationResult(valid=False, reason="wrong_code")

        # Success
        challenge.validated = True
        self._challenges.pop(challenge_id, None)
        logger.info(f"[OTP] Validated successfully: {challenge_id}")
        return OTPValidationResult(valid=True)

    def get_remaining_attempts(self, challenge_id: str) -> int:
        """Get remaining OTP attempts for a challenge."""
        challenge = self._challenges.get(challenge_id)
        if not challenge:
            return 0
        return max(0, challenge.max_attempts - challenge.attempts)

    def invalidate(self, challenge_id: str) -> None:
        """Explicitly invalidate a challenge (e.g. on flow cancel)."""
        self._challenges.pop(challenge_id, None)
        logger.info(f"[OTP] Challenge invalidated: {challenge_id}")


# Module-level singleton for Phase 1
otp_service = OTPService()
