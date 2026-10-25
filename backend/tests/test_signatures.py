"""
Comprehensive cryptographic security tests for EIP-712 signatures.
"""
import pytest
import eth_abi
from eth_account import Account
from eth_account.messages import _hash_eip191_message
from eth_utils import keccak, to_checksum_address

from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import (
    SECP256K1_HALF_N,
    SECP256K1_N,
    SignatureValidationError,
    build_typed_data,
    recover_signer,
    sign_receipt,
    validate_signature_format,
)

# Test-only deterministic keypair (Hardhat Account #0)
TEST_PRIV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
EXPECTED_SIGNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# Secondary test keypair (Hardhat Account #1)
SECONDARY_PRIV_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
SECONDARY_SIGNER = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@pytest.fixture
def default_domain():
    return EIP712Domain(
        name="TRACE Receipt Registry",
        version="1",
        chain_id=31337,
        verifying_contract="0x1111111111111111111111111111111111111111",
    )


@pytest.fixture
def valid_receipt():
    return Receipt(
        project_id="PROJECT-ALPHA",
        vendor_id="ACME-DRILLING",
        invoice_id="INV-1042",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=1714000000,
        evidence_commitment="0x" + "aa" * 32,
    )


def test_valid_signature_recovery(valid_receipt, default_domain):
    """A valid signature recovers the exact expected Ethereum address."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)
    recovered = recover_signer(valid_receipt, sig, default_domain)
    assert recovered.lower() == EXPECTED_SIGNER.lower()


def test_different_key_recovers_different_address(valid_receipt, default_domain):
    """Signing with a different private key recovers that key's address, not the vendor."""
    sig = sign_receipt(valid_receipt, SECONDARY_PRIV_KEY, default_domain)
    recovered = recover_signer(valid_receipt, sig, default_domain)
    assert recovered.lower() == SECONDARY_SIGNER.lower()
    assert recovered.lower() != EXPECTED_SIGNER.lower()


@pytest.mark.parametrize(
    "tamper_field,tamper_value",
    [
        ("project_id", "PROJECT-BETA"),
        ("vendor_id", "MALICIOUS-VENDOR"),
        ("invoice_id", "INV-9999"),
        ("invoice_total", 999999),
        ("currency", "EUR"),
        ("category", "FOOD_SUPPLIES"),
        ("issued_at", 1714000001),
        ("evidence_commitment", "0x" + "bb" * 32),
    ],
)
def test_all_fields_are_tamper_evident(valid_receipt, default_domain, tamper_field, tamper_value):
    """
    Tampering with ANY field of the signed receipt causes signer recovery to yield
    a different (invalid) address, proving complete cryptographic integrity.
    """
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)

    # Create tampered receipt
    data = valid_receipt.to_dict()
    data[tamper_field] = tamper_value
    tampered_receipt = Receipt(**data)

    recovered_tampered = recover_signer(tampered_receipt, valid_sig, default_domain)
    assert recovered_tampered.lower() != EXPECTED_SIGNER.lower()


def test_wrong_domain_chain_id(valid_receipt, default_domain):
    """Signatures are bound to chainId; mismatched chainId causes recovery mismatch."""
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)

    wrong_domain = EIP712Domain(
        name=default_domain.name,
        version=default_domain.version,
        chain_id=1,  # Mainnet instead of 31337
        verifying_contract=default_domain.verifying_contract,
    )
    recovered = recover_signer(valid_receipt, valid_sig, wrong_domain)
    assert recovered.lower() != EXPECTED_SIGNER.lower()


def test_wrong_verifying_contract(valid_receipt, default_domain):
    """Signatures are bound to verifyingContract; mismatched address causes recovery mismatch."""
    valid_sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)

    wrong_domain = EIP712Domain(
        name=default_domain.name,
        version=default_domain.version,
        chain_id=default_domain.chain_id,
        verifying_contract="0x2222222222222222222222222222222222222222",
    )
    recovered = recover_signer(valid_receipt, valid_sig, wrong_domain)
    assert recovered.lower() != EXPECTED_SIGNER.lower()


def test_malformed_signatures_rejected(valid_receipt, default_domain):
    """Fail-closed rejection on invalid signature lengths and encodings."""
    # 1. Empty signature
    with pytest.raises(SignatureValidationError):
        validate_signature_format("")

    # 2. Garbage text
    with pytest.raises(SignatureValidationError):
        validate_signature_format("not-a-hex-signature")

    # 3. 64-byte signature (missing v)
    with pytest.raises(SignatureValidationError):
        validate_signature_format("0x" + "aa" * 64)

    # 4. 66-byte signature (too long)
    with pytest.raises(SignatureValidationError):
        validate_signature_format("0x" + "aa" * 66)

    # 5. Invalid hex characters
    with pytest.raises(SignatureValidationError):
        validate_signature_format("0x" + "zz" * 65)


