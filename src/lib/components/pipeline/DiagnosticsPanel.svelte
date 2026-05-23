<script>
  /**
   * DiagnosticsPanel - v2.0.0 Phase C diagnostic summary.
   *
   * Manager view (default): 4 traffic-light rows with CSS dot indicators
   * (accessibility per audit M2 - no emoji for status).
   * Expert expand: trace plots placeholder + ESS per-parameter table +
   * PPCScatter sub-component.
   *
   * Per WIZARD_FLOW_v2_FINAL.md §3.2 + §6.
   *
   * @component DiagnosticsPanel
   */
  import { ChevronDown, TrendingUp, Info } from 'lucide-svelte';
  import { expertMode } from '$lib/project-state.js';
  import PPCScatter from './PPCScatter.svelte';

  /**
   * @type {{
   *   diagnostics: {
   *     mcmcConvergence?: { r_hat?: number, ess?: number, per_param_rhat?: Record<string, number>, per_param_ess?: Record<string, number> } | null,
   *     backtest?: { mape?: number, r2?: number } | null,
   *     ppc?: { r2?: number, durbin_watson?: number, actual?: number[], predicted?: number[], residuals?: number[] } | null,
   *     sensitivity?: { param_label?: string, sensitivity_pct?: number } | null,
   *   } | null,
   *   expandable?: boolean,
   * }}
   */
  const { diagnostics = null, expandable = true } = $props();

  /** Whether expert section is open */
  let expertOpen = $state(false);

  // ── Thresholds ──────────────────────────────────────────────────────────────

  /**
   * Compute MCMC convergence status from r_hat + ess.
   * @param {number | undefined} rhat
   * @param {number | undefined} ess
   * @returns {'ok' | 'warn' | 'bad'}
   */
  function mcmcStatus(rhat, ess) {
    const r = rhat ?? 0;
    const e = ess ?? 0;
    if (r < 1.05 && e > 400) return 'ok';
    if (r <= 1.10 && e >= 200) return 'warn';
    return 'bad';
  }

  /**
   * Compute backtest status from MAPE.
   * @param {number | undefined} mape
   * @returns {'ok' | 'warn' | 'bad'}
   */
  function backtestStatus(mape) {
    const m = mape ?? 100;
    if (m < 10) return 'ok';
    if (m <= 20) return 'warn';
    return 'bad';
  }

  /**
   * Compute PPC status from r2.
   * @param {number | undefined} r2
   * @returns {'ok' | 'warn' | 'bad'}
   */
  function ppcStatus(r2) {
    const v = r2 ?? 0;
    if (v > 0.85) return 'ok';
    if (v >= 0.70) return 'warn';
    return 'bad';
  }

  // ── Derived row data ─────────────────────────────────────────────────────────

  const mcmc = $derived.by(() => {
    const d = diagnostics?.mcmcConvergence;
    const rhat = d?.r_hat ?? undefined;
    const ess = d?.ess ?? undefined;
    return {
      status: mcmcStatus(rhat, ess),
      rhat: rhat != null ? Number(rhat).toFixed(4) : '-',
      ess: ess != null ? Math.round(ess) : '-',
    };
  });

  const backtest = $derived.by(() => {
    const d = diagnostics?.backtest;
    const mape = d?.mape ?? undefined;
    const r2 = d?.r2 ?? undefined;
    return {
      status: backtestStatus(mape),
      mape: mape != null ? Number(mape).toFixed(1) : '-',
      r2: r2 != null ? Number(r2).toFixed(3) : '-',
    };
  });

  const ppc = $derived.by(() => {
    const d = diagnostics?.ppc;
    const r2 = d?.r2 ?? undefined;
    const dw = d?.durbin_watson ?? undefined;
    return {
      status: ppcStatus(r2),
      r2: r2 != null ? Number(r2).toFixed(3) : '-',
      dw: dw != null ? Number(dw).toFixed(2) : '-',
    };
  });

  const sensitivity = $derived.by(() => {
    const d = diagnostics?.sensitivity;
    return {
      label: d?.param_label ?? 'Топ-параметр',
      pct: d?.sensitivity_pct != null ? Number(d.sensitivity_pct).toFixed(1) : '-',
    };
  });

  /** ESS per-parameter for expert table */
  const essParams = $derived.by(() => {
    const perEss = diagnostics?.mcmcConvergence?.per_param_ess ?? {};
    const perRhat = diagnostics?.mcmcConvergence?.per_param_rhat ?? {};
    return Object.keys(perEss).map(k => ({
      name: k,
      ess: Math.round(perEss[k]),
      rhat: Number(perRhat[k] ?? 0).toFixed(4),
      status: mcmcStatus(perRhat[k], perEss[k]),
    }));
  });

  /** PPC data for PPCScatter sub-component */
  const ppcData = $derived.by(() => {
    const d = diagnostics?.ppc;
    if (!d?.actual?.length || !d?.predicted?.length) return null;
    return {
      actual: d.actual,
      predicted: d.predicted,
      residuals: d.residuals ?? d.actual.map((a, i) => a - (d.predicted?.[i] ?? 0)),
      r2: d.r2 ?? 0,
      durbin_watson: d.durbin_watson ?? 0,
    };
  });

  /** Show expert expand button */
  const canExpand = $derived(expandable || $expertMode);

  /** Overall panel status: worst of 4 rows */
  const overallStatus = $derived.by(() => {
    const statuses = [mcmc.status, backtest.status, ppc.status];
    if (statuses.includes('bad')) return 'bad';
    if (statuses.includes('warn')) return 'warn';
    return 'ok';
  });
