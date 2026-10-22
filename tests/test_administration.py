"""Explicit private record API and disabled offline management candidates."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from tests.test_access_inventory import _card, _fingerprint, _pin, _response
from tests.test_pin_pagination import _client
from ttlock_ble.commands.administrative_records import parse_administrative_record
from ttlock_ble.commands.management_candidates import (
    ManagementStage,
    indexed_management_candidate,
    interpret_candidate_response,
    pin_modify_candidate,
)


@pytest.mark.parametrize(
    ("method", "wire", "identifier"),
    [
        ("keypad_pin", _pin(b"8675309", cursor=0), b"8675309"),
        (
            "fingerprint",
            _fingerprint(bytes.fromhex("cafebabe"), end=bytes(5)),
            bytes.fromhex("cafebabe0003"),
        ),
        ("ic_card", _card(bytes.fromhex("deadbeef"), end=bytes(5)), bytes.fromhex("deadbeef")),
    ],
)
async def test_private_records_are_opt_in_and_never_in_public_summary(method, wire, identifier):
    terminal = {
        "keypad_pin": b"\x07\x01\x00\x00",
        "fingerprint": _response(6, b"\x64\x06\xff\xff"),
        "ic_card": _response(5, b"\x64\x01\xff\xff"),
    }[method]
    pages = [wire] if method == "keypad_pin" else [wire, terminal]
    client = _client(pages)
    result = await client.get_administrative_inventory(method)
    assert result.records_complete
    assert result.records[0].identifier == identifier
    assert not result.records[0].schedule_verified
    assert identifier.hex() not in repr(result) + repr(result.summary)
    assert identifier.hex() not in repr(result.records[0])
    assert "8675309" not in repr(result) + repr(result.records[0])
    assert not replace(result, records=result.records * 2).records_complete
    assert not replace(
        result, summary=replace(result.summary, transport_interrupted=True)
    ).records_complete
    assert not replace(result, records=()).records_complete


@pytest.mark.parametrize("method", ["keypad_pin", "fingerprint", "ic_card"])
async def test_administrative_cancellation_propagates(method):
    client = _client([])
    client._inventory_admin_handshake = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await client.get_administrative_inventory(method)
    assert not client._command_lock.locked()


async def test_bad_method_and_private_decode_fail_closed():
    client = _client([])
    with pytest.raises(ValueError, match="Unknown administrative"):
        await client.get_administrative_inventory("fob")
    for wire in (b"secret", _pin(b"12", cursor=0), _pin(b"1234", cursor=0, validity=2)):
        with pytest.raises(ValueError) as error:
            parse_administrative_record("keypad_pin", wire)
        assert "secret" not in str(error.value)
    for method in ("fingerprint", "ic_card", "unknown"):
        with pytest.raises(ValueError):
            parse_administrative_record(method, b"\x07\x01")
    records = []
    client._collect_administrative_record(records, "keypad_pin", b"secret")
    assert not records


def test_schedule_is_observed_not_verified():
    wire = _card(bytes.fromhex("deadbeef"), end=bytes([27, 1, 1, 0, 0]))
    wire = wire[:10] + bytes([26, 1, 1, 0, 0]) + wire[15:]
    record = parse_administrative_record("ic_card", wire)
    assert record.observed_window == ("2026-01-01T00:00:00", "2027-01-01T00:00:00")
    assert not record.schedule_verified


def test_exact_offline_payloads_no_dispatch_no_false_success():
    candidate = pin_modify_candidate(
        "1234", "56789", pwd_type=1, start="2601010000", end="2701010000"
    )
    assert (candidate.opcode, candidate.operation) == (3, 5)
    assert candidate.payload == b"\x05\x01\x041234\x0556789" + bytes(
        [26, 1, 1, 0, 0, 27, 1, 1, 0, 0]
    )
    assert "1234" not in repr(candidate) and "56789" not in repr(candidate)
    assert not candidate.write_enabled and not candidate.hardware_validated
    assert interpret_candidate_response(candidate, b"\x03\x01").stage == ManagementStage.ENVELOPE
    for method, identifier, opcode in [
        ("ic_card", bytes.fromhex("deadbeef"), 5),
        ("fingerprint", bytes.fromhex("cafebabe0003"), 6),
    ]:
        for op, number in [("enrol", 2), ("modify", 5), ("delete", 3)]:
            dates = {} if op == "delete" else {"start": "2601010000", "end": "2701010000"}
            cmd = indexed_management_candidate(method, op, identifier=identifier, **dates)
            assert cmd.payload.startswith(bytes([number]) + identifier)
            assert cmd.opcode == opcode
            assert not cmd.write_enabled and not cmd.hardware_validated
            assert identifier.hex() not in repr(cmd)
            result = interpret_candidate_response(cmd, bytes([opcode, 1, 90, number, 1]))
            assert (
                not result.physical_confirmed
                and not result.retry_allowed
                and result.reconciliation_required
            )
        cmd = indexed_management_candidate(method, "enrol")
        assert cmd.payload == b"\x02"
        for wire, stage in [
            (b"", ManagementStage.UNVERIFIED),
            (b"\x03\x01", ManagementStage.UNVERIFIED),
            (bytes([opcode, 0]), ManagementStage.REJECTED),
            (bytes([opcode, 3]), ManagementStage.UNVERIFIED),
            (bytes([opcode, 1]), ManagementStage.UNVERIFIED),
            (bytes([opcode, 1, 90, 2]), ManagementStage.UNVERIFIED),
            (bytes([opcode, 1, 90, 2, 2]), ManagementStage.ENROLLMENT),
            (bytes([opcode, 1, 90, 2, 1]), ManagementStage.AMBIGUOUS),
        ]:
            assert interpret_candidate_response(cmd, wire).stage == stage
    fp = indexed_management_candidate("fingerprint", "enrol")
    assert (
        interpret_candidate_response(fp, b"\x06\x01\x64\x02\x03").stage == ManagementStage.PROGRESS
    )
    assert (
        interpret_candidate_response(fp, b"\x06\x01\x64\x02\x04").stage == ManagementStage.TEMPLATE
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("secret", "2701010000"),
        ("2699010000", "2701010000"),
        ("2701010000", "2601010000"),
        ("abcdefghij", "2701010000"),
        ("٢٦٠١٠١٠٠٠٠", "2701010000"),
    ],
)
def test_bad_windows_are_fixed_errors_without_input_echo(start, end):
    with pytest.raises(ValueError, match="Invalid management validity window") as error:
        pin_modify_candidate("1234", "5678", pwd_type=1, start=start, end=end)
    assert start not in str(error.value)


def test_bad_management_inputs_do_not_echo_or_enable_writes():
    for method, operation, kwargs in [
        ("fob", "enrol", {}),
        ("ic_card", "clear", {}),
        ("ic_card", "delete", {}),
        ("ic_card", "delete", {"identifier": bytes(8)}),
        ("fingerprint", "modify", {"identifier": bytes(6)}),
        ("ic_card", "delete", {"identifier": bytes(4), "start": "secret"}),
    ]:
        with pytest.raises(ValueError) as error:
            indexed_management_candidate(method, operation, **kwargs)
        assert "secret" not in str(error.value)
    with pytest.raises(ValueError, match="Invalid PIN"):
        pin_modify_candidate("secret", "5678", pwd_type=1, start="2601010000", end="2701010000")
