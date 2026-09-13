<script>
  /**
   * EChartOptionProbe – подмена EChartBase в проверках.
   *
   * ECharts в jsdom холст не поднимает, поэтому проверить «что нарисовано» можно
   * только по переданной настройке. Заглушка выкладывает в разметку список линий
   * легенды и число слоёв – этого хватает, чтобы стеречь «несколько сценариев в
   * ОДНИХ осях» и не зависеть от внутренностей ECharts.
   */
  const { option = {}, height = '' } = $props();

  const legend = $derived(
    Array.isArray(option?.legend?.data) ? option.legend.data.join('|') : ''
  );
  const seriesCount = $derived(Array.isArray(option?.series) ? option.series.length : 0);
</script>

<div
  class="echart-probe"
  data-echart
  data-testid="echart-probe"
  data-legend={legend}
  data-series-count={seriesCount}
  data-height={height}
></div>
