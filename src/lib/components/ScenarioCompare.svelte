<script>
  /**
   * Scenario comparison panel.
   * - Budget sliders (what-if: TV ±30%)
   * - Upload mediaplan xlsx
   * - Side-by-side comparison table
   *
   * @component ScenarioCompare
   */
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import { get } from 'svelte/store';
  import {
    activeProjectId,
    pipelineState,
    isComputing,
    computeStatus,
    chartImages,
    valuePerCountUnit,
    kpiKind,
  } from '$lib/project-state.js';
  import DataTable from './DataTable.svelte';
  import { formatMoney, formatCount, formatROI } from '$lib/format-numbers.js';

  // B3-E2 (pilot R3 2026-05-17): kpiKind-aware label вместо hardcoded «% продаж».
  // monetary → «% продаж», count → «% KPI» (generic, покрывает sales_packs/leads/etc).
  const liftLabel = $derived($kpiKind === 'count' ? '% KPI' : '% продаж');

  // v2.1.0 (pilot R2 B2-02 2026-05-17): derive kpi_unit_cost для count KPI.
  // Без него econ_scenario сохраняет сценарий без money equivalents → при
  // загрузке lift/KPI расходится с тем, что показано на момент создания
  // (ADR-021 incomplete coverage, обнаружено в pilot round 2).
  function deriveKpiUnitCost() {
    const k = get(valuePerCountUnit);
    return get(kpiKind) === 'count' && typeof k === 'number' && k > 0 ? k : null;
  }

  /** @type {{ channels?: string[], optimization?: any }} */
  let { channels = [], optimization } = $props();

  // ── Sliders state ──
  /** @type {Record<string, number>} Channel budget multiplier (100 = unchanged) */
  let sliders = $state(/** @type {Record<string, number>} */ ({}));
  let sliderPrediction = $state('');

  $effect(() => {
    if (channels.length && Object.keys(sliders).length === 0) {
      /** @type {Record<string, number>} */
      const init = {};
      for (const ch of channels) init[ch] = 100;
      sliders = init;
    }
  });

  /** @type {any[]} Saved scenarios for comparison */
  let scenarios = $state([]);
  let comparison = $state(/** @type {any} */ (null));

  // B3-E1 (pilot R3 2026-05-17): pre-format rows per row_units flag, чтобы
  // DataTable получала string-cells с правильной размерностью. Money primary
  // для count+kpi_unit_cost; native count fallback для legacy/monetary.
  /** @param {any} comp */
  function formatComparisonRows(comp) {
    if (!comp || !Array.isArray(comp.rows)) return comp;
    const units = Array.isArray(comp.row_units) ? comp.row_units : [];
    const rows = comp.rows.map(/** @param {any[]} row @param {number} i */ (row, i) => {
      const unit = units[i];
      if (!unit) return row;
      return row.map(/** @param {any} cell @param {number} j */ (cell, j) => {
        // Label column (j=0) и non-numeric cells - оставить как есть.
        if (j === 0 || cell == null || typeof cell !== 'number') return cell;
        if (unit === '₽' || unit === 'money') return formatMoney(cell);
        if (unit === 'count') return formatCount(cell, '');
        if (unit === 'roas') return formatROI(cell);
        // 'native' / 'pct' / unknown - DataTable fmt() handles thousand sep.
        return cell;
      });
    });
    return { ...comp, rows };
  }

  let displayComparison = $derived(formatComparisonRows(comparison));

  // ── Slider what-if (instant predict) ──
  /** @param {string} channel */
  async function onSliderChange(channel) {
    const projectId = $activeProjectId;
    if (!projectId) return;

    // Build media plan from sliders (relative to current spend)
    /** @type {Record<string, number[]>} */
    const plan = {};
    for (const ch of channels) {
      const mult = (sliders[ch] || 100) / 100;
      // Single period prediction
      plan[ch] = [mult];
    }

    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName: 'slider-preview',
        mediaPlan: plan,
        kpiUnitCost: deriveKpiUnitCost(),
      }));
      if (result.status === 'ok') {
        sliderPrediction = `Прогноз: ${result.totals.lift_pct > 0 ? '+' : ''}${result.totals.lift_pct}${liftLabel}`;
      }
    } catch { /* silent */ }
  }

  // ── Upload mediaplan ──
  async function uploadMediaplan() {
    const projectId = $activeProjectId;
    if (!projectId) return;

    const filePath = await open({
      filters: [{ name: 'Excel', extensions: ['xlsx', 'xls', 'csv'] }],
      multiple: false,
    });
    if (!filePath) return;

    isComputing.set(true);
    computeStatus.set('Загружаю медиаплан...');

    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName: `mediaplan-${Date.now()}`,
        mediaPlanFile: filePath,
        kpiUnitCost: deriveKpiUnitCost(),
      }));

      if (result.status === 'ok') {
        computeStatus.set(`Прогноз: ${result.totals.lift_pct > 0 ? '+' : ''}${result.totals.lift_pct}${liftLabel}`);
        await loadComparison();
      } else {
        computeStatus.set(`Ошибка: ${result.message}`);
      }
    } catch (e) {
      computeStatus.set(`Ошибка: ${e}`);
    }

    setTimeout(() => { isComputing.set(false); computeStatus.set(''); }, 3000);
  }

  // ── Load comparison ──
  async function loadComparison() {
    const projectId = $activeProjectId;
    if (!projectId) return;

    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_compare', { projectDir }));
      if (result.status === 'ok') {
        scenarios = result.scenarios || [];
        comparison = result.comparison || null;
      }
    } catch { /* silent */ }
  }

  // ── Generate chart ──
  async function loadResponseCurves() {
    const projectId = $activeProjectId;
    if (!projectId) return;

    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_chart', { projectDir, chartType: 'response_curves' }));
      if (result.status === 'ok' && result.chart) {
        chartImages.update(/** @param {any} c */ (c) => ({ ...c, response_curves: result.chart }));
      }
    } catch { /* silent */ }
  }
