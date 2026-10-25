"""
Receipt verification and claim processing service for TRACE.

Orchestrates deterministic multi-step cryptographic verification:
structure, signature format/low-s, signer recovery, vendor registry,
category policy, timestamp freshness, evidence binding, and ledger claim execution.
"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Union
from eth_utils import is_address, to_checksum_address

from backend.app.models.receipt import EIP712Domain, Receipt

from backend.app.services.canonical import normalize_identifier
from backend.app.services.evidence import verify_evidence
from backend.app.services.invoice_identity import InvoiceLedger
from backend.app.services.signatures import (
    SignatureValidationError,
    recover_signer,
    validate_signature_format,
)


class VendorRegistry:
    """
    Registry mapping canonical vendor identifiers to authorized Ethereum addresses.
    """

    def __init__(self) -> None:
        self._vendors: Dict[str, str] = {}

    def register_vendor(self, vendor_id: str, address: str) -> None:
        """Registers a vendor ID with its authorized Ethereum address."""
        c_vendor = normalize_identifier(vendor_id)
        if not is_address(address):
            raise ValueError(f"Invalid Ethereum address: {address!r}")
        self._vendors[c_vendor] = to_checksum_address(address)

    def get_vendor_address(self, vendor_id: str) -> Optional[str]:
        """Looks up the registered address for a vendor ID."""
        try:
            c_vendor = normalize_identifier(vendor_id)
            return self._vendors.get(c_vendor)
        except Exception:
            return None

    def is_registered(self, vendor_id: str) -> bool:
        """Returns True if the vendor is registered."""
        return self.get_vendor_address(vendor_id) is not None


@dataclass
class VerificationResult:
    """Detailed result of receipt cryptographic and policy verification."""
    status: str  # "VERIFIED" or "REJECTED"
    reason: Optional[str] = None
    recovered_signer: Optional[str] = None
    checks: Dict[str, bool] = field(default_factory=dict)
    receipt_data: Optional[Dict[str, Any]] = None


@dataclass
class ClaimProcessResult:
    """Result of processing an expenditure claim against the invoice ledger."""
    status: str  # "VERIFIED" or "REJECTED"
    reason: Optional[str] = None
    verification_result: Optional[VerificationResult] = None
    claimed_amount: int = 0
    remaining_balance: int = 0
    checks: Dict[str, bool] = field(default_factory=dict)


def verify_receipt(
    receipt: Any,
    signature: Union[str, bytes],
    domain: EIP712Domain,
    registry: VendorRegistry,
    allowed_category: Union[str, Sequence[str]],
    now: int,
    file_bytes: Optional[bytes] = None,
    salt: Optional[bytes] = None,
) -> VerificationResult:
    """
    Verifies a vendor-signed receipt statement in strict deterministic order:
    1. Receipt structure & field validation.
    2. Signature format & low-s validation.
    3. EIP-712 signer recovery.
    4. Vendor registration check.
    5. Recovered signer equals registered vendor address.
    6. Category authorization check.
    7. Future timestamp policy check (issued_at > now + 86400).
    8. Optional evidence commitment check (fail-closed if partial data provided).

    Fails closed: any unexpected exception returns REJECTED with INTERNAL_ERROR.
    """
    checks: Dict[str, bool] = {
        "structure_valid": False,
        "signature_format_valid": False,
        "signature_valid": False,
        "vendor_registered": False,
        "signer_matches_vendor": False,
        "category_allowed": False,
        "timestamp_valid": False,
        "evidence_verified": False,
    }

    try:
        from backend.app.models.receipt import Receipt

        # 1. Structure & Field Validation
        if isinstance(receipt, Receipt):
            rec = receipt
        elif isinstance(receipt, dict):
            try:
                rec = Receipt(**receipt)
            except Exception:
                return VerificationResult(
                    status="REJECTED",
                    reason="MALFORMED_RECEIPT",
                    checks=checks,
                )
        else:
            return VerificationResult(
                status="REJECTED",
                reason="MALFORMED_RECEIPT",
                checks=checks,
            )
        checks["structure_valid"] = True

        # 2. Signature format & low-s validation
        try:
            validate_signature_format(signature)
            checks["signature_format_valid"] = True
        except SignatureValidationError:
            return VerificationResult(
                status="REJECTED",
                reason="MALFORMED_SIGNATURE",
                checks=checks,
                receipt_data=rec.to_dict(),
            )

        # 3. EIP-712 Signer Recovery
        try:
            recovered_signer = recover_signer(rec, signature, domain)
            checks["signature_valid"] = True
        except SignatureValidationError:
            return VerificationResult(
                status="REJECTED",
                reason="SIGNATURE_INVALID",
                checks=checks,
                receipt_data=rec.to_dict(),
            )

        # 4. Vendor Registration
        registered_address = registry.get_vendor_address(rec.vendor_id)
        if registered_address is None:
            return VerificationResult(
                status="REJECTED",
                reason="UNREGISTERED_VENDOR",
                recovered_signer=recovered_signer,
                checks=checks,
                receipt_data=rec.to_dict(),
            )
        checks["vendor_registered"] = True

        # 5. Signer matches registered vendor
        if recovered_signer.lower() != registered_address.lower():
            return VerificationResult(
                status="REJECTED",
                reason="SIGNER_VENDOR_MISMATCH",
                recovered_signer=recovered_signer,
                checks=checks,
                receipt_data=rec.to_dict(),
            )
        checks["signer_matches_vendor"] = True

        # 6. Category Authorization
        if isinstance(allowed_category, str):
            allowed_set = {allowed_category.strip().upper()}
        else:
            allowed_set = {c.strip().upper() for c in allowed_category}

        if rec.category not in allowed_set:
            return VerificationResult(
                status="REJECTED",
                reason="CATEGORY_NOT_ALLOWED",
                recovered_signer=recovered_signer,
                checks=checks,
                receipt_data=rec.to_dict(),
            )
        checks["category_allowed"] = True

        # 7. Future Timestamp Policy (reject if issued_at > now + 86400 seconds)
        if rec.issued_at > (now + 86400):
            return VerificationResult(
                status="REJECTED",
                reason="DATED_IN_FUTURE",
                recovered_signer=recovered_signer,
                checks=checks,
                receipt_data=rec.to_dict(),
            )
        checks["timestamp_valid"] = True

        # 8. Optional Evidence Commitment Verification
        # If both are provided, verify them.
        # If only one is provided, fail closed (MALFORMED_EVIDENCE).
        # If neither is provided, check is not performed (checks['evidence_verified'] remains False).
        if file_bytes is not None and salt is not None:
            if not verify_evidence(file_bytes, salt, rec.evidence_commitment):
                return VerificationResult(
                    status="REJECTED",
                    reason="EVIDENCE_COMMITMENT_MISMATCH",
                    recovered_signer=recovered_signer,
                    checks=checks,
                    receipt_data=rec.to_dict(),
                )
            checks["evidence_verified"] = True
        elif (file_bytes is not None and salt is None) or (file_bytes is None and salt is not None):
            return VerificationResult(
                status="REJECTED",
                reason="MALFORMED_EVIDENCE",
                recovered_signer=recovered_signer,
                checks=checks,
                receipt_data=rec.to_dict(),
            )

        # All required verification checks passed
        return VerificationResult(
            status="VERIFIED",
            reason=None,
            recovered_signer=recovered_signer,
            checks=checks,
            receipt_data=rec.to_dict(),
        )

    except Exception:
        # Outermost boundary fail-closed protection
        return VerificationResult(
            status="REJECTED",
            reason="INTERNAL_ERROR",
            checks=checks,
        )


def process_claim(
    receipt: Any,
    signature: Union[str, bytes],
    domain: EIP712Domain,
    registry: VendorRegistry,
    allowed_category: Union[str, Sequence[str]],
    now: int,
    ledger: InvoiceLedger,
    claim_amount: int,
    report_id: str,
    file_bytes: Optional[bytes] = None,
    salt: Optional[bytes] = None,
) -> ClaimProcessResult:
    """
    Processes an expenditure claim against the invoice ledger.

    Strict Order:
    1. Validates and verifies receipt via verify_receipt.
    2. Rejects immediately if any verification check fails; does not touch ledger.
    3. If verified, executes claim against ledger.
    4. Returns exact rejection reason if claim is rejected.
    """
    checks: Dict[str, bool] = {
        "receipt_verified": False,
        "ledger_claim_valid": False,
    }

    try:
        # Step 1: Verify receipt
        v_res = verify_receipt(
            receipt=receipt,
            signature=signature,
            domain=domain,
            registry=registry,
            allowed_category=allowed_category,
            now=now,
            file_bytes=file_bytes,
            salt=salt,
        )

        checks.update(v_res.checks)

        if v_res.status != "VERIFIED":
            return ClaimProcessResult(
                status="REJECTED",
                reason=v_res.reason,
                verification_result=v_res,
                checks=checks,
            )

        checks["receipt_verified"] = True

        # Extract verified receipt object
        if isinstance(receipt, Receipt):
            rec = receipt
        else:
            rec = Receipt(**receipt)

        # Step 2: Attempt ledger claim
        outcome = ledger.try_claim(
            nullifier=rec.invoice_nullifier,
            invoice_total=rec.invoice_total,
            amount=claim_amount,
            report_id=report_id,
        )

        if not outcome.success:
            return ClaimProcessResult(
                status="REJECTED",
                reason=outcome.reason,
                verification_result=v_res,
                claimed_amount=outcome.claimed_so_far,
                remaining_balance=outcome.remaining_balance,
                checks=checks,
            )

        checks["ledger_claim_valid"] = True
        return ClaimProcessResult(
            status="VERIFIED",
            reason=None,
            verification_result=v_res,
            claimed_amount=outcome.claimed_so_far,
            remaining_balance=outcome.remaining_balance,
            checks=checks,
        )

    except Exception:
        return ClaimProcessResult(
            status="REJECTED",
            reason="INTERNAL_ERROR",
            checks=checks,
        )
