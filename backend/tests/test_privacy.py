"""
Privacy tests for TRACE API public endpoints (Step 7).

Verifies that public JSON responses NEVER leak:
- Vendor private signing keys
- Raw evidence files or evidence salts
- Sensitive private beneficiary PII
"""
import tempfile
import time
from pathlib import Path
import pytest

from backend.app.db import Database
from backend.app.demo.vendors import ATTACKER_SIGNER, VENDOR_SOLAR_PUMP, VENDOR_WELL_DRILL
from backend.app.main import app, get_db
from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import sign_receipt
from backend.tests.test_api import AsgiTestClient


# Sensitive strings that must NEVER appear in public API JSON responses
SENSITIVE_STRINGS = [
    VENDOR_WELL_DRILL.private_key,
    VENDOR_SOLAR_PUMP.private_key,
    ATTACKER_SIGNER.private_key,
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x2a871d0798f97d79848a013d3bbd362c6b97fe5356e0bbeed1241f93003444a0",
    "SECRET_TEST_SALT_VALUE_NEVER_LEAK_0123456789",
    "BENEFICIARY_PRIVATE_IDENTIFIER_KENYA_PATIENT_007",
]


@pytest.fixture
def privacy_client():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_privacy.db")
        db = Database(db_path)
        db.reset_demo_state()

        app.dependency_overrides[get_db] = lambda: db

        test_client = AsgiTestClient(app)
        try:
            yield test_client, db
        finally:
            app.dependency_overrides.clear()
            db.close()


def test_public_endpoints_privacy_scan(privacy_client):
    """
    Executes claims and exercises all public API endpoints,
    then scans raw response text for any leaks of private keys, salts, or beneficiary PII.
    """
    client, db = privacy_client
    now = int(time.time())
    domain = EIP712Domain()

    # Submit a verified claim
    rec = Receipt(
        project_id="WATER-001",
        vendor_id=VENDOR_WELL_DRILL.vendor_id,
        invoice_id="INV-PRIVACY-001",
        invoice_total=400000,
        currency="USD",
        category="WATER_INFRASTRUCTURE",
        issued_at=now,
        evidence_commitment="0x" + "ee" * 32,
    )
    sig = sign_receipt(rec, VENDOR_WELL_DRILL.private_key, domain)

    res_claim = client.post(
        "/claims",
        json={
            "project_id": "WATER-001",
            "vendor_id": VENDOR_WELL_DRILL.vendor_id,
            "invoice_id": "INV-PRIVACY-001",
            "invoice_total": 400000,
            "claim_amount": 400000,
            "currency": "USD",
            "category": "WATER_INFRASTRUCTURE",
            "issued_at": now,
            "evidence_commitment": "0x" + "ee" * 32,
            "signature": sig,
            "report_id": "REPORT-PRIVACY",
        },
    )
    assert res_claim.status_code == 200

    # Endpoints to scan
    endpoints = [
        "/health",
        "/projects",
        "/projects/WATER-001",
        "/projects/WATER-001/trace",
        "/audit",
        "/metrics",
        "/demo/scenarios",
    ]

    all_responses_text = [res_claim.text]

    for ep in endpoints:
        resp = client.get(ep)
        all_responses_text.append(resp.text)

    # Scan all responses for any sensitive marker
    combined_public_output = "\n".join(all_responses_text).lower()

    for sensitive in SENSITIVE_STRINGS:
        # Check if the private key / secret string appears anywhere in public JSON
        clean_sensitive = sensitive.lower()
        assert clean_sensitive not in combined_public_output, (
            f"PRIVACY VIOLATION: Found sensitive private data in public endpoint response: {sensitive}"
        )
