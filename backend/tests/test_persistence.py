"""
Tests for TRACE SQLite persistence layer (backend/app/db.py).

Verifies:
- Schema initialization and deterministic seed/reset.
- State persistence across connection lifecycles.
- Transaction atomicity: rejection preserves audit trail and freeze status
  without polluting claims, invoice ledger, or spend totals.
- Cross-report duplicate prevention and project freezing.
"""
import os
import tempfile
import time
from pathlib import Path
import pytest

from eth_account import Account

from backend.app.db import Database
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import sign_receipt


@pytest.fixture
def temp_db():
    """Provides a fresh isolated temporary database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_trace.db")
        db = Database(db_path)
        db.reset_demo_state()
        try:
            yield db
        finally:
            db.close()


def test_schema_init_and_deterministic_reset(temp_db):
    """Verifies schema creation and deterministic seeding at Tranche 0."""
    proj = temp_db.get_project("WATER-001")
    assert proj is not None
    assert proj["name"] == "Clean Water Initiative Kenya"
    assert proj["purpose"] == "WATER_INFRASTRUCTURE"
    assert int(proj["funding_wei"]) == 50 * 10**18
    assert proj["current_tranche"] == 0
    assert int(proj["released_wei"]) == 0
    assert int(proj["verified_spend_wei"]) == 0
    assert proj["is_frozen"] == 0

    vendors = temp_db.list_vendors()
    assert len(vendors) == 2
    vendor_ids = {v["vendor_id"] for v in vendors}
    assert "WELL-DRILL-01" in vendor_ids
    assert "SOLAR-PUMP-02" in vendor_ids

    flows = temp_db.get_flow_events("WATER-001")
    assert len(flows) == 1
    assert flows[0]["event_type"] == "DONATION"

    audits = temp_db.get_audit_events("WATER-001")
    assert len(audits) >= 1
    assert audits[0]["event_type"] == "DEMO_RESET"


def test_seeded_complete_trace(temp_db):
    """Verifies seeding complete 6-hop trace with zero residual."""
    temp_db.reset_demo_state(seed_complete_trace=True)
    proj = temp_db.get_project("WATER-001")
    assert proj["current_tranche"] == 1
    assert int(proj["released_wei"]) == 10 * 10**18
    assert int(proj["verified_spend_wei"]) == 10 * 10**18
    flows = temp_db.get_flow_events("WATER-001")
    assert len(flows) == 6
    event_types = [f["event_type"] for f in flows]
    assert event_types == ["DONATION", "ALLOCATION", "SWAP", "BRIDGE", "OFFRAMP", "VENDOR_PAYMENT"]


def test_persistence_across_connections():
    """Verifies data persists across different Database instances on same file."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "persist.db")
        db1 = Database(db_path)
        db1.reset_demo_state()
        db1.register_vendor("NEW-VENDOR", "New Vendor Inc", "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC")
        db1.close()

        # Open second connection to the exact same file
        db2 = Database(db_path)
        try:
            v = db2.get_vendor("NEW-VENDOR")
            assert v is not None
            assert v["name"] == "New Vendor Inc"
            assert v["address"].lower() == "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
        finally:
            db2.close()


def test_atomic_claim_processing_success(temp_db):
    """Verifies successful claim persistence, ledger update, and spend accumulation."""
    priv_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    domain = EIP712Domain()
    now = int(time.time())

    rec = Receipt(
        project_id="WATER-001",
        vendor_id="WELL-DRILL-01",
        invoice_id="INV-2026-001",
        invoice_total=500000,  # $5,000 USD
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "aa" * 32,
    )

    sig = sign_receipt(rec, priv_key, domain)

    # Release Tranche 1 first to disburse operating funds
    release_res = temp_db.release_next_tranche("WATER-001")
    assert release_res["status"] == "RELEASED"

    res = temp_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=500000,
        report_id="REPORT-Q1",
        domain=domain,
        now=now,
    )

    assert res["status"] == "VERIFIED"
    assert res["disbursement_allowed"] is True
    assert res["claimed_amount"] == 500000
    assert res["remaining_balance"] == 0

    # Verify database state
    proj = temp_db.get_project("WATER-001")
    assert proj["verified_spend_usd_cents"] == 500000
    # 500,000 cents * 5 * 10**12 = 2.5 * 10**18 wei
    assert int(proj["verified_spend_wei"]) == 2500000000000000000

    ledger = temp_db.get_ledger_record("0x" + rec.invoice_nullifier.hex())
    assert ledger is not None
    assert ledger["claimed"] == 500000
    assert ledger["invoice_total"] == 500000

    audits = temp_db.get_audit_events("WATER-001")
    audit_types = [a["event_type"] for a in audits]
    assert "CLAIM_VERIFIED" in audit_types

    # Verify complete 6-hop chain
    flows = temp_db.get_flow_events("WATER-001")
    assert len(flows) == 6
    assert [f["event_type"] for f in flows] == [
        "DONATION", "ALLOCATION", "SWAP", "BRIDGE", "OFFRAMP", "VENDOR_PAYMENT"
    ]


