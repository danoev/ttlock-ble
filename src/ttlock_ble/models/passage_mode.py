"""One native passage-mode schedule stored by a TTLock-family lock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt

    from ..constants import PassageModeType


@dataclass(frozen=True, slots=True)
class PassageMode:
    """Describe one weekly or monthly interval in the lock's local clock."""

    mode_type: PassageModeType
    week_or_day: int
    month: int
    start_time: dt.time
    end_time: dt.time

    def __post_init__(self) -> None:
        """Reject values that cannot fit in the protocol's one-byte fields."""
        if not 0 <= self.week_or_day <= 0xFF:
            raise ValueError("passage-mode week_or_day must fit in one byte")
        if not 0 <= self.month <= 0xFF:
            raise ValueError("passage-mode month must fit in one byte")
        if self.start_time.second or self.start_time.microsecond:
            raise ValueError("passage-mode start_time has minute precision")
        if self.end_time.second or self.end_time.microsecond:
            raise ValueError("passage-mode end_time has minute precision")
