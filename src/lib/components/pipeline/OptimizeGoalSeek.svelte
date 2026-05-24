<script>
  /**
   * OptimizeGoalSeek - v1.3.0 inverse optimization UI (per ADR-014).
   *
   * Юзер задаёт целевые продажи, система ищет минимальный бюджет.
   * Использует backend `econ_optimize_inverse` через bisection.
   *
   * @component OptimizeGoalSeek
   */

  import { invoke } from '@tauri-apps/api/core';
  import {
    activeProjectId,
    kpiKind,
    derivedMode,
    valuePerCountUnit,
    planningMode,
    forecastConfig,
  } from '$lib/project-state.js';
  import { get } from 'svelte/store';
  import CorridorSlider from './CorridorSlider.svelte';
  import GoalSeekResultCard from './GoalSeekResultCard.svelte';
  import WhyThisStep from './WhyThisStep.svelte';

  const { currentSales = 0, salesCorridor } = $props();

  // Target slider state.
  let targetSales = $state(currentSales);
  /** @type {number | null} */
  let maxBudgetCap = $state(null);
  /** @type {any | null} */
  let result = $state(null);
  let busy = $state(false);
  /** @type {string | null} */
  let errorMessage = $state(null);
  /** @type {'green' | 'yellow' | 'red'} */
  let currentZone = $state('green');

  const corridorLo = $derived(salesCorridor?.lo ?? Math.max(0, currentSales * 0.7));
  const corridorHi = $derived(salesCorridor?.hi ?? currentSales * 1.5);

  // Auto-reset target into corridor if outside.
  $effect(() => {
    if (currentSales > 0 && targetSales === 0) {
      targetSales = currentSales;
    }
  });

  /** @param {number} n */
  function formatTarget(n) {
    if ($kpiKind === 'monetary') {
      if (n >= 1e9) return `${(n / 1e9).toFixed(2)} млрд ₽`;
      if (n >= 1e6) return `${(n / 1e6).toFixed(1)} млн ₽`;
      return `${Math.round(n).toLocaleString('ru-RU')} ₽`;
    }
    return `${Math.round(n).toLocaleString('ru-RU')} ед.`;
  }

  async function runGoalSeek() {
    if (!$activeProjectId) {
      errorMessage = 'Откройте проект сначала.';
      return;
    }
    // v2.1.0 (pilot E P0-1 2026-05-17): block Goal-Seek в planning mode -
    // backend _forward_at_budget строит config без forecast_periods/inflation,
    // поэтому target из планируемого горизонта применяется к training horizon
    // → backend ищет budget в неверном масштабе. Honest reject с инструкцией
    // переключиться в analyst mode для Goal-Seek.
    if ($planningMode === 'planner') {
      errorMessage = (
        'Goal-Seek недоступен в режиме Планирования. ' +
        'Переключитесь на «Анализ» (вверху страницы «Оптимизация»), либо используйте ' +
        'Forward-оптимизацию с заданным бюджетом для прогнозного горизонта.'
      );
      return;
    }
    busy = true;
    errorMessage = null;
    result = null;
    try {
      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: $activeProjectId }));
      const res = await invoke('econ_optimize_inverse', {
        projectDir,
        targetSales: targetSales,
        kpiKind: $kpiKind,
        mode: $derivedMode,
        maxBudget: maxBudgetCap,
        minBudget: null,
      });
      result = res;
    } catch (e) {
      const err = /** @type {{message?: string} | string} */ (e);
      errorMessage = typeof err === 'string' ? err : String(err?.message ?? err);
      console.error('Goal-Seek failed:', e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="goal-seek-panel">
  <WhyThisStep
    stepId="optimize-goal-seek"
    title="Зачем Goal-Seek?"
    whatWeDo="Вы задаёте целевые продажи. Программа находит минимальный бюджет, при котором эта цель достижима с высокой вероятностью."
    whyNeed="Forward оптимизация отвечает: «у меня есть бюджет - куда вложить?». Goal-Seek отвечает на противоположный вопрос CFO/CEO: «нужно достичь продаж X - сколько потратить?»"
    attentionTo={[
      'Цель должна быть в зелёной зоне коридора - иначе модель экстраполирует за пределы observed range.',
      'Доверительный интервал на бюджете шире, чем точечная оценка - учитывайте при планировании.',
      'Низкая P(достижения) означает, что цель близка к границам - рассмотрите менее агрессивные цели.',
    ]}
    whatsNext="Получите распределение по каналам и можно сразу строить отчёт «План достижения цели X»."
  />

  <section class="target-controls">
    <h3>Целевые продажи</h3>
    <CorridorSlider
      value={targetSales}
      min={corridorLo * 0.5}
      max={corridorHi * 1.15}
      corridorLo={corridorLo}
      corridorHi={corridorHi}
      yellowZonePct={0.10}
      step={(corridorHi - corridorLo) / 100}
      label="Целевые продажи"
      formatFn={formatTarget}
      onChange={(/** @type {number} */ v) => { targetSales = v; }}
      onZoneChange={(/** @type {'green' | 'yellow' | 'red'} */ z) => { currentZone = z; }}
    />

    <div class="numeric-input">
      <label for="target-direct">Или введите точно:</label>
      <input
        id="target-direct"
        type="text"
        inputmode="numeric"
        value={Math.round(Number(targetSales) || 0).toLocaleString('ru-RU')}
        oninput={(e) => {
          const raw = /** @type {HTMLInputElement} */ (e.target).value.replace(/\D/g, '');
          targetSales = parseInt(raw, 10) || 0;
        }}
      />
      <span class="unit">{$kpiKind === 'monetary' ? '₽' : 'ед.'}</span>
    </div>
  </section>

  <section class="budget-cap">
    <label>
      <input
        type="checkbox"
        checked={maxBudgetCap !== null}
        onchange={(e) => {
          const target = /** @type {HTMLInputElement} */ (e.target);
          maxBudgetCap = target.checked ? currentSales : null;
        }}
      />
      Ограничить максимальный бюджет (опционально)
    </label>
    {#if maxBudgetCap !== null}
      <input
        type="number"
        min="0"
        bind:value={maxBudgetCap}
        placeholder="например, 100000000"
      />
      <span class="unit">₽</span>
    {/if}
  </section>

  <div class="actions">
    <button
      type="button"
      class="btn-primary"
      disabled={busy || currentZone === 'red' || !targetSales}
      onclick={runGoalSeek}
    >
      {busy ? 'Ищем оптимум...' : 'Найти решение →'}
    </button>
    {#if currentZone === 'red'}
      <span class="zone-warning">
        ⚠ Цель в красной зоне - кнопка заблокирована.
      </span>
    {/if}
  </div>

  {#if errorMessage}
    <div class="error">
      {errorMessage}
    </div>
  {/if}

  {#if result}
    <GoalSeekResultCard result={result} kpiKind={$kpiKind} targetSales={targetSales} />
  {/if}
</div>

<style>
  .goal-seek-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 12px 0;
  }
  .target-controls h3 {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .numeric-input {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
    font-size: 12px;
  }
  .numeric-input label { color: var(--text-muted); }
  .numeric-input input {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 13px;
    width: 200px;
    font: inherit;
  }
  .unit { color: var(--text-muted); font-size: 12px; }

  .budget-cap {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 10px 12px;
    background: var(--bg-surface-quiet);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
    color: var(--text-secondary);
  }
  .budget-cap label { display: flex; gap: 6px; align-items: center; cursor: pointer; }
  .budget-cap input[type="number"] {
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 12px;
    width: 160px;
    font: inherit;
  }

  .actions {
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .btn-primary {
    padding: 10px 20px;
    background: var(--accent-primary);
    color: #fff;
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-btn, 8px);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    font: inherit;
  }
  .btn-primary:disabled {
    background: var(--bg-surface-quiet);
    color: var(--text-muted);
    border-color: var(--border);
    cursor: not-allowed;
  }
  .zone-warning {
    font-size: 11px;
    color: var(--danger, #f87171);
  }

  .error {
    padding: 10px 12px;
    background: color-mix(in srgb, var(--danger, #f87171) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger, #f87171) 30%, transparent);
    border-radius: var(--radius-sm, 6px);
    font-size: 12px;
    color: var(--danger, #f87171);
  }
</style>
