"""Sensitive, opt-in administrative records; never use in public telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .access_inventory import InventoryResult


@dataclass(frozen=True, slots=True)
class AdministrativeRecord:
    """A lock record, not a person; raw identifiers stay in private memory."""

    method: str
    record_type: str
    validity: str
    identifier: bytes = field(repr=False)
    observed_window: tuple[str, str] | None = None
    schedule_verified: bool = False


@dataclass(frozen=True, slots=True)
class AdministrativeInventory:
    """Explicit private API result; not serializable into ordinary HA events."""

    summary: InventoryResult
    records: tuple[AdministrativeRecord, ...] = field(repr=False)

    @property
    def records_complete(self) -> bool:
        """Require complete, uninterrupted traversal and distinct decoded records."""
        return (
            self.summary.complete
            and not self.summary.transport_interrupted
            and not self.summary.skipped_unknown
            and len(self.records) == len(self.summary.entries)
            and len({(r.record_type, r.identifier) for r in self.records}) == len(self.records)
        )
