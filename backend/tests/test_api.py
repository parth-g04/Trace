"""
Integration tests for TRACE FastAPI endpoints (backend/app/main.py).

Verifies:
- All required endpoints respond with proper schema and HTTP status codes.
- Structured rejection responses.
- Idempotency and repeatability of demo reset.
"""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional
import pytest

from backend.app.db import Database
from backend.app.demo.vendors import VENDOR_WELL_DRILL
from backend.app.main import app, get_db
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import sign_receipt


class ApiResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], body: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = body
        self.text = body.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)


class AsgiTestClient:
    """Lightweight in-memory ASGI test client (zero third-party dependencies)."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    def request(
        self,
        method: str,
        path: str,
        json_data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> ApiResponse:
        headers_dict = headers or {}
        body = b""
        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            headers_dict["content-type"] = "application/json"

        query_string = b""
        if "?" in path:
            path, qs = path.split("?", 1)
            query_string = qs.encode("ascii")

        raw_headers = [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in headers_dict.items()
        ]

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_string,
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        }

        res_body = bytearray()
        status_code = 0
        response_headers: Dict[str, str] = {}

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            nonlocal status_code, res_body, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                for k, v in message.get("headers", []):
                    response_headers[k.decode("latin-1")] = v.decode("latin-1")
            elif message["type"] == "http.response.body":
                res_body.extend(message.get("body", b""))

        asyncio.run(self.app(scope, receive, send))
        return ApiResponse(status_code, response_headers, bytes(res_body))

    def get(self, path: str, headers: Optional[Dict[str, str]] = None) -> ApiResponse:
        return self.request("GET", path, headers=headers)

    def post(self, path: str, json: Optional[Any] = None, headers: Optional[Dict[str, str]] = None) -> ApiResponse:
        return self.request("POST", path, json_data=json, headers=headers)


@pytest.fixture
def client():
    """Provides a TestClient connected to an isolated test database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_api.db")
        db = Database(db_path)
        db.reset_demo_state()

        app.dependency_overrides[get_db] = lambda: db

        test_client = AsgiTestClient(app)
        try:
            yield test_client
        finally:
            app.dependency_overrides.clear()
            db.close()


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["simulation_mode"] is True
    assert data["database"] == "connected"


def test_projects_endpoints(client):
    res = client.get("/projects")
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) >= 1
    assert projects[0]["id"] == "WATER-001"
    assert projects[0]["purpose"] == "WATER_INFRASTRUCTURE"

    res_single = client.get("/projects/WATER-001")
    assert res_single.status_code == 200
    assert res_single.json()["id"] == "WATER-001"

    res_404 = client.get("/projects/NON-EXISTENT")
    assert res_404.status_code == 404


def test_project_trace_endpoint(client):
    res = client.get("/projects/WATER-001/trace")
    assert res.status_code == 200
    trace = res.json()
    assert trace["project_id"] == "WATER-001"
    assert len(trace["events"]) == 1
    assert len(trace["edges"]) == 0
    assert trace["is_conserved"] is True

    # After releasing Tranche 1 and submitting valid claim: full 6-hop chain
    res_release = client.post("/projects/WATER-001/release")
    assert res_release.status_code == 200
    res_claim = client.post("/demo/scenarios/valid_claim/run")
    assert res_claim.status_code == 200

    res2 = client.get("/projects/WATER-001/trace")
    assert res2.status_code == 200
    trace2 = res2.json()
    assert len(trace2["events"]) == 6
    assert len(trace2["edges"]) == 5
    assert trace2["is_conserved"] is True


