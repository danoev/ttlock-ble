"""Capture-shaped termination, conservative truncation and safe page metadata."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_virtual_key
from tests.test_access_inventory import _pin
from ttlock_ble import InventoryError, InventoryReason, TTLockClient
from ttlock_ble import commands as cmd
from ttlock_ble.models import InventoryParseError


@pytest.mark.parametrize(
    "wire", [b"\x00\x00", b"\x07\x01", b"\x07\x01\x00\x00", b"\x07\x01\x00\x00\x00\x00"]
)
def test_only_known_pin_terminators_are_accepted(wire: bytes) -> None:
    assert cmd.parse_passcode_list_response(wire) == (None, 0, False)


@pytest.mark.parametrize(
    ("wire", "reason"),
    [
        (b"", InventoryReason.TRUNCATED),
        (b"\x07", InventoryReason.TRUNCATED),
        (b"\x07\x00\x1a", InventoryReason.REJECTED),
        (b"\x06\x01", InventoryReason.LAYOUT),
        (b"\x07\x01\x00", InventoryReason.TRUNCATED),
        (b"\x07\x01\x00\x01", InventoryReason.TRUNCATED),
        (b"\x07\x01\x00\x00\x00", InventoryReason.TRUNCATED),
        (b"\x07\x01\x00\x00\x00\x00\x01", InventoryReason.TRUNCATED),
    ],
)
def test_rejected_and_short_frames_never_establish_completion(wire, reason) -> None:
    with pytest.raises(InventoryParseError) as error:
        cmd.parse_passcode_list_response(wire)
    assert error.value.reason == reason


async def test_second_page_partial_includes_safe_shape_not_assumed_s31_capture(caplog) -> None:
    """The real S31 shape is unknown; this synthetic failed status stays partial."""
    caplog.set_level(logging.DEBUG, logger="ttlock_ble.client")
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_pin(b"8675309", cursor=5), b"\x07\x00" + b"8675309"]
    )
    result = await client.get_passcodes()
    assert len(result.entries) == 1 and not result.complete
    assert not result.transport_interrupted
    assert result.reason == InventoryReason.REJECTED
    assert result.diagnostic is not None
    assert result.diagnostic.page == 1 and result.diagnostic.cursor == 5
    assert result.diagnostic.response_length == 9
    assert result.diagnostic.command_echo == 7 and result.diagnostic.response_status == 0
    assert "8675309" not in repr(result) + caplog.text


async def test_admin_timeout_is_classified_without_raw_cause() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._exchange = AsyncMock(side_effect=TimeoutError("synthetic-private"))  # type: ignore[method-assign]
    with pytest.raises(InventoryError) as error:
        await client.get_passcodes()
    assert error.value.reason == InventoryReason.ADMIN_TIMEOUT
    assert error.value.stage == "admin"
    assert "synthetic-private" not in str(error.value)


async def test_unknown_type_keeps_cursor_and_cancellation_still_propagates() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_pin(b"8675309", cursor=2, validity=2), b"\x00\x00"]
    )
    result = await client.get_passcodes()
    assert result.skipped_unknown == 1 and result.complete
    assert result.reason == InventoryReason.INCOMPLETE
    client._inventory_exchange = AsyncMock(side_effect=asyncio.CancelledError)  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await client.get_passcodes()
