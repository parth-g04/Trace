"""
Tests for TRACE demo scenarios (backend/app/demo/scenarios.py).

Verifies:
- All scenarios execute deterministically.
- Expected outcome, rejection reason, project freeze status, and release outcomes match specifications.
- Valid claim scenario accurately reports evidence verification (checks['evidence_verified'] is True).
- Evidence-omitted scenario is supported and correctly recorded (checks['evidence_verified'] is False).
- Changed evidence or incorrect salt is rejected with EVIDENCE_COMMITMENT_MISMATCH.
- Neither raw evidence nor salt is exposed in scenario responses.
- Reset repeatability: running a scenario after reset produces the identical result.
"""
from pathlib import Path
import tempfile
import time
import pytest

from backend.app.db import Database
from backend.app.demo.scenarios import list_demo_scenarios, run_scenario
from backend.app.demo.vendors import (
    TEST_EVIDENCE_BYTES,
    TEST_EVIDENCE_COMMITMENT,
    TEST_EVIDENCE_SALT,
    VENDOR_WELL_DRILL,
)
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import sign_receipt


@pytest.fixture
def scenario_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_scenarios.db")
        db = Database(db_path)
        db.reset_demo_state()
        try:
            yield db
        finally:
            db.close()


def test_scenario_catalog():
    """Confirms all scenarios are cataloged with descriptions."""
    catalog = list_demo_scenarios()
    assert len(catalog) == 7
    names = [s["name"] for s in catalog]
    assert "valid_claim" in names
    assert "valid_claim_evidence_omitted" in names
    assert "tampered_amount" in names
    assert "forged_signature" in names
    assert "unregistered_vendor" in names
    assert "duplicate_report" in names
    assert "out_of_purpose" in names


def test_scenario_valid_claim(scenario_db):
    """Scenario 1: valid_claim verifies signature, verifies evidence, updates spend, project remains ACTIVE."""
    res = run_scenario("valid_claim", scenario_db)
    assert res["status"] == "VERIFIED"
    assert res["reason"] is None
    assert res["project_status"] == "ACTIVE"
    assert res["next_release_outcome"] == "BLOCKED"  # Needs 10 ETH, has 2.5 ETH
    assert res["disbursement_allowed"] is True
    # Verify cryptographic evidence verification check is True
    assert res["checks"]["evidence_verified"] is True
    assert res["checks"]["signature_valid"] is True
    assert res["checks"]["signer_matches_vendor"] is True
    assert res["checks"]["vendor_registered"] is True


def test_scenario_valid_claim_evidence_omitted(scenario_db):
    """Scenario 1b: valid_claim_evidence_omitted verifies signature and ledger while truthfully recording evidence omitted."""
    res = run_scenario("valid_claim_evidence_omitted", scenario_db)
    assert res["status"] == "VERIFIED"
    assert res["reason"] is None
    assert res["project_status"] == "ACTIVE"
    assert res["disbursement_allowed"] is True
    # Evidence was omitted, so evidence_verified is False
    assert res["checks"]["evidence_verified"] is False
    assert res["checks"]["signature_valid"] is True


def test_changed_evidence_or_wrong_salt_rejected(scenario_db):
    """
    Verifies that:
    1. Altered evidence file bytes fail closed with EVIDENCE_COMMITMENT_MISMATCH.
    2. Wrong salt fails closed with EVIDENCE_COMMITMENT_MISMATCH.
    3. Partial evidence (salt without bytes or bytes without salt) fails with MALFORMED_EVIDENCE.
    """
    domain = EIP712Domain()
    now = int(time.time())

    rec = Receipt(
        project_id="WATER-001",
        vendor_id=VENDOR_WELL_DRILL.vendor_id,
        invoice_id="INV-EVIDENCE-TEST-001",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment=TEST_EVIDENCE_COMMITMENT,
    )
    sig = sign_receipt(rec, VENDOR_WELL_DRILL.private_key, domain)

    # 1. Altered evidence content
    tampered_bytes = TEST_EVIDENCE_BYTES + b" [MALICIOUS TAMPERING DETECTED]"
    res_tampered_bytes = scenario_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=500000,
        report_id="REPORT-EVIDENCE-1",
        domain=domain,
        now=now,
        file_bytes=tampered_bytes,
        salt=TEST_EVIDENCE_SALT,
    )
    assert res_tampered_bytes["status"] == "REJECTED"
    assert res_tampered_bytes["reason"] == "EVIDENCE_COMMITMENT_MISMATCH"
    assert res_tampered_bytes["checks"]["evidence_verified"] is False

    # 2. Incorrect salt (reset project state first so prior freeze does not mask reason)
    scenario_db.reset_demo_state()
    wrong_salt = bytes.fromhex("22" * 32)  # Different from TEST_EVIDENCE_SALT ("11"*32)
    res_wrong_salt = scenario_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=500000,
        report_id="REPORT-EVIDENCE-2",
        domain=domain,
        now=now,
        file_bytes=TEST_EVIDENCE_BYTES,
        salt=wrong_salt,
    )
    assert res_wrong_salt["status"] == "REJECTED"
    assert res_wrong_salt["reason"] == "EVIDENCE_COMMITMENT_MISMATCH"
    assert res_wrong_salt["checks"]["evidence_verified"] is False

    # 3. Partial evidence: bytes provided, salt missing
    scenario_db.reset_demo_state()
    res_missing_salt = scenario_db.process_and_persist_claim(
        receipt=rec,
        signature=sig,
        claim_amount=500000,
        report_id="REPORT-EVIDENCE-3",
        domain=domain,
        now=now,
        file_bytes=TEST_EVIDENCE_BYTES,
        salt=None,
    )
    assert res_missing_salt["status"] == "REJECTED"
    assert res_missing_salt["reason"] == "MALFORMED_EVIDENCE"


