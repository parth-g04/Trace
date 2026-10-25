# TRACE Receipt Specification & Cryptographic Verification Standard
**CASCADE '26 Hackathon — Problem Statement 4.2: The Black Hole Ledger — Verifiable NGO Fund Flows**

> **Phase 1 Specification:**  
> This specification documents the canonical data structures, EIP-712 typed signing standards, canonical text normalization policies, invoice nullifiers, evidence commitments, and fail-closed verification rules for TRACE. It serves as the authoritative blueprint for Phase 2's Solidity smart contracts (`TraceEscrow.sol`).

---

## 1. Receipt Fields & Schema

A canonical TRACE receipt contains eight logical fields:

| Field Name | Type | Description | Canonical Constraints |
|---|---|---|---|
| `project_id` | `string` / `bytes32` | Identifier of the donor-funded project | Normalized via `normalize_identifier`. Stored as `bytes32` via `id32`. |
| `vendor_id` | `string` / `bytes32` | Identifier of the contracted vendor | Normalized via `normalize_identifier`. Stored as `bytes32` via `id32`. |
| `invoice_id` | `string` / `bytes32` | Vendor invoice or reference number | Normalized via `normalize_invoice_id`. Stored as `bytes32` via `id32`. |
| `invoice_total` | `uint256` | Total monetary value of the invoice in minor units | Validated via `validate_monetary_value`. $1 \le v \le 2^{256} - 1$. Integer minor units (e.g., cents, paise). |
| `currency` | `string` / `bytes32` | 3-letter currency code (ISO 4217) | Exactly 3 ASCII uppercase letters. Stored as `bytes32` via `id32`. |
| `category` | `string` / `bytes32` | Purpose-bound expenditure category | Exactly one of the 5 allowed categories. Stored as `bytes32` via `id32`. |
| `issued_at` | `uint64` | Unix timestamp of receipt issuance (seconds) | Integer seconds: $0 < \text{issued\_at} < 2^{64}$. |
| `evidence_commitment` | `bytes32` | Privacy-preserving salted document commitment | Salted Keccak-256 hash of off-chain invoice PDF/data. |

---

## 2. Canonical Text Normalization & Collision Tradeoffs

### 2.1 General Identifier Normalization (`project_id`, `vendor_id`)
1. **Unicode NFKC normalization:** Decomposes and normalizes equivalent characters.
2. **Trim & Uppercase:** Strips leading/trailing whitespace and converts to uppercase ASCII.
3. **Punctuation & Space Stripping:** Strips all characters outside `[A-Z0-9]`.
4. **Fail-Closed Rejection:** Rejects empty strings or any non-ASCII characters remaining after normalization.

### 2.2 Invoice Identifier Normalization (`invoice_id`)
1. Applies NFKC, whitespace trimming, uppercase conversion, and non-ASCII rejection.
2. Strips all characters outside `[A-Z0-9]`.
3. Strips leading zeros from **each digit run** (`re.sub(r'(?<!\d)0+(?=\d)', '', s)`).
4. Rejects empty results.

#### Proven Equivalence Examples:
- `INV-1042` $\rightarrow$ `INV1042`
- `inv 1042` $\rightarrow$ `INV1042`
- `INV1042` $\rightarrow$ `INV1042`
- `INV-001042` $\rightarrow$ `INV1042`

#### Documented Collision Risk:
Stripping punctuation, whitespace, and leading zeros prevents duplicate claims disguised through formatting variations (e.g. resubmitting `INV-0042` as `INV-42`). However, this policy introduces an intentional collision risk: distinct vendor invoices that differ only by leading zeros (e.g., invoice `001` vs `1` from the same vendor) collapse into the same canonical identity. In the TRACE threat model, this trade-off is accepted to prioritize duplicate fraud prevention.

### 2.3 Currency Normalization
- Exactly three ASCII alphabetic characters (e.g., `USD`, `EUR`, `INR`).
- Case-normalized to uppercase.
- All numbers, symbols, non-3-char strings, or non-ASCII characters are rejected.

