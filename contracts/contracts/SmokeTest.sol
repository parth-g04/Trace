// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/**
 * @title SmokeTest
 * @notice Temporary contract for Phase 0 toolchain verification only.
 * This is not a TRACE product contract.
 */
contract SmokeTest {
    string public constant STATUS = "TOOLCHAIN_OK";

    function getStatus() external pure returns (string memory) {
        return STATUS;
    }
}
