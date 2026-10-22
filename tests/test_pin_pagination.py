"""Exact upstream-captured terminator; S31's undisclosed bytes are not a fixture."""

from __future__ import annotations

import asyncio
import logging
import traceback
from unittest.mock import AsyncMock, MagicMock

import pytest

import ttlock_ble.client as client_module
from tests.conftest import make_virtual_key
from tests.test_access_inventory import _pin, _response
from tests.test_client_ble import FakeBleakClient, _resp_frame
from ttlock_ble import InventoryError, InventoryReason, TTLockClient
from ttlock_ble import commands as cmd
from ttlock_ble.models import InventoryParseError

pytest_plugins = ("tests.test_client_ble",)

# Protocol fact from upstream 8025f57 tests: _real_plain("0000") adds 07/01.
# This is NOT a claim about the two bytes omitted from the S31 diagnostics.
_WRAPPED_END = b"\x07\x01\x00\x00"


def _client(pages):
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()
    client._inventory_exchange = AsyncMock(side_effect=pages)
    return client


@pytest.mark.parametrize("cursors", [(336,), (7, 336)])
async def test_one_and_multiple_records_follow_cursors_to_exact_marker(cursors, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="ttlock_ble.client")
    client = _client([*(_pin(b"8675309", cursor=c) for c in cursors), _WRAPPED_END])
    result = await client.get_passcodes()
    assert result.complete and len(result.entries) == len(cursors)
    assert result.reason == InventoryReason.INCOMPLETE
    assert "not a complete" in result.limitation
    assert not result.transport_interrupted
    assert result.diagnostic is not None
    assert result.diagnostic.page == len(cursors)
    assert result.diagnostic.cursor == 336
    assert result.diagnostic.response_length == 4
    assert result.diagnostic.pin_short_end_marker_matches is True
    assert [call.args[1] for call in client._inventory_exchange.await_args_list] == [
        cursor.to_bytes(2, "big") for cursor in (0, *cursors)
    ]
    assert "8675309" not in repr(result) + caplog.text
    assert "38363735333039" not in repr(result) + caplog.text


@pytest.mark.parametrize("terminal", [b"\x00\x00", b"\x07\x01"])
async def test_existing_two_byte_terminal_replies_remain_supported(terminal) -> None:
    result = await _client([_pin(b"8675309", cursor=336), terminal]).get_passcodes()
    assert result.complete and len(result.entries) == 1
    assert result.reason == InventoryReason.INCOMPLETE


async def test_exact_initial_empty_marker_is_distinct_from_malformed_early_end() -> None:
    result = await _client([_WRAPPED_END]).get_passcodes()
    assert result.complete and not result.entries
    assert result.diagnostic is not None
    assert result.diagnostic.page == result.diagnostic.cursor == 0
    assert result.diagnostic.pin_short_end_marker_matches is True
    assert result.reason == InventoryReason.INCOMPLETE


def test_every_other_two_byte_data_value_is_rejected_not_generic_short_success() -> None:
    for value in range(1, 65536):
        with pytest.raises(InventoryParseError) as error:
            cmd.parse_passcode_list_response(b"\x07\x01" + value.to_bytes(2, "big"))
        assert error.value.reason == InventoryReason.TRUNCATED


@pytest.mark.parametrize("tail", [b"\x00\x01", b"\x01\x00", b"\xff\xff", b"12"])
@pytest.mark.parametrize("after_record", [False, True])
async def test_unmatched_four_byte_shape_reports_only_false_predicate(tail, after_record, caplog):
    caplog.set_level(logging.DEBUG, logger="ttlock_ble.client")
    wire = b"\x07\x01" + tail
    client = _client([*([_pin(b"8675309", cursor=336)] if after_record else []), wire])
    if after_record:
        result = await client.get_passcodes()
        assert not result.complete and len(result.entries) == 1
        assert not result.transport_interrupted
        diagnostic = result.diagnostic
    else:
        with pytest.raises(InventoryError) as error:
            await client.get_passcodes()
        assert error.value.reason == InventoryReason.TRUNCATED
        diagnostic = error.value.diagnostic
        assert "8675309" not in "".join(traceback.format_exception(error.value))
    assert diagnostic is not None
    assert diagnostic.pin_short_end_marker_matches is False
    assert diagnostic.category == InventoryReason.TRUNCATED
    assert wire.hex() not in repr(diagnostic) + caplog.text
    assert repr(wire) not in repr(diagnostic) + caplog.text


