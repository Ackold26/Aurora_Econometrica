<script>
  /**
   * Pipeline main page.
   * A3: ONE route with visibility switching — no dynamic [step] routing.
   *     All 6 step components rendered simultaneously; CSS controls which is visible.
   *     CLAUDE.md Rule 14: visibility/opacity, not display:none.
   */
  import StepWrapper from '$lib/components/pipeline/StepWrapper.svelte';
  import ImportStep from '$lib/components/pipeline/ImportStep.svelte';
  import ValidateStep from '$lib/components/pipeline/ValidateStep.svelte';
  import { completeStep } from '$lib/project-state.js';
</script>

<!-- A3: Single route, all steps present in DOM, visibility controlled by StepWrapper -->
<div class="pipeline-page">

  <!-- Step 0: Import — Phase 2 -->
  <StepWrapper step={0}>
    <ImportStep />
  </StepWrapper>

  <!-- Step 1: Validate — Phase 2 -->
  <StepWrapper step={1}>
    <ValidateStep />
  </StepWrapper>

  <!-- Step 2: Model -->
  <StepWrapper step={2}>
    <div class="step-placeholder">
      <div class="placeholder-icon">🧠</div>
      <h3>Обучение модели</h3>
      <p>Bayesian Marketing Mix Model (PyMC-Marketing) с adstock и saturation.</p>
      <p class="note">ConfigPanel + ConvergenceDashboard (ECharts) — Фаза 3</p>
      <button class="dev-btn" onclick={() => completeStep(2)}>
        Dev: отметить готово →
      </button>
    </div>
  </StepWrapper>

  <!-- Step 3: Decompose -->
  <StepWrapper step={3}>
    <div class="step-placeholder">
      <div class="placeholder-icon">🔬</div>
      <h3>Декомпозиция</h3>
      <p>Waterfall: разбивка продаж по каналам, базовому уровню и контрольным переменным.</p>
      <p class="note">ECharts waterfall + channel contribution bar — Фаза 3</p>
      <button class="dev-btn" onclick={() => completeStep(3)}>
        Dev: отметить готово →
      </button>
    </div>
  </StepWrapper>

  <!-- Step 4: Optimize -->
  <StepWrapper step={4}>
    <div class="step-placeholder">
      <div class="placeholder-icon">🎯</div>
      <h3>Оптимизация бюджета</h3>
      <p>Интерактивный оптимизатор с draggable слайдерами и marginal ROI кривыми.</p>
      <p class="note">Hill function client-side + ECharts graphic draggable — Фаза 4 (аудит B1)</p>
      <button class="dev-btn" onclick={() => completeStep(4)}>
        Dev: отметить готово →
      </button>
    </div>
  </StepWrapper>

  <!-- Step 5: Report -->
  <StepWrapper step={5}>
    <div class="step-placeholder">
      <div class="placeholder-icon">📋</div>
      <h3>Отчёт</h3>
      <p>Executive summary, экспорт в PowerPoint и PDF. AI-интерпретация результатов.</p>
      <p class="note">PPTX pipeline + AI narrative — Фаза 5</p>
    </div>
  </StepWrapper>

</div>

<style>
  .pipeline-page {
    /* Relative container so absolute-positioned hidden steps don't leak */
    position: relative;
    height: 100%;
    overflow: hidden;
  }

  /* Step placeholder styles (Phases 2-5 will replace with real components) */
  .step-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 48px 32px;
    text-align: center;
    height: 100%;
    box-sizing: border-box;
  }
  .placeholder-icon { font-size: 52px; line-height: 1; }
  h3 {
    font-size: 22px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
    margin: 0;
  }
  p {
    font-size: 14px;
    color: var(--text-secondary, #94a3b8);
    margin: 0;
    max-width: 500px;
    line-height: 1.6;
  }
  .note {
    font-size: 11px;
    color: rgba(148,163,184,0.45);
    font-style: italic;
  }

  /* Dev shortcut button — visible only in dev, styled subtly */
  .dev-btn {
    margin-top: 8px;
    padding: 6px 16px;
    background: rgba(59,130,246,0.1);
    border: 1px dashed rgba(59,130,246,0.3);
    border-radius: 6px;
    color: rgba(59,130,246,0.7);
    font-size: 11px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .dev-btn:hover {
    background: rgba(59,130,246,0.18);
    border-color: var(--accent-primary, #3b82f6);
    color: var(--accent-primary, #3b82f6);
  }
</style>
