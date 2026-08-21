"""PassageModeType: recurrence family stored by the lock."""

from __future__ import annotations

from enum import IntEnum


class PassageModeType(IntEnum):
    """Recurrence family for a native passage-mode schedule."""

    WEEKLY = 1
    MONTHLY = 2
