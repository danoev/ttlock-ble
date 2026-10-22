"""Opt-in private decoding of established MIT inventory layouts; no logging."""

from __future__ import annotations

from ..models import InventoryParseError, InventoryReason
from ..models.administration import AdministrativeRecord
from .access_inventory import (
    parse_card_list_response,
    parse_fingerprint_list_response,
    parse_passcode_list_response,
)
from .encoding import decode_date5


def parse_administrative_record(method: str, plain: bytes) -> AdministrativeRecord:
    """Extract only validated record IDs; never format identifiers into errors."""
    window = None
    if method == "keypad_pin":
        entry, _cursor, unknown = parse_passcode_list_response(plain)
        if entry is None or unknown:
            raise InventoryParseError(InventoryReason.LAYOUT)
        item = plain[6:]
        identifier = item[3 : 3 + item[2]]
        if not (4 <= len(identifier) <= 9) or not identifier.isdigit():
            raise InventoryParseError(InventoryReason.LAYOUT)
        record_type = f"pin_type_{item[1]}"
        trailer = 4 + item[2] + item[3 + item[2]]
        dates = item[trailer:]
    elif method == "fingerprint":
        entry = parse_fingerprint_list_response(plain)
        identifier = plain[6:12]  # ID and slot together; not the pagination position
        record_type = "fingerprint_record"
        dates = plain[12:22]
    elif method == "ic_card":
        entry = parse_card_list_response(plain)
        identifier = plain[6:10]
        record_type = "card_4byte"
        dates = plain[10:20]
    else:
        raise InventoryParseError(InventoryReason.LAYOUT)
    if entry is None:
        raise InventoryParseError(InventoryReason.LAYOUT)
    if entry.validity == "time_window" and len(dates) == 10:
        start, end = decode_date5(dates[:5]), decode_date5(dates[5:])
        if start is not None and end is not None and start < end:
            window = (start.isoformat(), end.isoformat())
    return AdministrativeRecord(method, record_type, entry.validity, identifier, window)
