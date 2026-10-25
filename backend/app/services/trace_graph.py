"""
Multi-hop fund-flow tracing and conservation reconciliation for TRACE.

Reconstructs directed flow graphs from genesis donations through allocations,
cross-chain bridges, fiat off-ramps, and vendor claim settlements.
Enforces strict asset-specific integer conservation checks and flags discrepancies.
"""
from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.app.db import Database


@dataclass
class TraceDiscrepancy:
    """Represents an anomaly, conservation violation, or unlinked hop in the fund flow graph."""
    code: str
    severity: str  # "INFO", "WARNING", "CRITICAL"
    affected_event_ids: List[str]
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TraceGraphReconciler:
    """
    Reconciles fund-flow event trees and validates conservation of funds.
    Operates strictly on integer quantities per asset denomination.
    """

    @staticmethod
    def reconcile(events: Sequence[Dict[str, Any]]) -> Tuple[bool, List[TraceDiscrepancy]]:
        """
        Validates the conservation of flow and structural integrity of events:
        1. Root events (DONATION) have no parent.
        2. Non-root events must have a valid existing parent_event_id.
        3. Child input_asset must match parent output_asset (never mix ETH and USD).
        4. Sum of child inputs must not exceed parent output (no overspending).
        5. Off-ramp and Bridge events must carry attestations and be marked simulated.
        """
        discrepancies: List[TraceDiscrepancy] = []
        events_by_id: Dict[str, Dict[str, Any]] = {}

        # 1. Index all events
        for evt in events:
            eid = evt["event_id"]
            if eid in events_by_id:
                discrepancies.append(
                    TraceDiscrepancy(
                        code="DUPLICATE_EVENT_ID",
                        severity="CRITICAL",
                        affected_event_ids=[eid],
                        explanation=f"Duplicate event ID detected in trace: {eid}",
                    )
                )
            events_by_id[eid] = evt

        # Group children by parent_event_id
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}

        for evt in events:
            eid = evt["event_id"]
            etype = evt["event_type"]
            parent_id = evt.get("parent_event_id")

            # Validate root vs child
            if etype == "DONATION":
                if parent_id is not None:
                    discrepancies.append(
                        TraceDiscrepancy(
                            code="ROOT_HAS_PARENT",
                            severity="WARNING",
                            affected_event_ids=[eid],
                            explanation=f"Root DONATION event {eid} should not have a parent_event_id.",
                        )
                    )
            else:
                if not parent_id:
                    discrepancies.append(
                        TraceDiscrepancy(
                            code="UNMATCHED_PAYMENT" if etype == "VENDOR_PAYMENT" else "ORPHAN_EVENT",
                            severity="CRITICAL",
                            affected_event_ids=[eid],
                            explanation=(
                                f"{etype} event {eid} has no parent_event_id; "
                                f"funds cannot be traced to an authorized source."
                            ),
                        )
                    )
                elif parent_id not in events_by_id:
                    discrepancies.append(
                        TraceDiscrepancy(
                            code="UNMATCHED_PAYMENT" if etype == "VENDOR_PAYMENT" else "ORPHAN_EVENT",
                            severity="CRITICAL",
                            affected_event_ids=[eid, parent_id],
                            explanation=(
                                f"{etype} event {eid} references missing parent {parent_id}."
                            ),
                        )
                    )
                else:
                    children_by_parent.setdefault(parent_id, []).append(evt)

                    # Check asset continuity
                    parent_evt = events_by_id[parent_id]
                    if evt["input_asset"] != parent_evt["output_asset"]:
                        discrepancies.append(
                            TraceDiscrepancy(
                                code="ASSET_MISMATCH",
                                severity="CRITICAL",
                                affected_event_ids=[parent_id, eid],
                                explanation=(
                                    f"Event {eid} consumes asset '{evt['input_asset']}', but parent "
                                    f"{parent_id} outputs asset '{parent_evt['output_asset']}'."
                                ),
                            )
                        )

            # Check simulated annotations for offramp and bridge
            if etype in ("BRIDGE", "OFFRAMP", "SWAP"):
                if not evt.get("is_simulated"):
                    discrepancies.append(
                        TraceDiscrepancy(
                            code="UNLABELED_SIMULATION",
                            severity="WARNING",
                            affected_event_ids=[eid],
                            explanation=f"{etype} event {eid} must be explicitly labeled as simulated.",
                        )
                    )
                if not evt.get("attestation"):
                    discrepancies.append(
                        TraceDiscrepancy(
                            code="MISSING_ATTESTATION",
                            severity="WARNING",
                            affected_event_ids=[eid],
                            explanation=f"Simulated {etype} event {eid} is missing audit attestation reference.",
                        )
                    )

        # 2. Conservation of flow per parent node
        for parent_id, children in children_by_parent.items():
            parent_evt = events_by_id.get(parent_id)
            if not parent_evt:
                continue

            parent_output = int(parent_evt["output_amount"])
            parent_asset = parent_evt["output_asset"]

            total_consumed_by_children = sum(int(c["input_amount"]) for c in children)

            if total_consumed_by_children > parent_output:
                overspend = total_consumed_by_children - parent_output
                child_ids = [c["event_id"] for c in children]
                discrepancies.append(
                    TraceDiscrepancy(
                        code="CONSERVATION_VIOLATION",
                        severity="CRITICAL",
                        affected_event_ids=[parent_id] + child_ids,
                        explanation=(
                            f"Parent event {parent_id} ({parent_evt['event_type']}) provided {parent_output} "
                            f"{parent_asset}, but child events consumed {total_consumed_by_children} "
                            f"{parent_asset} (overspend: {overspend} {parent_asset})."
                        ),
                    )
                )

        has_critical = any(d.severity == "CRITICAL" for d in discrepancies)
        return not has_critical, discrepancies


