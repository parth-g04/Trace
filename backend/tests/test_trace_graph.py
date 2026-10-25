"""
Tests for fund-flow tracing and conservation reconciliation (backend/app/services/trace_graph.py).

Verifies:
- Valid trace: all conservation rules hold, zero critical discrepancies.
- Injected overspend: detects when child allocations exceed parent donation.
- Unmatched vendor payment: detects orphan or invalid parent payment references.
- Asset mismatch: catches attempts to claim ETH directly against USD or vice versa.
"""
import pytest

from backend.app.services.trace_graph import TraceGraphReconciler


def test_valid_trace_reconciliation():
    """Verifies that a valid multi-hop flow passes all conservation checks cleanly."""
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
            "attestation": "SIM_ALLOC",
        },
        {
            "event_id": "EVT-BRIDGE-1",
            "project_id": "WATER-001",
            "event_type": "BRIDGE",
            "parent_event_id": "EVT-ALLOC-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "ETH",
            "output_amount": "10000000000000000000",
            "is_simulated": 1,
            "attestation": "SIM_BRIDGE",
        },
        {
            "event_id": "EVT-OFFRAMP-1",
            "project_id": "WATER-001",
            "event_type": "OFFRAMP",
            "parent_event_id": "EVT-BRIDGE-1",
            "input_asset": "ETH",
            "input_amount": "10000000000000000000",
            "output_asset": "USD_CENTS",
            "output_amount": "2000000",  # $20,000 USD
            "is_simulated": 1,
            "attestation": "SIM_OFFRAMP",
        },
        {
            "event_id": "EVT-PAY-1",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-OFFRAMP-1",
            "input_asset": "USD_CENTS",
            "input_amount": "500000",  # $5,000 USD
            "output_asset": "USD_CENTS",
            "output_amount": "500000",
            "is_simulated": 1,
            "attestation": "SIM_PAY",
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(events)
    assert is_conserved is True
    assert len(discrepancies) == 0


def test_injected_overspend_triggers_conservation_violation():
    """Injected overspend (allocations exceed donation) triggers CONSERVATION_VIOLATION."""
    events = [
        {
            "event_id": "EVT-DONATION-1",
            "project_id": "WATER-001",
            "event_type": "DONATION",
            "parent_event_id": None,
            "input_asset": "ETH",
            "input_amount": "50000000000000000000",  # 50 ETH
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
            "input_amount": "30000000000000000000",  # 30 ETH
            "output_asset": "ETH",
            "output_amount": "30000000000000000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
        {
            "event_id": "EVT-ALLOC-2",
            "project_id": "WATER-001",
            "event_type": "ALLOCATION",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "ETH",
            "input_amount": "30000000000000000000",  # 30 ETH (total = 60 ETH > 50 ETH)
            "output_asset": "ETH",
            "output_amount": "30000000000000000000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(events)
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "CONSERVATION_VIOLATION" in codes
    violation = next(d for d in discrepancies if d.code == "CONSERVATION_VIOLATION")
    assert violation.severity == "CRITICAL"
    assert "overspend: 10000000000000000000" in violation.explanation


def test_unmatched_vendor_payment_discrepancy():
    """A vendor payment referencing a non-existent parent event is flagged as UNMATCHED_PAYMENT."""
    events = [
        {
            "event_id": "EVT-PAY-GHOST",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-NON-EXISTENT",
            "input_asset": "USD_CENTS",
            "input_amount": "500000",
            "output_asset": "USD_CENTS",
            "output_amount": "500000",
            "is_simulated": 1,
        }
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(events)
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "UNMATCHED_PAYMENT" in codes
    unmatched = next(d for d in discrepancies if d.code == "UNMATCHED_PAYMENT")
    assert unmatched.severity == "CRITICAL"


def test_asset_mismatch_discrepancy():
    """Connecting USD payment directly to an ETH output is caught as ASSET_MISMATCH."""
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
            "event_id": "EVT-PAY-INVALID",
            "project_id": "WATER-001",
            "event_type": "VENDOR_PAYMENT",
            "parent_event_id": "EVT-DONATION-1",
            "input_asset": "USD_CENTS",  # Mismatch: Parent outputs ETH!
            "input_amount": "500000",
            "output_asset": "USD_CENTS",
            "output_amount": "500000",
            "is_simulated": 1,
            "attestation": "SIM",
        },
    ]

    is_conserved, discrepancies = TraceGraphReconciler.reconcile(events)
    assert is_conserved is False
    codes = [d.code for d in discrepancies]
    assert "ASSET_MISMATCH" in codes
