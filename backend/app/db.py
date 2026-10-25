"""
SQLite persistence layer for TRACE.

Provides atomic, transaction-safe persistence for:
- projects
- vendors
- claims
- invoice_ledger
- escrow_state
- flow_events
- audit_events

All financial figures in wei are stored as decimal strings (to prevent 64-bit integer overflow)
and parsed to/from Python arbitrary-precision integers.
"""
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import uuid

from eth_utils import to_checksum_address

from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.canonical import (
    ALLOWED_CATEGORIES,
    normalize_category,
    normalize_currency,
    normalize_identifier,
    normalize_invoice_id,
    validate_bytes32,
    validate_monetary_value,
)
from backend.app.services.verification import (
    VendorRegistry,
    VerificationResult,
    verify_receipt,
)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trace.db"

# Qualifying security rejections that immediately freeze the offending project
SECURITY_FREEZE_REASONS = {
    "SIGNATURE_INVALID",
    "SIGNER_VENDOR_MISMATCH",
    "MALFORMED_SIGNATURE",
    "INVOICE_REUSED_ACROSS_REPORTS",
    "INVOICE_TOTAL_MISMATCH",
    "CATEGORY_NOT_ALLOWED",
    "EVIDENCE_COMMITMENT_MISMATCH",
}


def get_db_path(override_path: Optional[str] = None) -> str:
    """Returns the effective database path."""
    if override_path:
        return override_path
    env_path = os.environ.get("TRACE_DB_PATH")
    if env_path:
        return env_path
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return str(DEFAULT_DB_PATH)


