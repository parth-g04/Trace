"""
Pydantic API request and response models for TRACE REST API.

Enforces strict type validation, prevents private data leakage,
and provides structured error reporting.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str = "healthy"
    version: str = "0.1.0"
    simulation_mode: bool = True
    database: str = "connected"
    timestamp: int


class ProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    purpose: str
    funding_wei: str
    total_tranches: int
    current_tranche: int
    released_wei: str
    verified_spend_wei: str
    verified_spend_usd_cents: int
    is_frozen: bool
    freeze_reason: Optional[str] = None
    created_at: int
    updated_at: int


class ClaimSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    vendor_id: str
    invoice_id: str
    invoice_total: int = Field(gt=0, description="Total invoice amount in currency minor units")
    claim_amount: int = Field(gt=0, description="Claim amount in currency minor units")
    currency: str = "USD"
    category: str
    issued_at: int
    evidence_commitment: str
    signature: str = Field(description="EIP-712 cryptographic signature from vendor private key")
    report_id: str
    # Optional evidence fields for cryptographic checking
    file_bytes_base64: Optional[str] = None
    salt_hex: Optional[str] = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str  # "VERIFIED" or "REJECTED"
    claim_id: Optional[str] = None
    reason: Optional[str] = None
    explanation: str
    checks: Dict[str, bool]
    disbursement_allowed: bool
    claimed_amount: int = 0
    remaining_balance: int = 0
    recovered_signer: Optional[str] = None


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str  # "RELEASED" or "BLOCKED"
    project_id: str
    tranche_number: Optional[int] = None
    released_wei: Optional[int] = None
    total_released_wei: Optional[int] = None
    remaining_budget_wei: Optional[int] = None
    disbursement_allowed: bool
    reason: Optional[str] = None
    explanation: Optional[str] = None


class TraceGraphResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    project_name: str
    purpose: str
    events: List[Dict[str, Any]]
    edges: List[Dict[str, str]]
    summary: Dict[str, Any]
    discrepancies: List[Dict[str, Any]]
    is_conserved: bool


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    event_id: str
    event_type: str
    project_id: Optional[str] = None
    severity: str
    reason_code: Optional[str] = None
    details: Dict[str, Any]
    created_at: int


class MetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid_claims: int
    rejected_claims: int
    forged_attempts_detected: int
    duplicate_invoice_attempts_blocked: int
    release_attempts_blocked: int
    frozen_projects: int
    unexplained_trace_discrepancies: int


class ScenarioInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    category: str
    description: str
    expected_status: str
    expected_reason: Optional[str] = None


class ScenarioRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario: str
    title: str
    status: str
    reason: Optional[str] = None
    explanation: str
    project_status: str
    next_release_outcome: str
    next_release_reason: Optional[str] = None
    disbursement_allowed: bool
    checks: Dict[str, bool]
    details: Dict[str, Any]


class ClaimRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    claim_id: str
    project_id: str
    vendor_id: str
    invoice_id: str
    nullifier: str
    report_id: str
    claim_amount: int
    invoice_total: int
    currency: str
    category: str
    issued_at: int
    evidence_commitment: str
    signature: str
    recovered_signer: str
    status: str
    submitted_at: int
