const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("TraceEscrow Contract Test Suite", function () {
  let traceEscrow;
  let owner;
  let operator;
  let vendor1;
  let vendor2;
  let attacker;
  let recipient;

  const PROJECT_ID = ethers.encodeBytes32String("WATER-001");
  const PROJECT_NAME = "Clean Water Initiative - Turkana Basin";
  const PROJECT_PURPOSE = ethers.encodeBytes32String("WATER_INFRASTRUCTURE");
  const VENDOR_1_ID = ethers.encodeBytes32String("WELL-DRILL-01");
  const VENDOR_2_ID = ethers.encodeBytes32String("SOLAR-PUMP-02");
  const CATEGORY_WATER = ethers.encodeBytes32String("WATER_INFRASTRUCTURE");
  const CATEGORY_FOOD = ethers.encodeBytes32String("FOOD_SUPPLIES");

  const FUNDING_WEI = ethers.parseEther("50"); // 50 ETH
  const TOTAL_TRANCHES = 5n;
  const TRANCHE_SIZE_WEI = ethers.parseEther("10"); // 10 ETH

  beforeEach(async function () {
    [owner, operator, vendor1, vendor2, attacker, recipient] =
      await ethers.getSigners();

    const TraceEscrowFactory = await ethers.getContractFactory("TraceEscrow");
    traceEscrow = await TraceEscrowFactory.deploy(
      PROJECT_ID,
      PROJECT_NAME,
      PROJECT_PURPOSE,
      FUNDING_WEI,
      TOTAL_TRANCHES,
      operator.address
    );
    await traceEscrow.waitForDeployment();

    // Whitelist categories
    await traceEscrow.setAllowedCategory(CATEGORY_WATER, true);

    // Register vendor 1 & vendor 2
    await traceEscrow.registerVendor(VENDOR_1_ID, vendor1.address);
    await traceEscrow.registerVendor(VENDOR_2_ID, vendor2.address);

    // Fund the escrow with 50 ETH
    await owner.sendTransaction({
      to: await traceEscrow.getAddress(),
      value: FUNDING_WEI,
    });
  });

  describe("Initialization & Funding", function () {
    it("should initialize project parameters accurately", async function () {
      const summary = await traceEscrow.getProjectSummary();
      expect(summary._projectId).to.equal(PROJECT_ID);
      expect(summary._projectName).to.equal(PROJECT_NAME);
      expect(summary._fundingWei).to.equal(FUNDING_WEI);
      expect(summary._totalTranches).to.equal(TOTAL_TRANCHES);
      expect(summary._currentTranche).to.equal(0n);
      expect(summary._releasedWei).to.equal(0n);
      expect(summary._verifiedSpendWei).to.equal(0n);
      expect(summary._isFrozen).to.equal(false);
      expect(summary._contractBalance).to.equal(FUNDING_WEI);
    });

    it("should emit EscrowFunded event on deposit", async function () {
      const additionalFund = ethers.parseEther("1");
      await expect(
        traceEscrow.connect(owner).fundEscrow({ value: additionalFund })
      )
        .to.emit(traceEscrow, "EscrowFunded")
        .withArgs(PROJECT_ID, owner.address, additionalFund);
    });
  });

  describe("Tranche Release Spend-Gating", function () {
    it("should allow Tranche 1 release without prior verified spend", async function () {
      const recipientInitial = await ethers.provider.getBalance(recipient.address);

      await expect(
        traceEscrow.connect(operator).releaseNextTranche(recipient.address)
      )
        .to.emit(traceEscrow, "TrancheReleased")
        .withArgs(PROJECT_ID, 1n, TRANCHE_SIZE_WEI, recipient.address);

      const summary = await traceEscrow.getProjectSummary();
      expect(summary._currentTranche).to.equal(1n);
      expect(summary._releasedWei).to.equal(TRANCHE_SIZE_WEI);

      const recipientFinal = await ethers.provider.getBalance(recipient.address);
      expect(recipientFinal - recipientInitial).to.equal(TRANCHE_SIZE_WEI);
    });

    it("should REJECT unauthorized caller attempting tranche release", async function () {
      await expect(
        traceEscrow.connect(attacker).releaseNextTranche(recipient.address)
      ).to.be.revertedWithCustomError(traceEscrow, "NotAuthorized");
    });

    it("should REJECT Tranche 2 release when verified spend is insufficient", async function () {
      // Release Tranche 1
      await traceEscrow.connect(operator).releaseNextTranche(recipient.address);

      // Attempt Tranche 2 release with 0 verified spend (released is 10 ETH)
      await expect(
        traceEscrow.connect(operator).releaseNextTranche(recipient.address)
      )
        .to.be.revertedWithCustomError(traceEscrow, "InsufficientVerifiedSpend")
        .withArgs(TRANCHE_SIZE_WEI, 0n);
    });

    it("should allow Tranche 2 release once cumulative verified spend covers released funds", async function () {
      // Release Tranche 1 (10 ETH)
      await traceEscrow.connect(operator).releaseNextTranche(recipient.address);

      // Record spend attestation: $20,000 USD (2,000,000 cents) = 10 ETH (10 * 10^18 wei)
      const invoiceId = ethers.encodeBytes32String("INV-1001");
      const evidenceCommitment = ethers.keccak256(ethers.toUtf8Bytes("receipt-evidence-1"));
      await traceEscrow
        .connect(operator)
        .recordVerifiedSpendAttestation(
          VENDOR_1_ID,
          invoiceId,
          2000000n, // $20,000.00
          evidenceCommitment
        );

      const summary = await traceEscrow.getProjectSummary();
      expect(summary._verifiedSpendWei).to.equal(TRANCHE_SIZE_WEI);

      // Now Tranche 2 release must succeed!
      await expect(
        traceEscrow.connect(operator).releaseNextTranche(recipient.address)
      )
        .to.emit(traceEscrow, "TrancheReleased")
        .withArgs(PROJECT_ID, 2n, TRANCHE_SIZE_WEI, recipient.address);

      const summaryAfter = await traceEscrow.getProjectSummary();
      expect(summaryAfter._currentTranche).to.equal(2n);
      expect(summaryAfter._releasedWei).to.equal(TRANCHE_SIZE_WEI * 2n);
    });
  });

  describe("Nullifier Collision & Cross-Report Duplicate Defense", function () {
    it("should compute deterministic canonical nullifier matching Python keccak standard", async function () {
      const vendorId = VENDOR_1_ID;
      const invoiceId = ethers.encodeBytes32String("INV-1042");

      const nullifierContract = await traceEscrow.computeNullifier(vendorId, invoiceId);
      const expectedNullifier = ethers.keccak256(
        ethers.AbiCoder.defaultAbiCoder().encode(
          ["bytes32", "bytes32"],
          [vendorId, invoiceId]
        )
      );

      expect(nullifierContract).to.equal(expectedNullifier);
    });

    it("should REJECT duplicate invoice submission, freeze the escrow, and emit security events", async function () {
      const invoiceId = ethers.encodeBytes32String("INV-DUP-99");
      const commitment = ethers.keccak256(ethers.toUtf8Bytes("receipt-dup"));

      // First submission succeeds
      await traceEscrow
        .connect(operator)
        .recordVerifiedSpendAttestation(VENDOR_1_ID, invoiceId, 500000n, commitment);

      const nullifier = await traceEscrow.computeNullifier(VENDOR_1_ID, invoiceId);
      expect(await traceEscrow.nullifiers(nullifier)).to.be.true;

      // Second submission of the same invoice must revert with DuplicateInvoiceNullifier
      await expect(
        traceEscrow
          .connect(operator)
          .recordVerifiedSpendAttestation(VENDOR_1_ID, invoiceId, 500000n, commitment)
      )
        .to.be.revertedWithCustomError(traceEscrow, "DuplicateInvoiceNullifier")
        .withArgs(nullifier);

      // Operator reports duplicate collision on-chain to freeze project
      await expect(
        traceEscrow.connect(operator).reportDuplicateInvoice(VENDOR_1_ID, invoiceId)
      )
        .to.emit(traceEscrow, "DuplicateInvoiceRejected")
        .withArgs(PROJECT_ID, nullifier)
        .and.to.emit(traceEscrow, "ProjectFrozen")
        .withArgs(PROJECT_ID, "INVOICE_REUSED_ACROSS_REPORTS");

      const summary = await traceEscrow.getProjectSummary();
      expect(summary._isFrozen).to.be.true;
      expect(summary._freezeReason).to.equal("INVOICE_REUSED_ACROSS_REPORTS");

      // Releases must now be blocked because project is frozen
      await expect(
        traceEscrow.connect(operator).releaseNextTranche(recipient.address)
      )
        .to.be.revertedWithCustomError(traceEscrow, "ProjectIsFrozen")
        .withArgs("INVOICE_REUSED_ACROSS_REPORTS");
    });
  });

  describe("EIP-712 Signature Verification On-Chain", function () {
    async function signReceipt(vendorSigner, receiptData) {
      const contractAddress = await traceEscrow.getAddress();
      const network = await ethers.provider.getNetwork();

      const domain = {
        name: "TRACE Receipt Registry",
        version: "1",
        chainId: network.chainId,
        verifyingContract: contractAddress,
      };

      const types = {
        Receipt: [
          { name: "projectId", type: "bytes32" },
          { name: "vendorId", type: "bytes32" },
          { name: "invoiceId", type: "bytes32" },
          { name: "invoiceTotal", type: "uint256" },
          { name: "currency", type: "bytes32" },
          { name: "category", type: "bytes32" },
          { name: "issuedAt", type: "uint64" },
          { name: "evidenceCommitment", type: "bytes32" },
        ],
      };

      return await vendorSigner.signTypedData(domain, types, receiptData);
    }

    it("should accept authentic vendor EIP-712 signature and record spend", async function () {
      const receipt = {
        projectId: PROJECT_ID,
        vendorId: VENDOR_1_ID,
        invoiceId: ethers.encodeBytes32String("INV-EIP-01"),
        invoiceTotal: 1000000n, // $10,000.00 USD cents
        currency: ethers.encodeBytes32String("USD"),
        category: CATEGORY_WATER,
        issuedAt: Math.floor(Date.now() / 1000),
        evidenceCommitment: ethers.keccak256(ethers.toUtf8Bytes("salt-evidence-01")),
      };

      const signature = await signReceipt(vendor1, receipt);

      await expect(
        traceEscrow.connect(operator).verifyAndRecordClaim(receipt, signature)
      )
        .to.emit(traceEscrow, "ClaimRecorded");

      const nullifier = await traceEscrow.computeNullifier(receipt.vendorId, receipt.invoiceId);
      expect(await traceEscrow.nullifiers(nullifier)).to.be.true;

      const summary = await traceEscrow.getProjectSummary();
      // 1,000,000 cents * 5*10^12 = 5 * 10^18 wei (5 ETH)
      expect(summary._verifiedSpendWei).to.equal(ethers.parseEther("5"));
    });

    it("should REJECT tampered invoice amount due to signer mismatch", async function () {
      const receipt = {
        projectId: PROJECT_ID,
        vendorId: VENDOR_1_ID,
        invoiceId: ethers.encodeBytes32String("INV-TAMPER-01"),
        invoiceTotal: 100000n, // $1,000 signed
        currency: ethers.encodeBytes32String("USD"),
        category: CATEGORY_WATER,
        issuedAt: Math.floor(Date.now() / 1000),
        evidenceCommitment: ethers.keccak256(ethers.toUtf8Bytes("evidence-tamper")),
      };

      const signature = await signReceipt(vendor1, receipt);

      // Adversary alters invoiceTotal to $10,000
      const tamperedReceipt = { ...receipt, invoiceTotal: 1000000n };

      await expect(
        traceEscrow.connect(operator).verifyAndRecordClaim(tamperedReceipt, signature)
      ).to.be.revertedWithCustomError(traceEscrow, "SignerVendorMismatch");
    });

    it("should REJECT signature from forged / unauthorized key", async function () {
      const receipt = {
        projectId: PROJECT_ID,
        vendorId: VENDOR_1_ID,
        invoiceId: ethers.encodeBytes32String("INV-FORGE-01"),
        invoiceTotal: 500000n,
        currency: ethers.encodeBytes32String("USD"),
        category: CATEGORY_WATER,
        issuedAt: Math.floor(Date.now() / 1000),
        evidenceCommitment: ethers.keccak256(ethers.toUtf8Bytes("evidence-forge")),
      };

      // Attacker signs pretending to be vendor1
      const signature = await signReceipt(attacker, receipt);

      await expect(
        traceEscrow.connect(operator).verifyAndRecordClaim(receipt, signature)
      )
        .to.be.revertedWithCustomError(traceEscrow, "SignerVendorMismatch")
        .withArgs(vendor1.address, attacker.address);
    });

    it("should REJECT unapproved expenditure category", async function () {
      const receipt = {
        projectId: PROJECT_ID,
        vendorId: VENDOR_1_ID,
        invoiceId: ethers.encodeBytes32String("INV-CATEGORY-01"),
        invoiceTotal: 500000n,
        currency: ethers.encodeBytes32String("USD"),
        category: CATEGORY_FOOD, // Not whitelisted
        issuedAt: Math.floor(Date.now() / 1000),
        evidenceCommitment: ethers.keccak256(ethers.toUtf8Bytes("evidence-cat")),
      };

      const signature = await signReceipt(vendor1, receipt);

      await expect(
        traceEscrow.connect(operator).verifyAndRecordClaim(receipt, signature)
      )
        .to.be.revertedWithCustomError(traceEscrow, "CategoryNotAllowed")
        .withArgs(CATEGORY_FOOD);
    });
  });

  describe("Administrative Recovery & Emergency Controls", function () {
    it("should allow owner to freeze and unfreeze project", async function () {
      await expect(traceEscrow.connect(owner).freeze("SECURITY_AUDIT"))
        .to.emit(traceEscrow, "ProjectFrozen")
        .withArgs(PROJECT_ID, "SECURITY_AUDIT");

      expect(await traceEscrow.isFrozen()).to.be.true;

      await expect(traceEscrow.connect(owner).unfreeze())
        .to.emit(traceEscrow, "ProjectUnfrozen")
        .withArgs(PROJECT_ID);

      expect(await traceEscrow.isFrozen()).to.be.false;
    });

    it("should allow emergency sweep only when frozen and only by owner", async function () {
      // Revert if not frozen
      await expect(
        traceEscrow.connect(owner).emergencySweep(recipient.address, FUNDING_WEI)
      ).to.be.revertedWith("MUST_BE_FROZEN_TO_SWEEP");

      await traceEscrow.connect(owner).freeze("EMERGENCY_HALT");

      // Non-owner cannot sweep
      await expect(
        traceEscrow.connect(attacker).emergencySweep(recipient.address, FUNDING_WEI)
      ).to.be.revertedWithCustomError(traceEscrow, "NotAuthorized");

      // Owner can sweep
      const recipientBefore = await ethers.provider.getBalance(recipient.address);
      await expect(
        traceEscrow.connect(owner).emergencySweep(recipient.address, FUNDING_WEI)
      )
        .to.emit(traceEscrow, "EmergencyFundsRescued")
        .withArgs(recipient.address, FUNDING_WEI);

      const recipientAfter = await ethers.provider.getBalance(recipient.address);
      expect(recipientAfter - recipientBefore).to.equal(FUNDING_WEI);
    });
  });
});
