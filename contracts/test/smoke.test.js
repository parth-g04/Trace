const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("Phase 0 Smoke Test (Toolchain Verification)", function () {
  it("should compile, deploy SmokeTest contract, and return TOOLCHAIN_OK", async function () {
    const SmokeTest = await ethers.getContractFactory("SmokeTest");
    const smokeTest = await SmokeTest.deploy();
    await smokeTest.waitForDeployment();

    const status = await smokeTest.getStatus();
    expect(status).to.equal("TOOLCHAIN_OK");
  });
});
