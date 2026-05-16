<script>
  /**
   * Waterfall chart: stacked bar technique for sales decomposition.
   * Baseline → channel contributions → signed factors → total.
   *
   * v2.0.0 (ADR-019 §4): extended для signed factor negative bars.
   * Types: 'baseline' | 'channel' | 'signed_competitor' | 'signed_price' |
   *        'signed_weather' | 'signed_macro' | 'holiday' | 'positive_control' | 'total'.
   * Negative values render bar going downward from previous cumulative
   * (support adjusts to new lower cumulative, display height = abs(value)).
   *
   * Backward compat: callers passing types=['baseline','channel',...,'total']
   * с positive values работают unchanged (negative path не triggered).
   *
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

    // Compute support + display values (negative-aware waterfall layout).
    const support = new Array(n).fill(0);
    /** @type {number[]} display heights (always positive for ECharts) */
    const displayValues = new Array(n).fill(0);
    /** @type {boolean[]} negative flag per bar - для tooltip + color */
    const isNegative = new Array(n).fill(false);
    let cumulative = 0;
    for (let i = 0; i < n; i++) {
      const t = types[i];
      const v = values[i];
      if (t === 'total') {
        support[i] = 0;
        displayValues[i] = v; // total bar absolute from 0
      } else if (v >= 0) {
        // Positive bar: stack above previous cumulative
        support[i] = cumulative;
        displayValues[i] = v;
        cumulative += v;
      } else {
        // Negative bar (signed factor reducing total): cumulative decreases
        cumulative += v; // v < 0, so cumulative drops
        support[i] = cumulative; // support at new lower position
        displayValues[i] = -v; // display height = abs(v)
        isNegative[i] = true;
      }
    }

    // Assign colors by type (v2.0.0: signed factors get distinct palette)
    const colors = labels.map((_, i) => {
      const t = types[i];
      if (t === 'baseline') return '#3b82f6';            // blue
      if (t === 'total') return 'rgba(148,163,184,0.5)';  // light grey
      if (t === 'signed_competitor') return '#dc2626';    // red - explicit negative
      if (t === 'signed_price') return '#a855f7';         // purple - signed unconstrained
      if (t === 'signed_weather') return '#0ea5e9';       // sky-blue
      if (t === 'signed_macro') return '#f59e0b';         // amber
      if (t === 'holiday') return '#8b5cf6';              // violet
      if (t === 'positive_control') return '#10b981';     // teal
      // Negative value, fallback type - still red
      if (isNegative[i]) return '#dc2626';
      // 'channel' or generic positive - pick from palette by channel index
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
          const val = values[idx]; // ОRIGINAL value (preserve sign для tooltip)
          const pct = ((val / total) * 100).toFixed(1);
          const sign = val < 0 ? '−' : '';
          const absVal = Math.abs(val).toLocaleString('ru-RU');
          // v2.0.0: signed factors показывают «−15%» в tooltip vs «+10%»
          return `<div style="color:#fff;font-weight:600;margin-bottom:4px;">${labels[idx]}</div>` +
                 `<div style="color:#fff;">${sign}${absVal} <span style="opacity:0.7;">(${pct}%)</span></div>`;
        },
      },
      // Audit pass 14 (Антон 2026-05-03): explicit hide default ECharts legend.
      // Pre-fix: stray «support / value» labels (internal series names) появлялись
      // в верхнем углу chart - confusing customer.
      legend: { show: false },
      grid: { left: 16, right: 16, top: 12, bottom: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: labels,
        // v1.3.2 UX polish: graduated rotation per channel count для лучшей
        // читаемости русских названий (Cyrillic glyphs шире latin):
        //   ≤4 → 0° (horizontal)
        //   5-7 → 20°
        //   8-10 → 35°
        //   11+ → 45° (max readable per stack overflow tests)
        // Width tracks rotation для truncation threshold.
        axisLabel: {
          color: '#94a3b8',
          fontSize: 11,
          rotate: labels.length <= 4 ? 0 : labels.length <= 7 ? 20 : labels.length <= 10 ? 35 : 45,
          overflow: 'truncate',
          width: labels.length > 10 ? 72 : labels.length > 7 ? 88 : 100,
        },
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
          // v2.0.0: data uses displayValues (always positive heights).
          // Sign preserved в labels + tooltip + color (red для negative).
          data: displayValues.map((v, i) => ({
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
              // Show ORIGINAL value (с sign) на label, не abs display height
              const v = values[p.dataIndex];
              const sign = v < 0 ? '−' : '';
              const absV = Math.abs(v);
              return sign + (absV >= 1e6 ? `${(absV / 1e6).toFixed(1)}M`
                           : absV >= 1e3 ? `${(absV / 1e3).toFixed(0)}K`
                           : String(absV));
            },
          },
        },
      ],
    };
  });
</script>

<EChartBase {option} height="280px" />
