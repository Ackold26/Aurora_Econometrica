<script>
  /**
   * MultiScenarioChartStub — minimal test double for MultiScenarioChart.svelte.
   * Used by multi-scenario-page.test.js to avoid ECharts canvas init in jsdom.
   */
  const { scenarios = [], baseline = null, maxVisible = 5, kpiLabel = 'KPI' } = $props();
</script>

<div class="multi-scenario-chart-stub" data-testid="multi-scenario-chart-stub">
  <!-- stub: no ECharts canvas -->
</div>
