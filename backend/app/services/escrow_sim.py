"""
=============================================================================
SIMULATION NOTICE: NOT ON-CHAIN SETTLEMENT
This module implements a simulated purpose-bound escrow vault for TRACE
Phase 1 / Milestone 1 testing and demonstration.

It enforces tranche disbursement conditions, multi-tranche cumulative budget
checks, and automatic freeze triggers on security violations in Python memory/SQLite.

ON-CHAIN SOLIDITY ENFORCEMENT (TraceEscrow.sol) IS DEFERRED TO PHASE 2.
THIS IS A PROTOTYPE SIMULATION AND MUST NOT BE USED FOR REAL ASSET CUSTODY.
=============================================================================
"""
from typing import Any, Dict, Optional, Tuple

from backend.app.db import Database


# Escrow constants for demo project WATER-001
DEFAULT_PROJECT_ID = "WATER-001"
DEFAULT_PURPOSE = "WATER_INFRASTRUCTURE"
DEFAULT_FUNDING_WEI = 50 * 10**18  # 50 ETH
DEFAULT_TRANCHES = 5
DEFAULT_TRANCHE_SIZE_WEI = 10 * 10**18  # 10 ETH
ETH_USD_RATE_CENTS = 200000  # $2,000.00 USD per 1 ETH
WEI_PER_USD_CENT = (10**18) // ETH_USD_RATE_CENTS  # 5 * 10**12 wei per cent (exact integer)


def convert_usd_cents_to_wei(usd_cents: int) -> int:
    """
    Converts USD minor units (cents) to Ethereum wei using integer arithmetic.
    1 ETH = $2,000.00 (200,000 cents).
    wei = cents * 10**18 // 200,000 = cents * 5,000,000,000,000.
    """
    if not isinstance(usd_cents, int) or isinstance(usd_cents, bool) or usd_cents < 0:
        raise ValueError(f"Amount in USD cents must be a non-negative integer, got {usd_cents!r}")
    return usd_cents * WEI_PER_USD_CENT


def convert_wei_to_usd_cents(wei: int) -> int:
    """
    Converts Ethereum wei to USD minor units (cents) using integer arithmetic.
    cents = wei // (5 * 10**12).
    """
    if not isinstance(wei, int) or isinstance(wei, bool) or wei < 0:
        raise ValueError(f"Amount in wei must be a non-negative integer, got {wei!r}")
    return wei // WEI_PER_USD_CENT


class SimulatedEscrowService:
    """
    Simulated Escrow Service managing tranche releases and spending conditions.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def evaluate_release(self, project_id: str) -> Dict[str, Any]:
        """
        Evaluates whether the next tranche for a project can be released,
        without performing the release state mutation.
        """
        proj = self.db.get_project(project_id)
        if not proj:
            return {
                "disbursement_allowed": False,
                "status": "BLOCKED",
                "reason": "PROJECT_NOT_FOUND",
                "explanation": f"Project '{project_id}' does not exist in registry.",
            }

        if proj["is_frozen"]:
            return {
                "disbursement_allowed": False,
                "status": "BLOCKED",
                "reason": "PROJECT_FROZEN",
                "explanation": f"Cannot release tranche: Project is frozen due to: {proj['freeze_reason']}",
            }

        current_tranche = proj["current_tranche"]
        total_tranches = proj["total_tranches"]
        if current_tranche >= total_tranches:
            return {
                "disbursement_allowed": False,
                "status": "BLOCKED",
                "reason": "ALL_TRANCHES_RELEASED",
                "explanation": f"All {total_tranches} tranches have already been disbursed.",
            }

        next_tranche = current_tranche + 1
        released_wei = int(proj["released_wei"])
        verified_spend_wei = int(proj["verified_spend_wei"])

        # Tranche 1 release rule
        if current_tranche == 0:
            return {
                "disbursement_allowed": True,
                "status": "READY",
                "reason": None,
                "explanation": "Initial Tranche 1 is ready for disbursement without prior verified spending.",
                "next_tranche": next_tranche,
                "released_wei": released_wei,
                "verified_spend_wei": verified_spend_wei,
            }

        # Subsequent tranches rule: verified spending must cover all previously released funds
        if verified_spend_wei < released_wei:
            deficit_wei = released_wei - verified_spend_wei
            deficit_usd_cents = convert_wei_to_usd_cents(deficit_wei)
            return {
                "disbursement_allowed": False,
                "status": "BLOCKED",
                "reason": "INSUFFICIENT_VERIFIED_SPEND",
                "explanation": (
                    f"Tranche {next_tranche} requires verified spending covering all prior releases "
                    f"({released_wei} wei). Current verified spend is {verified_spend_wei} wei "
                    f"(deficit: {deficit_wei} wei / approx ${deficit_usd_cents / 100:.2f})."
                ),
                "next_tranche": next_tranche,
                "released_wei": released_wei,
                "verified_spend_wei": verified_spend_wei,
                "deficit_wei": deficit_wei,
            }

        return {
            "disbursement_allowed": True,
            "status": "READY",
            "reason": None,
            "explanation": f"Tranche {next_tranche} is ready for release. Spending requirements met.",
            "next_tranche": next_tranche,
            "released_wei": released_wei,
            "verified_spend_wei": verified_spend_wei,
        }

    def release_next_tranche(self, project_id: str) -> Dict[str, Any]:
        """
        Executes the release of the next tranche if conditions are met.
        Delegates atomic state updates, flow events, and audit logging to Database.
        """
        return self.db.release_next_tranche(project_id)
