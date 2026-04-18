<script>
  /**
   * Convergence diagnostics after model training.
   * Panel A: R-hat per parameter (ECharts horizontal bar).
   * Panel B: Actual vs Predicted (ECharts line/scatter).
   * D1: ECharts lazy-loaded via EChartBase.
   * B1: Full-width vertical stack.
   *
   * @component ConvergenceDashboard
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';

  /** @type {{ diagnostics: any }} */
  let { diagnostics } = $props();

  /** R-hat threshold */
  const RHAT_WARN = 1.05;
  const RHAT_GOOD = 1.01;

  /** ECharts option for R-hat bar chart (Panel A) */
  const rhatOption = $derived.by(() => {
    const rhat = diagnostics?.per_param_rhat || {};
    const params = Object.keys(rhat);
    const values = params.map(p => rhat[p]);

    const colors = values.map(v =>
      v < RHAT_GOOD ? '#22c55e' :
      v < RHAT_WARN ? '#f59e0b' :
      '#ef4444'
    );

    return {
      backgroundColor: 'transparent',
      grid: { left: '160px', right: '40px', top: '16px', bottom: '32px' },
      xAxis: {
        type: 'value',
        min: 0.99,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      yAxis: {
        type: 'category',
        data: params,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
          barMaxWidth: 18,
          label: { show: true, position: 'right', color: '#94a3b8', fontSize: 10,
                   formatter: (/** @type {any} */ p) => p.value.toFixed(4) },
        },
        {
          type: 'line',
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ xAxis: RHAT_WARN }],
            lineStyle: { color: '#f59e0b', type: 'dashed', width: 1 },
            label: { show: true, position: 'end', color: '#f59e0b', fontSize: 10,
                     formatter: 'Порог сходимости' },
          },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(20,23,34,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: (/** @type {any[]} */ params) => {
          const p = params[0];
          const color = p.value < RHAT_GOOD ? '#22c55e' : p.value < RHAT_WARN ? '#f59e0b' : '#ef4444';
          const verdict = p.value < RHAT_WARN ? 'Сошёлся' : 'Не сошёлся';
          return `<b>${p.name}</b><br/>R-hat: <span style="color:${color}">${p.value.toFixed(4)}</span> (${verdict})`;
        },
      },
    };
  });

  /** ECharts option for Actual vs Predicted (Panel B) */
  const avpOption = $derived.by(() => {
    const avp = diagnostics?.actual_vs_predicted;
    if (!avp) return null;

    const xData = avp.dates
      ? avp.dates
      : avp.actual.map((/** @type {any} */ _, /** @type {number} */ i) => `#${i + 1}`);

    return {
      backgroundColor: 'transparent',
      grid: { left: '60px', right: '20px', top: '28px', bottom: '40px' },
      legend: {
        top: 4,
        textStyle: { color: '#94a3b8', fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
          color: '#94a3b8', fontSize: 10,
          rotate: xData.length > 20 ? 35 : 0,
          interval: Math.max(0, Math.floor(xData.length / 12) - 1),
        },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: [
        {
          name: 'Факт',
          type: 'line',
          data: avp.actual,
          lineStyle: { color: '#3b82f6', width: 1.5 },
          itemStyle: { color: '#3b82f6' },
          symbol: 'none',
          smooth: false,
        },
        {
          name: 'Прогноз',
          type: 'line',
          data: avp.predicted,
          lineStyle: { color: '#22c55e', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#22c55e' },
          symbol: 'circle',
          symbolSize: 3,
          smooth: false,
        },
      ],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(20,23,34,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        textStyle: { color: '#e2e8f0', fontSize: 12 },
      },
    };
  });

  /** Check counts for warnings */
  const convergenceOk = $derived(diagnostics?.checks?.convergence !== false);
  const divergences = $derived(diagnostics?.metrics?.divergences || 0);
  const rhatCount = $derived(Object.keys(diagnostics?.per_param_rhat || {}).length);
  const rhatFailed = $derived(
    Object.values(diagnostics?.per_param_rhat || {}).filter(v => v >= 1.05).length
  );

  /** Chart height — scale with number of params */
  const rhatHeight = $derived(`${Math.max(180, rhatCount * 28 + 60)}px`);
</script>

{#if diagnostics}
  <!-- Warning banners -->
  {#if !convergenceOk}
    <div class="warn-banner warn">
      ⚠ Модель не сошлась: {rhatFailed} параметров с R-hat &gt; 1.05.
      Рекомендуется увеличить draws/tune в расширенных настройках.
    </div>
  {/if}
  {#if divergences > 0}
    <div class="warn-banner warn">
      ⚠ {divergences} дивергенций обнаружено. Возможна слишком сложная модель.
    </div>
  {/if}

  <!-- Panel A: R-hat per parameter -->
  {#if rhatCount > 0}
    <div class="chart-panel">
      <h4 class="chart-title">R-hat по параметрам</h4>
      <EChartBase option={rhatOption} height={rhatHeight} />
      <p class="chart-hint">
        {rhatCount - rhatFailed} из {rhatCount} параметров сошлись (R-hat &lt; 1.05)
      </p>
    </div>
  {/if}

  <!-- Panel B: Actual vs Predicted -->
  {#if diagnostics.actual_vs_predicted}
    <div class="chart-panel">
      <h4 class="chart-title">Факт vs Прогноз</h4>
      <EChartBase option={avpOption} height="260px" />
    </div>
  {/if}
{/if}

<style>
  .warn-banner {
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.5;
  }

  .warn-banner.warn {
    background: color-mix(in srgb, var(--warning) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
    color: #f59e0b;
  }

  .chart-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-radius: 12px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .chart-title {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .chart-hint {
    margin: 0;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
  }
</style>
