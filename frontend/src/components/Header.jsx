import React from 'react';

/**
 * Operational Header Component
 * Displays TRACE branding, project identity, active/frozen state, simulation environment, and connectivity.
 */
export function Header({ project, health, isRefreshing, onRefresh }) {
  const isHealthy = health?.status === 'healthy';
  const isFrozen = project?.is_frozen;

  return (
    <header className="trace-header">
      <div className="header-brand">
        <div className="brand-mark">
          <span className="brand-dot" />
          <h1 className="brand-title">TRACE</h1>
        </div>
        <span className="brand-divider">/</span>
        <span className="brand-subtitle">THE BLACK HOLE LEDGER</span>
      </div>

      <div className="header-meta">
        {/* Environment Badge */}
        <div className="meta-item">
          <span className="badge badge-neutral">
            LOCAL DEMO · SIMULATION
          </span>
        </div>

        {/* Connectivity Status */}
        <div className="meta-item">
          <span className={`badge ${isHealthy ? 'badge-verified' : 'badge-rejected'}`}>
            <span className={`status-indicator ${isHealthy ? 'status-online' : 'status-offline'}`} />
            {isHealthy ? 'API CONNECTED' : 'API DISCONNECTED'}
          </span>
        </div>

        {/* Project State Badge */}
        {project && (
          <div className="meta-item">
            <span
              className={`badge ${isFrozen ? 'badge-rejected' : 'badge-verified'}`}
              title={isFrozen ? `Frozen: ${project.freeze_reason || 'Security violation'}` : 'Project Active'}
            >
              {isFrozen ? 'PROJECT FROZEN' : 'PROJECT ACTIVE'}
            </span>
          </div>
        )}

        {/* Refresh Action */}
        <button
          id="refresh-btn"
          className="refresh-btn"
          onClick={onRefresh}
          disabled={isRefreshing}
          title="Refresh all project data from backend"
        >
          {isRefreshing ? 'REFRESHING...' : 'REFRESH'}
        </button>
      </div>
    </header>
  );
}
