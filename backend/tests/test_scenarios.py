"""
Tests for TRACE demo scenarios (backend/app/demo/scenarios.py).

Verifies:
- All 6 scenarios execute deterministically.
- Expected outcome, rejection reason, project freeze status, and release outcomes match specifications.
- Reset repeatability: running a scenario after reset produces the identical result.
"""
import tempfile
from pathlib import Path
import pytest

from backend.app.db import Database
from backend.app.demo.scenarios import list_demo_scenarios, run_scenario


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
    """Confirms all 6 scenarios are cataloged with descriptions."""
    catalog = list_demo_scenarios()
    assert len(catalog) == 6
    names = [s["name"] for s in catalog]
    assert "valid_claim" in names
    assert "tampered_amount" in names
    assert "forged_signature" in names
    assert "unregistered_vendor" in names
    assert "duplicate_report" in names
    assert "out_of_purpose" in names


def test_scenario_valid_claim(scenario_db):
    """Scenario 1: valid_claim verifies, updates spend, project remains ACTIVE."""
    res = run_scenario("valid_claim", scenario_db)
    assert res["status"] == "VERIFIED"
    assert res["reason"] is None
    assert res["project_status"] == "ACTIVE"
    assert res["next_release_outcome"] == "BLOCKED"  # Needs 10 ETH, has 2.5 ETH
    assert res["disbursement_allowed"] is True


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
