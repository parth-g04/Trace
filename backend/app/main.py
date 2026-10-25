"""
TRACE — Verifiable NGO Fund Flows REST API.
CASCADE '26 Hackathon (Problem Statement 4.2).

FastAPI backend orchestrating cryptographic receipt verification,
simulated purpose-bound escrow release, and multi-hop fund-flow tracing.
"""
import base64
from contextlib import asynccontextmanager
import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.db import Database, get_db_path
from backend.app.demo.scenarios import list_demo_scenarios, run_scenario
from backend.app.models.api import (
    AuditEventResponse,
    ChainStateResponse,
    ChainStatusResponse,
    ClaimRecordResponse,
    ClaimResponse,
    ClaimSubmitRequest,
    HealthResponse,
    MetricsResponse,
    ModeUpdateRequest,
    ProjectResponse,
    ReleaseResponse,
    ScenarioInfo,
    ScenarioRunResponse,
    TraceGraphResponse,
)
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.trace_graph import TraceGraphReconciler, build_trace_graph
from backend.app.services.web3_service import Web3Service

# Global database instance
_global_db: Optional[Database] = None
# Global Web3 service instance
_global_web3: Optional[Web3Service] = None


def get_db() -> Database:
    """Dependency provider for database instance."""
    global _global_db
    if _global_db is None:
        _global_db = Database()
    return _global_db


def get_web3_service() -> Web3Service:
    """Dependency provider for Web3 contract service."""
    global _global_web3
    if _global_web3 is None:
        _global_web3 = Web3Service()
    return _global_web3


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes database schema and seed state on startup."""
    db = get_db()
    db.init_schema()
    if os.environ.get("TRACE_PERSIST_ON_BOOT") != "1":
        db.reset_demo_state()
    else:
        proj = db.get_project("WATER-001")
        if not proj:
            db.reset_demo_state()
    yield


app = FastAPI(
    title="TRACE Backend API",
    description="Verifiable NGO Fund Flows & Cryptographic Escrow Engine",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration for local Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health(
    db: Database = Depends(get_db),
    web3_svc: Web3Service = Depends(get_web3_service),
):
    """Health check endpoint indicating simulation mode and datastore status."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        simulation_mode=(web3_svc.mode != "local_chain"),
        database="connected",
        timestamp=int(time.time()),
    )


