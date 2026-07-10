<script>
  /**
   * Minimal ECharts wrapper.
   * D1: lazy-loads ECharts via dynamic import - 0 extra bytes until charts needed.
   * F2: theme-reactive via CSS vars (no hardcoded 'dark').
   * P4: step-aware - init only when visible step, dispose when leaving.
   * Rule 2: onMount is sync, async work in IIFE.
   *
   * @component EChartBase
   */
  import { onMount } from 'svelte';
  import { theme } from '$lib/store.js';
  import { pipelineCurrentStep } from '$lib/project-state.js';

  /** @type {{ option: any, height?: string, step?: number, onInit?: (chart: any) => void }} */
  let { option, height = '300px', step = -1, onInit } = $props();

  /** @type {HTMLDivElement} */
  let container;
  /** @type {any} */
  let chart;
  let initialized = $state(false);

  /** @type {boolean} P4: only init when this step is active (or step not specified) */
  const isVisible = $derived(step < 0 || $pipelineCurrentStep === step);

  async function initChart() {
    if (chart || !container) return;
    const { echarts, getBaseChartOption } = await import('$lib/echarts-setup.js');
    if (!container) return;
    chart = echarts.init(container);
    const base = getBaseChartOption();
    chart.setOption({ ...base, ...option });
    onInit?.(chart);
    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(container);
    initialized = true;
  }

  function disposeChart() {
    if (chart) {
      chart.dispose();
      chart = null;
      initialized = false;
    }
  }

  onMount(() => {
    // P4: init immediately if visible, otherwise wait
    if (isVisible) {
      initChart();
    }
    return () => disposeChart();
  });

  // P4: lazy-init when step becomes visible, dispose when leaving
  $effect(() => {
    if (isVisible && !chart && container) {
      initChart();
    } else if (!isVisible && chart) {
      disposeChart();
    }
  });

  // Reactive update when option changes
  // П2-1 (2026-07-10): setOption на живом echarts может бросить (universalTransition/
  // seriesKey морф) — без catch $effect умирает МОЛЧА и все дальнейшие обновления
  // option перестают применяться («клики не приводят к изменениям»). Ловим, логируем,
  // пробуем деградацию без анимации перехода (морф теряется, данные доезжают).
  $effect(() => {
    if (chart && option && initialized) {
      try {
        chart.setOption(option, true);
      } catch (e) {
        console.error('[EChartBase] setOption failed:', e);
        try {
          const stripped = {
            ...option,
            series: (option.series ?? []).map((/** @type {any} */ s) => {
              const { universalTransition, ...rest } = s ?? {};
              return rest;
            }),
          };
          chart.setOption(stripped, true);
          console.warn('[EChartBase] applied without universalTransition (morph degraded)');
        } catch (e2) {
          console.error('[EChartBase] fallback setOption failed too:', e2);
        }
      }
    }
  });

  // F2: re-apply base colors when theme changes
  $effect(() => {
    void $theme;
    if (!chart || !initialized) return;
    (async () => {
      const { getBaseChartOption } = await import('$lib/echarts-setup.js');
      chart.setOption(getBaseChartOption(), { notMerge: false });
    })();
  });
</script>

<div bind:this={container} style="width:100%;height:{height}"></div>
