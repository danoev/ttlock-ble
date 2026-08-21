"""Device-feature discovery and typed capability decoding."""

from __future__ import annotations

from ..models import LockCapabilities
from .envelope import RESPONSE_SUCCESS, parse_response_status


def payload_feature_query() -> bytes:
    """Build the empty `COMM_SEARCH_DEVICE_FEATURE` request payload."""
    return b""


def parse_feature_response(plaintext: bytes) -> tuple[LockCapabilities, int | None]:
    """Decode the battery byte and arbitrary-width feature bit field."""
    _command, status, data = parse_response_status(plaintext)
    if status != RESPONSE_SUCCESS:
        raise RuntimeError(f"device-feature query failed with status={status:#x}")
    if len(data) < 2:
        raise ValueError("device-feature response is missing the feature bit field")
    battery = data[0]
    return LockCapabilities(int.from_bytes(data[1:], "big")), battery
