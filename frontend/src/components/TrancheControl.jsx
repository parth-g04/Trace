import React, { useState } from 'react';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

/**
 * TrancheControl Component
 *
 * Implements purposeful disbursement control with strict spend-gating.
 * Supports:
 * - Deterministic Simulation releases via backend SQLite engine
 * - Real on-chain EVM transactions via connected wallet or backend Web3 adapter
 * - Transparent display of release deficit, spending thresholds, and real error reasons
 */
export function TrancheControl({
  project,
  chainState,
  mode,
  _chainStatus,
  wallet,
  contractAddress,
  contractAbi,
  onReleaseAttempt,
  onChainReleaseAttempt,
}) {
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const isChainMode = mode === 'local_chain';
  const effectiveProject = isChainMode && chainState ? chainState : project;

  if (!effectiveProject) return null;

  const currentTranche = Number(effectiveProject.current_tranche ?? 0);
  const totalTranches = Number(effectiveProject.total_tranches ?? 5);
  const nextTranche = currentTranche < totalTranches ? currentTranche + 1 : null;
  const isFrozen = Boolean(effectiveProject.is_frozen);
  const freezeReason = effectiveProject.freeze_reason || 'Security violation detected';

  const releasedWei = BigInt(effectiveProject.released_wei || '0');
  const verifiedSpendWei = BigInt(effectiveProject.verified_spend_wei || '0');

  // Gating rule: Tranche 1 requires no prior spend. Subsequent tranches require spend >= released.
  const hasMetThreshold = currentTranche === 0 || verifiedSpendWei >= releasedWei;
  const deficitWei = releasedWei > verifiedSpendWei ? releasedWei - verifiedSpendWei : 0n;
  const deficitEth = formatWeiToEth(deficitWei);
  const deficitUsd = formatCentsToUsd(Number(deficitWei / 5000000000000n));

  const releasedEth = formatWeiToEth(releasedWei);
  const verifiedSpendEth = formatWeiToEth(verifiedSpendWei);

  const handleRelease = async () => {
    if (submitting) return;
    setSubmitting(true);
    setLastResult(null);

    try {
      let res;
      if (isChainMode) {
        // If user wallet is connected and on correct network, offer direct wallet execution
        if (wallet?.isConnected && !wallet?.isWrongNetwork && contractAddress && contractAbi) {
          res = await wallet.releaseTrancheOnChain(contractAddress, contractAbi);
          res = {
            status: 'RELEASED',
            tx_hash: res.txHash,
            explanation: `Tranche ${nextTranche} confirmed on local Hardhat blockchain.`,
            mode: 'local_chain',
          };
        } else {
          // Otherwise execute via backend Web3 adapter
          res = await onChainReleaseAttempt();
        }
      } else {
        // Simulation mode release
        res = await onReleaseAttempt(project.id);
      }

      setLastResult({
        success: res.status === 'RELEASED',
        data: res,
      });
    } catch (err) {
      console.error('[TrancheControl] Release failed:', err);
      setLastResult({
        success: false,
        data: err.data || {
          reason: err.name || 'RELEASE_FAILED',
          explanation: err.message || 'Transaction reverted or blocked by spend gate.',
        },
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel tranche-control-panel" aria-label="Escrow Disbursement Controller">
      <div className="panel-header">
        <div>
          <span className="micro-label">PURPOSE-BOUND DISBURSEMENT GATE</span>
          <h2 className="panel-title">Tranche Progress & Spend-Gated Release</h2>
        </div>
        <div className="panel-actions">
          <span
            className={`status-chip ${
              isFrozen
                ? 'chip-danger'
                : currentTranche === 0
                ? 'chip-success'
                : hasMetThreshold
                ? 'chip-success'
                : 'chip-warning'
            }`}
          >
            {isFrozen
              ? 'LOCKED (PROJECT FROZEN)'
              : currentTranche === 0
              ? 'TRANCHE 1 READY'
              : currentTranche >= totalTranches
              ? 'ALL TRANCHES RELEASED'
              : hasMetThreshold
              ? `TRANCHE ${nextTranche} UNLOCKED`
              : `TRANCHE ${nextTranche} LOCKED (DEFICIT)`}
          </span>
        </div>
      </div>

      <div className="tranche-body">
        {/* Frozen Alert Banner */}
        {isFrozen && (
          <div className="alert-banner alert-banner-danger" role="alert">
            <div className="alert-header">
              <strong>ESCROW VAULT FROZEN:</strong> {freezeReason}
            </div>
            <p className="alert-text">
              All tranche disbursements are cryptographically halted on-chain. Reset the demo or resolve security findings to restore operations.
            </p>
          </div>
        )}

        {/* 4 Stat Column Row */}
        <div className="tranche-stats-strip">
          <div className="tranche-stat-box">
            <span className="stat-label">CURRENT DISBURSED</span>
            <span className="stat-value font-mono">
              Tranche {currentTranche} <span className="stat-denom">/ {totalTranches}</span>
            </span>
          </div>

          <div className="tranche-stat-box">
            <span className="stat-label">CUMULATIVE RELEASED</span>
            <span className="stat-value font-mono num-tabular">{releasedEth} ETH</span>
          </div>

          <div className="tranche-stat-box">
            <span className="stat-label">VERIFIED SPENDING</span>
            <span className="stat-value font-mono num-tabular">{verifiedSpendEth} ETH</span>
          </div>

          <div className="tranche-stat-box">
            <span className="stat-label">DISBURSEMENT CONDITION</span>
            <span className="stat-value font-mono">
              {currentTranche === 0
                ? '0.00 ETH (Genesis Release)'
                : `${releasedEth} ETH Verified Spend Required`}
            </span>
          </div>
        </div>

        {/* Spend Deficit / Threshold Guidance */}
        {!isFrozen && currentTranche > 0 && currentTranche < totalTranches && (
          <div
            className={`threshold-guidance-box ${
              hasMetThreshold ? 'guidance-unlocked' : 'guidance-locked'
            }`}
          >
            {hasMetThreshold ? (
              <div>
                <strong>Spending Gate Satisfied:</strong> Verified expenditure ({verifiedSpendEth} ETH) meets or exceeds previously disbursed funds ({releasedEth} ETH). Tranche {nextTranche} is eligible for release.
              </div>
            ) : (
              <div>
                <strong>Spending Requirement Unmet:</strong> Tranche {nextTranche} is strictly gated until NGO submits additional verified claims. Current spend deficit:{' '}
                <strong className="font-mono">{deficitEth} ETH</strong> (approx <span className="font-mono">{deficitUsd}</span>).
              </div>
            )}
          </div>
        )}

        {/* Release Action Controls */}
        <div className="tranche-actions-bar">
          <div className="action-mode-info">
            <span className="font-mono text-muted">
              Execution Target:{' '}
              <strong>
                {isChainMode
                  ? wallet?.isConnected
                    ? `Connected Wallet (${wallet.truncatedAddress}) → TraceEscrow.sol`
                    : 'Backend Web3 Relay → TraceEscrow.sol'
                  : 'Python / SQLite Simulated Escrow Vault'}
              </strong>
            </span>
          </div>

          <button
            id="release-tranche-btn"
            type="button"
            className="btn-primary"
            onClick={handleRelease}
            disabled={submitting || isFrozen || currentTranche >= totalTranches}
            title={
              isFrozen
                ? 'Disbursement blocked: project is frozen'
                : currentTranche >= totalTranches
                ? 'All tranches already disbursed'
                : `Attempt disbursement of Tranche ${nextTranche || 1}`
            }
          >
            {submitting
              ? isChainMode
                ? 'CONFIRMING ON CHAIN...'
                : 'RELEASING TRANCHE...'
              : currentTranche >= totalTranches
              ? 'ALL TRANCHES RELEASED'
              : `RELEASE TRANCHE ${nextTranche || 1} (${isChainMode ? 'BLOCKCHAIN' : 'SIMULATION'})`}
          </button>
        </div>

        {/* Last Release Result Feedback Box */}
        {lastResult && (
          <div
            className={`result-feedback-box ${
              lastResult.success ? 'feedback-success' : 'feedback-failure'
            }`}
            role="status"
          >
            <div className="feedback-header">
              <span className={`status-chip ${lastResult.success ? 'chip-success' : 'chip-danger'}`}>
                {lastResult.success ? 'TRANCHE RELEASED' : 'RELEASE BLOCKED'}
              </span>
              {lastResult.data?.tx_hash && (
                <span className="tx-hash-badge font-mono" title={lastResult.data.tx_hash}>
                  TX: {lastResult.data.tx_hash.slice(0, 10)}...{lastResult.data.tx_hash.slice(-8)}
                </span>
              )}
            </div>
            <p className="feedback-explanation">
              {lastResult.data?.explanation || lastResult.data?.reason || 'Evaluation complete.'}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
