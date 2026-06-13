<script>
  /**
   * Multi-scenario comparison route - v2.0.0 (ADR-019 §7).
   *
   * Page shown после Optimize stage когда у project есть ≥2 scenarios.
   * Embeds MultiScenarioPage с overlay chart, comparison table,
   * diff narratives, export actions.
   *
   * Phase E (2026-06-13): wired к реальным данным движка —
   *  baseline-история = modelData.diagnostics.actual_vs_predicted (model fit),
   *  прогнозные хвосты + per-period CI-веер = econ_compare().scenarios[].
   *  Сборка таймлайна доказана probe `tools/probe_forecast_scenarios_kagocel.py`.
   *
   * @route /pipeline/compare
   */
  import MultiScenarioPage from '$lib/components/pipeline/MultiScenarioPage.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import { activeProjectId, unitCosts, modelData } from '$lib/project-state.js';
  import { assembleScenarioTimeline } from '$lib/forecast-timeline.js';

  /** @type {any[]} */
  let scenarios = $state([]);
  /** @type {any} */
  let baseline = $state(null);
  let loading = $state(true);
  /** @type {string | null} */
  let loadError = $state(null);

  // Нейтрально: chart рисует predictions[] в НАТИВНОЙ единице KPI модели (для count-KPI
  // это штуки, не ₽) — money-конверсия применяется только к табличным полям внутри сборки.
  const kpiLabel = 'Прогноз продаж';

  /**
   * Загрузить сохранённые сценарии + baseline-историю и собрать единый таймлайн.
   * Переиспользуется при mount и после удаления сценария.
   */
  async function loadScenarios() {
    loading = true;
    loadError = null;
    try {
      const projectId = get(activeProjectId);
      if (!projectId) {
        loadError = 'Проект не выбран — откройте проект на шаге «Данные».';
        scenarios = [];
        baseline = null;
        return;
      }
      const projectDir = await invoke('project_get_dir', { projectId });
      const uc = get(unitCosts) ?? {};
      const result = /** @type {any} */ (await invoke('econ_compare', {
        projectDir,
        unitCosts: Object.keys(uc).length > 0 ? uc : null,
      }));

      if (result?.status !== 'ok') {
        // Нет сохранённых сценариев — это НЕ ошибка, а пустое состояние с CTA.
        scenarios = [];
        baseline = null;
        return;
      }

      const diag = get(modelData)?.diagnostics ?? null;
      const assembled = assembleScenarioTimeline(result, diag);
      scenarios = assembled.scenarios;
      baseline = assembled.baseline;
    } catch (/** @type {any} */ e) {
      loadError = String(e);
      scenarios = [];
      baseline = null;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void loadScenarios();
  });

  /** @param {any} scenario */
  function handleAccept(scenario) {
    // Сценарий уже сохранён (артефакт шага Optimize) — «принять» = выбрать и вернуться.
    console.log('[Compare] Accept scenario:', scenario?.name);
    goto('/pipeline');
  }

  /** @param {any} scenario */
  async function handleDelete(scenario) {
    const projectId = get(activeProjectId);
    if (!projectId || !scenario?.name) return;
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const r = /** @type {any} */ (await invoke('econ_scenario_delete', {
        projectDir,
        scenarioName: scenario.name,
      }));
      if (r?.status === 'ok') {
        await loadScenarios();
      } else {
        loadError = r?.message || 'Не удалось удалить сценарий';
      }
    } catch (/** @type {any} */ e) {
      loadError = String(e);
    }
  }
</script>

<svelte:head>
  <title>Aurora MMM Optimizer - Сравнение сценариев</title>
</svelte:head>

<main class="compare-route">
  <header class="route-header">
    <button class="back-link" onclick={() => goto('/pipeline')}>← Назад к pipeline</button>
    <h1>Прогноз продаж по сценариям</h1>
  </header>

  {#if loading}
    <div class="state-box">Загрузка сценариев…</div>
  {:else if loadError}
    <div class="state-box state-error" role="alert">{loadError}</div>
  {:else}
    {#if !baseline}
      <div class="state-box state-hint">
        История модели недоступна — постройте модель и декомпозицию, чтобы увидеть
        факт+прогноз на одном таймлайне. Сценарии ниже показаны без исторической линии.
      </div>
    {/if}
    <MultiScenarioPage
      {scenarios}
      {baseline}
      {kpiLabel}
      onAccept={handleAccept}
      onDelete={handleDelete}
    />
  {/if}
</main>

<style>
  .compare-route {
    padding: 24px 32px;
    max-width: 1400px;
    margin: 0 auto;
  }
  .route-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }
  .route-header h1 {
    margin: 0;
    font-size: 22px;
    color: var(--text-primary);
  }
  .back-link {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 6px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
  }
  .back-link:hover {
    border-color: var(--gold, #c9a449);
    color: var(--gold, #c9a449);
  }
  .state-box {
    padding: 16px 18px;
    border-radius: 10px;
    background: var(--bg-card, #181824);
    border: 1px solid var(--border, rgba(255,255,255,0.08));
    color: var(--text-secondary);
    font-size: 14px;
    margin-bottom: 16px;
  }
  .state-error {
    border-color: color-mix(in srgb, #ef4444 40%, transparent);
    color: #fca5a5;
  }
  .state-hint {
    border-color: color-mix(in srgb, var(--warning, #F59E0B) 30%, transparent);
    color: var(--warning, #F59E0B);
  }
</style>