def build_trace_graph(db: Database, project_id: str) -> Dict[str, Any]:
    """
    Constructs the complete traceable graph for a project, including:
    - Flow events list
    - Directed edges (parent -> child)
    - Reconciled totals
    - Conservation discrepancies
    """
    proj = db.get_project(project_id)
    if not proj:
        return {
            "project_id": project_id,
            "status": "NOT_FOUND",
            "events": [],
            "edges": [],
            "summary": {},
            "discrepancies": [],
            "is_conserved": False,
        }

    raw_events = db.get_flow_events(project_id)
    is_conserved, discrepancies = TraceGraphReconciler.reconcile(raw_events)

    events_list: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    total_donated_wei = 0
    total_allocated_wei = 0
    total_offramped_usd_cents = 0
    total_paid_usd_cents = 0

    for e in raw_events:
        item = dict(e)
        if isinstance(item.get("metadata_json"), str):
            try:
                item["metadata"] = json.loads(item["metadata_json"])
            except Exception:
                item["metadata"] = {}
        else:
            item["metadata"] = {}

        events_list.append(item)

        if e.get("parent_event_id"):
            edges.append({"from": e["parent_event_id"], "to": e["event_id"]})

        etype = e["event_type"]
        if etype == "DONATION":
            total_donated_wei += int(e["output_amount"])
        elif etype == "ALLOCATION":
            total_allocated_wei += int(e["output_amount"])
        elif etype == "OFFRAMP":
            total_offramped_usd_cents += int(e["output_amount"])
        elif etype == "VENDOR_PAYMENT":
            total_paid_usd_cents += int(e["output_amount"])

    return {
        "project_id": proj["id"],
        "project_name": proj["name"],
        "purpose": proj["purpose"],
        "events": events_list,
        "edges": edges,
        "summary": {
            "total_donated_wei": str(total_donated_wei),
            "total_allocated_wei": str(total_allocated_wei),
            "total_offramped_usd_cents": total_offramped_usd_cents,
            "total_paid_usd_cents": total_paid_usd_cents,
            "verified_spend_wei": proj["verified_spend_wei"],
            "verified_spend_usd_cents": proj["verified_spend_usd_cents"],
        },
        "discrepancies": [d.to_dict() for d in discrepancies],
        "is_conserved": is_conserved,
    }