@app.get("/projects", response_model=List[ProjectResponse], tags=["Projects"])
def list_projects(db: Database = Depends(get_db)):
    """Lists all registered projects and their escrow states."""
    rows = db.list_projects()
    result: List[ProjectResponse] = []
    for r in rows:
        result.append(
            ProjectResponse(
                id=r["id"],
                name=r["name"],
                purpose=r["purpose"],
                funding_wei=r["funding_wei"],
                total_tranches=r["total_tranches"],
                current_tranche=r["current_tranche"],
                released_wei=r["released_wei"],
                verified_spend_wei=r["verified_spend_wei"],
                verified_spend_usd_cents=r["verified_spend_usd_cents"],
                is_frozen=bool(r["is_frozen"]),
                freeze_reason=r.get("freeze_reason"),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    return result


@app.get("/projects/{id}", response_model=ProjectResponse, tags=["Projects"])
def get_project(id: str, db: Database = Depends(get_db)):
    """Retrieves detailed project and escrow information by project ID."""
    p = db.get_project(id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )
    return ProjectResponse(
        id=p["id"],
        name=p["name"],
        purpose=p["purpose"],
        funding_wei=p["funding_wei"],
        total_tranches=p["total_tranches"],
        current_tranche=p["current_tranche"],
        released_wei=p["released_wei"],
        verified_spend_wei=p["verified_spend_wei"],
        verified_spend_usd_cents=p["verified_spend_usd_cents"],
        is_frozen=bool(p["is_frozen"]),
        freeze_reason=p.get("freeze_reason"),
        created_at=p["created_at"],
        updated_at=p["updated_at"],
    )


@app.get("/projects/{id}/trace", response_model=TraceGraphResponse, tags=["Trace"])
def get_project_trace(id: str, db: Database = Depends(get_db)):
    """
    Returns multi-hop fund-flow trace graph for a project,
    reconciled against integer conservation laws.
    """
    p = db.get_project(id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )
    data = build_trace_graph(db, id)
    return TraceGraphResponse(**data)


@app.post("/claims", response_model=ClaimResponse, tags=["Claims"])
def submit_claim(req: ClaimSubmitRequest, db: Database = Depends(get_db)):
    """
    Submits a vendor-signed expenditure receipt for cryptographic verification and claim persistence.
    Verifies the submitted EIP-712 signature using Phase 1 verification logic.
    Does NOT sign receipts on behalf of callers.
    """
    # Parse optional evidence payload
    file_bytes: Optional[bytes] = None
    salt_bytes: Optional[bytes] = None

    if req.file_bytes_base64:
        try:
            file_bytes = base64.b64decode(req.file_bytes_base64)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=ClaimResponse(
                    status="REJECTED",
                    reason="MALFORMED_EVIDENCE",
                    explanation="file_bytes_base64 is not valid base64 data.",
                    checks={"structure_valid": False},
                    disbursement_allowed=False,
                ).model_dump(),
            )

    if req.salt_hex:
        try:
            s_hex = req.salt_hex[2:] if req.salt_hex.startswith("0x") else req.salt_hex
            salt_bytes = bytes.fromhex(s_hex)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=ClaimResponse(
                    status="REJECTED",
                    reason="MALFORMED_EVIDENCE",
                    explanation="salt_hex is not valid hexadecimal string.",
                    checks={"structure_valid": False},
                    disbursement_allowed=False,
                ).model_dump(),
            )

    # Construct receipt model
    try:
        rec = Receipt(
            project_id=req.project_id,
            vendor_id=req.vendor_id,
            invoice_id=req.invoice_id,
            invoice_total=req.invoice_total,
            currency=req.currency,
            category=req.category,
            issued_at=req.issued_at,
            evidence_commitment=req.evidence_commitment,
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ClaimResponse(
                status="REJECTED",
                reason="MALFORMED_RECEIPT",
                explanation=str(e),
                checks={"structure_valid": False},
                disbursement_allowed=False,
            ).model_dump(),
        )

    res = db.process_and_persist_claim(
        receipt=rec,
        signature=req.signature,
        claim_amount=req.claim_amount,
        report_id=req.report_id,
        file_bytes=file_bytes,
        salt=salt_bytes,
    )

    resp_model = ClaimResponse(
        status=res["status"],
        claim_id=res.get("claim_id"),
        reason=res.get("reason"),
        explanation=res["explanation"],
        checks=res["checks"],
        disbursement_allowed=res["disbursement_allowed"],
        claimed_amount=res.get("claimed_amount", 0),
        remaining_balance=res.get("remaining_balance", 0),
        recovered_signer=res.get("recovered_signer"),
    )

    if res["status"] == "VERIFIED":
        return resp_model

    # For duplicate invoice rejections, use HTTP 409 Conflict; otherwise HTTP 400
    status_code = (
        status.HTTP_409_CONFLICT
        if res.get("reason") == "INVOICE_REUSED_ACROSS_REPORTS"
        else status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse(status_code=status_code, content=resp_model.model_dump())


@app.get("/claims", response_model=List[ClaimRecordResponse], tags=["Claims"])
def list_claims(
    project_id: Optional[str] = Query(None, description="Filter claims by project ID"),
    db: Database = Depends(get_db),
):
    """
    Retrieves recorded claims and their verification statuses.
    Read-only audit endpoint for dashboard and verifier inspection.
    """
    rows = db.get_claims(project_id)
    return [ClaimRecordResponse(**r) for r in rows]


@app.post("/projects/{id}/release", response_model=ReleaseResponse, tags=["Escrow"])
def release_tranche(
    id: str,
    db: Database = Depends(get_db),
    web3_svc: Web3Service = Depends(get_web3_service),
):
    """
    Attempts to release the next funding tranche for a project.
    If active mode is 'local_chain', executes directly on-chain and verifies the receipt.
    If active mode is 'simulation', enforces the spend-gating rules in SQLite.
    Never silently falls back to simulation on on-chain failure.
    """
    if web3_svc.mode == "local_chain":
        res = web3_svc.release_next_tranche_on_chain()
        resp_model = ReleaseResponse(
            status=res["status"],
            project_id=res.get("project_id", id),
            tranche_number=res.get("tranche_number"),
            released_wei=res.get("released_wei"),
            total_released_wei=res.get("total_released_wei"),
            remaining_budget_wei=res.get("remaining_budget_wei"),
            disbursement_allowed=res.get("disbursement_allowed", False),
            reason=res.get("reason"),
            explanation=res.get("explanation"),
            tx_hash=res.get("tx_hash"),
            mode="local_chain",
        )
        if res["status"] == "RELEASED":
            return resp_model
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=resp_model.model_dump())

    res = db.release_next_tranche(id)
    resp_model = ReleaseResponse(
        status=res["status"],
        project_id=res.get("project_id", id),
        tranche_number=res.get("tranche_number"),
        released_wei=res.get("released_wei"),
        total_released_wei=res.get("total_released_wei"),
        remaining_budget_wei=res.get("remaining_budget_wei"),
        disbursement_allowed=res.get("disbursement_allowed", False),
        reason=res.get("reason"),
        explanation=res.get("explanation"),
        mode="simulation",
    )

    if res["status"] == "RELEASED":
        return resp_model

    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=resp_model.model_dump())