def test_no_salt_or_raw_evidence_in_scenario_response(scenario_db):
    """Never expose the salt or raw evidence through scenario or API responses."""
    res = run_scenario("valid_claim", scenario_db)

    # Recursively check that salt and raw bytes do not appear anywhere in values
    def check_no_leak(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert "salt" not in k.lower(), f"Salt key leaked at {path}.{k}"
                assert "file_bytes" not in k.lower(), f"File bytes key leaked at {path}.{k}"
                check_no_leak(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                check_no_leak(item, f"{path}[{idx}]")
        elif isinstance(obj, str):
            assert TEST_EVIDENCE_SALT.hex() not in obj, f"Salt hex leaked at {path}"
            assert "Hydrogeological Survey" not in obj, f"Evidence text leaked at {path}"

    check_no_leak(res)


def test_scenario_tampered_amount(scenario_db):
    """Scenario 2: tampered_amount rejected and project is FROZEN."""
    res = run_scenario("tampered_amount", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "SIGNER_VENDOR_MISMATCH"
    assert res["project_status"] == "FROZEN"
    assert res["next_release_outcome"] == "BLOCKED"
    assert res["disbursement_allowed"] is False


def test_scenario_forged_signature(scenario_db):
    """Scenario 3: forged_signature rejected and project is FROZEN."""
    res = run_scenario("forged_signature", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "SIGNER_VENDOR_MISMATCH"
    assert res["project_status"] == "FROZEN"
    assert res["next_release_outcome"] == "BLOCKED"
    assert res["disbursement_allowed"] is False


def test_scenario_unregistered_vendor(scenario_db):
    """Scenario 4: unregistered_vendor rejected."""
    res = run_scenario("unregistered_vendor", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "UNREGISTERED_VENDOR"
    assert res["disbursement_allowed"] is False


def test_scenario_duplicate_report(scenario_db):
    """Scenario 5: duplicate_report cross-report reuse rejected and project is FROZEN."""
    res = run_scenario("duplicate_report", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "INVOICE_REUSED_ACROSS_REPORTS"
    assert res["project_status"] == "FROZEN"
    assert res["next_release_outcome"] == "BLOCKED"
    assert res["disbursement_allowed"] is False


def test_scenario_out_of_purpose(scenario_db):
    """Scenario 6: out_of_purpose fund diversion rejected and project is FROZEN."""
    res = run_scenario("out_of_purpose", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "CATEGORY_NOT_ALLOWED"
    assert res["project_status"] == "FROZEN"
    assert res["next_release_outcome"] == "BLOCKED"
    assert res["disbursement_allowed"] is False


def test_repeatable_reset(scenario_db):
    """Resetting the database allows scenarios to be re-run repeatably."""
    # Run tampering scenario -> project freezes
    res1 = run_scenario("tampered_amount", scenario_db)
    assert res1["project_status"] == "FROZEN"

    # Reset
    scenario_db.reset_demo_state()
    is_frozen, _ = scenario_db.is_project_frozen("WATER-001")
    assert is_frozen is False

    # Run valid claim -> succeeds
    res2 = run_scenario("valid_claim", scenario_db)
    assert res2["status"] == "VERIFIED"
    assert res2["project_status"] == "ACTIVE"

    # Reset again
    scenario_db.reset_demo_state()
    res3 = run_scenario("valid_claim", scenario_db)
    assert res3["status"] == "VERIFIED"
    assert res3["project_status"] == "ACTIVE"


def test_attack_scenarios_do_not_auto_release_tranche(scenario_db):
    """
    Requirement 1 & 4:
    Attack scenarios (out_of_purpose, tampered_amount, forged_signature, unregistered_vendor)
    must NOT auto-release Tranche 1.
    From a clean Tranche 0 state, they must evaluate without disbursing escrow funds,
    leaving released_wei at 0 and current_tranche at 0.
    """
    attack_scenarios = [
        ("out_of_purpose", "CATEGORY_NOT_ALLOWED"),
        ("tampered_amount", "SIGNER_VENDOR_MISMATCH"),
        ("forged_signature", "SIGNER_VENDOR_MISMATCH"),
        ("unregistered_vendor", "UNREGISTERED_VENDOR"),
    ]

    for sc_name, expected_reason in attack_scenarios:
        scenario_db.reset_demo_state()
        res = run_scenario(sc_name, scenario_db)
        assert res["status"] == "REJECTED"
        assert res["reason"] == expected_reason

        proj = scenario_db.get_project("WATER-001")
        assert proj["current_tranche"] == 0
        assert int(proj["released_wei"]) == 0
        assert int(proj["verified_spend_wei"]) == 0

        # Confirm no OFFRAMP flow event exists
        flow_events = scenario_db.get_flow_events("WATER-001")
        offramp_events = [e for e in flow_events if e["event_type"] == "OFFRAMP"]
        assert len(offramp_events) == 0


def test_duplicate_invoice_metric_increments_by_one(scenario_db):
    """
    Requirement 3:
    The duplicate invoice counter must increment according to actual duplicate attempts,
    yielding exactly 1 on a single duplicate invoice submission, not 2.
    """
    scenario_db.reset_demo_state()
    res = run_scenario("duplicate_report", scenario_db)
    assert res["status"] == "REJECTED"
    assert res["reason"] == "INVOICE_REUSED_ACROSS_REPORTS"

    metrics = scenario_db.get_metrics()
    assert metrics["duplicate_invoice_attempts_blocked"] == 1
    assert metrics["valid_claims"] == 1
    assert metrics["rejected_claims"] == 1
    assert metrics["frozen_projects"] == 1


def test_tranche_release_rules_and_spend_gate(scenario_db):
    """
    Requirement 5:
    From clean state:
    1. Release Tranche 1 -> Allowed without prior spend.
    2. Attempt Tranche 2 release -> Blocked (0 spend < 10 ETH released).
    3. Submit valid claim ($5,000 = 2.5 ETH) -> Verified spend is 2.5 ETH.
    4. Attempt Tranche 2 release -> Still blocked (2.5 ETH spend < 10 ETH released).
    5. Freeze project -> Tranche release blocked with PROJECT_FROZEN.
    """
    scenario_db.reset_demo_state()

    # 1. Release Tranche 1
    rel1 = scenario_db.release_next_tranche("WATER-001")
    assert rel1["status"] == "RELEASED"
    assert rel1["tranche_number"] == 1
    assert int(rel1["released_wei"]) == 10 * 10**18

    # 2. Attempt Tranche 2 release -> Insufficient spend
    rel2_blocked = scenario_db.release_next_tranche("WATER-001")
    assert rel2_blocked["status"] == "BLOCKED"
    assert rel2_blocked["reason"] == "INSUFFICIENT_VERIFIED_SPEND"

    # 3. Submit valid claim ($5,000 = 2.5 ETH)
    res_claim = run_scenario("valid_claim", scenario_db)
    assert res_claim["status"] == "VERIFIED"

    proj = scenario_db.get_project("WATER-001")
    assert int(proj["verified_spend_wei"]) == 25 * 10**17  # 2.5 ETH

    # 4. Attempt Tranche 2 release again -> Still blocked (needs 10 ETH, has 2.5 ETH)
    rel2_still_blocked = scenario_db.release_next_tranche("WATER-001")
    assert rel2_still_blocked["status"] == "BLOCKED"
    assert rel2_still_blocked["reason"] == "INSUFFICIENT_VERIFIED_SPEND"

    # 5. Freeze project -> Tranche release blocked with PROJECT_FROZEN
    scenario_db.freeze_project("WATER-001", "TEST_FREEZE_REASON")
    rel_frozen = scenario_db.release_next_tranche("WATER-001")
    assert rel_frozen["status"] == "BLOCKED"
    assert rel_frozen["reason"] == "PROJECT_FROZEN"

