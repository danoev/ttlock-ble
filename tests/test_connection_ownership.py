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
    await asyncio.wait_for(started.wait(), timeout=1)
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


def test_connector_constructor_registers_before_any_connection(monkeypatch):
    created = []
    monkeypatch.setattr(
        client_module.BleakClientWithServiceCache,
        "__init__",
        lambda *_a, **_k: None,
    )
    owned = client_module._OwnedBleakClient(
        MagicMock(),
        ttlock_client_created=created.append,
    )
    assert created == [owned]


async def test_real_connector_cancellation_requires_explicit_backend_disconnect(monkeypatch):
    import bleak_retry_connector as connector

    started = asyncio.Event()
    released = asyncio.Event()
    created = []

    class Backend:
        is_connected = False

        def __init__(self, _device, *, ttlock_client_created, **_kwargs):
            created.append(self)
            ttlock_client_created(self)

        async def connect(self, **_kwargs):
            started.set()
            await asyncio.Future()

        async def disconnect(self):
            released.set()

    monkeypatch.setattr(client_module, "_OwnedBleakClient", Backend)
    monkeypatch.setattr(connector, "IS_LINUX", False)
    monkeypatch.setattr(connector, "_has_valid_services_in_cache", AsyncMock(return_value=False))
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    attempt = asyncio.create_task(client.connect())
    await asyncio.wait_for(started.wait(), timeout=1)
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    assert len(created) == 1
    assert client._client is created[0]
    assert released.is_set() is False
    assert client.connection_cleanup_confirmed is False
    await client.disconnect()
    assert released.is_set()
    assert client.connection_cleanup_confirmed is True


async def test_disconnect_cancellation_retains_backend_for_retry(monkeypatch):
    backend = MagicMock(is_connected=False)
    started = asyncio.Event()

    async def _disconnect():
        started.set()
        await asyncio.Future()

    async def _establish(_class, *_args, **kwargs):
        kwargs["ttlock_client_created"](backend)
        raise OSError("setup failed")

    backend.disconnect = AsyncMock(side_effect=_disconnect)
    monkeypatch.setattr(client_module, "establish_connection", _establish)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    with pytest.raises(TTLockError):
        await client.connect()
    cleanup = asyncio.create_task(client.disconnect())
    await asyncio.wait_for(started.wait(), timeout=1)
    cleanup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cleanup

    assert client._client is backend
    assert client.connection_cleanup_confirmed is False
    backend.disconnect = AsyncMock(return_value=None)
    await client.disconnect()
    assert client.connection_cleanup_confirmed is True


async def test_disconnect_cannot_retire_backend_while_setup_is_running(monkeypatch):
    started = asyncio.Event()
    backend = MagicMock(is_connected=False)
    backend.disconnect = AsyncMock(return_value=None)

    async def _establish(_class, *_args, **kwargs):
        kwargs["ttlock_client_created"](backend)
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(client_module, "establish_connection", _establish)
    client = TTLockClient(make_virtual_key(), device=MagicMock())
    attempt = asyncio.create_task(client.connect())
    await asyncio.wait_for(started.wait(), timeout=1)
    with pytest.raises(TTLockError, match="still running"):
        await client.disconnect()
    assert client._client is backend
    assert client.connection_cleanup_confirmed is False
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    await client.disconnect()
    assert client.connection_cleanup_confirmed is True
