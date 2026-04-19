<script>
  /**
   * Model Quality Score badge — visual indicator with tier label.
   * Shows human-readable verdict + collapsible tech metrics.
   *
   * @component MQSBadge
   */

  /** @type {{ diagnostics: any }} */
  let { diagnostics } = $props();

  let showDetails = $state(false);

  /** @type {any} */
  let mqs = $derived(diagnostics?.mqs || null);
  let verdict = $derived(diagnostics?.verdict || '');
  let metrics = $derived(diagnostics?.metrics || {});
  let checks = $derived(diagnostics?.checks || {});

  // Общая подсказочная база — синхронизирована с ExpertModelPanel.svelte.
  const HELP = {
    rSq:    'R² (коэффициент детерминации) — доля вариации KPI, объяснённая моделью.\n\nЧто это: 0 = модель не лучше среднего, 1 = идеальный fit. ≥ 0.7 — хорошо, ≥ 0.9 — отлично.\n\nПочему важно: показывает насколько модель захватывает динамику продаж. Низкий R² = вы что-то упустили (промо, сезонность, конкуренты).',
    mape:   'MAPE (Mean Absolute Percentage Error) — средняя абсолютная ошибка прогноза в процентах.\n\nЧто это: на сколько процентов в среднем прогноз отличается от факта. < 10% — отлично, 10-20% — приемлемо, > 20% — плохо.\n\nПочему важно: дополняет R². Можно иметь высокий R² и большие отклонения в отдельных периодах — MAPE это ловит.',
    rHat:   'R-hat max (Gelman-Rubin) — максимальное значение меры сходимости по всем параметрам модели.\n\nЧто это: насколько разные цепи MCMC пришли к одному распределению (1.0 = идеально, ≤ 1.05 — сошлись, > 1.1 — нет).\n\nПочему важно: если цепи не сошлись — оценки ROI и доверительные интервалы ненадёжны, результаты случайны.',
    divs:   'Дивергенции (divergences) — количество шагов сэмплера NUTS, которые «соскочили» с траектории.\n\nЧто это: индикатор сложной геометрии posterior — модель плохо параметризована или priors слишком широкие.\n\nПочему важно: при divergences > 0 часть пространства параметров не исследована — оценки могут быть смещены. Цель = 0.',
    ratio:  'Ratio — отношение числа наблюдений к числу предикторов (каналов + controls).\n\nЧто это: «хватает ли данных модели, чтобы оценить все параметры». ≥ 4:1 — норма, ≥ 6:1 — идеал, < 2:1 — критически мало.\n\nПочему важно: при низком Ratio модель переобучается — R² получается высокий искусственно, а настоящий прогноз будет плохим. Aurora автоматически ограничивает MQS на тонких данных (cap 70 при Ratio<4, 50 при <2).',
    block:  'Техническая диагностика — детализация метрик, из которых считается MQS.\n\nЗелёная галочка — метрика в норме. Красный крестик или ⚠ — требует внимания.\n\nПолный гайд: кнопка «?» в шапке шага → раздел «Методология MMM».',
  };
</script>

{#if mqs}
  <div class="mqs-badge">
    <div class="mqs-header">
      <div
        class="mqs-score"
        style="--score-color: {mqs.color}"
        title="MQS (Model Quality Score) — общая агрегированная оценка качества модели от 0 до 100.&#10;&#10;Формула: R² (fit, 40%) + MAPE (точность прогноза, 30%) + сходимость MCMC (30%).&#10;&#10;Шкала: ≥ 80 — отлично, 60-80 — хорошо, 40-60 — приемлемо, < 40 — требует доработки."
      >
        <span class="score-title">MQS</span>
        <span class="score-value">{Math.round(mqs.score)}</span>
        <span class="score-label">{mqs.tier_label}</span>
      </div>
      <div class="mqs-verdict">
        <p>{verdict}</p>
      </div>
    </div>

    <button class="details-toggle" onclick={() => showDetails = !showDetails}>
      {showDetails ? '▾' : '▸'} Техническая диагностика<span class="help-icon" title={HELP.block}>?</span>
    </button>

    {#if showDetails}
      <div class="mqs-details">
        <div class="metric-row">
          <span class="metric-label">R²<span class="help-icon" title={HELP.rSq}>?</span></span>
          <span class="metric-value">{metrics.r_squared}</span>
          <span class="metric-check">{checks.fit ? '✓' : '✗'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">MAPE<span class="help-icon" title={HELP.mape}>?</span></span>
          <span class="metric-value">{metrics.mape_pct}%</span>
          <span class="metric-check">{metrics.mape_pct < 20 ? '✓' : '✗'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">R-hat max<span class="help-icon" title={HELP.rHat}>?</span></span>
          <span class="metric-value">{metrics.r_hat_max}</span>
          <span class="metric-check">{checks.convergence ? '✓' : '✗'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Divergences<span class="help-icon" title={HELP.divs}>?</span></span>
          <span class="metric-value">{metrics.divergences}</span>
          <span class="metric-check">{metrics.divergences === 0 ? '✓' : '✗'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Ratio<span class="help-icon" title={HELP.ratio}>?</span></span>
          <span class="metric-value">{metrics.ratio}:1</span>
          <span class="metric-check">{checks.ratio ? '✓' : '⚠'}</span>
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .mqs-badge {
    background: var(--bg-surface-quiet, rgba(30, 33, 44, 0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
  }

  .mqs-header {
    display: flex;
    gap: 16px;
    align-items: center;
  }

  .mqs-score {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 64px;
    padding: 12px;
    border-radius: 12px;
    background: rgba(0,0,0,0.3);
    border: 2px solid var(--score-color);
    cursor: help;
  }

  .score-title {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 4px;
  }

  .score-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--score-color);
    line-height: 1;
  }

  .score-label {
    font-size: 11px;
    color: var(--text-secondary, #94a3b8);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .mqs-verdict {
    flex: 1;
  }

  .mqs-verdict p {
    color: var(--text-primary, #e2e8f0);
    font-size: 14px;
    line-height: 1.5;
    margin: 0;
  }

  .details-toggle {
    display: block;
    width: 100%;
    padding: 8px 0 0;
    margin-top: 12px;
    border: none;
    border-top: 1px solid rgba(255,255,255,0.06);
    background: transparent;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    text-align: left;
  }

  .details-toggle:hover { color: var(--text-primary, #e2e8f0); }

  .mqs-details {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .metric-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    font-size: 12px;
  }

  .metric-label {
    color: var(--text-secondary, #94a3b8);
    min-width: 100px;
  }

  .metric-value {
    color: var(--text-primary, #e2e8f0);
    font-family: monospace;
    min-width: 80px;
  }

  .metric-check {
    font-size: 14px;
  }

  /* Inline tooltip-triggers — совпадает по стилю с ExpertModelPanel */
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
