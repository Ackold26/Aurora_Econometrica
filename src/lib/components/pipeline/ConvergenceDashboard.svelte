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
  import ExpandableCard from '$lib/components/ExpandableCard.svelte';
  import PPCScatter from '$lib/components/pipeline/PPCScatter.svelte';
  import { chartTooltipDark, escapeHtml } from '$lib/echarts-setup.js';
  import { TriangleAlert, Check } from 'lucide-svelte';
  import Tooltip from '$lib/components/Tooltip.svelte';
  import { TOOLTIPS } from '$lib/data/tooltip-texts.js';
  import { pluralizeRu } from '$lib/utils/i18n.js';

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
          return `<b>${escapeHtml(p.name)}</b><br/>R-hat: <span style="color:${color}">${p.value.toFixed(4)}</span> (${verdict})`;
        },
      },
    };
  });

  // R²/MAPE для overlay-HTML (theme-contrastable вместо hardcoded ECharts graphic)
  const avpMetrics = $derived.by(() => {
    const r2 = diagnostics?.metrics?.r_squared;
    const mape = diagnostics?.metrics?.mape_pct;
    return {
      r2: r2 != null ? Number(r2).toFixed(3) : null,
      mape: mape != null ? Number(mape).toFixed(2) : null,
    };
  });

  /** ECharts option for Actual vs Predicted (Panel B) */
  const avpOption = $derived.by(() => {
    const avp = diagnostics?.actual_vs_predicted;
    if (!avp) return null;

    const xData = avp.dates
      ? avp.dates
      : avp.actual.map((/** @type {any} */ _, /** @type {number} */ i) => `#${i + 1}`);

    return {
      backgroundColor: 'transparent',
      grid: { left: '60px', right: '20px', top: '38px', bottom: '40px' },
      legend: {
        top: 4,
        left: 'center',
        textStyle: { color: '#94a3b8', fontSize: 11 },
      },
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
          // Audit pass 10 (Антон 2026-05-03): compact formatter - full numbers
          // «100 000 000» (11 chars × ~7px = 77px) обрезались в grid.left=60px
          // → customer видел «00 000 000» (clipped). Compact «100M» (4 chars)
          // fits comfortably + читается лучше.
          formatter: (/** @type {number} */ v) => {
            if (!Number.isFinite(v)) return '';
            const abs = Math.abs(v);
            if (abs >= 1e9) return (v / 1e9).toFixed(1) + 'B';
            if (abs >= 1e6) return (v / 1e6).toFixed(0) + 'M';
            if (abs >= 1e3) return (v / 1e3).toFixed(0) + 'K';
            return String(Math.round(v));
          },
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

  /** Panel C: PPC-данные (адаптация имён полей actual_vs_predicted под проп ppcData
   *  PPCScatter). residuals не передаём - компонент сам вычитает факт-прогноз (в OLS-ветке
   *  поле называется 'residual' в ед.ч. и с пропом не совпадает - пропуск осознанный).
   *  r2 - metrics.r_squared под другим именем. durbin_watson в движке нигде не считается -
   *  не передаём, компонент сам скрывает подпись DW при отсутствии значения. */
  const ppcData = $derived.by(() => {
    const avp = diagnostics?.actual_vs_predicted;
    if (!avp) return null;
    return {
      actual: avp.actual,
      predicted: avp.predicted,
      r2: diagnostics?.metrics?.r_squared,
    };
  });

  /** Check counts for warnings */
  const convergenceOk = $derived(diagnostics?.checks?.convergence !== false);
  const divergences = $derived(diagnostics?.metrics?.divergences || 0);
  const rhatCount = $derived(Object.keys(diagnostics?.per_param_rhat || {}).length);
  const rhatFailed = $derived(
    Object.values(diagnostics?.per_param_rhat || {}).filter(v => v >= 1.05).length
  );
  /** MCMC config used in this run - drives context-aware divergence advice. */
  const mcmcTune = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.tune ?? 2000));
  const mcmcDraws = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.draws ?? 2000));
  const mcmcChains = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.chains ?? 4));
  const mcmcTargetAccept = $derived(/** @type {number} */ (diagnostics?.metrics?.mcmc?.target_accept ?? 0.95));
  /** Total posterior samples = chains × draws. Used для divergence percentage display. */
  const totalDraws = $derived(mcmcChains * mcmcDraws);
  const divergencesPct = $derived(totalDraws > 0 ? (divergences / totalDraws * 100) : 0);

  /** Chart height - scale with number of params */
  const rhatHeight = $derived(`${Math.max(180, rhatCount * 28 + 60)}px`);

  // Подсказки для ?-иконок
  const HELP = {
    rhatChart: 'R-hat по параметрам - проверка сходимости MCMC для каждого параметра модели отдельно.\n\nЧто это: горизонтальные бары для sigma (шум), intercept (базовая линия) и media_betas[N] (коэффициенты каналов). Красная зона - R-hat ≥ 1.05.\n\nКак читать: все бары в зелёной зоне → модель сошлась; один канал в красной → его ROI ненадёжен; sigma или intercept красные → нужно увеличить warmup/samples.',
    avpChart:  'Факт vs Прогноз - визуальная проверка качества модели.\n\nЧто это: синяя линия - реальные продажи, зелёная пунктирная - предсказание модели. В правом верхнем углу - R² и MAPE.\n\nКак читать: линии почти совпадают → модель хорошая; зелёная систематически выше/ниже синей → bias; большие выбросы в отдельных точках → пропущенный событие (промо, launch, кризис).',
    ppcChart:  'Разброс прогноза и остатки - ещё одна проверка качества модели.\n\nЧто это: слева - точки «факт против прогноза» относительно диагонали идеальной подгонки; справа - остатки (факт минус прогноз) во времени с полосой среднее ± 2 стандартных отклонения.\n\nКак читать: точки плотно у диагонали → модель точна; остатки без явного тренда и в пределах полосы → ошибка случайна, не систематична.',
  };
