"""Credential-free summaries of read-only, admin-gated BLE inventory queries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..exceptions import TTLockError


class InventoryReason(StrEnum):
    """Closed vocabulary: never copy device or exception text into diagnostics."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete_inventory"
    REJECTED = "operation_rejected"
    LAYOUT = "unrecognised_response_layout"
    TRUNCATED = "truncated_response"
    CURSOR = "pagination_error"
    LIMIT = "pagination_limit"
    TRANSPORT = "transport_interrupted"
    ADMIN_REJECTED = "admin_challenge_rejected"
    ADMIN_TIMEOUT = "admin_challenge_timeout"


@dataclass(frozen=True, slots=True)
class InventoryDiagnostic:
    """Only envelope/shape metadata; never retain plaintext or identifiers."""

    method: str
    page: int
    cursor: int
    response_length: int | None
    command_echo: int | None
    response_status: int | None
    category: InventoryReason


class InventoryError(TTLockError):
    """Credential-safe classified failure without a raw exception chain."""

    def __init__(
        self,
        reason: InventoryReason,
        stage: str,
        diagnostic: InventoryDiagnostic | None = None,
    ) -> None:
        """Store only classified metadata and a fixed-format message."""
        self.reason = reason
        self.stage = stage
        self.diagnostic = diagnostic
        operation = "admin authorization" if stage == "admin" else "read"
        super().__init__(f"Credential inventory {operation} failed: {reason.value}")


class InventoryParseError(ValueError):
    """A parser category that carries no device-controlled text."""

    def __init__(self, reason: InventoryReason) -> None:
        """Describe malformed data without retaining its contents."""
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """One observed item without PIN, card UID, fingerprint ID or slot."""

    validity: str


@dataclass(frozen=True, slots=True)
class InventoryResult:
    """Enumeration result; `complete` means the cursor ended, not full coverage."""

    entries: tuple[InventoryEntry, ...]
    complete: bool
    limitation: str
    skipped_unknown: int = 0
    transport_interrupted: bool = False
    reason: InventoryReason = InventoryReason.COMPLETE
    diagnostic: InventoryDiagnostic | None = None


class UnverifiedCardLayoutError(ValueError):
    """An 8-byte card response was seen, but that layout lacks live validation."""
