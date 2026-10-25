# TRACE — The Black Hole Ledger
## Verifiable NGO Fund Flows & Cryptographic Expenditure Integrity

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

1. **Donors & Philanthropic Institutions**: Commit funds into purpose-bound escrow vaults; monitor disbursement gating and verified evidence before downstream tranches release.
2. **NGO Program Operators**: Submit vendor expenditure claims, manage project milestones, and trigger contract-verified tranche disbursements.
3. **Registered Commercial Vendors**: Cryptographically sign canonical invoices using EIP-712 private keys without exposing private banking details.
4. **Independent Auditors & Public Evaluators**: Inspect end-to-end fund-flow traces, detect double-counting, verify conservation arithmetic, and inspect tamper-evident audit logs.

## Product Purpose

TRACE resolves the "Black Hole" problem in non-governmental organization (NGO) donations: traditional fund flows lose traceability once funds cross from cryptocurrency escrows into fiat banking and vendor settlements. TRACE provides an institutional-grade financial integrity dashboard powered by on-chain Solidity escrow enforcement, EIP-712 vendor signatures, and canonical invoice nullifiers.

## Positioning

The only purpose-bound NGO donation protocol that combines:
1. **On-chain Solidity Escrow Gating**: Tranches are locked on-chain and disbursed only when cumulative verified vendor spending matches or exceeds prior disbursements.
2. **The Black Hole Ledger (Nullifier Engine)**: Prevents invoice double-dipping across donor reports and grant projects via canonical normalized identifiers $H(\text{vendor\_id} \parallel \text{canonical\_invoice\_id})$.
3. **Off-Chain Privacy with On-Chain Binding**: Private receipt PDFs, itemized bills, and vendor salts remain off-chain while commitments are cryptographically bound to on-chain attestations.

## Operating Context

- Institutional financial audit terminal.
- Dual execution modes: Deterministic Python Simulation and Local EVM Blockchain (Hardhat / Solidity).
- Strict adherence to integer arithmetic in wei and USD minor units (cents).

## Evidence on Hand

- EIP-712 structured typed data signatures for vendor non-repudiation.
- SHA-256 salted evidence commitments ($H(\text{preimage} \parallel \text{salt})$).
- Reconciled multi-hop conservation graphs (DONATION $\to$ ALLOCATION $\to$ SWAP $\to$ BRIDGE $\to$ OFFRAMP $\to$ VENDOR PAYMENT).
- Immutable SQLite audit trails with real-time discrepancy detectors.

## Product Principles

- **Truthful Accounting**: Zero discrepancies are never fabricated or claimed when conservation mismatches exist.
- **Residual Fiat Transparency**: Unspent off-ramped fiat is tracked as unspent cash, never conflated with vendor payments.
- **Strict Spend-Gating**: Downstream tranches cannot be disbursed until backend and smart contract ledger verify cumulative expenditure $\ge$ released funds.
- **Fail-Closed Security**: Any cryptographic forgery, tampered invoice amount, unauthorized vendor, or duplicate nullifier immediately blocks releases and triggers project freeze.
