"""
=============================================================================
TEST-ONLY DEMO VENDOR IDENTITIES AND KEYS
CRITICAL NOTICE:
The private keys in this module are well-known, public Hardhat/Foundry testing
keys. They are strictly for automated demo scenarios, test fixture generation,
and local evaluation.

NEVER expose these keys to callers of the public REST API.
NEVER use these keys on any public blockchain or with real value.
DO NOT import or use these keys in the production receipt processing path.
=============================================================================
"""
from dataclasses import dataclass
from typing import Dict
from eth_utils import to_checksum_address


@dataclass(frozen=True)
class DemoVendor:
    vendor_id: str
    name: str
    address: str
    # TEST ONLY - Not for production use
    private_key: str
    is_registered: bool = True


# Registered Authorized Demo Vendors for Project WATER-001
VENDOR_WELL_DRILL = DemoVendor(
    vendor_id="WELL-DRILL-01",
    name="Nairobi Borehole Drilling Ltd",
    address=to_checksum_address("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"),
    private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    is_registered=True,
)

VENDOR_SOLAR_PUMP = DemoVendor(
    vendor_id="SOLAR-PUMP-02",
    name="Rift Valley Solar Pumps",
    address=to_checksum_address("0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
    private_key="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    is_registered=True,
)

# Unregistered vendor (address is valid, but NOT in the vendor registry)
VENDOR_UNREGISTERED = DemoVendor(
    vendor_id="UNREGISTERED-VENDOR-99",
    name="Ghost Hardware Supplies",
    address=to_checksum_address("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"),
    private_key="0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    is_registered=False,
)

# Adversary key (used to simulate forgeries and unauthorized signers)
ATTACKER_SIGNER = DemoVendor(
    vendor_id="ATTACKER-KEY-EVIL",
    name="Malicious Adversary Signer",
    address=to_checksum_address("0x1CBd3b2770909D4e10f157cABC84C7264073C9Ec"),
    private_key="0x2a871d0798f97d79848a013d3bbd362c6b97fe5356e0bbeed1241f93003444a0",
    is_registered=False,
)

DEMO_VENDORS_MAP: Dict[str, DemoVendor] = {
    VENDOR_WELL_DRILL.vendor_id: VENDOR_WELL_DRILL,
    VENDOR_SOLAR_PUMP.vendor_id: VENDOR_SOLAR_PUMP,
    VENDOR_UNREGISTERED.vendor_id: VENDOR_UNREGISTERED,
}
