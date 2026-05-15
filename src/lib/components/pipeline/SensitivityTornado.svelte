<script>
  /**
   * SensitivityTornado - adaptive top-7 tornado bar chart for sensitivity analysis.
   *
   * Horizontal bar chart: Y=parameter names, X=ΔROI %.
   * Two bars per parameter: low_variation (negative, warm/red) and
   * high_variation (positive, cool/blue).
   * Sorted by |sensitivity_pct| descending. Baseline ROI label at top.
   * Empty state when parameters array is empty (post H4 fix — sensitivity guarded).
   *
   * Per WIZARD_FLOW_v2_FINAL.md §6.4.
   *
   * @component SensitivityTornado
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { TrendingUp } from 'lucide-svelte';
  import Tooltip from '$lib/components/Tooltip.svelte';
  import { TOOLTIPS } from '$lib/data/tooltip-texts.js';

  /**
   * @typedef {{
   *   name: string,
   *   low_variation: number,
   *   high_variation: number,
   *   sensitivity_pct: number,
   *   channel?: string,
   *   param_type?: string,
   * }} TornadoParam
   */

  /**
   * @type {{
   *   tornadoData: {
   *     baseline_roi?: number,
   *     parameters?: TornadoParam[],
   *   } | null,
   * }}
   */
  const { tornadoData = null } = $props();

  const MAX_PARAMS = 7;

  /** Sorted top-MAX_PARAMS parameters by |sensitivity_pct| desc */
  const sortedParams = $derived.by(() => {
    const params = tornadoData?.parameters ?? [];
    return [...params]
      .sort((a, b) => Math.abs(b.sensitivity_pct) - Math.abs(a.sensitivity_pct))
      .slice(0, MAX_PARAMS);
  });

  const baselineRoi = $derived(
    tornadoData?.baseline_roi != null
      ? Number(tornadoData.baseline_roi).toFixed(2)
      : null
  );

  const isEmpty = $derived(sortedParams.length === 0);

  /**
   * Build ECharts horizontal bar option (diverging tornado).
   * Two dataset series: low_variation (left, negative impact) and
   * high_variation (right, positive impact).
   */
  const option = $derived.by(() => {
    if (isEmpty) return {};

    const names = sortedParams.map(p => p.name);
    const lowValues = sortedParams.map(p => -Math.abs(p.low_variation));   // always negative side
    const highValues = sortedParams.map(p => Math.abs(p.high_variation));  // always positive side

    return {
      backgroundColor: 'transparent',
      grid: { left: '140px', right: '60px', top: '32px', bottom: '36px' },
      xAxis: {
        type: 'value',
        name: 'ΔROI %',
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          formatter: (/** @type {number} */ v) => (v > 0 ? '+' : '') + v.toFixed(1) + '%',
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        // Symmetric axis
        min: (/** @type {any} */ scale) => {
          const m = Math.min(...lowValues);
          return Math.min(scale.min, m * 1.1);
        },
        max: (/** @type {any} */ scale) => {
          const m = Math.max(...highValues);
          return Math.max(scale.max, m * 1.1);
        },
      },
      yAxis: {
        type: 'category',
        data: names,
        inverse: true,   // top = highest sensitivity
        axisLabel: {
          color: '#94a3b8',
          fontSize: 11,
          overflow: 'truncate',
          width: 130,
        },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      legend: {
        top: 4,
        right: 0,
        icon: 'roundRect',
        itemWidth: 12,
        itemHeight: 6,
        textStyle: { color: '#94a3b8', fontSize: 10 },
        data: [
          { name: 'Снижение', icon: 'roundRect' },
          { name: 'Рост', icon: 'roundRect' },
        ],
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(15,18,28,0.94)',
        borderColor: 'rgba(255,255,255,0.14)',
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (/** @type {any[]} */ params) => {
          if (!params?.length) return '';
          const pIdx = params[0].dataIndex;
          const pd = sortedParams[pIdx];
          if (!pd) return '';
          const low = lowValues[pIdx];
          const high = highValues[pIdx];
          return `
            <div style="font-weight:600;margin-bottom:6px;color:#fff;">${pd.name}</div>
            <div style="color:#fff;line-height:1.6;">
              <span style="color:#f87171;">↓ Снижение: ${low.toFixed(2)}%</span><br/>
              <span style="color:#60a5fa;">↑ Рост: +${high.toFixed(2)}%</span><br/>
              <span style="opacity:0.7;">|Чувствительность| ${Math.abs(pd.sensitivity_pct).toFixed(1)}%</span>
            </div>
          `.trim();
        },
      },
      series: [
        {
          name: 'Снижение',
          type: 'bar',
          stack: 'total',
          data: lowValues.map(v => ({
            value: v,
            itemStyle: { color: '#f87171', opacity: 0.85 },
          })),
          barMaxWidth: 20,
          label: {
            show: true,
            position: 'left',
            color: '#f87171',
            fontSize: 9,
            formatter: (/** @type {any} */ p) => p.value.toFixed(1) + '%',
          },
        },
        {
          name: 'Рост',
          type: 'bar',
          stack: 'total',
          data: highValues.map(v => ({
            value: v,
            itemStyle: { color: '#60a5fa', opacity: 0.85 },
          })),
          barMaxWidth: 20,
          label: {
            show: true,
            position: 'right',
            color: '#60a5fa',
            fontSize: 9,
            formatter: (/** @type {any} */ p) => '+' + p.value.toFixed(1) + '%',
          },
        },
        // Zero reference markLine on invisible series
        /** @type {any} */ ({
          name: '_zero_',
          type: 'line',
          data: [],
          showInLegend: false,
          silent: true,
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ xAxis: 0 }],
            lineStyle: { color: 'rgba(255,255,255,0.25)', type: 'solid', width: 1 },
            label: { show: false },
          },
        }),
      ],
    };
  });

  /** Dynamic height based on number of params */
  const chartHeight = $derived(`${Math.max(160, sortedParams.length * 36 + 80)}px`);
