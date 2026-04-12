<script>
  /**
   * Step 4: Budget Optimization — KILLER FEATURE.
   * C1: builds scaledParams from modelData.channelParams + current_spend from optimize response.
   * C4: triggerCompletion() on step completion.
   * A4: media query for two-column layout < 1000px → stack.
   * Layout: insight → controls → [BudgetOptimizer | ResponseCurves] → ScenarioPlayground.
   * @component OptimizeStep
   */
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    modelData,
    optimizeData,
    completeStep,
    setStepError,
    isComputing,
    computeStatus,
    triggerCompletion,
    sessionStats,
  } from '$lib/project-state.js';
  import { buildScaledParams, predictKPI } from '$lib/hill.js';
  import BudgetOptimizer from '$lib/components/pipeline/BudgetOptimizer.svelte';
  import ResponseCurves from '$lib/components/pipeline/ResponseCurves.svelte';
  import ScenarioPlayground from '$lib/components/pipeline/ScenarioPlayground.svelte';

  /** @type {'idle' | 'optimizing' | 'done' | 'error'} */
  let stepState = $state('idle');
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {boolean} */
  let budgetLocked = $state(true);
  /** @type {boolean} */
  let playgroundOpen = $state(false);
  /** @type {number | null} */
  let totalBudgetInput = $state(null);
  let minPct = $state(50);
  let maxPct = $state(150);

  // Current data from store
  const optData = $derived($optimizeData);
  const mData = $derived($modelData);

  /** @type {string[]} */
  const channels = $derived(optData?.channels?.map(/** @type {(c: any) => string} */ (c) => c.name) ?? []);

  /** @type {Record<string, number>} current spend from optimize response */
  const currentSpend = $derived.by(() => {
    if (!optData?.channels) return {};
    return Object.fromEntries(optData.channels.map(/** @type {(c: any) => [string, number]} */ (c) => [c.name, c.current_spend]));
  });

  /** @type {Record<string, {alpha: number, gammaScaled: number, beta: number}>} */
  const scaledParams = $derived.by(() => {
    if (!mData?.channelParams || !Object.keys(currentSpend).length) return {};
    return buildScaledParams(mData.channelParams, currentSpend);
  });

  /** Current KPI at current_spend (baseline for lift%). Uses predictKPI from hill.js. */
  const currentKPI = $derived(predictKPI(currentSpend, scaledParams));

  /** Shared channel budgets — source of truth for BudgetOptimizer & ResponseCurves */
  let channelBudgets = $state(/** @type {Record<string, number>} */ ({}));

  /** Optimal budgets from last run */
  let optimalBudgets = $state(/** @type {Record<string, number> | null} */ (null));

  // Init channelBudgets when optData arrives
  // IMPORTANT: don't read stepState here — it would create a recursive dependency
  $effect(() => {
    const data = $optimizeData;
    if (data?.channels && channels.length > 0) {
      const init = /** @type {Record<string, number>} */ ({});
      for (const ch of data.channels) init[ch.name] = ch.current_spend;
      channelBudgets = init;
      totalBudgetInput = data.total_budget ?? null;
    }
  });

  /** Run scipy optimization */
  async function runOptimize() {
    const projectId = get(activeProjectId);
    if (!projectId) return;

    stepState = 'optimizing';
    isComputing.set(true);
    computeStatus.set('Оптимизирую бюджет...');
    errorMessage = null;

    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId }));
      const result = /** @type {any} */ (await invoke('econ_optimize', {
        projectDir,
        totalBudget: totalBudgetInput,
        minPct,
        maxPct,
      }));

      if (result.status === 'ok') {
        optimizeData.set(result);
        stepState = 'done';

        // Build optimalBudgets for slider animation targets
        const ob = /** @type {Record<string, number>} */ ({});
        for (const ch of (result.channels ?? [])) ob[ch.name] = ch.optimal_spend;
        optimalBudgets = ob;
      } else {
        handleError(result.message || 'Ошибка оптимизации');
      }
    } catch (/** @type {any} */ e) {
      handleError(String(e));
    } finally {
      isComputing.set(false);
      computeStatus.set('');
    }
  }

  /** Apply optimal budgets to sliders with animation */
  function applyOptimal() {
    if (!optimalBudgets) return;
    // Animate: set budgets step by step over 800ms
    const start = { ...channelBudgets };
    const end = optimalBudgets;
    const duration = 800;
    const startTime = Date.now();

    /** @param {number} t */
    function smoothstep(t) {
      return t * t * (3 - 2 * t);
    }

    function animate() {
      const elapsed = Date.now() - startTime;
      const t = Math.min(elapsed / duration, 1);
      const s = smoothstep(t);

      const newBudgets = /** @type {Record<string, number>} */ ({});
      for (const ch of channels) {
        newBudgets[ch] = start[ch] + (end[ch] - start[ch]) * s;
      }
      channelBudgets = newBudgets;

      if (t < 1) requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
  }

  /** @param {string} msg */
  function handleError(msg) {
    errorMessage = msg;
    stepState = 'error';
    setStepError(4, msg);
    isComputing.set(false);
    computeStatus.set('');
  }

  /** Reset to current spend */
  function resetBudgets() {
    const data = get(optimizeData);
    if (!data?.channels) return;
    const init = /** @type {Record<string, number>} */ ({});
    for (const ch of data.channels) init[ch.name] = ch.current_spend;
    channelBudgets = init;
    optimalBudgets = null;
  }

  /** Confirm optimization & complete step */
  function confirmOptimization() {
    sessionStats.update(s => ({ ...s, scenarioCount: s.scenarioCount + 1 }));
    completeStep(4);
    triggerCompletion();
  }

  /**
   * @param {string} ch
   * @param {number} val
   */
  function handleBudgetChange(ch, val) {
    channelBudgets = { ...channelBudgets, [ch]: val };
  }
</script>

<div class="optimize-step">

  <!-- Error banner -->
  {#if stepState === 'error' && errorMessage}
    <div class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-text">{errorMessage}</span>
      <button class="btn-retry" onclick={runOptimize}>Повторить</button>
    </div>
  {/if}

  <!-- Insight banner -->
  {#if optData?.insight}
    <div class="insight-banner">
      <span class="insight-icon">🎯</span>
      <p class="insight-text">{optData.insight}</p>
      {#if optData.expected_lift_pct != null}
        <span class="lift-badge" class:negative-lift={optData.expected_lift_pct < 0}>
          {optData.expected_lift_pct >= 0 ? '+' : ''}{optData.expected_lift_pct.toFixed(1)}%
        </span>
      {/if}
    </div>
  {/if}

  <!-- Controls -->
  <div class="controls-card">
    <div class="controls-row">
      <label class="ctrl-label">
        Общий бюджет
        <input
          type="number"
          class="budget-input"
          bind:value={totalBudgetInput}
          placeholder="авто"
          min={0}
          step={10000}
        />
      </label>
      <label class="ctrl-label">
        Мин. %
        <input type="range" min={10} max={100} step={5} bind:value={minPct} class="mini-slider" />
        <span class="mini-val">{minPct}%</span>
      </label>
      <label class="ctrl-label">
        Макс. %
        <input type="range" min={100} max={300} step={10} bind:value={maxPct} class="mini-slider" />
        <span class="mini-val">{maxPct}%</span>
      </label>
      <button
        class="btn-run"
        onclick={runOptimize}
        disabled={stepState === 'optimizing'}
      >
        {stepState === 'optimizing' ? 'Оптимизирую...' : 'Оптимизировать бюджет'}
      </button>
      <label class="lock-label">
        <input type="checkbox" bind:checked={budgetLocked} class="lock-check" />
        Фиксировать бюджет
      </label>
    </div>
  </div>

  <!-- Two-column: BudgetOptimizer | ResponseCurves -->
  {#if channels.length > 0}
    <div class="optimize-grid">
      <div class="card">
        <div class="card-title">Распределение бюджета</div>
        <BudgetOptimizer
          {channels}
          {scaledParams}
          {channelBudgets}
          initialSpend={currentSpend}
          currentKPI={currentKPI}
          locked={budgetLocked}
          onBudgetChange={handleBudgetChange}
          onOptimize={applyOptimal}
          onReset={resetBudgets}
          optimizing={stepState === 'optimizing'}
          {optimalBudgets}
        />
      </div>
      <div class="card">
        <div class="card-title">Response Curves</div>
        {#if optData?.response_curves && Object.keys(scaledParams).length > 0}
          <ResponseCurves
            responseCurves={optData.response_curves}
            {channelBudgets}
            {scaledParams}
            {channels}
            onBudgetChange={handleBudgetChange}
          />
        {:else}
          <div class="no-curves">Запустите оптимизацию для отображения кривых</div>
        {/if}
      </div>
    </div>

    <!-- Confirm + Scenario Playground -->
    <div class="bottom-section">
      <div class="confirm-row">
        <button class="btn-confirm" onclick={confirmOptimization}>
          Подтвердить и перейти к отчёту →
        </button>
        <button
          class="btn-scenario-toggle"
          onclick={() => { playgroundOpen = !playgroundOpen; }}
        >
          {playgroundOpen ? '▲' : '▼'} Сценарии
        </button>
      </div>

      {#if playgroundOpen}
        <div class="card scenario-card">
          <div class="card-title">Сценарный анализ</div>
          <ScenarioPlayground {channelBudgets} {channels} />
        </div>
      {/if}
    </div>
  {:else if stepState === 'idle'}
    <div class="empty-state">
      <p>Запустите оптимизацию для интерактивного анализа бюджета</p>
      <button class="btn-run-big" onclick={runOptimize}>Оптимизировать бюджет</button>
    </div>
  {/if}

</div>

<style>
  .optimize-step {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.25);
    border-radius: 10px;
    flex-wrap: wrap;
  }
  .error-icon { font-size: 16px; flex-shrink: 0; }
  .error-text { flex: 1; font-size: 13px; color: #ef4444; }
  .btn-retry {
    padding: 6px 14px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 6px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }

  .insight-banner {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 16px;
    background: rgba(59,130,246,0.08);
    border: 1px solid rgba(59,130,246,0.2);
    border-radius: 10px;
  }
  .insight-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
  .insight-text { flex: 1; font-size: 13px; color: var(--text-secondary, #94a3b8); line-height: 1.6; margin: 0; }
  .lift-badge {
    flex-shrink: 0;
    padding: 4px 10px;
    background: rgba(34,197,94,0.15);
    border: 1px solid rgba(34,197,94,0.3);
    border-radius: 20px;
    color: #22c55e;
    font-size: 13px;
    font-weight: 700;
    font-family: monospace;
  }
  .lift-badge.negative-lift {
    background: rgba(239,68,68,0.15);
    border-color: rgba(239,68,68,0.3);
    color: #ef4444;
  }

  .controls-card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 14px 16px;
  }
  .controls-row {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .ctrl-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
  }
  .budget-input {
    width: 100px;
    padding: 6px 10px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
    outline: none;
  }
  .mini-slider {
    width: 80px;
    height: 3px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    outline: none;
  }
  .mini-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--accent-primary, #3b82f6);
    cursor: pointer;
  }
  .mini-val { font-size: 11px; font-family: monospace; min-width: 32px; }

  .btn-run {
    padding: 8px 18px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: opacity 0.15s;
  }
  .btn-run:hover:not(:disabled) { opacity: 0.85; }
  .btn-run:disabled { opacity: 0.5; cursor: not-allowed; }

  .lock-label {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    user-select: none;
  }
  .lock-check { cursor: pointer; accent-color: var(--accent-primary, #3b82f6); }

  /* A4: two-column, stack on narrow */
  .optimize-grid {
    display: grid;
    grid-template-columns: 2fr 3fr;
    gap: 16px;
  }
  @media (max-width: 1000px) {
    .optimize-grid { grid-template-columns: 1fr; }
  }

  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .no-curves {
    padding: 40px 20px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
  }

  .bottom-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .confirm-row {
    display: flex;
    gap: 10px;
    align-items: center;
  }

  .btn-confirm {
    flex: 1;
    padding: 11px 20px;
    background: linear-gradient(135deg, #22c55e, #16a34a);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-confirm:hover { opacity: 0.9; }

  .btn-scenario-toggle {
    padding: 11px 16px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .btn-scenario-toggle:hover { border-color: rgba(255,255,255,0.25); color: var(--text-primary, #e2e8f0); }

  .scenario-card { margin-top: 4px; }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    padding: 60px 20px;
    text-align: center;
    color: var(--text-secondary, #94a3b8);
    font-size: 14px;
  }
  .btn-run-big {
    padding: 12px 28px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .btn-run-big:hover { opacity: 0.85; }
</style>
