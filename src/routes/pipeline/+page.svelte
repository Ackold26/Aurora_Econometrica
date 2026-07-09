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
  import PlanningStep from '$lib/components/pipeline/PlanningStep.svelte';
  import ReportStep from '$lib/components/pipeline/ReportStep.svelte';
  import PipelineWhyThisStep from '$lib/components/pipeline/PipelineWhyThisStep.svelte';
  import FirstRunTour from '$lib/components/FirstRunTour.svelte';
  import { useDerivedModeUX, validateData } from '$lib/project-state.js';
  import { groupChannelColumns } from '$lib/channel-pairs.js';
  import { onMount } from 'svelte';

  const FIRST_RUN_TOUR_KEY = 'aurora.firstRunTourCompleted';

  /** Показывать ли первый тур */
  let showFirstRunTour = $state(false);

  onMount(() => {
    if (typeof window === 'undefined') return;
    try {
      const done = window.localStorage.getItem(FIRST_RUN_TOUR_KEY);
      if (!done) showFirstRunTour = true;
    } catch { /* ok - localStorage blocked */ }
  });

  // Audit fix v1.3.0 (red-team review BLOCKER #1):
  // ValidateStepV13 нуждается в реальных каналах из validate result + auto-detected
  // available metrics per канал. Hardcoded {} раньше делал компонент бесполезным
  // в production. Теперь reads из validateData store + computes available metrics
  // через column names heuristic (separator-aware regex mirrors backend column_detection).
  // ПАРЫ (2026-07-05, решение Антона): media-колонки группируются в КАНАЛЫ по
  // базе имени (tv_spend + tv_trp → канал «tv» с живым выбором ₽|TRP) — единый
  // чистый модуль channel-pairs.js (vitest). Прежняя inline-группировка
  // фактически не спаривала (channels = полные имена колонок → prefix-матч
  // никогда не находил партнёра); парные файлы впервые появились вместе с
  // обновлёнными примерами — логика нагружена и закрыта тестами.
  const pairGroups = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return { channels: [], byChannel: {} };
    const media = cols
      .filter((/** @type {any} */ c) => c?.role === 'media')
      .map((/** @type {any} */ c) => String(c.name));
    return groupChannelColumns(media);
  });
  const channels = $derived(pairGroups.channels);
  const availableMetricsByChannel = $derived(pairGroups.byChannel);

  // v1.3.2: column stats lookup для PerChannelInputSelector - позволяет
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

{#if showFirstRunTour}
  <FirstRunTour onDone={() => { showFirstRunTour = false; }} />
{/if}

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

  <!-- Step 5: Planning - Phase 2 planning mode -->
  <StepWrapper step={5} helpPage="pipeline">
    <PlanningStep />
  </StepWrapper>

  <!-- Step 6: Report - Phase 5 -->
  <StepWrapper step={6} helpPage="pipeline">
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
