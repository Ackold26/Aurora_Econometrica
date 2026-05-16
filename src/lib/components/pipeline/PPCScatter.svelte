<script>
  /**
   * PPCScatter - Posterior Predictive Check scatter + residuals.
   *
   * Left panel: Actual vs Predicted scatter (diagonal 45° reference, R² label,
   * points colored by recency gradient).
   * Right panel: Residuals over time (zero baseline, mean ± 2σ band,
   * Durbin-Watson statistic label).
   *
   * Per WIZARD_FLOW_v2_FINAL.md §6.3.
   *
   * @component PPCScatter
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';

  /**
   * @type {{
   *   ppcData: {
   *     actual: number[],
   *     predicted: number[],
   *     residuals?: number[],
   *     r2?: number,
   *     durbin_watson?: number,
   *   } | null,
   * }}
   */
  const { ppcData = null } = $props();

  // ── Derived statistics ───────────────────────────────────────────────────────

  const residuals = $derived.by(() => {
    if (!ppcData) return [];
    if (ppcData.residuals?.length) return ppcData.residuals;
    return (ppcData.actual ?? []).map((a, i) => a - (ppcData.predicted?.[i] ?? 0));
  });

  const residualStats = $derived.by(() => {
    const r = residuals;
    if (!r.length) return { mean: 0, std: 0 };
    const mean = r.reduce((s, v) => s + v, 0) / r.length;
    const variance = r.reduce((s, v) => s + (v - mean) ** 2, 0) / r.length;
    return { mean, std: Math.sqrt(variance) };
  });

  const r2Label = $derived(
    ppcData?.r2 != null ? `R² = ${Number(ppcData.r2).toFixed(3)}` : ''
  );

  const dwLabel = $derived(
    ppcData?.durbin_watson != null
      ? `DW = ${Number(ppcData.durbin_watson).toFixed(2)}`
      : ''
  );

  /**
   * Build color for scatter points: gradient from old (muted blue) to recent (bright orange).
   * @param {number} idx
   * @param {number} total
   * @returns {string}
   */
  function recencyColor(idx, total) {
    const t = total > 1 ? idx / (total - 1) : 0;
    // Interpolate: #3b82f6 (old) → #f97316 (recent)
    const r = Math.round(59 + (249 - 59) * t);
    const g = Math.round(130 + (115 - 130) * t);
    const b = Math.round(246 + (22 - 246) * t);
    return `rgb(${r},${g},${b})`;
  }

  // ── Left chart: Actual vs Predicted scatter ────────────────────────────────

  const scatterOption = $derived.by(() => {
    if (!ppcData?.actual?.length || !ppcData?.predicted?.length) return {};

    const actual = ppcData.actual;
    const predicted = ppcData.predicted;
    const n = Math.min(actual.length, predicted.length);

    const scatterData = Array.from({ length: n }, (_, i) => ({
      value: [predicted[i], actual[i]],
      itemStyle: { color: recencyColor(i, n), opacity: 0.8 },
    }));

    // 45° reference line: from min to max
    const allVals = [...actual, ...predicted].filter(Number.isFinite);
    const minV = Math.min(...allVals);
    const maxV = Math.max(...allVals);

    return {
      backgroundColor: 'transparent',
      grid: { left: '52px', right: '16px', top: '32px', bottom: '40px' },
      title: {
        text: 'Факт vs Прогноз',
        subtext: r2Label,
        left: 'center',
        top: 2,
        textStyle: { color: '#94a3b8', fontSize: 11, fontWeight: 600 },
        subtextStyle: { color: '#10b981', fontSize: 10 },
      },
      xAxis: {
        type: 'value',
        name: 'Прогноз',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#94a3b8', fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      },
      yAxis: {
        type: 'value',
        name: 'Факт',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#94a3b8', fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(15,18,28,0.94)',
        borderColor: 'rgba(255,255,255,0.14)',
        textStyle: { color: '#fff', fontSize: 11 },
        formatter: (/** @type {any} */ p) => {
          const [pred, act] = p.value;
          const idx = p.dataIndex;
          return `<b>Наблюдение #${idx + 1}</b><br/>
Факт: ${Math.round(act).toLocaleString('ru-RU')}<br/>
Прогноз: ${Math.round(pred).toLocaleString('ru-RU')}<br/>
Отклонение: ${Math.round(act - pred).toLocaleString('ru-RU')}`;
        },
      },
      series: /** @type {any[]} */ ([
        // Diagonal reference line y=x
        {
          name: 'Идеальная подгонка',
          type: 'line',
          data: [[minV, minV], [maxV, maxV]],
          lineStyle: { color: 'rgba(255,255,255,0.25)', type: 'dashed', width: 1 },
          itemStyle: { opacity: 0 },
          symbol: 'none',
          showInLegend: false,
          silent: true,
          z: 1,
        },
        // Scatter points
        {
          name: 'Наблюдения',
          type: 'scatter',
          data: scatterData,
          symbolSize: 5,
          z: 5,
          showInLegend: false,
        },
      ]),
    };
  });

  // ── Right chart: Residuals over time ─────────────────────────────────────────

  const residualsOption = $derived.by(() => {
    const r = residuals;
    if (!r.length) return {};

    const { mean, std } = residualStats;
    const indices = r.map((_, i) => i + 1);
    const bandHigh = r.map(() => mean + 2 * std);
    const bandLow  = r.map(() => mean - 2 * std);

    return {
      backgroundColor: 'transparent',
      grid: { left: '52px', right: '16px', top: '32px', bottom: '40px' },
      title: {
        text: 'Остатки',
        subtext: dwLabel,
        left: 'center',
        top: 2,
        textStyle: { color: '#94a3b8', fontSize: 11, fontWeight: 600 },
        subtextStyle: { color: '#94a3b8', fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: indices,
        name: 'Период',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 9,
          interval: Math.max(0, Math.floor(r.length / 10) - 1),
        },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: 'Остаток',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: { color: '#94a3b8', fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLine: { show: false },
      },
      tooltip: chartTooltipDark({ trigger: 'axis' }),
      series: /** @type {any[]} */ ([
        // Mean ± 2σ band - high bound (invisible anchor)
        {
          name: 'mean+2σ',
          type: 'line',
          data: bandHigh,
          lineStyle: { color: 'transparent' },
          itemStyle: { opacity: 0 },
          symbol: 'none',
          showInLegend: false,
          silent: true,
          stack: 'sigma_band',
          z: 1,
        },
        // Band fill (high - low → displayed as area above low)
        {
          name: 'mean±2σ',
          type: 'line',
          data: bandHigh.map((h, i) => h - bandLow[i]),
          lineStyle: { color: 'transparent' },
          itemStyle: { opacity: 0 },
          symbol: 'none',
          areaStyle: { color: 'rgba(147,197,253,0.12)' },
          stack: 'sigma_band',
          z: 2,
        },
        // Zero baseline
        {
          name: 'zero',
          type: 'line',
          data: r.map(() => 0),
          lineStyle: { color: 'rgba(255,255,255,0.22)', type: 'dashed', width: 1 },
          itemStyle: { opacity: 0 },
          symbol: 'none',
          showInLegend: false,
          silent: true,
          z: 3,
        },
        // Mean residual line
        {
          name: `Среднее (${mean > 0 ? '+' : ''}${mean.toFixed(0)})`,
          type: 'line',
          data: r.map(() => mean),
          lineStyle: { color: '#f59e0b', type: 'dashed', width: 1 },
          itemStyle: { opacity: 0 },
          symbol: 'none',
          showInLegend: false,
          silent: true,
          z: 4,
        },
        // Residual line
        {
          name: 'Остаток',
          type: 'line',
          data: r,
          lineStyle: { color: '#a78bfa', width: 1.5 },
          itemStyle: { color: '#a78bfa' },
          symbol: 'circle',
          symbolSize: 3,
          z: 6,
          showInLegend: false,
        },
      ]),
    };
  });

  const hasData = $derived(
    ppcData != null && (ppcData.actual?.length ?? 0) > 0
  );
</script>

<div class="ppc-scatter">
  {#if !hasData}
    <div class="empty-state" role="status">
      <p>PPC данные недоступны</p>
    </div>
  {:else}
    <div class="charts-row">
      <div class="chart-cell">
        <EChartBase option={scatterOption} height="240px" />
      </div>
      <div class="chart-cell">
        <EChartBase option={residualsOption} height="240px" />
      </div>
    </div>
    <div class="legend-row">
      <span class="legend-item">
        <span class="color-dot" style="background: #3b82f6;"></span>Ранние периоды
      </span>
      <span class="legend-item">
        <span class="color-dot" style="background: #f97316;"></span>Поздние периоды
      </span>
      {#if r2Label}
        <span class="metric-badge success">{r2Label}</span>
      {/if}
      {#if dwLabel}
        <span class="metric-badge neutral">{dwLabel}</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .ppc-scatter {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .charts-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  @media (max-width: 640px) {
    .charts-row { grid-template-columns: 1fr; }
  }

  .chart-cell {
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.07));
  }

  .legend-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 2px 4px;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--text-secondary);
  }

  .color-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .metric-badge {
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;
  }

  .metric-badge.success {
    background: color-mix(in srgb, var(--success, #10B981) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--success, #10B981) 28%, transparent);
    color: #34d399;
  }

  .metric-badge.neutral {
    background: color-mix(in srgb, var(--text-secondary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-secondary) 20%, transparent);
    color: var(--text-secondary);
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100px;
    color: var(--text-secondary);
    font-size: 12px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border-radius: 8px;
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.08));
  }

  .empty-state p { margin: 0; }
</style>
