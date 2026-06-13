<script>
  /**
   * MultiScenarioChart - N-scenario overlay extension of ContinuationChart.
   *
   * Renders a baseline line + up to N scenario lines, each with:
   *   - CI 90% ribbon (area-between low/high bands)
   *   - Endpoint labels (value + scenario name)
   *   - Alternating solid/dashed line styles for colorblind accessibility
   *   - Clickable legend to toggle individual scenarios
   *   - Dark hover tooltip per-period
   *
   * Per WIZARD_FLOW_v2_FINAL.md §4.2, §13 Q-fin-4 (limit 5 on chart).
   * Extension of ContinuationChart.svelte pattern.
   *
   * @component MultiScenarioChart
   */

  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import ExpandableCard from '$lib/components/ExpandableCard.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { compactNum, buildForecastTooltip, forecastLegendLabel } from '$lib/forecast-chart-format.js';
  import { Info } from 'lucide-svelte';

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
   * }} Scenario
   */

  /**
   * @type {{
   *   scenarios: Scenario[],
   *   baseline?: Scenario | null,
   *   maxVisible?: number,
   *   kpiLabel?: string,
   * }}
   */
  const {
    scenarios = [],
    baseline = null,
    maxVisible = 5,
    kpiLabel = 'KPI',
  } = $props();

  /**
   * 5 distinct Aurora scenario colors, per spec.
   * Alternating solid (1,3,5) + dashed (2,4) for colorblind accessibility.
   */
  const SCENARIO_COLORS = [
    '#10b981', // emerald - scenario 1
    '#3b82f6', // blue    - scenario 2
    '#f59e0b', // amber   - scenario 3
    '#8b5cf6', // violet  - scenario 4
    '#ef4444', // red     - scenario 5
  ];

  /** Baseline is always grey-slate */
  const BASELINE_COLOR = '#94a3b8';

  /** Scenarios visible on chart (capped at maxVisible) */
  const visibleScenarios = $derived(scenarios.slice(0, maxVisible));
  const hiddenCount = $derived(Math.max(0, scenarios.length - maxVisible));

  /**
   * Build full combined dates timeline.
   * Uses baseline dates if available, otherwise first scenario dates.
   * @type {string[]}
   */
  const allDates = $derived.by(() => {
    const baseDates = baseline?.dates ?? [];
    const firstScDates = visibleScenarios[0]?.dates ?? [];
    const histDates = baseDates.length > 0 ? baseDates : firstScDates;
    if (visibleScenarios.length === 0) return histDates;

    // Merge: history dates + any forecast dates not already in history
    const histSet = new Set(histDates);
    /** @type {string[]} */
    const extraDates = [];
    for (const sc of visibleScenarios) {
      for (const d of (sc.dates ?? [])) {
        if (!histSet.has(d)) {
          extraDates.push(d);
          histSet.add(d); // prevent duplicates across scenarios
        }
      }
    }
    // Sort combined dates
    const combined = [...histDates, ...extraDates];
    combined.sort();
    return combined;
  });

  /** Заголовок карточки (текст важен для тестов: «{kpiLabel} - Сравнение сценариев»). */
  const chartTitle = $derived(`${kpiLabel} - Сравнение сценариев`);

  /**
   * Align a series' own dates to the global allDates index, filling gaps with null.
   * @param {string[]} seriesDates
   * @param {number[]} values
   * @returns {(number | null)[]}
   */
  function alignToTimeline(seriesDates, values) {
    const dateIdx = new Map(allDates.map((d, i) => [d, i]));
    const result = /** @type {(number | null)[]} */ (new Array(allDates.length).fill(null));
    seriesDates.forEach((d, i) => {
      const idx = dateIdx.get(d);
      if (idx !== undefined) result[idx] = values[i] ?? null;
    });
    return result;
  }

  /** Cutoff index = end of baseline series (where actual data ends) */
  const cutoffIndex = $derived.by(() => {
    const baseDates = baseline?.dates ?? [];
    if (baseDates.length === 0) return -1;
    const lastBaseDate = baseDates[baseDates.length - 1];
    const idx = allDates.indexOf(lastBaseDate);
    return idx >= 0 ? idx : allDates.length - 1;
  });

  /** Build ECharts option reactive to all inputs */
  const option = $derived.by(() => {
    if (allDates.length === 0) return {};

    /** @type {import('echarts').SeriesOption[]} */
    const series = [];

    // ── Baseline line (grey, solid thick) ──────────────────────────────────────
    if (baseline) {
      const baseAligned = alignToTimeline(baseline.dates ?? [], baseline.predictions ?? []);
      series.push({
        name: baseline.name,
        type: 'line',
        data: baseAligned,
        lineStyle: { color: BASELINE_COLOR, width: 2, type: 'solid' },
        itemStyle: { color: BASELINE_COLOR },
        symbol: 'none',
        connectNulls: true,
        z: 4,
        endLabel: {
          show: true,
          formatter: (/** @type {any} */ p) => compactNum(p.value),
          color: BASELINE_COLOR,
          fontSize: 10,
          fontWeight: 600,
          distance: 4,
        },
      });
    }

    // ── Scenario series + CI ribbons ─────────────────────────────────────────────
    visibleScenarios.forEach((sc, i) => {
      const color = SCENARIO_COLORS[i % SCENARIO_COLORS.length];
      // Alternating solid (0,2,4 = scenarios 1,3,5) + dashed (1,3 = scenarios 2,4)
      const lineType = i % 2 === 0 ? 'solid' : 'dashed';
      const aligned = alignToTimeline(sc.dates ?? [], sc.predictions ?? []);

      // CI bands - only if per-period arrays provided
      const ciLowArr = sc.ciLowSeries;
      const ciHighArr = sc.ciHighSeries;

      if (ciLowArr?.length && ciHighArr?.length) {
        const ciLowAligned = alignToTimeline(sc.dates ?? [], ciLowArr);
        const ciHighAligned = alignToTimeline(sc.dates ?? [], ciHighArr);

        // Lower bound - invisible baseline for area fill
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

        // Upper bound - fills down to ci_low with semi-transparent area
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

      // Main scenario line
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

    // ── Cutoff vertical dashed line ──────────────────────────────────────────────
    if (cutoffIndex >= 0 && cutoffIndex < allDates.length) {
      series.push(/** @type {any} */ ({
        name: '_cutoff_',
        type: 'line',
        data: [],
        showInLegend: false,
        silent: true,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ xAxis: cutoffIndex }],
          lineStyle: { color: 'rgba(255,255,255,0.3)', type: 'dashed', width: 1 },
          label: {
            show: true,
            position: 'insideEndTop',
            color: 'rgba(255,255,255,0.45)',
            fontSize: 10,
            formatter: 'Прогноз →',
          },
        },
      }));
    }

    // Legend items: baseline (if any) + scenario names
    const legendData = [
      ...(baseline ? [baseline.name] : []),
      ...visibleScenarios.map(sc => sc.name),
    ];

    const chartHeight = allDates.length > 40 ? '360px' : '300px';

    return {
      backgroundColor: 'transparent',
      grid: { left: '56px', right: '90px', top: '44px', bottom: '44px' },
      legend: {
        top: 4,
        left: 'left',
        icon: 'roundRect',
        itemWidth: 18,
        itemHeight: 4,
        itemGap: 16,
        textStyle: { color: '#cbd5e1', fontSize: 11 },
        inactiveColor: 'rgba(255,255,255,0.25)',
        data: legendData,
        // Легенда показывает итоговый прогноз каждого сценария (endpoint) — быстрый ранг.
        formatter: (/** @type {string} */ name) =>
          forecastLegendLabel(name, { baseline, visibleScenarios }),
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
      tooltip: {
        ...chartTooltipDark({ trigger: 'axis' }),
        axisPointer: { type: 'line', lineStyle: { color: 'rgba(255,255,255,0.22)', type: 'dashed' } },
        extraCssText: 'max-width:320px;',
        // Богатый тултип (forecast-chart-format.js): дата + метка история/прогноз +
        // строка на серию (маркер, значение, ДИ 90% веера). Helper-серии CI — только источник границ.
        formatter: (/** @type {any} */ rawParams) => buildForecastTooltip(rawParams, {
          baseline, visibleScenarios, allDates, cutoffIndex,
          baselineColor: BASELINE_COLOR, scenarioColors: SCENARIO_COLORS,
        }),
      },
      series,
      _chartHeight: chartHeight, // stored for height reactive binding below
    };
  });

  /** Chart height derived from data length */
  const chartHeight = $derived(allDates.length > 40 ? '360px' : '300px');
</script>

<div class="ms-chart-root">
  {#if hiddenCount > 0}
    <div class="overflow-warn" role="alert">
      <Info size={12} />
      <span>На графике первые {maxVisible} из {scenarios.length} - остальные только в таблице</span>
    </div>
  {/if}

  <!-- ExpandableCard: кнопка «развернуть на весь экран» (как в других графиках проекта).
       EChartBase — единственный потомок children → overlay-content 70vh подхватывается
       ResizeObserver'ом ECharts, график растягивается в fullscreen. -->
  <ExpandableCard title={chartTitle}>
    {#if allDates.length === 0 || (scenarios.length === 0 && !baseline)}
      <div class="empty-state">
        <p>Нет данных для отображения</p>
      </div>
    {:else}
      <EChartBase option={option} height={chartHeight} />
    {/if}
  </ExpandableCard>
</div>

<style>
  .ms-chart-root {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
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
    min-height: 180px;
    color: var(--text-secondary);
    font-size: 13px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-radius: 8px;
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.08));
  }

  .empty-state p { margin: 0; }
</style>