@pytest.mark.parametrize(
    ("wire", "reason"),
    [
        (b"\x07\x01\x00", InventoryReason.TRUNCATED),
        (b"\x07\x01\x00\x00\x00", InventoryReason.TRUNCATED),
        (b"\x07\x00\x00\x00", InventoryReason.REJECTED),
        (b"\x06\x01\x00\x00", InventoryReason.LAYOUT),
    ],
)
@pytest.mark.parametrize("after_record", [False, True])
async def test_malformed_early_or_later_response_never_completes(wire, reason, after_record):
    client = _client([*([_pin(b"8675309", cursor=336)] if after_record else []), wire])
    if after_record:
        result = await client.get_passcodes()
        assert not result.complete and len(result.entries) == 1
        assert result.reason == reason
        diagnostic = result.diagnostic
    else:
        with pytest.raises(InventoryError) as error:
            await client.get_passcodes()
        assert error.value.reason == reason
        diagnostic = error.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.pin_short_end_marker_matches is None


async def test_repeated_cursor_and_cap_stay_bounded(monkeypatch) -> None:
    client = _client([_pin(b"8675309", cursor=336), _pin(b"8675309", cursor=336)])
    result = await client.get_passcodes()
    assert not result.complete and result.reason == InventoryReason.CURSOR
    assert client._inventory_exchange.await_count == 2
    monkeypatch.setattr(client_module, "_MAX_INVENTORY_ROUND_TRIPS", 2)
    client = _client([_pin(b"8675309", cursor=1), _pin(b"2468135", cursor=2)])
    result = await client.get_passcodes()
    assert not result.complete and result.reason == InventoryReason.LIMIT
    assert client._inventory_exchange.await_count == 2


async def test_timeout_after_record_preserves_only_partial_evidence() -> None:
    client = _client([])
    key = make_virtual_key()
    # Exercise the real inventory exchange boundary, not just a raised result.
    del client._inventory_exchange
    client._exchange = AsyncMock(
        side_effect=[
            _resp_frame(key, 7, _pin(b"8675309", cursor=336)),
            TimeoutError("synthetic-private-frame"),
        ]
    )
    result = await client.get_passcodes()
    assert not result.complete and len(result.entries) == 1
    assert result.transport_interrupted and result.reason == InventoryReason.TRANSPORT
    assert "synthetic-private-frame" not in repr(result)
    assert "8675309" not in repr(result)
    assert not client._command_lock.locked()


async def test_pin_cancellation_releases_serialisation_without_fabricated_completion() -> None:
    client = _client([])
    started = asyncio.Event()

    async def page(*_args):
        started.set()
        await asyncio.Future()

    client._inventory_exchange.side_effect = page
    task = asyncio.create_task(client.get_passcodes())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client._command_lock.locked()


async def test_encrypted_admin_handshake_and_exact_end_cleanup(patched_connect) -> None:
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock(), keep_alive_after_command=0)
    fake = FakeBleakClient(key)
    patched_connect(fake)
    await client.connect()
    fake.reply_for_next = [
        _resp_frame(key, cmd.CMD_CHECK_ADMIN, _response(cmd.CMD_CHECK_ADMIN, bytes(4))),
        _resp_frame(key, cmd.CMD_CHECK_RANDOM, _response(cmd.CMD_CHECK_RANDOM)),
        _resp_frame(key, 7, _pin(b"8675309", cursor=336)),
        _resp_frame(key, 7, _WRAPPED_END),
    ]
    result = await client.get_passcodes()
    assert result.complete and len(result.entries) == 1
    assert sum(chunk.startswith(b"\x7fZ") for chunk in fake.written) == 4
    await client.disconnect()
    assert client.connection_cleanup_confirmed is True
