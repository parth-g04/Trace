"""
Tests for fund-flow tracing and conservation reconciliation (backend/app/services/trace_graph.py).

Verifies the 5 requirements from TRACE M1:
1. Complete expected chain and parent relationships:
   DONATION -> ALLOCATION -> SWAP -> BRIDGE -> OFFRAMP -> VENDOR_PAYMENT.
2. Asset conversions without adding unlike denominations (strict per-denomination integrity).
3. Detection of off-ramp without matching vendor payment when required (UNMATCHED_OFFRAMP).
4. Detection of vendor payment with no corresponding verified claim (UNVERIFIED_PAYMENT_CLAIM).
5. Detection of overspend (CONSERVATION_VIOLATION) and zero residual for valid seeded trace.
"""
from pathlib import Path
import tempfile
import pytest

from backend.app.db import Database
from backend.app.services.trace_graph import TraceGraphReconciler, build_trace_graph


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_trace.db")
        db = Database(db_path)
        try:
            yield db
        finally:
            db.close()


def test_complete_expected_chain_and_parent_relationships():
    """
    Verifies the complete 6-hop flow chain and parent relationships:
    DONATION -> ALLOCATION -> SWAP -> BRIDGE -> OFFRAMP -> VENDOR_PAYMENT.
    """
    events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",
            "output_asset": "ETH",
            "output_amount": "50000000000000000000",
            "is_simulated": 0,
            "attestation": "GENESIS_TX",
        },
        {
            "event_id": "EVT-ALLOC-1",
            "project_id": "WATER-001",
            "event_type": "ALLOCATION",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "ETH",
            "output_amount": "10000000000000000000",
            "is_simulated": 1,
            "attestation": "SIM_ALLOC_T1",
        },
        {
            "event_id": "EVT-SWAP-1",
            "project_id": "WATER-001",
            "event_type": "SWAP",
            "parent_event_id": "EVT-ALLOC-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USDC",
            "output_amount": "20000000000",  # 20,000 USDC (6 decimals)
            "conversion_rate_basis": 2000,
            "is_simulated": 1,
            "attestation": "SIM_SWAP_UNISWAP_V3",
        },
        {
            "event_id": "EVT-BRIDGE-1",
            "project_id": "WATER-001",
            "event_type": "BRIDGE",
            "parent_event_id": "EVT-SWAP-1",
            "input_asset": "USDC",
            "input_amount": "20000000000",
            "output_asset": "USDC",
            "output_amount": "20000000000",
            "is_simulated": 1,
            "attestation": "SIM_BRIDGE_ARBITRUM",
        },
        {
            "event_id": "EVT-OFFRAMP-1",
            "project_id": "WATER-001",
            "event_type": "OFFRAMP",
            "parent_event_id": "EVT-BRIDGE-1",
            "input_asset": "USDC",
            "input_amount": "20000000000",
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",  # $20,000 USD fiat
            "conversion_rate_basis": 100,
            "is_simulated": 1,
            "attestation": "SIM_OFFRAMP_CIRCLE",
        },
        {
            "event_id": "EVT-PAY-1",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-OFFRAMP-1",
            "input_asset": "USD_CENTS",
            "input_amount": "2000000",  # $20,000 paid to vendor
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",
            "is_simulated": 1,
            "attestation": "SIM_PAY_RECEIPT",
            "metadata": {"claim_id": "CLM-VERIFIED-100"},
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(
        events,
        require_matching_vendor_payment=True,
        verified_claim_ids={"CLM-VERIFIED-100"},
    )
    assert is_conserved is True
    assert len(discrepancies) == 0


def test_asset_conversions_without_adding_unlike_denominations():
    """
    Verifies asset conversions maintain denominational continuity without adding unlike denominations:
    - ALLOCATION consumes ETH and outputs ETH
    - SWAP consumes ETH and outputs USDC
    - BRIDGE consumes USDC and outputs USDC
    - OFFRAMP consumes USDC and outputs USD_CENTS
    - VENDOR_PAYMENT consumes USD_CENTS and outputs USD_CENTS
    Directly feeding USD_CENTS to an ETH or USDC parent triggers ASSET_MISMATCH.
    """
    # Mismatch: VENDOR_PAYMENT attempting to consume directly from SWAP (USDC parent)
    mismatched_events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",
            "output_asset": "ETH",
            "output_amount": "50000000000000000000",
            "is_simulated": 0,
        },
        {
            "event_id": "EVT-SWAP-1",
            "project_id": "WATER-001",
            "event_type": "SWAP",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USDC",
            "output_amount": "20000000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
        {
            "event_id": "EVT-PAY-INVALID",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-SWAP-1",
            "input_asset": "USD_CENTS",  # Mismatch: Parent outputs USDC!
            "input_amount": "500000",
            "output_asset": "USD_CENTS",
            "output_amount": "500000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(mismatched_events)
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "ASSET_MISMATCH" in codes
    mismatch = next(d for d in discrepancies if d.code == "ASSET_MISMATCH")
    assert mismatch.severity == "CRITICAL"
    assert "consumes asset 'USD_CENTS', but parent EVT-SWAP-1 outputs asset 'USDC'" in mismatch.explanation


def test_detect_offramp_without_matching_vendor_payment():
    """
    Detects an off-ramp without a matching vendor payment when one is required.
    Triggers UNMATCHED_OFFRAMP with CRITICAL severity.
    """
    events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",
            "output_asset": "ETH",
            "output_amount": "50000000000000000000",
            "is_simulated": 0,
        },
        {
            "event_id": "EVT-ALLOC-1",
            "project_id": "WATER-001",
            "event_type": "ALLOCATION",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "ETH",
            "output_amount": "10000000000000000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
        {
            "event_id": "EVT-OFFRAMP-1",
            "project_id": "WATER-001",
            "event_type": "OFFRAMP",
            "parent_event_id": "EVT-ALLOC-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
        # NOTE: NO VENDOR_PAYMENT child event consuming EVT-OFFRAMP-1
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(
        events,
        require_matching_vendor_payment=True,
    )
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "UNMATCHED_OFFRAMP" in codes
    unmatched = next(d for d in discrepancies if d.code == "UNMATCHED_OFFRAMP")
    assert unmatched.severity == "CRITICAL"
    assert "EVT-OFFRAMP-1" in unmatched.affected_event_ids


def test_detect_vendor_payment_with_no_corresponding_verified_claim():
    """
    Detects a vendor payment event that does not link to an authentic verified claim record.
    Triggers UNVERIFIED_PAYMENT_CLAIM with CRITICAL severity.
    """
    events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",
            "output_asset": "ETH",
            "output_amount": "50000000000000000000",
            "is_simulated": 0,
        },
        {
            "event_id": "EVT-OFFRAMP-1",
            "project_id": "WATER-001",
            "event_type": "OFFRAMP",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
        {
            "event_id": "EVT-PAY-GHOST",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-OFFRAMP-1",
            "input_asset": "USD_CENTS",
            "input_amount": "500000",
            "output_asset": "USD_CENTS",
            "output_amount": "500000",
            "is_simulated": 1,
            "attestation": "SIM",
            "metadata": {"claim_id": "CLM-NONEXISTENT-999"},
        },
    ]

    verified_claims = {"CLM-REAL-001"}  # Does not include CLM-NONEXISTENT-999

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(
        events,
        verified_claim_ids=verified_claims,
    )
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "UNVERIFIED_PAYMENT_CLAIM" in codes
    unverified = next(d for d in discrepancies if d.code == "UNVERIFIED_PAYMENT_CLAIM")
    assert unverified.severity == "CRITICAL"
    assert "CLM-NONEXISTENT-999" in unverified.explanation


def test_detect_overspend_and_preserve_zero_residual_for_valid_trace(test_db):
    """
    1. Detects overspend when child events consume more than parent output.
    2. Verifies that a valid seeded trace preserves exactly zero residual.
    """
    # 1. Overspend detection
    overspend_events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",
            "output_asset": "ETH",
            "output_amount": "50000000000000000000",
            "is_simulated": 0,
        },
        {
            "event_id": "EVT-OFFRAMP-1",
            "project_id": "WATER-001",
            "event_type": "OFFRAMP",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",  # $20,000 USD
            "is_simulated": 1,
            "attestation": "SIM",
        },
        {
            "event_id": "EVT-PAY-OVERSPEND",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-OFFRAMP-1",
            "input_asset": "USD_CENTS",
            "input_amount": "2500000",  # $25,000 USD (Overspend by 500,000 cents!)
            "output_asset": "USD_CENTS",
            "output_amount": "2500000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(overspend_events)
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "CONSERVATION_VIOLATION" in codes
    violation = next(d for d in discrepancies if d.code == "CONSERVATION_VIOLATION")
    assert violation.severity == "CRITICAL"
    assert "overspend: 500000 USD_CENTS" in violation.explanation

    # 2. Zero residual for valid seeded trace
    test_db.reset_demo_state(seed_complete_trace=True)
    graph = build_trace_graph(test_db, "WATER-001", require_matching_vendor_payment=True)
    assert graph["is_conserved"] is True
    assert len(graph["discrepancies"]) == 0

    summary = graph["summary"]
    assert summary["total_offramped_usd_cents"] == 2000000
    assert summary["total_paid_usd_cents"] == 2000000
    assert summary["offramp_residual_usd_cents"] == 0  # EXACT ZERO RESIDUAL

    # Verify event types and chaining
    event_types = [e["event_type"] for e in graph["events"]]
    assert event_types == [
        "DONATION",
        "ALLOCATION",
        "SWAP",
        "BRIDGE",
        "OFFRAMP",
        "VENDOR_PAYMENT",
    ]
