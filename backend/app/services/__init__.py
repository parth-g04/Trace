"""
TRACE Core Services Package.
"""
from backend.app.services.canonical import (
    ALLOWED_CATEGORIES,
    id32,
    id32_hex,
    normalize_category,
    normalize_currency,
    normalize_identifier,
    normalize_invoice_id,
    normalize_text,
    validate_bytes32,
    validate_monetary_value,
    validate_timestamp,
)
from backend.app.services.signatures import (
    SECP256K1_HALF_N,
    SECP256K1_N,
    ZERO_ADDRESS,
    build_typed_data,
    recover_signer,
    sign_receipt,
    validate_signature_format,
)
from backend.app.services.invoice_identity import (
    ClaimOutcome,
    ClaimRecord,
    InvoiceLedger,
    compute_nullifier,
)
from backend.app.services.evidence import (
    compute_evidence_commitment,
    generate_salt,
    verify_evidence,
)
def __getattr__(name: str):
    if name in {"ClaimProcessResult", "VendorRegistry", "VerificationResult", "process_claim", "verify_receipt"}:
        import backend.app.services.verification as v
        return getattr(v, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ALLOWED_CATEGORIES",
    "normalize_text",
    "normalize_identifier",
    "normalize_invoice_id",
    "normalize_currency",
    "normalize_category",
    "validate_monetary_value",
    "validate_timestamp",
    "validate_bytes32",
    "id32",
    "id32_hex",
    "SECP256K1_N",
    "SECP256K1_HALF_N",
    "ZERO_ADDRESS",
    "build_typed_data",
    "sign_receipt",
    "validate_signature_format",
    "recover_signer",
    "compute_nullifier",
    "ClaimRecord",
    "InvoiceLedger",
    "ClaimOutcome",
    "compute_evidence_commitment",
    "generate_salt",
    "verify_evidence",
    "VendorRegistry",
    "VerificationResult",
    "ClaimProcessResult",
    "verify_receipt",
    "process_claim",
]
