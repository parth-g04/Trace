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
from backend.app.services.signatures import (
    SECP256K1_HALF_N,
    SECP256K1_N,
    ZERO_ADDRESS,
    recover_signer,
    sign_receipt,
)
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


def test_wrong_key_forgery_rejected(valid_receipt, domain, registry):
    """
    An attacker signing with an unauthorized key (TEST_PRIV_KEY_2) forging a claim
    for ACME-DRILLING is rejected with SIGNER_VENDOR_MISMATCH in both verify_receipt
    and process_claim, leaving ledger unchanged.
    """
    ledger = InvoiceLedger()
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

    claim_res = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=100000,
        report_id="REPORT-FORGERY",
    )
    assert claim_res.status == "REJECTED"
    assert claim_res.reason == "SIGNER_VENDOR_MISMATCH"
    assert ledger.has_nullifier(valid_receipt.invoice_nullifier) is False
    assert ledger.record_count() == 0


@pytest.mark.parametrize(
    "tamper_field,tamper_value,expected_reason",
    [
        ("project_id", "PROJECT-BETA", "SIGNER_VENDOR_MISMATCH"),
        ("vendor_id", "MALICIOUS-VENDOR", "UNREGISTERED_VENDOR"),
        ("invoice_id", "INV-9999", "SIGNER_VENDOR_MISMATCH"),
        ("invoice_total", 999999, "SIGNER_VENDOR_MISMATCH"),
        ("currency", "EUR", "SIGNER_VENDOR_MISMATCH"),
        ("category", "FOOD_SUPPLIES", "SIGNER_VENDOR_MISMATCH"),
        ("issued_at", 1714000001, "SIGNER_VENDOR_MISMATCH"),
        ("evidence_commitment", "0x" + "bb" * 32, "SIGNER_VENDOR_MISMATCH"),
    ],
)
def test_all_signed_fields_tamper_evident_in_verification(
    valid_receipt, domain, registry, tamper_field, tamper_value, expected_reason
):
    """
    Every signed field is tamper-evident:
    Assert exact status and reason code in verify_receipt AND process_claim,
    and confirm that failed verification leaves ledger state completely unchanged.
    """
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)
    ledger = InvoiceLedger()

    data = valid_receipt.to_dict()
    data[tamper_field] = tamper_value
    tampered_receipt = Receipt(**data)

    # 1. verify_receipt check
    res = verify_receipt(
        receipt=tampered_receipt,
        signature=valid_sig,
        domain=domain,
        registry=registry,
        allowed_category=["WATER_INFRASTRUCTURE", "FOOD_SUPPLIES"],
        now=1714000000,
    )
    assert res.status == "REJECTED"
    assert res.reason == expected_reason

    # 2. process_claim check
    claim_res = process_claim(
        receipt=tampered_receipt,
        signature=valid_sig,
        domain=domain,
        registry=registry,
        allowed_category=["WATER_INFRASTRUCTURE", "FOOD_SUPPLIES"],
        now=1714000000,
        ledger=ledger,
        claim_amount=100000,
        report_id="REPORT-TEST",
    )
    assert claim_res.status == "REJECTED"
    assert claim_res.reason == expected_reason

    # 3. Ledger is completely untouched
    assert ledger.has_nullifier(tampered_receipt.invoice_nullifier) is False
    assert ledger.has_nullifier(valid_receipt.invoice_nullifier) is False
    assert ledger.record_count() == 0