def test_invalid_v_recovery_identifier(valid_receipt, default_domain):
    """Recovery identifier v must be exactly 27 or 28."""
    sig = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)
    raw = bytes.fromhex(sig[2:])

    for bad_v in [0, 1, 26, 29, 30, 255]:
        bad_sig = raw[:64] + bytes([bad_v])
        with pytest.raises(SignatureValidationError, match="Recovery identifier v"):
            validate_signature_format(bad_sig)


def test_high_s_malleated_signature_rejected(valid_receipt, default_domain):
    """
    GENUINE HIGH-S SIGNATURE MALLEABILITY TEST.
    Constructs a mathematically valid secp256k1 signature where s' = N - s > N/2.
    Proves that our explicit low-s validation rule rejects it fail-closed.
    """
    valid_sig_hex = sign_receipt(valid_receipt, TEST_PRIV_KEY, default_domain)
    valid_sig_bytes = bytes.fromhex(valid_sig_hex[2:])

    r = int.from_bytes(valid_sig_bytes[:32], "big")
    s = int.from_bytes(valid_sig_bytes[32:64], "big")
    v = valid_sig_bytes[64]

    # Confirm original signature has low-s
    assert s <= SECP256K1_HALF_N

    # Construct mathematically related high-s signature
    high_s = SECP256K1_N - s
    assert high_s > SECP256K1_HALF_N
    malleated_v = 28 if v == 27 else 27

    malleated_sig = valid_sig_bytes[:32] + high_s.to_bytes(32, "big") + bytes([malleated_v])
    assert len(malleated_sig) == 65

    # Standard eth_account would recover the same signer from this malleated signature:
    signable = build_typed_data(valid_receipt, default_domain)
    recovered_from_malleated = Account.recover_message(signable, signature=malleated_sig)
    assert recovered_from_malleated.lower() == EXPECTED_SIGNER.lower()

    # But our strict validate_signature_format MUST REJECT IT!
    with pytest.raises(SignatureValidationError, match="high-s detected"):
        validate_signature_format(malleated_sig)

    with pytest.raises(SignatureValidationError, match="high-s detected"):
        recover_signer(valid_receipt, malleated_sig, default_domain)


def test_independent_eip712_digest_calculation(valid_receipt, default_domain):
    """
    INDEPENDENT EIP-712 DIGEST RECOMPUTATION.
    Independently recomputes domain separator, primary type hash, struct hash,
    and final 0x1901 digest using eth_abi and keccak, without using eth-account helpers.
    Compares against eth-account's internal SignableMessage.
    """
    # 1. Independent Domain Separator
    domain_type_str = b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    domain_type_hash = keccak(domain_type_str)
    domain_separator = keccak(
        eth_abi.encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                domain_type_hash,
                keccak(default_domain.name.encode("utf-8")),
                keccak(default_domain.version.encode("utf-8")),
                default_domain.chain_id,
                to_checksum_address(default_domain.verifying_contract),
            ],
        )
    )

    # 2. Independent Primary Type Hash & Struct Hash
    receipt_type_str = (
        b"Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,"
        b"uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,"
        b"bytes32 evidenceCommitment)"
    )
    receipt_type_hash = keccak(receipt_type_str)
    struct_hash = keccak(
        eth_abi.encode(
            [
                "bytes32",
                "bytes32",
                "bytes32",
                "bytes32",
                "uint256",
                "bytes32",
                "bytes32",
                "uint64",
                "bytes32",
            ],
            [
                receipt_type_hash,
                valid_receipt.project_id_bytes32,
                valid_receipt.vendor_id_bytes32,
                valid_receipt.invoice_id_bytes32,
                valid_receipt.invoice_total,
                valid_receipt.currency_bytes32,
                valid_receipt.category_bytes32,
                valid_receipt.issued_at,
                valid_receipt.evidence_commitment_bytes,
            ],
        )
    )

    # 3. Independent 0x1901 Digest
    independent_digest = keccak(b"\x19\x01" + domain_separator + struct_hash)

    # 4. eth-account SignableMessage Digest
    signable = build_typed_data(valid_receipt, default_domain)
    eth_account_digest = _hash_eip191_message(signable)

    assert signable.header == domain_separator
    assert signable.body == struct_hash
    assert eth_account_digest == independent_digest