</script>

{#if diagnostics}
  <!-- Warning banners.
       UI bug fix (Phase 0.1 live-test): show "не сошлась" ONLY when R-hat > 1.05
       для хотя бы одного параметра. Backend's `checks.convergence` смешивает
       R-hat и divergences в один флаг - это сбивало пользователя ("не сошлась:
       0 параметров"). Дивергенции - отдельный signal об эффективности NUTS,
       не о сходимости. -->
  {#if rhatFailed > 0}
    <div class="warn-banner warn">
      <p class="banner-primary">
        <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Модель не завершила расчёт корректно: {rhatFailed} параметров показывают
        нестабильность. Откройте расширенные настройки и увеличьте число итераций.
      </p>
      <details class="banner-details">
        <summary>Технические детали</summary>
        <div class="banner-secondary">
          Модель не сошлась: {rhatFailed} параметров с R-hat &gt; 1.05.
          Рекомендуется увеличить draws/tune в расширенных настройках.
        </div>
      </details>
    </div>
  {/if}
  {#if divergences > 0}
    <div class="warn-banner warn">
      <p class="banner-primary">
        {#if rhatFailed === 0}
          {#if divergences <= 10}
            {#if mcmcTune < 4000}
              <Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Сходимость достигнута (R-hat &lt; 1.05). Для максимальной точности можно
              улучшить выборку в Эксперт-режиме.
            {:else}
              <Check size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Сходимость достигнута (R-hat &lt; 1.05). Единичные нестабильности не влияют
              на сходимость – надёжность выводов оценивайте по баллу качества модели (MQS).
            {/if}
          {:else if divergences <= 50}
            {#if mcmcTune < 6000}
              <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Результаты можно использовать ориентировочно. Для улучшения точности
              повторите расчёт с расширенными настройками.
            {:else}
              <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Результаты требуют проверки. Попробуйте упростить модель – уберите
              каналы, которые дублируют друг друга (см. отчёт по мультиколлинеарности
              в Валидации).
            {/if}
          {:else}
            {#if mcmcTune < 6000}
              <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Расчёт нестабилен. Повторите с более мощными настройками или упростите
              состав каналов перед принятием решений.
            {:else}
              <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Расчёт нестабилен при текущем наборе каналов. Уберите каналы с похожими
              данными – это обычно решает проблему. Результаты пока не рекомендуется
              использовать для планирования.
            {/if}
          {/if}
        {:else}
          {#if mcmcTune < 6000}
            <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Модель не завершила расчёт. Увеличьте число итераций или сократите
            количество каналов – особенно тех, чьи данные похожи друг на друга.
          {:else}
            <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Модель не завершила расчёт. Упростите модель – уберите каналы с похожими
            данными (см. мультиколлинеарность в Эксперт-режиме Валидации).
          {/if}
        {/if}
      </p>
      <details class="banner-details">
        <summary>Технические детали</summary>
        <div class="banner-secondary">
          Обнаружено: {divergences} {pluralizeRu(divergences, ['дивергенция', 'дивергенции', 'дивергенций'])} <span class="muted">({divergencesPct.toFixed(2)}% от {totalDraws} draws)</span>
          <span class="muted">(Tune={mcmcTune}, Draws={mcmcDraws}, target_accept={mcmcTargetAccept}).</span>
          {#if rhatFailed === 0}
            Параметры сошлись (R-hat &lt; 1.05) - модель готова к использованию.
            {#if divergences <= 10}
              {#if mcmcTune < 4000}
                <strong>Можно продолжать.</strong> Для академической чистоты - увеличьте Tune до 4000-6000 в Эксперт-режиме.
              {:else if mcmcTargetAccept < 0.99}
                <strong>Можно продолжать.</strong> Tune уже {mcmcTune} - дальнейшее увеличение не поможет. 1-3 дивергенции практически безвредны для 95%-го правдоподобного диапазона; альтернативно - повысьте target_accept до 0.99 (медленнее, но устранит остатки).
              {:else}
                <strong>Можно продолжать.</strong> Tune={mcmcTune}, target_accept={mcmcTargetAccept} - настройки максимальные. Остаточные дивергенции говорят о геометрии posterior'а, а не о NUTS adaptation. Безопасно для 95%-го правдоподобного диапазона.
              {/if}
            {:else if divergences <= 50}
              {#if mcmcTune < 6000}
                <strong>Продолжать можно с осторожностью.</strong> Увеличьте Tune до 6000 и Draws до 4000 - обычно уменьшает дивергенции в 5-10 раз.
              {:else}
                <strong>Продолжать можно с осторожностью.</strong> Tune={mcmcTune} не помогает уменьшить дивергенции. Альтернативы: target_accept=0.99, упростить модель (исключить коллинеарные каналы - см. VIF в Эксперт-режиме Валидации), или ужесточить приоры.
              {/if}
            {:else}
              {#if mcmcTune < 6000}
                <strong>Результаты использовать с осторожностью.</strong> Увеличьте Tune до 6000+, Draws до 6000, и/или исключите сильно коллинеарные каналы (см. VIF в Эксперт-режиме Валидации).
              {:else}
                <strong>Результаты использовать с осторожностью.</strong> Tune={mcmcTune} максимален - дальнейшее увеличение не поможет. Проблема в геометрии posterior'а: упростите модель (уберите коллинеарные каналы по VIF), сократите количество параметров, или сузьте приоры.
              {/if}
            {/if}
          {:else}
            Параметры не сошлись (R-hat &gt; 1.05).
            {#if mcmcTune < 6000}
              Увеличьте Tune до 6000 и Draws до 4000; если не помогло - упростите модель (исключите коллинеарные каналы).
            {:else}
              Tune={mcmcTune} не помогает достичь сходимости. Упростите модель (уберите коллинеарные каналы по VIF) или пересмотрите приоры в Эксперт-режиме.
            {/if}
          {/if}
        </div>
      </details>
    </div>
  {/if}

  <!-- Panel A: R-hat per parameter -->
  {#if rhatCount > 0}
    <ExpandableCard title="R-hat по параметрам">
      <div class="chart-panel-body">
        <span class="chart-title-help" title={HELP.rhatChart}>?</span>
        <EChartBase option={rhatOption} height={rhatHeight} />
        <p class="chart-hint">
          {rhatCount - rhatFailed} из {rhatCount} параметров сошлись (R-hat &lt; 1.05)
        </p>
      </div>
    </ExpandableCard>
  {/if}

  <!-- Panel B: Actual vs Predicted - wrapped в ExpandableCard для fullscreen.
       Метрики R²/MAPE - HTML overlay через CSS tokens (theme-contrastable). -->
  {#if diagnostics.actual_vs_predicted}
    <ExpandableCard title="Факт vs Прогноз">
      <div class="chart-panel-body avp-panel">
        <span class="chart-title-help" title={HELP.avpChart}>?</span>
        {#if avpMetrics.r2 != null || avpMetrics.mape != null}
          <div class="avp-metrics">
            {#if avpMetrics.r2 != null}
              <span class="metric-item">
                <Tooltip text={TOOLTIPS['metric.r2']} position="top">
                  <span class="metric-label metric-label-tip">R²</span>
                </Tooltip>
                <span class="metric-sep">=</span><b>{avpMetrics.r2}</b>
              </span>
            {/if}
            {#if avpMetrics.r2 != null && avpMetrics.mape != null}<span class="metric-dot">·</span>{/if}
            {#if avpMetrics.mape != null}
              <span class="metric-item">
                <Tooltip text={TOOLTIPS['metric.mape']} position="top">
                  <span class="metric-label metric-label-tip">MAPE</span>
                </Tooltip>
                <span class="metric-sep">=</span><b>{avpMetrics.mape}%</b>
              </span>
            {/if}
          </div>
        {/if}
        <EChartBase option={avpOption} height="260px" />
      </div>
    </ExpandableCard>
  {/if}

  <!-- Panel C: разброс прогноза (диагональ 45°) + остатки во времени (mean±2σ).
       Осиротевший компонент PPCScatter подключён 2026-08-07 - те же данные,
       что и Panel B, гейт идентичный. -->
  {#if diagnostics.actual_vs_predicted}
    <ExpandableCard title="Разброс прогноза и остатки">
      <div class="chart-panel-body">
        <span class="chart-title-help" title={HELP.ppcChart}>?</span>
        <PPCScatter {ppcData} />
      </div>
    </ExpandableCard>
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

  .banner-primary {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    font-weight: 500;
    color: var(--text-primary, #e2e8f0);
  }

  .banner-details {
    margin-top: 8px;
  }

  .banner-details > summary {
    list-style: none;
    cursor: pointer;
    user-select: none;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: color-mix(in srgb, var(--text-secondary, #94a3b8) 90%, transparent);
    padding: 3px 0;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: color 0.15s;
  }

  .banner-details > summary::-webkit-details-marker {
    display: none;
  }

  .banner-details > summary::before {
    content: '▸';
    font-size: 10px;
    transition: transform 0.15s;
    display: inline-block;
  }

  .banner-details[open] > summary::before {
    transform: rotate(90deg);
  }

  .banner-details > summary:hover {
    color: var(--text-primary, #e2e8f0);
  }

  .banner-secondary {
    margin-top: 8px;
    padding: 10px 12px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--text-primary, #e2e8f0) 4%, transparent);
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-secondary, #94a3b8);
  }

  .banner-secondary strong {
    color: var(--text-primary, #e2e8f0);
    font-weight: 600;
  }

  .banner-secondary .muted {
    color: color-mix(in srgb, var(--text-secondary, #94a3b8) 70%, transparent);
    font-size: 11px;
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

  /* Phase 2 audit pass 5 cont (Антон 2026-05-03): chart panel body inside
     ExpandableCard. Position relative - overlay R²/MAPE metrics absolutely. */
  .chart-panel-body {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .chart-title-help {
    position: absolute;
    top: 0;
    left: 0;
    z-index: 5;
    width: 16px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: color-mix(in srgb, var(--text-secondary, #94a3b8) 18%, transparent);
    color: var(--text-secondary, #94a3b8);
    border-radius: 50%;
    font-size: 11px;
    font-weight: 700;
    cursor: help;
    user-select: none;
  }
  /* R²/MAPE overlay - theme-contrastable через CSS tokens. */
  .avp-metrics {
    position: absolute;
    top: 0;
    right: 4px;
    z-index: 5;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--text-primary) 6%, transparent);
    border: 1px solid var(--border-subtle);
    font-family: Consolas, 'SF Mono', Menlo, monospace;
    font-size: 11px;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }
  .avp-metrics .metric-item {
    display: inline-flex;
    align-items: baseline;
    gap: 3px;
  }
  .avp-metrics .metric-label {
    color: var(--text-secondary);
    font-weight: 500;
  }
  .avp-metrics .metric-label-tip {
    cursor: help;
    border-bottom: 1px dashed var(--text-muted, #64748b);
    text-decoration: none;
  }
  .avp-metrics .metric-sep {
    color: var(--text-muted);
  }
  .avp-metrics b {
    color: var(--text-primary);
    font-weight: 600;
  }
  .avp-metrics .metric-dot {
    color: var(--text-muted);
    font-weight: 700;
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
