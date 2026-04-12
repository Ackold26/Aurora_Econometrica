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
  import ModelTrainingStep from '$lib/components/pipeline/ModelTrainingStep.svelte';
  import DecomposeStep from '$lib/components/pipeline/DecomposeStep.svelte';
  import OptimizeStep from '$lib/components/pipeline/OptimizeStep.svelte';
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

  <!-- Step 2: Model — Phase 3 -->
  <StepWrapper step={2}>
    <ModelTrainingStep />
  </StepWrapper>

  <!-- Step 3: Decompose — Phase 4A -->
  <StepWrapper step={3}>
    <DecomposeStep />
  </StepWrapper>

  <!-- Step 4: Optimize — Phase 4B -->
  <StepWrapper step={4}>
    <OptimizeStep />
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
