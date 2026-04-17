<script>
  /**
   * Minimal ECharts wrapper (~40 lines).
   * D1: lazy-loads ECharts via dynamic import — 0 extra bytes until charts needed.
   * D2: minimal implementation — init, setOption, resize, dispose.
   * F2: theme-reactive via CSS vars (no hardcoded 'dark').
   * Rule 2: onMount is sync, async work in IIFE.
   *
   * @component EChartBase
   */
  import { onMount } from 'svelte';
  import { theme } from '$lib/store.js';

  /** @type {{ option: any, height?: string, onInit?: (chart: any) => void }} */
  let { option, height = '300px', onInit } = $props();

  /** @type {HTMLDivElement} */
  let container;
  /** @type {any} */
  let chart;

  onMount(() => {
    // D1: dynamic import — ECharts loads only when this component mounts
    (async () => {
      const { echarts, getBaseChartOption } = await import('$lib/echarts-setup.js');
      if (!container) return;
      chart = echarts.init(container);
      const base = getBaseChartOption();
      chart.setOption({ ...base, ...option });
      onInit?.(chart);
      const ro = new ResizeObserver(() => chart?.resize());
      ro.observe(container);
    })();
    // Rule 2: sync cleanup
    return () => chart?.dispose();
  });

  // Reactive update when option changes
  $effect(() => {
    if (chart && option) chart.setOption(option, true);
  });

  // F2: re-apply base colors when theme changes
  $effect(() => {
    void $theme; // subscribe to theme store
    if (!chart) return;
    (async () => {
      const { getBaseChartOption } = await import('$lib/echarts-setup.js');
      chart.setOption(getBaseChartOption(), { notMerge: false });
    })();
  });
</script>

<div bind:this={container} style="width:100%;height:{height}"></div>
