import React, { useState } from 'react';
import { EventInspector } from './EventInspector';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

function formatNodeAmount(asset, amountStr) {
  if (!amountStr) return '0';
  if (asset === 'ETH') return `${formatWeiToEth(amountStr)} ETH`;
  if (asset === 'USDC') return `${(Number(amountStr) / 1000000).toLocaleString()} USDC`;
  if (asset === 'USD_CENTS') return formatCentsToUsd(Number(amountStr));
  return `${amountStr} ${asset}`;
}

export function FundFlowGraph({ trace, loading }) {
  const [selectedEventId, setSelectedEventId] = useState(null);

  if (loading && !trace) {
    return (
      <div className="panel trace-panel">
        <div className="panel-header">
          <span className="micro-label">FUND-FLOW TRACE GRAPH</span>
        </div>
        <div className="graph-loading">Loading multi-hop trace graph...</div>
      </div>
    );
  }

  const events = trace?.events || [];
  const discrepancies = trace?.discrepancies || [];
  const isConserved = trace?.is_conserved ?? true;
  const selectedEvent = events.find((e) => e.event_id === selectedEventId);

  // Group events into chain hops:
  // Root (DONATION) -> ALLOCATION -> SWAP -> BRIDGE -> OFFRAMP -> VENDOR_PAYMENT(s)
  const nonPayments = events.filter((e) => e.event_type !== 'VENDOR_PAYMENT');
  const payments = events.filter((e) => e.event_type === 'VENDOR_PAYMENT');

  return (
    <div className="panel trace-panel">
      <div className="panel-header">
        <div>
          <span className="micro-label">CRYPTOGRAPHIC FUND-FLOW TRACE</span>
          <h2 className="panel-title">End-to-End Asset Conservation Graph</h2>
        </div>
        <div className="panel-actions">
          <span className={`badge ${isConserved ? 'badge-verified' : 'badge-rejected'}`}>
            {isConserved
              ? 'INTEGER CONSERVED · 0 DISCREPANCIES'
              : `${discrepancies.length} DISCREPANCIES DETECTED`}
          </span>
        </div>
      </div>

      {/* Discrepancies Alert Banner if any */}
      {discrepancies.length > 0 && (
        <div className="discrepancy-banner">
          <div className="discrepancy-title">Security & Conservation Alerts:</div>
          {discrepancies.map((d, idx) => (
            <div key={idx} className="discrepancy-item">
              <span className="badge badge-rejected">{d.code}</span>
              <span className="discrepancy-text">{d.explanation}</span>
            </div>
          ))}
        </div>
      )}

      {/* Graph Legend */}
      <div className="graph-legend">
        <div className="legend-item">
          <span className="legend-box legend-real" />
          <span>Real Settlement</span>
        </div>
        <div className="legend-item">
          <span className="legend-box legend-simulated" />
          <span>Simulated Engine Hop</span>
        </div>
        <div className="legend-item">
          <span className="legend-box legend-payment" />
          <span>Vendor Payment (Claimed)</span>
        </div>
        <div className="legend-item">
          <span className="legend-line" />
          <span>Parent Edge</span>
        </div>
      </div>

      {/* Graph Canvas */}
      <div className="graph-canvas">
        {events.length === 0 ? (
          <div className="graph-empty">No flow events recorded for this project yet.</div>
        ) : (
          <div className="graph-flow-container">
            {/* Primary Hop Chain */}
            <div className="flow-hops-row">
              {nonPayments.map((evt, idx) => {
                const isSelected = evt.event_id === selectedEventId;
                const isReal = !evt.is_simulated;

                return (
                  <React.Fragment key={evt.event_id}>
                    <div
                      id={`node-${evt.event_id}`}
                      className={`flow-node ${isReal ? 'node-real' : 'node-simulated'} ${
                        isSelected ? 'node-selected' : ''
                      }`}
                      onClick={() => setSelectedEventId(evt.event_id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          setSelectedEventId(evt.event_id);
                        }
                      }}
                    >
                      <div className="node-header">
                        <span className="node-type font-mono">{evt.event_type}</span>
                        <span className={`badge ${isReal ? 'badge-verified' : 'badge-neutral'}`}>
                          {isReal ? 'REAL' : 'SIM'}
                        </span>
                      </div>
                      <div className="node-id font-mono">{evt.event_id}</div>
                      <div className="node-amounts font-mono">
                        <div className="node-amt in">
                          IN: {formatNodeAmount(evt.input_asset, evt.input_amount)}
                        </div>
                        <div className="node-amt out">
                          OUT: {formatNodeAmount(evt.output_asset, evt.output_amount)}
                        </div>
                      </div>
                    </div>

                    {/* Arrow to next non-payment or to payments */}
                    {(idx < nonPayments.length - 1 || payments.length > 0) && (
                      <div className="flow-arrow">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                          <path
                            d="M5 12H19M19 12L13 6M19 12L13 18"
                            stroke="#94A3B8"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </div>
                    )}
                  </React.Fragment>
                );
              })}
            </div>

            {/* Downstream Vendor Payments Branch */}
            {payments.length > 0 && (
              <div className="flow-payments-section">
                <div className="payments-branch-label micro-label">
                  DOWNSTREAM DISBURSEMENTS ({payments.length})
                </div>
                <div className="payments-grid">
                  {payments.map((evt) => {
                    const isSelected = evt.event_id === selectedEventId;
                    const meta = evt.metadata || {};

                    return (
                      <div
                        id={`node-${evt.event_id}`}
                        key={evt.event_id}
                        className={`flow-node node-payment ${isSelected ? 'node-selected' : ''}`}
                        onClick={() => setSelectedEventId(evt.event_id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            setSelectedEventId(evt.event_id);
                          }
                        }}
                      >
                        <div className="node-header">
                          <span className="node-type font-mono">VENDOR_PAYMENT</span>
                          <span className="badge badge-verified">CLAIMED</span>
                        </div>
                        <div className="node-id font-mono">{evt.event_id}</div>
                        <div className="node-amounts font-mono">
                          <div className="node-amt">
                            PAID: {formatNodeAmount(evt.output_asset, evt.output_amount)}
                          </div>
                          {meta.vendor_id && (
                            <div className="node-meta">Vendor: {meta.vendor_id}</div>
                          )}
                          {meta.claim_id && (
                            <div className="node-meta">Claim: {meta.claim_id}</div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Selected Event Details Panel */}
      {selectedEvent && (
        <EventInspector
          event={selectedEvent}
          onClose={() => setSelectedEventId(null)}
        />
      )}
    </div>
  );
}
