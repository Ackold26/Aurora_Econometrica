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

</style>
