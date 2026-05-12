<script>
  /**
   * Channel comparison chart: grouped bar — Share of Spend vs Share of Effect.
   *
   * Compares каждый канал по двум долям (всегда в %), независимо от KPI mode:
   * - monetary ROI: «доля бюджета vs доля выручки»
   * - count: «доля бюджета vs доля проданных единиц»
   * - effectiveness: «доля бюджета vs доля эффекта в портфеле»
   *
   * Зелёный = эффект > расходов (недонасыщен), красный = расходы > эффекта
   * (перенасыщен). Y-axis всегда percentage — KPI-agnostic.
   *
   * v1.3.2: renamed из ROIComparison.svelte. Chart показывает shares of total
   * в процентах; не путать с ROI×/CPU/Доля метриками (которые показываются
   * на других чартах: WaterfallChart, action-table).
   *
   * @component ChannelComparisonChart
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';

  /**
   * @type {{
   *   channels: Array<{name: string, share_of_spend: number, share_of_effect: number, efficiency_gap: number}>
   * }}
   */
  let { channels } = $props();

  // Палитра — hex/rgba (ECharts не понимает color-mix()).
  const COLOR_SPEND = '#64748b';   // нейтральный slate — «фоновая» метрика для сравнения
  const COLOR_EFFICIENT = '#22c55e'; // зелёный — эффект > расходов
  const COLOR_INEFFICIENT = '#ef4444'; // красный — расходы > эффекта
  const COLOR_NEUTRAL = '#3b82f6'; // синий для дефолта/нулевого gap

  const option = $derived.by(() => {
    if (!channels?.length) return {};

    const names = channels.map(c => c.name);
    const spendData = channels.map(c => c.share_of_spend);
    const effectData = channels.map(c => c.share_of_effect);

    return {
      backgroundColor: 'transparent',
      tooltip: {
        ...chartTooltipDark({ trigger: 'axis' }),
        axisPointer: { type: 'shadow' },
        formatter: (/** @type {any[]} */ params) => {
          const ch = channels[params[0].dataIndex];
          const gap = ch.efficiency_gap;
          const sign = gap > 0 ? '+' : '';
          const gapColor = gap > 0 ? '#4ade80' : '#fb7185';
          return `<div style="color:#fff;font-weight:600;margin-bottom:4px;">${ch.name}</div>` +
                 `<div style="color:#fff;">Доля расходов: <b>${ch.share_of_spend}%</b></div>` +
                 `<div style="color:#fff;">Доля эффекта: <b>${ch.share_of_effect}%</b></div>` +
                 `<div style="color:${gapColor};font-weight:600;">Разрыв: ${sign}${gap}%</div>`;
        },
      },
      // Custom legend rows — явно задаём цвет и иконку, чтобы соответствие
      // легенды и реальной раскраски было 1:1 (а не дефолтная палитра ECharts).
      legend: {
        data: [
          { name: 'Расходы %', icon: 'roundRect', itemStyle: { color: COLOR_SPEND } },
          { name: 'Эффект (эффективен)', icon: 'roundRect', itemStyle: { color: COLOR_EFFICIENT } },
          { name: 'Эффект (перенасыщен)', icon: 'roundRect', itemStyle: { color: COLOR_INEFFICIENT } },
        ],
        textStyle: { color: '#94a3b8', fontSize: 11 },
        top: 4,
        itemGap: 18,
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
          itemStyle: { color: COLOR_SPEND, borderRadius: [4, 4, 0, 0] },
          data: spendData,
          label: { show: true, position: 'top', color: '#94a3b8', fontSize: 10, formatter: '{c}%' },
        },
        // Две серии для зелёных/красных, чтобы легенда корректно подсвечивала их.
        // ECharts не позволяет per-bar легенду в одной серии — поэтому split.
        {
          name: 'Эффект (эффективен)',
          type: 'bar',
          barMaxWidth: 32,
          stack: 'effect',
          itemStyle: { color: COLOR_EFFICIENT, borderRadius: [4, 4, 0, 0] },
          data: effectData.map((v, i) => (channels[i].efficiency_gap > 0 ? v : null)),
          label: { show: true, position: 'top', color: '#94a3b8', fontSize: 10, formatter: (/** @type {any} */ p) => p.value != null ? `${p.value}%` : '' },
        },
        {
          name: 'Эффект (перенасыщен)',
          type: 'bar',
          barMaxWidth: 32,
          stack: 'effect',
          itemStyle: { color: COLOR_INEFFICIENT, borderRadius: [4, 4, 0, 0] },
          data: effectData.map((v, i) => (channels[i].efficiency_gap <= 0 ? v : null)),
          label: { show: true, position: 'top', color: '#94a3b8', fontSize: 10, formatter: (/** @type {any} */ p) => p.value != null ? `${p.value}%` : '' },
        },
      ],
    };
  });
</script>

<EChartBase {option} height="240px" />
