"""
Comprehensive tests for invoice identity, canonical nullifiers, and the claim ledger.
"""
import pytest
from eth_utils import keccak

from backend.app.models.receipt import Receipt
from backend.app.services.canonical import id32
from backend.app.services.invoice_identity import InvoiceLedger, compute_nullifier


def test_nullifier_invariance_under_normalization():
    """
    Invoices with different input formatting (INV-1042, inv 1042, INV-001042)
    normalize to the same canonical IDs and produce the exact same nullifier.
    """
    from backend.app.services.canonical import normalize_invoice_id

    v_id = id32("ACME")
    i1 = id32(normalize_invoice_id("INV-1042"))
    i2 = id32(normalize_invoice_id("inv 1042"))
    i3 = id32(normalize_invoice_id("INV-001042"))
    i4 = id32(normalize_invoice_id("INV1042"))

    n1 = compute_nullifier(v_id, i1)
    n2 = compute_nullifier(v_id, i2)
    n3 = compute_nullifier(v_id, i3)
    n4 = compute_nullifier(v_id, i4)

    assert n1 == n2 == n3 == n4


def test_nullifier_distinct_across_vendors():
    """Same invoice number for different vendors produces different nullifiers."""
    v_a = id32("VENDORA")
    v_b = id32("VENDORB")
    i_id = id32("INV1042")

    nullifier_a = compute_nullifier(v_a, i_id)
    nullifier_b = compute_nullifier(v_b, i_id)

    assert nullifier_a != nullifier_b


def test_nullifier_collides_across_different_projects():
    """
    CRITICAL DOUBLE-CLAIMING DEFENSE:
    Same vendor and invoice submitted to two different projects produces the SAME nullifier.
    """
    r1 = Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "aa" * 32,
    )
    r2 = Receipt(
        project_id="PROJECT-BETA",  # Different project!
        vendor_id="ACME",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "aa" * 32,
    )

    assert r1.invoice_nullifier == r2.invoice_nullifier


def test_nullifier_collides_with_different_evidence():
    """
    Same vendor and invoice with different evidence commitments still collides.
    Attacker cannot bypass duplicate invoice detection by hashing a different file.
    """
    r1 = Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "11" * 32,
    )
    r2 = Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "22" * 32,  # Different evidence!
    )

    assert r1.invoice_nullifier == r2.invoice_nullifier


def test_ledger_first_claim_success():
    """Valid initial claim creates ledger record with correct balance."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER")

    outcome = ledger.try_claim(nullifier, invoice_total=1000, amount=400, report_id="REPORT-1")
    assert outcome.success is True
    assert outcome.reason is None
    assert outcome.claimed_so_far == 400
    assert outcome.remaining_balance == 600

    rec = ledger.get_record(nullifier)
    assert rec is not None
    assert rec.invoice_total == 1000
    assert rec.claimed == 400
    assert rec.report_id == "REPORT-1"


def test_ledger_installments_same_report():
    """Multiple installments under the same report_id succeed up to the invoice total."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER_INSTALLMENTS")

    # Installment 1: 300 of 1000
    res1 = ledger.try_claim(nullifier, 1000, 300, "REPORT-1")
    assert res1.success is True
    assert res1.claimed_so_far == 300
    assert res1.remaining_balance == 700

    # Installment 2: 700 of 1000 (completes the invoice)
    res2 = ledger.try_claim(nullifier, 1000, 700, "REPORT-1")
    assert res2.success is True
    assert res2.claimed_so_far == 1000
    assert res2.remaining_balance == 0

    rec = ledger.get_record(nullifier)
    assert rec.claimed == 1000


def test_ledger_rejects_cross_report_reuse():
    """Same invoice claimed under a different report_id is rejected with INVOICE_REUSED_ACROSS_REPORTS."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER_CROSS_REPORT")

    # First claim under donor report 1
    res1 = ledger.try_claim(nullifier, 1000, 500, "DONOR-REPORT-ALPHA")
    assert res1.success is True

    # State before attack
    rec_before = ledger.get_record(nullifier)

    # Attempt to claim against donor report 2
    res2 = ledger.try_claim(nullifier, 1000, 500, "DONOR-REPORT-BETA")
    assert res2.success is False
    assert res2.reason == "INVOICE_REUSED_ACROSS_REPORTS"

    # Verify atomic invariance: state unchanged
    rec_after = ledger.get_record(nullifier)
    assert rec_after == rec_before


def test_ledger_rejects_claim_exceeding_total():
    """Claim exceeding the total invoice amount is rejected and ledger is not mutated."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER_EXCEED")

    # Claim 1500 on 1000 total on first claim
    res1 = ledger.try_claim(nullifier, 1000, 1500, "REPORT-1")
    assert res1.success is False
    assert res1.reason == "CLAIM_EXCEEDS_INVOICE_TOTAL"
    assert ledger.has_nullifier(nullifier) is False  # Never created

    # Valid first claim of 800
    ledger.try_claim(nullifier, 1000, 800, "REPORT-1")

    # Subsequent claim of 300 (800 + 300 = 1100 > 1000)
    rec_before = ledger.get_record(nullifier)
    res2 = ledger.try_claim(nullifier, 1000, 300, "REPORT-1")
    assert res2.success is False
    assert res2.reason == "CLAIM_EXCEEDS_INVOICE_TOTAL"

    rec_after = ledger.get_record(nullifier)
    assert rec_after == rec_before


def test_ledger_rejects_when_fully_claimed():
    """Once an invoice is 100% claimed, any further claims are rejected with INVOICE_ALREADY_FULLY_CLAIMED."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER_FULL")

    ledger.try_claim(nullifier, 1000, 1000, "REPORT-1")
    rec_before = ledger.get_record(nullifier)

    res = ledger.try_claim(nullifier, 1000, 1, "REPORT-1")
    assert res.success is False
    assert res.reason == "INVOICE_ALREADY_FULLY_CLAIMED"

    rec_after = ledger.get_record(nullifier)
    assert rec_after == rec_before


def test_ledger_rejects_tampered_invoice_total():
    """Presenting a different invoice total for an existing nullifier is rejected."""
    ledger = InvoiceLedger()
    nullifier = keccak(b"TEST_NULLIFIER_TAMPER_TOTAL")

    ledger.try_claim(nullifier, 1000, 500, "REPORT-1")
    rec_before = ledger.get_record(nullifier)

    # Attacker tries to increase invoice_total to 2000
    res = ledger.try_claim(nullifier, 2000, 500, "REPORT-1")
    assert res.success is False
    assert res.reason == "INVOICE_TOTAL_MISMATCH"

    rec_after = ledger.get_record(nullifier)
    assert rec_after == rec_before
