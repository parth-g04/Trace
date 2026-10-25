import React, { useState, useEffect, useCallback } from 'react';
import { api } from './api/client';
import { Header } from './components/Header';
import { MetricCards } from './components/MetricCards';
import { TrancheControl } from './components/TrancheControl';
import { FundFlowGraph } from './components/FundFlowGraph';
import { ClaimsPanel } from './components/ClaimsPanel';
import { ScenarioConsole } from './components/ScenarioConsole';
import { AuditTimeline } from './components/AuditTimeline';
import { useWallet } from './utils/useWallet';
import contractArtifact from './contracts/TraceEscrow.json';
import './App.css';

const DEFAULT_PROJECT_ID = 'WATER-001';

export default function App() {
  const [health, setHealth] = useState(null);
  const [project, setProject] = useState(null);
  const [trace, setTrace] = useState(null);
  const [claims, setClaims] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [scenarios, setScenarios] = useState([]);

  // Blockchain and mode state
  const [mode, setMode] = useState('simulation'); // 'simulation' | 'local_chain'
  const [chainStatus, setChainStatus] = useState(null);
  const [chainState, setChainState] = useState(null);

  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [connectionError, setConnectionError] = useState(null);
  const [isActionInProgress, setIsActionInProgress] = useState(false);

  // Injected EVM Wallet hook
  const wallet = useWallet();

  // Load all dashboard data atomically on user action or refresh
  const fetchDashboardData = useCallback(async (isManualRefresh = false) => {
    if (isManualRefresh) setIsRefreshing(true);
    setConnectionError(null);

    try {
      const [healthData, chainStatusData] = await Promise.all([
        api.health(),
        api.getChainStatus().catch(() => null),
      ]);

      setHealth(healthData);
      if (chainStatusData) {
        setChainStatus(chainStatusData);
        if (chainStatusData.mode) {
          setMode(chainStatusData.mode);
        }
      }

      const [projData, traceData, claimsData, auditData, metricsData, scenariosData, onChainData] =
        await Promise.all([
          api.getProject(DEFAULT_PROJECT_ID),
          api.getProjectTrace(DEFAULT_PROJECT_ID),
          api.getClaims(DEFAULT_PROJECT_ID),
          api.getAuditTrail(DEFAULT_PROJECT_ID, 50),
          api.getMetrics(),
          api.getScenarios(),
          chainStatusData?.connected && chainStatusData?.contract_deployed
            ? api.getChainState().catch(() => null)
            : Promise.resolve(null),
        ]);

      setProject(projData);
      setTrace(traceData);
      setClaims(claimsData);
      setAuditEvents(auditData);
      setMetrics(metricsData);
      setScenarios(scenariosData);
      if (onChainData) {
        setChainState(onChainData);
      }
    } catch (err) {
      console.error('[TRACE Frontend] Failed to fetch dashboard data:', err);
      setConnectionError(err.message || 'Unable to connect to TRACE backend.');
      setHealth(null);
    } finally {
      setLoading(false);
      if (isManualRefresh) setIsRefreshing(false);
    }
  }, []);

  // Initial fetch on mount
  useEffect(() => {
    let ignore = false;
    async function initLoad() {
      try {
        const [healthData, chainStatusData] = await Promise.all([
          api.health(),
          api.getChainStatus().catch(() => null),
        ]);

        if (ignore) return;
        setHealth(healthData);
        if (chainStatusData) {
          setChainStatus(chainStatusData);
          if (chainStatusData.mode) {
            setMode(chainStatusData.mode);
          }
        }

        const [projData, traceData, claimsData, auditData, metricsData, scenariosData, onChainData] =
          await Promise.all([
            api.getProject(DEFAULT_PROJECT_ID),
            api.getProjectTrace(DEFAULT_PROJECT_ID),
            api.getClaims(DEFAULT_PROJECT_ID),
            api.getAuditTrail(DEFAULT_PROJECT_ID, 50),
            api.getMetrics(),
            api.getScenarios(),
            chainStatusData?.connected && chainStatusData?.contract_deployed
              ? api.getChainState().catch(() => null)
              : Promise.resolve(null),
          ]);

        if (ignore) return;
        setProject(projData);
        setTrace(traceData);
        setClaims(claimsData);
        setAuditEvents(auditData);
        setMetrics(metricsData);
        setScenarios(scenariosData);
        if (onChainData) {
          setChainState(onChainData);
        }
      } catch (err) {
        if (ignore) return;
        console.error('[TRACE Frontend] Failed to initialize dashboard:', err);
        setConnectionError(err.message || 'Unable to connect to TRACE backend.');
        setHealth(null);
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    initLoad();
    return () => {
      ignore = true;
    };
  }, []);

  // Handle switching execution mode
  const handleToggleMode = async (newMode) => {
    setIsActionInProgress(true);
    try {
      await api.setChainMode(newMode);
      setMode(newMode);
      await fetchDashboardData();
    } catch (err) {
      console.error('[TRACE Frontend] Failed to toggle mode:', err);
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Handle tranche release attempt in simulation mode
  const handleReleaseAttempt = async (projectId) => {
    setIsActionInProgress(true);
    try {
      const res = await api.releaseTranche(projectId);
      await fetchDashboardData();
      return res;
    } catch (err) {
      await fetchDashboardData();
      throw err;
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Handle on-chain release attempt via backend Web3 adapter
  const handleChainReleaseAttempt = async () => {
    setIsActionInProgress(true);
    try {
      const res = await api.releaseChain();
      await fetchDashboardData();
      return res;
    } catch (err) {
      await fetchDashboardData();
      throw err;
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Handle scenario execution
  const handleRunScenario = async (scenarioName) => {
    setIsActionInProgress(true);
    try {
      const res = await api.runScenario(scenarioName);
      await fetchDashboardData();
      return res;
    } catch (err) {
      await fetchDashboardData();
      throw err;
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Handle demo state reset
  const handleResetDemo = async () => {
    setIsActionInProgress(true);
    try {
      const res = await api.resetDemo();
      await fetchDashboardData();
      return res;
    } catch (err) {
      await fetchDashboardData();
      throw err;
    } finally {
      setIsActionInProgress(false);
    }
  };

  const discrepanciesCount = trace?.discrepancies?.length || 0;

  return (
    <div className="trace-app">
      {/* Persistent Operational Header */}
      <Header
        project={project}
        health={health}
        chainStatus={chainStatus}
        mode={mode}
        onToggleMode={handleToggleMode}
        wallet={wallet}
        isRefreshing={isRefreshing}
        onRefresh={() => fetchDashboardData(true)}
        onResetDemo={handleResetDemo}
      />

      {/* Main Scrollable Workspace */}
      <main className="trace-main">
        <div className="trace-container">
          {/* Connection Error Banner */}
          {connectionError && (
            <div className="connection-error-banner" role="alert">
              <div className="error-title">
                <span className="badge badge-danger">SYSTEM ERROR</span>
                <strong>API Unreachable:</strong> {connectionError}
              </div>
              <button
                type="button"
                className="btn-retry"
                onClick={() => fetchDashboardData(true)}
                disabled={isRefreshing}
              >
                {isRefreshing ? 'RETRIEVING...' : 'RETRY CONNECTION'}
              </button>
            </div>
          )}

          {/* Project Identity Headline */}
          <div className="project-title-bar">
            <div>
              <span className="micro-label">PROJECT IDENTITY & GOVERNANCE</span>
              <h2 className="project-display-name">
                {project ? `${project.name} (${project.id})` : 'Clean Water Initiative Kenya (WATER-001)'}
              </h2>
              <div className="project-purpose font-mono">
                PURPOSE: {project?.purpose || 'WATER_INFRASTRUCTURE'} · GOVERNANCE: SPEND-GATED TRANCHE ESCROW
              </div>
            </div>
            {project?.is_frozen && (
              <div className="freeze-alert-pill" role="alert">
                <span className="freeze-icon">⚠️</span>
                <span>ESCROW FROZEN: {project.freeze_reason || 'SECURITY VIOLATION DETECTED'}</span>
              </div>
            )}
          </div>

          {/* 6 Principal Summary Metric Cards */}
          <MetricCards
            project={project}
            traceSummary={trace?.summary}
            chainState={chainState}
            mode={mode}
            metrics={metrics}
            discrepanciesCount={discrepanciesCount}
            loading={loading}
          />

          {/* Tranche & Disbursement Controller */}
          <TrancheControl
            project={project}
            chainState={chainState}
            mode={mode}
            chainStatus={chainStatus}
            wallet={wallet}
            contractAddress={contractArtifact?.address}
            contractAbi={contractArtifact?.abi}
            onReleaseAttempt={handleReleaseAttempt}
            onChainReleaseAttempt={handleChainReleaseAttempt}
          />

          {/* End-to-End Asset Conservation Graph */}
          <FundFlowGraph
            trace={trace}
            loading={loading}
          />

          {/* Claims & Evidence Ledger Panel */}
          <ClaimsPanel
            claims={claims}
            loading={loading}
          />

          {/* Scenario Console for Hackathon Evaluation */}
          <ScenarioConsole
            scenarios={scenarios}
            project={project}
            onRunScenario={handleRunScenario}
            onResetDemo={handleResetDemo}
            isRunning={isActionInProgress}
          />

          {/* Audit Timeline & Security Metrics */}
          <AuditTimeline
            auditEvents={auditEvents}
            metrics={metrics}
            loading={loading}
          />
        </div>
      </main>

      {/* Footer */}
      <footer className="trace-footer">
        <div className="footer-content">
          <span>TRACE / The Black Hole Ledger · Problem Statement 4.2 · CASCADE '26</span>
          <span className="font-mono">INTEGRITY ENGINE: SOLIDITY ESCROW + EIP-712 + SHA-256 NULLIFIERS</span>
        </div>
      </footer>
    </div>
  );
}
