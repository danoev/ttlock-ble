"""Read-only inventory, including capture-shaped layouts and secret handling."""

from __future__ import annotations

import asyncio
import traceback
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_virtual_key
from tests.test_client_ble import FakeBleakClient, _resp_frame
from ttlock_ble import TTLockClient
from ttlock_ble import commands as cmd
from ttlock_ble.exceptions import TTLockError

pytest_plugins = ("tests.test_client_ble",)


def _response(opcode: int, data: bytes = b"") -> bytes:
    return bytes([opcode, cmd.RESPONSE_SUCCESS]) + data


def _pin(code: bytes, *, cursor: int, validity: int = 1) -> bytes:
    trailer = bytes([0, 1, 1, 0, 0]) if validity == 1 else bytes(10)
    item = bytes([0, validity, len(code)]) + code + bytes([len(code)]) + code + trailer
    return _response(7, bytes([0, 0]) + cursor.to_bytes(2, "big") + item)


def _fingerprint(identifier: bytes, *, end: bytes) -> bytes:
    return _response(6, bytes([100, 6, 0, 1]) + identifier + bytes([0, 3]) + bytes(5) + end)


def _card(identifier: bytes, *, end: bytes) -> bytes:
    return _response(5, bytes([85, 1, 0, 1]) + identifier + bytes(5) + end)


def test_pin_parser_discards_values_and_tracks_cursor() -> None:
    code = b"8675309"
    item, cursor, unknown = cmd.parse_passcode_list_response(_pin(code, cursor=4))
    assert item is not None and item.validity == "permanent"
    assert cursor == 4 and not unknown
    assert code.decode() not in repr(item)
    assert cmd.parse_passcode_list_response(b"\x00\x00") == (None, 0, False)


def test_unknown_pin_type_is_skipped_without_dropping_cursor() -> None:
    item, cursor, unknown = cmd.parse_passcode_list_response(_pin(b"1456", cursor=2, validity=2))
    assert item is None and cursor == 2 and unknown


def test_confirmed_indexed_layouts_discard_identifiers() -> None:
    fp = bytes.fromhex("cafebabe")
    uid = bytes.fromhex("deadbeef")
    assert cmd.parse_fingerprint_list_response(
        _fingerprint(fp, end=bytes([99, 1, 1, 0, 0]))
    ) == cmd.parse_card_list_response(_card(uid, end=bytes([99, 1, 1, 0, 0])))
    assert fp.hex() not in repr(cmd.parse_fingerprint_list_response(_fingerprint(fp, end=bytes(5))))
    assert uid.hex() not in repr(cmd.parse_card_list_response(_card(uid, end=bytes(5))))
    assert cmd.parse_fingerprint_list_response(_response(6, bytes([100, 6, 255, 255]))) is None
    assert cmd.parse_card_list_response(_response(5, bytes([85, 1, 255, 255]))) is None


def test_unverified_card_and_error_are_credential_free() -> None:
    uid = bytes.fromhex("deadbeefcafebabe")
    with pytest.raises(ValueError) as long_error:
        cmd.parse_card_list_response(_card(uid, end=bytes(5)))
    with pytest.raises(ValueError) as failed_error:
        cmd.parse_card_list_response(bytes([5, 0]) + uid)
    assert uid.hex() not in str(long_error.value) + str(failed_error.value)


@pytest.mark.parametrize("method", ["get_passcodes", "get_fingerprints", "get_cards"])
async def test_admin_password_missing_prevents_any_ble_write(method: str) -> None:
    key = make_virtual_key()
    key.adminPs = ""
    client = TTLockClient(key, device=MagicMock())
    client._exchange = AsyncMock()  # type: ignore[method-assign]
    with pytest.raises(TTLockError, match="admin password"):
        await getattr(client, method)()
    client._exchange.assert_not_awaited()


async def test_page_navigation_partial_coverage_and_no_secret() -> None:
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    replies = [_pin(b"8675309", cursor=4), _pin(b"1456", cursor=0)]
    client._inventory_exchange = AsyncMock(side_effect=replies)  # type: ignore[method-assign]
    result = await client.get_passcodes()
    assert result.complete and len(result.entries) == 2
    assert "not a complete" in result.limitation
    assert b"\x00\x04" in client._inventory_exchange.await_args_list[1].args[1]
    assert "8675309" not in repr(result)


async def test_repeated_cursor_and_midscan_rejection_are_partial() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(return_value=_pin(b"1456", cursor=2))  # type: ignore[method-assign]
    result = await client.get_passcodes()
    assert not result.complete and len(result.entries) == 2
    assert "cursor repeated" in result.limitation
    client._inventory_exchange = AsyncMock(side_effect=[_pin(b"1456", cursor=1), bytes([7, 0])])  # type: ignore[method-assign]
    result = await client.get_passcodes()
    assert not result.complete and len(result.entries) == 1


