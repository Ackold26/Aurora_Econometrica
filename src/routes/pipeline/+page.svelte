<script>
  /**
   * Pipeline main page.
   * A3: ONE route with visibility switching - no dynamic [step] routing.
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
  import { useDerivedModeUX, validateData } from '$lib/project-state.js';

  // Audit fix v1.3.0 (red-team review BLOCKER #1):
  // ValidateStepV13 нуждается в реальных каналах из validate result + auto-detected
  // available metrics per канал. Hardcoded {} раньше делал компонент бесполезным
  // в production. Теперь reads из validateData store + computes available metrics
  // через column names heuristic (separator-aware regex mirrors backend column_detection).
  const channels = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return [];
    return cols
      .filter((/** @type {any} */ c) => c?.role === 'media')
      .map((/** @type {any} */ c) => c.name);
  });

  const availableMetricsByChannel = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols) || channels.length === 0) return {};
    /** @type {Record<string, {monetary: string[], physical: string[]}>} */
    const result = {};
    for (const ch of channels) {
      result[ch] = { monetary: [], physical: [] };
    }
    // Classify каждую media column: name содержит ₽-marker (spend|budget|cost|бюджет|расход|rub)
    // → monetary; impressions|clicks|grp|показ|клик|грп → physical.
    const monetaryRe = /(?:^|[_\s-])(?:spend(?:s|ing)?|budget|cost(?:s)?|expense|бюджет|расход|затрат|rub|usd|eur)(?:[_\s-]|$)/i;
    const physicalRe = /(?:^|[_\s-])(?:impression|impr|click|visit|reach|contact|grp|trp|показ|клик|визит|охват|просмотр|грп|трп)(?:[_\s-]|$)/i;
    for (const c of cols) {
      if (c?.role !== 'media') continue;
      const name = c.name;
      // Try to match channel prefix (e.g. 'tv_spend' → channel 'tv').
      for (const ch of channels) {
        const lower = name.toLowerCase();
        const chLower = ch.toLowerCase();
        if (lower === chLower || lower.startsWith(chLower + '_') || lower.startsWith(chLower + '-') || lower.startsWith(chLower + ' ')) {
          if (monetaryRe.test(name)) result[ch].monetary.push(name);
          else if (physicalRe.test(name)) result[ch].physical.push(name);
          else result[ch].monetary.push(name);  // unknown - default monetary
          break;
        }
      }
      // If no channel prefix match - channel name === column name → default monetary.
      if (result[name]) result[name].monetary.push(name);
    }
    return result;
  });

  // v1.3.2: column stats lookup для PerChannelInputSelector — позволяет
  // показать data quality preview (zeros%/missing%) per metric option.
  const columnStats = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return {};
    /** @type {Record<string, {zeros_pct: number, missing_pct: number}>} */
    const stats = {};
    for (const c of cols) {
      if (c?.name && c?.stats) {
        stats[c.name] = {
          zeros_pct: Number(c.stats.zeros_pct ?? 0),
          missing_pct: Number(c.stats.missing_pct ?? 0),
        };
      }
    }
    return stats;
  });
</script>

<!-- A3: Single route, all steps present in DOM, visibility controlled by StepWrapper -->
<div class="pipeline-page">

  <!-- v1.3.0: «Зачем этот шаг?» panel - global header per pipelineCurrentStep -->
  <PipelineWhyThisStep />

  <!-- Step 0: Import - Phase 2 -->
  <StepWrapper step={0} helpPage="data-preparation">
    <ImportStep />
  </StepWrapper>

  <!-- Step 1: Validate - Phase 2 / v1.3.0 derived mode (per ADR-015) -->
  <StepWrapper step={1} helpPage="data-preparation">
    {#if $useDerivedModeUX}
      <ValidateStepV13 channels={channels} availableMetricsByChannel={availableMetricsByChannel} columnStats={columnStats} />
    {:else}
      <ValidateStep />
    {/if}
  </StepWrapper>

  <!-- Step 2: Model - Phase 3 -->
  <StepWrapper step={2} helpPage="methodology">
    <ModelTrainingStep />
  </StepWrapper>

  <!-- Step 3: Decompose - Phase 4A -->
  <StepWrapper step={3} helpPage="pipeline">
    <DecomposeStep />
  </StepWrapper>

  <!-- Step 4: Optimize - Phase 4B -->
  <StepWrapper step={4} helpPage="pipeline">
    <OptimizeStep />
  </StepWrapper>

  <!-- Step 5: Report - Phase 5 -->
  <StepWrapper step={5} helpPage="pipeline">
    <ReportStep />
  </StepWrapper>

</div>

<style>
  .pipeline-page {
    /* Relative container so absolute-positioned hidden steps don't leak.
       NO overflow here - scrolling is owned by .pipeline-main (parent).
       Double-scroll containers caused phantom scroll into empty space. */
    position: relative;
    height: 100%;
  }
</style>
