import React, { useState } from 'react';

export function AuditTimeline({ auditEvents, metrics, loading }) {
  const [expandedEventId, setExpandedEventId] = useState(null);

  if (loading && !auditEvents) {
    return (
      <div className="panel audit-panel">
        <div className="panel-header">
          <span className="micro-label">SYSTEM INTEGRITY & EVENT LOG</span>
        </div>
        <div className="audit-empty">Loading audit trail and security metrics...</div>
      </div>
    );
  }

  const events = auditEvents || [];
  const m = metrics || {
    valid_claims: 0,
    rejected_claims: 0,
    forged_attempts_detected: 0,
    duplicate_invoice_attempts_blocked: 0,
    release_attempts_blocked: 0,
    frozen_projects: 0,
    unexplained_trace_discrepancies: 0,
  };

  return (
    <div className="panel audit-panel">
      <div className="panel-header">
        <div>
          <span className="micro-label">SYSTEM INTEGRITY & EVENT LOG</span>
          <h2 className="panel-title">Audit Trail & Security Metrics</h2>
        </div>
        <div className="panel-actions">
          <span className="badge badge-neutral">
            {events.length} AUDIT ENTRIES
          </span>
        </div>
      </div>

      {/* Security Metrics Counter Grid */}
      <div className="metrics-summary-grid">
        <div className="metric-stat-box">
          <span className="micro-label">VALID CLAIMS</span>
          <span className="stat-number font-mono text-verified">{m.valid_claims}</span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">REJECTED CLAIMS</span>
          <span className="stat-number font-mono text-rejected">{m.rejected_claims}</span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">FORGERIES BLOCKED</span>
          <span className="stat-number font-mono text-rejected">{m.forged_attempts_detected}</span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">DUPLICATE INVOICES</span>
          <span className="stat-number font-mono text-rejected">{m.duplicate_invoice_attempts_blocked}</span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">RELEASES BLOCKED</span>
          <span className="stat-number font-mono text-warning">{m.release_attempts_blocked}</span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">FROZEN PROJECTS</span>
          <span className={`stat-number font-mono ${m.frozen_projects > 0 ? 'text-rejected' : ''}`}>
            {m.frozen_projects}
          </span>
        </div>
        <div className="metric-stat-box">
          <span className="micro-label">UNEXPLAINED DISCREPANCIES</span>
          <span className={`stat-number font-mono ${m.unexplained_trace_discrepancies > 0 ? 'text-rejected' : 'text-verified'}`}>
            {m.unexplained_trace_discrepancies}
          </span>
        </div>
      </div>

      {/* Audit Log Table */}
      {events.length === 0 ? (
        <div className="audit-empty">No audit events recorded yet.</div>
      ) : (
        <div className="audit-table-wrapper">
          <table className="audit-table font-mono">
            <thead>
              <tr>
                <th>TIMESTAMP</th>
                <th>SEVERITY</th>
                <th>EVENT TYPE</th>
                <th>REASON CODE</th>
                <th>DETAILS</th>
              </tr>
            </thead>
            <tbody>
              {events.map((evt) => {
                const isCritical = evt.severity === 'CRITICAL';
                const isWarning = evt.severity === 'WARNING';
                const isExpanded = expandedEventId === evt.event_id;

                return (
                  <React.Fragment key={evt.event_id}>
                    <tr className={`audit-row ${isExpanded ? 'row-expanded' : ''}`}>
                      <td className="cell-time">
                        {evt.created_at ? new Date(evt.created_at * 1000).toLocaleTimeString() : 'N/A'}
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            isCritical ? 'badge-rejected' : isWarning ? 'badge-warning' : 'badge-neutral'
                          }`}
                        >
                          {evt.severity}
                        </span>
                      </td>
                      <td>
                        <strong>{evt.event_type}</strong>
                      </td>
                      <td>
                        {evt.reason_code ? (
                          <span className="badge badge-neutral">{evt.reason_code}</span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        {evt.details && Object.keys(evt.details).length > 0 ? (
                          <button
                            className="btn-sm"
                            onClick={() => setExpandedEventId(isExpanded ? null : evt.event_id)}
                          >
                            {isExpanded ? 'HIDE' : 'VIEW'}
                          </button>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>

                    {isExpanded && evt.details && (
                      <tr className="audit-detail-row">
                        <td colSpan={5}>
                          <pre className="audit-details-json">
                            {JSON.stringify(evt.details, null, 2)}
                          </pre>
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
