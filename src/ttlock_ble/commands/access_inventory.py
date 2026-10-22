"""Read-only credential inventory layouts, adapted from upstream 0.1.11.

Provenance: roquerodrigo/ttlock-ble passcode/fingerprint inventory and
PR #96's hardware-tested four-byte IC-card layout. No plaintext fields are
returned or included in diagnostics. The eight-byte card layout is rejected.
"""

from __future__ import annotations

from ..models.access_inventory import (
    InventoryEntry,
    InventoryParseError,
    InventoryReason,
    UnverifiedCardLayoutError,
)
from .envelope import RESPONSE_SUCCESS, parse_response_status

_END_SENTINEL = bytes([99, 1, 1, 0, 0])
_PIN_TRAILER_LENGTHS = {1: 5, 3: 10, 4: 7}


def payload_passcode_list(sequence: int) -> bytes:
    """Request one CMD 0x07 page by UInt16 big-endian sequence cursor."""
    return sequence.to_bytes(2, "big")


def payload_fingerprint_list(index: int) -> bytes:
    """Request indexed CMD 0x06/0x06 fingerprint inventory."""
    return bytes([6]) + index.to_bytes(2, "big")


def payload_card_list(index: int) -> bytes:
    """Request indexed CMD 0x05/0x01 IC-card inventory."""
    return bytes([1]) + index.to_bytes(2, "big")


def _data(plaintext: bytes, opcode: int) -> bytes:
    if len(plaintext) < 2:
        raise InventoryParseError(InventoryReason.TRUNCATED)
    echo, status, data = parse_response_status(plaintext)
    if echo != opcode:
        raise InventoryParseError(InventoryReason.LAYOUT)
    if status != RESPONSE_SUCCESS:
        raise InventoryParseError(InventoryReason.REJECTED)
    return data


def parse_passcode_list_response(plaintext: bytes) -> tuple[InventoryEntry | None, int, bool]:
    """Return credential-free item, next cursor and unknown-layout flag."""
    if plaintext == b"\x00\x00":  # captured bare end-of-list marker
        return None, 0, False
    data = _data(plaintext, 7)
    if len(data) == 0:  # captured bare [echo][success] terminator
        return None, 0, False
    if len(data) < 4:
        raise InventoryParseError(InventoryReason.TRUNCATED)
    cursor = int.from_bytes(data[2:4], "big")
    item = data[4:]
    if not item:
        return None, cursor, False
    if len(item) < 4:
        raise InventoryParseError(InventoryReason.TRUNCATED)
    pwd_type = item[1]
    trailer_length = _PIN_TRAILER_LENGTHS.get(pwd_type)
    if trailer_length is None:
        return None, cursor, True
    new_length = item[2]
    old_length_offset = 3 + new_length
    if old_length_offset >= len(item):
        raise InventoryParseError(InventoryReason.TRUNCATED)
    old_length = item[old_length_offset]
    trailer_offset = old_length_offset + 1 + old_length
    if len(item) - trailer_offset < trailer_length:
        raise InventoryParseError(InventoryReason.TRUNCATED)
    return InventoryEntry({1: "permanent", 3: "time_window", 4: "cyclic"}[pwd_type]), cursor, False


def _indexed_entry(plaintext: bytes, *, opcode: int, operation: int) -> bytes | None:
    data = _data(plaintext, opcode)
    if len(data) == 4 and data[1:] == bytes([operation, 0xFF, 0xFF]):
        return None
    if len(data) < 4 or data[1] != operation:
        raise InventoryParseError(InventoryReason.LAYOUT)
    return data


def parse_fingerprint_list_response(plaintext: bytes) -> InventoryEntry | None:
    """Discard fingerprint ID and slot from the confirmed 20-byte layout."""
    data = _indexed_entry(plaintext, opcode=6, operation=6)
    if data is None:
        return None
    if len(data) != 20:
        raise InventoryParseError(InventoryReason.LAYOUT)
    return InventoryEntry("permanent" if data[15:20] == _END_SENTINEL else "time_window")


def parse_card_list_response(plaintext: bytes) -> InventoryEntry | None:
    """Accept only PR #96's hardware-validated four-byte card layout."""
    data = _indexed_entry(plaintext, opcode=5, operation=1)
    if data is None:
        return None
    if len(data) == 22:
        raise UnverifiedCardLayoutError("eight-byte IC-card inventory layout is unverified")
    if len(data) != 18:
        raise InventoryParseError(InventoryReason.LAYOUT)
    return InventoryEntry("permanent" if data[13:18] == _END_SENTINEL else "time_window")
