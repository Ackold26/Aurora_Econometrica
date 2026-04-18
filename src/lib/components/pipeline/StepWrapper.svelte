<script>
  /**
   * StepWrapper — visibility-switched container for a single pipeline step.
   * A3: Uses opacity/visibility, NOT display:none, to preserve CSS transitions.
   * CLAUDE.md Rule 14: visibility, not display:none.
   */
  import { PIPELINE_STEPS, pipelineCurrentStep, pipelineStepMeta } from '$lib/project-state.js';

  /** @type {{ step: number, children: import('svelte').Snippet }} */
  let { step, children } = $props();

  const stepDef = $derived(PIPELINE_STEPS[step]);
  const meta = $derived($pipelineStepMeta[step]);
  const isActive = $derived(step === $pipelineCurrentStep);
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
  /* A3: visibility switching — NOT display:none */
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
    margin-left: auto;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 20px;
    font-weight: 500;
  }
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
