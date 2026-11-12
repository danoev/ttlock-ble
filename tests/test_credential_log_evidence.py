"""Synthetic fixtures only: positive evidence never guesses wire width or method."""

import pytest

from ttlock_ble.commands.operate_log import parse_operate_log_response


def _page(record_type: int, tail: bytes) -> bytes:
    record = bytes([record_type, 26, 5, 11, 14, 23, 7, 90]) + tail
    return (
        b"\x25\x01"
        + (len(record) + 5).to_bytes(2, "big")
        + b"\x00\x05"
        + bytes([len(record)])
        + record
    )


@pytest.mark.parametrize(
    ("record_type", "wire", "evidence"),
    [
        (20, b"\x00\x13\x24\x35\x46\x07", b"\x00\x13\x24\x35\x46\x07"),
        (20, b"\x07\x46\x35\x24\x13\x00", b"\x07\x46\x35\x24\x13\x00"),
        (17, b"\x00\x12\x23\x34", b"\x00\x12\x23\x34"),
        (4, b"\x06004831\x00", b"004831"),
        (4, b"\x06004831", None),
        (4, b"\x06004831\x014", None),
        (4, b"\x0600\xff831\x00", None),
        (4, b"\x07004831\x00", None),
        (7, b"\x06004831\x00", None),
        (17, b"\x00\x00\x00\x00\x00\x12\x23\x34", None),
        (17, b"\x12\x23\x34", None),
        (20, b"\x00\x13\x24\x35\x46", None),
        (20, b"\x00\x13\x24\x35\x46\x07\x00", None),
        (21, b"\x00\x13\x24\x35\x46\x07", None),
    ],
)
def test_credential_evidence_is_exact_and_not_in_repr(record_type, wire, evidence):
    entries, _ = parse_operate_log_response(_page(record_type, wire), strict=True)
    record = entries[0]
    assert record.credential_identifier == evidence
    assert "password=" not in repr(record)
    assert "credential_identifier=" not in repr(record)
    assert "004831" not in repr(record)


@pytest.mark.parametrize(
    "frame",
    [
        b"\x24" + _page(4, b"\x06004831\x00")[1:],
        b"\x25\x00\x00\x00",
        b"\x25\x01\x00\x00\x01",
        _page(4, b"\x06004831\x00")[:-1],
        b"\x25\x01\x00\x05\x00\x01\x01\x04",
    ],
)
def test_strict_log_read_never_treats_malformed_page_as_complete(frame):
    with pytest.raises(ValueError, match="Operation log") as error:
        parse_operate_log_response(frame, strict=True)
    assert "004831" not in str(error.value)