### 2.4 Allowed Categories
Only these five locked enumeration strings are permitted:
- `WATER_INFRASTRUCTURE`
- `FOOD_SUPPLIES`
- `MEDICAL_SUPPLIES`
- `EDUCATION`
- `ADMINISTRATION`

---

## 3. Identifiers to `bytes32` Encoding (`id32`)

For Solidity and EIP-712 interoperability, string identifiers are hashed into 32-byte words:

$$\text{id32}(x) = \text{keccak256}(\text{UTF8}(\text{canonical\_}x))$$

- `project_id_bytes32 = id32(canonical_project_id)`
- `vendor_id_bytes32 = id32(canonical_vendor_id)`
- `invoice_id_bytes32 = id32(canonical_invoice_id)`
- `currency_bytes32 = id32(canonical_currency)`
- `category_bytes32 = id32(canonical_category)`

---

## 4. EIP-712 Domain & Typed Data Specification

### 4.1 Domain Separator
```text
EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)
```
- `name`: `TRACE Receipt Registry`
- `version`: `1`
- `chainId`: `31337` (configurable for testnets/mainnet)
- `verifyingContract`: `0x1111111111111111111111111111111111111111` (test placeholder; updated upon Phase 2 deployment)

### 4.2 Primary Type: `Receipt`
Serialized canonical type string (no whitespace or newlines):
```text
Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,bytes32 evidenceCommitment)
```

Type hash:
$$\text{RECEIPT\_TYPEHASH} = \text{keccak256}("Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,bytes32 evidenceCommitment)")$$

---

## 5. Global Invoice Nullifier (Cross-Report Duplicate Protection)

$$\text{nullifier} = \text{keccak256}(\text{abi.encode}(\text{bytes32 } \text{vendorId}, \text{bytes32 } \text{invoiceId}))$$

### Critical Security Invariants:
1. **Standard ABI Encoding:** Encodes two 32-byte words into exactly 64 bytes (`abi.encode`, NOT `abi.encodePacked`).
2. **No `projectId` Binding:** The nullifier is independent of `projectId`. If an NGO submits vendor invoice `INV-1042` to Project Alpha, submitting the same invoice to Project Beta produces an identical nullifier and is rejected.
3. **No Amount or Date Binding:** Tampering with claimed amounts, dates, or evidence does not alter the nullifier.

---

## 6. Evidence Commitment Standard

$$\text{commitment} = \text{keccak256}(\text{abi.encode}(\text{bytes32 } \text{salt}, \text{bytes32 } \text{sha256}(\text{file\_bytes})))$$

- `salt`: Cryptographically secure 32 random bytes (`secrets.token_bytes(32)`).
- `sha256(file_bytes)`: 32-byte SHA-256 digest of off-chain evidence (e.g. receipt PDF).
- `abi.encode(bytes32, bytes32)`: Exactly 64 bytes encoded before Keccak-256 hashing.
- **Privacy Guarantee:** The commitment reveals zero information about the invoice contents or beneficiary details without the salt and original document.

---

## 7. Fail-Closed Signature Validation & Low-s Policy

To prevent signature malleability attacks on secp256k1:
1. **Length:** Exactly 65 bytes (`r`: 32 bytes, `s`: 32 bytes, `v`: 1 byte).
2. **Recovery ID:** $v \in \{27, 28\}$.
3. **Range:** $1 \le r < \text{SECP256K1\_N}$.
4. **Low-$s$ Enforcement:** Rejects any signature where $s > \text{SECP256K1\_N} / 2$:
   $$\text{SECP256K1\_HALF\_N} = \text{0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0}$$
5. **Zero Address Rejection:** Rejects signer recovery yielding `0x0000000000000000000000000000000000000000`.

---

## 8. Verification Pipeline & Reason Codes

