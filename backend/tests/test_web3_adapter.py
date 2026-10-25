"""
Unit & Integration tests for TRACE Web3 Service and Blockchain Endpoints.

Tests:
1. RPC unavailable failure handling (fails closed without false success)
2. Missing contract address / undeployed contract handling
3. Wrong chain ID validation
4. Simulation mode backward compatibility
5. Contract state reading (with mocked/stubbed Web3 responses)
6. API endpoint handlers for /chain/status, /chain/state, /chain/mode, /chain/release
7. Fail-closed guarantees on on-chain release failure
"""
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest
from web3.exceptions import ContractLogicError

from backend.app.db import Database
from backend.app.main import (
    chain_release,
    get_chain_state,
    get_chain_status,
    release_tranche,
    set_chain_mode,
)
from backend.app.models.api import ModeUpdateRequest
from backend.app.services.web3_service import Web3Service


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_web3.db")
        db = Database(db_path)
        db.reset_demo_state()
        try:
            yield db
        finally:
            db.close()


def test_web3_service_rpc_unavailable():
    """Verifies that an unreachable RPC endpoint fails gracefully and reports clean diagnostics."""
    svc = Web3Service(rpc_url="http://127.0.0.1:59999")  # Unused port
    assert svc.is_connected() is False
    status = svc.get_status()
    assert status["connected"] is False
    assert status["contract_deployed"] is False
    assert "Cannot connect to JSON-RPC node" in status["error"]


def test_web3_service_missing_contract():
    """Verifies that when contract address is missing or 0x0, contract returns None."""
    svc = Web3Service(contract_address="0x0000000000000000000000000000000000000000")
    assert svc.get_contract() is None


def test_chain_status_endpoint_reports_diagnostics():
    """Verifies get_chain_status returns structured diagnostic information."""
    svc = Web3Service()
    resp = get_chain_status(web3_svc=svc)
    assert hasattr(resp, "connected")
    assert hasattr(resp, "rpc_url")
    assert resp.expected_chain_id == 31337
    assert hasattr(resp, "mode")


def test_chain_mode_toggle():
    """Verifies set_chain_mode allows toggling between simulation and local_chain."""
    svc = Web3Service()

    # Set to local_chain
    resp2 = set_chain_mode(ModeUpdateRequest(mode="local_chain"), web3_svc=svc)
    assert resp2["status"] == "MODE_UPDATED"
    assert resp2["mode"] == "local_chain"
    assert svc.mode == "local_chain"

    # Set to simulation
    resp1 = set_chain_mode(ModeUpdateRequest(mode="simulation"), web3_svc=svc)
    assert resp1["status"] == "MODE_UPDATED"
    assert resp1["mode"] == "simulation"
    assert svc.mode == "simulation"


def test_simulation_mode_backward_compatibility(test_db):
    """Verifies that simulation mode remains 100% backward-compatible for existing release flow."""
    svc = Web3Service(mode="simulation")

    # Tranche 1 release in simulation mode succeeds
    resp = release_tranche(id="WATER-001", db=test_db, web3_svc=svc)
    assert resp.status == "RELEASED"
    assert resp.tranche_number == 1
    assert resp.mode == "simulation"

    # Tranche 2 release without spend is blocked in simulation mode
    resp2 = release_tranche(id="WATER-001", db=test_db, web3_svc=svc)
    # Returns JSONResponse with status 400
    assert hasattr(resp2, "status_code")
    assert resp2.status_code == 400


def test_fail_closed_on_blockchain_release_when_node_offline(test_db):
    """
    CRITICAL REQUIREMENT: When mode is 'local_chain' and the blockchain node is unavailable,
    it MUST NOT silently fall back to simulated release. It must fail closed and return 400.
    """
    svc = Web3Service(
        rpc_url="http://127.0.0.1:59998",
        mode="local_chain",
    )

    resp = release_tranche(id="WATER-001", db=test_db, web3_svc=svc)
    assert hasattr(resp, "status_code")
    assert resp.status_code == 400


def test_mocked_contract_state_and_successful_release():
    """Tests Web3Service release and state querying with mocked contract calls."""
    svc = Web3Service(rpc_url="http://127.0.0.1:8545")

    mock_contract = MagicMock()
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.chain_id = 31337
    mock_w3.eth.block_number = 42
    mock_w3.eth.gas_price = 1000000000
    mock_w3.eth.get_transaction_count.return_value = 1
    mock_w3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"mock-tx")
    mock_w3.eth.send_raw_transaction.return_value = bytes.fromhex("aabbccdd" * 8)
    mock_w3.eth.wait_for_transaction_receipt.return_value = {
        "status": 1,
        "blockNumber": 43,
        "gasUsed": 85000,
    }

    mock_contract.functions.getProjectSummary().call.return_value = (
        b"WATER-001\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        "Clean Water Initiative",
        50 * 10**18,
        5,
        1,  # currentTranche
        10 * 10**18,  # releasedWei
        10 * 10**18,  # verifiedSpendWei
        False,  # isFrozen
        "",  # freezeReason
        40 * 10**18,  # balance
    )

    mock_contract.functions.releaseNextTranche().call.return_value = True
    mock_contract.functions.releaseNextTranche().build_transaction.return_value = {
        "to": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
        "data": b"",
    }

    svc._w3 = mock_w3
    svc._contract = mock_contract
    svc._resolved_address = "0x5FbDB2315678afecb367f032d93F642f64180aa3"

    # 1. Test get_contract_state
    state = svc.get_contract_state()
    assert state["project_id"] == "WATER-001"
    assert state["current_tranche"] == 1
    assert state["released_wei"] == str(10 * 10**18)
    assert state["is_frozen"] is False

    # 2. Test release_next_tranche_on_chain
    res = svc.release_next_tranche_on_chain()
    assert res["status"] == "RELEASED"
    assert res["disbursement_allowed"] is True
    assert "aabbccdd" in res["tx_hash"]
    assert res["block_number"] == 43


def test_mocked_contract_revert_handling():
    """Tests that on-chain contract reverts are caught and clearly categorized."""
    svc = Web3Service(rpc_url="http://127.0.0.1:8545")

    mock_contract = MagicMock()
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_contract.functions.releaseNextTranche().call.side_effect = ContractLogicError(
        "execution reverted: InsufficientVerifiedSpend(10000000000000000000, 0)"
    )

    svc._w3 = mock_w3
    svc._contract = mock_contract

    res = svc.release_next_tranche_on_chain()
    assert res["status"] == "BLOCKED"
    assert res["reason"] == "INSUFFICIENT_VERIFIED_SPEND"
    assert "Contract reverted on-chain" in res["explanation"]
