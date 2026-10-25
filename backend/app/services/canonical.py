"""
Canonical text normalization and field validation services for TRACE.

Enforces strict canonical representation rules for identifiers, monetary amounts,
currencies, categories, and timestamps to prevent collision attacks and evasion.
"""
import re
import unicodedata
from typing import Any, Sequence
from eth_utils import keccak

ALLOWED_CATEGORIES: Sequence[str] = (
    "WATER_INFRASTRUCTURE",
    "FOOD_SUPPLIES",
    "MEDICAL_SUPPLIES",
    "EDUCATION",
    "ADMINISTRATION",
)

UINT256_MAX = (1 << 256) - 1
UINT64_MAX = (1 << 64) - 1


def normalize_text(text: Any) -> str:
    """
    Applies Unicode NFKC normalization, whitespace trimming, uppercase conversion,
    and fail-closed ASCII enforcement.
    """
    if not isinstance(text, str):
        raise ValueError(f"Expected string input, got {type(text).__name__}")
    if isinstance(text, bool):
        raise ValueError("Boolean values are not valid strings")

    normalized = unicodedata.normalize("NFKC", text).strip().upper()
    if not normalized.isascii():
        raise ValueError(
            f"Input contains non-ASCII characters after NFKC normalization: {text!r}"
        )
    return normalized


def normalize_identifier(text: Any) -> str:
    """
    Normalizes a general identifier (project_id, vendor_id).
    
    1. Unicode NFKC normalization, trim, uppercase, ASCII verification.
    2. Strips all characters outside [A-Z0-9].
    3. Rejects empty results.
    """
    s = normalize_text(text)
    s = re.sub(r"[^A-Z0-9]", "", s)
    if not s:
        raise ValueError(f"Identifier is empty after normalization: {text!r}")
    return s


def normalize_invoice_id(text: Any) -> str:
    """
    Normalizes an invoice identifier.
    
    1. Unicode NFKC normalization, trim, uppercase, ASCII verification.
    2. Strips all characters outside [A-Z0-9].
    3. Strips leading zeros from each digit run.
    4. Rejects empty results.

    Collision Risk Note:
    Removing punctuation and leading zeros collapses distinct identifiers
    (e.g., 'INV-1042', 'inv 1042', 'INV1042', and 'INV-001042') into the same
    canonical value. This intentional policy prevents duplicate claims across
    formatting variations, but vendors must avoid ambiguous numbering schemes.
    """
    s = normalize_text(text)
    s = re.sub(r"[^A-Z0-9]", "", s)
    # Remove leading zeros from each digit run:
    # (?<!\d) ensures we are at the start of a digit run
    # 0+ matches leading zeros
    # (?=\d) ensures we don't remove the last zero if the digit run is all zeros (e.g., '0' remains '0')
    s = re.sub(r"(?<!\d)0+(?=\d)", "", s)
    if not s:
        raise ValueError(f"Invoice ID is empty after normalization: {text!r}")
    return s


def normalize_currency(text: Any) -> str:
    """
    Normalizes currency codes.
    Requires exactly three ASCII alphabetic characters (e.g., 'USD', 'EUR', 'INR').
    """
    s = normalize_text(text)
    if len(s) != 3 or not s.isalpha() or not s.isascii():
        raise ValueError(
            f"Currency must be exactly 3 ASCII alphabetic characters, got {text!r}"
        )
    return s


def normalize_category(text: Any) -> str:
    """
    Normalizes expenditure categories against the locked allowed enumeration.
    """
    s = normalize_text(text)
    if s not in ALLOWED_CATEGORIES:
        raise ValueError(
            f"Category {text!r} (normalized: {s!r}) is not allowed. "
            f"Must be one of: {list(ALLOWED_CATEGORIES)}"
        )
    return s


def validate_monetary_value(v: Any) -> int:
    """
    Validates monetary values.
    
    Accepts:
    - Non-boolean Python integers.
    - Strings containing ASCII decimal digits only.
    
    Requires:
    1 <= value <= 2^256 - 1
    
    Rejects:
    - Booleans (True / False).
    - Floating point values (including 100.0).
    - Zero or negative values.
    - Scientific notation (e.g., '1e5').
    - Strings with whitespace, separators, signs, or decimal points.
    """
    if isinstance(v, bool):
        raise ValueError(f"Monetary value cannot be a boolean: {v!r}")

    if isinstance(v, int):
        val = v
    elif isinstance(v, str):
        if not v.isascii() or not v.isdigit():
            raise ValueError(
                f"Monetary value string must contain only ASCII decimal digits, got {v!r}"
            )
        val = int(v)
    else:
        raise ValueError(
            f"Monetary value must be an int or digit string, got {type(v).__name__}"
        )

    if val < 1 or val > UINT256_MAX:
        raise ValueError(
            f"Monetary value must satisfy 1 <= value <= 2^256 - 1, got {val}"
        )
    return val


def validate_timestamp(v: Any) -> int:
    """
    Validates Unix timestamps.
    
    Requires:
    - Integer Unix timestamp in seconds.
    - 0 < issued_at < 2^64.
    
    Rejects booleans, floats, strings, zero, negatives, and out-of-range values.
    """
    if isinstance(v, bool):
        raise ValueError(f"Timestamp cannot be a boolean: {v!r}")
    if not isinstance(v, int):
        raise ValueError(
            f"Timestamp must be an integer, got {type(v).__name__} ({v!r})"
        )
    if v <= 0 or v > UINT64_MAX:
        raise ValueError(f"Timestamp must satisfy 0 < issued_at < 2^64, got {v}")
    return v


def validate_bytes32(v: Any) -> bytes:
    """
    Validates a 32-byte field. Accepts raw 32 bytes or 0x-prefixed 64-hex strings.
    Returns 32 bytes.
    """
    if isinstance(v, bytes):
        if len(v) != 32:
            raise ValueError(f"Expected 32 bytes, got {len(v)} bytes")
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith(("0x", "0X")):
            s = s[2:]
        if len(s) != 64:
            raise ValueError(
                f"Expected 64 hex characters (32 bytes), got {len(s)}: {v!r}"
            )
        try:
            b = bytes.fromhex(s)
            return b
        except ValueError as e:
            raise ValueError(f"Invalid hex string for bytes32: {v!r} ({e})") from e

    raise ValueError(
        f"Expected bytes or hex string for bytes32, got {type(v).__name__}"
    )


def id32(x: str) -> bytes:
    """
    Computes id32(x) = keccak256(UTF8(canonical_x)).
    Returns exactly 32 bytes.
    """
    if not isinstance(x, str):
        raise ValueError(f"id32 input must be a string, got {type(x).__name__}")
    return keccak(x.encode("utf-8"))


def id32_hex(x: str) -> str:
    """
    Computes 0x-prefixed 64-hex string representation of id32(x).
    """
    return "0x" + id32(x).hex()
