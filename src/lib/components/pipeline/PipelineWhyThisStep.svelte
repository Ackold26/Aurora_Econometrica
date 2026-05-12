<script>
  /**
   * PipelineWhyThisStep — global header in pipeline page.
   * Renders WhyThisStep with content из contextual-help.json для текущего шага.
   * Hidden если $hideEducationalHints (Settings toggle).
   *
   * @component PipelineWhyThisStep
   */

  import { pipelineCurrentStep } from '$lib/project-state.js';
  import { hideEducationalHints } from '$lib/project-state.js';
  import contextualHelp from '$lib/contextual-help.json';
  import WhyThisStep from './WhyThisStep.svelte';

  /** @type {Record<number, string>} */
  const stepIdMap = {
    0: 'import',
    1: 'validate',
    2: 'model',
    3: 'decompose',
    4: 'optimize',
    5: 'report',
  };

  const currentStepId = $derived(stepIdMap[$pipelineCurrentStep] ?? 'validate');
  const currentHelp = $derived(/** @type {any} */ (contextualHelp)[currentStepId]);
</script>

{#if !$hideEducationalHints && currentHelp}
  <WhyThisStep
    stepId={currentStepId}
    title={currentHelp.title}
    whatWeDo={currentHelp.whatWeDo}
    whyNeed={currentHelp.whyNeed}
    attentionTo={currentHelp.attentionTo}
    whatsNext={currentHelp.whatsNext}
    defaultOpen={false}
  />
{/if}
