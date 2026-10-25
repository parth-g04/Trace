import React from 'react';

/**
 * Institutional Operational Header Component
 *
 * Responsibilities:
 * - Wordmark & Project Identity
 * - Mode indicator & switcher: Simulation vs Local Blockchain
 * - API connectivity & local EVM node status
 * - Smart contract availability & address
 * - EVM Wallet connection state: Connected, Disconnected, Wrong Network
 * - Operational controls: Refresh & Reset Demo
 */
export function Header({
  project,
  health,
  chainStatus,
  mode,
  onToggleMode,
  wallet,
  isRefreshing,
  onRefresh,
  onResetDemo,
}) {
  const isHealthy = health?.status === 'healthy';
  const isFrozen = project?.is_frozen;

  const isChainConnected = chainStatus?.connected;
  const isContractDeployed = chainStatus?.contract_deployed;
  const contractAddress = chainStatus?.contract_address;

  const truncatedContract = contractAddress
    ? `${contractAddress.slice(0, 6)}...${contractAddress.slice(-4)}`
    : null;

  return (
    <header className="trace-header">
      <div className="header-brand-group">
        <div className="brand-mark">
          <span className="brand-dot" />
          <h1 className="brand-title">TRACE</h1>
        </div>
        <span className="brand-divider">/</span>
        <span className="brand-subtitle">THE BLACK HOLE LEDGER</span>
      </div>

      <div className="header-meta-group">
        {/* Execution Mode Switcher */}
        <div className="meta-control">
          <span className="meta-label">EXECUTION MODE</span>
          <div className="mode-toggle-group">
            <button
              id="mode-sim-btn"
              type="button"
              className={`mode-btn ${mode === 'simulation' ? 'mode-btn-active' : ''}`}
              onClick={() => onToggleMode('simulation')}
              title="Deterministic Python simulation mode"
            >
              SIMULATION
            </button>
            <button
              id="mode-chain-btn"
              type="button"
              className={`mode-btn ${mode === 'local_chain' ? 'mode-btn-active' : ''}`}
              onClick={() => onToggleMode('local_chain')}
              title="Real local Hardhat EVM contract transactions"
            >
              LOCAL CHAIN
            </button>
          </div>
        </div>

        {/* API Status */}
        <div className="meta-badge-item" title={isHealthy ? 'FastAPI backend connected' : 'FastAPI offline'}>
          <span className={`status-dot ${isHealthy ? 'dot-online' : 'dot-offline'}`} />
          <span className="status-text">{isHealthy ? 'API ONLINE' : 'API OFFLINE'}</span>
        </div>

        {/* Local Chain Node & Contract Status */}
        <div
          className="meta-badge-item font-mono"
          title={
            isChainConnected
              ? `Hardhat Node Block #${chainStatus?.block_number || 0}`
              : 'Local Hardhat RPC unreachable at http://127.0.0.1:8545'
          }
        >
          <span className={`status-dot ${isChainConnected ? 'dot-online' : 'dot-offline'}`} />
          <span className="status-text">
            {isChainConnected ? 'RPC:31337' : 'RPC OFFLINE'}
          </span>
          {isContractDeployed && truncatedContract && (
            <span className="contract-chip" title={`Deployed at ${contractAddress}`}>
              {truncatedContract}
            </span>
          )}
        </div>

        {/* EVM Wallet Connection Bar */}
        <div className="wallet-header-widget">
          {wallet.isWrongNetwork ? (
            <button
              id="wallet-switch-btn"
              type="button"
              className="btn-wallet-warning"
              onClick={wallet.switchNetwork}
              title="Switch to Hardhat Local Network (Chain 31337)"
            >
              SWITCH TO HARDHAT (31337)
            </button>
          ) : wallet.isConnected ? (
            <div className="wallet-connected-badge font-mono">
              <span className="status-dot dot-online" />
              <span className="wallet-addr">{wallet.truncatedAddress}</span>
              <button
                id="wallet-disconnect-btn"
                type="button"
                className="btn-wallet-disconnect"
                onClick={wallet.disconnectWallet}
                title="Disconnect wallet"
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              id="wallet-connect-btn"
              type="button"
              className="btn-wallet-connect"
              onClick={wallet.connectWallet}
              disabled={wallet.isConnecting}
              title={wallet.hasInjectedProvider ? 'Connect MetaMask/EVM wallet' : 'No wallet extension detected'}
            >
              {wallet.isConnecting ? 'CONNECTING...' : 'CONNECT WALLET'}
            </button>
          )}
        </div>

        {/* Project Frozen Alert Pill */}
        {project && isFrozen && (
          <span
            className="badge badge-danger font-mono"
            title={`Escrow frozen due to security violation: ${project.freeze_reason || 'Cryptographic rejection'}`}
          >
            ESCROW FROZEN
          </span>
        )}

        {/* Operational Actions */}
        <div className="header-actions">
          <button
            id="refresh-btn"
            type="button"
            className="btn-header-secondary"
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh state from backend & blockchain"
          >
            {isRefreshing ? 'REFRESHING...' : 'REFRESH'}
          </button>
          <button
            id="reset-demo-header-btn"
            type="button"
            className="btn-header-danger"
            onClick={onResetDemo}
            title="Reset demo state to deterministic seed"
          >
            RESET
          </button>
        </div>
      </div>
    </header>
  );
}