</script>

<div class="diag-panel" class:status-ok={overallStatus === 'ok'} class:status-warn={overallStatus === 'warn'} class:status-bad={overallStatus === 'bad'}>

  <header class="panel-header">
    <span class="header-icon"><TrendingUp size={16} strokeWidth={1.8} /></span>
    <h3 class="panel-title">Диагностика модели</h3>
    {#if canExpand}
      <button
        type="button"
        class="expand-btn"
        aria-expanded={expertOpen}
        aria-controls="diag-expert-section"
        onclick={() => (expertOpen = !expertOpen)}
      >
        <span class="expand-label">{expertOpen ? 'Свернуть' : 'Подробнее'}</span>
        <span class="chevron" class:open={expertOpen}><ChevronDown size={14} /></span>
      </button>
    {/if}
  </header>

  <!-- ── Manager view: 4 traffic-light rows ─────────────────────────────────── -->
  <div class="rows" role="list" aria-label="Показатели качества модели">

    <!-- Row 1: MCMC Convergence -->
    <div class="diag-row" role="listitem">
      <span class="tl-dot tl-{mcmc.status}" aria-label="Сходимость: {mcmc.status === 'ok' ? 'хорошо' : mcmc.status === 'warn' ? 'предупреждение' : 'ошибка'}"></span>
      <span class="row-label">Сходимость (MCMC)</span>
      <span class="row-values">
        <span class="metric-chip">R-hat {mcmc.rhat}</span>
        <span class="metric-chip">ESS {mcmc.ess}</span>
      </span>
      <span class="row-hint">
        {#if mcmc.status === 'ok'}Модель сошлась
        {:else if mcmc.status === 'warn'}Частичная сходимость
        {:else}Не сошлась - нужно больше итераций{/if}
      </span>
    </div>

    <!-- Row 2: Backtest -->
    <div class="diag-row" role="listitem">
      <span class="tl-dot tl-{backtest.status}" aria-label="Бэктест: {backtest.status === 'ok' ? 'хорошо' : backtest.status === 'warn' ? 'предупреждение' : 'ошибка'}"></span>
      <span class="row-label">Бэктест</span>
      <span class="row-values">
        <span class="metric-chip">MAPE {backtest.mape}%</span>
        <span class="metric-chip">R² {backtest.r2}</span>
      </span>
      <span class="row-hint">
        {#if backtest.status === 'ok'}Точность прогноза высокая
        {:else if backtest.status === 'warn'}Умеренная точность
        {:else}Ошибка прогноза высокая{/if}
      </span>
    </div>

    <!-- Row 3: Posterior Predictive Check -->
    <div class="diag-row" role="listitem">
      <span class="tl-dot tl-{ppc.status}" aria-label="Posterior predictive: {ppc.status === 'ok' ? 'хорошо' : ppc.status === 'warn' ? 'предупреждение' : 'ошибка'}"></span>
      <span class="row-label">Posterior predictive</span>
      <span class="row-values">
        <span class="metric-chip">R² {ppc.r2}</span>
        <span class="metric-chip">DW {ppc.dw}</span>
      </span>
      <span class="row-hint">
        {#if ppc.status === 'ok'}Остатки без паттернов
        {:else if ppc.status === 'warn'}Умеренное качество подгонки
        {:else}Систематическая ошибка{/if}
      </span>
    </div>

    <!-- Row 4: Sensitivity -->
    <div class="diag-row" role="listitem">
      <span class="tl-dot tl-ok" aria-label="Чувствительность: информация"></span>
      <span class="row-label">Чувствительность - {sensitivity.label}</span>
      <span class="row-values">
        <span class="metric-chip chip-info">±{sensitivity.pct}%</span>
      </span>
      <span class="row-hint">Влияние параметра на ROI</span>
    </div>
  </div>

  <!-- ── Expert expand section ─────────────────────────────────────────────── -->
  {#if expertOpen && canExpand}
    <div id="diag-expert-section" class="expert-section" role="region" aria-label="Детальная диагностика">

      <div class="expert-badge-row">
        <span class="expert-badge">EXPERT</span>
        <span class="expert-note"><Info size={12} /> Детальные метрики - только для аналитиков</span>
      </div>

      <!-- Trace plots placeholder -->
      <div class="trace-placeholder">
        <div class="trace-placeholder-inner">
          <TrendingUp size={24} strokeWidth={1} />
          <p>Trace plots доступны в v2.1.0</p>
          <span class="trace-note">MCMC chains визуализация + effective sample size per parameter</span>
        </div>
      </div>

      <!-- ESS per-parameter table -->
      {#if essParams.length > 0}
        <div class="ess-table-wrap">
          <h4 class="expert-section-title">ESS по параметрам</h4>
          <table class="ess-table" aria-label="Effective Sample Size по параметрам">
            <thead>
              <tr>
                <th scope="col">Параметр</th>
                <th scope="col">R-hat</th>
                <th scope="col">ESS</th>
                <th scope="col">Статус</th>
              </tr>
            </thead>
            <tbody>
              {#each essParams as row (row.name)}
                <tr>
                  <td class="param-name">{row.name}</td>
                  <td class="metric-val">{row.rhat}</td>
                  <td class="metric-val">{row.ess}</td>
                  <td><span class="tl-dot tl-{row.status}" style="display:inline-block"></span></td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <p class="no-data">Детальная статистика ESS недоступна</p>
      {/if}

      <!-- PPC Scatter sub-component -->
      {#if ppcData}
        <div class="ppc-scatter-wrap">
          <h4 class="expert-section-title">Posterior Predictive Check - детали</h4>
          <PPCScatter ppcData={ppcData} />
        </div>
      {/if}

    </div>
  {/if}

</div>

<style>
  /* ─── Panel shell ─────────────────────────────────────────────────────────── */
  .diag-panel {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    padding: 16px 18px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  /* Left-side hairline accent by overall status */
  .diag-panel.status-ok  { border-left: 3px solid var(--success,  #10B981); }
  .diag-panel.status-warn { border-left: 3px solid var(--warning, #F59E0B); }
  .diag-panel.status-bad { border-left: 3px solid var(--danger,  #EF4444); }

  /* ─── Header ─────────────────────────────────────────────────────────────── */
  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .header-icon {
    display: flex;
    align-items: center;
    color: var(--text-secondary);
    flex-shrink: 0;
  }
  .panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    flex: 1;
    letter-spacing: 0.01em;
  }
  .expand-btn {
    display: flex;
    align-items: center;
    gap: 4px;
    background: none;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 6px;
    color: var(--text-secondary);
    font: inherit;
    font-size: 11px;
    padding: 3px 8px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    flex-shrink: 0;
  }
  .expand-btn:hover {
    border-color: var(--accent-primary);
    color: var(--text-primary);
  }
  .expand-label { white-space: nowrap; }
  .chevron {
    display: flex;
    align-items: center;
    transition: transform 0.2s;
  }
  .chevron.open { transform: rotate(180deg); }

  /* ─── Rows ─────────────────────────────────────────────────────────────────── */
  .rows {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .diag-row {
    display: grid;
    grid-template-columns: 14px minmax(140px, 1fr) auto auto;
    align-items: center;
    gap: 8px 10px;
    padding: 7px 8px;
    background: color-mix(in srgb, var(--text-primary) 3%, transparent);
    border-radius: 6px;
    min-height: 32px;
  }

  @media (max-width: 600px) {
    .diag-row {
      grid-template-columns: 14px 1fr;
      grid-template-rows: auto auto;
    }
    .row-values { grid-column: 2; }
    .row-hint { grid-column: 1 / -1; padding-left: 22px; }
  }

  /* ─── Traffic-light CSS dots (accessibility: not emoji) ─────────────────── */
  .tl-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    display: block;
  }
  .tl-ok   { background: var(--success,  #10B981); box-shadow: 0 0 6px color-mix(in srgb, var(--success,  #10B981) 60%, transparent); }
  .tl-warn { background: var(--warning, #F59E0B); box-shadow: 0 0 6px color-mix(in srgb, var(--warning, #F59E0B) 60%, transparent); }
  .tl-bad  { background: var(--danger,  #EF4444); box-shadow: 0 0 6px color-mix(in srgb, var(--danger,  #EF4444) 60%, transparent); }

  .row-label {
    font-size: 12px;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .row-values {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .metric-chip {
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    padding: 2px 7px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    color: var(--text-secondary);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    white-space: nowrap;
  }

  .chip-info {
    background: color-mix(in srgb, var(--warning, #F59E0B) 10%, transparent);
    border-color: color-mix(in srgb, var(--warning, #F59E0B) 25%, transparent);
    color: var(--warning-text, #FBBF24);
  }

  .row-hint {
    font-size: 11px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    grid-column: 4;
  }

  /* ─── Expert section ──────────────────────────────────────────────────────── */
  .expert-section {
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    padding-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .expert-badge-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .expert-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 7px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 40%, transparent);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--warning, #F59E0B);
    flex-shrink: 0;
  }

  .expert-note {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--text-secondary);
  }

  /* ─── Trace placeholder ───────────────────────────────────────────────────── */
  .trace-placeholder {
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.1));
    border-radius: 8px;
    padding: 2px;
  }

  .trace-placeholder-inner {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 80px;
    padding: 16px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-radius: 6px;
    color: var(--text-secondary);
    text-align: center;
  }

  .trace-placeholder-inner p {
    margin: 0;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  .trace-note {
    font-size: 11px;
    color: color-mix(in srgb, var(--text-secondary) 70%, transparent);
  }

  .expert-section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary);
    margin: 0 0 8px;
  }

  /* ─── ESS table ────────────────────────────────────────────────────────────── */
  .ess-table-wrap {
    overflow-x: auto;
  }

  .ess-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }

  .ess-table th {
    text-align: left;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary);
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .ess-table td {
    padding: 5px 8px;
    color: var(--text-primary);
    border-bottom: 1px solid color-mix(in srgb, var(--border-subtle) 50%, transparent);
    vertical-align: middle;
  }

  .param-name {
    font-family: var(--font-mono, monospace);
    font-size: 11px;
    color: var(--text-secondary);
  }

  .metric-val {
    font-variant-numeric: tabular-nums;
    font-size: 12px;
    text-align: right;
  }

  .no-data {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
    padding: 8px 0;
  }

  .ppc-scatter-wrap {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