def test_post_claims_valid(client):
    now = int(time.time())
    domain = EIP712Domain()
    rec = Receipt(
        project_id="WATER-001",
        vendor_id=VENDOR_WELL_DRILL.vendor_id,
        invoice_id="INV-API-001",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "aa" * 32,
    )
    sig = sign_receipt(rec, VENDOR_WELL_DRILL.private_key, domain)

    payload = {
        "project_id": "WATER-001",
        "vendor_id": VENDOR_WELL_DRILL.vendor_id,
        "invoice_id": "INV-API-001",
        "invoice_total": 500000,
        "claim_amount": 500000,
        "currency": "USD",
        "category": "WATER_INFRASTRUCTURE",
        "issued_at": now,
        "evidence_commitment": "0x" + "aa" * 32,
        "signature": sig,
        "report_id": "REPORT-API-1",
    }

    res = client.post("/claims", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VERIFIED"
    assert data["disbursement_allowed"] is True
    assert data["claimed_amount"] == 500000

    # Verify GET /claims returns the recorded claim
    res_list = client.get("/claims?project_id=WATER-001")
    assert res_list.status_code == 200
    claims = res_list.json()
    assert len(claims) >= 1
    assert any(c["claim_id"] == data["claim_id"] for c in claims)


def test_post_claims_tampered_rejected(client):
    now = int(time.time())
    domain = EIP712Domain()
    rec = Receipt(
        project_id="WATER-001",
        vendor_id=VENDOR_WELL_DRILL.vendor_id,
        invoice_id="INV-API-002",
        invoice_total=500000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "bb" * 32,
    )
    # Genuine signature for $5,000
    sig = sign_receipt(rec, VENDOR_WELL_DRILL.private_key, domain)

    # Tampered payload asking for $50,000
    payload = {
        "project_id": "WATER-001",
        "vendor_id": VENDOR_WELL_DRILL.vendor_id,
        "invoice_id": "INV-API-002",
        "invoice_total": 5000000,  # Tampered!
        "claim_amount": 5000000,
        "currency": "USD",
        "category": "WATER_INFRASTRUCTURE",
        "issued_at": now,
        "evidence_commitment": "0x" + "bb" * 32,
        "signature": sig,
        "report_id": "REPORT-API-2",
    }

    res = client.post("/claims", json=payload)
    assert res.status_code == 400
    data = res.json()
    assert data["status"] == "REJECTED"
    assert data["reason"] == "SIGNER_VENDOR_MISMATCH"
    assert data["disbursement_allowed"] is False


def test_post_claims_duplicate_conflict(client):
    now = int(time.time())
    domain = EIP712Domain()
    rec = Receipt(
        project_id="WATER-001",
        vendor_id=VENDOR_WELL_DRILL.vendor_id,
        invoice_id="INV-API-DUP",
        invoice_total=300000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "cc" * 32,
    )
    sig = sign_receipt(rec, VENDOR_WELL_DRILL.private_key, domain)

    payload_a = {
        "project_id": "WATER-001",
        "vendor_id": VENDOR_WELL_DRILL.vendor_id,
        "invoice_id": "INV-API-DUP",
        "invoice_total": 300000,
        "claim_amount": 300000,
        "currency": "USD",
        "category": "WATER_INFRASTRUCTURE",
        "issued_at": now,
        "evidence_commitment": "0x" + "cc" * 32,
        "signature": sig,
        "report_id": "REPORT-FIRST",
    }

    res1 = client.post("/claims", json=payload_a)
    assert res1.status_code == 200

    payload_b = dict(payload_a)
    payload_b["report_id"] = "REPORT-SECOND"  # Cross-report duplicate!

    res2 = client.post("/claims", json=payload_b)
    assert res2.status_code == 409  # Conflict!
    data = res2.json()
    assert data["status"] == "REJECTED"
    assert data["reason"] == "INVOICE_REUSED_ACROSS_REPORTS"


def test_release_tranche_blocked_insufficient_spend(client):
    # Tranche 1 releases without spending requirement
    res1 = client.post("/projects/WATER-001/release")
    assert res1.status_code == 200
    assert res1.json()["status"] == "RELEASED"
    assert res1.json()["tranche_number"] == 1

    # Tranche 2 is blocked because verified spend is 0 (requires 10 ETH)
    res2 = client.post("/projects/WATER-001/release")
    assert res2.status_code == 400
    data = res2.json()
    assert data["status"] == "BLOCKED"
    assert data["reason"] == "INSUFFICIENT_VERIFIED_SPEND"
    assert data["disbursement_allowed"] is False


def test_audit_and_metrics_endpoints(client):
    res_audit = client.get("/audit")
    assert res_audit.status_code == 200
    audits = res_audit.json()
    assert len(audits) >= 1

    res_metrics = client.get("/metrics")
    assert res_metrics.status_code == 200
    metrics = res_metrics.json()
    assert "valid_claims" in metrics
    assert "rejected_claims" in metrics
    assert "forged_attempts_detected" in metrics
    assert "duplicate_invoice_attempts_blocked" in metrics
    assert "release_attempts_blocked" in metrics
    assert "frozen_projects" in metrics
    assert "unexplained_trace_discrepancies" in metrics


def test_demo_scenarios_and_reset(client):
    # Get scenarios catalog
    res_cat = client.get("/demo/scenarios")
    assert res_cat.status_code == 200
    catalog = res_cat.json()
    assert len(catalog) == 7

    # Run valid claim scenario
    res_run = client.post("/demo/scenarios/valid_claim/run")
    assert res_run.status_code == 200
    data = res_run.json()
    assert data["scenario"] == "valid_claim"
    assert data["status"] == "VERIFIED"

    # Reset
    res_reset = client.post("/demo/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["status"] == "RESET_OK"
