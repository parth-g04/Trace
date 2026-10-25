import React, { useState } from 'react';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

/**
 * TrancheControl Component
 * Displays tranche disbursement rules, spending thresholds, and executes release attempts.
 * Truthfulness rule: Frontend reflects actual backend release rules and responses; does not authorize releases locally.
 */
export function TrancheControl({ project, onReleaseAttempt }) {
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  if (!project) return null;

  const currentTranche = project.current_tranche;
  const totalTranches = project.total_tranches;
  const nextTranche = currentTranche < totalTranches ? currentTranche + 1 : null;
  const isFrozen = project.is_frozen;

  // Release rules:
  // Tranche 1 requires 0 prior spend.
  // Tranche N (N > 1) requires verified_spend >= released_wei.
  const releasedWei = BigInt(project.released_wei || '0');
  const verifiedSpendWei = BigInt(project.verified_spend_wei || '0');
  const hasMetThreshold = currentTranche === 0 || verifiedSpendWei >= releasedWei;

  const releasedEth = formatWeiToEth(project.released_wei);
  const verifiedSpendEth = formatWeiToEth(project.verified_spend_wei);

  const deficitWei = releasedWei > verifiedSpendWei ? releasedWei - verifiedSpendWei : 0n;
  const deficitEth = formatWeiToEth(deficitWei);

  const handleRelease = async () => {
    setSubmitting(true);
    setLastResult(null);
    try {
      const res = await onReleaseAttempt(project.id);
      setLastResult({ success: res.status === 'RELEASED', data: res });
    } catch (err) {
      setLastResult({
        success: false,
        data: err.data || { reason: 'API_ERROR', explanation: err.message },
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="panel tranche-control-panel">
      <div className="panel-header">
        <div>
          <span className="micro-label">ESCROW DISBURSEMENT CONTROLLER</span>
          <h2 className="panel-title">Tranche Progress & Release Eligibility</h2>
        </div>
        <div className="panel-actions">
          <span className={`badge ${hasMetThreshold && !isFrozen ? 'badge-verified' : 'badge-warning'}`}>
            {isFrozen
              ? 'BLOCKED: PROJECT FROZEN'
              : currentTranche === 0
              ? 'TRANCHE 1 READY'
              : hasMetThreshold
              ? `TRANCHE ${nextTranche} UNLOCKED`
              : `TRANCHE ${nextTranche} LOCKED`}
          </span>
        </div>
      </div>

      <div className="tranche-body">
        <div className="tranche-stats-grid">
          <div className="tranche-stat">
            <span className="micro-label">CURRENT TRANCHE</span>
            <span className="stat-val font-mono">
              {currentTranche} <span className="stat-max">/ {totalTranches}</span>
            </span>
          </div>

          <div className="tranche-stat">
            <span className="micro-label">TOTAL RELEASED</span>
            <span className="stat-val font-mono">{releasedEth} ETH</span>
          </div>

          <div className="tranche-stat">
            <span className="micro-label">VERIFIED EXPENDITURE</span>
            <span className="stat-val font-mono">{verifiedSpendEth} ETH</span>
          </div>

          <div className="tranche-stat">
            <span className="micro-label">NEXT RELEASE REQUIREMENT</span>
            <span className="stat-val font-mono">
              {currentTranche === 0
                ? '0.00 ETH (Initial Release)'
                : `${releasedEth} ETH verified`}
            </span>
          </div>
        </div>

        {/* Threshold explanation */}
        <div className="tranche-threshold-banner">
          {currentTranche === 0 ? (
            <p className="threshold-text">
              Project is at Tranche 0. Initial tranche of 10.00 ETH can be disbursed without prior expenditure claims.
            </p>
          ) : hasMetThreshold ? (
            <p className="threshold-text text-verified">
              Verified spend ({verifiedSpendEth} ETH) covers all prior releases ({releasedEth} ETH). Tranche {nextTranche} is eligible for disbursement.
            </p>
          ) : (
            <p className="threshold-text text-warning">
              Tranche {nextTranche} requires verified spending covering all prior releases ({releasedEth} ETH). Current deficit: <strong className="font-mono">{deficitEth} ETH</strong> ({formatCentsToUsd(Number((deficitWei * 200000n) / 1000000000000000000n))}).
            </p>
          )}
        </div>

        {/* Release Button */}
        <div className="tranche-actions">
          <button
            id="release-tranche-btn"
            className="btn-primary release-trigger-btn"
            onClick={handleRelease}
            disabled={submitting || currentTranche >= totalTranches}
          >
            {submitting ? 'EVALUATING RELEASE VIA BACKEND...' : `ATTEMPT TRANCHE ${nextTranche || 'FULL'} RELEASE`}
          </button>
        </div>

        {/* Outcome Feedback */}
        {lastResult && (
          <div className={`result-box ${lastResult.success ? 'result-success' : 'result-failure'}`}>
            <div className="result-header">
              <span className="micro-label">BACKEND EVALUATION OUTCOME</span>
              <span className={`badge ${lastResult.success ? 'badge-verified' : 'badge-rejected'}`}>
                {lastResult.data.status}
              </span>
            </div>
            {lastResult.data.reason && (
              <div className="result-reason font-mono">
                REASON: {lastResult.data.reason}
              </div>
            )}
            <div className="result-explanation">
              {lastResult.data.explanation || (lastResult.success ? 'Tranche released successfully.' : 'Disbursement rejected by escrow rules.')}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
