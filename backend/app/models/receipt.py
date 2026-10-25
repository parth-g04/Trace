"""
Receipt and EIP-712 Domain models for TRACE.

Implements validated canonical representations, bytes32 encodings,
and EIP-712 message mapping using Pydantic.
"""
from typing import Any, Dict, Union
from eth_utils import is_address, to_checksum_address
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.services.canonical import (
    id32,
    id32_hex,
    normalize_category,
    normalize_currency,
    normalize_identifier,
    normalize_invoice_id,
    validate_bytes32,
    validate_monetary_value,
    validate_timestamp,
)
from backend.app.services.invoice_identity import compute_nullifier


class EIP712Domain(BaseModel):
    """
    EIP-712 Domain Separator Configuration.
    Matches: EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)
    Supports both snake_case and camelCase field names.
    """
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    name: str = "TRACE Receipt Registry"
    version: str = "1"
    chain_id: int = Field(default=31337, alias="chainId")
    verifying_contract: str = Field(
        default="0x1111111111111111111111111111111111111111",
        alias="verifyingContract",
    )

    @field_validator("chain_id")
    @classmethod
    def validate_chain_id(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ValueError(f"chainId must be a positive integer, got {v!r}")
        return v

    @field_validator("verifying_contract")
    @classmethod
    def validate_contract_address(cls, v: Any) -> str:
        if not isinstance(v, str) or not is_address(v):
            raise ValueError(f"verifyingContract must be a valid Ethereum address: {v!r}")
        return to_checksum_address(v)

    def to_eip712_dict(self) -> Dict[str, Any]:
        """Returns domain data dictionary for eth-account encode_typed_data."""
        return {
            "name": self.name,
            "version": self.version,
            "chainId": self.chain_id,
            "verifyingContract": self.verifying_contract,
        }


class Receipt(BaseModel):
    """
    Validated Canonical Receipt Model.
    
    Ensures all fields adhere to canonical normalization rules upon creation.
    Provides canonical bytes32 representations for EIP-712 signing and Solidity interoperability.
    """
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    project_id: str
    vendor_id: str
    invoice_id: str
    invoice_total: int
    currency: str
    category: str
    issued_at: int
    evidence_commitment: str

    @field_validator("project_id")
    @classmethod
    def val_project_id(cls, v: Any) -> str:
        return normalize_identifier(v)

    @field_validator("vendor_id")
    @classmethod
    def val_vendor_id(cls, v: Any) -> str:
        return normalize_identifier(v)

    @field_validator("invoice_id")
    @classmethod
    def val_invoice_id(cls, v: Any) -> str:
        return normalize_invoice_id(v)

    @field_validator("invoice_total", mode="before")
    @classmethod
    def val_invoice_total(cls, v: Any) -> int:
        return validate_monetary_value(v)

    @field_validator("currency")
    @classmethod
    def val_currency(cls, v: Any) -> str:
        return normalize_currency(v)

    @field_validator("category")
    @classmethod
    def val_category(cls, v: Any) -> str:
        return normalize_category(v)

    @field_validator("issued_at", mode="before")
    @classmethod
    def val_issued_at(cls, v: Any) -> int:
        return validate_timestamp(v)

    @field_validator("evidence_commitment", mode="before")
    @classmethod
    def val_evidence_commitment(cls, v: Any) -> str:
        b = validate_bytes32(v)
        return "0x" + b.hex()

    # --- Canonical bytes32 representations for EIP-712 / Solidity ---

    @property
    def project_id_bytes32(self) -> bytes:
        return id32(self.project_id)

    @property
    def vendor_id_bytes32(self) -> bytes:
        return id32(self.vendor_id)

    @property
    def invoice_id_bytes32(self) -> bytes:
        return id32(self.invoice_id)

    @property
    def currency_bytes32(self) -> bytes:
        return id32(self.currency)

    @property
    def category_bytes32(self) -> bytes:
        return id32(self.category)

    @property
    def evidence_commitment_bytes(self) -> bytes:
        return validate_bytes32(self.evidence_commitment)

    # --- Nullifier ---

    @property
    def invoice_nullifier(self) -> bytes:
        """
        Global cross-report invoice nullifier:
        keccak256(abi.encode(bytes32 vendorId, bytes32 invoiceId))
        """
        return compute_nullifier(self.vendor_id_bytes32, self.invoice_id_bytes32)

    @property
    def invoice_nullifier_hex(self) -> str:
        return "0x" + self.invoice_nullifier.hex()

    def to_eip712_message(self) -> Dict[str, Any]:
        """
        Formats message payload for EIP-712 encode_typed_data.
        All string identifier fields are encoded to their canonical bytes32 representation.
        """
        return {
            "projectId": self.project_id_bytes32,
            "vendorId": self.vendor_id_bytes32,
            "invoiceId": self.invoice_id_bytes32,
            "invoiceTotal": self.invoice_total,
            "currency": self.currency_bytes32,
            "category": self.category_bytes32,
            "issuedAt": self.issued_at,
            "evidenceCommitment": self.evidence_commitment_bytes,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard serialized JSON-compatible dictionary."""
        return {
            "project_id": self.project_id,
            "vendor_id": self.vendor_id,
            "invoice_id": self.invoice_id,
            "invoice_total": self.invoice_total,
            "currency": self.currency,
            "category": self.category,
            "issued_at": self.issued_at,
            "evidence_commitment": self.evidence_commitment,
            "invoice_nullifier": self.invoice_nullifier_hex,
        }
