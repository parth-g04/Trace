#!/usr/bin/env python3
"""
Test vector generator for TRACE Phase 1.

Generates reproducible, deterministic test vectors for cross-language validation
(Python backend and Solidity smart contracts in Phase 2).

CRITICAL NOTICE:
The private key used in this script is the well-known, public Hardhat Account #0
testing key. It is strictly for local unit tests and fixture generation.
NEVER use this key with real funds or on any public network.
"""
import json
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from eth_account.messages import _hash_eip191_message

from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.evidence import compute_evidence_commitment
from backend.app.services.signatures import build_typed_data, recover_signer, sign_receipt

# Well-known public Hardhat testing key #0 - TEST FIXTURE ONLY
TEST_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)
EXPECTED_TEST_SIGNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

TEST_DOMAIN = EIP712Domain(
    name="TRACE Receipt Registry",
    version="1",
    chain_id=31337,
    verifying_contract="0x1111111111111111111111111111111111111111",
)

RAW_VECTORS = [
    {
        "description": "Standard clean receipt for water infrastructure project",
        "raw_input": {
            "project_id": "PROJECT-KENYA-WATER",
            "vendor_id": "ACME-DRILLING-CORP",
            "invoice_id": "INV-1042",
            "invoice_total": 500000,
            "currency": "usd",
            "category": "water_infrastructure",
            "issued_at": 1714000000,
        },
        "evidence_text": "INVOICE #INV-1042: Deep well drilling services in Turkana Basin.",
        "salt_hex": "0x" + "11" * 32,
    },
    {
        "description": "Invoice with lowercase text, spaces, and leading zeros in invoice ID",
        "raw_input": {
            "project_id": "proj relief 2026",
            "vendor_id": "grain suppliers ltd",
            "invoice_id": "inv-001042",
            "invoice_total": "1250000",
            "currency": "EUR",
            "category": "FOOD_SUPPLIES",
            "issued_at": 1714050000,
        },
        "evidence_text": "INVOICE #inv-001042: 50 metric tons emergency sorghum delivery.",
        "salt_hex": "0x" + "22" * 32,
    },
    {
        "description": "High-value medical emergency supplies in Indian Rupees",
        "raw_input": {
            "project_id": "HEALTH-CLINIC-BIHAR",
            "vendor_id": "PHARMA-DIRECT",
            "invoice_id": "MED-00089",
            "invoice_total": 98500000,
            "currency": "INR",
            "category": "MEDICAL_SUPPLIES",
            "issued_at": 1714100000,
        },
        "evidence_text": "INVOICE #MED-00089: Critical antibiotics and surgical supplies.",
        "salt_hex": "0x" + "33" * 32,
    },
    {
        "description": "School education supplies with alphanumeric invoice number",
        "raw_input": {
            "project_id": "SCHOOLS-2026",
            "vendor_id": "GLOBAL-BOOKS-LTD",
            "invoice_id": "EDU-007A009",
            "invoice_total": 75000,
            "currency": "USD",
            "category": "EDUCATION",
            "issued_at": 1714150000,
        },
        "evidence_text": "INVOICE #EDU-007A009: STEM textbooks and student learning kits.",
        "salt_hex": "0x" + "44" * 32,
    },
]


def generate_vectors():
    vectors = []

    for idx, item in enumerate(RAW_VECTORS, start=1):
        raw = item["raw_input"]
        evidence_bytes = item["evidence_text"].encode("utf-8")
        salt_bytes = bytes.fromhex(item["salt_hex"][2:])

        # Compute commitment
        commitment_bytes = compute_evidence_commitment(evidence_bytes, salt_bytes)
        commitment_hex = "0x" + commitment_bytes.hex()

        # Build canonical receipt
        receipt = Receipt(
            project_id=raw["project_id"],
            vendor_id=raw["vendor_id"],
            invoice_id=raw["invoice_id"],
            invoice_total=raw["invoice_total"],
            currency=raw["currency"],
            category=raw["category"],
            issued_at=raw["issued_at"],
            evidence_commitment=commitment_hex,
        )

        # Build typed data and compute EIP-712 digest
        signable = build_typed_data(receipt, TEST_DOMAIN)
        digest = _hash_eip191_message(signable)

        # Sign receipt
        signature = sign_receipt(receipt, TEST_PRIVATE_KEY, TEST_DOMAIN)
        recovered_signer = recover_signer(receipt, signature, TEST_DOMAIN)
        assert recovered_signer.lower() == EXPECTED_TEST_SIGNER.lower()

        vector_record = {
            "vector_id": idx,
            "description": item["description"],
            "test_key_notice": "Public Hardhat Account #0 (TEST ONLY)",
            "test_signer_address": EXPECTED_TEST_SIGNER,
            "domain": TEST_DOMAIN.to_eip712_dict(),
            "raw_input": raw,
            "canonical_receipt": receipt.to_dict(),
            "bytes32_encodings": {
                "projectId": "0x" + receipt.project_id_bytes32.hex(),
                "vendorId": "0x" + receipt.vendor_id_bytes32.hex(),
                "invoiceId": "0x" + receipt.invoice_id_bytes32.hex(),
                "currency": "0x" + receipt.currency_bytes32.hex(),
                "category": "0x" + receipt.category_bytes32.hex(),
                "evidenceCommitment": receipt.evidence_commitment,
            },
            "eip712_digest": "0x" + digest.hex(),
            "signature": signature,
            "recovered_signer": recovered_signer,
            "invoice_nullifier": receipt.invoice_nullifier_hex,
            "evidence": {
                "salt": item["salt_hex"],
                "file_text": item["evidence_text"],
                "commitment": commitment_hex,
            },
        }
        vectors.append(vector_record)

    return {
        "title": "TRACE Phase 1 Canonical Receipt Test Vectors",
        "version": "1.0.0",
        "notice": "Generated for Phase 1 verification and Phase 2 Solidity interoperability tests.",
        "domain_type_string": "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)",
        "receipt_type_string": "Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,bytes32 evidenceCommitment)",
        "vectors": vectors,
    }


def main():
    output_path = root_dir / "docs" / "test-vectors" / "phase1.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = generate_vectors()
    json_content = json.dumps(data, indent=2, sort_keys=True) + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_content)

    print(f"Generated {len(data['vectors'])} test vectors in {output_path}")


if __name__ == "__main__":
    main()
