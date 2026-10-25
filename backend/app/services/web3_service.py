"""
Web3 Service & JSON-RPC Adapter for TRACE.

Interacts with the local Ethereum-compatible JSON-RPC node (Hardhat) and the
TraceEscrow smart contract using web3.py.

Handles:
- Node connectivity checks & chain ID validation
- Contract bytecode & deployment verification
- Reading purpose-bound escrow state directly from the blockchain
- Submitting authorized tranche release transactions and waiting for receipts
- Transparently reporting transaction hashes, block numbers, gas, and revert reasons
- Fail-closed error handling (never silently falling back to simulated success)
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError, Web3Exception

logger = logging.getLogger("trace.web3_service")

# Default local Hardhat network parameters
DEFAULT_RPC_URL = "http://127.0.0.1:8545"
DEFAULT_CHAIN_ID = 31337

# Default Hardhat Account #1 private key for testing/operator transactions
# Publicly known test fixture only - NEVER use on public networks
DEFAULT_OPERATOR_KEY = (
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
)

# Deployment artifact search paths
DEPLOYMENT_PATHS = [
    Path(__file__).resolve().parent.parent.parent.parent
    / "contracts"
    / "deployments"
    / "localhost.json",
    Path(__file__).resolve().parent.parent.parent.parent
    / "frontend"
    / "src"
    / "contracts"
    / "TraceEscrow.json",
]


class Web3Service:
    """
    TRACE Web3 Contract Service managing local EVM blockchain interactions.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        chain_id: Optional[int] = None,
        contract_address: Optional[str] = None,
        mode: Optional[str] = None,
        operator_key: Optional[str] = None,
    ) -> None:
        self.rpc_url = rpc_url or os.environ.get("RPC_URL", DEFAULT_RPC_URL)
        self.expected_chain_id = chain_id or int(
            os.environ.get("CHAIN_ID", str(DEFAULT_CHAIN_ID))
        )
        self._manual_contract_address = contract_address or os.environ.get(
            "TRACE_ESCROW_CONTRACT_ADDRESS"
        )
        self.mode = mode or os.environ.get("TRACE_MODE", "simulation")

        # Operator account for authorized on-chain transactions
        self.operator_key = operator_key or os.environ.get(
            "OPERATOR_PRIVATE_KEY", DEFAULT_OPERATOR_KEY
        )

        self._w3: Optional[Web3] = None
        self._contract: Optional[Any] = None
        self._contract_abi: Optional[list] = None
        self._resolved_address: Optional[str] = None

    @property
    def w3(self) -> Web3:
        """Lazy-loaded Web3 provider instance."""
        if self._w3 is None:
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 5.0}))
        return self._w3

    def is_connected(self) -> bool:
        """Checks if the configured JSON-RPC endpoint is responsive."""
        try:
            return bool(self.w3.is_connected())
        except Exception:
            return False

    def load_deployment_info(self) -> Tuple[Optional[str], Optional[list]]:
        """Loads contract address and ABI from deployment artifacts."""
        if self._resolved_address and self._contract_abi:
            return self._resolved_address, self._contract_abi

        # If manually specified in environment / constructor
        if self._manual_contract_address is not None:
            if self._manual_contract_address == "" or self._manual_contract_address == "0x0000000000000000000000000000000000000000":
                self._resolved_address = "0x0000000000000000000000000000000000000000"
            else:
                try:
                    self._resolved_address = Web3.to_checksum_address(self._manual_contract_address)
                except Exception:
                    self._resolved_address = None

        for p in DEPLOYMENT_PATHS:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        addr = data.get("address")
                        abi = data.get("abi")
                        if addr and self._resolved_address is None and self._manual_contract_address is None:
                            self._resolved_address = Web3.to_checksum_address(addr)
                        if abi:
                            self._contract_abi = abi
                        if self._resolved_address and self._contract_abi:
                            return self._resolved_address, self._contract_abi
                except Exception as e:
                    logger.warning("Failed to parse deployment artifact at %s: %s", p, e)

        return self._resolved_address, self._contract_abi

    def get_contract(self) -> Optional[Any]:
        """Returns initialized Contract instance if deployed."""
        if self._contract is not None:
            return self._contract

        addr, abi = self.load_deployment_info()
        if not addr or not abi or not self.is_connected():
            return None

        try:
            # Check that bytecode exists at address
            code = self.w3.eth.get_code(addr)
            if not code or code == b"" or code == b"\x00":
                return None
            self._contract = self.w3.eth.contract(address=addr, abi=abi)
            return self._contract
        except Exception as e:
            logger.warning("Failed to initialize contract at %s: %s", addr, e)
            return None

    def get_status(self) -> Dict[str, Any]:
        """Provides full diagnostic status of blockchain connectivity and contract deployment."""
        connected = self.is_connected()
        actual_chain_id: Optional[int] = None
        block_number: Optional[int] = None
        contract_deployed = False
        addr, _ = self.load_deployment_info()
        err_msg: Optional[str] = None

        if connected:
            try:
                actual_chain_id = self.w3.eth.chain_id
                block_number = self.w3.eth.block_number

                if actual_chain_id != self.expected_chain_id:
                    err_msg = (
                        f"Chain ID mismatch: Node returned {actual_chain_id}, "
                        f"expected {self.expected_chain_id}."
                    )

                if addr:
                    code = self.w3.eth.get_code(addr)
                    contract_deployed = bool(code and code != b"" and code != b"\x00")
                    if not contract_deployed:
                        err_msg = f"No contract bytecode deployed at {addr}."
                else:
                    err_msg = "No contract address configured or deployed."
            except Exception as e:
                err_msg = f"RPC query error: {str(e)}"
        else:
            err_msg = f"Cannot connect to JSON-RPC node at {self.rpc_url}."

        return {
            "connected": connected,
            "rpc_url": self.rpc_url,
            "chain_id": actual_chain_id,
            "expected_chain_id": self.expected_chain_id,
            "block_number": block_number,
            "contract_address": addr,
            "contract_deployed": contract_deployed,
            "mode": self.mode,
            "error": err_msg if not (connected and contract_deployed and not err_msg) else None,
        }

    def get_contract_state(self) -> Dict[str, Any]:
        """Queries on-chain project state from TraceEscrow contract."""
        contract = self.get_contract()
        if not contract:
            status = self.get_status()
            raise RuntimeError(
                f"TraceEscrow contract unavailable on chain: {status.get('error', 'Unknown error')}"
            )

        try:
            summary = contract.functions.getProjectSummary().call()
            # Summary tuple:
            # (projectId, projectName, fundingWei, totalTranches, currentTranche,
            #  releasedWei, verifiedSpendWei, isFrozen, freezeReason, contractBalance)
            proj_id_bytes = summary[0]
            # Convert bytes32 to decoded string without trailing nulls
            try:
                proj_id = proj_id_bytes.rstrip(b"\x00").decode("utf-8")
            except Exception:
                proj_id = "WATER-001"

            return {
                "project_id": proj_id,
                "project_name": summary[1],
                "funding_wei": str(summary[2]),
                "total_tranches": int(summary[3]),
                "current_tranche": int(summary[4]),
                "released_wei": str(summary[5]),
                "verified_spend_wei": str(summary[6]),
                "is_frozen": bool(summary[7]),
                "freeze_reason": summary[8] or None,
                "contract_balance_wei": str(summary[9]),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to read contract state from chain: {e}") from e

    def release_next_tranche_on_chain(
        self, recipient: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits an authorized on-chain release transaction to TraceEscrow.
        Waits for transaction receipt and validates status == 1.
        Never falsely reports success.
        """
        contract = self.get_contract()
        if not contract:
            status = self.get_status()
            return {
                "status": "BLOCKED",
                "reason": "BLOCKCHAIN_UNAVAILABLE",
                "explanation": f"Cannot execute on-chain release: {status.get('error')}",
                "disbursement_allowed": False,
            }

        account = Account.from_key(self.operator_key)
        operator_address = account.address

        # Target recipient: operator address if none specified
        target_recipient = Web3.to_checksum_address(recipient or operator_address)

        try:
            # Simulate first via eth_call to catch custom errors and reasons before sending
            contract.functions.releaseNextTranche(target_recipient).call(
                {"from": operator_address}
            )
        except ContractLogicError as e:
            # The contract reverted on-chain
            err_msg = str(e)
            reason = "CONTRACT_REVERT"
            if "InsufficientVerifiedSpend" in err_msg:
                reason = "INSUFFICIENT_VERIFIED_SPEND"
            elif "ProjectIsFrozen" in err_msg:
                reason = "PROJECT_FROZEN"
            elif "AllTranchesReleased" in err_msg:
                reason = "ALL_TRANCHES_RELEASED"
            elif "NotAuthorized" in err_msg:
                reason = "UNAUTHORIZED"

            return {
                "status": "BLOCKED",
                "reason": reason,
                "explanation": f"Contract reverted on-chain: {err_msg}",
                "disbursement_allowed": False,
            }
        except Exception as e:
            return {
                "status": "BLOCKED",
                "reason": "SIMULATION_FAILED",
                "explanation": f"Pre-flight call check failed: {str(e)}",
                "disbursement_allowed": False,
            }

        # Build and sign transaction
        try:
            nonce = self.w3.eth.get_transaction_count(operator_address, "pending")
            gas_price = self.w3.eth.gas_price

            tx = contract.functions.releaseNextTranche(target_recipient).build_transaction(
                {
                    "from": operator_address,
                    "nonce": nonce,
                    "gas": 300000,
                    "gasPrice": gas_price,
                    "chainId": self.expected_chain_id,
                }
            )

            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.operator_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            # Wait for receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)

            if receipt.get("status") != 1:
                return {
                    "status": "BLOCKED",
                    "reason": "TRANSACTION_REVERTED",
                    "explanation": f"On-chain transaction reverted (tx: {tx_hash.hex()}).",
                    "disbursement_allowed": False,
                    "tx_hash": tx_hash.hex(),
                    "block_number": receipt.get("blockNumber"),
                }

            # Transaction confirmed! Query new state
            new_state = self.get_contract_state()

            return {
                "status": "RELEASED",
                "project_id": new_state["project_id"],
                "tranche_number": new_state["current_tranche"],
                "released_wei": int(new_state["released_wei"]),
                "total_released_wei": int(new_state["released_wei"]),
                "remaining_budget_wei": int(new_state["funding_wei"]) - int(new_state["released_wei"]),
                "disbursement_allowed": True,
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.get("blockNumber"),
                "recipient": target_recipient,
                "explanation": (
                    f"Tranche {new_state['current_tranche']} successfully disbursed on local chain "
                    f"(Block #{receipt.get('blockNumber')}, Tx: {tx_hash.hex()[:10]}...)."
                ),
            }

        except Exception as e:
            return {
                "status": "BLOCKED",
                "reason": "TRANSACTION_EXECUTION_ERROR",
                "explanation": f"Failed to execute on-chain transaction: {str(e)}",
                "disbursement_allowed": False,
            }

    def record_claim_attestation_on_chain(
        self,
        vendor_id: str,
        invoice_id: str,
        claim_usd_cents: int,
        evidence_commitment: str,
    ) -> Dict[str, Any]:
        """
        Submits a verified expenditure attestation to the TraceEscrow contract on-chain.
        """
        contract = self.get_contract()
        if not contract:
            return {"status": "FAILED", "reason": "CONTRACT_UNAVAILABLE"}

        account = Account.from_key(self.operator_key)
        operator_address = account.address

        # Encode bytes32 fields
        v_bytes = vendor_id.encode("utf-8").ljust(32, b"\x00")[:32]
        i_bytes = invoice_id.encode("utf-8").ljust(32, b"\x00")[:32]
        c_bytes = (
            bytes.fromhex(evidence_commitment[2:])
            if evidence_commitment.startswith("0x")
            else bytes.fromhex(evidence_commitment)
        )
        if len(c_bytes) < 32:
            c_bytes = c_bytes.ljust(32, b"\x00")

        try:
            nonce = self.w3.eth.get_transaction_count(operator_address, "pending")
            gas_price = self.w3.eth.gas_price

            tx = contract.functions.recordVerifiedSpendAttestation(
                v_bytes, i_bytes, claim_usd_cents, c_bytes
            ).build_transaction(
                {
                    "from": operator_address,
                    "nonce": nonce,
                    "gas": 300000,
                    "gasPrice": gas_price,
                    "chainId": self.expected_chain_id,
                }
            )

            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.operator_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)

            return {
                "status": "SUCCESS" if receipt.get("status") == 1 else "REVERTED",
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.get("blockNumber"),
            }
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}

    def report_duplicate_on_chain(
        self, vendor_id: str, invoice_id: str
    ) -> Dict[str, Any]:
        """
        Reports an invoice nullifier collision on-chain, committing the project freeze.
        """
        contract = self.get_contract()
        if not contract:
            return {"status": "FAILED", "reason": "CONTRACT_UNAVAILABLE"}

        account = Account.from_key(self.operator_key)
        operator_address = account.address
        v_bytes = vendor_id.encode("utf-8").ljust(32, b"\x00")[:32]
        i_bytes = invoice_id.encode("utf-8").ljust(32, b"\x00")[:32]

        try:
            nonce = self.w3.eth.get_transaction_count(operator_address, "pending")
            tx = contract.functions.reportDuplicateInvoice(v_bytes, i_bytes).build_transaction(
                {
                    "from": operator_address,
                    "nonce": nonce,
                    "gas": 300000,
                    "gasPrice": self.w3.eth.gas_price,
                    "chainId": self.expected_chain_id,
                }
            )
            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.operator_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)
            return {
                "status": "FROZEN_ON_CHAIN" if receipt.get("status") == 1 else "REVERTED",
                "tx_hash": tx_hash.hex(),
                "block_number": receipt.get("blockNumber"),
            }
        except Exception as e:
            return {"status": "FAILED", "error": str(e)}
