"""
Comprehensive unit tests for canonical text normalization and field validation.
"""
import pytest
from backend.app.services.canonical import (
    ALLOWED_CATEGORIES,
    id32,
    id32_hex,
    normalize_category,
    normalize_currency,
    normalize_identifier,
    normalize_invoice_id,
    normalize_text,
    validate_bytes32,
    validate_monetary_value,
    validate_timestamp,
)


def test_invoice_normalization_equivalences():
    """INV-1042, inv 1042, INV1042, and INV-001042 must normalize identically to INV1042."""
    expected = "INV1042"
    assert normalize_invoice_id("INV-1042") == expected
    assert normalize_invoice_id("inv 1042") == expected
    assert normalize_invoice_id("INV1042") == expected
    assert normalize_invoice_id("INV-001042") == expected


def test_invoice_normalization_digit_runs():
    """Leading zeros in each distinct digit run are stripped, while leaving single zeros."""
    assert normalize_invoice_id("INV-0") == "INV0"
    assert normalize_invoice_id("INV-00") == "INV0"
    assert normalize_invoice_id("INV-000") == "INV0"
    assert normalize_invoice_id("INV-007-009") == "INV7009"  # non-alnum stripped -> INV007009 -> INV7009
    assert normalize_invoice_id("BATCH001A002") == "BATCH1A2"


def test_vendor_identifier_distinctness():
    """Different vendor identifiers must remain distinct and punctuation stripped."""
    assert normalize_identifier("VENDOR-A") == "VENDORA"
    assert normalize_identifier("VENDOR-B") == "VENDORB"
    assert normalize_identifier("VENDOR-A") != normalize_identifier("VENDOR-B")
    assert normalize_identifier("  acme drilling corp  ") == "ACMEDRILLINGCORP"


def test_unicode_nfkc_normalization():
    """Fullwidth ASCII characters are normalized to standard ASCII."""
    # Fullwidth Latin letters ＩＮＶ-１０４２
    fullwidth = "\uff29\uff2e\uff36-\uff11\uff10\uff14\uff12"
    assert normalize_invoice_id(fullwidth) == "INV1042"


def test_non_ascii_homoglyph_rejection():
    """Cyrillic or other non-ASCII homoglyphs must be rejected fail-closed."""
    # Cyrillic 'А' (U+0410) instead of Latin 'A' (U+0041)
    cyrillic_a = "\u0410CME-VENDOR"
    with pytest.raises(ValueError, match="non-ASCII"):
        normalize_identifier(cyrillic_a)

    with pytest.raises(ValueError, match="non-ASCII"):
        normalize_invoice_id("INV-\u041e")  # Cyrillic O


def test_empty_identifiers_rejected():
    """Empty strings, whitespace-only, or punctuation-only strings must be rejected."""
    for empty_val in ["", "   ", "---", "___", "\t\n", "!@#$%"]:
        with pytest.raises(ValueError):
            normalize_identifier(empty_val)
        with pytest.raises(ValueError):
            normalize_invoice_id(empty_val)


def test_currency_validation():
    """Currency must be exactly 3 ASCII alphabetic characters and uppercase."""
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("EUR") == "EUR"
    assert normalize_currency("  inr  ") == "INR"

    for invalid in ["US", "USDD", "U$D", "123", "US1", "", "   ", "US\u0410"]:
        with pytest.raises(ValueError):
            normalize_currency(invalid)


def test_category_validation():
    """Allowed categories must match exact enumeration; all others rejected."""
    for cat in ALLOWED_CATEGORIES:
        assert normalize_category(cat) == cat
        assert normalize_category(cat.lower()) == cat

    for invalid in [
        "WEAPONS",
        "PERSONAL_EXPENSES",
        "CRYPTO_PURCHASE",
        "UNKNOWN",
        "",
        "water infrastructure",  # has space instead of underscore
    ]:
        with pytest.raises(ValueError):
            normalize_category(invalid)


def test_monetary_value_validation():
    """Monetary values must be integer or digit-only string satisfying 1 <= v <= 2^256-1."""
    assert validate_monetary_value(1) == 1
    assert validate_monetary_value(50000) == 50000
    assert validate_monetary_value("50000") == 50000
    assert validate_monetary_value((1 << 256) - 1) == (1 << 256) - 1

    # Rejected cases
    invalid_cases = [
        True,
        False,
        0,
        -1,
        -500,
        100.0,
        100.5,
        "100.0",
        "1e5",
        " 100",
        "100 ",
        "+100",
        "-100",
        "1,000",
        "",
        "   ",
        (1 << 256),  # overflow uint256
        None,
        [],
    ]
    for case in invalid_cases:
        with pytest.raises(ValueError):
            validate_monetary_value(case)


def test_timestamp_validation():
    """Timestamp must be an integer in 0 < ts < 2^64."""
    assert validate_timestamp(1714000000) == 1714000000
    assert validate_timestamp(1) == 1
    assert validate_timestamp((1 << 64) - 1) == (1 << 64) - 1

    invalid_timestamps = [
        0,
        -1,
        -1714000000,
        True,
        False,
        1714000000.5,
        "1714000000",
        (1 << 64),
        None,
    ]
    for case in invalid_timestamps:
        with pytest.raises(ValueError):
            validate_timestamp(case)


def test_bytes32_validation():
    """Bytes32 must be 32 bytes or 0x-prefixed 64 hex characters."""
    raw_bytes = b"\x11" * 32
    hex_str = "0x" + "11" * 32
    assert validate_bytes32(raw_bytes) == raw_bytes
    assert validate_bytes32(hex_str) == raw_bytes
    assert validate_bytes32("11" * 32) == raw_bytes

    invalid_cases = [
        b"\x11" * 31,
        b"\x11" * 33,
        "0x" + "11" * 31,
        "0x" + "11" * 33,
        "0x" + "zz" * 32,
        12345,
        None,
    ]
    for case in invalid_cases:
        with pytest.raises(ValueError):
            validate_bytes32(case)


def test_id32_hashing():
    """id32 produces keccak256 hash of UTF-8 canonical string."""
    h = id32("INV1042")
    assert isinstance(h, bytes)
    assert len(h) == 32
    assert id32_hex("INV1042").startswith("0x")
    assert len(id32_hex("INV1042")) == 66
