<script>
  /**
   * StepSummary — Wizard Step 6: Summary + Diagnostics + Run.
   *
   * Per §2.6 WIZARD_FLOW_v2_FINAL.md:
   *   Shown AFTER training completes (model has been built).
   *   Diagnostics fields populated from train pipeline results.
   *
   * Traffic-light thresholds per §6.2 / Q-fin-2:
   *   MCMC:    green R-hat<1.05 & ESS>400 / yellow 1.05-1.10 or 200-400 / red >1.10 or <200
   *   Backtest: green MAPE<10% R²>0.85 / yellow 10-20% 0.70-0.85 / red >20% or <0.70
   *   PPC R²:  green >0.85 / yellow 0.70-0.85 / red <0.70
   *   Sensitivity: always yellow (informational, not a blocker)
   *
   * Actions:
   *   onRun()        → proceed to Decompose
   *   onEditExpert() → switch to Expert mode with pre-filled wizard values
   *
   * @component StepSummary
   */

  import {
    Activity,
    Target,
    FileLineChart,
    Save,
    Download,
    CheckCircle,
    AlertTriangle,
    AlertCircle,
    ChevronLeft,
    ChevronRight,
    Info,
  } from 'lucide-svelte';
  import { wizardState } from '$lib/wizard-state.js';
  import { analysisMode, kpiKind, kpiType, expertMode } from '$lib/project-state.js';

  /**
   * @typedef {Object} McmcDiagnostics
   * @property {number} rHatMax
   * @property {number} essMin
   */

  /**
   * @typedef {Object} BacktestDiagnostics
   * @property {number} mape         - MAPE in percent (e.g. 8.2 = 8.2%)
   * @property {number} r2           - R-squared
   * @property {number|null} [rmse]
   */

  /**
   * @typedef {Object} PpcDiagnostics
   * @property {number} r2           - Posterior predictive R²
   * @property {boolean} [hasBias]   - true if residual bias detected
   */

  /**
   * @typedef {Object} SensitivityEntry
   * @property {string} param        - e.g. "TV-adstock"
   * @property {number} deltaPct     - delta % (e.g. 15 = ±15%)
   */

  /**
   * @typedef {Object} Diagnostics
   * @property {McmcDiagnostics} mcmcConvergence
   * @property {BacktestDiagnostics} backtest
   * @property {PpcDiagnostics} ppc
   * @property {SensitivityEntry[]} sensitivity   - top-7 sorted desc by |deltaPct|
   */

  /**
   * @typedef {Object} ExternalFactorContrib
   * @property {string} name
   * @property {number} pct          - contribution percent (positive = beneficial, negative = drag)
   */

  /**
   * @typedef {Object} SoftRecommendation
   * @property {string} channel
   * @property {string} message
   */

  /**
   * @typedef {Object} SummaryData
   * @property {string} scenarioLabel        - e.g. "Оптимизация медиа-бюджета для established бренда"
   * @property {string} goalDescription      - e.g. "Распределить плановый бюджет 50 млн ₽ на 12 месяцев"
   * @property {string[]} channels           - e.g. ["TV", "Digital", "OOH", "Performance"]
   * @property {string} modeLabel            - e.g. "ROI режим (все каналы в ₽)"
   * @property {string} kpiLabel             - e.g. "продажи в упаковках"
   * @property {number|null} valuePerUnit    - e.g. 80
   * @property {string} taskTypeLabel        - human-readable task
   * @property {ExternalFactorContrib[]} externalFactors
   * @property {SoftRecommendation[]} softRecommendations
   */

  /**
   * v2.0.0 audit fix: relaxed types to allow partial / null data during
   * wizard development. Component handles missing fields gracefully via nullish coalescing.
   * @type {{
   *   summary: any,
   *   diagnostics: any,
   *   onRun: () => void,
   *   onEditExpert: () => void,
   *   onSaveModel?: (() => void) | null,
   *   onDownloadJson?: (() => void) | null,
   *   onBack?: (() => void) | null,
   * }}
   */
  const {
    summary,
    diagnostics,
    onRun,
    onEditExpert,
    onSaveModel = null,
    onDownloadJson = null,
    onBack = null,
  } = $props();

  // ─── Traffic-light helpers ───

  /**
   * @param {number} rHatMax
   * @param {number} essMin
   * @returns {'green'|'yellow'|'red'}
   */
  function mcmcStatus(rHatMax, essMin) {
    if (rHatMax > 1.10 || essMin < 200) return 'red';
    if (rHatMax > 1.05 || essMin < 400) return 'yellow';
    return 'green';
  }

  /**
   * @param {number} mape
   * @param {number} r2
   * @returns {'green'|'yellow'|'red'}
   */
  function backtestStatus(mape, r2) {
    if (mape > 20 || r2 < 0.70) return 'red';
    if (mape > 10 || r2 < 0.85) return 'yellow';
    return 'green';
  }

  /**
   * @param {number} r2
   * @returns {'green'|'yellow'|'red'}
   */
  function ppcStatus(r2) {
    if (r2 < 0.70) return 'red';
    if (r2 < 0.85) return 'yellow';
    return 'green';
  }

  /** @param {'green'|'yellow'|'red'} status */
  function trafficDot(status) {
    if (status === 'green')  return '🟢';
    if (status === 'yellow') return '🟡';
    return '🔴';
  }

  /** @param {'green'|'yellow'|'red'} status @returns {string} */
  function trafficLabel(status) {
    if (status === 'green')  return 'ok';
    if (status === 'yellow') return 'внимание';
    return 'требует внимания';
  }

  // ─── Derived status values ───
  const mcmcSt      = $derived(mcmcStatus(diagnostics.mcmcConvergence.rHatMax, diagnostics.mcmcConvergence.essMin));
  const backtestSt  = $derived(backtestStatus(diagnostics.backtest.mape, diagnostics.backtest.r2));
  const ppcSt       = $derived(ppcStatus(diagnostics.ppc.r2));
  /** Sensitivity always yellow (informational) */
  const sensTopEntry = $derived(diagnostics.sensitivity[0] ?? null);

  /** Overall diagnostics status — worst of the three non-sensitivity */
  const overallStatus = $derived.by(() => {
    const statuses = [mcmcSt, backtestSt, ppcSt];
    if (statuses.includes('red')) return 'red';
    if (statuses.includes('yellow')) return 'yellow';
    return 'green';
  });

  /** true if any diagnostic is red — shows cascade warning */
  const hasRedDiagnostic = $derived(
    mcmcSt === 'red' || backtestSt === 'red' || ppcSt === 'red'
  );

  /** Format value to 1 decimal @param {number} v */
  function fmt1(v) {
    return v.toFixed(1);
  }

  /** Format value to 2 decimal @param {number} v */
  function fmt2(v) {
    return v.toFixed(2);
  }

  /** Format contribution percent with sign @param {number} v */
  function fmtPct(v) {
    const sign = v > 0 ? '+' : '';
    return `${sign}${fmt1(v)}%`;
  }
