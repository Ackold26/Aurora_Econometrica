<script>
  /**
   * Convergence diagnostics after model training.
   * Panel A: R-hat per parameter (ECharts horizontal bar).
   * Panel B: Actual vs Predicted (ECharts line/scatter).
   * D1: ECharts lazy-loaded via EChartBase.
   * B1: Full-width vertical stack.
   *
   * @component ConvergenceDashboard
   */
  import EChartBase from '$lib/components/charts/EChartBase.svelte';
  import { chartTooltipDark } from '$lib/echarts-setup.js';

  /** @type {{ diagnostics: any }} */
  let { diagnostics } = $props();

  /** R-hat threshold */
  const RHAT_WARN = 1.05;
  const RHAT_GOOD = 1.01;

  /** ECharts option for R-hat bar chart (Panel A) */
  const rhatOption = $derived.by(() => {
    const rhat = diagnostics?.per_param_rhat || {};
    const params = Object.keys(rhat);
    const values = params.map(p => rhat[p]);

    const colors = values.map(v =>
      v < RHAT_GOOD ? '#22c55e' :
      v < RHAT_WARN ? '#f59e0b' :
      '#ef4444'
    );

    return {
      backgroundColor: 'transparent',
      grid: { left: '160px', right: '40px', top: '16px', bottom: '32px' },
      xAxis: {
        type: 'value',
        min: 0.99,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      yAxis: {
        type: 'category',
        data: params,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
          barMaxWidth: 18,
          label: { show: true, position: 'right', color: '#94a3b8', fontSize: 10,
                   formatter: (/** @type {any} */ p) => p.value.toFixed(4) },
        },
        {
          type: 'line',
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ xAxis: RHAT_WARN }],
            lineStyle: { color: '#f59e0b', type: 'dashed', width: 1 },
            label: { show: true, position: 'end', color: '#f59e0b', fontSize: 10,
                     formatter: 'Порог сходимости' },
          },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(20,23,34,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: (/** @type {any[]} */ params) => {
          const p = params[0];
          const color = p.value < RHAT_GOOD ? '#22c55e' : p.value < RHAT_WARN ? '#f59e0b' : '#ef4444';
          const verdict = p.value < RHAT_WARN ? 'Сошёлся' : 'Не сошёлся';
          return `<b>${p.name}</b><br/>R-hat: <span style="color:${color}">${p.value.toFixed(4)}</span> (${verdict})`;
        },
      },
    };
  });

  /** ECharts option for Actual vs Predicted (Panel B) */
  const avpOption = $derived.by(() => {
    const avp = diagnostics?.actual_vs_predicted;
    if (!avp) return null;

    const xData = avp.dates
      ? avp.dates
      : avp.actual.map((/** @type {any} */ _, /** @type {number} */ i) => `#${i + 1}`);

    // Метрики качества — показываем в правом верхнем углу вместо сухой легенды.
    const r2 = diagnostics?.metrics?.r_squared;
    const mape = diagnostics?.metrics?.mape_pct;
    const r2Str = r2 != null ? `R² = ${Number(r2).toFixed(4)}` : '';
    const mapeStr = mape != null ? `MAPE = ${Number(mape).toFixed(2)}%` : '';
    const metricsLine = [r2Str, mapeStr].filter(Boolean).join('   ·   ');

    return {
      backgroundColor: 'transparent',
      grid: { left: '60px', right: '20px', top: '38px', bottom: '40px' },
      legend: {
        top: 4,
        left: 'center',
        textStyle: { color: '#94a3b8', fontSize: 11 },
      },
      graphic: metricsLine ? [{
        type: 'text',
        right: 14,
        top: 6,
        style: {
          text: metricsLine,
          fill: '#e2e8f0',
          fontFamily: 'Consolas, monospace',
          fontSize: 11,
          fontWeight: 600,
        },
        z: 10,
      }] : [],
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
          color: '#94a3b8', fontSize: 10,
          rotate: xData.length > 20 ? 35 : 0,
          interval: Math.max(0, Math.floor(xData.length / 12) - 1),
        },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8', fontSize: 10,
          formatter: (/** @type {number} */ v) => Math.round(v).toLocaleString('ru-RU'),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: [
        {
          name: 'Факт',
          type: 'line',
          data: avp.actual,
          lineStyle: { color: '#3b82f6', width: 1.5 },
          itemStyle: { color: '#3b82f6' },
          symbol: 'none',
          smooth: false,
        },
        {
          name: 'Прогноз',
          type: 'line',
          data: avp.predicted,
          lineStyle: { color: '#22c55e', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#22c55e' },
          symbol: 'circle',
          symbolSize: 3,
          smooth: false,
        },
      ],
      tooltip: chartTooltipDark({ trigger: 'axis' }),
    };
  });

  /** Check counts for warnings */
  const convergenceOk = $derived(diagnostics?.checks?.convergence !== false);
  const divergences = $derived(diagnostics?.metrics?.divergences || 0);
  const rhatCount = $derived(Object.keys(diagnostics?.per_param_rhat || {}).length);
  const rhatFailed = $derived(
    Object.values(diagnostics?.per_param_rhat || {}).filter(v => v >= 1.05).length
  );
  /** MCMC config used in this run — drives context-aware divergence advice. */
  const mcmcTune = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.tune ?? 2000));
  const mcmcDraws = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.draws ?? 2000));
  const mcmcTargetAccept = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.target_accept ?? 0.95));

  /** Chart height — scale with number of params */
  const rhatHeight = $derived(`${Math.max(180, rhatCount * 28 + 60)}px`);

  // Подсказки для ?-иконок
  const HELP = {
    rhatChart: 'R-hat по параметрам — проверка сходимости MCMC для каждого параметра модели отдельно.\n\nЧто это: горизонтальные бары для sigma (шум), intercept (базовая линия) и media_betas[N] (коэффициенты каналов). Красная зона — R-hat ≥ 1.05.\n\nКак читать: все бары в зелёной зоне → модель сошлась; один канал в красной → его ROI ненадёжен; sigma или intercept красные → нужно увеличить warmup/samples.',
    avpChart:  'Факт vs Прогноз — визуальная проверка качества модели.\n\nЧто это: синяя линия — реальные продажи, зелёная пунктирная — предсказание модели. В правом верхнем углу — R² и MAPE.\n\nКак читать: линии почти совпадают → модель хорошая; зелёная систематически выше/ниже синей → bias; большие выбросы в отдельных точках → пропущенный событие (промо, launch, кризис).',
  };
