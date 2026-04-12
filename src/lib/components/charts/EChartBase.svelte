<script>
  /**
   * Minimal ECharts wrapper (~40 lines).
   * D1: lazy-loads ECharts via dynamic import — 0 extra bytes until charts needed.
   * D2: minimal implementation — init, setOption, resize, dispose.
   * Rule 2: onMount is sync, async work in IIFE.
   *
   * @component EChartBase
   */
  import { onMount } from 'svelte';

  /** @type {{ option: any, height?: string }} */
  let { option, height = '300px' } = $props();

  /** @type {HTMLDivElement} */
  let container;
  /** @type {any} */
  let chart;

  onMount(() => {
    // D1: dynamic import — ECharts loads only when this component mounts
    (async () => {
      const { echarts } = await import('$lib/echarts-setup.js');
      if (!container) return;
      chart = echarts.init(container, 'dark');
      chart.setOption(option);
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
</script>

<div bind:this={container} style="width:100%;height:{height}"></div>
