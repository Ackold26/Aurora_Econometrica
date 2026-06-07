<script>
  /**
   * Model Quality Score badge - visual indicator with tier label.
   * Shows human-readable verdict + collapsible tech metrics.
   *
   * @component MQSBadge
   */
  import { invoke } from '@tauri-apps/api/core';

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

  // v2.1 (микро-справка-рычаг): «?» открывает страницу «Интерпретация
  // результатов» во внешнем браузере (полный разбор MQS, ROI, вердиктов,
  // переобучения). Тихо логируем ошибку, если open_help недоступен.
  function openInterpretationHelp() {
    invoke('open_help', { cabinetId: 'interpretation' }).catch((err) => console.error(err));
  }

  /** @type {any} */
  let mqs = $derived(diagnostics?.mqs || null);
  let backendVerdict = $derived(diagnostics?.verdict || '');
  let metrics = $derived(diagnostics?.metrics || {});
  let checks = $derived(diagnostics?.checks || {});
  // v2.1.0 (Pilot C): engine detection. OLS pickles set diagnostics.engine='ols'
  // и не имеют MCMC diagnostics (r_hat_max=null, divergences=null).
  let isOls = $derived(diagnostics?.engine === 'ols');

  // 2026-06-07 (INV-50): MQS теперь честный НА BACKEND — data-thinness cap
  // считается по ЭФФЕКТИВНОМУ ratio (posterior contraction = реальные степени
  // свободы; байес-приоры сжимают слабо-идентифицируемые параметры). Frontend
  // БОЛЬШЕ НЕ раскапывает score по media-only SSOT ratio: прежний override
  // выдавал переобучённую на тонких данных модель за «Отличное» 86, тогда как
  // честная оценка — «Хорошее» 70. Программа и ВСЕ отчёты (XLSX/PPTX/HTML)
  // показывают ОДИН источник истины: diagnostics.mqs. ssotRatio (наблюдений
  // на медиа-канал) остаётся отдельным data-sufficiency индикатором, но НЕ
  // влияет на MQS. См. memory: отчёты ≠ программа ревизия.
  const displayVerdict = $derived(backendVerdict);
  const displayMqs = $derived(mqs);

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
        <button
          type="button"
          class="mqs-help"
          onclick={openInterpretationHelp}
          title="Как читать MQS, ROI и вердикты — открыть «Интерпретацию результатов»"
        >? Как читать результаты</button>
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

  .mqs-help {
    margin-top: 8px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.12));
    color: var(--text-secondary, #94a3b8);
    font-size: 11.5px;
    font-family: inherit;
    padding: 3px 10px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .mqs-help:hover {
    color: var(--text-primary, #e2e8f0);
    border-color: var(--accent-primary, #58a6ff);
    background: var(--accent-glow, rgba(88,166,255,0.1));
  }

  .mqs-help:focus-visible {
    outline: 2px solid var(--accent-primary, #58a6ff);
    outline-offset: 1px;
  }

</style>
