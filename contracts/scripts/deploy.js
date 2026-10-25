const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer, operator, vendor1, vendor2] = await hre.ethers.getSigners();
  console.log("Deploying TraceEscrow with deployer:", deployer.address);
  console.log("Operator account:", operator.address);

  const PROJECT_ID = hre.ethers.encodeBytes32String("WATER-001");
  const PROJECT_NAME = "Clean Water Initiative - Turkana Basin";
  const PROJECT_PURPOSE = hre.ethers.encodeBytes32String("WATER_INFRASTRUCTURE");
  const FUNDING_WEI = hre.ethers.parseEther("50"); // 50 ETH
  const TOTAL_TRANCHES = 5n;

  const TraceEscrowFactory = await hre.ethers.getContractFactory("TraceEscrow");
  const traceEscrow = await TraceEscrowFactory.deploy(
    PROJECT_ID,
    PROJECT_NAME,
    PROJECT_PURPOSE,
    FUNDING_WEI,
    TOTAL_TRANCHES,
    operator.address
  );
  await traceEscrow.waitForDeployment();
  const contractAddress = await traceEscrow.getAddress();
  console.log("TraceEscrow deployed to:", contractAddress);

  // Configure permitted category: WATER_INFRASTRUCTURE
  const CATEGORY_WATER = hre.ethers.encodeBytes32String("WATER_INFRASTRUCTURE");
  const txCat = await traceEscrow.setAllowedCategory(CATEGORY_WATER, true);
  await txCat.wait();
  console.log("Whitelisted category: WATER_INFRASTRUCTURE");

  // Register demo vendors
  // Hardhat Account #0: WELL-DRILL-01 (0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266)
  // Hardhat Account #1: SOLAR-PUMP-02 (0x70997970C51812dc3A010C7d01b50e0d17dc79C8)
  const VENDOR_1_ID = hre.ethers.encodeBytes32String("WELL-DRILL-01");
  const VENDOR_2_ID = hre.ethers.encodeBytes32String("SOLAR-PUMP-02");

  const txV1 = await traceEscrow.registerVendor(VENDOR_1_ID, deployer.address); // Account #0
  await txV1.wait();
  console.log("Registered vendor WELL-DRILL-01 at:", deployer.address);

  const txV2 = await traceEscrow.registerVendor(VENDOR_2_ID, operator.address); // Account #1
  await txV2.wait();
  console.log("Registered vendor SOLAR-PUMP-02 at:", operator.address);

  // Fund escrow with 50 ETH
  const txFund = await deployer.sendTransaction({
    to: contractAddress,
    value: FUNDING_WEI,
  });
  await txFund.wait();
  console.log("Funded escrow with 50 ETH. Balance:", hre.ethers.formatEther(await hre.ethers.provider.getBalance(contractAddress)), "ETH");

  // Save deployment artifact
  const artifact = await hre.artifacts.readArtifact("TraceEscrow");
  const network = await hre.ethers.provider.getNetwork();

  const deploymentData = {
    address: contractAddress,
    chainId: Number(network.chainId),
    deployer: deployer.address,
    operator: operator.address,
    projectId: "WATER-001",
    fundingWei: FUNDING_WEI.toString(),
    totalTranches: TOTAL_TRANCHES.toString(),
    abi: artifact.abi,
    deployedAt: new Date().toISOString(),
  };

  const deploymentsDir = path.join(__dirname, "..", "deployments");
  if (!fs.existsSync(deploymentsDir)) {
    fs.mkdirSync(deploymentsDir, { recursive: true });
  }

  const deploymentPath = path.join(deploymentsDir, "localhost.json");
  fs.writeFileSync(deploymentPath, JSON.stringify(deploymentData, null, 2));
  console.log("Deployment artifact saved to:", deploymentPath);

  // Also save to frontend src directory for clean access
  const frontendArtifactDir = path.join(__dirname, "..", "..", "frontend", "src", "contracts");
  if (!fs.existsSync(frontendArtifactDir)) {
    fs.mkdirSync(frontendArtifactDir, { recursive: true });
  }
  fs.writeFileSync(path.join(frontendArtifactDir, "TraceEscrow.json"), JSON.stringify(deploymentData, null, 2));
  console.log("Contract artifact synced to frontend:", path.join(frontendArtifactDir, "TraceEscrow.json"));

  return deploymentData;
}

if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch((error) => {
      console.error(error);
      process.exit(1);
    });
}

module.exports = main;
