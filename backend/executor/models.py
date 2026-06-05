"""Execution result model."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    """Result of executing a transaction via banking API."""
    success: bool
    message: str
    error_code: str | None = None
    transaction_ref: str | None = None
    fee: int = 0
    balance_after: int | None = None
    data: dict = field(default_factory=dict)