def test_zero_address_recovery_rejected_in_verification(valid_receipt, domain, registry):
    """Signer recovery resulting in zero address fails verification closed and touches no ledger."""
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)
    ledger = InvoiceLedger()

    with patch(
        "backend.app.services.signatures.Account.recover_message",
        return_value=ZERO_ADDRESS,
    ):
        res = verify_receipt(
            receipt=valid_receipt,
            signature=valid_sig,
            domain=domain,
            registry=registry,
            allowed_category="WATER_INFRASTRUCTURE",
            now=1714000000,
        )
        assert res.status == "REJECTED"
        assert res.reason == "SIGNATURE_INVALID"

        claim_res = process_claim(
            receipt=valid_receipt,
            signature=valid_sig,
            domain=domain,
            registry=registry,
            allowed_category="WATER_INFRASTRUCTURE",
            now=1714000000,
            ledger=ledger,
            claim_amount=100000,
            report_id="REPORT-TEST",
        )
        assert claim_res.status == "REJECTED"
        assert claim_res.reason == "SIGNATURE_INVALID"
        assert ledger.record_count() == 0


def test_malleated_signature_rejected_in_verification(valid_receipt, domain, registry):
    """
    A high-s malleated signature is rejected by verify_receipt and process_claim
    with MALFORMED_SIGNATURE, leaving ledger untouched.
    """
    valid_sig_hex = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)
    valid_sig_bytes = bytes.fromhex(valid_sig_hex[2:])

    s = int.from_bytes(valid_sig_bytes[32:64], "big")
    v = valid_sig_bytes[64]
    high_s = SECP256K1_N - s
    malleated_v = 28 if v == 27 else 27
    malleated_sig = "0x" + (valid_sig_bytes[:32] + high_s.to_bytes(32, "big") + bytes([malleated_v])).hex()

    ledger = InvoiceLedger()

    res = verify_receipt(
        receipt=valid_receipt,
        signature=malleated_sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res.status == "REJECTED"
    assert res.reason == "MALFORMED_SIGNATURE"
    assert res.checks["signature_format_valid"] is False

    claim_res = process_claim(
        receipt=valid_receipt,
        signature=malleated_sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=100000,
        report_id="REPORT-MALLEATE",
    )
    assert claim_res.status == "REJECTED"
    assert claim_res.reason == "MALFORMED_SIGNATURE"
    assert ledger.record_count() == 0


def test_duplicate_invoice_different_evidence_rejected(domain, registry):
    """
    A validly signed duplicate invoice presenting a different evidence commitment
    under a second report ID must be rejected with INVOICE_REUSED_ACROSS_REPORTS,
    and must not mutate the existing ledger record.
    """
    ledger = InvoiceLedger()

    receipt1 = Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "11" * 32,
    )
    sig1 = sign_receipt(receipt1, TEST_PRIV_KEY, domain)

    # First claim succeeds under REPORT-1
    res1 = process_claim(
        receipt=receipt1,
        signature=sig1,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=200000,
        report_id="REPORT-1",
    )
    assert res1.status == "VERIFIED"
    assert res1.claimed_amount == 200000

    # Receipt 2: Same vendor, same invoice (using formatting variant INV-001042),
    # but DIFFERENT evidence commitment and different project
    receipt2 = Receipt(
        project_id="PROJECT-BETA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-001042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "22" * 32,
    )
    sig2 = sign_receipt(receipt2, TEST_PRIV_KEY, domain)

    # Prove nullifiers are identical
    assert receipt1.invoice_nullifier == receipt2.invoice_nullifier

    # Claim under REPORT-2
    res2 = process_claim(
        receipt=receipt2,
        signature=sig2,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=150000,
        report_id="REPORT-2",
    )
    assert res2.status == "REJECTED"
    assert res2.reason == "INVOICE_REUSED_ACROSS_REPORTS"

    # Verify ledger state is pristine: original claim amount remains 200000, report remains REPORT-1
    rec = ledger.get_record(receipt1.invoice_nullifier)
    assert rec is not None
    assert rec.claimed == 200000
    assert rec.report_id == "REPORT-1"


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


