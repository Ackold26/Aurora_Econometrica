<script module>
  /** Накопитель применённых option — читается тестом. */
  let applied = [];
  export function __getAppliedOptions() { return applied; }
  export function __resetAppliedOptions() { applied = []; }
</script>

<script>
  /** Мок EChartBase (canvas недоступен в jsdom): копит каждый option. */
  let { option, height = '280px', step = -1, onInit } = $props();
  $effect(() => {
    if (option) applied.push(option);
  });
</script>

<div data-testid="mock-echart" style="height:{height}"></div>
