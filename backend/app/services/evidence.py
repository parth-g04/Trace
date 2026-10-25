"""
Evidence commitment and verification service for TRACE.

Computes privacy-preserving commitments binding off-chain documents to on-chain
receipt records without publishing sensitive beneficiary or vendor invoice data.
"""
import hashlib
import hmac
import secrets
from typing import Union
import eth_abi
from eth_utils import keccak

from backend.app.services.canonical import validate_bytes32


def generate_salt() -> bytes:
    """Generates a cryptographically secure 32-byte salt."""
    return secrets.token_bytes(32)


def compute_evidence_commitment(file_bytes: bytes, salt: bytes) -> bytes:
    """
    Computes evidence commitment:
    commitment = keccak256(abi.encode(bytes32 salt, bytes32 sha256(file_bytes)))

    CRITICAL PROPERTIES:
    1. Standard ABI encoding (eth_abi.encode) of two bytes32 values.
    2. Salt must be exactly 32 bytes.
    3. File contents are hashed with SHA-256 before ABI encoding with salt.
    4. Provides cryptographic binding to the document content and salt.
       Does NOT prove physical delivery of goods or real-world authenticity.
    """
    if not isinstance(file_bytes, (bytes, bytearray)):
        raise TypeError(
            f"file_bytes must be bytes or bytearray, got {type(file_bytes).__name__}"
        )
    if not isinstance(salt, bytes):
        raise TypeError(f"salt must be bytes, got {type(salt).__name__}")
    if len(salt) != 32:
        raise ValueError(f"salt must be exactly 32 bytes, got {len(salt)} bytes")

    sha256_digest = hashlib.sha256(file_bytes).digest()
    encoded = eth_abi.encode(["bytes32", "bytes32"], [salt, sha256_digest])
    return keccak(encoded)


def verify_evidence(
    file_bytes: bytes,
    salt: bytes,
    expected_commitment: Union[bytes, str],
) -> bool:
    """
    Verifies that the provided file_bytes and salt produce the expected commitment.
    Uses constant-time comparison to prevent timing side-channels.
    """
    try:
        expected_bytes = validate_bytes32(expected_commitment)
        actual_bytes = compute_evidence_commitment(file_bytes, salt)
        return hmac.compare_digest(actual_bytes, expected_bytes)
    except Exception:
        return False