@app.get("/chain/status", response_model=ChainStatusResponse, tags=["Blockchain"])
def get_chain_status(web3_svc: Web3Service = Depends(get_web3_service)):
    """Returns local blockchain connectivity, chain ID, contract address, deployment status, and active mode."""
    return ChainStatusResponse(**web3_svc.get_status())


@app.get("/chain/state", response_model=ChainStateResponse, tags=["Blockchain"])
def get_chain_state(web3_svc: Web3Service = Depends(get_web3_service)):
    """Reads on-chain project escrow state directly from the deployed TraceEscrow contract."""
    try:
        data = web3_svc.get_contract_state()
        return ChainStateResponse(**data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to query on-chain state: {str(e)}",
        )


@app.post("/chain/mode", tags=["Blockchain"])
def set_chain_mode(
    req: ModeUpdateRequest,
    web3_svc: Web3Service = Depends(get_web3_service),
):
    """Explicitly toggles between 'simulation' and 'local_chain' execution modes."""
    if req.mode not in ("simulation", "local_chain"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mode must be either 'simulation' or 'local_chain'.",
        )
    web3_svc.mode = req.mode
    return {"status": "MODE_UPDATED", "mode": req.mode}


@app.post("/chain/release", response_model=ReleaseResponse, tags=["Blockchain"])
def chain_release(
    recipient: Optional[str] = Query(None, description="Optional recipient address for release"),
    web3_svc: Web3Service = Depends(get_web3_service),
):
    """Explicitly submits an on-chain tranche release transaction to the local Hardhat chain."""
    res = web3_svc.release_next_tranche_on_chain(recipient)
    resp_model = ReleaseResponse(
        status=res["status"],
        project_id=res.get("project_id", "WATER-001"),
        tranche_number=res.get("tranche_number"),
        released_wei=res.get("released_wei"),
        total_released_wei=res.get("total_released_wei"),
        remaining_budget_wei=res.get("remaining_budget_wei"),
        disbursement_allowed=res.get("disbursement_allowed", False),
        reason=res.get("reason"),
        explanation=res.get("explanation"),
        tx_hash=res.get("tx_hash"),
        mode="local_chain",
    )
    if res["status"] == "RELEASED":
        return resp_model
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=resp_model.model_dump())


@app.get("/audit", response_model=List[AuditEventResponse], tags=["Audit"])
def get_audit_trail(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    severity: Optional[str] = Query(None, description="Filter by severity (INFO, WARNING, CRITICAL)"),
    limit: int = Query(100, ge=1, le=1000),
    db: Database = Depends(get_db),
):
    """Retrieves immutable audit trail entries."""
    rows = db.get_audit_events(project_id=project_id, severity=severity, limit=limit)
    res: List[AuditEventResponse] = []
    for r in rows:
        details = {}
        if r.get("details_json"):
            try:
                details = json.loads(r["details_json"])
            except Exception:
                details = {}
        res.append(
            AuditEventResponse(
                id=r["id"],
                event_id=r["event_id"],
                event_type=r["event_type"],
                project_id=r.get("project_id"),
                severity=r["severity"],
                reason_code=r.get("reason_code"),
                details=details,
                created_at=r["created_at"],
            )
        )
    return res


@app.get("/metrics", response_model=MetricsResponse, tags=["Metrics"])
def get_metrics(db: Database = Depends(get_db)):
    """Computes security and flow metrics from actual persisted records."""
    metrics = db.get_metrics()

    # Calculate unexplained trace discrepancies dynamically across all projects
    projects = db.list_projects()
    total_discrepancies = 0
    for p in projects:
        events = db.get_flow_events(p["id"])
        claims = db.get_claims(p["id"])
        verified_claim_ids = {c["claim_id"] for c in claims if c["status"] == "VERIFIED"}
        _, disc = TraceGraphReconciler.reconcile(
            events,
            require_matching_vendor_payment=False,
            verified_claim_ids=verified_claim_ids,
        )
        total_discrepancies += len(disc)

    metrics["unexplained_trace_discrepancies"] = total_discrepancies
    return MetricsResponse(**metrics)


@app.post("/demo/reset", tags=["Demo"])
def demo_reset(db: Database = Depends(get_db)):
    """Resets the entire database to the deterministic seed state."""
    db.reset_demo_state()
    return {"status": "RESET_OK", "message": "Demo state reset to deterministic seed"}


@app.get("/demo/scenarios", response_model=List[ScenarioInfo], tags=["Demo"])
def get_demo_scenarios():
    """Lists all available automated evaluation scenarios."""
    return [ScenarioInfo(**s) for s in list_demo_scenarios()]


@app.post("/demo/scenarios/{name}/run", response_model=ScenarioRunResponse, tags=["Demo"])
def run_demo_scenario(name: str, db: Database = Depends(get_db)):
    """Executes a named evaluation scenario and returns detailed results."""
    try:
        res = run_scenario(name, db)
        return ScenarioRunResponse(**res)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