def test_process_claim_cumulative_exceeds_invoice_total_rejected(valid_receipt, domain, registry):
    """
    Section C1: Through process_claim, claim 300000 then 300000 on a 500000 invoice in SAME report.
    Second claim is rejected with CLAIM_EXCEEDS_INVOICE_TOTAL, and ledger claimed stays 300000.
    """
    ledger = InvoiceLedger()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # First claim: 300000
    res1 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=300000,
        report_id="REPORT-SAME",
    )
    assert res1.status == "VERIFIED"
    assert res1.claimed_amount == 300000
    assert res1.remaining_balance == 200000

    rec1 = ledger.get_record(valid_receipt.invoice_nullifier)
    assert rec1 is not None
    assert rec1.claimed == 300000

    # Second claim: 300000 on same report
    res2 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=300000,
        report_id="REPORT-SAME",
    )
    assert res2.status == "REJECTED"
    assert res2.reason == "CLAIM_EXCEEDS_INVOICE_TOTAL"

    # Crucial ledger state check: claimed remains 300000
    rec2 = ledger.get_record(valid_receipt.invoice_nullifier)
    assert rec2 is not None
    assert rec2.claimed == 300000
    assert rec2.report_id == "REPORT-SAME"


def test_process_claim_fully_claimed_invoice_rejected(valid_receipt, domain, registry):
    """
    Section C2: Through process_claim, invoice fully claimed (500000 of 500000), then one more
    unit (1) is rejected with INVOICE_ALREADY_FULLY_CLAIMED, leaving ledger unchanged.
    """
    ledger = InvoiceLedger()
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # Claim full 500000
    res1 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=500000,
        report_id="REPORT-FULL",
    )
    assert res1.status == "VERIFIED"
    assert res1.claimed_amount == 500000
    assert res1.remaining_balance == 0

    rec1 = ledger.get_record(valid_receipt.invoice_nullifier)
    assert rec1.claimed == 500000

    # Attempt one more unit (1 minor unit)
    res2 = process_claim(
        receipt=valid_receipt,
        signature=sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=1,
        report_id="REPORT-FULL",
    )
    assert res2.status == "REJECTED"
    assert res2.reason == "INVOICE_ALREADY_FULLY_CLAIMED"

    # Ledger state unchanged
    rec2 = ledger.get_record(valid_receipt.invoice_nullifier)
    assert rec2.claimed == 500000
    assert rec2.report_id == "REPORT-FULL"


def test_cross_project_double_count_rejected(domain, registry):
    """
    Section C3: Cross-project double count attack.
    Same vendor + invoice validly signed separately for Project A and Project B (each signature
    cryptographically binds its own distinct projectId).
    When claimed under two different report_ids, second claim is rejected with
    INVOICE_REUSED_ACROSS_REPORTS, even though projectId differs.
    Ledger state for Project A remains unmodified.
    """
    ledger = InvoiceLedger()

    receipt_a = Receipt(
        project_id="PROJECT-ALPHA-KENYA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "aa" * 32,
    )
    sig_a = sign_receipt(receipt_a, TEST_PRIV_KEY, domain)

    receipt_b = Receipt(
        project_id="PROJECT-BETA-TANZANIA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "bb" * 32,
    )
    sig_b = sign_receipt(receipt_b, TEST_PRIV_KEY, domain)

    # Signatures differ because project_id is signed into structHash
    assert sig_a != sig_b

    # Both signatures recover the legitimate vendor address
    assert recover_signer(receipt_a, sig_a, domain).lower() == TEST_SIGNER.lower()
    assert recover_signer(receipt_b, sig_b, domain).lower() == TEST_SIGNER.lower()

    # Nullifiers are identical because projectId is excluded from the nullifier formula
    assert receipt_a.invoice_nullifier == receipt_b.invoice_nullifier

    # First claim under Report A succeeds
    res_a = process_claim(
        receipt=receipt_a,
        signature=sig_a,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=250000,
        report_id="REPORT-PROJECT-A",
    )
    assert res_a.status == "VERIFIED"
    assert res_a.claimed_amount == 250000

    # Second claim under Report B for Project B must be REJECTED
    res_b = process_claim(
        receipt=receipt_b,
        signature=sig_b,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
        ledger=ledger,
        claim_amount=250000,
        report_id="REPORT-PROJECT-B",
    )
    assert res_b.status == "REJECTED"
    assert res_b.reason == "INVOICE_REUSED_ACROSS_REPORTS"

    # Ledger state for Project A remains pristine
    rec = ledger.get_record(receipt_a.invoice_nullifier)
    assert rec is not None
    assert rec.claimed == 250000
    assert rec.report_id == "REPORT-PROJECT-A"


