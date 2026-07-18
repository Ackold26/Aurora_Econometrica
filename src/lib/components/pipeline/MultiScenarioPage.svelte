<script>
  /**
   * MultiScenarioPage - Phase D comparison page orchestrator.
   *
   * Layout per WIZARD_FLOW_v2_FINAL.md §4.1:
   *   1. MultiScenarioChart (top, full width)
   *   2. Comparison table (sortable: name / budget / KPI / CI 90% / Δ%)
   *   3. Per-channel breakdown (collapsible)
   *   4. Auto-generated diff narrative block
   *   5. Actions row: Export ▾ / Accept ▾ / Duplicate ▾ / Delete ▾
   *
   * Edge cases per spec audit:
   *   - 0 scenarios → empty state с CTA
   *   - 1 scenario → «нужно ≥2 для сравнения»
   *   - >5 scenarios → all in table, chart limits to 5
   *
   * Per ADR-019 §7 Multi-Scenario Comparison Page.
   *
   * @component MultiScenarioPage
   */

  import MultiScenarioChart from '$lib/components/pipeline/MultiScenarioChart.svelte';
  import {
    generateDiffNarratives,
    computePerChannelDiff,
  } from '$lib/scenario-diff-analyzer.js';
  import {
    exportToCsv,
    exportToExcel,
    exportToPptx,
    downloadText,
    buildExportFilename,
  } from '$lib/scenario-export.js';
  import {
    Download,
    Save,
    Copy,
    Trash2,
    ChevronDown,
    BarChart3,
  } from 'lucide-svelte';

  /**
   * @typedef {{
   *   id: string,
   *   name: string,
   *   budget: number,
   *   predictedKpi: number,
   *   ciLow?: number,
   *   ciHigh?: number,
   *   perChannelAllocation?: Record<string, number>,
   *   dates?: string[],
   *   predictions?: number[],
   *   ciLowSeries?: number[],
   *   ciHighSeries?: number[],
   *   extrapolation?: { severity: number, channels?: Array<{ name: string, ratio_vs_max?: number | null }> } | null,
   * }} Scenario
   */

  /**
   * @type {{
   *   scenarios: Scenario[],
   *   baseline?: Scenario | null,
   *   kpiLabel?: string,
   *   onAccept?: ((scenario: Scenario) => void) | null,
   *   onDuplicate?: ((scenario: Scenario) => void) | null,
   *   onDelete?: ((scenario: Scenario) => void) | null,
   * }}
   */
  const {
    scenarios = [],
    baseline = null,
    kpiLabel = 'KPI',
    onAccept = null,
    onDuplicate = null,
    onDelete = null,
  } = $props();

  // ── UI state ────────────────────────────────────────────────────────────────

  /** Currently selected scenario (for Accept / Duplicate / Delete actions) */
  let selectedId = $state(/** @type {string | null} */ (null));

  /** Collapsible per-channel breakdown */
  let breakdownOpen = $state(false);

  /** Sort column for comparison table */
  let sortCol = $state(/** @type {'name' | 'budget' | 'kpi' | 'uplift'} */ ('kpi'));
  let sortAsc = $state(false);

  /** Export dropdown open */
  let exportOpen = $state(false);
  /** Accept dropdown open */
  let acceptOpen = $state(false);
  /** Duplicate dropdown open */
  let duplicateOpen = $state(false);
  /** Delete dropdown open */
  let deleteOpen = $state(false);

  /** Export in-progress flag */
  let exportBusy = $state(false);
  /** Inline status message for export feedback */
  let exportStatus = $state(/** @type {string | null} */ (null));

  // ── Derived data ────────────────────────────────────────────────────────────

  /** All scenarios including baseline as first row (if distinct) */
  const allRows = $derived.by(() => {
    const base = baseline ? [baseline] : [];
    const rest = scenarios.filter(s => !baseline || s.id !== baseline.id);
    return [...base, ...rest];
  });

  /** Scenarios sorted by current sort column */
  const sortedRows = $derived.by(() => {
    const rows = [...allRows];
    rows.sort((a, b) => {
      /** @type {string | number} */
      let av;
      /** @type {string | number} */
      let bv;
      if (sortCol === 'name') {
        av = a.name.toLowerCase();
        bv = b.name.toLowerCase();
      } else if (sortCol === 'budget') {
        av = a.budget ?? 0;
        bv = b.budget ?? 0;
      } else if (sortCol === 'uplift') {
        av = baseline ? upliftPct(a) : (a.predictedKpi ?? 0);
        bv = baseline ? upliftPct(b) : (b.predictedKpi ?? 0);
      } else {
        // kpi
        av = a.predictedKpi ?? 0;
        bv = b.predictedKpi ?? 0;
      }
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return rows;
  });

  /** Auto-generated narratives */
  const narratives = $derived(generateDiffNarratives(scenarios, baseline));

  /** Collect all unique channel names across scenarios */
  const allChannels = $derived.by(() => {
    /** @type {Set<string>} */
    const ch = new Set();
    const all = baseline ? [baseline, ...scenarios] : scenarios;
    for (const sc of all) {
      for (const k of Object.keys(sc.perChannelAllocation ?? {})) ch.add(k);
    }
    return [...ch].sort();
  });

  /** Per-channel diff between selected scenario and baseline */
  const selectedChannelDiff = $derived.by(() => {
    if (!selectedId || !baseline) return [];
    const sc = scenarios.find(s => s.id === selectedId);
    if (!sc) return [];
    return computePerChannelDiff(baseline, sc);
  });

  // ── Helpers ─────────────────────────────────────────────────────────────────

  /**
   * Compute uplift % vs baseline.
   * @param {Scenario} sc
   * @returns {number}
   */
  function upliftPct(sc) {
    if (!baseline || !baseline.predictedKpi || sc.id === baseline.id) return 0;
    return ((sc.predictedKpi - baseline.predictedKpi) / Math.abs(baseline.predictedKpi)) * 100;
  }

  /**
   * Format budget in millions.
   * @param {number} v
   * @returns {string}
   */
  function fmtBudget(v) {
    if (!Number.isFinite(v)) return '-';
    const m = v / 1_000_000;
    if (m >= 1) return `${m.toFixed(m >= 10 ? 0 : 1)} млн ₽`;
    return `${(v / 1_000).toFixed(0)} тыс. ₽`;
  }

  /**
   * Format KPI with K/M suffix.
   * @param {number} v
   * @returns {string}
   */
  function fmtKpi(v) {
    if (!Number.isFinite(v)) return '-';
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
    if (v >= 1_000) return (v / 1_000).toFixed(0) + 'K';
    return Math.round(v).toLocaleString('ru-RU');
  }

  /**
   * Format CI 90% range.
   * @param {Scenario} sc
   * @returns {string}
   */
  function fmtCi(sc) {
    if (sc.ciLow == null || sc.ciHigh == null) return '-';
    return `${fmtKpi(sc.ciLow)} – ${fmtKpi(sc.ciHigh)}`;
  }

  /**
   * Format uplift string.
   * @param {Scenario} sc
   * @returns {string}
   */
  function fmtUplift(sc) {
    if (!baseline || sc.id === baseline.id) return '-';
    const pct = upliftPct(sc);
    const sign = pct >= 0 ? '+' : '';
    return `${sign}${pct.toFixed(1)}%`;
  }

  /**
   * CSS class for uplift cell.
   * @param {Scenario} sc
   * @returns {string}
   */
  function upliftClass(sc) {
    if (!baseline || sc.id === baseline.id) return '';
    const pct = upliftPct(sc);
    if (pct > 0) return 'positive';
    if (pct < 0) return 'negative';
    return '';
  }

  /**
   * Toggle sort: same col → flip direction; new col → descending.
   * @param {'name' | 'budget' | 'kpi' | 'uplift'} col
   */
  function toggleSort(col) {
    if (sortCol === col) {
      sortAsc = !sortAsc;
    } else {
      sortCol = col;
      sortAsc = false;
    }
  }

  /**
   * Sort indicator string.
   * @param {'name' | 'budget' | 'kpi' | 'uplift'} col
   * @returns {string}
   */
  function sortIndicator(col) {
    if (sortCol !== col) return '';
    return sortAsc ? ' ▲' : ' ▼';
  }

  // ── Actions ─────────────────────────────────────────────────────────────────

  /** @param {Scenario} sc */
  function handleAccept(sc) {
    acceptOpen = false;
    onAccept?.(sc);
  }

  /** @param {Scenario} sc */
  function handleDuplicate(sc) {
    duplicateOpen = false;
    onDuplicate?.(sc);
  }

  /** @param {Scenario} sc */
  function handleDelete(sc) {
    deleteOpen = false;
    if (selectedId === sc.id) selectedId = null;
    onDelete?.(sc);
  }

  /** Export to CSV (client-side) */
  async function handleExportCsv() {
    exportOpen = false;
    exportBusy = true;
    exportStatus = null;
    try {
      const csv = exportToCsv(scenarios, baseline);
      const fname = buildExportFilename(scenarios) + '.csv';
      downloadText(csv, fname, 'text/csv;charset=utf-8;');
      exportStatus = `CSV сохранён: ${fname}`;
    } catch (e) {
      exportStatus = `Ошибка: ${String(e)}`;
    } finally {
      exportBusy = false;
    }
  }

  /** Export to Excel via Rust backend */
  async function handleExportExcel() {
    exportOpen = false;
    exportBusy = true;
    exportStatus = null;
    try {
      const result = await exportToExcel(scenarios, baseline);
      if ('stub' in result) {
        exportStatus = result.message;
      } else {
        exportStatus = `Excel сохранён: ${result.path}`;
      }
    } catch (e) {
      exportStatus = `Ошибка: ${String(e)}`;
    } finally {
      exportBusy = false;
    }
  }

  /** Export to PPTX via Rust backend */
  async function handleExportPptx() {
    exportOpen = false;
    exportBusy = true;
    exportStatus = null;
    try {
      const result = await exportToPptx(scenarios, baseline);
      if ('stub' in result) {
        exportStatus = result.message;
      } else {
        exportStatus = `PPTX сохранён: ${result.path}`;
      }
    } catch (e) {
      exportStatus = `Ошибка: ${String(e)}`;
    } finally {
      exportBusy = false;
    }
  }

  // Close any open dropdown on outside click
  function handleDocClick(/** @type {MouseEvent} */ e) {
    const target = /** @type {HTMLElement | null} */ (e.target);
    if (!target?.closest('.dropdown-anchor')) {
      exportOpen = false;
      acceptOpen = false;
      duplicateOpen = false;
      deleteOpen = false;
    }
  }
</script>

<svelte:document onclick={handleDocClick} />

<section class="multi-scenario-page" aria-label="Сравнение сценариев">

  <!-- ── Header ──────────────────────────────────────────────────────────────── -->
  <header class="page-header">
    <div class="page-title-row">
      <BarChart3 size={20} strokeWidth={1.5} class="title-icon" />
      <h2 class="page-title">СРАВНЕНИЕ СЦЕНАРИЕВ</h2>
      {#if scenarios.length > 0}
        <span class="scenario-count">{scenarios.length} сценари{scenarios.length === 1 ? 'й' : 'я'}</span>
      {/if}
    </div>
  </header>

  <!-- ── Empty / single scenario states ──────────────────────────────────────── -->
  {#if scenarios.length === 0}
    <div class="empty-state" role="status">
      <BarChart3 size={40} strokeWidth={1} opacity={0.3} />
      <p class="empty-title">Нет сценариев для сравнения</p>
      <p class="empty-body">
        Добавьте сценарий через «Оптимизировать» или «Прогноз по плану»
        чтобы сравнить результаты.
      </p>
    </div>

  {:else if scenarios.length === 1 && !baseline}
    <div class="single-state" role="status">
      <p>Нужно ≥2 сценария для сравнения. Добавьте ещё один сценарий.</p>
    </div>

  {:else}
    <!-- ── Chart ──────────────────────────────────────────────────────────────── -->
    <div class="chart-block">
      <MultiScenarioChart
        scenarios={scenarios}
        baseline={baseline}
        maxVisible={5}
        kpiLabel={kpiLabel}
      />
    </div>

    <!-- ── Comparison Table ───────────────────────────────────────────────────── -->
    <div class="table-block" aria-label="Таблица сравнения сценариев">
      <div class="table-scroll">
        <table class="comparison-table">
          <thead>
            <tr>
              <th class="col-check"></th>
              <th class="col-name sortable" onclick={() => toggleSort('name')}>
                Сценарий{sortIndicator('name')}
              </th>
              <th class="col-budget sortable" onclick={() => toggleSort('budget')}>
                Бюджет{sortIndicator('budget')}
              </th>
              <th class="col-kpi sortable" onclick={() => toggleSort('kpi')}>
                {kpiLabel}{sortIndicator('kpi')}
              </th>
              <th class="col-ci">Диапазон 90%</th>
              {#if baseline}
                <th class="col-uplift sortable" onclick={() => toggleSort('uplift')}>
                  Δ%{sortIndicator('uplift')}
                </th>
              {/if}
            </tr>
          </thead>
          <tbody>
            {#each sortedRows as sc (sc.id)}
              {@const isBaseline = baseline && sc.id === baseline.id}
              {@const isSelected = selectedId === sc.id}
              <tr
                class:baseline-row={isBaseline}
                class:selected-row={isSelected}
                onclick={() => { selectedId = isSelected ? null : sc.id; }}
                role="row"
                aria-selected={isSelected}
                style="cursor: pointer;"
              >
                <td class="col-check">
                  <span class="row-dot" class:dot-selected={isSelected}></span>
                </td>
                <td class="col-name">
                  <span class="sc-name">{sc.name}</span>
                  {#if isBaseline}
                    <span class="badge-baseline">базовый</span>
                  {/if}
                  <!-- A3/OPP-03: единый язык extrapolation-тиров — бейдж из
                       сохранённого scenario-JSON (движок пишет с F-04);
                       прежде маркер вычислялся, но compare-страница молчала. -->
                  {#if sc.extrapolation && sc.extrapolation.severity >= 1}
                    <span
                      class="badge-extrapolation"
                      class:critical={sc.extrapolation.severity >= 2}
                      title={
                        (sc.extrapolation.severity >= 2
                          ? 'Сильная экстраполяция: '
                          : 'Экстраполяция: ')
                        + 'план уводит траты за диапазон, на котором обучалась модель'
                        + ((sc.extrapolation.channels ?? []).length
                          ? ' (' + (sc.extrapolation.channels ?? []).map((/** @type {any} */ c) =>
                              c.ratio_vs_max != null ? `${c.name} – ${c.ratio_vs_max}×` : c.name
                            ).join(', ') + ')'
                          : '')
                        + '. Форма кривой отклика в этой зоне не подтверждена данными.'
                      }
                    >📈 {sc.extrapolation.severity >= 2 ? 'сильная экстраполяция' : 'экстраполяция'}</span>
                  {/if}
                </td>
                <td class="col-budget">{fmtBudget(sc.budget)}</td>
                <td class="col-kpi"><strong>{fmtKpi(sc.predictedKpi)}</strong></td>
                <td class="col-ci">{fmtCi(sc)}</td>
                {#if baseline}
                  <td class="col-uplift {upliftClass(sc)}">{fmtUplift(sc)}</td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Per-channel Breakdown ─────────────────────────────────────────────── -->
    <details
      class="breakdown-block"
      bind:open={breakdownOpen}
    >
      <summary class="breakdown-summary">
        <ChevronDown size={14} class="chevron-icon" />
        <span>Распределение по каналам</span>
        {#if allChannels.length > 0}
          <span class="channel-count">{allChannels.length} каналов</span>
        {/if}
      </summary>

      <div class="breakdown-content">
        {#if allChannels.length === 0}
          <p class="breakdown-empty">Нет данных о распределении по каналам.</p>
        {:else}
          <div class="breakdown-scroll">
            <table class="breakdown-table">
              <thead>
                <tr>
                  <th class="bd-channel">Канал</th>
                  {#each allRows as sc (sc.id)}
                    <th class="bd-sc">{sc.name}</th>
                  {/each}
                </tr>
              </thead>
              <tbody>
                {#each allChannels as ch}
                  <tr>
                    <td class="bd-channel">{ch}</td>
                    {#each allRows as sc (sc.id)}
                      {@const alloc = (sc.perChannelAllocation ?? {})[ch]}
                      <td class="bd-value">
                        {alloc != null ? `${(alloc * 100).toFixed(1)}%` : '-'}
                      </td>
                    {/each}
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>

          <!-- Delta vs baseline for selected scenario -->
          {#if selectedId && baseline && selectedChannelDiff.length > 0}
            <div class="delta-section">
              <p class="delta-title">
                Сдвиги: <strong>{scenarios.find(s => s.id === selectedId)?.name ?? ''}</strong>
                vs {baseline.name}
              </p>
              <div class="delta-bars">
                {#each selectedChannelDiff.filter(d => Math.abs(d.deltaPct) >= 1) as diff}
                  <div class="delta-row">
                    <span class="delta-ch">{diff.channel}</span>
                    <div class="delta-bar-wrap">
                      <div
                        class="delta-bar"
                        class:bar-pos={diff.deltaAbs > 0}
                        class:bar-neg={diff.deltaAbs < 0}
                        style="width: {Math.min(100, Math.abs(diff.deltaPct) * 2)}%"
                      ></div>
                    </div>
                    <span class="delta-val {diff.deltaAbs >= 0 ? 'positive' : 'negative'}">
                      {diff.deltaAbs >= 0 ? '+' : ''}{diff.deltaPct.toFixed(1)} пп
                    </span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        {/if}
      </div>
    </details>

    <!-- ── Diff Analysis Narratives ──────────────────────────────────────────── -->
    <div class="analysis-block" aria-label="Автоматический анализ сравнения">
      <h3 class="analysis-title">Анализ</h3>
      {#if narratives.length === 0}
        <p class="analysis-empty">Недостаточно данных для автоматического анализа.</p>
      {:else}
        <ul class="narrative-list">
          {#each narratives as line}
            <li class="narrative-item">{line}</li>
          {/each}
        </ul>
      {/if}
    </div>

    <!-- ── Actions Row ────────────────────────────────────────────────────────── -->
    <div class="actions-row" role="toolbar" aria-label="Действия со сценариями">

      <!-- Export ▾ -->
      <div class="dropdown-anchor">
        <button
          type="button"
          class="btn-action btn-primary"
          disabled={exportBusy}
          onclick={(e) => { e.stopPropagation(); exportOpen = !exportOpen; acceptOpen = false; duplicateOpen = false; deleteOpen = false; }}
          aria-haspopup="menu"
          aria-expanded={exportOpen}
        >
          <Download size={14} />
          {exportBusy ? 'Экспорт...' : 'Экспорт'}
          <ChevronDown size={12} />
        </button>
        {#if exportOpen}
          <ul class="dropdown-menu" role="menu">
            <li role="menuitem">
              <button type="button" onclick={handleExportCsv}>
                CSV - сравнение
              </button>
            </li>
            <li role="menuitem">
              <button type="button" onclick={handleExportExcel}>
                Excel (.xlsx) - сравнение
              </button>
            </li>
            <li role="menuitem">
              <button type="button" onclick={handleExportPptx}>
                Слайд PPTX
              </button>
            </li>
          </ul>
        {/if}
      </div>

      <!-- Accept as plan ▾ -->
      {#if onAccept}
        <div class="dropdown-anchor">
          <button
            type="button"
            class="btn-action btn-secondary"
            onclick={(e) => { e.stopPropagation(); acceptOpen = !acceptOpen; exportOpen = false; duplicateOpen = false; deleteOpen = false; }}
            aria-haspopup="menu"
            aria-expanded={acceptOpen}
          >
            <Save size={14} />
            Принять сценарий
            <ChevronDown size={12} />
          </button>
          {#if acceptOpen}
            <ul class="dropdown-menu" role="menu">
              {#each scenarios as sc (sc.id)}
                <li role="menuitem">
                  <button type="button" onclick={() => handleAccept(sc)}>
                    {sc.name}
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}

      <!-- Duplicate ▾ -->
      {#if onDuplicate}
        <div class="dropdown-anchor">
          <button
            type="button"
            class="btn-action btn-ghost"
            onclick={(e) => { e.stopPropagation(); duplicateOpen = !duplicateOpen; exportOpen = false; acceptOpen = false; deleteOpen = false; }}
            aria-haspopup="menu"
            aria-expanded={duplicateOpen}
          >
            <Copy size={14} />
            Дублировать
            <ChevronDown size={12} />
          </button>
          {#if duplicateOpen}
            <ul class="dropdown-menu" role="menu">
              {#each scenarios as sc (sc.id)}
                <li role="menuitem">
                  <button type="button" onclick={() => handleDuplicate(sc)}>
                    {sc.name}
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}

      <!-- Delete ▾ -->
      {#if onDelete}
        <div class="dropdown-anchor">
          <button
            type="button"
            class="btn-action btn-danger"
            onclick={(e) => { e.stopPropagation(); deleteOpen = !deleteOpen; exportOpen = false; acceptOpen = false; duplicateOpen = false; }}
            aria-haspopup="menu"
            aria-expanded={deleteOpen}
          >
            <Trash2 size={14} />
            Удалить
            <ChevronDown size={12} />
          </button>
          {#if deleteOpen}
            <ul class="dropdown-menu role-danger" role="menu">
              {#each scenarios as sc (sc.id)}
                <li role="menuitem">
                  <button type="button" class="item-danger" onclick={() => handleDelete(sc)}>
                    {sc.name}
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}

      <!-- Export status message -->
      {#if exportStatus}
        <p class="export-status" role="status" aria-live="polite">{exportStatus}</p>
      {/if}
    </div>
  {/if}
</section>

<style>
  /* ── Page shell ─────────────────────────────────────────────────────────── */
  .multi-scenario-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1280px;
    margin: 0 auto;
    width: 100%;
  }

  /* ── Header ─────────────────────────────────────────────────────────────── */
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .page-title-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  :global(.title-icon) {
    color: var(--accent-primary, #3b82f6);
  }

  .page-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin: 0;
  }

  .scenario-count {
    font-size: 11px;
    color: var(--text-muted, #7A7A90);
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 20px;
    padding: 2px 8px;
  }

  /* ── Empty / single states ───────────────────────────────────────────────── */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 240px;
    gap: 12px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    padding: 32px;
    text-align: center;
    color: var(--text-secondary);
  }

  .empty-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }

  .empty-body {
    font-size: 13px;
    color: var(--text-secondary);
    max-width: 400px;
    line-height: 1.6;
    margin: 0;
  }

  .single-state {
    padding: 16px 20px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, var(--bg-card, #181824));
    border: 1px solid color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    border-radius: var(--radius-card, 12px);
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
  }

  .single-state p { margin: 0; }

  /* ── Chart block ─────────────────────────────────────────────────────────── */
  .chart-block {
    width: 100%;
  }

  /* ── Comparison Table ────────────────────────────────────────────────────── */
  .table-block {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    overflow: hidden;
  }

  .table-scroll {
    overflow-x: auto;
  }

  .comparison-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
  }

  .comparison-table thead th {
    background: var(--bg-secondary, #141420);
    color: var(--text-secondary, #94a3b8);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 8px 12px;
    text-align: left;
    white-space: nowrap;
    border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
  }

  .comparison-table thead th.sortable {
    cursor: pointer;
    user-select: none;
  }

  .comparison-table thead th.sortable:hover {
    color: var(--text-primary);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 8%, var(--bg-secondary, #141420));
  }

  .comparison-table tbody tr {
    transition: background 0.12s;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.04));
  }

  .comparison-table tbody tr:last-child {
    border-bottom: none;
  }

  .comparison-table tbody tr:hover {
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  }

  .comparison-table tbody tr.selected-row {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
    border-left: 2px solid var(--accent-primary, #3b82f6);
  }

  .comparison-table tbody tr.baseline-row {
    border-left: 2px solid var(--border-subtle, rgba(255,255,255,0.1));
  }

  .comparison-table td {
    padding: 9px 12px;
    color: var(--text-primary);
    white-space: nowrap;
    vertical-align: middle;
  }

  .col-check { width: 28px; padding: 0 8px 0 12px !important; }

  .row-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border, rgba(255,255,255,0.12));
    transition: background 0.15s;
  }

  .row-dot.dot-selected {
    background: var(--accent-primary, #3b82f6);
  }

  .sc-name {
    font-weight: 500;
    color: var(--text-primary);
  }

  .badge-baseline {
    margin-left: 6px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted, #7A7A90);
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 3px;
    padding: 1px 5px;
  }

  /* A3/OPP-03: бейдж экстраполяции сценария (warn tier; severity>=2 — danger). */
  .badge-extrapolation {
    margin-left: 6px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--warning, #fbbf24);
    background: color-mix(in srgb, var(--warning, #fbbf24) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #fbbf24) 35%, transparent);
    border-radius: 3px;
    padding: 1px 5px;
    cursor: help;
    white-space: nowrap;
  }
  .badge-extrapolation.critical {
    color: var(--danger, #ef4444);
    background: color-mix(in srgb, var(--danger, #ef4444) 10%, transparent);
    border-color: color-mix(in srgb, var(--danger, #ef4444) 35%, transparent);
  }

  .col-kpi strong {
    color: var(--text-primary);
    font-weight: 600;
    font-size: 13px;
  }

  .col-ci { color: var(--text-muted, #7A7A90) !important; font-size: 11.5px; }

  .col-uplift.positive { color: #10b981 !important; font-weight: 600; }
  .col-uplift.negative { color: #ef4444 !important; font-weight: 600; }

  /* ── Per-channel Breakdown ───────────────────────────────────────────────── */
  .breakdown-block {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    overflow: hidden;
  }

  .breakdown-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 11px 16px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    cursor: pointer;
    user-select: none;
    list-style: none;
    transition: background 0.12s;
  }

  .breakdown-summary:hover {
    background: color-mix(in srgb, var(--text-primary) 4%, transparent);
  }

  :global(.chevron-icon) {
    transition: transform 0.2s;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  details[open] :global(.chevron-icon) {
    transform: rotate(180deg);
  }

  .channel-count {
    font-size: 10px;
    color: var(--text-muted, #7A7A90);
    background: var(--bg-secondary, #141420);
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    border-radius: 10px;
    padding: 1px 6px;
    margin-left: auto;
  }

  .breakdown-content {
    padding: 0 16px 16px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }

  .breakdown-empty {
    color: var(--text-muted, #7A7A90);
    font-size: 12.5px;
    padding: 12px 0;
    margin: 0;
  }

  .breakdown-scroll { overflow-x: auto; }

  .breakdown-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin-top: 12px;
  }

  .breakdown-table thead th {
    color: var(--text-secondary, #94a3b8);
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 5px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    white-space: nowrap;
  }

  .breakdown-table td {
    padding: 5px 10px;
    color: var(--text-primary);
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.03));
    white-space: nowrap;
  }

  .bd-channel {
    font-weight: 500;
    min-width: 100px;
  }

  .bd-value { text-align: right; }

  /* Delta bars */
  .delta-section {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
  }

  .delta-title {
    font-size: 11.5px;
    color: var(--text-secondary);
    margin: 0 0 10px;
  }

  .delta-bars {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .delta-row {
    display: grid;
    grid-template-columns: 100px 1fr 70px;
    align-items: center;
    gap: 8px;
  }

  .delta-ch {
    font-size: 11.5px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .delta-bar-wrap {
    height: 6px;
    background: color-mix(in srgb, var(--text-primary) 6%, transparent);
    border-radius: 3px;
    overflow: hidden;
  }

  .delta-bar {
    height: 100%;
    border-radius: 3px;
    min-width: 2px;
    transition: width 0.25s ease-out;
  }

  .delta-bar.bar-pos { background: #10b981; }
  .delta-bar.bar-neg { background: #ef4444; }

  .delta-val {
    font-size: 11px;
    font-weight: 600;
    text-align: right;
    white-space: nowrap;
  }

  .delta-val.positive { color: #10b981; }
  .delta-val.negative { color: #ef4444; }

  /* ── Diff Analysis ──────────────────────────────────────────────────────── */
  .analysis-block {
    background: color-mix(in srgb, var(--gold, #c9a449) 5%, var(--bg-card, #0f172a));
    border: 1px solid color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
    border-radius: var(--radius-card, 12px);
    padding: 16px 20px;
  }

  .analysis-title {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--gold, #c9a449);
    margin: 0 0 10px;
  }

  .analysis-empty {
    font-size: 12.5px;
    color: var(--text-muted, #7A7A90);
    margin: 0;
  }

  .narrative-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  .narrative-item {
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
    padding-left: 16px;
    position: relative;
  }

  .narrative-item::before {
    content: '•';
    position: absolute;
    left: 2px;
    color: var(--gold, #c9a449);
    font-size: 14px;
    line-height: 1.3;
  }

  /* ── Actions row ────────────────────────────────────────────────────────── */
  .actions-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .export-status {
    font-size: 11.5px;
    color: var(--text-secondary);
    margin: 0;
    padding: 4px 8px;
    background: var(--bg-secondary, #141420);
    border-radius: 5px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── Dropdown shared ───────────────────────────────────────────────────── */
  .dropdown-anchor {
    position: relative;
  }

  .dropdown-menu {
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    z-index: 50;
    background: var(--bg-secondary, #1a1a2e);
    border: 1px solid var(--border, rgba(255,255,255,0.12));
    border-radius: var(--radius-sm, 8px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    padding: 4px 0;
    margin: 0;
    list-style: none;
    min-width: 180px;
    white-space: nowrap;
  }

  .dropdown-menu li { margin: 0; }

  .dropdown-menu button {
    width: 100%;
    background: none;
    border: none;
    color: var(--text-primary);
    font: inherit;
    font-size: 12.5px;
    padding: 7px 14px;
    text-align: left;
    cursor: pointer;
    transition: background 0.1s;
  }

  .dropdown-menu button:hover {
    background: color-mix(in srgb, var(--text-primary) 8%, transparent);
  }

  .dropdown-menu button.item-danger { color: #ef4444; }
  .dropdown-menu button.item-danger:hover {
    background: color-mix(in srgb, #ef4444 12%, transparent);
  }

  /* ── Buttons ────────────────────────────────────────────────────────────── */
  .btn-action {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px;
    border-radius: var(--radius-sm, 8px);
    font: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
    transition: opacity 0.15s, transform 0.1s, background 0.15s;
    white-space: nowrap;
  }

  .btn-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-action:active:not(:disabled) { transform: scale(0.97); }

  .btn-primary {
    background: var(--accent-primary, #3b82f6);
    color: #fff;
    border-color: transparent;
  }

  .btn-primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 85%, white);
  }

  .btn-secondary {
    background: color-mix(in srgb, var(--gold, #c9a449) 12%, var(--bg-card, #181824));
    color: var(--gold, #c9a449);
    border-color: color-mix(in srgb, var(--gold, #c9a449) 35%, transparent);
  }

  .btn-secondary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--gold, #c9a449) 20%, var(--bg-card, #181824));
  }

  .btn-ghost {
    background: var(--bg-secondary, #141420);
    color: var(--text-secondary);
    border-color: var(--border, rgba(255,255,255,0.08));
  }

  .btn-ghost:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text-primary) 8%, var(--bg-secondary, #141420));
    color: var(--text-primary);
  }

  .btn-danger {
    background: color-mix(in srgb, #ef4444 10%, var(--bg-card, #181824));
    color: #ef4444;
    border-color: color-mix(in srgb, #ef4444 30%, transparent);
  }

  .btn-danger:hover:not(:disabled) {
    background: color-mix(in srgb, #ef4444 18%, var(--bg-card, #181824));
  }

  /* ── Positive / Negative colors (reused in table) ─────────────────────── */
  .positive { color: #10b981; }
  .negative { color: #ef4444; }
</style>
