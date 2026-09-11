<script>
  /**
   * PPCScatter - Posterior Predictive Check scatter (Факт vs Прогноз).
   *
   * Точки «факт против прогноза» относительно диагонали идеальной подгонки
   * (45°), окрашены градиентом по давности наблюдения.
   *
   * Per WIZARD_FLOW_v2_FINAL.md §6.3. До 2026-09-11 рисовала ещё и остатки
   * во времени вторым графиком внутри той же карточки - разнесены на два
   * самостоятельных компонента с собственным разворотом каждый (см.
   * PPCResidualsChart.svelte), т.к. общая карточка открывала оба графика
   * сразу одной кнопкой.
   *
   * @component PPCScatter
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { getAxisThemeColors } from '$lib/echarts-setup.js';
  import { theme } from '$lib/store.js';

  /**
   * @type {{
   *   ppcData: {
   *     actual: number[],
   *     predicted: number[],
   *     r2?: number,
   *   } | null,
   * }}
   */
  const { ppcData = null } = $props();

  const r2Label = $derived(
    ppcData?.r2 != null ? `R² = ${Number(ppcData.r2).toFixed(3)}` : ''
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

  // ── Actual vs Predicted scatter ────────────────────────────────

  const scatterOption = $derived.by(() => {
    void $theme; // F2: пересчитать цвета осей/сетки/подписей при смене темы
    if (!ppcData?.actual?.length || !ppcData?.predicted?.length) return {};

    const { textSecondary, borderSubtle, border, success } = getAxisThemeColors();
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
        textStyle: { color: textSecondary, fontSize: 11, fontWeight: 600 },
        subtextStyle: { color: success, fontSize: 10 },
      },
      xAxis: {
        type: 'value',
        name: 'Прогноз',
        nameTextStyle: { color: textSecondary, fontSize: 10 },
        axisLabel: { color: textSecondary, fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: borderSubtle } },
        axisLine: { lineStyle: { color: borderSubtle } },
      },
      yAxis: {
        type: 'value',
        name: 'Факт',
        nameTextStyle: { color: textSecondary, fontSize: 10 },
        axisLabel: { color: textSecondary, fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: borderSubtle } },
        axisLine: { lineStyle: { color: borderSubtle } },
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
          lineStyle: { color: border, type: 'dashed', width: 1 },
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
    <div class="chart-cell">
      <EChartBase option={scatterOption} height="240px" />
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
    </div>
  {/if}
</div>

<style>
  .ppc-scatter {
    display: flex;
    flex-direction: column;
    gap: 8px;
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
