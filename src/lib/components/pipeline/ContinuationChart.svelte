<script>
  /**
   * ContinuationChart - main forecast visualization for Phase C.
   *
   * Historical actuals + model fit line + N scenario lines with CI ribbons.
   * Vertical cutoff dashed line, endpoint labels on scenario tails,
   * clickable legend (toggle visibility), per-period hover tooltip.
   *
   * Per WIZARD_FLOW_v2_FINAL.md §3.3.
   *
   * Uses ECharts (existing dep) via EChartBase wrapper.
   * D1: lazy-loaded; P4: step-aware.
   *
   * @component ContinuationChart
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { Info } from 'lucide-svelte';

  /**
   * @typedef {{
   *   name: string,
   *   dates: string[],
   *   predictions: number[],
   *   ciLow?: number[],
   *   ciHigh?: number[],
   *   color?: string,
   *   style?: 'solid' | 'dashed' | 'dotted',
   * }} ScenarioDef
   */

  /**
   * @type {{
   *   historical: { dates: string[], actuals: number[] },
   *   modelFit?: { dates: string[], predictions: number[] } | null,
   *   scenarios?: ScenarioDef[],
   *   cutoffIndex?: number,
   *   kpiLabel?: string,
   *   maxScenarios?: number,
   * }}
   */
  const {
    historical = { dates: [], actuals: [] },
    modelFit = null,
    scenarios = [],
    cutoffIndex = -1,
    kpiLabel = 'KPI',
    maxScenarios = 5,
  } = $props();

  /** Scenario colors fallback palette */
  const SCENARIO_COLORS = [
    '#3b82f6', '#a855f7', '#f59e0b', '#10b981', '#ec4899',
    '#06b6d4', '#f97316', '#84cc16',
  ];

  /** Visible scenarios (capped at maxScenarios) */
  const visibleScenarios = $derived(scenarios.slice(0, maxScenarios));
  const hiddenCount = $derived(Math.max(0, scenarios.length - maxScenarios));

  /**
   * Build full combined dates timeline: historical + forecast (from first scenario).
   * @type {string[]}
   */
  const allDates = $derived.by(() => {
    const hist = historical.dates ?? [];
    if (visibleScenarios.length === 0) return hist;
    const forecastDates = visibleScenarios[0].dates ?? [];
    // Deduplicate: forecast may overlap last historical point
    const cutDate = hist[hist.length - 1];
    const extraDates = forecastDates.filter(d => d !== cutDate);
    return [...hist, ...extraDates];
  });

  /** Compact Y-axis number formatter (K/M/B) */
  function compactNum(/** @type {number} */ v) {
    if (!Number.isFinite(v)) return '';
    const abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return (v / 1e6).toFixed(0) + 'M';
    if (abs >= 1e3) return (v / 1e3).toFixed(0) + 'K';
    return Math.round(v).toLocaleString('ru-RU');
  }

  /**
   * Map a series' own dates to allDates index positions, filling nulls.
   * @param {string[]} seriesDates
   * @param {number[]} values
   * @returns {(number | null)[]}
   */
  function alignToTimeline(seriesDates, values) {
    const dateIdx = new Map(allDates.map((d, i) => [d, i]));
    const result = new Array(allDates.length).fill(null);
    seriesDates.forEach((d, i) => {
      const idx = dateIdx.get(d);
      if (idx !== null && idx !== undefined) result[idx] = values[i] ?? null;
    });
    return result;
  }

  /**
   * Effective cutoff index in allDates.
   * If not passed, use end of historical.dates.
   */
  const effectiveCutoff = $derived.by(() => {
    if (cutoffIndex >= 0 && cutoffIndex < allDates.length) return cutoffIndex;
    const hl = historical.dates?.length ?? 0;
    return hl > 0 ? hl - 1 : -1;
  });

  /** Build ECharts option */
  const option = $derived.by(() => {
    if (!allDates.length) return {};

    /** @type {import('echarts').SeriesOption[]} */
    const series = [];

    // ── Actual (orange solid thick) ──────────────────────────────────────────
    series.push({
      name: 'Факт',
      type: 'line',
      data: alignToTimeline(historical.dates ?? [], historical.actuals ?? []),
      lineStyle: { color: '#f97316', width: 2.5 },
      itemStyle: { color: '#f97316' },
      symbol: 'none',
      connectNulls: false,
      z: 10,
    });

    // ── Model fit (dark grey medium) ─────────────────────────────────────────
    if (modelFit?.dates?.length) {
      series.push({
        name: 'Подгонка модели',
        type: 'line',
        data: alignToTimeline(modelFit.dates, modelFit.predictions),
        lineStyle: { color: '#64748b', width: 1.5, type: 'solid' },
        itemStyle: { color: '#64748b' },
        symbol: 'none',
        connectNulls: true,
        z: 9,
      });
    }

    // ── Scenario series + CI ribbons ─────────────────────────────────────────
    visibleScenarios.forEach((sc, i) => {
      const color = sc.color ?? SCENARIO_COLORS[i % SCENARIO_COLORS.length];
      const lineType = (sc.style === 'dashed' || (!sc.style && i % 2 === 1)) ? 'dashed' : 'solid';
      const aligned = alignToTimeline(sc.dates ?? [], sc.predictions ?? []);

      // CI low band (invisible — used only as lower bound for area-between)
      if (sc.ciLow?.length && sc.ciHigh?.length) {
        const ciLowAligned = alignToTimeline(sc.dates ?? [], sc.ciLow);
        series.push(/** @type {any} */ ({
          name: `${sc.name}_ci_low`,
          type: 'line',
          data: ciLowAligned,
          lineStyle: { color: 'transparent', width: 0 },
          itemStyle: { color: 'transparent' },
          symbol: 'none',
          connectNulls: true,
          legendHoverLink: false,
          silent: true,
          showInLegend: false,
          z: 1,
        }));

        // CI high band — fills down to ci_low series
        const ciHighAligned = alignToTimeline(sc.dates ?? [], sc.ciHigh);
        series.push(/** @type {any} */ ({
          name: `${sc.name}_ci_high`,
          type: 'line',
          data: ciHighAligned,
          lineStyle: { color: 'transparent', width: 0 },
          itemStyle: { color: 'transparent' },
          symbol: 'none',
          connectNulls: true,
          areaStyle: { color, opacity: 0.10 },
          showInLegend: false,
          z: 2,
        }));
      }

      // Scenario main line
      series.push({
        name: sc.name,
        type: 'line',
        data: aligned,
        lineStyle: { color, width: 2, type: /** @type {any} */ (lineType) },
        itemStyle: { color },
        symbol: 'none',
        connectNulls: true,
        z: 5 + i,
        endLabel: {
          show: true,
          formatter: (/** @type {any} */ p) => compactNum(p.value),
          color,
          fontSize: 10,
          fontWeight: 600,
          distance: 4,
        },
      });
    });

    // ── Cutoff mark line ─────────────────────────────────────────────────────
    if (effectiveCutoff >= 0 && effectiveCutoff < allDates.length) {
      series.push(/** @type {any} */ ({
        name: '_cutoff_',
        type: 'line',
        data: [],
        showInLegend: false,
        silent: true,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ xAxis: effectiveCutoff }],
          lineStyle: { color: 'rgba(255,255,255,0.35)', type: 'dashed', width: 1 },
          label: {
            show: true,
            position: 'insideEndTop',
            color: 'rgba(255,255,255,0.5)',
            fontSize: 10,
            formatter: 'Дата отсечки',
          },
        },
      }));
    }

    return {
      backgroundColor: 'transparent',
      grid: { left: '56px', right: '80px', top: '40px', bottom: '44px' },
      legend: {
        top: 4,
        left: 'left',
        icon: 'roundRect',
        itemWidth: 14,
        itemHeight: 4,
        textStyle: { color: '#94a3b8', fontSize: 10 },
        // Only scenario + Факт + Подгонка in legend (filter CI series)
        data: [
          'Факт',
          ...(modelFit ? ['Подгонка модели'] : []),
          ...visibleScenarios.map(sc => sc.name),
        ],
      },
      xAxis: {
        type: 'category',
        data: allDates,
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          rotate: allDates.length > 24 ? 35 : 0,
          interval: Math.max(0, Math.floor(allDates.length / 14) - 1),
        },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: kpiLabel,
        nameTextStyle: { color: '#94a3b8', fontSize: 10, align: 'right' },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          formatter: compactNum,
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        axisLine: { show: false },
      },
      tooltip: chartTooltipDark({ trigger: 'axis' }),
      series,
    };
  });

  /** Chart height based on data size */
  const chartHeight = $derived(allDates.length > 40 ? '340px' : '280px');
</script>

<div class="continuation-chart">
  <div class="chart-header">
    <h3 class="chart-title">{kpiLabel} — Прогноз по сценариям</h3>
    {#if hiddenCount > 0}
      <div class="overflow-warn" role="alert">
        <Info size={12} />
        <span>Показаны первые {maxScenarios} из {scenarios.length} сценариев — toggle через legend</span>
      </div>
    {/if}
  </div>

  {#if allDates.length === 0}
    <div class="empty-state">
      <p>Нет данных для отображения</p>
    </div>
  {:else}
    <EChartBase option={option} height={chartHeight} />
  {/if}
</div>

<style>
  .continuation-chart {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    padding: 16px 18px 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .chart-header {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .chart-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    flex: 1;
    letter-spacing: 0.01em;
  }

  .overflow-warn {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--warning, #F59E0B);
    background: color-mix(in srgb, var(--warning, #F59E0B) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #F59E0B) 30%, transparent);
    border-radius: 5px;
    padding: 3px 8px;
    white-space: nowrap;
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 160px;
    color: var(--text-secondary);
    font-size: 13px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-radius: 8px;
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.08));
  }

  .empty-state p { margin: 0; }
</style>
