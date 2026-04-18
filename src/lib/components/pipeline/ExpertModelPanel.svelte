<script>
  /**
   * Expert-only panel for ModelTrainingStep.
   * Shows: per-channel adstock details, MCMC diagnostics, convergence stats.
   * @component ExpertModelPanel
   */
  import { modelData } from '$lib/project-state.js';

  const diagnostics = $derived($modelData?.diagnostics);
  const channelParams = $derived($modelData?.channelParams);

  const paramRows = $derived.by(() => {
    if (!channelParams) return [];
    return Object.entries(channelParams).map(([name, p]) => ({
      name,
      alpha: /** @type {any} */ (p).alpha,
      gamma: /** @type {any} */ (p).gamma,
      beta: /** @type {any} */ (p).beta,
      roi: /** @type {any} */ (p).roi,
      roi_ci_lower: /** @type {any} */ (p).roi_ci_lower,
      roi_ci_upper: /** @type {any} */ (p).roi_ci_upper,
    }));
  });
</script>

<div class="expert-panel">
  {#if diagnostics}
    <div class="section-title">MCMC Диагностика</div>
    <div class="diag-grid">
      <div class="diag-item">
        <span class="diag-label">R-hat (max)</span>
        <span class="diag-value" class:good={diagnostics.r_hat <= 1.01} class:warn={diagnostics.r_hat > 1.01 && diagnostics.r_hat <= 1.05} class:bad={diagnostics.r_hat > 1.05}>
          {diagnostics.r_hat?.toFixed(4) ?? '—'}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">Дивергенции</span>
        <span class="diag-value" class:good={!diagnostics.divergences} class:warn={diagnostics.divergences > 0}>
          {diagnostics.divergences ?? 0}
        </span>
      </div>
      <div class="diag-item">
        <span class="diag-label">R²</span>
        <span class="diag-value">{diagnostics.r_squared?.toFixed(4) ?? '—'}</span>
      </div>
      <div class="diag-item">
        <span class="diag-label">MAPE</span>
        <span class="diag-value">{diagnostics.mape?.toFixed(2) ?? '—'}%</span>
      </div>
      <div class="diag-item">
        <span class="diag-label">MQS</span>
        <span class="diag-value">{diagnostics.mqs?.score?.toFixed(0) ?? '—'} ({diagnostics.mqs?.tier_label ?? ''})</span>
      </div>
    </div>
  {/if}

  {#if paramRows.length > 0}
    <div class="section-title">Параметры каналов (posterior means)</div>
    <div class="params-scroll">
      <table class="params-table">
        <thead>
          <tr>
            <th>Канал</th>
            <th title="Steepness (Hill function)">Alpha</th>
            <th title="Half-saturation point (raw)">Gamma</th>
            <th title="Channel coefficient">Beta</th>
            <th>ROI</th>
            <th>CI 95%</th>
          </tr>
        </thead>
        <tbody>
          {#each paramRows as row}
            <tr>
              <td>{row.name}</td>
              <td class="mono">{row.alpha?.toFixed(3) ?? '—'}</td>
              <td class="mono">{row.gamma?.toFixed(4) ?? '—'}</td>
              <td class="mono">{row.beta?.toFixed(4) ?? '—'}</td>
              <td class="mono" class:good={row.roi > 2} class:warn={row.roi < 1}>{row.roi?.toFixed(2) ?? '—'}x</td>
              <td class="mono ci">[{row.roi_ci_lower?.toFixed(2) ?? '?'}, {row.roi_ci_upper?.toFixed(2) ?? '?'}]</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .expert-panel {
    display: flex; flex-direction: column; gap: 16px; margin-top: 24px;
    padding: 16px; border-radius: var(--radius-md, 10px);
    background: color-mix(in srgb, var(--danger) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger) 8%, transparent);
    position: relative;
  }
  .expert-panel::before {
    content: 'Экспертный режим';
    position: absolute;
    top: -8px;
    left: 12px;
    padding: 2px 8px;
    background: var(--bg-primary, #0C0C12);
    color: var(--danger);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-radius: 4px;
  }
  .section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(252,165,165,0.85); }

  .diag-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  .diag-item {
    display: flex; flex-direction: column; gap: 2px;
    padding: 8px 10px; border-radius: 6px;
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.04);
  }
  .diag-label { font-size: 10px; color: var(--text-secondary, #94a3b8); }
  .diag-value { font-size: 14px; font-weight: 600; font-family: monospace; color: var(--text-primary, #e2e8f0); }
  .diag-value.good { color: #22c55e; }
  .diag-value.warn { color: #f59e0b; }
  .diag-value.bad { color: #ef4444; }

  .params-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th { text-align: left; padding: 6px 8px; color: var(--text-secondary, #94a3b8); border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
  td { padding: 5px 8px; color: var(--text-primary, #e2e8f0); border-bottom: 1px solid rgba(255,255,255,0.03); }
  .mono { font-family: monospace; }
  .good { color: #22c55e; }
  .warn { color: #f59e0b; }
  .ci { color: var(--text-muted); font-size: 10px; }
</style>
