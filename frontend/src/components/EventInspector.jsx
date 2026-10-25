import React from 'react';
import { formatWeiToEth, formatCentsToUsd } from '../utils/formatters';

/**
 * Formats asset amount based on asset denomination.
 */
function formatAssetAmount(asset, amountStr) {
  if (!asset || amountStr == null) return `${amountStr || '0'}`;
  if (asset === 'ETH') {
    return `${formatWeiToEth(amountStr)} ETH (${amountStr} wei)`;
  }
  if (asset === 'USDC') {
    const units = Number(amountStr) / 1000000;
    return `${units.toLocaleString('en-US', { minimumFractionDigits: 2 })} USDC`;
  }
  if (asset === 'USD_CENTS') {
    return `${formatCentsToUsd(Number(amountStr))} (${amountStr} cents)`;
  }
  return `${amountStr} ${asset}`;
}

/**
 * EventInspector Component
 * Detailed inspector for the selected trace graph event.
 */
export function EventInspector({ event, onClose }) {
  if (!event) return null;

  const isSimulated = Boolean(event.is_simulated);
  const meta = event.metadata || {};

  return (
    <div className="event-inspector">
      <div className="inspector-header">
        <div>
          <span className="micro-label">EVENT INSPECTOR</span>
          <h3 className="inspector-title font-mono">{event.event_id}</h3>
        </div>
        <div className="inspector-actions">
          <span className={`badge ${isSimulated ? 'badge-neutral' : 'badge-verified'}`}>
            {isSimulated ? 'SIMULATED EXECUTION' : 'REAL SETTLEMENT'}
          </span>
          <button id="inspector-close-btn" className="inspector-close-btn" onClick={onClose} title="Close Inspector">
            ✕
          </button>
        </div>
      </div>

      <div className="inspector-grid">
        <div className="inspector-row">
          <span className="inspector-label">Event Type</span>
          <span className="inspector-value font-mono"><strong>{event.event_type}</strong></span>
        </div>

        <div className="inspector-row">
          <span className="inspector-label">Project ID</span>
          <span className="inspector-value font-mono">{event.project_id}</span>
        </div>

        <div className="inspector-row">
          <span className="inspector-label">Parent Event</span>
          <span className="inspector-value font-mono">{event.parent_event_id || 'None (Genesis Event)'}</span>
        </div>

        <div className="inspector-row">
          <span className="inspector-label">Input</span>
          <span className="inspector-value font-mono">{formatAssetAmount(event.input_asset, event.input_amount)}</span>
        </div>

        <div className="inspector-row">
          <span className="inspector-label">Output</span>
          <span className="inspector-value font-mono">{formatAssetAmount(event.output_asset, event.output_amount)}</span>
        </div>

        {event.conversion_rate_basis != null && (
          <div className="inspector-row">
            <span className="inspector-label">Conversion Rate Basis</span>
            <span className="inspector-value font-mono">{event.conversion_rate_basis}</span>
          </div>
        )}

        {meta.claim_id && (
          <div className="inspector-row">
            <span className="inspector-label">Linked Claim ID</span>
            <span className="inspector-value font-mono badge-verified">{meta.claim_id}</span>
          </div>
        )}

        {meta.vendor_id && (
          <div className="inspector-row">
            <span className="inspector-label">Vendor ID</span>
            <span className="inspector-value font-mono">{meta.vendor_id}</span>
          </div>
        )}

        {meta.invoice_id && (
          <div className="inspector-row">
            <span className="inspector-label">Invoice ID</span>
            <span className="inspector-value font-mono">{meta.invoice_id}</span>
          </div>
        )}

        {event.attestation && (
          <div className="inspector-row">
            <span className="inspector-label">Attestation</span>
            <span className="inspector-value font-mono">{event.attestation}</span>
          </div>
        )}

        <div className="inspector-row">
          <span className="inspector-label">Recorded At</span>
          <span className="inspector-value font-mono">
            {event.created_at ? new Date(event.created_at * 1000).toISOString() : 'N/A'}
          </span>
        </div>
      </div>
    </div>
  );
}
