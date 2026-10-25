"""
Phase 0 End-to-End Local Chain Connectivity Smoke Test.
Connects to the local Hardhat EVM node via web3.py, queries chain ID and block number.
"""
import sys
from web3 import Web3

def test_connectivity():
    rpc_url = "http://127.0.0.1:8545"
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    is_connected = w3.is_connected()
    print(f"WEB3_CONNECTED: {is_connected}")
    if not is_connected:
        print("ERROR: Failed to connect to local Hardhat node at " + rpc_url, file=sys.stderr)
        sys.exit(1)
        
    chain_id = w3.eth.chain_id
    block_number = w3.eth.block_number
    client_version = w3.client_version
    
    print(f"CHAIN_ID: {chain_id}")
    print(f"BLOCK_NUMBER: {block_number}")
    print(f"CLIENT_VERSION: {client_version}")
    print("CHAIN_CONNECTIVITY_OK")

if __name__ == "__main__":
    test_connectivity()