def test_rejection_without_partial_writes(temp_db):
    """
    Verifies that a forged claim rejection freezes the project and logs the audit event,
    but does NOT write to claims, modify the invoice ledger, or increase spend totals.
    """
    domain = EIP712Domain()
    now = int(time.time())

    rec = Receipt(
        project_id="WATER-001",
        vendor_id="WELL-DRILL-01",
        invoice_id="INV-FORGED-001",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "aa" * 32,
    )

    # Sign with attacker key
    attacker_key = "0x2a871d0798f97d79848a013d3bbd362c6b97fe5356e0bbeed1241f93003444a0"
    forged_sig = sign_receipt(rec, attacker_key, domain)

    res = temp_db.process_and_persist_claim(
        receipt=rec,
        signature=forged_sig,
        claim_amount=500000,
        report_id="REPORT-FORGED",
        domain=domain,
        now=now,
    )

    assert res["status"] == "REJECTED"
    assert res["reason"] == "SIGNER_VENDOR_MISMATCH"
    assert res["disbursement_allowed"] is False

    # Check project is FROZEN
    proj = temp_db.get_project("WATER-001")
    assert proj["is_frozen"] == 1
    assert "SIGNER_VENDOR_MISMATCH" in proj["freeze_reason"]

    # Invariant: Spend total did NOT change
    assert int(proj["verified_spend_wei"]) == 0
    assert proj["verified_spend_usd_cents"] == 0

    # Invariant: No claim record inserted
    conn = temp_db.get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM claims WHERE invoice_id = 'INV-FORGED-001'")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()

    # Invariant: Invoice ledger remains untouched
    ledger = temp_db.get_ledger_record("0x" + rec.invoice_nullifier.hex())
    assert ledger is None

    # Audit event is preserved
    audits = temp_db.get_audit_events("WATER-001")
    audit_types = [a["event_type"] for a in audits]
    assert "CLAIM_REJECTED" in audit_types
    assert "PROJECT_FROZEN" in audit_types


def test_cross_report_duplicate_claim_freezes_project(temp_db):
    """
    Submitting an already-claimed invoice under a different report_id
    triggers INVOICE_REUSED_ACROSS_REPORTS and freezes the project.
    """
    priv_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    domain = EIP712Domain()
    now = int(time.time())

    rec = Receipt(
        project_id="WATER-001",
        vendor_id="WELL-DRILL-01",
        invoice_id="INV-DUP-TEST",
        invoice_total=300000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "aa" * 32,
    )
    sig = sign_receipt(rec, priv_key, domain)

    # First claim under REPORT-A succeeds
    res1 = temp_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=300000,
        report_id="REPORT-A",
        domain=domain,
        now=now,
    )
    assert res1["status"] == "VERIFIED"

    # Second claim with same invoice under REPORT-B is rejected
    res2 = temp_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=300000,
        report_id="REPORT-B",
        domain=domain,
        now=now,
    )
    assert res2["status"] == "REJECTED"
    assert res2["reason"] == "INVOICE_REUSED_ACROSS_REPORTS"
    assert res2["disbursement_allowed"] is False

    # Offending project is frozen
    proj = temp_db.get_project("WATER-001")
    assert proj["is_frozen"] == 1
    assert "INVOICE_REUSED_ACROSS_REPORTS" in proj["freeze_reason"]
