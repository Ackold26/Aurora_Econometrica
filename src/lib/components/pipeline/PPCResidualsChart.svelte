<script>
  /**
   * PPCResidualsChart - остатки (факт минус прогноз) во времени, с полосой
   * среднее ± 2σ и статистикой Durbin-Watson.
   *
   * Выделен из PPCScatter.svelte 2026-09-11: раньше рисовался вторым графиком
   * в той же карточке «Разброс прогноза и остатки» - разворот открывал сразу
   * оба графика. Теперь самостоятельный компонент со своей карточкой.
   *
   * Per WIZARD_FLOW_v2_FINAL.md §6.3.
   *
   * @component PPCResidualsChart
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark, getAxisThemeColors } from '$lib/echarts-setup.js';
  import { theme } from '$lib/store.js';

  /**
   * @type {{
   *   ppcData: {
   *     actual: number[],
   *     predicted: number[],
   *     residuals?: number[],
   *     durbin_watson?: number,
   *   } | null,
   *   expanded?: boolean,
   * }}
   */
  const { ppcData = null, expanded = false } = $props();

  /** Разворот (ExpandableCard) - график занимает доступную высоту вместо
   *  фиксированных 240px. Конкретное значение в развороте роли не играет:
   *  ExpandableCard снимает высоту с контейнера echarts (метка data-echart) и
   *  растягивает всю цепочку родителей одним общим правилом - см. там же.
   *  Живое измерение ИМЕННО этой карточки «Остатки» 13.09 (окно 1369px): холст
   *  1059px = 77.4% высоты окна; прежняя вёрстка на том же окне - 840px = 61.4%.
   *  До 13.09 здесь стояла ссылка на измерение соседней карточки - её не было,
   *  правку переносили по аналогии; теперь числа свои. */
  const chartHeight = $derived(expanded ? '100%' : '240px');

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

  const dwLabel = $derived(
    ppcData?.durbin_watson != null
      ? `DW = ${Number(ppcData.durbin_watson).toFixed(2)}`
      : ''
  );

  // ── Residuals over time ─────────────────────────────────────────

  const residualsOption = $derived.by(() => {
    void $theme; // F2: пересчитать цвета осей/сетки/подписей при смене темы
    const r = residuals;
    if (!r.length) return {};

    const { textSecondary, borderSubtle, border } = getAxisThemeColors();
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
        textStyle: { color: textSecondary, fontSize: 11, fontWeight: 600 },
        subtextStyle: { color: textSecondary, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: indices,
        name: 'Период',
        nameTextStyle: { color: textSecondary, fontSize: 10 },
        axisLabel: {
          color: textSecondary,
          fontSize: 9,
          interval: Math.max(0, Math.floor(r.length / 10) - 1),
        },
        axisLine: { lineStyle: { color: borderSubtle } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: 'Остаток',
        nameTextStyle: { color: textSecondary, fontSize: 10 },
        axisLabel: { color: textSecondary, fontSize: 9, formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU') },
        splitLine: { lineStyle: { color: borderSubtle } },
        axisLine: { show: false },
      },
      tooltip: chartTooltipDark({ trigger: 'axis' }),
      series: /** @type {any[]} */ ([
        // Полоса «среднее ± 2σ»: НИЖНЯЯ граница как невидимая опора.
        // 🔴 Здесь была опора на ВЕРХНЮЮ границу (2026-08-08, внешний аудит).
        // Слои с общим `stack` складываются, поэтому заливка высотой 4σ ложилась
        // не на нижнюю границу, а на верхнюю: полоса рисовалась в диапазоне от
        // среднего+2σ до среднего+6σ — над всеми остатками, вместо того чтобы
        // их охватывать. Дефект пережил написание, потому что компонент был
        // ничей и его никто не видел; подключён он только что.
        // Замысел автора виден в комментарии к следующему слою — «область над
        // нижней границей»: имя переменной и было ошибкой.
        {
          name: 'mean-2σ',
          type: 'line',
          data: bandLow,
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
          lineStyle: { color: border, type: 'dashed', width: 1 },
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

<div class="ppc-residuals">
  {#if !hasData}
    <div class="empty-state" role="status">
      <p>PPC данные недоступны</p>
    </div>
  {:else}
    <div class="chart-cell">
      <EChartBase option={residualsOption} height={chartHeight} />
    </div>
    {#if dwLabel}
      <div class="legend-row">
        <span class="metric-badge neutral">{dwLabel}</span>
      </div>
    {/if}
  {/if}
</div>

<style>
  .ppc-residuals {
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

  .metric-badge {
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;
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
