<script>
  /**
   * Model Quality Score badge - visual indicator with tier label.
   * Shows human-readable verdict + collapsible tech metrics.
   *
   * @component MQSBadge
   */

  /**
   * @type {{
   *   diagnostics: any,
   *   ssotRatio?: number
   * }}
   *
   * ssotRatio - v2.1.0 (пилот 2026-05-16) frontend SSOT ratio из
   * validationHeaderMetrics. Если передан и расходится с backend
   * diagnostics.metrics.ratio - используется он, чтобы юзер не видел
   * разные цифры в Валидации (3.9:1) и Модели (1.5:1).
   */
  let { diagnostics, ssotRatio = undefined } = $props();

  let showDetails = $state(false);

  /** @type {any} */
  let mqs = $derived(diagnostics?.mqs || null);
  let backendVerdict = $derived(diagnostics?.verdict || '');
  let metrics = $derived(diagnostics?.metrics || {});
  let checks = $derived(diagnostics?.checks || {});
  // v2.1.0 (Pilot C): engine detection. OLS pickles set diagnostics.engine='ols'
  // и не имеют MCMC diagnostics (r_hat_max=null, divergences=null).
  let isOls = $derived(diagnostics?.engine === 'ols');

  // v2.1.0 (пилот 2026-05-16): подменяем backend ratio в verdict-тексте
  // и пересчитываем MQS tier если SSOT ratio >= 4 (info / success коридоры).
  // Backend thinness_cap=50 при backend ratio<2 ставит «Слабое», что
  // несовместимо с frontend SSOT «Ниже рекомендуемого» (4.4:1) или
  // «Рекомендуемый уровень». Дотягиваем UI consistency без переписи backend.
  const useSsot = $derived(
    typeof ssotRatio === 'number' && Number.isFinite(ssotRatio) && ssotRatio > 0
  );

  const displayVerdict = $derived.by(() => {
    if (!useSsot) return backendVerdict;
    // Заменяем числовое значение ratio в верндикте. Patterns которые
    // встречаются в backend `generate_diagnostics_summary`:
    //   «Ratio 1.5:1»
    //   «Ratio 1.5:1 < 4:1»
    // Также заменяем тестовую часть «Данных критически мало / Данных мало»
    // когда SSOT даёт другой коридор.
    let v = backendVerdict;
    // 1) Подменить число в "Ratio X.X:1"
    v = v.replace(/Ratio\s+\d+(?:\.\d+)?:1/g, `Ratio ${(ssotRatio ?? 0).toFixed(1)}:1`);
    // 2) Если SSOT ratio >= 4 - убрать «критически мало» / «мало (Ratio < 4:1)»
    if ((ssotRatio ?? 0) >= 4) {
      v = v.replace(
        /⚠\s*Данных (критически\s*)?мало[^.]*\.\s*/g,
        ''
      );
      v = v.replace(
        /\s*-\s*высокий риск переобучения[^.]*\.\s*/g,
        '. '
      );
      // F-011 pilot (2026-05-18): backend verdict для thin-data случая включает
      // «Результаты ненадёжны - нужно больше данных или другая спецификация»
      // и «объясняет только N%». При SSOT ratio>=4 + good MQS этот тон
      // противоречит «Отличное» badge. Убираем pessimistic clauses.
      v = v.replace(
        /Результаты ненадёжны\s*[—–-]?\s*нужно больше данных[^.]*\.\s*/g,
        ''
      );
      v = v.replace(
        /объясняет\s+только\s+/g,
        'объясняет '
      );
    }
    return v.trim();
  });

  const displayMqs = $derived.by(() => {
    if (!mqs || !useSsot) return mqs;
    // Backend применил thinness_cap (50 / 70) на основе backend ratio.
    // Если SSOT ratio в info / success коридоре - используем raw_score и
    // пересчитаем tier_label.
    if ((ssotRatio ?? 0) < 4) return mqs;  // оставляем backend cap
    const rawScore = Number(mqs.raw_score ?? mqs.score ?? 0);
    if (!Number.isFinite(rawScore) || rawScore <= mqs.score) return mqs;
    let tier, tier_label, color;
    if (rawScore >= 85) {
      tier = 'excellent'; tier_label = 'Отличное'; color = '#22c55e';
    } else if (rawScore >= 70) {
      tier = 'good'; tier_label = 'Хорошее'; color = '#3b82f6';
    } else if (rawScore >= 55) {
      tier = 'acceptable'; tier_label = 'Приемлемое'; color = '#f59e0b';
    } else if (rawScore >= 40) {
      tier = 'weak'; tier_label = 'Слабое'; color = '#f97316';
    } else {
      tier = 'poor'; tier_label = 'Ненадёжное'; color = '#ef4444';
    }
    return { ...mqs, score: Math.round(rawScore * 10) / 10, tier, tier_label, color };
  });

  // Общая подсказочная база - синхронизирована с ExpertModelPanel.svelte.
  const HELP = {
    rSq:    'R² (коэффициент детерминации) - доля вариации KPI, объяснённая моделью.\n\nЧто это: 0 = модель не лучше среднего, 1 = идеальный fit. ≥ 0.7 - хорошо, ≥ 0.9 - отлично.\n\nПочему важно: показывает насколько модель захватывает динамику продаж. Низкий R² = вы что-то упустили (промо, сезонность, конкуренты).',
    mape:   'MAPE (Mean Absolute Percentage Error) - средняя абсолютная ошибка прогноза в процентах.\n\nЧто это: на сколько процентов в среднем прогноз отличается от факта. < 10% - отлично, 10-20% - приемлемо, > 20% - плохо.\n\nПочему важно: дополняет R². Можно иметь высокий R² и большие отклонения в отдельных периодах - MAPE это ловит.',
    rHat:   'R-hat max (Gelman-Rubin) - максимальное значение меры сходимости по всем параметрам модели.\n\nЧто это: насколько разные цепи MCMC пришли к одному распределению (1.0 = идеально, ≤ 1.05 - сошлись, > 1.1 - нет).\n\nПочему важно: если цепи не сошлись - оценки ROI и доверительные интервалы ненадёжны, результаты случайны.',
    divs:   'Дивергенции (divergences) - количество шагов сэмплера NUTS, которые «соскочили» с траектории.\n\nЧто это: индикатор сложной геометрии posterior - модель плохо параметризована или priors слишком широкие.\n\nПочему важно: при divergences > 0 часть пространства параметров не исследована - оценки могут быть смещены. Цель = 0.',
    ratio:  'Ratio - отношение числа наблюдений к числу предикторов (каналов + controls).\n\nЧто это: «хватает ли данных модели, чтобы оценить все параметры». ≥ 4:1 - норма, ≥ 6:1 - идеал, < 2:1 - критически мало.\n\nПочему важно: при низком Ratio модель переобучается - R² получается высокий искусственно, а настоящий прогноз будет плохим. Aurora автоматически ограничивает MQS на тонких данных (cap 70 при Ratio<4, 50 при <2).',
    block:  'Техническая диагностика - детализация метрик, из которых считается MQS.\n\nЗелёная галочка - метрика в норме. Красный крестик или ⚠ - требует внимания.\n\nПолный гайд: кнопка «?» в шапке шага → раздел «Методология MMM».',
  };
