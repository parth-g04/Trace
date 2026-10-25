import React from 'react';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

/**
 * MetricCards Component
 * Displays the 4 principal project metric panels required by TRACE M2:
 * 1. Total Funding
 * 2. Released Funds (Tranche progress)
 * 3. Verified Expenditure
 * 4. Unspent Off-Ramp Balance (Residual)
 */
export function MetricCards({ project, traceSummary, loading }) {
  if (loading && !project) {
    return (
      <div className="metric-cards-grid">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="metric-card metric-card-loading">
            <span className="micro-label">LOADING METRIC...</span>
            <div className="metric-skeleton" />
          </div>
        ))}
      </div>
    );
  }

  const fundingEth = formatWeiToEth(project?.funding_wei);
  const releasedEth = formatWeiToEth(project?.released_wei);
  const currentTranche = project?.current_tranche ?? 0;
  const totalTranches = project?.total_tranches ?? 5;

  const verifiedSpendEth = formatWeiToEth(project?.verified_spend_wei);
  const verifiedSpendUsd = formatCentsToUsd(project?.verified_spend_usd_cents ?? 0);

  const residualCents = traceSummary?.offramp_residual_usd_cents ?? 0;
  const residualUsd = formatCentsToUsd(residualCents);
  const totalOfframpedUsd = formatCentsToUsd(traceSummary?.total_offramped_usd_cents ?? 0);

  return (
    <div className="metric-cards-grid">
      {/* Metric A: Total Funding */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="micro-label">TOTAL FUNDING</span>
          <span className="badge badge-neutral">GENESIS ESCROW</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {fundingEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          Target budget: <span className="font-mono">{formatCentsToUsd(50 * 2000 * 100)}</span> (@ $2,000/ETH rate)
        </div>
      </div>

      {/* Metric B: Released Funds */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="micro-label">RELEASED FUNDS</span>
          <span className="badge badge-info">
            TRANCHE {currentTranche} / {totalTranches}
          </span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {releasedEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          {currentTranche === 0
            ? 'No tranches released yet'
            : `${((currentTranche / totalTranches) * 100).toFixed(0)}% of total budget released`}
        </div>
      </div>

      {/* Metric C: Verified Expenditure */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="micro-label">VERIFIED EXPENDITURE</span>
          <span className="badge badge-verified">ACCEPTED CLAIMS</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {verifiedSpendEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          Equivalent to <strong className="font-mono">{verifiedSpendUsd}</strong> in verified vendor claims
        </div>
      </div>

      {/* Metric D: Unspent Off-Ramp Balance */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="micro-label">UNSPENT OFF-RAMP BALANCE</span>
          <span className="badge badge-warning">RESIDUAL FIAT</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {residualUsd}
        </div>
        <div className="metric-subtext">
          {totalOfframpedUsd} off-ramped minus verified disbursements
        </div>
      </div>
    </div>
  );
}
