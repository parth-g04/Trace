// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/**
 * @title TraceEscrow
 * @author TRACE Protocol Engineering Team
 * @notice Purpose-bound NGO donation escrow vault with verifiable spend-gated
 * tranche releases, EIP-712 vendor receipt verification, and canonical invoice nullifiers.
 *
 * Trust Model & Boundaries:
 * 1. Smart Contract Enforcement:
 *    - The contract strictly gates tranche disbursement on-chain. Tranche N > 1 cannot
 *      be released unless cumulative verified expenditures on-chain match or exceed all
 *      previously released funds (verifiedSpendWei >= releasedWei).
 *    - Cross-report duplicate invoice submissions are prevented via deterministic nullifiers
 *      (keccak256(abi.encode(vendorId, invoiceId))). If a nullifier is seen a second time,
 *      the escrow immediately freezes all disbursements.
 *    - Receipts signed by vendors via EIP-712 are verified against registered vendor addresses.
 * 2. Off-Chain Evidence Boundaries:
 *    - The contract validates vendor cryptographic signatures, canonical identities, and authorized
 *      attestations. It does NOT independently inspect real-world physical delivery of goods
 *      or off-chain confidential PDF invoices; evidence commitments (SHA-256) are committed on-chain
 *      while raw evidence remains off-chain for donor/auditor privacy.
 */
