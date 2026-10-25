"""
Comprehensive integration and security tests for receipt verification, claim processing,
and signing CLI behavior.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.canonical import id32
from backend.app.services.evidence import compute_evidence_commitment
from backend.app.services.invoice_identity import InvoiceLedger
from backend.app.services.signatures import recover_signer, sign_receipt
from backend.app.services.verification import (
    VendorRegistry,
    process_claim,
    verify_receipt,
)
from backend.scripts.sign_receipt import sign_receipt_cli

TEST_PRIV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_SIGNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

TEST_PRIV_KEY_2 = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
TEST_SIGNER_2 = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@pytest.fixture
def domain():
    return EIP712Domain(
        name="TRACE Receipt Registry",
        version="1",
        chain_id=31337,
        verifying_contract="0x1111111111111111111111111111111111111111",
    )


@pytest.fixture
def registry():
    reg = VendorRegistry()
    reg.register_vendor("ACME-DRILLING", TEST_SIGNER)
    reg.register_vendor("VENDOR-TWO", TEST_SIGNER_2)
    return reg


@pytest.fixture
def sample_evidence():
    file_bytes = b"Sample itemized drill pipe receipt"
    salt = b"\x77" * 32
    commitment = compute_evidence_commitment(file_bytes, salt)
    return file_bytes, salt, "0x" + commitment.hex()


@pytest.fixture
def valid_receipt(sample_evidence):
    _, _, commitment_hex = sample_evidence
    return Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment=commitment_hex,
    )


def test_valid_receipt_verification(valid_receipt, domain, registry, sample_evidence):
    """A valid, signed receipt from a registered vendor passes all verification checks."""
    file_bytes, salt, _ = sample_evidence
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        file_bytes=file_bytes,
        salt=salt,
    )

    assert res.status == "VERIFIED"
    assert res.reason is None
    assert res.recovered_signer.lower() == TEST_SIGNER.lower()
    assert res.checks["structure_valid"] is True
    assert res.checks["signature_format_valid"] is True
    assert res.checks["signature_valid"] is True
    assert res.checks["vendor_registered"] is True
    assert res.checks["signer_matches_vendor"] is True
    assert res.checks["category_allowed"] is True
    assert res.checks["timestamp_valid"] is True
    assert res.checks["evidence_verified"] is True


def test_unregistered_vendor_rejected(valid_receipt, domain, registry):
    """A receipt from a vendor not present in the registry is rejected with UNREGISTERED_VENDOR."""
    empty_registry = VendorRegistry()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=empty_registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )

    assert res.status == "REJECTED"
    assert res.reason == "UNREGISTERED_VENDOR"
    assert res.checks["signature_valid"] is True
    assert res.checks["vendor_registered"] is False


def test_signer_vendor_mismatch_rejected(valid_receipt, domain, registry):
    """
    If Vendor B signs a claim presented as Vendor A, signature is cryptographically valid
    for Vendor B, but fails with SIGNER_VENDOR_MISMATCH against Vendor A's registered key.
    """
    # Signed by key 2 (Vendor Two), but receipt claims vendor_id is ACME-DRILLING
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY_2, domain)

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )

    assert res.status == "REJECTED"
    assert res.reason == "SIGNER_VENDOR_MISMATCH"
    assert res.checks["signature_valid"] is True
    assert res.checks["vendor_registered"] is True
    assert res.checks["signer_matches_vendor"] is False


def test_unauthorized_category_rejected(valid_receipt, domain, registry):
    """If project policy only permits FOOD_SUPPLIES, a WATER_INFRASTRUCTURE receipt is rejected."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category=["FOOD_SUPPLIES"],  # Does not include WATER_INFRASTRUCTURE
        now=1714000000,
    )

    assert res.status == "REJECTED"
    assert res.reason == "CATEGORY_NOT_ALLOWED"
    assert res.checks["category_allowed"] is False


