"""Protocol diagnostics retain status and size without credential payloads."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_virtual_key
from ttlock_ble import TTLockClient, TTLockError
from ttlock_ble import commands as cmd
from ttlock_ble.crypto import hex_key_to_bytes
from ttlock_ble.protocol import Frame


@pytest.mark.parametrize(
    "operation",
    ["query", "log", "auto_lock", "passcode", "control", "clock", "authentication"],
)
async def test_response_diagnostics_never_log_credentials(operation, monkeypatch, caplog):
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock(), keep_alive_after_command=0)
    sensitive = (key.aesKeyStr, key.unlockKey, key.adminPs, "PIN-864209", "LOG-USER-SECRET")
    secret_data = "|".join(sensitive).encode()
    payload = bytes([cmd.CMD_CHECK_USER_TIME, cmd.RESPONSE_SUCCESS]) + secret_data
    reply = Frame.for_lock(key.lockVersion, cmd.CMD_RESPONSE, payload).encrypt_data(
        hex_key_to_bytes(key.aesKeyStr),
    )
    client._exchange = AsyncMock(return_value=reply)
    monkeypatch.setattr(cmd, "parse_lock_status", lambda _plain: 0)
    monkeypatch.setattr(cmd, "parse_state_battery", lambda _plain: 80)
    monkeypatch.setattr(cmd, "parse_operate_log_response", lambda _plain: ([], 1))
    monkeypatch.setattr(cmd, "parse_auto_lock_response", lambda _plain: (30, 80))
    monkeypatch.setattr(cmd, "parse_check_user_time_response", lambda _plain: 0xDEADBEEF)

    with caplog.at_level(logging.DEBUG, logger="ttlock_ble.client"):
        if operation == "query":
            await client.query_state()
        elif operation == "log":
            await client.get_operation_log()
        elif operation == "auto_lock":
            await client.get_auto_lock_time()
        elif operation == "passcode":
            await client._keyboard_password_exchange(b"", "add passcode")
        elif operation == "control":
            await client.unlock()
        elif operation == "clock":
            await client.calibrate_time()
        else:
            await client._check_user_time()

    assert caplog.records
    for secret in sensitive:
        assert secret not in caplog.text
        assert secret.encode().hex() not in caplog.text
    assert payload.hex() not in caplog.text
    assert reply.data.hex() not in caplog.text
    assert "deadbeef" not in caplog.text.lower()


async def test_tx_and_rx_diagnostics_do_not_dump_frames(caplog):
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock())
    client._client = MagicMock()
    client._client.write_gatt_char = AsyncMock(return_value=None)
    client._write_char = MagicMock()
    frame = Frame.for_lock(key.lockVersion, cmd.CMD_MANAGE_KEYBOARD_PASSWORD, b"PIN-864209")
    client._waiting_for_response = 1
    with caplog.at_level(logging.DEBUG, logger="ttlock_ble.client"):
        await client._send(frame)
        client._on_notify(MagicMock(), bytearray(frame.build()))

    assert "TX cmd=" in caplog.text
    assert "RX notification:" in caplog.text
    assert frame.build().hex() not in caplog.text
    assert frame.data.hex() not in caplog.text
    assert "PIN-864209" not in caplog.text


async def test_rejected_credentials_do_not_escape_in_error_diagnostics(caplog):
    key = make_virtual_key()
    client = TTLockClient(key, device=MagicMock())
    secret = b"PIN-864209|ADMIN-SECRET"
    reply = Frame.for_lock(
        key.lockVersion,
        cmd.CMD_RESPONSE,
        bytes([cmd.CMD_CHECK_USER_TIME, 0]) + secret,
    ).encrypt_data(hex_key_to_bytes(key.aesKeyStr))
    client._exchange = AsyncMock(return_value=reply)
    with (
        caplog.at_level(logging.DEBUG, logger="ttlock_ble.client"),
        pytest.raises(TTLockError) as caught,
    ):
        await client._check_user_time()
    diagnostic = caplog.text + str(caught.value)
    assert "status=0x0" in diagnostic
    assert secret.hex() not in diagnostic
    assert secret.decode() not in diagnostic


def test_parser_errors_do_not_include_decrypted_payload():
    from ttlock_ble.commands.clock import parse_get_lock_time_response
    from ttlock_ble.commands.envelope import parse_response_status
    from ttlock_ble.commands.session import parse_check_user_time_response

    for parser, payload in (
        (parse_response_status, b"x"),
        (parse_check_user_time_response, b"\x55\x00PIN-864209"),
        (parse_get_lock_time_response, b"\x34\x00PIN-864209"),
    ):
        with pytest.raises((ValueError, RuntimeError)) as caught:
            parser(payload)
        assert payload.hex() not in str(caught.value)
        assert "PIN-864209" not in str(caught.value)
