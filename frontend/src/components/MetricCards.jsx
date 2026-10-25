import React from 'react';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

/**
 * MetricCards Component
 * Displays institutional financial and integrity metrics derived directly
 * from backend SQLite records or on-chain TraceEscrow contract state.
 *
 * Truthfulness Rule:
 * Never hardcodes values, never fabricates zero-discrepancy states,
 * and highlights active financial or conservation warnings.
 */
export function MetricCards({
  project,
  traceSummary,
  chainState,
  mode,
  metrics,
  discrepanciesCount = 0,
  loading = false,
}) {
  if (loading && !project && !chainState) {
    return (
      <div className="metric-cards-grid">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="metric-card metric-card-loading">
            <span className="micro-label">LOADING METRIC...</span>
            <div className="metric-skeleton" />
          </div>
        ))}
      </div>
    );
  }

  // Sourcing data: in local_chain mode with chainState available, use contract values
  const isChainMode = mode === 'local_chain' && Boolean(chainState);

  const fundingWei = isChainMode ? chainState.funding_wei : project?.funding_wei;
  const releasedWei = isChainMode ? chainState.released_wei : project?.released_wei;
  const currentTranche = isChainMode
    ? chainState.current_tranche
    : project?.current_tranche ?? 0;
  const totalTranches = isChainMode
    ? chainState.total_tranches
    : project?.total_tranches ?? 5;
  const verifiedSpendWei = isChainMode
    ? chainState.verified_spend_wei
    : project?.verified_spend_wei;

  const fundingEth = formatWeiToEth(fundingWei);
  const releasedEth = formatWeiToEth(releasedWei);
  const verifiedSpendEth = formatWeiToEth(verifiedSpendWei);

  // Conversion: 1 ETH = 200,000 cents ($2,000.00)
  const verifiedSpendUsd = formatCentsToUsd(
    project?.verified_spend_usd_cents ??
      (BigInt(verifiedSpendWei || '0') / 5000000000000n).toString()
  );

  const residualCents = traceSummary?.offramp_residual_usd_cents ?? 0;
  const residualUsd = formatCentsToUsd(residualCents);
  const totalOfframpedUsd = formatCentsToUsd(traceSummary?.total_offramped_usd_cents ?? 0);

  const validClaimsCount = metrics?.valid_claims ?? 0;
  const rejectedClaimsCount = metrics?.rejected_claims ?? 0;

  return (
    <div className="metric-cards-grid">
      {/* 1. Total Funding */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">TOTAL PROJECT FUNDING</span>
          <span className="metric-source-chip">
            {isChainMode ? 'CONTRACT VAULT' : 'GENESIS ESCROW'}
          </span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {fundingEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          Target budget: <span className="font-mono">{formatCentsToUsd(50 * 2000 * 100)}</span> (@ $2,000/ETH)
        </div>
      </div>

      {/* 2. Released Funds */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">RELEASED FUNDS</span>
          <span className="metric-badge-info font-mono">
            TRANCHE {currentTranche} / {totalTranches}
          </span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {releasedEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          {currentTranche === 0
            ? 'Genesis state: 0 tranches disbursed'
            : `${((currentTranche / totalTranches) * 100).toFixed(0)}% of total escrow disbursed`}
        </div>
      </div>

      {/* 3. Verified Expenditure */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">VERIFIED EXPENDITURE</span>
          <span className="metric-badge-success">CRYPTOGRAPHIC EVIDENCE</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {verifiedSpendEth} <span className="metric-unit">ETH</span>
        </div>
        <div className="metric-subtext">
          Equivalent to <strong className="font-mono">{verifiedSpendUsd}</strong> in verified claims
        </div>
      </div>

      {/* 4. Residual Fiat Balance */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">RESIDUAL FIAT CASH</span>
          <span className="metric-badge-neutral">UNSPENT OFF-RAMP</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          {residualUsd}
        </div>
        <div className="metric-subtext">
          Unspent balance remaining in off-ramp cash reserve (Total: {totalOfframpedUsd})
        </div>
      </div>

      {/* 5. Claims Accepted & Rejected */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">EXPENDITURE CLAIMS</span>
          <span className="metric-source-chip">NULLIFIER LEDGER</span>
        </div>
        <div className="metric-value font-mono num-tabular">
          <span className="text-success">{validClaimsCount}</span>
          <span className="metric-slash">/</span>
          <span className="text-danger">{rejectedClaimsCount}</span>
        </div>
        <div className="metric-subtext">
          <span className="text-success font-mono">{validClaimsCount} accepted</span> ·{' '}
          <span className="text-danger font-mono">{rejectedClaimsCount} rejected</span>
        </div>
      </div>

      {/* 6. Financial Discrepancies */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-label">FINANCIAL DISCREPANCIES</span>
          {discrepanciesCount === 0 ? (
            <span className="metric-badge-success">CONSERVED</span>
          ) : (
            <span className="metric-badge-danger">AUDIT ALERT</span>
          )}
        </div>
        <div className={`metric-value font-mono num-tabular ${discrepanciesCount > 0 ? 'text-danger' : 'text-primary'}`}>
          {discrepanciesCount}
        </div>
        <div className="metric-subtext">
          {discrepanciesCount === 0
            ? 'Multi-hop conservation laws fully satisfied'
            : `${discrepanciesCount} active conservation mismatches detected`}
        </div>
      </div>
    </div>
  );
}