class Database:
    """
    TRACE SQLite Database manager.
    Supports file-based or in-memory SQLite storage with strict atomic transactions.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path == ":memory:":
            self.db_path = ":memory:"
            # In-memory database requires a persistent connection across calls
            self._shared_conn: Optional[sqlite3.Connection] = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._shared_conn.row_factory = sqlite3.Row
            self._shared_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self.db_path = get_db_path(db_path)
            self._shared_conn = None
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Returns an active SQLite connection with Row factory and foreign keys enabled."""
        if self._shared_conn is not None:
            return self._shared_conn

        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def close(self) -> None:
        """Closes shared in-memory connection if active."""
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None

    def init_schema(self) -> None:
        """Creates the initial database schema if tables do not exist."""
        conn = self.get_connection()
        try:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        canonical_id TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        purpose TEXT NOT NULL,
                        funding_wei TEXT NOT NULL,
                        total_tranches INTEGER NOT NULL DEFAULT 5,
                        current_tranche INTEGER NOT NULL DEFAULT 0,
                        released_wei TEXT NOT NULL DEFAULT '0',
                        verified_spend_wei TEXT NOT NULL DEFAULT '0',
                        verified_spend_usd_cents INTEGER NOT NULL DEFAULT 0,
                        is_frozen INTEGER NOT NULL DEFAULT 0,
                        freeze_reason TEXT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS vendors (
                        vendor_id TEXT PRIMARY KEY,
                        canonical_id TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        address TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        registered_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS claims (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        claim_id TEXT UNIQUE NOT NULL,
                        project_id TEXT NOT NULL,
                        vendor_id TEXT NOT NULL,
                        invoice_id TEXT NOT NULL,
                        nullifier TEXT NOT NULL,
                        report_id TEXT NOT NULL,
                        claim_amount INTEGER NOT NULL,
                        invoice_total INTEGER NOT NULL,
                        currency TEXT NOT NULL,
                        category TEXT NOT NULL,
                        issued_at INTEGER NOT NULL,
                        evidence_commitment TEXT NOT NULL,
                        signature TEXT NOT NULL,
                        recovered_signer TEXT NOT NULL,
                        status TEXT NOT NULL,
                        submitted_at INTEGER NOT NULL,
                        FOREIGN KEY (project_id) REFERENCES projects(id)
                    );

                    CREATE TABLE IF NOT EXISTS invoice_ledger (
                        nullifier TEXT PRIMARY KEY,
                        invoice_total INTEGER NOT NULL,
                        claimed INTEGER NOT NULL,
                        report_id TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS escrow_state (
                        project_id TEXT PRIMARY KEY,
                        total_budget_wei TEXT NOT NULL,
                        released_wei TEXT NOT NULL DEFAULT '0',
                        current_tranche INTEGER NOT NULL DEFAULT 0,
                        total_tranches INTEGER NOT NULL DEFAULT 5,
                        tranche_size_wei TEXT NOT NULL,
                        eth_usd_rate_cents INTEGER NOT NULL DEFAULT 200000,
                        is_frozen INTEGER NOT NULL DEFAULT 0,
                        freeze_reason TEXT,
                        updated_at INTEGER NOT NULL,
                        FOREIGN KEY (project_id) REFERENCES projects(id)
                    );

                    CREATE TABLE IF NOT EXISTS flow_events (
                        event_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        parent_event_id TEXT,
                        input_asset TEXT NOT NULL,
                        input_amount TEXT NOT NULL,
                        output_asset TEXT NOT NULL,
                        output_amount TEXT NOT NULL,
                        conversion_rate_basis INTEGER,
                        is_simulated INTEGER NOT NULL DEFAULT 1,
                        attestation TEXT,
                        metadata_json TEXT,
                        created_at INTEGER NOT NULL,
                        FOREIGN KEY (project_id) REFERENCES projects(id)
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT UNIQUE NOT NULL,
                        event_type TEXT NOT NULL,
                        project_id TEXT,
                        severity TEXT NOT NULL,
                        reason_code TEXT,
                        details_json TEXT,
                        created_at INTEGER NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project_id);
                    CREATE INDEX IF NOT EXISTS idx_claims_nullifier ON claims(nullifier);
                    CREATE INDEX IF NOT EXISTS idx_flow_project ON flow_events(project_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_events(project_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
                    """
                )
        finally:
            if self._shared_conn is None:
                conn.close()

    def reset_demo_state(self) -> None:
        """
        Deterministically resets the database to the initial seed state:
        - Project WATER-001 (50 ETH funding, 5 tranches, 10 ETH released as Tranche 1).
        - Registered demo vendors (WELL-DRILL-01, SOLAR-PUMP-02).
        - Initial flow events: DONATION (50 ETH), ALLOCATION (10 ETH Tranche 1),
          BRIDGE (10 ETH, simulated), OFFRAMP (10 ETH -> $20,000 USD fiat, simulated).
        - Audit trail entry for DEMO_RESET.
        """
        self.init_schema()
        conn = self.get_connection()
        now = int(time.time())

        # Demo project constants
        project_id = "WATER-001"
        canonical_project_id = normalize_identifier(project_id)
        total_funding_wei = 50 * 10**18  # 50 ETH
        tranche_size_wei = 10 * 10**18   # 10 ETH
        initial_released_wei = 10 * 10**18  # Tranche 1 pre-released
        eth_usd_rate_cents = 200000  # $2,000.00 per ETH

        # Demo vendor constants
        demo_vendors = [
            (
                "WELL-DRILL-01",
                normalize_identifier("WELL-DRILL-01"),
                "Nairobi Borehole Drilling Ltd",
                to_checksum_address("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"),
            ),
            (
                "SOLAR-PUMP-02",
                normalize_identifier("SOLAR-PUMP-02"),
                "Rift Valley Solar Pumps",
                to_checksum_address("0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
            ),
        ]

        try:
            with conn:
                # Wipe all tables cleanly
                conn.execute("DELETE FROM audit_events;")
                conn.execute("DELETE FROM flow_events;")
                conn.execute("DELETE FROM claims;")
                conn.execute("DELETE FROM invoice_ledger;")
                conn.execute("DELETE FROM escrow_state;")
                conn.execute("DELETE FROM vendors;")
                conn.execute("DELETE FROM projects;")

                # Seed Project
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, canonical_id, name, purpose, funding_wei, total_tranches, current_tranche,
                        released_wei, verified_spend_wei, verified_spend_usd_cents,
                        is_frozen, freeze_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        canonical_project_id,
                        "Clean Water Initiative Kenya",
                        "WATER_INFRASTRUCTURE",
                        str(total_funding_wei),
                        5,
                        1,
                        str(initial_released_wei),
                        "0",
                        0,
                        0,
                        None,
                        now,
                        now,
                    ),
                )

                # Seed Escrow State
                conn.execute(
                    """
                    INSERT INTO escrow_state (
                        project_id, total_budget_wei, released_wei, current_tranche,
                        total_tranches, tranche_size_wei, eth_usd_rate_cents,
                        is_frozen, freeze_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        str(total_funding_wei),
                        str(initial_released_wei),
                        1,
                        5,
                        str(tranche_size_wei),
                        eth_usd_rate_cents,
                        0,
                        None,
                        now,
                    ),
                )

                # Seed Registered Vendors
                for v_id, c_id, v_name, v_addr in demo_vendors:
                    conn.execute(
                        """
                        INSERT INTO vendors (vendor_id, canonical_id, name, address, is_active, registered_at)
                        VALUES (?, ?, ?, ?, 1, ?)
                        """,
                        (v_id, c_id, v_name, v_addr, now),
                    )

                # Seed Initial Fund Flows for Tranche 1
                # 1. DONATION (50 ETH deposited into Escrow)
                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "EVT-DONATION-001",
                        project_id,
                        "DONATION",
                        None,
                        "ETH",
                        str(total_funding_wei),
                        "ETH",
                        str(total_funding_wei),
                        None,
                        0,
                        "GENESIS_DEPOSIT:tx_0x9876543210abcdef",
                        json.dumps({"donor": "Global Water Fund", "notes": "Initial 50 ETH Escrow Deposit"}),
                        now,
                    ),
                )

                # 2. ALLOCATION (Tranche 1 allocated: 10 ETH)
                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "EVT-ALLOC-T1",
                        project_id,
                        "ALLOCATION",
                        "EVT-DONATION-001",
                        "ETH",
                        str(initial_released_wei),
                        "ETH",
                        str(initial_released_wei),
                        None,
                        1,
                        "SIMULATED_ALLOCATION:tranche=1",
                        json.dumps({"tranche": 1, "status": "RELEASED_TO_OPERATING_ACCOUNT"}),
                        now,
                    ),
                )

                # 3. BRIDGE (10 ETH bridged to local operating network)
                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "EVT-BRIDGE-T1",
                        project_id,
                        "BRIDGE",
                        "EVT-ALLOC-T1",
                        "ETH",
                        str(initial_released_wei),
                        "ETH",
                        str(initial_released_wei),
                        None,
                        1,
                        "SIMULATED_BRIDGE_ATTESTATION:relayer=ArbitrumBridge_Sim:tx_bridge_t1",
                        json.dumps({"destination_network": "Arbitrum One (Simulated)"}),
                        now,
                    ),
                )

                # 4. OFFRAMP (10 ETH off-ramped to $20,000 USD fiat operating funds)
                initial_usd_cents = (initial_released_wei * eth_usd_rate_cents) // (10**18)  # 2,000,000 cents ($20,000)
                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "EVT-OFFRAMP-T1",
                        project_id,
                        "OFFRAMP",
                        "EVT-BRIDGE-T1",
                        "ETH",
                        str(initial_released_wei),
                        "USD_CENTS",
                        str(initial_usd_cents),
                        eth_usd_rate_cents,
                        1,
                        "SIMULATED_OFFRAMP_ATTESTATION:provider=Circle_Sim:ref=sim_offramp_water001_t1:status=SETTLED",
                        json.dumps({"provider": "Circle Mint Simulation", "settlement_currency": "USD"}),
                        now,
                    ),
                )

                # Audit Event: Reset Completed
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, event_type, project_id, severity, reason_code, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"AUDIT-RESET-{uuid.uuid4().hex[:8].upper()}",
                        "DEMO_RESET",
                        project_id,
                        "INFO",
                        "DETERMINISTIC_SEED",
                        json.dumps({"message": "Database reset to deterministic seed state"}),
                        now,
                    ),
                )
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves project details by ID or canonical ID."""
        try:
            c_id = normalize_identifier(project_id)
        except Exception:
            c_id = project_id

        conn = self.get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM projects WHERE id = ? OR canonical_id = ?",
                (project_id, c_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            if self._shared_conn is None:
                conn.close()

    def list_projects(self) -> List[Dict[str, Any]]:
        """Lists all projects."""
        conn = self.get_connection()
        try:
            cur = conn.execute("SELECT * FROM projects ORDER BY created_at ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_escrow_state(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves escrow state for a project."""
        proj = self.get_project(project_id)
        if not proj:
            return None
        conn = self.get_connection()
        try:
            cur = conn.execute("SELECT * FROM escrow_state WHERE project_id = ?", (proj["id"],))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            if self._shared_conn is None:
                conn.close()

    def is_project_frozen(self, project_id: str) -> Tuple[bool, Optional[str]]:
        """Checks if a project is frozen and returns (is_frozen, reason)."""
        project = self.get_project(project_id)
        if not project:
            return False, None
        return bool(project["is_frozen"]), project.get("freeze_reason")

    def freeze_project(self, project_id: str, reason: str) -> None:
        """Freezes a project and records an audit event."""
        proj = self.get_project(project_id)
        if not proj:
            return
        p_id = proj["id"]
        conn = self.get_connection()
        now = int(time.time())
        try:
            with conn:
                conn.execute(
                    "UPDATE projects SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE id = ?",
                    (reason, now, p_id),
                )
                conn.execute(
                    "UPDATE escrow_state SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE project_id = ?",
                    (reason, now, p_id),
                )
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, event_type, project_id, severity, reason_code, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"AUDIT-FREEZE-{uuid.uuid4().hex[:8].upper()}",
                        "PROJECT_FROZEN",
                        p_id,
                        "CRITICAL",
                        reason,
                        json.dumps({"freeze_reason": reason, "timestamp": now}),
                        now,
                    ),
                )
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """Looks up a vendor by ID or canonical ID."""
        try:
            c_id = normalize_identifier(vendor_id)
        except Exception:
            c_id = vendor_id

        conn = self.get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM vendors WHERE vendor_id = ? OR canonical_id = ?",
                (vendor_id, c_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            if self._shared_conn is None:
                conn.close()

    def list_vendors(self) -> List[Dict[str, Any]]:
        """Lists all registered vendors."""
        conn = self.get_connection()
        try:
            cur = conn.execute("SELECT * FROM vendors WHERE is_active = 1 ORDER BY vendor_id ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            if self._shared_conn is None:
                conn.close()

    def register_vendor(self, vendor_id: str, name: str, address: str) -> None:
        """Registers a new vendor in the database."""
        c_vendor = normalize_identifier(vendor_id)
        c_addr = to_checksum_address(address)
        now = int(time.time())
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO vendors (vendor_id, canonical_id, name, address, is_active, registered_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(vendor_id) DO UPDATE SET
                        canonical_id = excluded.canonical_id,
                        name = excluded.name,
                        address = excluded.address,
                        is_active = 1
                    """,
                    (vendor_id, c_vendor, name, c_addr, now),
                )
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_vendor_registry(self) -> VendorRegistry:
        """Builds an in-memory VendorRegistry from active vendors in the database."""
        registry = VendorRegistry()
        for v in self.list_vendors():
            registry.register_vendor(v["canonical_id"], v["address"])
            registry.register_vendor(v["vendor_id"], v["address"])
        return registry

    def get_ledger_record(self, nullifier: str) -> Optional[Dict[str, Any]]:
        """Queries the invoice ledger by nullifier hex string."""
        conn = self.get_connection()
        try:
            cur = conn.execute("SELECT * FROM invoice_ledger WHERE nullifier = ?", (nullifier,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_flow_events(self, project_id: str) -> List[Dict[str, Any]]:
        """Lists flow events for a project ordered by creation time."""
        proj = self.get_project(project_id)
        p_id = proj["id"] if proj else project_id
        conn = self.get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM flow_events WHERE project_id = ? ORDER BY created_at ASC",
                (p_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            if self._shared_conn is None:
                conn.close()

    def record_audit_event(
        self,
        event_type: str,
        project_id: Optional[str],
        severity: str,
        reason_code: Optional[str],
        details: Dict[str, Any],
    ) -> str:
        """Appends an immutable audit event to the audit trail."""
        conn = self.get_connection()
        event_id = f"AUDIT-{uuid.uuid4().hex[:10].upper()}"
        now = int(time.time())
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, event_type, project_id, severity, reason_code, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        project_id,
                        severity,
                        reason_code,
                        json.dumps(details),
                        now,
                    ),
                )
            return event_id
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_audit_events(
        self,
        project_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieves audit events filtered by project and severity."""
        p_id = None
        if project_id:
            proj = self.get_project(project_id)
            p_id = proj["id"] if proj else project_id

        conn = self.get_connection()
        try:
            query = "SELECT * FROM audit_events WHERE 1=1"
            params: List[Any] = []
            if p_id:
                query += " AND project_id = ?"
                params.append(p_id)
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cur = conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            if self._shared_conn is None:
                conn.close()

    def get_metrics(self) -> Dict[str, int]:
        """
        Computes system metrics dynamically from persisted database records.
        """
        conn = self.get_connection()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM claims WHERE status = 'VERIFIED'")
            valid_claims = cur.fetchone()[0]

            cur = conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type = 'CLAIM_REJECTED'")
            rejected_claims = cur.fetchone()[0]

            cur = conn.execute(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE event_type = 'CLAIM_REJECTED'
                  AND reason_code IN ('SIGNER_VENDOR_MISMATCH', 'SIGNATURE_INVALID', 'MALFORMED_SIGNATURE')
                """
            )
            forged_attempts_detected = cur.fetchone()[0]

            cur = conn.execute(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE reason_code = 'INVOICE_REUSED_ACROSS_REPORTS'
                """
            )
            duplicate_invoice_attempts_blocked = cur.fetchone()[0]

            cur = conn.execute(
                """
                SELECT COUNT(*) FROM audit_events
                WHERE event_type = 'TRANCHE_BLOCKED'
                """
            )
            release_attempts_blocked = cur.fetchone()[0]

            cur = conn.execute("SELECT COUNT(*) FROM projects WHERE is_frozen = 1")
            frozen_projects = cur.fetchone()[0]

            # Trace discrepancies will be computed by trace_graph service
            return {
                "valid_claims": valid_claims,
                "rejected_claims": rejected_claims,
                "forged_attempts_detected": forged_attempts_detected,
                "duplicate_invoice_attempts_blocked": duplicate_invoice_attempts_blocked,
                "release_attempts_blocked": release_attempts_blocked,
                "frozen_projects": frozen_projects,
                "unexplained_trace_discrepancies": 0,
            }
        finally:
            if self._shared_conn is None:
                conn.close()

    def process_and_persist_claim(
        self,
        receipt: Union[Receipt, Dict[str, Any]],
        signature: Union[str, bytes],
        claim_amount: int,
        report_id: str,
        domain: Optional[EIP712Domain] = None,
        now: Optional[int] = None,
        file_bytes: Optional[bytes] = None,
        salt: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end receipt claim verification and atomic database persistence.

        Guarantees:
        - Atomic transaction execution.
        - On rejection: records rejection audit event and freezes project if a qualifying security
          violation occurs. Leaves claims, invoice_ledger, and verified_spend totals unchanged.
        - On success: registers claim, updates invoice_ledger, increments verified_spend,
          records VENDOR_PAYMENT flow event, and appends CLAIM_VERIFIED audit event.
        """
        now = now if now is not None else int(time.time())
        domain = domain or EIP712Domain()

        # Parse receipt
        try:
            if isinstance(receipt, Receipt):
                rec = receipt
            else:
                rec = Receipt(**receipt)
        except Exception as e:
            return {
                "status": "REJECTED",
                "reason": "MALFORMED_RECEIPT",
                "explanation": f"Receipt failed structural validation: {e}",
                "checks": {"structure_valid": False},
                "disbursement_allowed": False,
                "claimed_amount": 0,
                "remaining_balance": 0,
            }

        # Step 1: Pre-checks on project
        project = self.get_project(rec.project_id)
        if not project:
            return {
                "status": "REJECTED",
                "reason": "PROJECT_NOT_FOUND",
                "explanation": f"Project '{rec.project_id}' does not exist in registry.",
                "checks": {"structure_valid": True, "project_exists": False},
                "disbursement_allowed": False,
                "claimed_amount": 0,
                "remaining_balance": 0,
            }

        project_id = project["id"]
        nullifier_hex = "0x" + rec.invoice_nullifier.hex()

        if project["is_frozen"]:
            return {
                "status": "REJECTED",
                "reason": "PROJECT_FROZEN",
                "explanation": f"Project '{project_id}' is frozen: {project.get('freeze_reason')}",
                "checks": {"structure_valid": True, "project_active": False},
                "disbursement_allowed": False,
                "claimed_amount": 0,
                "remaining_balance": 0,
            }

        # Step 2: Verification using Phase 1 verification engine
        registry = self.get_vendor_registry()
        allowed_category = project["purpose"]  # E.g. WATER_INFRASTRUCTURE

        v_res: VerificationResult = verify_receipt(
            receipt=rec,
            signature=signature,
            domain=domain,
            registry=registry,
            allowed_category=allowed_category,
            now=now,
            file_bytes=file_bytes,
            salt=salt,
        )

        checks = dict(v_res.checks)

        # Step 3: Handle Receipt Verification Failure
        if v_res.status != "VERIFIED":
            reason = v_res.reason or "VERIFICATION_FAILED"
            is_security_violation = reason in SECURITY_FREEZE_REASONS

            # Atomic transaction: record audit event, freeze project if security violation
            conn = self.get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO audit_events (
                            event_id, event_type, project_id, severity, reason_code, details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                            "CLAIM_REJECTED",
                            project_id,
                            "CRITICAL" if is_security_violation else "WARNING",
                            reason,
                            json.dumps(
                                {
                                    "vendor_id": rec.vendor_id,
                                    "invoice_id": rec.invoice_id,
                                    "reason": reason,
                                    "security_violation": is_security_violation,
                                }
                            ),
                            now,
                        ),
                    )

                    if is_security_violation:
                        freeze_reason = f"Security violation: {reason}"
                        conn.execute(
                            "UPDATE projects SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            "UPDATE escrow_state SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE project_id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-FREEZE-{uuid.uuid4().hex[:8].upper()}",
                                "PROJECT_FROZEN",
                                project_id,
                                "CRITICAL",
                                reason,
                                json.dumps({"trigger": reason, "freeze_reason": freeze_reason}),
                                now,
                            ),
                        )
            finally:
                if self._shared_conn is None:
                    conn.close()

            explanation = self._explain_rejection(reason, rec, v_res)
            return {
                "status": "REJECTED",
                "reason": reason,
                "explanation": explanation,
                "checks": checks,
                "disbursement_allowed": False,
                "claimed_amount": 0,
                "remaining_balance": 0,
                "recovered_signer": v_res.recovered_signer,
            }

        # Step 4: Ledger & Cumulative Limits Check within Transaction
        conn = self.get_connection()
        try:
            with conn:
                # Query invoice ledger for nullifier
                cur = conn.execute(
                    "SELECT * FROM invoice_ledger WHERE nullifier = ?",
                    (nullifier_hex,),
                )
                existing = cur.fetchone()

                if existing:
                    # Invariant 1: Cross-report duplicate check
                    if existing["report_id"] != report_id:
                        # CROSS-REPORT REUSE DETECTED!
                        freeze_reason = "Security violation: INVOICE_REUSED_ACROSS_REPORTS"
                        conn.execute(
                            "UPDATE projects SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            "UPDATE escrow_state SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE project_id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                                "CLAIM_REJECTED",
                                project_id,
                                "CRITICAL",
                                "INVOICE_REUSED_ACROSS_REPORTS",
                                json.dumps(
                                    {
                                        "nullifier": nullifier_hex,
                                        "original_report_id": existing["report_id"],
                                        "attempted_report_id": report_id,
                                    }
                                ),
                                now,
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-FREEZE-{uuid.uuid4().hex[:8].upper()}",
                                "PROJECT_FROZEN",
                                project_id,
                                "CRITICAL",
                                "INVOICE_REUSED_ACROSS_REPORTS",
                                json.dumps({"freeze_reason": freeze_reason}),
                                now,
                            ),
                        )
                        return {
                            "status": "REJECTED",
                            "reason": "INVOICE_REUSED_ACROSS_REPORTS",
                            "explanation": (
                                f"Invoice {rec.invoice_id} from {rec.vendor_id} was already claimed under "
                                f"report {existing['report_id']}. Cross-report duplicate invoice submission is blocked."
                            ),
                            "checks": checks,
                            "disbursement_allowed": False,
                            "claimed_amount": existing["claimed"],
                            "remaining_balance": existing["invoice_total"] - existing["claimed"],
                        }

                    # Invariant 2: Invoice total must match original
                    if existing["invoice_total"] != rec.invoice_total:
                        freeze_reason = "Security violation: INVOICE_TOTAL_MISMATCH"
                        conn.execute(
                            "UPDATE projects SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            "UPDATE escrow_state SET is_frozen = 1, freeze_reason = ?, updated_at = ? WHERE project_id = ?",
                            (freeze_reason, now, project_id),
                        )
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                                "CLAIM_REJECTED",
                                project_id,
                                "CRITICAL",
                                "INVOICE_TOTAL_MISMATCH",
                                json.dumps(
                                    {
                                        "original_total": existing["invoice_total"],
                                        "tampered_total": rec.invoice_total,
                                    }
                                ),
                                now,
                            ),
                        )
                        return {
                            "status": "REJECTED",
                            "reason": "INVOICE_TOTAL_MISMATCH",
                            "explanation": "Invoice total does not match previous claim record.",
                            "checks": checks,
                            "disbursement_allowed": False,
                            "claimed_amount": existing["claimed"],
                            "remaining_balance": existing["invoice_total"] - existing["claimed"],
                        }

                    # Invariant 3: Cumulative claim cap check
                    if existing["claimed"] >= existing["invoice_total"]:
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                                "CLAIM_REJECTED",
                                project_id,
                                "WARNING",
                                "INVOICE_ALREADY_FULLY_CLAIMED",
                                json.dumps({"nullifier": nullifier_hex, "claimed": existing["claimed"]}),
                                now,
                            ),
                        )
                        return {
                            "status": "REJECTED",
                            "reason": "INVOICE_ALREADY_FULLY_CLAIMED",
                            "explanation": f"Invoice {rec.invoice_id} is already 100% claimed.",
                            "checks": checks,
                            "disbursement_allowed": False,
                            "claimed_amount": existing["claimed"],
                            "remaining_balance": 0,
                        }

                    new_claimed = existing["claimed"] + claim_amount
                    if new_claimed > existing["invoice_total"]:
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                                "CLAIM_REJECTED",
                                project_id,
                                "WARNING",
                                "CLAIM_EXCEEDS_INVOICE_TOTAL",
                                json.dumps(
                                    {
                                        "invoice_total": existing["invoice_total"],
                                        "previously_claimed": existing["claimed"],
                                        "attempted_claim": claim_amount,
                                    }
                                ),
                                now,
                            ),
                        )
                        return {
                            "status": "REJECTED",
                            "reason": "CLAIM_EXCEEDS_INVOICE_TOTAL",
                            "explanation": (
                                f"Claim amount ({claim_amount}) + prior claimed ({existing['claimed']}) "
                                f"exceeds invoice total ({existing['invoice_total']})."
                            ),
                            "checks": checks,
                            "disbursement_allowed": False,
                            "claimed_amount": existing["claimed"],
                            "remaining_balance": existing["invoice_total"] - existing["claimed"],
                        }

                    # Update ledger record
                    conn.execute(
                        "UPDATE invoice_ledger SET claimed = ?, updated_at = ? WHERE nullifier = ?",
                        (new_claimed, now, nullifier_hex),
                    )
                    remaining = existing["invoice_total"] - new_claimed
                else:
                    # First claim on this nullifier
                    if claim_amount > rec.invoice_total:
                        conn.execute(
                            """
                            INSERT INTO audit_events (
                                event_id, event_type, project_id, severity, reason_code, details_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"AUDIT-REJECT-{uuid.uuid4().hex[:8].upper()}",
                                "CLAIM_REJECTED",
                                project_id,
                                "WARNING",
                                "CLAIM_EXCEEDS_INVOICE_TOTAL",
                                json.dumps({"invoice_total": rec.invoice_total, "claim_amount": claim_amount}),
                                now,
                            ),
                        )
                        return {
                            "status": "REJECTED",
                            "reason": "CLAIM_EXCEEDS_INVOICE_TOTAL",
                            "explanation": f"Claim amount ({claim_amount}) exceeds invoice total ({rec.invoice_total}).",
                            "checks": checks,
                            "disbursement_allowed": False,
                            "claimed_amount": 0,
                            "remaining_balance": rec.invoice_total,
                        }

                    conn.execute(
                        """
                        INSERT INTO invoice_ledger (
                            nullifier, invoice_total, claimed, report_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (nullifier_hex, rec.invoice_total, claim_amount, report_id, now, now),
                    )
                    new_claimed = claim_amount
                    remaining = rec.invoice_total - claim_amount

                # Insert into claims table
                claim_id = f"CLM-{uuid.uuid4().hex[:10].upper()}"
                sig_hex = signature if isinstance(signature, str) else "0x" + signature.hex()
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, project_id, vendor_id, invoice_id, nullifier, report_id,
                        claim_amount, invoice_total, currency, category, issued_at,
                        evidence_commitment, signature, recovered_signer, status, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        project_id,
                        rec.vendor_id,
                        rec.invoice_id,
                        nullifier_hex,
                        report_id,
                        claim_amount,
                        rec.invoice_total,
                        rec.currency,
                        rec.category,
                        rec.issued_at,
                        rec.evidence_commitment,
                        sig_hex,
                        v_res.recovered_signer,
                        "VERIFIED",
                        now,
                    ),
                )

                # Convert claim amount (USD cents) to wei using integer arithmetic:
                # 1 ETH = 2,000 USD = 200,000 cents
                # spend_wei = claim_amount * (10**18) // 200,000 = claim_amount * 5 * 10**12
                spend_wei = claim_amount * 5_000_000_000_000

                cur_proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                curr_spend_wei = int(cur_proj["verified_spend_wei"])
                new_spend_wei = curr_spend_wei + spend_wei
                curr_spend_usd_cents = cur_proj["verified_spend_usd_cents"]
                new_spend_usd_cents = curr_spend_usd_cents + claim_amount

                conn.execute(
                    """
                    UPDATE projects SET
                        verified_spend_wei = ?,
                        verified_spend_usd_cents = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (str(new_spend_wei), new_spend_usd_cents, now, project_id),
                )

                # Flow Event: VENDOR_PAYMENT
                payment_event_id = f"EVT-PAY-{claim_id}"
                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payment_event_id,
                        project_id,
                        "VENDOR_PAYMENT",
                        "EVT-OFFRAMP-T1",
                        "USD_CENTS",
                        str(claim_amount),
                        "USD_CENTS",
                        str(claim_amount),
                        None,
                        1,
                        f"VENDOR_PAYMENT_CONFIRMATION:claim_id={claim_id}:vendor={rec.vendor_id}",
                        json.dumps(
                            {
                                "claim_id": claim_id,
                                "vendor_id": rec.vendor_id,
                                "invoice_id": rec.invoice_id,
                                "category": rec.category,
                            }
                        ),
                        now,
                    ),
                )

                # Audit Event: CLAIM_VERIFIED
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, event_type, project_id, severity, reason_code, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"AUDIT-CLAIM-{uuid.uuid4().hex[:8].upper()}",
                        "CLAIM_VERIFIED",
                        project_id,
                        "INFO",
                        None,
                        json.dumps(
                            {
                                "claim_id": claim_id,
                                "vendor_id": rec.vendor_id,
                                "invoice_id": rec.invoice_id,
                                "amount_usd_cents": claim_amount,
                                "spend_wei": str(spend_wei),
                            }
                        ),
                        now,
                    ),
                )

            checks["receipt_verified"] = True
            checks["ledger_claim_valid"] = True
            return {
                "status": "VERIFIED",
                "claim_id": claim_id,
                "reason": None,
                "explanation": "Claim successfully verified and recorded in black-hole ledger.",
                "checks": checks,
                "disbursement_allowed": True,
                "claimed_amount": new_claimed,
                "remaining_balance": remaining,
                "recovered_signer": v_res.recovered_signer,
            }
        finally:
            if self._shared_conn is None:
                conn.close()

    def release_next_tranche(self, project_id: str) -> Dict[str, Any]:
        """
        Attempts to release the next funding tranche for a project according to simulated escrow rules:
        - Frozen projects cannot release funds.
        - Tranche 1 can be released without verified spending.
        - Each subsequent tranche requires verified spending (in wei) to cover the amount already released.
        - If all tranches are already released, rejects.
        """
        proj = self.get_project(project_id)
        if not proj:
            return {
                "status": "BLOCKED",
                "reason": "PROJECT_NOT_FOUND",
                "explanation": f"Project '{project_id}' does not exist.",
                "disbursement_allowed": False,
            }

        p_id = proj["id"]
        conn = self.get_connection()
        now = int(time.time())
        try:
            with conn:
                cur = conn.execute("SELECT * FROM projects WHERE id = ?", (p_id,))
                proj = cur.fetchone()

                if proj["is_frozen"]:
                    conn.execute(
                        """
                        INSERT INTO audit_events (
                            event_id, event_type, project_id, severity, reason_code, details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"AUDIT-BLOCK-{uuid.uuid4().hex[:8].upper()}",
                            "TRANCHE_BLOCKED",
                            p_id,
                            "WARNING",
                            "PROJECT_FROZEN",
                            json.dumps({"reason": proj["freeze_reason"]}),
                            now,
                        ),
                    )
                    return {
                        "status": "BLOCKED",
                        "reason": "PROJECT_FROZEN",
                        "explanation": f"Cannot release tranche: Project is frozen due to: {proj['freeze_reason']}",
                        "disbursement_allowed": False,
                    }

                total_budget_wei = int(proj["funding_wei"])
                released_wei = int(proj["released_wei"])
                verified_spend_wei = int(proj["verified_spend_wei"])
                current_tranche = proj["current_tranche"]
                total_tranches = proj["total_tranches"]

                if current_tranche >= total_tranches:
                    return {
                        "status": "BLOCKED",
                        "reason": "ALL_TRANCHES_RELEASED",
                        "explanation": f"All {total_tranches} tranches have already been disbursed.",
                        "disbursement_allowed": False,
                    }

                next_tranche_number = current_tranche + 1

                # Rule check: Subsequent tranches require verified spending covering amount already released
                if current_tranche > 0 and verified_spend_wei < released_wei:
                    deficit_wei = released_wei - verified_spend_wei
                    conn.execute(
                        """
                        INSERT INTO audit_events (
                            event_id, event_type, project_id, severity, reason_code, details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"AUDIT-BLOCK-{uuid.uuid4().hex[:8].upper()}",
                            "TRANCHE_BLOCKED",
                            p_id,
                            "WARNING",
                            "INSUFFICIENT_VERIFIED_SPEND",
                            json.dumps(
                                {
                                    "target_tranche": next_tranche_number,
                                    "released_wei": str(released_wei),
                                    "verified_spend_wei": str(verified_spend_wei),
                                    "deficit_wei": str(deficit_wei),
                                }
                            ),
                            now,
                        ),
                    )
                    return {
                        "status": "BLOCKED",
                        "reason": "INSUFFICIENT_VERIFIED_SPEND",
                        "explanation": (
                            f"Tranche {next_tranche_number} requires verified spending covering all prior "
                            f"releases ({released_wei} wei). Current verified spend is {verified_spend_wei} wei."
                        ),
                        "disbursement_allowed": False,
                        "released_wei": released_wei,
                        "verified_spend_wei": verified_spend_wei,
                    }

                # Compute amount for next tranche (first 4: 10 ETH each, 5th: remainder)
                tranche_size_wei = 10 * 10**18
                if next_tranche_number < total_tranches:
                    amount_to_release_wei = tranche_size_wei
                else:
                    amount_to_release_wei = total_budget_wei - released_wei

                new_released_wei = released_wei + amount_to_release_wei

                # Update database
                conn.execute(
                    """
                    UPDATE projects SET
                        current_tranche = ?,
                        released_wei = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (next_tranche_number, str(new_released_wei), now, p_id),
                )
                conn.execute(
                    """
                    UPDATE escrow_state SET
                        current_tranche = ?,
                        released_wei = ?,
                        updated_at = ?
                    WHERE project_id = ?
                    """,
                    (next_tranche_number, str(new_released_wei), now, p_id),
                )

                # Append flow events with unique IDs
                alloc_event_id = f"EVT-ALLOC-T{next_tranche_number}-{uuid.uuid4().hex[:6].upper()}"
                bridge_event_id = f"EVT-BRIDGE-T{next_tranche_number}-{uuid.uuid4().hex[:6].upper()}"
                offramp_event_id = f"EVT-OFFRAMP-T{next_tranche_number}-{uuid.uuid4().hex[:6].upper()}"
                usd_cents_out = (amount_to_release_wei * 200000) // (10**18)

                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alloc_event_id,
                        p_id,
                        "ALLOCATION",
                        "EVT-DONATION-001",
                        "ETH",
                        str(amount_to_release_wei),
                        "ETH",
                        str(amount_to_release_wei),
                        None,
                        1,
                        f"SIMULATED_ALLOCATION:tranche={next_tranche_number}",
                        json.dumps({"tranche": next_tranche_number}),
                        now,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bridge_event_id,
                        p_id,
                        "BRIDGE",
                        alloc_event_id,
                        "ETH",
                        str(amount_to_release_wei),
                        "ETH",
                        str(amount_to_release_wei),
                        None,
                        1,
                        f"SIMULATED_BRIDGE:tx_bridge_t{next_tranche_number}",
                        json.dumps({"destination_network": "Arbitrum One (Simulated)"}),
                        now,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO flow_events (
                        event_id, project_id, event_type, parent_event_id,
                        input_asset, input_amount, output_asset, output_amount,
                        conversion_rate_basis, is_simulated, attestation, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        offramp_event_id,
                        p_id,
                        "OFFRAMP",
                        bridge_event_id,
                        "ETH",
                        str(amount_to_release_wei),
                        "USD_CENTS",
                        str(usd_cents_out),
                        200000,
                        1,
                        f"SIMULATED_OFFRAMP_ATTESTATION:provider=Circle_Sim:ref=sim_offramp_t{next_tranche_number}:status=SETTLED",
                        json.dumps({"provider": "Circle Mint Simulation"}),
                        now,
                    ),
                )

                # Record audit event
                conn.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, event_type, project_id, severity, reason_code, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"AUDIT-RELEASE-{uuid.uuid4().hex[:8].upper()}",
                        "TRANCHE_RELEASED",
                        p_id,
                        "INFO",
                        None,
                        json.dumps(
                            {
                                "tranche_number": next_tranche_number,
                                "released_wei": str(amount_to_release_wei),
                                "total_released_wei": str(new_released_wei),
                            }
                        ),
                        now,
                    ),
                )

                return {
                    "status": "RELEASED",
                    "project_id": p_id,
                    "tranche_number": next_tranche_number,
                    "released_wei": amount_to_release_wei,
                    "total_released_wei": new_released_wei,
                    "remaining_budget_wei": total_budget_wei - new_released_wei,
                    "disbursement_allowed": True,
                }
        finally:
            if self._shared_conn is None:
                conn.close()

    @staticmethod
    def _explain_rejection(reason: str, rec: Receipt, v_res: VerificationResult) -> str:
        """Returns plain-English human-readable explanation for a rejection code."""
        explanations = {
            "SIGNATURE_INVALID": "Vendor EIP-712 cryptographic signature verification failed.",
            "SIGNER_VENDOR_MISMATCH": (
                f"Recovered signer '{v_res.recovered_signer}' does not match registered address "
                f"for vendor '{rec.vendor_id}'."
            ),
            "MALFORMED_SIGNATURE": "Signature format invalid (expected 65 bytes with low-s).",
            "UNREGISTERED_VENDOR": f"Vendor '{rec.vendor_id}' is not in the authorized vendor registry.",
            "CATEGORY_NOT_ALLOWED": (
                f"Receipt category '{rec.category}' is not approved for this project's purpose."
            ),
            "DATED_IN_FUTURE": f"Receipt issue timestamp {rec.issued_at} is dated in the future.",
            "EVIDENCE_COMMITMENT_MISMATCH": (
                "Document file content or salt does not match cryptographic commitment."
            ),
            "MALFORMED_EVIDENCE": "Evidence verification failed closed due to incomplete salt/file.",
            "INVOICE_REUSED_ACROSS_REPORTS": (
                "Invoice nullifier was already claimed in another report. Cross-report duplicate blocked."
            ),
            "CLAIM_EXCEEDS_INVOICE_TOTAL": "Claimed amount exceeds remaining invoice total.",
            "INVOICE_ALREADY_FULLY_CLAIMED": "Invoice total has already been exhausted.",
        }
        return explanations.get(reason, f"Claim rejected due to policy or verification failure: {reason}")