</script>

<div class="tornado-panel">
  <div class="panel-header">
    <span class="header-icon"><TrendingUp size={15} strokeWidth={1.8} /></span>
    <Tooltip text={TOOLTIPS['tornado.bar']} position="right">
      <h3 class="panel-title panel-title-tip">Анализ чувствительности</h3>
    </Tooltip>
    {#if baselineRoi !== null}
      <span class="baseline-badge">
        <Tooltip text={TOOLTIPS['metric.roi']} position="top">
          <span class="baseline-roi-label">Базовый ROI:</span>
        </Tooltip>
        <strong>{baselineRoi}</strong>
      </span>
    {/if}
  </div>

  {#if isEmpty}
    <div class="empty-state" role="status">
      <TrendingUp size={24} strokeWidth={1} />
      <p>Данные чувствительности недоступны</p>
      <span class="empty-note">Запустите анализ чувствительности для отображения tornado chart</span>
    </div>
  {:else}
    <EChartBase option={option} height={chartHeight} />
    <p class="chart-caption">
      Топ-{sortedParams.length} параметров по влиянию на ROI.
      Красные бары — отрицательное влияние, синие — положительное.
    </p>
  {/if}
</div>

<style>
  .tornado-panel {
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    border-radius: var(--radius-card, 12px);
    padding: 16px 18px 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .header-icon {
    display: flex;
    align-items: center;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
    flex: 1;
    letter-spacing: 0.01em;
  }
  .panel-title-tip {
    cursor: help;
    border-bottom: 1px dashed color-mix(in srgb, var(--text-secondary) 50%, transparent);
  }
  .baseline-roi-label {
    cursor: help;
    border-bottom: 1px dashed color-mix(in srgb, var(--text-secondary) 40%, transparent);
  }

  .baseline-badge {
    font-size: 11px;
    color: var(--text-secondary);
    background: color-mix(in srgb, var(--accent-primary) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-primary) 22%, transparent);
    border-radius: 5px;
    padding: 2px 8px;
    white-space: nowrap;
  }

  .baseline-badge strong {
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 120px;
    padding: 20px;
    background: color-mix(in srgb, var(--text-primary) 2%, transparent);
    border: 1px dashed var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 8px;
    color: var(--text-secondary);
    text-align: center;
  }

  .empty-state p {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
  }

  .empty-note {
    font-size: 11px;
    color: color-mix(in srgb, var(--text-secondary) 70%, transparent);
  }

  .chart-caption {
    margin: 0;
    font-size: 11px;
    color: var(--text-secondary);
    line-height: 1.5;
    padding: 0 2px;
  }
</style>
