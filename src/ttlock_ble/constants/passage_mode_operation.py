"""PassageModeOperation: sub-operation for native passage-mode management."""

from __future__ import annotations

from enum import IntEnum


class PassageModeOperation(IntEnum):
    """Sub-operation for `COMM_CONFIGURE_PASSAGE_MODE`."""

    QUERY = 1
    ADD = 2
    DELETE = 3
    CLEAR = 4