</script>

{#if displayMqs}
  <div class="mqs-badge">
    <div class="mqs-header">
      <div
        class="mqs-score"
        style="--score-color: {displayMqs.color}"
        title={isOls
          ? "MQS (Model Quality Score) - общая агрегированная оценка качества модели от 0 до 100.\n\nФормула: R² (fit, 40%) + MAPE (точность прогноза, 30%) + надёжность оценок (bootstrap, 30%).\n\nШкала: ≥ 80 - отлично, 60-80 - хорошо, 40-60 - приемлемо, < 40 - требует доработки."
          : "MQS (Model Quality Score) - общая агрегированная оценка качества модели от 0 до 100.\n\nФормула: R² (fit, 40%) + MAPE (точность прогноза, 30%) + сходимость MCMC (30%).\n\nШкала: ≥ 80 - отлично, 60-80 - хорошо, 40-60 - приемлемо, < 40 - требует доработки."}
      >
        <span class="score-title">MQS</span>
        <span class="score-value">{Math.round(displayMqs.score)}</span>
        <span class="score-label">{displayMqs.tier_label}</span>
      </div>
      <div class="mqs-verdict">
        <p>{displayVerdict}</p>
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
        {#if !isOls && metrics.r_hat_max != null}
          <div class="metric-row">
            <span class="metric-label">R-hat max<span class="help-icon" title={HELP.rHat}>?</span></span>
            <span class="metric-value">{metrics.r_hat_max}</span>
            <span class="metric-check">{checks.convergence ? '✓' : '✗'}</span>
          </div>
        {/if}
        {#if !isOls && metrics.divergences != null}
          <div class="metric-row">
            <span class="metric-label">Divergences<span class="help-icon" title={HELP.divs}>?</span></span>
            <span class="metric-value">{metrics.divergences}</span>
            <span class="metric-check">{metrics.divergences === 0 ? '✓' : '✗'}</span>
          </div>
        {/if}
        <div class="metric-row">
          <span class="metric-label">Ratio<span class="help-icon" title={HELP.ratio}>?</span></span>
          <span class="metric-value">{useSsot ? (ssotRatio ?? 0).toFixed(1) : metrics.ratio}:1</span>
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

  /* Inline tooltip-triggers - совпадает по стилю с ExpertModelPanel */
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
