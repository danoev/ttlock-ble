"""Native passage-mode schedule payloads and response parsing."""

from __future__ import annotations

import datetime as dt

from ..constants import PassageModeOperation, PassageModeType
from ..models import PassageMode
from .envelope import RESPONSE_SUCCESS, parse_response_status

_SCHEDULE_BYTES = 7


def payload_passage_mode_query(sequence: int = 0) -> bytes:
    """Request one page of passage schedules from `sequence`."""
    if not 0 <= sequence <= 0xFF:
        raise ValueError("passage-mode sequence must fit in one byte")
    return bytes([PassageModeOperation.QUERY, sequence])


def payload_passage_mode_change(
    operation: PassageModeOperation,
    schedule: PassageMode,
) -> bytes:
    """Build an ADD or DELETE request for one exact schedule record."""
    if operation not in {PassageModeOperation.ADD, PassageModeOperation.DELETE}:
        raise ValueError("passage-mode change must use ADD or DELETE")
    return bytes(
        [
            operation,
            schedule.mode_type,
            schedule.week_or_day,
            schedule.month,
            schedule.start_time.hour,
            schedule.start_time.minute,
            schedule.end_time.hour,
            schedule.end_time.minute,
        ]
    )


def payload_passage_mode_clear() -> bytes:
    """Build the request that removes every passage-mode schedule."""
    return bytes([PassageModeOperation.CLEAR])


def parse_passage_mode_response(plaintext: bytes) -> tuple[list[PassageMode], int]:
    """Decode a query page into schedules and its continuation sequence."""
    _command, status, data = parse_response_status(plaintext)
    if status != RESPONSE_SUCCESS:
        raise RuntimeError(f"passage-mode query failed with status={status:#x}")
    if len(data) < 3:
        raise ValueError("passage-mode query response is missing its page header")
    if data[1] != PassageModeOperation.QUERY:
        raise ValueError(f"passage-mode response echoed unexpected operation {data[1]}")
    raw_schedules = data[3:]
    if len(raw_schedules) % _SCHEDULE_BYTES:
        raise ValueError("passage-mode response contains a truncated schedule")

    schedules: list[PassageMode] = []
    for offset in range(0, len(raw_schedules), _SCHEDULE_BYTES):
        record = raw_schedules[offset : offset + _SCHEDULE_BYTES]
        try:
            schedules.append(
                PassageMode(
                    mode_type=PassageModeType(record[0]),
                    week_or_day=record[1],
                    month=record[2],
                    start_time=dt.time(record[3], record[4]),
                    end_time=dt.time(record[5], record[6]),
                )
            )
        except ValueError as error:
            raise ValueError(f"invalid passage-mode schedule at offset {offset}") from error
    return schedules, data[2]
