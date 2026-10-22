"""Offline protocol candidates only; no transport or enabled write dispatcher.

Payload facts: kind3r/ttlock-sdk-js 8c84cda (GPL, protocol reference only),
and existing MIT keyboard envelope handling. Independent Python implementation.
S31 write authentication, acknowledgement and recovery need hardware evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .encoding import decimal_time_bytes, decode_date5


@dataclass(frozen=True, slots=True)
class OfflineManagementCommand:
    """Sensitive offline fixture. It does not authorize or execute anything."""

    opcode: int
    operation: int
    payload: bytes = field(repr=False)
    hardware_validated: bool = False
    write_enabled: bool = False
    authentication: str = "write_session_contract_unverified"


class ManagementStage(StrEnum):
    """An envelope/progress response never proves a physically confirmed result."""

    REJECTED = "rejected"
    UNVERIFIED = "unverified_response"
    ENVELOPE = "envelope_ack_only"
    ENROLLMENT = "enrollment_mode"
    PROGRESS = "enrollment_progress"
    TEMPLATE = "template_requested"
    AMBIGUOUS = "ambiguous_requires_read_reconciliation"


@dataclass(frozen=True, slots=True)
class ManagementOutcome:
    """No implicit retry, rollback, replacement credential or physical success."""

    stage: ManagementStage
    physical_confirmed: bool = False
    retry_allowed: bool = False
    reconciliation_required: bool = True


def _window(start: str, end: str) -> bytes:
    if len(start) != 10 or len(end) != 10 or not start.isascii() or not end.isascii():
        raise ValueError("Invalid management validity window")
    try:
        raw = decimal_time_bytes(start) + decimal_time_bytes(end)
        first, last = decode_date5(raw[:5]), decode_date5(raw[5:])
    except (ValueError, TypeError):
        raise ValueError("Invalid management validity window") from None
    if first is None or last is None or first >= last:
        raise ValueError("Invalid management validity window")
    return raw


def pin_modify_candidate(
    old: str, new: str, *, pwd_type: int, start: str, end: str
) -> OfflineManagementCommand:
    """Single opcode 03/05 candidate; never emulate modification with delete/add."""
    if pwd_type not in {1, 3} or not all(
        4 <= len(v) <= 9 and v.isascii() and v.isdigit() for v in (old, new)
    ):
        raise ValueError("Invalid PIN modification input")
    payload = bytes([5, pwd_type, len(old)]) + old.encode("ascii")
    payload += bytes([len(new)]) + new.encode("ascii") + _window(start, end)
    return OfflineManagementCommand(3, 5, payload)


def indexed_management_candidate(
    method: str,
    operation: str,
    *,
    identifier: bytes | None = None,
    start: str | None = None,
    end: str | None = None,
) -> OfflineManagementCommand:
    """Four-byte card / six-byte composite fingerprint candidates, kept offline."""
    if method not in {"ic_card", "fingerprint"} or operation not in {"enrol", "modify", "delete"}:
        raise ValueError("Unsupported management candidate")
    op = {"enrol": 2, "modify": 5, "delete": 3}[operation]
    opcode, size = (5, 4) if method == "ic_card" else (6, 6)
    if operation == "enrol" and identifier is None and start is None and end is None:
        return OfflineManagementCommand(opcode, op, bytes([op]))
    if identifier is None or len(identifier) != size:
        raise ValueError("Invalid management identifier")
    payload = bytes([op]) + identifier
    if operation != "delete":
        if start is None or end is None:
            raise ValueError("Management validity window required")
        payload += _window(start, end)
    elif start is not None or end is not None:
        raise ValueError("Deletion has no validity window")
    return OfflineManagementCommand(opcode, op, payload)


def interpret_candidate_response(
    candidate: OfflineManagementCommand, plaintext: bytes
) -> ManagementOutcome:
    """Classify only known envelope/progress facts; never declare write success."""
    stage = ManagementStage.UNVERIFIED
    if len(plaintext) >= 2 and plaintext[0] == candidate.opcode:
        if plaintext[1] == 0:
            stage = ManagementStage.REJECTED
        elif plaintext[1] == 1:
            stage = _success_envelope_stage(candidate, plaintext[2:])
    return ManagementOutcome(stage)


def _success_envelope_stage(candidate: OfflineManagementCommand, data: bytes) -> ManagementStage:
    if candidate.opcode == 3:
        return ManagementStage.ENVELOPE
    if len(data) < 2 or data[1] != candidate.operation:
        return ManagementStage.UNVERIFIED
    if candidate.operation != 2:
        return ManagementStage.ENVELOPE
    if len(data) < 3:
        return ManagementStage.UNVERIFIED
    stages = {2: ManagementStage.ENROLLMENT}
    if candidate.opcode == 6:
        stages.update({3: ManagementStage.PROGRESS, 4: ManagementStage.TEMPLATE})
    # An unknown status is not success or a retry instruction.
    return stages.get(data[2], ManagementStage.AMBIGUOUS)