def test_future_dated_receipt_rejected(valid_receipt, domain, registry):
    """A receipt timestamped more than 24 hours in the future is rejected with DATED_IN_FUTURE."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # now is 1713000000, issued_at is 1714000000 (100,000 seconds later > 86400)
    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1713000000,
    )

    assert res.status == "REJECTED"
    assert res.reason == "DATED_IN_FUTURE"
    assert res.checks["timestamp_valid"] is False


def test_evidence_mismatch_rejected(valid_receipt, domain, registry):
    """Tampered evidence content fails with EVIDENCE_COMMITMENT_MISMATCH."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)
    wrong_file = b"Completely different invoice file"
    salt = b"\x77" * 32

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        file_bytes=wrong_file,
        salt=salt,
    )

    assert res.status == "REJECTED"
    assert res.reason == "EVIDENCE_COMMITMENT_MISMATCH"
    assert res.checks["evidence_verified"] is False


def test_partial_evidence_fails_closed(valid_receipt, domain, registry):
    """Supplying only file_bytes or only salt must fail closed with MALFORMED_EVIDENCE."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # Only file_bytes
    res1 = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        file_bytes=b"Some content",
        salt=None,
    )
    assert res1.status == "REJECTED"
    assert res1.reason == "MALFORMED_EVIDENCE"

    # Only salt
    res2 = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        file_bytes=None,
        salt=b"\x11" * 32,
    )
    assert res2.status == "REJECTED"
    assert res2.reason == "MALFORMED_EVIDENCE"


def test_optional_evidence_omitted_is_truthfully_recorded(valid_receipt, domain, registry):
    """When evidence is omitted, verification succeeds but evidence_verified remains False."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = verify_receipt(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        file_bytes=None,
        salt=None,
    )

    assert res.status == "VERIFIED"
    assert res.checks["evidence_verified"] is False  # Truthfully not claimed as verified


def test_invalid_structure_rejected(domain, registry):
    """Malformed receipt structure is rejected with MALFORMED_RECEIPT."""
    bad_receipt = {"project_id": "P", "vendor_id": "V"}  # Missing required fields

    res = verify_receipt(
        receipt=bad_receipt,
        signature="0x" + "aa" * 65,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )

    assert res.status == "REJECTED"
    assert res.reason == "MALFORMED_RECEIPT"
    assert res.checks["structure_valid"] is False


def test_fail_closed_on_unexpected_exception(valid_receipt, domain, registry):
    """Any unexpected exception in an internal helper produces REJECTED with INTERNAL_ERROR."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    with patch(
        "backend.app.services.verification.recover_signer",
        side_effect=RuntimeError("Simulated unexpected crash"),
    ):
        res = verify_receipt(
            receipt=valid_receipt,
            signature=sig,
            domain=domain,
            registry=registry,
            allowed_category="WATER_INFRASTRUCTURE",
            now=1714000000,
        )

        assert res.status == "REJECTED"
        assert res.reason == "INTERNAL_ERROR"


def test_process_claim_e2e_success(valid_receipt, domain, registry):
    """process_claim successfully verifies receipt and updates ledger."""
    ledger = InvoiceLedger()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=250000,
        report_id="REPORT-2026-Q1",
    )

    assert res.status == "VERIFIED"
    assert res.claimed_amount == 250000
    assert res.remaining_balance == 250000
    assert ledger.has_nullifier(valid_receipt.invoice_nullifier) is True


def test_process_claim_ledger_rejection_leaves_state_clean(valid_receipt, domain, registry):
    """When a claim fails ledger checks (e.g. claim exceeds total), it returns the exact reason."""
    ledger = InvoiceLedger()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    res = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=999999999,  # Exceeds total
        report_id="REPORT-1",
    )

    assert res.status == "REJECTED"
    assert res.reason == "CLAIM_EXCEEDS_INVOICE_TOTAL"
    assert ledger.has_nullifier(valid_receipt.invoice_nullifier) is False


def test_process_claim_duplicate_report_rejection(valid_receipt, domain, registry):
    """Claiming an invoice under a second report_id is rejected with INVOICE_REUSED_ACROSS_REPORTS."""
    ledger = InvoiceLedger()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # First claim
    res1 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=100000,
        report_id="DONOR-A-REPORT",
    )
    assert res1.status == "VERIFIED"

    # Second claim under different donor report
    res2 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=100000,
        report_id="DONOR-B-REPORT",
    )
    assert res2.status == "REJECTED"
    assert res2.reason == "INVOICE_REUSED_ACROSS_REPORTS"


def test_signing_cli_missing_key_fails_closed():
    """CLI fails closed when private key environment variable is not configured."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        receipt_file = Path(tmp_dir) / "test_receipt.json"
        receipt_data = {
            "project_id": "PROJECT-ALPHA",
            "vendor_id": "ACME-DRILLING",
            "invoice_id": "INV-1042",
            "invoice_total": 500000,
            "currency": "USD",
            "category": "WATER_INFRASTRUCTURE",
            "issued_at": 1714000000,
            "evidence_commitment": "0x" + "aa" * 32,
        }
        receipt_file.write_text(json.dumps(receipt_data), encoding="utf-8")

        # Env var name not present
        exit_code = sign_receipt_cli(
            [str(receipt_file), "--env-var", "NON_EXISTENT_KEY_VAR_XYZ"]
        )
        assert exit_code == 1


