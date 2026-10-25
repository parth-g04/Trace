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