def test_verify_receipt_domain_and_signature_rejections(valid_receipt, domain, registry):
    """
    Section C4: Through verify_receipt:
    - Wrong chainId domain -> SIGNER_VENDOR_MISMATCH
    - Wrong verifyingContract domain -> SIGNER_VENDOR_MISMATCH
    - Malformed signatures (empty, 64 bytes, 66 bytes, bad v=29) -> MALFORMED_SIGNATURE
    Assert the exact reason codes returned by verify_receipt.
    """
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    # 1. Wrong chainId domain
    wrong_chain_domain = EIP712Domain(
        name=domain.name,
        version=domain.version,
        chain_id=1,  # Mismatched chain ID
        verifying_contract=domain.verifying_contract,
    )
    res_chain = verify_receipt(
        receipt=valid_receipt,
        signature=valid_sig,
        domain=wrong_chain_domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_chain.status == "REJECTED"
    assert res_chain.reason == "SIGNER_VENDOR_MISMATCH"

    # 2. Wrong verifyingContract domain
    wrong_contract_domain = EIP712Domain(
        name=domain.name,
        version=domain.version,
        chain_id=domain.chain_id,
        verifying_contract="0x2222222222222222222222222222222222222222",
    )
    res_contract = verify_receipt(
        receipt=valid_receipt,
        signature=valid_sig,
        domain=wrong_contract_domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_contract.status == "REJECTED"
    assert res_contract.reason == "SIGNER_VENDOR_MISMATCH"

    # 3. Empty signature
    res_empty = verify_receipt(
        receipt=valid_receipt,
        signature="",
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_empty.status == "REJECTED"
    assert res_empty.reason == "MALFORMED_SIGNATURE"

    # 4. 64-byte signature
    res_64 = verify_receipt(
        receipt=valid_receipt,
        signature="0x" + "aa" * 64,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_64.status == "REJECTED"
    assert res_64.reason == "MALFORMED_SIGNATURE"

    # 5. 66-byte signature
    res_66 = verify_receipt(
        receipt=valid_receipt,
        signature="0x" + "aa" * 66,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_66.status == "REJECTED"
    assert res_66.reason == "MALFORMED_SIGNATURE"

    # 6. Bad v recovery identifier (v=29)
    valid_sig_bytes = bytes.fromhex(valid_sig[2:])
    bad_v_sig = "0x" + (valid_sig_bytes[:64] + bytes([29])).hex()
    res_bad_v = verify_receipt(
        receipt=valid_receipt,
        signature=bad_v_sig,
        domain=domain,
        registry=registry,
        allowed_category="WATER_INFRASTRUCTURE",
        now=1714000000,
    )
    assert res_bad_v.status == "REJECTED"
    assert res_bad_v.reason == "MALFORMED_SIGNATURE"


def test_fail_closed_on_unexpected_evidence_exception(valid_receipt, domain, registry):
    """Any unexpected exception during evidence verification produces REJECTED with INTERNAL_ERROR."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, domain)

    with patch(
        "backend.app.services.verification.verify_evidence",
        side_effect=RuntimeError("Simulated evidence subsystem crash"),
    ):
        res = verify_receipt(
            receipt=valid_receipt,
            signature=sig,
            domain=domain,
            registry=registry,
            allowed_category="WATER_INFRASTRUCTURE",
            now=1714000000,
            file_bytes=b"sample",
            salt=b"\x11" * 32,
        )
        assert res.status == "REJECTED"
        assert res.reason == "INTERNAL_ERROR"


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
