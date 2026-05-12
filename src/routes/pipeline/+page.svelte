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
  import ValidateStepV13 from '$lib/components/pipeline/ValidateStepV13.svelte';
  import ModelTrainingStep from '$lib/components/pipeline/ModelTrainingStep.svelte';
  import DecomposeStep from '$lib/components/pipeline/DecomposeStep.svelte';
  import OptimizeStep from '$lib/components/pipeline/OptimizeStep.svelte';
  import ReportStep from '$lib/components/pipeline/ReportStep.svelte';
  import PipelineWhyThisStep from '$lib/components/pipeline/PipelineWhyThisStep.svelte';
  import { useDerivedModeUX } from '$lib/project-state.js';
</script>

<!-- A3: Single route, all steps present in DOM, visibility controlled by StepWrapper -->
<div class="pipeline-page">

  <!-- v1.3.0: «Зачем этот шаг?» panel — global header per pipelineCurrentStep -->
  <PipelineWhyThisStep />

  <!-- Step 0: Import — Phase 2 -->
  <StepWrapper step={0} helpPage="data-preparation">
    <ImportStep />
  </StepWrapper>

  <!-- Step 1: Validate — Phase 2 / v1.3.0 derived mode (per ADR-015) -->
  <StepWrapper step={1} helpPage="data-preparation">
    {#if $useDerivedModeUX}
      <ValidateStepV13 channels={[]} availableMetricsByChannel={{}} />
    {:else}
      <ValidateStep />
    {/if}
  </StepWrapper>

  <!-- Step 2: Model — Phase 3 -->
  <StepWrapper step={2} helpPage="methodology">
    <ModelTrainingStep />
  </StepWrapper>

  <!-- Step 3: Decompose — Phase 4A -->
  <StepWrapper step={3} helpPage="pipeline">
    <DecomposeStep />
  </StepWrapper>

  <!-- Step 4: Optimize — Phase 4B -->
  <StepWrapper step={4} helpPage="pipeline">
    <OptimizeStep />
  </StepWrapper>

  <!-- Step 5: Report — Phase 5 -->
  <StepWrapper step={5} helpPage="pipeline">
    <ReportStep />
  </StepWrapper>

</div>

<style>
  .pipeline-page {
    /* Relative container so absolute-positioned hidden steps don't leak.
       NO overflow here — scrolling is owned by .pipeline-main (parent).
       Double-scroll containers caused phantom scroll into empty space. */
    position: relative;
    height: 100%;
  }
</style>
