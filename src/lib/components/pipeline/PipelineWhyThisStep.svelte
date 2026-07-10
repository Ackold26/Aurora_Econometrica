<script>
  /**
   * PipelineWhyThisStep - global header in pipeline page.
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
    5: 'planning', // 7-шаговый пайплайн: сдвиг индексов (был report → «Зачем шаг „Отчёт"?» на Планировании)
    6: 'report',
  };

  const currentStepId = $derived(stepIdMap[$pipelineCurrentStep] ?? 'validate');
  const currentHelp = $derived(/** @type {any} */ (contextualHelp)[currentStepId]);

  // v2.1+ first-visit auto-open: панель «Зачем шаг» автоматически раскрыта
  // при первом посещении каждого шага в данной инсталляции (per-step
  // localStorage flag). После первого открытия — collapsed по умолчанию
  // (юзер уже видел content, дальше открывает explicit кликом, когда нужно).
  //
  // Rationale: WhyThisStep — самый ценный обучающий контент (3-4 структурных
  // блока: что делаем / зачем / на что обратить внимание / что дальше).
  // До v2.1 был collapsed=false на ВСЕХ шагах (включая первое посещение) —
  // новый менеджер просто не знал что content существует. Auto-open per
  // first-visit решает discovery без раздражения опытного пользователя
  // (повторно не открывается).
  //
  // Master switch остаётся через `hideEducationalHints` (Settings → Скрыть
  // подсказки / Эксперт-режим) — если on, панель вообще не рендерится,
  // auto-open irrelevant.

  let shouldOpenByDefault = $state(false);

  $effect(() => {
    if (typeof localStorage === 'undefined') return; // SSR safety
    // ONBOARD-1 (2026-06-04): не авто-раскрывать пока FirstRunTour не пройден/пропущен —
    // иначе WhyThisStep наслаивается на тур на pipeline-входе (тур поверх backdrop, панель
    // под ним). Зеркало coach-marks guard (onboarding-state.shouldShowOnboarding). После
    // тура — обычный auto-open per-first-visit. Master switch hideEducationalHints выше.
    if (localStorage.getItem('aurora.firstRunTourCompleted') === null) {
      shouldOpenByDefault = false;
      return;
    }
    const visitedKey = `aurora.whyThisStep.visited.${currentStepId}`;
    if (!localStorage.getItem(visitedKey)) {
      shouldOpenByDefault = true;
      localStorage.setItem(visitedKey, '1');
    } else {
      shouldOpenByDefault = false;
    }
  });
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
