"""
EIP-712 typed receipt signing and fail-closed signature verification service for TRACE.

Implements EIP-712 domain binding, primary type definitions, strict signature length/format
validation, low-s enforcement (preventing ECDSA malleability), and signer address recovery.
"""
from typing import TYPE_CHECKING, Any, Dict, Union
from eth_account import Account
from eth_account.messages import SignableMessage, encode_typed_data
import eth_keys
from eth_utils import is_address, is_hex, to_bytes, to_checksum_address

if TYPE_CHECKING:
    from backend.app.models.receipt import EIP712Domain, Receipt

# Secp256k1 curve parameters
SECP256K1_N = eth_keys.constants.SECPK1_N
SECP256K1_HALF_N = SECP256K1_N // 2

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Canonical EIP-712 Type String (without whitespace or newlines)
RECEIPT_TYPE_STRING = (
    "Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,"
    "uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,"
    "bytes32 evidenceCommitment)"
)

# EIP-712 Type definitions for eth-account encode_typed_data
EIP712_TYPES: Dict[str, Any] = {
    "Receipt": [
        {"name": "projectId", "type": "bytes32"},
        {"name": "vendorId", "type": "bytes32"},
        {"name": "invoiceId", "type": "bytes32"},
        {"name": "invoiceTotal", "type": "uint256"},
        {"name": "currency", "type": "bytes32"},
        {"name": "category", "type": "bytes32"},
        {"name": "issuedAt", "type": "uint64"},
        {"name": "evidenceCommitment", "type": "bytes32"},
    ]
}


class SignatureValidationError(ValueError):
    """Raised when a signature fails cryptographic or structural validation."""
    pass


def build_typed_data(receipt: Any, domain: Any) -> SignableMessage:
    """
    Builds the EIP-712 typed data SignableMessage using eth-account.
    Supports Receipt and EIP712Domain instances as well as equivalent dicts.
    """
    if hasattr(receipt, "to_eip712_message"):
        msg_data = receipt.to_eip712_message()
    elif isinstance(receipt, dict):
        msg_data = receipt
    else:
        raise TypeError(f"Invalid receipt type: {type(receipt).__name__}")

    if hasattr(domain, "to_eip712_dict"):
        domain_data = domain.to_eip712_dict()
    elif isinstance(domain, dict):
        domain_data = domain
    else:
        raise TypeError(f"Invalid domain type: {type(domain).__name__}")

    return encode_typed_data(
        domain_data=domain_data,
        message_types=EIP712_TYPES,
        message_data=msg_data,
    )


def validate_signature_format(signature: Union[str, bytes]) -> bytes:
    """
    Validates a signature fail-closed:
    1. Exactly 65 bytes (r: 32 bytes, s: 32 bytes, v: 1 byte).
    2. Hex format validity without unexpected characters.
    3. Recovery identifier v must be exactly 27 or 28 in normalized serialized form.
    4. Enforces low-s: rejects high-s signatures where s > SECP256K1_N / 2 to prevent malleability.
    5. Enforces valid range: 1 <= r < SECP256K1_N and 1 <= s <= SECP256K1_HALF_N.
    """
    if isinstance(signature, str):
        sig_str = signature.strip()
        if not is_hex(sig_str):
            raise SignatureValidationError(f"Signature is not valid hex: {signature!r}")
        if sig_str.startswith(("0x", "0X")):
            sig_str = sig_str[2:]
        if len(sig_str) != 130:
            raise SignatureValidationError(
                f"Signature hex string must be exactly 130 hex characters (65 bytes), got {len(sig_str)}"
            )
        try:
            sig_bytes = bytes.fromhex(sig_str)
        except ValueError as e:
            raise SignatureValidationError(f"Invalid hex characters in signature: {e}") from e
    elif isinstance(signature, (bytes, bytearray)):
        sig_bytes = bytes(signature)
        if len(sig_bytes) != 65:
            raise SignatureValidationError(
                f"Signature bytes must be exactly 65 bytes, got {len(sig_bytes)}"
            )
    else:
        raise SignatureValidationError(
            f"Signature must be a hex string or bytes, got {type(signature).__name__}"
        )

    r = int.from_bytes(sig_bytes[:32], "big")
    s = int.from_bytes(sig_bytes[32:64], "big")
    v = sig_bytes[64]

    # Validate v
    if v not in (27, 28):
        raise SignatureValidationError(
            f"Recovery identifier v must be 27 or 28, got {v}"
        )

    # Validate r
    if r < 1 or r >= SECP256K1_N:
        raise SignatureValidationError(
            f"Signature r value out of bounds: {r}"
        )

    # Validate low-s (crucial malleability defense)
    if s < 1 or s > SECP256K1_HALF_N:
        raise SignatureValidationError(
            f"Signature rejected: high-s detected (s > secp256k1n / 2). "
            f"s={s}, half_n={SECP256K1_HALF_N}"
        )

    return sig_bytes


def sign_receipt(receipt: Receipt, private_key: Union[str, bytes], domain: EIP712Domain) -> str:
    """
    Signs a canonical receipt using an EIP-712 domain and private key.
    Returns 0x-prefixed 130-hex-character serialized 65-byte signature.
    """
    signable = build_typed_data(receipt, domain)
    signed_msg = Account.sign_message(signable, private_key)
    sig_bytes = signed_msg.signature

    # Validate before returning
    validated = validate_signature_format(sig_bytes)
    return "0x" + validated.hex()


def recover_signer(receipt: Receipt, signature: Union[str, bytes], domain: EIP712Domain) -> str:
    """
    Recovers the Ethereum checksum address of the signer from receipt and signature.
    Fails closed on format errors, high-s, invalid v, or recovery failures.
    """
    valid_sig = validate_signature_format(signature)
    signable = build_typed_data(receipt, domain)

    try:
        recovered = Account.recover_message(signable, signature=valid_sig)
    except Exception as e:
        raise SignatureValidationError(f"Cryptographic recovery failed: {e}") from e

    if not recovered or recovered.lower() == ZERO_ADDRESS.lower():
        raise SignatureValidationError("Signer recovered as zero address")

    return to_checksum_address(recovered)