</script>

{#if diagnostics}
  <!-- Warning banners.
       UI bug fix (Phase 0.1 live-test): show "не сошлась" ONLY when R-hat > 1.05
       для хотя бы одного параметра. Backend's `checks.convergence` смешивает
       R-hat и divergences в один флаг — это сбивало пользователя ("не сошлась:
       0 параметров"). Дивергенции — отдельный signal об эффективности NUTS,
       не о сходимости. -->
  {#if rhatFailed > 0}
    <div class="warn-banner warn">
      ⚠ Модель не сошлась: {rhatFailed} параметров с R-hat &gt; 1.05.
      Рекомендуется увеличить draws/tune в расширенных настройках.
    </div>
  {/if}
  {#if divergences > 0}
    <div class="warn-banner warn">
      ⚠ {divergences} дивергенций обнаружено
      <span class="muted">(Tune={mcmcTune}, Draws={mcmcDraws}, target_accept={mcmcTargetAccept}).</span>
      {#if rhatFailed === 0}
        Параметры сошлись (R-hat &lt; 1.05) — модель готова к использованию.
        {#if divergences <= 10}
          {#if mcmcTune < 4000}
            <strong>Можно продолжать.</strong> Для академической чистоты — увеличьте Tune до 4000-6000 в Эксперт-режиме.
          {:else if mcmcTargetAccept < 0.99}
            <strong>Можно продолжать.</strong> Tune уже {mcmcTune} — дальнейшее увеличение не поможет. 1-3 дивергенции практически безвредны для 95% CI; альтернативно — повысьте target_accept до 0.99 (медленнее, но устранит остатки).
          {:else}
            <strong>Можно продолжать.</strong> Tune={mcmcTune}, target_accept={mcmcTargetAccept} — настройки максимальные. Остаточные дивергенции говорят о геометрии posterior'а, а не о NUTS adaptation. Безопасно для 95% CI.
          {/if}
        {:else if divergences <= 50}
          {#if mcmcTune < 6000}
            <strong>Продолжать можно с осторожностью.</strong> Увеличьте Tune до 6000 и Draws до 4000 — обычно уменьшает дивергенции в 5-10 раз.
          {:else}
            <strong>Продолжать можно с осторожностью.</strong> Tune={mcmcTune} не помогает уменьшить дивергенции. Альтернативы: target_accept=0.99, упростить модель (исключить коллинеарные каналы — см. VIF в Эксперт-режиме Валидации), или ужесточить приоры.
          {/if}
        {:else}
          {#if mcmcTune < 6000}
            <strong>Результаты использовать с осторожностью.</strong> Увеличьте Tune до 6000+, Draws до 6000, и/или исключите сильно коллинеарные каналы (см. VIF в Эксперт-режиме Валидации).
          {:else}
            <strong>Результаты использовать с осторожностью.</strong> Tune={mcmcTune} максимален — дальнейшее увеличение не поможет. Проблема в геометрии posterior'а: упростите модель (уберите коллинеарные каналы по VIF), сократите количество параметров, или сузьте приоры.
          {/if}
        {/if}
      {:else}
        Параметры не сошлись (R-hat &gt; 1.05).
        {#if mcmcTune < 6000}
          Увеличьте Tune до 6000 и Draws до 4000; если не помогло — упростите модель (исключите коллинеарные каналы).
        {:else}
          Tune={mcmcTune} не помогает достичь сходимости. Упростите модель (уберите коллинеарные каналы по VIF) или пересмотрите приоры в Эксперт-режиме.
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Panel A: R-hat per parameter -->
  {#if rhatCount > 0}
    <div class="chart-panel">
      <h4 class="chart-title">R-hat по параметрам<span class="help-icon" title={HELP.rhatChart}>?</span></h4>
      <EChartBase option={rhatOption} height={rhatHeight} />
      <p class="chart-hint">
        {rhatCount - rhatFailed} из {rhatCount} параметров сошлись (R-hat &lt; 1.05)
      </p>
    </div>
  {/if}

  <!-- Panel B: Actual vs Predicted -->
  {#if diagnostics.actual_vs_predicted}
    <div class="chart-panel">
      <h4 class="chart-title">Факт vs Прогноз<span class="help-icon" title={HELP.avpChart}>?</span></h4>
      <EChartBase option={avpOption} height="260px" />
    </div>
  {/if}
{/if}

<style>
  .warn-banner {
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.5;
  }

  .warn-banner.warn {
    background: color-mix(in srgb, var(--warning) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
    color: #f59e0b;
  }

  .chart-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border-radius: 12px;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
  }

  .chart-title {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
  }

  .chart-hint {
    margin: 0;
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
  }

  .help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-left: 6px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--text-secondary, #94a3b8) 18%, transparent);
    color: var(--text-secondary, #94a3b8);
    font-size: 10px;
    font-weight: 700;
    cursor: help;
    user-select: none;
    vertical-align: middle;
    transition: background 0.15s, color 0.15s;
  }
  .help-icon:hover {
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
    color: var(--accent-primary, #3b82f6);
  }
</style>