async def test_indexed_card_unverified_layout_returns_partial() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(
        side_effect=[_card(bytes.fromhex("deadbeef"), end=bytes(5)), _card(bytes(8), end=bytes(5))]
    )  # type: ignore[method-assign]
    result = await client.get_cards()
    assert len(result.entries) == 1 and not result.complete
    assert "unverified" in result.limitation
    assert "deadbeef" not in repr(result)


async def test_inventory_cancellation_propagates_without_partial_result() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(side_effect=asyncio.CancelledError)  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await client.get_fingerprints()


async def test_transport_error_is_sanitized_and_later_failure_is_partial() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(side_effect=OSError("private wire detail"))  # type: ignore[method-assign]
    with pytest.raises(TTLockError, match="inventory read failed") as error:
        await client.get_cards()
    assert "private wire detail" not in str(error.value)
    client._inventory_exchange = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_card(bytes.fromhex("deadbeef"), end=bytes(5)), OSError("private wire detail")]
    )
    result = await client.get_cards()
    assert not result.complete and len(result.entries) == 1
    assert "private wire detail" not in repr(result)
    assert result.transport_interrupted


@pytest.mark.parametrize("phase", ["admin", "random", "page"])
async def test_admin_transport_failure_traceback_is_credential_free(phase: str) -> None:
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock())
    replies = []
    if phase != "admin":
        replies.append(
            _resp_frame(key, cmd.CMD_CHECK_ADMIN, _response(cmd.CMD_CHECK_ADMIN, bytes(4)))
        )
    if phase == "page":
        replies.append(_resp_frame(key, cmd.CMD_CHECK_RANDOM, _response(cmd.CMD_CHECK_RANDOM)))
    replies.append(OSError("synthetic-secret-frame"))
    client._exchange = AsyncMock(side_effect=replies)  # type: ignore[method-assign]
    with pytest.raises(TTLockError) as error:
        await client.get_cards()
    assert "synthetic-secret-frame" not in "".join(traceback.format_exception(error.value))


async def test_pin_transport_interruption_keeps_only_partial_metadata() -> None:
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    client._inventory_admin_handshake = AsyncMock()  # type: ignore[method-assign]
    client._inventory_exchange = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_pin(b"8675309", cursor=1), OSError("synthetic-secret-frame")]
    )
    result = await client.get_passcodes()
    assert result.transport_interrupted
    assert not result.complete and len(result.entries) == 1
    assert "8675309" not in repr(result)
    assert "synthetic-secret-frame" not in repr(result)
    assert not client._command_lock.locked()


async def test_malformed_admin_challenge_key_does_not_escape_in_traceback() -> None:
    key = make_virtual_key()
    key.unlockKey = "synthetic-private-key"
    client = TTLockClient(key, device=MagicMock())
    client._exchange = AsyncMock(  # type: ignore[method-assign]
        return_value=_resp_frame(key, cmd.CMD_CHECK_ADMIN, _response(cmd.CMD_CHECK_ADMIN, bytes(4)))
    )
    with pytest.raises(TTLockError) as error:
        await client.get_cards()
    assert "synthetic-private-key" not in "".join(traceback.format_exception(error.value))


async def test_real_encrypted_ble_handshake_and_indexed_read(patched_connect) -> None:
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock(), keep_alive_after_command=0)
    fake = FakeBleakClient(key)
    patched_connect(fake)
    await client.connect()
    fake.reply_for_next = [
        _resp_frame(key, cmd.CMD_CHECK_ADMIN, _response(cmd.CMD_CHECK_ADMIN, bytes([1, 2, 3, 4]))),
        _resp_frame(key, cmd.CMD_CHECK_RANDOM, _response(cmd.CMD_CHECK_RANDOM)),
        _resp_frame(
            key,
            cmd.CMD_MANAGE_IC_CARD,
            _card(bytes.fromhex("deadbeef"), end=bytes([99, 1, 1, 0, 0])),
        ),
        _resp_frame(key, cmd.CMD_MANAGE_IC_CARD, _response(5, bytes([85, 1, 255, 255]))),
    ]
    result = await client.get_cards()
    assert result.complete and len(result.entries) == 1
    assert result.entries[0].validity == "permanent"
    assert sum(chunk.startswith(b"\x7fZ") for chunk in fake.written) == 4
    assert "deadbeef" not in repr(result)
    await client.disconnect()


async def test_admin_rejection_prevents_inventory_read(patched_connect) -> None:
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock(), keep_alive_after_command=0)
    fake = FakeBleakClient(key)
    patched_connect(fake)
    await client.connect()
    fake.reply_for_next = [
        _resp_frame(key, cmd.CMD_CHECK_ADMIN, bytes([cmd.CMD_CHECK_ADMIN, cmd.RESPONSE_FAILED])),
    ]
    with pytest.raises(TTLockError, match="admin authorization"):
        await client.get_fingerprints()
    assert sum(chunk.startswith(b"\x7fZ") for chunk in fake.written) == 1
    await client.disconnect()
