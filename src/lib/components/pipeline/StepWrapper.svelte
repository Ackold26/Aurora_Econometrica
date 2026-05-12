<script>
  /**
   * StepWrapper - visibility-switched container for a single pipeline step.
   * A3: Uses opacity/visibility, NOT display:none, to preserve CSS transitions.
   * CLAUDE.md Rule 14: visibility, not display:none.
   */
  import { PIPELINE_STEPS, pipelineCurrentStep, pipelineStepMeta, validationHeaderMetrics } from '$lib/project-state.js';

  /** helpPage сохранён как prop для обратной совместимости с /pipeline/+page.svelte,
      но сама кнопка «?» больше здесь не рендерится - она переехала в header pipeline. */
  /** @type {{ step: number, helpPage?: string, children: import('svelte').Snippet }} */
  let { step, helpPage: _helpPage, children } = $props();

  const stepDef = $derived(PIPELINE_STEPS[step]);
  const meta = $derived($pipelineStepMeta[step]);
  const isActive = $derived(step === $pipelineCurrentStep);

  // На шаге Валидация (step=1) - sticky header с ключевыми параметрами
  // (Ratio / VIF / Период / MQS прогноз). Reactive через derived store -
  // обновляется автоматически при смене ролей columns или объективы.
  const validationMetrics = $derived(step === 1 ? $validationHeaderMetrics : null);
</script>

<!-- A3: visibility switching instead of display:none (preserves transitions, CLAUDE.md Rule 14) -->
<div
  class="step-wrapper"
  class:hidden={!isActive}
  role="tabpanel"
  aria-label={stepDef.labelRu}
  aria-hidden={!isActive}
>
  <div class="step-header">
    <span class="step-icon">{stepDef.icon}</span>
    <h2 class="step-title">{stepDef.labelRu}</h2>
    {#if validationMetrics}
      <div class="key-metrics" aria-label="Ключевые параметры валидации">
        <span class="metric-chip light-{validationMetrics.ratioStatus}" title="Ratio (наблюдений на параметр) - устойчивость оценок. ≥10 отлично, 4–10 приемлемо (широкие CI), <4 рискованно (overfitting).">
          <span class="metric-label">Ratio</span>
          <span class="metric-value">{validationMetrics.ratio.toFixed(1)}:1</span>
        </span>
        <span class="metric-chip light-{validationMetrics.vifStatus}" title="VIF max - коллинеарность медиа-каналов. ≤5 каналы независимы, 5–10 умеренная collinearity (CI шире), >10 модель не разделит вклады каналов.">
          <span class="metric-label">VIF max</span>
          <span class="metric-value">{validationMetrics.maxVif == null ? 'н/д' : validationMetrics.maxVif.toFixed(1)}</span>
        </span>
        <span class="metric-chip light-{validationMetrics.periodStatus}" title="Период наблюдений. ≥24 захват 2+ сезонов, 12–24 один сезон, <12 недостаточно для baseline сезонности.">
          <span class="metric-label">Период</span>
          <span class="metric-value">{validationMetrics.nObs}</span>
        </span>
        <span class="metric-chip light-{validationMetrics.mqsStatus}" title="MQS прогноз - комбинированная оценка готовности данных до обучения (на основе Ratio, VIF, периода). ≥80 модель будет точной, 60–80 приемлемая, <60 нужна доработка данных. Реальный MQS уточнится после обучения.">
          <span class="metric-label">MQS прогноз</span>
          <span class="metric-value">{validationMetrics.mqs}</span>
        </span>
      </div>
    {/if}
    {#if meta.status === 'complete'}
      <span class="step-badge complete">✓ Готово</span>
    {:else if meta.status === 'error'}
      <span class="step-badge error">✕ Ошибка{meta.errorMessage ? `: ${meta.errorMessage}` : ''}</span>
    {:else if meta.status === 'active'}
      <span class="step-badge active">● Выполняется</span>
    {/if}
  </div>

  <div class="step-content">
    {@render children()}
  </div>
</div>

<style>
  /* A3: visibility switching - NOT display:none */
  .step-wrapper {
    display: flex;
    flex-direction: column;
    height: 100%;
    opacity: 1;
    visibility: visible;
    transition: opacity 0.15s ease;
  }
  .step-wrapper.hidden {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    position: absolute;
    inset: 0;
    height: 100%;
  }

  .step-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px 12px;
    min-height: 52px;
    box-sizing: border-box;
    border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.06));
    flex-shrink: 0;
  }
  .step-icon { font-size: 18px; }
  .step-title {
    font-size: 17px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    margin: 0;
  }
  .step-badge {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 20px;
    font-weight: 500;
  }

  /* ── Key metrics для шапки Валидации (sticky, не прокручивается) ──── */
  .key-metrics {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .metric-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    line-height: 1.2;
    font-weight: 500;
    background: rgba(127, 127, 127, 0.08);
    border: 1px solid rgba(127, 127, 127, 0.2);
    color: var(--text-primary, #e2e8f0);
    cursor: help;
    transition: border-color 0.15s, background 0.15s;
  }
  .metric-chip .metric-label {
    color: var(--text-muted, #94a3b8);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .metric-chip .metric-value {
    font-weight: 700;
    font-size: 12px;
    color: var(--text-primary, #e2e8f0);
  }
  /* Светофор: muted hybrid стилистика (consistent c TrafficLight det-chip) */
  .metric-chip.light-ok   { background: color-mix(in srgb, var(--success) 12%, transparent); border-color: color-mix(in srgb, var(--success) 30%, transparent); }
  .metric-chip.light-warn { background: color-mix(in srgb, var(--warning) 12%, transparent); border-color: color-mix(in srgb, var(--warning) 30%, transparent); }
  .metric-chip.light-bad  { background: color-mix(in srgb, var(--danger)  12%, transparent); border-color: color-mix(in srgb, var(--danger)  30%, transparent); }
  .metric-chip.light-na   { background: rgba(127, 127, 127, 0.08); border-color: rgba(127, 127, 127, 0.2); }

  /* На step-badge нужен gap, чтобы не сливался с metrics */
  .key-metrics + .step-badge { margin-left: 8px; }
  .step-badge.complete {
    background: color-mix(in srgb, var(--success) 12%, transparent);
    color: var(--success, #22c55e);
  }
  .step-badge.error {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    color: var(--error, #ef4444);
  }
  .step-badge.active {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary, #3b82f6);
  }

  .step-content {
    flex: 1;
    min-height: 0;
    overflow: visible;
    padding: 24px;
  }
</style>
