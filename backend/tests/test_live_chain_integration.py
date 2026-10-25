import pytest
from backend.app.services.web3_service import Web3Service

DEPLOYMENT_ADDR = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
HARDHAT_RPC = "http://127.0.0.1:8545"

# Account #1 is the operator configured during deploy
OPERATOR_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def test_live_chain_status_and_read():
    service = Web3Service(
        rpc_url=HARDHAT_RPC,
        contract_address=DEPLOYMENT_ADDR,
        operator_key=OPERATOR_KEY,
    )

    status = service.get_status()
    assert status["connected"] is True
    assert status["chain_id"] == 31337
    assert status["contract_address"].lower() == DEPLOYMENT_ADDR.lower()
    assert status["contract_deployed"] is True
    assert status["mode"] == "simulation"

    state = service.get_contract_state()
    assert state is not None
    assert state["project_id"] == "WATER-001"
    assert state["total_tranches"] == 5
    assert state["is_frozen"] is False
    assert int(state["funding_wei"]) == 50 * 10**18


def test_live_chain_release_and_spend_gate():
    service = Web3Service(
        rpc_url=HARDHAT_RPC,
        contract_address=DEPLOYMENT_ADDR,
        operator_key=OPERATOR_KEY,
    )

    initial_state = service.get_contract_state()
    initial_tranche = initial_state["current_tranche"]

    # If at tranche 0, release tranche 1
    if initial_tranche == 0:
        res = service.release_next_tranche_on_chain()
        assert res["status"] == "RELEASED"
        assert res.get("tx_hash") is not None
        assert res["tranche_number"] == 1
        assert int(res["released_wei"]) == 10 * 10**18

    # Now at tranche 1, attempting tranche 2 without verified spend MUST be blocked by contract spend-gate
    res2 = service.release_next_tranche_on_chain()
    assert res2["status"] == "BLOCKED"
    assert (
        "INSUFFICIENT_VERIFIED_SPEND" in res2.get("reason", "")
        or "revert" in res2.get("explanation", "").lower()
        or "spend" in res2.get("explanation", "").lower()
    )
