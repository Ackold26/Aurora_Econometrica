<script>
  /**
   * ROI comparison: grouped bar — Share of Spend vs Share of Effect per channel.
   * Green = effect > spend (efficient), Red = spend > effect (inefficient).
   * @component ROIComparison
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';

  /**
   * @type {{
   *   channels: Array<{name: string, share_of_spend: number, share_of_effect: number, efficiency_gap: number}>
   * }}
   */
  let { channels } = $props();

  const option = $derived.by(() => {
    if (!channels?.length) return {};

    const names = channels.map(c => c.name);
    const spendData = channels.map(c => c.share_of_spend);
    const effectData = channels.map(c => c.share_of_effect);

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (/** @type {any[]} */ params) => {
          const ch = channels[params[0].dataIndex];
          const gap = ch.efficiency_gap;
          const sign = gap > 0 ? '+' : '';
          const gapColor = gap > 0 ? '#22c55e' : '#ef4444';
          return `<b>${ch.name}</b><br>
            Доля расходов: ${ch.share_of_spend}%<br>
            Доля эффекта: ${ch.share_of_effect}%<br>
            <span style="color:${gapColor}">Разрыв: ${sign}${gap}%</span>`;
        },
      },
      legend: {
        data: ['Расходы %', 'Эффект %'],
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 4,
      },
      grid: { left: 16, right: 16, top: 36, bottom: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: names,
        axisLabel: { color: '#94a3b8', fontSize: 11, rotate: names.length > 3 ? 25 : 0, overflow: 'truncate', width: 80 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        max: 100,
        axisLabel: { color: '#94a3b8', fontSize: 11, formatter: '{value}%' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      },
      series: [
        {
          name: 'Расходы %',
          type: 'bar',
          barGap: '10%',
          barMaxWidth: 32,
          data: spendData.map((v, i) => ({
            value: v,
            itemStyle: { color: 'rgba(148,163,184,0.4)', borderRadius: [4, 4, 0, 0] },
          })),
          label: { show: true, position: 'top', color: '#94a3b8', fontSize: 10, formatter: '{c}%' },
        },
        {
          name: 'Эффект %',
          type: 'bar',
          barMaxWidth: 32,
          data: effectData.map((v, i) => {
            const gap = channels[i].efficiency_gap;
            return {
              value: v,
              itemStyle: {
                color: gap > 0 ? 'color-mix(in srgb, var(--success) 70%, transparent)' : 'color-mix(in srgb, var(--danger) 70%, transparent)',
                borderRadius: [4, 4, 0, 0],
              },
            };
          }),
          label: { show: true, position: 'top', color: '#94a3b8', fontSize: 10, formatter: '{c}%' },
        },
      ],
    };
  });
</script>

<EChartBase {option} height="240px" />