</script>

<div class="scenario-panel">
  <!-- Sliders section -->
  <div class="section">
    <h4 class="section-title">Бюджетные сценарии</h4>
    <p class="section-hint">Перетащите ползунок - прогноз обновится мгновенно</p>

    <div class="sliders">
      {#each channels as ch}
        <div class="slider-row">
          <span class="slider-label">{ch}</span>
          <input
            type="range"
            min="0" max="200" step="5"
            bind:value={sliders[ch]}
            oninput={() => onSliderChange(ch)}
            class="slider"
          />
          <span class="slider-value" class:positive={sliders[ch] > 100} class:negative={sliders[ch] < 100}>
            {sliders[ch] > 100 ? '+' : ''}{sliders[ch] - 100}%
          </span>
        </div>
      {/each}
    </div>

    {#if sliderPrediction}
      <div class="slider-result">{sliderPrediction}</div>
    {/if}
  </div>

  <!-- Upload mediaplan -->
  <div class="section">
    <h4 class="section-title">Загрузить медиаплан</h4>
    <button class="upload-btn" onclick={uploadMediaplan} disabled={$isComputing}>
      📎 Загрузить xlsx с медиапланом
    </button>
    <p class="section-hint">Формат: дата | канал1 | канал2 | ... (бюджеты в руб.)</p>
  </div>

  <!-- Response curves -->
  {#if $chartImages.response_curves}
    <div class="section">
      <h4 class="section-title">Response Curves</h4>
      <img
        class="chart-img"
        src="data:image/png;base64,{$chartImages.response_curves}"
        alt="Response Curves по каналам"
      />
    </div>
  {:else if optimization}
    <button class="chart-btn" onclick={loadResponseCurves}>Показать Response Curves</button>
  {/if}

  <!-- Comparison table -->
  {#if displayComparison}
    <div class="section">
      <DataTable
        mode="scenario"
        title="Сравнение сценариев"
        headers={displayComparison.headers}
        rows={displayComparison.rows}
        highlightColumn={displayComparison.headers?.[1]}
      />
    </div>
  {:else if scenarios.length === 0}
    <button class="chart-btn" onclick={loadComparison}>Загрузить сценарии</button>
  {/if}
</div>

<style>
  .scenario-panel {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .section {
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }

  .section-title {
    margin: 0 0 8px;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .section-hint {
    margin: 0 0 12px;
    font-size: 12px;
    color: var(--text-secondary, #94a3b8);
  }

  .sliders {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .slider-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .slider-label {
    min-width: 120px;
    font-size: 12px;
    color: var(--text-primary, #e2e8f0);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
    outline: none;
  }

  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent-primary, #3b82f6);
    cursor: pointer;
  }

  .slider-value {
    min-width: 48px;
    text-align: right;
    font-size: 12px;
    font-family: monospace;
    color: var(--text-secondary, #94a3b8);
  }

  .slider-value.positive { color: var(--success, #22c55e); }
  .slider-value.negative { color: var(--error, #ef4444); }

  .slider-result {
    margin-top: 12px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 20%, transparent);
    border-radius: 8px;
    color: var(--accent-primary, #3b82f6);
    font-size: 14px;
    font-weight: 600;
    text-align: center;
  }

  .upload-btn {
    width: 100%;
    padding: 12px;
    background: rgba(0,0,0,0.2);
    border: 2px dashed rgba(255,255,255,0.15);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .upload-btn:hover:not(:disabled) {
    border-color: var(--accent-primary, #3b82f6);
    color: var(--text-primary, #e2e8f0);
  }

  .upload-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .chart-img {
    width: 100%;
    border-radius: 8px;
    margin-top: 8px;
  }

  .chart-btn {
    width: 100%;
    padding: 10px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
  }

  .chart-btn:hover {
    border-color: var(--accent-primary, #3b82f6);
    color: var(--text-primary, #e2e8f0);
  }
</style>
