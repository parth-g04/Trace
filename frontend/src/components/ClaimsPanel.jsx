import React, { useState } from 'react';
import { formatCentsToUsd } from '../utils/formatters';

export function ClaimsPanel({ claims, loading }) {
  const [selectedClaimId, setSelectedClaimId] = useState(null);

  if (loading && !claims) {
    return (
      <div className="panel claims-panel">
        <div className="panel-header">
          <span className="micro-label">EXPENDITURE CLAIMS & EVIDENCE LEDGER</span>
        </div>
        <div className="claims-loading">Loading verified vendor claims...</div>
      </div>
    );
  }

  const claimList = claims || [];

  return (
    <div className="panel claims-panel">
      <div className="panel-header">
        <div>
          <span className="micro-label">EXPENDITURE CLAIMS & EVIDENCE LEDGER</span>
          <h2 className="panel-title">Cryptographically Authenticated Claims</h2>
        </div>
        <div className="panel-actions">
          <span className="badge badge-neutral">
            {claimList.length} {claimList.length === 1 ? 'RECORD' : 'RECORDS'}
          </span>
        </div>
      </div>

      <div className="claims-notice">
        <p>
          Each expenditure claim is signed using vendor EIP-712 domain keys. The Black Hole Ledger records unique invoice nullifiers to prevent duplicate disbursement across reports.
        </p>
      </div>

      {claimList.length === 0 ? (
        <div className="claims-empty">
          No expenditure claims registered for this project yet. Use the Scenario Console below to evaluate claims.
        </div>
      ) : (
        <div className="claims-table-wrapper">
          <table className="claims-table">
            <thead>
              <tr>
                <th>CLAIM ID</th>
                <th>VENDOR / INVOICE</th>
                <th>AMOUNT</th>
                <th>REPORT ID</th>
                <th>STATUS</th>
                <th>EVIDENCE STATUS</th>
                <th>DETAILS</th>
              </tr>
            </thead>
            <tbody>
              {claimList.map((c) => {
                const isVerified = c.status === 'VERIFIED';
                const hasEvidence = Boolean(c.evidence_commitment && c.evidence_commitment !== '0x' + '00' * 32);
                const isExpanded = selectedClaimId === c.claim_id;

                return (
                  <React.Fragment key={c.claim_id}>
                    <tr className={`claim-row ${isExpanded ? 'row-expanded' : ''}`}>
                      <td className="font-mono">
                        <strong>{c.claim_id}</strong>
                      </td>
                      <td className="font-mono">
                        <div>{c.vendor_id}</div>
                        <div className="cell-subtext">{c.invoice_id}</div>
                      </td>
                      <td className="font-mono num-tabular">
                        <strong>{formatCentsToUsd(c.claim_amount)}</strong>
                        <div className="cell-subtext">{c.currency}</div>
                      </td>
                      <td className="font-mono">{c.report_id}</td>
                      <td>
                        <span className={`badge ${isVerified ? 'badge-verified' : 'badge-rejected'}`}>
                          {c.status}
                        </span>
                      </td>
                      <td>
                        {hasEvidence ? (
                          <span className="badge badge-verified" title={`Commitment: ${c.evidence_commitment}`}>
                            EVIDENCE COMMITMENT VERIFIED
                          </span>
                        ) : (
                          <span className="badge badge-neutral">
                            EVIDENCE NOT PROVIDED
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn-sm"
                          onClick={() => setSelectedClaimId(isExpanded ? null : c.claim_id)}
                        >
                          {isExpanded ? 'HIDE' : 'INSPECT'}
                        </button>
                      </td>
                    </tr>

                    {/* Expanded Detail Row */}
                    {isExpanded && (
                      <tr className="claim-detail-row">
                        <td colSpan={7}>
                          <div className="claim-expanded-card font-mono">
                            <div className="expanded-grid">
                              <div>
                                <span className="micro-label">INVOICE NULLIFIER</span>
                                <div className="expanded-val">{c.nullifier}</div>
                              </div>
                              <div>
                                <span className="micro-label">EIP-712 SIGNER RECOVERED</span>
                                <div className="expanded-val">{c.recovered_signer}</div>
                              </div>
                              <div>
                                <span className="micro-label">CATEGORY</span>
                                <div className="expanded-val">{c.category}</div>
                              </div>
                              <div>
                                <span className="micro-label">EVIDENCE COMMITMENT HASH</span>
                                <div className="expanded-val">{c.evidence_commitment}</div>
                              </div>
                              <div>
                                <span className="micro-label">SUBMISSION TIMESTAMP</span>
                                <div className="expanded-val">
                                  {new Date(c.submitted_at * 1000).toISOString()}
                                </div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
