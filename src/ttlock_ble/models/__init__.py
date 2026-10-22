"""Dataclass models for ttlock_ble: cloud and protocol record types."""

from __future__ import annotations

from .access_inventory import (
    InventoryDiagnostic,
    InventoryEntry,
    InventoryError,
    InventoryParseError,
    InventoryReason,
    InventoryResult,
    UnverifiedCardLayoutError,
)
from .administration import AdministrativeInventory, AdministrativeRecord
from .cloud_credentials import CloudCredentials
from .lock_advertisement import LockAdvertisement
from .lock_event import LockEvent
from .lock_version import LockVersion
from .log_entry import LogEntry
from .site_info import SiteInfo
from .virtual_key import VirtualKey

__all__ = [
    "AdministrativeInventory",
    "AdministrativeRecord",
    "CloudCredentials",
    "InventoryDiagnostic",
    "InventoryEntry",
    "InventoryError",
    "InventoryParseError",
    "InventoryReason",
    "InventoryResult",
    "LockAdvertisement",
    "LockEvent",
    "LockVersion",
    "LogEntry",
    "SiteInfo",
    "UnverifiedCardLayoutError",
    "VirtualKey",
]
