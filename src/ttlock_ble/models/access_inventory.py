"""Credential-free summaries of read-only, admin-gated BLE inventory queries."""

from __future__ import annotations

from dataclasses import dataclass


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


class UnverifiedCardLayoutError(ValueError):
    """An 8-byte card response was seen, but that layout lacks live validation."""
