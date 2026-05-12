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

  // UX audit v1.3.0: open by default на первых 2 шагах (Import / Validate) для novice.
  // На остальных collapsed — юзер уже знает контекст.
  const shouldOpenByDefault = $derived($pipelineCurrentStep <= 1);
</script>

{#if !$hideEducationalHints && currentHelp}
  {#key currentStepId}
    <WhyThisStep
      stepId={currentStepId}
      title={currentHelp.title}
      whatWeDo={currentHelp.whatWeDo}
      whyNeed={currentHelp.whyNeed}
      attentionTo={currentHelp.attentionTo}
      whatsNext={currentHelp.whatsNext}
      defaultOpen={shouldOpenByDefault}
    />
  {/key}
{/if}
