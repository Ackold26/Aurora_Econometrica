<script>
  /**
   * Waterfall chart: stacked bar technique for sales decomposition.
   * Baseline → channel contributions → total.
   * @component WaterfallChart
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { CHANNEL_COLORS } from '$lib/hill.js';

  /** @type {{ waterfall: { labels: string[], values: number[], types: string[] } }} */
  let { waterfall } = $props();

  const option = $derived.by(() => {
    if (!waterfall?.labels?.length) return {};

    const labels = waterfall.labels;
    const values = waterfall.values;
    const types = waterfall.types;
    const n = labels.length;

    // Compute cumulative "invisible" support bars
    const support = new Array(n).fill(0);
    let cumulative = 0;
    for (let i = 0; i < n; i++) {
      if (types[i] === 'total') {
        support[i] = 0; // total bar starts from 0
      } else {
        support[i] = cumulative;
        cumulative += values[i];
      }
    }

    // Assign colors by type
    const colors = labels.map((_, i) => {
      const t = types[i];
      if (t === 'baseline') return '#3b82f6';
      if (t === 'total') return 'rgba(148,163,184,0.5)';
      // channel — pick from palette by channel index
      const chIdx = types.slice(0, i).filter(x => x === 'channel').length;
      return CHANNEL_COLORS[(chIdx + 1) % CHANNEL_COLORS.length];
    });

    const total = values[n - 1] || 1;

    return {
      backgroundColor: 'transparent',
      tooltip: {
        ...chartTooltipDark({ trigger: 'axis' }),
        axisPointer: { type: 'shadow' },
        formatter: (/** @type {any[]} */ params) => {
          const idx = params[1]?.dataIndex ?? params[0]?.dataIndex ?? 0;
          const val = values[idx];
          const pct = ((val / total) * 100).toFixed(1);
          return `<div style="color:#fff;font-weight:600;margin-bottom:4px;">${labels[idx]}</div>` +
                 `<div style="color:#fff;">${val.toLocaleString('ru-RU')} <span style="opacity:0.7;">(${pct}%)</span></div>`;
        },
      },
      grid: { left: 16, right: 16, top: 12, bottom: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#94a3b8', fontSize: 11, rotate: labels.length > 5 ? 25 : 0, overflow: 'truncate', width: 80 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8', fontSize: 11,
          formatter: (/** @type {number} */ v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      },
      series: [
        {
          name: 'support',
          type: 'bar',
          stack: 'waterfall',
          itemStyle: { color: 'transparent', borderColor: 'transparent' },
          data: support,
          tooltip: { show: false },
        },
        {
          name: 'value',
          type: 'bar',
          stack: 'waterfall',
          barMaxWidth: 48,
          data: values.map((v, i) => ({
            value: v,
            itemStyle: {
              color: colors[i],
              borderRadius: types[i] === 'total' ? [4, 4, 4, 4] : [4, 4, 0, 0],
            },
          })),
          label: {
            show: true,
            position: 'top',
            color: '#94a3b8',
            fontSize: 10,
            formatter: (/** @type {any} */ p) => {
              const v = values[p.dataIndex];
              return v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v);
            },
          },
        },
      ],
    };
  });
</script>

<EChartBase {option} height="280px" />