`verify_receipt` executes in strict deterministic order:
1. `structure_valid`: Structural format and fields. $\rightarrow$ `MALFORMED_RECEIPT`
2. `signature_format_valid`: 65-byte length, hex format, $v \in \{27, 28\}$, low-$s$. $\rightarrow$ `MALFORMED_SIGNATURE`
3. `signature_valid`: EIP-712 signer recovery. $\rightarrow$ `SIGNATURE_INVALID`
4. `vendor_registered`: Vendor registered in `VendorRegistry`. $\rightarrow$ `UNREGISTERED_VENDOR`
5. `signer_matches_vendor`: Recovered address equals registered vendor key. $\rightarrow$ `SIGNER_VENDOR_MISMATCH`
6. `category_allowed`: Receipt category permitted by project policy. $\rightarrow$ `CATEGORY_NOT_ALLOWED`
7. `timestamp_valid`: `issued_at` not dated in future ($\le \text{now} + 86400$). $\rightarrow$ `DATED_IN_FUTURE`
8. `evidence_verified`: Optional evidence check against commitment. $\rightarrow$ `EVIDENCE_COMMITMENT_MISMATCH` / `MALFORMED_EVIDENCE`

`process_claim` touches the `InvoiceLedger` only after `verify_receipt` passes completely:
- Reused across reports: $\rightarrow$ `INVOICE_REUSED_ACROSS_REPORTS`
- Amount exceeds total or remaining: $\rightarrow$ `CLAIM_EXCEEDS_INVOICE_TOTAL`
- Invoice already fully settled: $\rightarrow$ `INVOICE_ALREADY_FULLY_CLAIMED`
- Tampered invoice total: $\rightarrow$ `INVOICE_TOTAL_MISMATCH`
- Outermost unexpected exception: $\rightarrow$ `INTERNAL_ERROR` (never `VERIFIED`)

---

## 9. Phase 2 Solidity Interoperability Requirements

Phase 2 will implement `TraceEscrow.sol`. The Solidity implementation MUST match this specification exactly:

1. **Hashing:** Standard `keccak256`.
2. **Domain Separator:** Matches `EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)`.
3. **Receipt Struct:**
   ```solidity
   struct Receipt {
       bytes32 projectId;
       bytes32 vendorId;
       bytes32 invoiceId;
       uint256 invoiceTotal;
       bytes32 currency;
       bytes32 category;
       uint64 issuedAt;
       bytes32 evidenceCommitment;
   }
   ```
4. **Encoding Rule:** Standard `abi.encode`, NOT `abi.encodePacked`.
5. **Nullifier Calculation:**
   ```solidity
   bytes32 nullifier = keccak256(abi.encode(receipt.vendorId, receipt.invoiceId));
   ```
6. **Evidence Commitment:**
   ```solidity
   bytes32 commitment = keccak256(abi.encode(salt, sha256(fileBytes)));
   ```
7. **Signature Verification:** Uses `ecrecover` with strict low-$s$ check:
   ```solidity
   require(uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0, "Invalid S");
   require(v == 27 || v == 28, "Invalid V");
   ```

---

## 10. Developer Utilities & Test Reproduction

### Run Test Suite
```bash
cd backend
.\.venv\Scripts\Activate.ps1
pytest -v
```

### Regenerate Deterministic Test Vectors
```bash
cd backend
python scripts/generate_test_vectors.py
```

### Sign a Receipt via CLI
```bash
# Set private key in an environment variable (never pass on CLI)
$env:TRACE_SIGNER_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
python scripts/sign_receipt.py path/to/receipt.json --output signed_receipt.json
```

---

## 11. Security Limitations (What Phase 1 Does NOT Prove)
- **Physical Delivery:** A cryptographically valid vendor signature proves that the holder of the vendor private key signed the statement. It does not prove that goods were delivered in the physical world.
- **Off-Chain Storage:** Evidence commitment proves document integrity; it does not host or persist off-chain files.
- **Blockchain Finality:** Phase 1 is an off-chain Python verification prototype. On-chain autonomous enforcement occurs in Phase 2.
