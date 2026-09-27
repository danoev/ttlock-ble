"""SDK ownership must survive cancellation before connector return."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import ttlock_ble.client as client_module
from tests.conftest import make_virtual_key
from ttlock_ble import TTLockClient, TTLockError


async def test_cancelled_connector_retains_created_backend(monkeypatch):
    started = asyncio.Event()
    backend = MagicMock(is_connected=False)
    backend.disconnect = AsyncMock(return_value=None)

    async def _establish(_client_class, *_args, **kwargs):
        kwargs["ttlock_client_created"](backend)
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(client_module, "establish_connection", _establish)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    attempt = asyncio.create_task(client.connect())
    await started.wait()
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    assert client._client is backend
    assert client.connection_cleanup_confirmed is False
    await client.disconnect()
    backend.disconnect.assert_awaited_once()
    assert client.connection_cleanup_confirmed is True
    assert client._client is None


async def test_unassigned_attempt_is_not_confirmed_cleanup(monkeypatch):
    async def _unowned(*_args, **_kwargs):
        raise OSError("connector failed before handing over ownership")

    monkeypatch.setattr(client_module, "establish_connection", _unowned)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    with pytest.raises(TTLockError, match="Failed to connect"):
        await client.connect()

    assert client._client is None
    assert client.is_connected is False
    assert client.connection_cleanup_confirmed is False
    with pytest.raises(TTLockError, match="cannot be confirmed"):
        await client.disconnect()
    assert client.connection_cleanup_confirmed is False


async def test_failed_disconnect_with_false_connected_flag_stays_uncertain(monkeypatch):
    backend = MagicMock(is_connected=False)
    backend.disconnect = AsyncMock(side_effect=OSError("disconnect failed"))

    async def _establish(_class, *_args, **kwargs):
        kwargs["ttlock_client_created"](backend)
        raise OSError("setup failed")

    monkeypatch.setattr(client_module, "establish_connection", _establish)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    with pytest.raises(TTLockError):
        await client.connect()
    with pytest.raises(OSError, match="disconnect failed"):
        await client.disconnect()

    assert client._client is backend
    assert client.connection_cleanup_confirmed is False
    backend.disconnect = AsyncMock(return_value=None)
    await client.disconnect()
    assert client.connection_cleanup_confirmed is True


async def test_successful_disconnect_must_report_disconnected(monkeypatch):
    backend = MagicMock(is_connected=True)
    backend.disconnect = AsyncMock(return_value=None)

    async def _establish(_class, *_args, **kwargs):
        kwargs["ttlock_client_created"](backend)
        raise OSError("setup failed")

    monkeypatch.setattr(client_module, "establish_connection", _establish)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    with pytest.raises(TTLockError):
        await client.connect()
    with pytest.raises(TTLockError, match="still reports connected"):
        await client.disconnect()
    assert client._client is backend
    assert client.connection_cleanup_confirmed is False


async def test_never_started_client_has_explicit_no_resource_proof():
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    assert client.connection_cleanup_confirmed is True
    await client.disconnect()
    assert client.connection_cleanup_confirmed is True