</script>

<div class="step-summary">

  <!-- ─── Summary card header ─── -->
  <div class="summary-card">
    <div class="card-title-row">
      <span class="card-eyebrow">Программа поняла вашу задачу</span>
    </div>

    <!-- Scenario -->
    <section class="summary-section">
      <h3 class="ss-label">
        <Activity size={15} strokeWidth={1.8} />
        Сценарий
      </h3>
      <p class="ss-value">{summary.scenarioLabel}</p>
    </section>

    <!-- Goal -->
    <section class="summary-section">
      <h3 class="ss-label">
        <Target size={15} strokeWidth={1.8} />
        Цель
      </h3>
      <p class="ss-value">{summary.goalDescription}</p>
      {#if summary.channels.length > 0}
        <p class="ss-sub">Каналы: {summary.channels.join(', ')}</p>
      {/if}
    </section>

    <!-- Mode -->
    <section class="summary-section">
      <h3 class="ss-label">
        <FileLineChart size={15} strokeWidth={1.8} />
        Эконометрический режим
      </h3>
      <p class="ss-value">{summary.modeLabel}</p>
      <p class="ss-sub">
        KPI: {summary.kpiLabel}
        {#if summary.valuePerUnit !== null && summary.valuePerUnit !== undefined}
          , ценность = {summary.valuePerUnit} ₽/ед.
        {/if}
      </p>
    </section>

    <!-- Task type -->
    <section class="summary-section">
      <h3 class="ss-label">
        <Info size={15} strokeWidth={1.8} />
        Тип расчёта
      </h3>
      <p class="ss-value">{summary.taskTypeLabel}</p>
    </section>

    <!-- ─── Diagnostics block ─── -->
    <div class="divider-row">
      <span class="divider-label">ДИАГНОСТИКА МОДЕЛИ</span>
    </div>

    <div class="diagnostics-grid">

      <!-- MCMC convergence -->
      <div class="diag-row diag-{mcmcSt}">
        <span class="traffic-dot" aria-label={`MCMC: ${trafficLabel(mcmcSt)}`}>
          {trafficDot(mcmcSt)}
        </span>
        <div class="diag-body">
          <span class="diag-name">Сходимость (MCMC)</span>
          <span class="diag-vals">
            R-hat {fmt2(diagnostics.mcmcConvergence.rHatMax)},
            ESS {diagnostics.mcmcConvergence.essMin}
            {#if mcmcSt === 'red'}
              <span class="diag-action"> — рекомендуем re-train</span>
            {:else if mcmcSt === 'yellow'}
              <span class="diag-action"> — допустимо, возможен re-train</span>
            {:else}
              <span class="diag-ok"> — OK</span>
            {/if}
          </span>
        </div>
      </div>

      <!-- Backtest -->
      <div class="diag-row diag-{backtestSt}">
        <span class="traffic-dot" aria-label={`Backtest: ${trafficLabel(backtestSt)}`}>
          {trafficDot(backtestSt)}
        </span>
        <div class="diag-body">
          <span class="diag-name">Backtest (4 месяца holdout)</span>
          <span class="diag-vals">
            MAPE {fmt1(diagnostics.backtest.mape)}%
            {#if diagnostics.backtest.rmse !== null && diagnostics.backtest.rmse !== undefined}
              , RMSE {fmt1(diagnostics.backtest.rmse)}
            {/if}
            , R² {fmt2(diagnostics.backtest.r2)}
            {#if backtestSt === 'red'}
              <span class="diag-action"> — проверьте данные</span>
            {:else if backtestSt === 'yellow'}
              <span class="diag-action"> — есть резерв точности</span>
            {:else}
              <span class="diag-ok"> — OK</span>
            {/if}
          </span>
        </div>
      </div>

      <!-- PPC -->
      <div class="diag-row diag-{ppcSt}">
        <span class="traffic-dot" aria-label={`PPC: ${trafficLabel(ppcSt)}`}>
          {trafficDot(ppcSt)}
        </span>
        <div class="diag-body">
          <span class="diag-name">Posterior predictive</span>
          <span class="diag-vals">
            R² {fmt2(diagnostics.ppc.r2)} на observed
            {#if diagnostics.ppc.hasBias}
              <span class="diag-action"> — обнаружен bias в residuals</span>
            {:else}
              <span class="diag-ok"> — без bias residuals</span>
            {/if}
          </span>
        </div>
      </div>

      <!-- Sensitivity (always yellow, informational) -->
      {#if sensTopEntry !== null}
        <div class="diag-row diag-yellow">
          <span class="traffic-dot" aria-label="Sensitivity: информационно">🟡</span>
          <div class="diag-body">
            <span class="diag-name">Sensitivity</span>
            <span class="diag-vals">
              {sensTopEntry.param} ±20% → ROI меняется на ±{fmt1(sensTopEntry.deltaPct)}%
              <span class="diag-note"> (нормально)</span>
            </span>
          </div>
        </div>
      {/if}

    </div>

    <!-- ─── Red diagnostic cascade warning ─── -->
    {#if hasRedDiagnostic}
      <div class="cascade-warning" role="alert">
        <AlertCircle size={16} strokeWidth={2} />
        <div class="cascade-body">
          <strong>Качество модели требует внимания.</strong>
          Рекомендуем проверить данные и при необходимости повторить обучение прежде чем запускать анализ.
          Можно продолжить — результаты будут с пометкой «низкая надёжность».
        </div>
      </div>
    {/if}

    <!-- ─── External factors block ─── -->
    {#if summary.externalFactors.length > 0}
      <div class="divider-row">
        <span class="divider-label">ВНЕШНИЕ ФАКТОРЫ</span>
      </div>

      <ul class="factors-list" role="list">
        {#each summary.externalFactors as factor}
          <li class="factor-item {factor.pct < 0 ? 'factor-neg' : 'factor-pos'}">
            <CheckCircle size={13} strokeWidth={2.5} />
            <span class="factor-name">{factor.name} учтён:</span>
            <span class="factor-pct">{fmtPct(factor.pct)} вклад</span>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- ─── Soft recommendations block ─── -->
    {#if summary.softRecommendations.length > 0}
      <div class="soft-rec-block">
        <div class="soft-rec-header">
          <AlertTriangle size={14} strokeWidth={2} />
          Soft-recommendations (можно проигнорировать)
        </div>
        <ul class="soft-rec-list">
          {#each summary.softRecommendations as rec}
            <li class="soft-rec-item">
              <span class="dot">•</span>
              {rec.channel} — {rec.message}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

  </div>

  <!-- ─── Action buttons ─── -->
  <div class="actions-row">
    <div class="actions-left">
      {#if onBack}
        <button type="button" class="btn-ghost btn-back" onclick={onBack}>
          <ChevronLeft size={15} strokeWidth={2} />
          Назад
        </button>
      {/if}
    </div>

    <div class="actions-right">
      {#if onSaveModel}
        <button type="button" class="btn-secondary" onclick={onSaveModel}>
          <Save size={14} strokeWidth={2} />
          Сохранить модель
        </button>
      {/if}
      {#if onDownloadJson}
        <button type="button" class="btn-secondary" onclick={onDownloadJson}>
          <Download size={14} strokeWidth={2} />
          Скачать model.json
        </button>
      {/if}
      <button type="button" class="btn-ghost btn-expert" onclick={onEditExpert}>
        Изменить настройки (Expert)
      </button>
      <button
        type="button"
        class="btn-primary btn-run"
        onclick={onRun}
        aria-label="Запустить анализ"
      >
        Запустить анализ
        <ChevronRight size={16} strokeWidth={2.5} />
      </button>
    </div>
  </div>
</div>

<style>
  .step-summary {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 860px;
    margin: 0 auto;
    width: 100%;
  }

  /* ─── Main summary card ─── */
  .summary-card {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    box-shadow: var(--shadow-card, 0 2px 16px rgba(0,0,0,0.4));
    overflow: hidden;
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ─── Card title row ─── */
  .card-title-row {
    padding: 16px 20px 12px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #181824));
  }
  .card-eyebrow {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--gold, #c9a449);
  }

  /* ─── Summary sections ─── */
  .summary-section {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .summary-section:last-of-type {
    border-bottom: none;
  }

  .ss-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted, #7A7A90);
    margin: 0 0 2px;
  }
  .ss-value {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    line-height: 1.4;
  }
  .ss-sub {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
    line-height: 1.5;
  }

  /* ─── Divider rows ─── */
  .divider-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 20px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }
  .divider-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-muted, #7A7A90);
  }

  /* ─── Diagnostics grid ─── */
  .diagnostics-grid {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .diag-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 20px;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.04));
    transition: background 0.15s;
  }
  .diag-row:last-child {
    border-bottom: none;
  }
  .diag-green  { background: transparent; }
  .diag-yellow { background: color-mix(in srgb, var(--warning, #F59E0B) 3%, transparent); }
  .diag-red    { background: color-mix(in srgb, var(--danger, #ef4444) 5%, transparent); }

  .traffic-dot {
    flex-shrink: 0;
    font-size: 14px;
    line-height: 1.6;
    user-select: none;
  }

  .diag-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .diag-name {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .diag-vals {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .diag-ok     { color: var(--success, #22c55e); }
  .diag-action { color: var(--warning, #F59E0B); }
  .diag-note   { color: var(--text-muted, #7A7A90); }

  /* ─── Red cascade warning ─── */
  .cascade-warning {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: 0 16px 12px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--danger, #ef4444) 8%, var(--bg-card, #181824));
    border: 1px solid color-mix(in srgb, var(--danger, #ef4444) 30%, transparent);
    border-radius: var(--radius-sm, 8px);
    color: var(--danger, #ef4444);
    font-size: 12.5px;
    line-height: 1.5;
  }
  .cascade-body {
    flex: 1;
    color: var(--text-secondary);
  }
  .cascade-body strong {
    color: var(--danger, #ef4444);
    font-weight: 600;
  }

  /* ─── External factors list ─── */
  .factors-list {
    list-style: none;
    margin: 0;
    padding: 12px 20px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .factor-item {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    line-height: 1.5;
  }
  .factor-pos { color: var(--success, #22c55e); }
  .factor-neg { color: var(--warning, #F59E0B); }
  .factor-name {
    color: var(--text-secondary);
    font-weight: 500;
  }
  .factor-pct {
    font-weight: 600;
  }

  /* ─── Soft recommendations ─── */
  .soft-rec-block {
    margin: 0 16px 16px;
    padding: 12px 14px;
    background: color-mix(in srgb, var(--warning, #F59E0B) 5%, var(--bg-card, #181824));
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 20%, transparent);
    border-radius: var(--radius-sm, 8px);
  }
  .soft-rec-header {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--warning, #F59E0B);
    margin-bottom: 8px;
  }
  .soft-rec-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .soft-rec-item {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
  .dot {
    color: var(--text-muted, #7A7A90);
    flex-shrink: 0;
    margin-top: 1px;
  }

  /* ─── Actions row ─── */
  .actions-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    padding-top: 4px;
  }
  .actions-left,
  .actions-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  /* ─── Buttons ─── */
  .btn-primary {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 11px 24px;
    background: var(--gold, #c9a449);
    color: #0a0a14;
    font-size: 14px;
    font-weight: 700;
    border: none;
    border-radius: var(--radius-sm, 8px);
    cursor: pointer;
    transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
    font-family: inherit;
    letter-spacing: -0.01em;
  }
  .btn-primary:hover {
    background: color-mix(in srgb, var(--gold, #c9a449) 85%, white);
    transform: translateY(-1px);
    box-shadow: 0 4px 16px color-mix(in srgb, var(--gold, #c9a449) 30%, transparent);
  }
  .btn-run {
    min-width: 175px;
    justify-content: center;
    font-size: 15px;
    padding: 12px 28px;
  }

  .btn-secondary {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: var(--bg-surface-quiet, rgba(20,20,30,0.92));
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-secondary);
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    font-family: inherit;
  }
  .btn-secondary:hover {
    border-color: var(--gold, #c9a449);
    color: var(--text-primary);
  }

  .btn-ghost {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: none;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: var(--radius-sm, 8px);
    color: var(--text-muted, #7A7A90);
    font-size: 12.5px;
    font-weight: 500;
    padding: 8px 14px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
    font-family: inherit;
  }
  .btn-ghost:hover {
    border-color: var(--border, rgba(255,255,255,0.1));
    color: var(--text-secondary);
  }
  /* .btn-back inherits .btn-ghost styles */
  .btn-expert {
    color: var(--text-secondary);
    border-color: var(--border, rgba(255,255,255,0.08));
  }
  .btn-expert:hover {
    border-color: var(--warning, #F59E0B);
    color: var(--warning, #F59E0B);
  }
</style>
