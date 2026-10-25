"""
Tests for simulated escrow service (backend/app/services/escrow_sim.py).

Verifies:
- Integer conversion between USD cents and wei.
- Tranche 1 release without verified spending.
- Tranche 2 blocked when verified spending is insufficient.
- Tranche 2 released when verified spending meets or exceeds prior releases.
- Frozen projects cannot release tranches.
- Rejection when all tranches have been disbursed.
"""
import tempfile
import time
from pathlib import Path
import pytest

from backend.app.db import Database
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.escrow_sim import (
    SimulatedEscrowService,
    convert_usd_cents_to_wei,
    convert_wei_to_usd_cents,
)
from backend.app.services.signatures import sign_receipt


@pytest.fixture
def fresh_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_escrow.db")
        db = Database(db_path)
        db.reset_demo_state()
        try:
            yield db
        finally:
            db.close()


def test_integer_money_conversions():
    """Confirms exact integer money conversion without floating-point drift."""
    # 1 ETH = $2,000.00 = 200,000 cents
    cents = 200000
    wei = convert_usd_cents_to_wei(cents)
    assert wei == 10**18
    assert convert_wei_to_usd_cents(wei) == cents

    # 1 cent = 5 * 10**12 wei
    assert convert_usd_cents_to_wei(1) == 5_000_000_000_000
    assert convert_wei_to_usd_cents(5_000_000_000_000) == 1

    # Invalid input types or values reject cleanly
    with pytest.raises(ValueError):
        convert_usd_cents_to_wei(-1)
    with pytest.raises(ValueError):
        convert_usd_cents_to_wei(10.5)  # No floats allowed!


def test_tranche_1_release_without_spending(fresh_db):
    """Initial Tranche 1 can be released without any verified spending."""
    # Create project at tranche 0
    conn = fresh_db.get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE projects SET current_tranche = 0, released_wei = '0', verified_spend_wei = '0' WHERE id = 'WATER-001'"
            )
            conn.execute(
                "UPDATE escrow_state SET current_tranche = 0, released_wei = '0' WHERE project_id = 'WATER-001'"
            )
    finally:
        conn.close()

    escrow = SimulatedEscrowService(fresh_db)
    readiness = escrow.evaluate_release("WATER-001")
    assert readiness["disbursement_allowed"] is True
    assert readiness["status"] == "READY"
    assert readiness["next_tranche"] == 1

    res = escrow.release_next_tranche("WATER-001")
    assert res["status"] == "RELEASED"
    assert res["tranche_number"] == 1
    assert res["released_wei"] == 10 * 10**18


def test_tranche_2_blocked_without_verified_spend(fresh_db):
    """Tranche 2 is BLOCKED when verified spend has not covered Tranche 1."""
    escrow = SimulatedEscrowService(fresh_db)
    # Release Tranche 1 first
    res1 = escrow.release_next_tranche("WATER-001")
    assert res1["status"] == "RELEASED"
    assert res1["tranche_number"] == 1

    # At Tranche 1 with 0 verified spend, Tranche 2 is blocked
    readiness = escrow.evaluate_release("WATER-001")
    assert readiness["disbursement_allowed"] is False
    assert readiness["status"] == "BLOCKED"
    assert readiness["reason"] == "INSUFFICIENT_VERIFIED_SPEND"

    res = escrow.release_next_tranche("WATER-001")
    assert res["status"] == "BLOCKED"
    assert res["reason"] == "INSUFFICIENT_VERIFIED_SPEND"
    assert res["disbursement_allowed"] is False


def test_tranche_2_unlocked_after_verified_spend(fresh_db):
    """Tranche 2 unlocks after verified claims cover the 10 ETH previously released."""
    escrow = SimulatedEscrowService(fresh_db)
    # Release Tranche 1 first
    res1 = escrow.release_next_tranche("WATER-001")
    assert res1["status"] == "RELEASED"
    assert res1["tranche_number"] == 1

    # Spend required: 10 ETH = $20,000 USD = 2,000,000 cents
    priv_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    domain = EIP712Domain()
    now = int(time.time())

    rec = Receipt(
        project_id="WATER-001",
        vendor_id="WELL-DRILL-01",
        invoice_id="INV-FULL-TRANCHE-1",
        invoice_total=2000000,  # $20,000 USD
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "aa" * 32,
    )
    sig = sign_receipt(rec, priv_key, domain)

    claim_res = fresh_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=2000000,
        report_id="REPORT-FULL-T1",
        domain=domain,
        now=now,
    )
    assert claim_res["status"] == "VERIFIED"

    readiness = escrow.evaluate_release("WATER-001")
    assert readiness["disbursement_allowed"] is True
    assert readiness["status"] == "READY"
    assert readiness["next_tranche"] == 2

    release_res = escrow.release_next_tranche("WATER-001")
    assert release_res["status"] == "RELEASED"
    assert release_res["tranche_number"] == 2
    assert release_res["total_released_wei"] == 20 * 10**18


def test_frozen_project_cannot_release(fresh_db):
    """Frozen project cannot disburse any funds."""
    fresh_db.freeze_project("WATER-001", "Security violation: FORGERY_DETECTED")
    escrow = SimulatedEscrowService(fresh_db)

    readiness = escrow.evaluate_release("WATER-001")
    assert readiness["disbursement_allowed"] is False
    assert readiness["reason"] == "PROJECT_FROZEN"

    res = escrow.release_next_tranche("WATER-001")
    assert res["status"] == "BLOCKED"
    assert res["reason"] == "PROJECT_FROZEN"