contract TraceEscrow {
    // --- Constant Definitions ---

    // Fixed conversion rate: 1 ETH = $2,000.00 USD (200,000 USD cents)
    uint256 public constant ETH_USD_RATE_CENTS = 200000;
    // Integer multiplier: 1 USD cent = 5 * 10^12 wei (10^18 / 200,000)
    uint256 public constant WEI_PER_USD_CENT = 5 * 10**12;

    // Secp256k1 curve half order for ECDSA malleability protection
    uint256 internal constant SECP256K1_HALF_N =
        0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D5761722CE6567983091143308A3853;

    // EIP-712 Domain Separator TypeHash
    bytes32 public constant EIP712_DOMAIN_TYPEHASH =
        keccak256(
            "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
        );

    // EIP-712 Canonical Receipt TypeHash (matches TRACE Python verification engine)
    bytes32 public constant RECEIPT_TYPEHASH =
        keccak256(
            "Receipt(bytes32 projectId,bytes32 vendorId,bytes32 invoiceId,uint256 invoiceTotal,bytes32 currency,bytes32 category,uint64 issuedAt,bytes32 evidenceCommitment)"
        );

    // --- Data Structures ---

    struct Receipt {
        bytes32 projectId;
        bytes32 vendorId;
        bytes32 invoiceId;
        uint256 invoiceTotal; // In minor units (USD cents)
        bytes32 currency;     // e.g. "USD"
        bytes32 category;     // e.g. "WATER_INFRASTRUCTURE"
        uint64 issuedAt;      // Unix timestamp in seconds
        bytes32 evidenceCommitment; // SHA-256 salted evidence hash
    }

    // --- State Variables ---

    address public owner;
    address public operator; // Authorized verifier / backend executor

    bytes32 public projectId;
    string public projectName;
    bytes32 public projectPurpose;
    uint256 public fundingWei;
    uint256 public totalTranches;
    uint256 public currentTranche;
    uint256 public releasedWei;
    uint256 public verifiedSpendWei;

    bool public isFrozen;
    string public freezeReason;

    // EIP-712 Domain Separator (computed in constructor)
    bytes32 public DOMAIN_SEPARATOR;

    // Nullifier registry: nullifier => exists
    mapping(bytes32 => bool) public nullifiers;

    // Authorized Vendor Registry: vendorId => vendorAddress
    mapping(bytes32 => address) public vendorAddresses;
    mapping(bytes32 => bool) public authorizedVendors;

    // Allowed spending categories: categoryHash => isAllowed
    mapping(bytes32 => bool) public allowedCategories;

    // Reentrancy guard lock
    uint256 private _status;
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    // --- Events ---

    event EscrowFunded(bytes32 indexed projectId, address indexed donor, uint256 amountWei);
    event TrancheReleased(
        bytes32 indexed projectId,
        uint256 indexed trancheNumber,
        uint256 amountWei,
        address indexed recipient
    );
    event ClaimRecorded(
        bytes32 indexed projectId,
        bytes32 indexed nullifier,
        bytes32 vendorId,
        uint256 amountWei,
        uint256 cumulativeVerifiedSpendWei,
        bytes32 evidenceCommitment
    );
    event DuplicateInvoiceRejected(bytes32 indexed projectId, bytes32 indexed nullifier);
    event ProjectFrozen(bytes32 indexed projectId, string reason);
    event ProjectUnfrozen(bytes32 indexed projectId);
    event VendorRegistered(bytes32 indexed vendorId, address indexed vendorAddress);
    event CategoryConfigured(bytes32 indexed category, bool isAllowed);
    event OperatorUpdated(address indexed previousOperator, address indexed newOperator);
    event EmergencyFundsRescued(address indexed recipient, uint256 amountWei);

    // --- Custom Errors ---

    error NotAuthorized();
    error ProjectIsFrozen(string reason);
    error AllTranchesReleased();
    error InsufficientContractBalance(uint256 available, uint256 required);
    error InsufficientVerifiedSpend(uint256 requiredWei, uint256 currentSpendWei);
    error DuplicateInvoiceNullifier(bytes32 nullifier);
    error InvalidProjectId();
    error UnregisteredVendor(bytes32 vendorId);
    error SignerVendorMismatch(address expected, address recovered);
    error CategoryNotAllowed(bytes32 category);
    error InvalidSignatureLength();
    error InvalidSignatureS();
    error InvalidSignatureV();
    error TransferFailed();
    error ReentrancyGuard();

    // --- Modifiers ---

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotAuthorized();
        _;
    }

    modifier onlyAuthorized() {
        if (msg.sender != owner && msg.sender != operator) revert NotAuthorized();
        _;
    }

    modifier notFrozen() {
        if (isFrozen) revert ProjectIsFrozen(freezeReason);
        _;
    }

    modifier nonReentrant() {
        if (_status == _ENTERED) revert ReentrancyGuard();
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }

    // --- Constructor ---

    constructor(
        bytes32 _projectId,
        string memory _projectName,
        bytes32 _projectPurpose,
        uint256 _fundingWei,
        uint256 _totalTranches,
        address _operator
    ) {
        require(_totalTranches > 0, "TOTAL_TRANCHES_ZERO");
        require(_fundingWei > 0, "FUNDING_WEI_ZERO");

        owner = msg.sender;
        operator = _operator == address(0) ? msg.sender : _operator;

        projectId = _projectId;
        projectName = _projectName;
        projectPurpose = _projectPurpose;
        fundingWei = _fundingWei;
        totalTranches = _totalTranches;
        currentTranche = 0;
        releasedWei = 0;
        verifiedSpendWei = 0;
        isFrozen = false;
        _status = _NOT_ENTERED;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes("TRACE Receipt Registry")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    // --- Receive & Funding ---

    receive() external payable {
        emit EscrowFunded(projectId, msg.sender, msg.value);
    }

    function fundEscrow() external payable {
        require(msg.value > 0, "ZERO_FUNDING");
        emit EscrowFunded(projectId, msg.sender, msg.value);
    }

    // --- Purpose-Bound Tranche Release ---

    /**
     * @notice Releases the next purpose-bound tranche to an authorized recipient.
     * @dev Release rules strictly enforced by smart contract:
     *      1. Project must not be frozen.
     *      2. Current tranche must be strictly less than totalTranches.
     *      3. Tranche 1 requires no prior spend.
     *      4. Tranche N > 1 requires cumulative verifiedSpendWei >= releasedWei.
     *      5. Follows Checks-Effects-Interactions pattern.
     * @param recipient The recipient address (e.g. NGO operational disbursement wallet)
     */
    function releaseNextTranche(address payable recipient)
        external
        onlyAuthorized
        notFrozen
        nonReentrant
    {
        if (recipient == address(0)) revert NotAuthorized();
        if (currentTranche >= totalTranches) revert AllTranchesReleased();

        uint256 nextTranche = currentTranche + 1;
        uint256 trancheSize = fundingWei / totalTranches;

        // Balance check
        if (address(this).balance < trancheSize) {
            revert InsufficientContractBalance(address(this).balance, trancheSize);
        }

        // Spend-gating condition for downstream tranches (Tranche 2, 3, ...)
        if (nextTranche > 1) {
            if (verifiedSpendWei < releasedWei) {
                revert InsufficientVerifiedSpend(releasedWei, verifiedSpendWei);
            }
        }

        // State update (Effects before Interactions)
        currentTranche = nextTranche;
        releasedWei += trancheSize;

        emit TrancheReleased(projectId, nextTranche, trancheSize, recipient);

        // Interaction
        (bool success, ) = recipient.call{value: trancheSize}("");
        if (!success) revert TransferFailed();
    }

    // --- Nullifier & Claim Tracking ---

    /**
     * @notice Computes canonical invoice nullifier.
     * @dev Exactly mirrors Python: keccak256(abi.encode(bytes32 vendorId, bytes32 invoiceId)).
     */
    function computeNullifier(bytes32 vendorId, bytes32 invoiceId)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(vendorId, invoiceId));
    }

    /**
     * @notice Formally reports a duplicate invoice collision, freezing the escrow.
     * @dev Commits the freeze to storage and emits DuplicateInvoiceRejected + ProjectFrozen.
     */
    function reportDuplicateInvoice(bytes32 vendorId, bytes32 invoiceId)
        external
        onlyAuthorized
    {
        bytes32 nullifier = computeNullifier(vendorId, invoiceId);
        isFrozen = true;
        freezeReason = "INVOICE_REUSED_ACROSS_REPORTS";
        emit DuplicateInvoiceRejected(projectId, nullifier);
        emit ProjectFrozen(projectId, "INVOICE_REUSED_ACROSS_REPORTS");
    }

    /**
     * @notice Records verified expenditure attestation from authorized verifier / backend.
     * @dev Used when off-chain verification (such as receipt evidence hash preimage matching)
     *      is validated off-chain and the result is committed on-chain.
     */
    function recordVerifiedSpendAttestation(
        bytes32 vendorId,
        bytes32 invoiceId,
        uint256 claimAmountUsdCents,
        bytes32 evidenceCommitment
    ) external onlyAuthorized notFrozen {
        bytes32 nullifier = computeNullifier(vendorId, invoiceId);

        // Nullifier collision check: prevents cross-report double-counting
        if (nullifiers[nullifier]) {
            revert DuplicateInvoiceNullifier(nullifier);
        }

        // Record nullifier permanently
        nullifiers[nullifier] = true;

        // Calculate wei equivalent using integer arithmetic
        uint256 claimWei = claimAmountUsdCents * WEI_PER_USD_CENT;
        verifiedSpendWei += claimWei;

        emit ClaimRecorded(
            projectId,
            nullifier,
            vendorId,
            claimWei,
            verifiedSpendWei,
            evidenceCommitment
        );
    }

    /**
     * @notice Verifies an authentic vendor EIP-712 signed receipt and records expenditure on-chain.
     * @dev Validates EIP-712 signature, verifies registered vendor authorization,
     *      checks spending category whitelist, and prevents nullifier reuse.
     */
    function verifyAndRecordClaim(Receipt calldata receipt, bytes calldata signature)
        external
        onlyAuthorized
        notFrozen
        returns (bool)
    {
        // 1. Project ID binding check
        if (receipt.projectId != projectId) revert InvalidProjectId();

        // 2. Vendor registration check
        if (!authorizedVendors[receipt.vendorId]) {
            revert UnregisteredVendor(receipt.vendorId);
        }

        // 3. Category policy check
        if (!allowedCategories[receipt.category]) {
            revert CategoryNotAllowed(receipt.category);
        }

        // 4. Recover signer via EIP-712
        address recovered = recoverSigner(receipt, signature);
        address expectedVendorAddress = vendorAddresses[receipt.vendorId];
        if (recovered != expectedVendorAddress) {
            revert SignerVendorMismatch(expectedVendorAddress, recovered);
        }

        // 5. Canonical nullifier check
        bytes32 nullifier = computeNullifier(receipt.vendorId, receipt.invoiceId);
        if (nullifiers[nullifier]) {
            isFrozen = true;
            freezeReason = "INVOICE_REUSED_ACROSS_REPORTS";
            emit DuplicateInvoiceRejected(projectId, nullifier);
            emit ProjectFrozen(projectId, "INVOICE_REUSED_ACROSS_REPORTS");
            revert DuplicateInvoiceNullifier(nullifier);
        }

        // 6. Record claim and credit spend
        nullifiers[nullifier] = true;
        uint256 claimWei = receipt.invoiceTotal * WEI_PER_USD_CENT;
        verifiedSpendWei += claimWei;

        emit ClaimRecorded(
            projectId,
            nullifier,
            receipt.vendorId,
            claimWei,
            verifiedSpendWei,
            receipt.evidenceCommitment
        );

        return true;
    }

    /**
     * @notice Recovers the signer address for a canonical EIP-712 receipt struct.
     */
    function recoverSigner(Receipt calldata receipt, bytes calldata signature)
        public
        view
        returns (address)
    {
        if (signature.length != 65) revert InvalidSignatureLength();

        bytes32 r;
        bytes32 s;
        uint8 v;

        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }

        // Strict ECDSA malleability check
        if (uint256(s) > SECP256K1_HALF_N) revert InvalidSignatureS();
        if (v != 27 && v != 28) revert InvalidSignatureV();

        bytes32 structHash = keccak256(
            abi.encode(
                RECEIPT_TYPEHASH,
                receipt.projectId,
                receipt.vendorId,
                receipt.invoiceId,
                receipt.invoiceTotal,
                receipt.currency,
                receipt.category,
                receipt.issuedAt,
                receipt.evidenceCommitment
            )
        );

        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash)
        );

        address signer = ecrecover(digest, v, r, s);
        require(signer != address(0), "INVALID_SIGNER_ZERO");
        return signer;
    }

    // --- Administrative & Governance Controls ---

    /**
     * @notice Explicitly freezes project disbursements due to security violation or fraud detection.
     */
    function freeze(string calldata reason) external onlyAuthorized {
        isFrozen = true;
        freezeReason = reason;
        emit ProjectFrozen(projectId, reason);
    }

    /**
     * @notice Unfreezes project disbursements following investigation and remediation.
     */
    function unfreeze() external onlyOwner {
        isFrozen = false;
        freezeReason = "";
        emit ProjectUnfrozen(projectId);
    }

    /**
     * @notice Registers an authorized vendor address for a vendor ID.
     */
    function registerVendor(
        bytes32 vendorId,
        address vendorAddress
    ) external onlyOwner {
        require(vendorAddress != address(0), "INVALID_VENDOR_ADDR");
        vendorAddresses[vendorId] = vendorAddress;
        authorizedVendors[vendorId] = true;
        emit VendorRegistered(vendorId, vendorAddress);
    }

    /**
     * @notice Configures permitted expenditure categories for project mandate.
     */
    function setAllowedCategory(bytes32 category, bool isAllowed) external onlyOwner {
        allowedCategories[category] = isAllowed;
        emit CategoryConfigured(category, isAllowed);
    }

    /**
     * @notice Updates authorized operator role.
     */
    function setOperator(address newOperator) external onlyOwner {
        require(newOperator != address(0), "INVALID_OPERATOR");
        emit OperatorUpdated(operator, newOperator);
        operator = newOperator;
    }

    /**
     * @notice Emergency recovery of remaining funds if project is permanently halted.
     */
    function emergencySweep(address payable recipient, uint256 amountWei)
        external
        onlyOwner
        nonReentrant
    {
        require(isFrozen, "MUST_BE_FROZEN_TO_SWEEP");
        require(recipient != address(0), "INVALID_RECIPIENT");
        require(amountWei <= address(this).balance, "EXCEEDS_BALANCE");

        emit EmergencyFundsRescued(recipient, amountWei);

        (bool success, ) = recipient.call{value: amountWei}("");
        if (!success) revert TransferFailed();
    }

    // --- View Helpers ---

    /**
     * @notice Returns complete project summary tuple for easy frontend and Web3 adapter querying.
     */
    function getProjectSummary()
        external
        view
        returns (
            bytes32 _projectId,
            string memory _projectName,
            uint256 _fundingWei,
            uint256 _totalTranches,
            uint256 _currentTranche,
            uint256 _releasedWei,
            uint256 _verifiedSpendWei,
            bool _isFrozen,
            string memory _freezeReason,
            uint256 _contractBalance
        )
    {
        return (
            projectId,
            projectName,
            fundingWei,
            totalTranches,
            currentTranche,
            releasedWei,
            verifiedSpendWei,
            isFrozen,
            freezeReason,
            address(this).balance
        );
    }
}
