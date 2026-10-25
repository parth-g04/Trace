"""
Invoice identity, nullifier calculation, and in-memory claim ledger for TRACE.

Enforces cross-report duplicate claim detection and cumulative claim limits.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union
import eth_abi
from eth_utils import keccak

from backend.app.services.canonical import (
    validate_bytes32,
    validate_monetary_value,
)


def compute_nullifier(vendor_id_bytes32: bytes, invoice_id_bytes32: bytes) -> bytes:
    """
    Computes canonical invoice nullifier:
    nullifier = keccak256(abi.encode(bytes32 vendorId, bytes32 invoiceId))

    CRITICAL SECURITY INVARIANTS:
    1. Uses standard ABI encoding (eth_abi.encode), equivalent to Solidity abi.encode.
       Does NOT use packed encoding (abi.encodePacked).
    2. Does NOT bind to projectId. Claims for the same vendor and invoice across
       different projects/donor reports produce identical nullifiers, preventing
       double-claiming.
    3. Does NOT include amounts, dates, categories, file hashes, or evidence commitments.
    """
    v_bytes = validate_bytes32(vendor_id_bytes32)
    i_bytes = validate_bytes32(invoice_id_bytes32)

    # Standard ABI encode of two bytes32 values produces exactly 64 bytes
    encoded = eth_abi.encode(["bytes32", "bytes32"], [v_bytes, i_bytes])
    return keccak(encoded)


@dataclass
class ClaimRecord:
    """Represents the ledger state for a single canonical invoice nullifier."""
    invoice_total: int
    claimed: int
    report_id: str


@dataclass
class ClaimOutcome:
    """Result of an invoice claim attempt."""
    success: bool
    reason: Optional[str] = None
    claimed_so_far: int = 0
    remaining_balance: int = 0


class InvoiceLedger:
    """
    In-memory ledger tracking invoice claims and enforcing cumulative spending limits.
    Designed for testability in Phase 1; to be replaced with SQLite in Phase 3.
    """

    def __init__(self) -> None:
        self._records: Dict[bytes, ClaimRecord] = {}

    def get_record(self, nullifier: Union[bytes, str]) -> Optional[ClaimRecord]:
        """Returns a copy of the claim record for the given nullifier, if present."""
        n_bytes = validate_bytes32(nullifier)
        rec = self._records.get(n_bytes)
        if rec is None:
            return None
        return ClaimRecord(
            invoice_total=rec.invoice_total,
            claimed=rec.claimed,
            report_id=rec.report_id,
        )

    def has_nullifier(self, nullifier: Union[bytes, str]) -> bool:
        """Checks if a nullifier has been registered in the ledger."""
        n_bytes = validate_bytes32(nullifier)
        return n_bytes in self._records

    def record_count(self) -> int:
        """Returns the number of unique invoices in the ledger."""
        return len(self._records)

    def try_claim(
        self,
        nullifier: Union[bytes, str],
        invoice_total: int,
        amount: int,
        report_id: str,
    ) -> ClaimOutcome:
        """
        Attempts to claim an amount against an invoice nullifier.

        Enforces:
        - Input validity for amounts and report_id.
        - Cross-report duplicate prevention (INVOICE_REUSED_ACROSS_REPORTS).
        - Invoice total consistency (INVOICE_TOTAL_MISMATCH).
        - Cumulative spending caps (CLAIM_EXCEEDS_INVOICE_TOTAL).
        - Exhaustion rejection (INVOICE_ALREADY_FULLY_CLAIMED).
        - Strict atomicity: state is never mutated on any rejection.
        """
        try:
            n_bytes = validate_bytes32(nullifier)
            val_total = validate_monetary_value(invoice_total)
            val_amount = validate_monetary_value(amount)
        except ValueError as err:
            return ClaimOutcome(
                success=False,
                reason="MALFORMED_RECEIPT",
                claimed_so_far=0,
                remaining_balance=0,
            )

        if not isinstance(report_id, str) or not report_id.strip():
            return ClaimOutcome(
                success=False,
                reason="MALFORMED_RECEIPT",
                claimed_so_far=0,
                remaining_balance=0,
            )
        clean_report_id = report_id.strip()

        # Check if nullifier already exists
        if n_bytes not in self._records:
            # First claim on this invoice
            if val_amount > val_total:
                return ClaimOutcome(
                    success=False,
                    reason="CLAIM_EXCEEDS_INVOICE_TOTAL",
                    claimed_so_far=0,
                    remaining_balance=val_total,
                )

            # Atomic creation
            self._records[n_bytes] = ClaimRecord(
                invoice_total=val_total,
                claimed=val_amount,
                report_id=clean_report_id,
            )
            return ClaimOutcome(
                success=True,
                reason=None,
                claimed_so_far=val_amount,
                remaining_balance=val_total - val_amount,
            )

        # Existing record check
        existing = self._records[n_bytes]

        # 1. Reject total tampering
        if val_total != existing.invoice_total:
            return ClaimOutcome(
                success=False,
                reason="INVOICE_TOTAL_MISMATCH",
                claimed_so_far=existing.claimed,
                remaining_balance=existing.invoice_total - existing.claimed,
            )

        # 2. Reject cross-report reuse
        if clean_report_id != existing.report_id:
            return ClaimOutcome(
                success=False,
                reason="INVOICE_REUSED_ACROSS_REPORTS",
                claimed_so_far=existing.claimed,
                remaining_balance=existing.invoice_total - existing.claimed,
            )

        # 3. Reject if already fully claimed
        if existing.claimed >= existing.invoice_total:
            return ClaimOutcome(
                success=False,
                reason="INVOICE_ALREADY_FULLY_CLAIMED",
                claimed_so_far=existing.claimed,
                remaining_balance=0,
            )

        # 4. Reject if cumulative amount exceeds invoice total
        if existing.claimed + val_amount > existing.invoice_total:
            return ClaimOutcome(
                success=False,
                reason="CLAIM_EXCEEDS_INVOICE_TOTAL",
                claimed_so_far=existing.claimed,
                remaining_balance=existing.invoice_total - existing.claimed,
            )

        # Atomic update
        existing.claimed += val_amount
        return ClaimOutcome(
            success=True,
            reason=None,
            claimed_so_far=existing.claimed,
            remaining_balance=existing.invoice_total - existing.claimed,
        )
