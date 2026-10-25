"""
Comprehensive tests for off-chain evidence commitments.
"""
import pytest
from backend.app.services.evidence import (
    compute_evidence_commitment,
    generate_salt,
    verify_evidence,
)


def test_evidence_commitment_success():
    """Correct file and salt validate against the generated commitment."""
    file_bytes = b"%PDF-1.4 Invoice for solar water pump installation"
    salt = generate_salt()
    assert len(salt) == 32

    commitment = compute_evidence_commitment(file_bytes, salt)
    assert len(commitment) == 32

    assert verify_evidence(file_bytes, salt, commitment) is True
    assert verify_evidence(file_bytes, salt, "0x" + commitment.hex()) is True


def test_wrong_file_fails():
    """Tampered file content fails verification."""
    original_file = b"Valid invoice: 100 pipes delivered"
    tampered_file = b"Valid invoice: 1000 pipes delivered"
    salt = generate_salt()

    commitment = compute_evidence_commitment(original_file, salt)
    assert verify_evidence(tampered_file, salt, commitment) is False


def test_wrong_salt_fails():
    """Mismatched salt fails verification."""
    file_bytes = b"Sample receipt content"
    salt1 = generate_salt()
    salt2 = generate_salt()

    commitment = compute_evidence_commitment(file_bytes, salt1)
    assert verify_evidence(file_bytes, salt2, commitment) is False


def test_invalid_salt_length_rejected():
    """Salt must be exactly 32 bytes."""
    file_bytes = b"Document content"
    for bad_salt in [b"", b"short_salt", b"\x00" * 31, b"\x00" * 33]:
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            compute_evidence_commitment(file_bytes, bad_salt)


def test_different_salts_produce_different_commitments():
    """Different salts for the exact same file produce completely distinct commitments."""
    file_bytes = b"Static report document"
    salt1 = b"\x01" * 32
    salt2 = b"\x02" * 32

    c1 = compute_evidence_commitment(file_bytes, salt1)
    c2 = compute_evidence_commitment(file_bytes, salt2)
    assert c1 != c2


def test_different_files_produce_different_commitments():
    """Different files for the same salt produce distinct commitments."""
    salt = b"\x05" * 32
    file1 = b"Report Version 1"
    file2 = b"Report Version 2"

    c1 = compute_evidence_commitment(file1, salt)
    c2 = compute_evidence_commitment(file2, salt)
    assert c1 != c2


def test_invalid_input_types():
    """Non-bytes inputs are rejected with TypeError."""
    with pytest.raises(TypeError):
        compute_evidence_commitment("string_not_bytes", b"\x01" * 32)

    with pytest.raises(TypeError):
        compute_evidence_commitment(b"valid_bytes", "salt_as_string")