def test_signing_cli_valid_execution(monkeypatch):
    """CLI signs receipt and outputs formatted JSON when key is configured via environment."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        receipt_file = Path(tmp_dir) / "test_receipt.json"
        output_file = Path(tmp_dir) / "signed_output.json"

        receipt_data = {
            "project_id": "PROJECT-ALPHA",
            "vendor_id": "ACME-DRILLING",
            "invoice_id": "INV-1042",
            "invoice_total": 500000,
            "currency": "USD",
            "category": "WATER_INFRASTRUCTURE",
            "issued_at": 1714000000,
            "evidence_commitment": "0x" + "aa" * 32,
        }
        receipt_file.write_text(json.dumps(receipt_data), encoding="utf-8")

        monkeypatch.setenv("TEST_CLI_SECRET_KEY", TEST_PRIV_KEY)

        exit_code = sign_receipt_cli(
            [
                str(receipt_file),
                "--env-var",
                "TEST_CLI_SECRET_KEY",
                "--output",
                str(output_file),
            ]
        )
        assert exit_code == 0
        assert output_file.is_file()

        with open(output_file, "r", encoding="utf-8") as f:
            signed_data = json.load(f)

        assert signed_data["status"] == "SIGNED"
        assert signed_data["recovered_signer"].lower() == TEST_SIGNER.lower()
        assert signed_data["signature"].startswith("0x")


def test_generated_test_vectors_validation():
    """Validates all test vectors in docs/test-vectors/phase1.json."""
    vector_file = Path(__file__).resolve().parent.parent.parent / "docs" / "test-vectors" / "phase1.json"
    assert vector_file.is_file()

    with open(vector_file, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    vectors = bundle["vectors"]
    assert len(vectors) >= 4

    for vec in vectors:
        raw = vec["raw_input"]
        rec = Receipt(**raw, evidence_commitment=vec["canonical_receipt"]["evidence_commitment"])
        dom = EIP712Domain(**vec["domain"])

        # Validate bytes32 encodings
        assert "0x" + rec.project_id_bytes32.hex() == vec["bytes32_encodings"]["projectId"]
        assert "0x" + rec.vendor_id_bytes32.hex() == vec["bytes32_encodings"]["vendorId"]
        assert "0x" + rec.invoice_id_bytes32.hex() == vec["bytes32_encodings"]["invoiceId"]
        assert "0x" + rec.currency_bytes32.hex() == vec["bytes32_encodings"]["currency"]
        assert "0x" + rec.category_bytes32.hex() == vec["bytes32_encodings"]["category"]

        # Validate nullifier
        assert rec.invoice_nullifier_hex == vec["invoice_nullifier"]

        # Validate signature recovery
        recovered = recover_signer(rec, vec["signature"], dom)
        assert recovered.lower() == vec["recovered_signer"].lower()

        # Validate evidence
        ev = vec["evidence"]
        file_bytes = ev["file_text"].encode("utf-8")
        salt_bytes = bytes.fromhex(ev["salt"][2:])
        calculated_comm = compute_evidence_commitment(file_bytes, salt_bytes)
        assert "0x" + calculated_comm.hex() == ev["commitment"]
