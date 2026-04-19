<script>
  /**
   * Stacked area chart showing per-period contributions.
   * Baseline at bottom, channels stacked above.
   * DataZoom slider for period zoom (Phase 4, Plan 4A.6).
   * @component ChannelTimeline
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';
  import { CHANNEL_COLORS } from '$lib/hill.js';

  /**
   * @type {{
   *   timeSeries: {
   *     dates: string[],
   *     baseline: number[],
   *     channels: Record<string, number[]>
   *   }
   * }}
   */
  let { timeSeries } = $props();

  const option = $derived.by(() => {
    if (!timeSeries?.dates?.length) return {};

    const { dates, baseline, channels } = timeSeries;
    const channelNames = Object.keys(channels);
    const allSeries = [];

    // Baseline series (bottom)
    allSeries.push({
      name: 'Базовый уровень',
      type: 'line',
      stack: 'total',
      areaStyle: { opacity: 0.6, color: '#3b82f6' },
      lineStyle: { width: 0 },
      symbol: 'none',
      data: baseline,
      itemStyle: { color: '#3b82f6' },
      emphasis: { focus: 'series' },
    });

    // Channel series
    channelNames.forEach((ch, idx) => {
      const color = CHANNEL_COLORS[(idx + 1) % CHANNEL_COLORS.length];
      allSeries.push({
        name: ch,
        type: 'line',
        stack: 'total',
        areaStyle: { opacity: 0.65, color },
        lineStyle: { width: 0 },
        symbol: 'none',
        data: channels[ch],
        itemStyle: { color },
        emphasis: { focus: 'series' },
      });
    });

    return {
      backgroundColor: 'transparent',
      tooltip: {
        ...chartTooltipDark({ trigger: 'axis' }),
        axisPointer: { type: 'cross', label: { backgroundColor: 'rgba(15,18,28,0.94)', color: '#fff' } },
        formatter: (/** @type {any[]} */ params) => {
          const total = params.reduce((s, p) => s + (p.value ?? 0), 0);
          let html = `<div style="color:#fff;font-weight:600;margin-bottom:6px;">${params[0]?.axisValue}</div>`;
          params.forEach(p => {
            const pct = total > 0 ? ((p.value / total) * 100).toFixed(1) : '0.0';
            const v = typeof p.value === 'number' ? p.value.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) : p.value;
            const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${p.color};margin-right:8px;vertical-align:middle;"></span>`;
            html += `<div style="color:#fff;line-height:1.5;">${dot}<span style="opacity:0.9;">${p.seriesName}:</span> <b>${v}</b> <span style="opacity:0.7;">(${pct}%)</span></div>`;
          });
          html += `<div style="color:#fff;font-weight:600;margin-top:6px;border-top:1px solid rgba(255,255,255,0.15);padding-top:4px;">Итого: ${total.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}</div>`;
          return html;
        },
      },
      legend: {
        type: 'scroll',
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 4,
        pageTextStyle: { color: '#94a3b8' },
      },
      grid: { left: 16, right: 16, top: 44, bottom: 56, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { color: '#94a3b8', fontSize: 10, rotate: 25 },
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
      dataZoom: [
        {
          type: 'slider',
          bottom: 4,
          height: 20,
          borderColor: 'rgba(255,255,255,0.1)',
          backgroundColor: 'rgba(255,255,255,0.04)',
          fillerColor: 'color-mix(in srgb, var(--accent-primary) 15%, transparent)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { color: '#94a3b8', fontSize: 10 },
          start: 0,
          end: 100,
        },
        { type: 'inside' },
      ],
      series: allSeries,
    };
  });
</script>

<EChartBase {option} height="280px" />
