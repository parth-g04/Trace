import React, { useState } from 'react';

export function ScenarioConsole({
  scenarios,
  onRunScenario,
  onResetDemo,
  isRunning,
}) {
  const [runningScenario, setRunningScenario] = useState(null);
  const [lastScenarioResult, setLastScenarioResult] = useState(null);
  const [showResetModal, setShowResetModal] = useState(false);
  const [resetting, setResetting] = useState(false);

  const scenarioList = scenarios || [];

  const handleRun = async (name) => {
    setRunningScenario(name);
    setLastScenarioResult(null);
    try {
      const res = await onRunScenario(name);
      setLastScenarioResult({ success: res.status === 'VERIFIED', data: res });
    } catch (err) {
      setLastScenarioResult({
        success: false,
        data: err.data || { reason: 'API_ERROR', explanation: err.message, status: 'ERROR' },
      });
    } finally {
      setRunningScenario(null);
    }
  };

  const handleConfirmReset = async () => {
    setResetting(true);
    try {
      await onResetDemo();
      setLastScenarioResult({
        success: true,
        data: {
          scenario: 'DEMO_RESET',
          title: 'Database Reset',
          status: 'RESET_OK',
          explanation: 'Database restored to initial deterministic seed state.',
        },
      });
    } catch (err) {
      setLastScenarioResult({
        success: false,
        data: {
          scenario: 'DEMO_RESET',
          title: 'Reset Failed',
          status: 'ERROR',
          explanation: err.message,
        },
      });
    } finally {
      setResetting(false);
      setShowResetModal(false);
    }
  };

  return (
    <div className="panel scenario-console-panel">
      <div className="panel-header">
        <div>
          <span className="micro-label">HACKATHON EVALUATION SUITE</span>
          <h2 className="panel-title">Demo Scenario Controller</h2>
        </div>
        <div className="panel-actions">
          <button
            id="reset-demo-btn"
            className="btn-danger reset-btn"
            onClick={() => setShowResetModal(true)}
            disabled={isRunning || resetting}
          >
            {resetting ? 'RESETTING...' : 'RESET DEMO STATE'}
          </button>
        </div>
      </div>

      <div className="scenario-instructions">
        <p>
          Execute live scenarios to verify cryptographic defenses. Security attacks immediately reject disbursements and trigger project-level escrow freezes.
        </p>
      </div>

      {/* Scenario Grid */}
      <div className="scenario-grid">
        {scenarioList.map((s) => {
          const isAttack = s.category === 'ATTACK';
          const isPolicy = s.category === 'POLICY_CHECK';
          const isRunningThis = runningScenario === s.name;

          return (
            <div
              key={s.name}
              className={`scenario-card ${isAttack ? 'card-attack' : isPolicy ? 'card-policy' : 'card-benign'}`}
            >
              <div className="scenario-card-top">
                <span
                  className={`badge ${
                    isAttack ? 'badge-rejected' : isPolicy ? 'badge-warning' : 'badge-verified'
                  }`}
                >
                  {s.category}
                </span>
                <span className="micro-label font-mono">
                  EXPECTED: {s.expected_status}
                </span>
              </div>

              <h3 className="scenario-title">{s.title}</h3>
              <p className="scenario-desc">{s.description}</p>

              <button
                id={`scenario-run-${s.name}`}
                className={`scenario-run-btn ${isAttack ? 'btn-run-attack' : 'btn-run-normal'}`}
                onClick={() => handleRun(s.name)}
                disabled={isRunning || runningScenario !== null}
              >
                {isRunningThis ? 'EXECUTING SCENARIO...' : 'EXECUTE SCENARIO'}
              </button>
            </div>
          );
        })}
      </div>

      {/* Last Scenario Execution Result Box */}
      {lastScenarioResult && (
        <div
          className={`scenario-result-box ${
            lastScenarioResult.success ? 'result-box-verified' : 'result-box-rejected'
          }`}
        >
          <div className="result-box-header">
            <div>
              <span className="micro-label">LATEST EXECUTION RESULT</span>
              <h3 className="result-title font-mono">{lastScenarioResult.data.title || lastScenarioResult.data.scenario}</h3>
            </div>
            <div className="result-status-badges">
              <span
                className={`badge ${
                  lastScenarioResult.data.status === 'VERIFIED'
                    ? 'badge-verified'
                    : lastScenarioResult.data.status === 'RESET_OK'
                    ? 'badge-info'
                    : 'badge-rejected'
                }`}
              >
                STATUS: {lastScenarioResult.data.status}
              </span>
              {lastScenarioResult.data.project_status && (
                <span
                  className={`badge ${
                    lastScenarioResult.data.project_status === 'ACTIVE'
                      ? 'badge-verified'
                      : 'badge-rejected'
                  }`}
                >
                  PROJECT: {lastScenarioResult.data.project_status}
                </span>
              )}
            </div>
          </div>

          {lastScenarioResult.data.reason && (
            <div className="result-reason-row font-mono">
              <strong>REJECTION REASON:</strong> {lastScenarioResult.data.reason}
            </div>
          )}

          <div className="result-explanation-text">
            {lastScenarioResult.data.explanation}
          </div>

          {/* Verification Checks Matrix if returned */}
          {lastScenarioResult.data.checks && (
            <div className="result-checks-matrix">
              <div className="micro-label">CRYPTOGRAPHIC CHECKS BREAKDOWN</div>
              <div className="checks-chips-grid font-mono">
                {Object.entries(lastScenarioResult.data.checks).map(([checkKey, pass]) => (
                  <div
                    key={checkKey}
                    className={`check-chip ${pass ? 'chip-pass' : 'chip-fail'}`}
                  >
                    <span className="chip-icon">{pass ? '✓' : '✗'}</span>
                    <span className="chip-name">{checkKey}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="modal-header">
              <span className="micro-label text-rejected">DESTRUCTIVE OPERATION</span>
              <h3>Confirm Demo State Reset</h3>
            </div>
            <p className="modal-body">
              This action will reset project <strong>WATER-001</strong> and the Black Hole Ledger to the initial deterministic seed state:
              <br /><br />
              • Current Tranche will return to 0 (0 ETH released).
              • All registered expenditure claims will be purged.
              • Flow events will reset to the initial 50 ETH donation.
              • Freeze status will be cleared.
            </p>
            <div className="modal-actions">
              <button
                id="cancel-reset-btn"
                className="btn-neutral"
                onClick={() => setShowResetModal(false)}
                disabled={resetting}
              >
                CANCEL
              </button>
              <button
                id="confirm-reset-btn"
                className="btn-danger-confirm"
                onClick={handleConfirmReset}
                disabled={resetting}
              >
                {resetting ? 'RESETTING...' : 'CONFIRM RESET'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
