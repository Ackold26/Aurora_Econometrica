<script>
  /**
   * Scenario Playground - сохранение двух пресетов (текущий слайдерный / оптимальный)
   * + сравнение всех сохранённых сценариев.
   *
   * unit_costs пробрасываются в backend → backend считает ROAS в ₽ (money_mode) когда
   * все активные каналы покрыты. Смешанные native-единицы → warn в comparison.
   *
   * @component ScenarioPlayground
   */
  import { invoke } from '@tauri-apps/api/core';
  import { activeProjectId, sessionStats, unitCosts, unitCostInflation, valuePerCountUnit, kpiKind } from '$lib/project-state.js';
  import { get } from 'svelte/store';
  import DataTable from '$lib/components/DataTable.svelte';
  import { TriangleAlert, X } from 'lucide-svelte';

  /** @type {{
   *   channelBudgets: Record<string, number>,
   *   channels: string[],
   *   optimalBudgets?: Record<string, number> | null,
   *   planningPeriods?: number | null,
   *   planningLabel?: string | null,
   * }} */
  let {
    channelBudgets, channels, optimalBudgets = null,
    planningPeriods = null, planningLabel = null,
  } = $props();

  /** @type {'idle' | 'saving-current' | 'saving-optimal' | 'comparing'} */
  let status = $state('idle');
  /** @type {string | null} */
  let errorMsg = $state(null);
  /** @type {any | null} */
  let comparison = $state(null);
  /** @type {boolean} true если backend вернул money-mode. */
  let moneyMode = $state(false);
  let scenarioName = $state('');

  /** dd.MM HH:mm - человеко-читаемый timestamp для авто-имён. */
  function autoTimestamp() {
    const d = new Date();
    const pad = (/** @type {number} */ n) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /**
   * @param {Record<string, number>} budgets - per-channel native budget (one period)
   * @param {string} namePrefix - дефолтный префикс когда пользователь не задал имя
   * @param {'saving-current' | 'saving-optimal'} newStatus
   */
  async function saveFrom(budgets, namePrefix, newStatus) {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    status = newStatus;
    errorMsg = null;
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const baseName = scenarioName.trim() || `${namePrefix} ${autoTimestamp()}`;
      /** @type {Record<string, number[]>} */
      const mediaPlan = {};
      for (const ch of channels) mediaPlan[ch] = [budgets[ch] ?? 0];

      const uc = get(unitCosts) ?? {};
      // v2.1.0 (pilot E P1-3 2026-05-17): передаём kpi_unit_cost в сценарий для
      // count KPI - без него scenarios теряли money equivalents (ADR-021 incomplete).
      const _kuc = get(valuePerCountUnit);
      const kpiUnitCost = get(kpiKind) === 'count' && typeof _kuc === 'number' && _kuc > 0 ? _kuc : null;
      const result = /** @type {any} */ (await invoke('econ_scenario', {
        projectDir,
        scenarioName: baseName,
        mediaPlan,
        unitCosts: Object.keys(uc).length > 0 ? uc : null,
        // Phase 2: planning context - backend distributes mediaPlan total
        // across forecast_periods (not training_n_periods) когда set.
        forecastPeriods: planningPeriods,
        forecastPeriodLabel: planningLabel,
        unitCostInflationPct: (() => { const v = get(unitCostInflation) ?? {}; return Object.keys(v).length > 0 ? v : null; })(),
        kpiUnitCost,
      }));
      if (result.status === 'ok') {
        scenarioName = '';
        sessionStats.update(s => ({ ...s, scenarioCount: s.scenarioCount + 1 }));
        await loadComparison();
      } else {
        errorMsg = result.message || 'Ошибка сохранения';
      }
    } catch (/** @type {any} */ e) {
      errorMsg = String(e);
    }
    status = 'idle';
  }

  async function saveCurrent() {
    await saveFrom(channelBudgets, 'Текущий', 'saving-current');
  }

  async function saveOptimal() {
    if (!optimalBudgets) return;
    await saveFrom(optimalBudgets, 'Оптимум', 'saving-optimal');
  }

  async function loadComparison() {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    status = 'comparing';
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const uc = get(unitCosts) ?? {};
      const result = /** @type {any} */ (await invoke('econ_compare', {
        projectDir,
        unitCosts: Object.keys(uc).length > 0 ? uc : null,
      }));
      if (result.status === 'ok') {
        comparison = result.comparison || null;
        moneyMode = Boolean(result.money_mode);
      } else {
        comparison = null;
        moneyMode = false;
      }
    } catch { /* silent */ }
    status = 'idle';
  }

  /** @param {string} name */
  async function deleteScenario(name) {
    const projectId = get(activeProjectId);
    if (!projectId) return;
    if (!confirm(`Удалить сценарий «${name}»?`)) return;
    errorMsg = null;
    try {
      const projectDir = await invoke('project_get_dir', { projectId });
      const result = /** @type {any} */ (await invoke('econ_scenario_delete', {
        projectDir,
        scenarioName: name,
      }));
      if (result.status === 'ok') {
        await loadComparison();
      } else {
        errorMsg = result.message || 'Ошибка удаления';
      }
    } catch (/** @type {any} */ e) {
      errorMsg = String(e);
    }
  }

  /** Имена сценариев из comparison (headers[0] - "Метрика", дальше имена). */
  let scenarioNames = $derived(
    comparison?.headers ? comparison.headers.slice(1) : []
  );

  let hasOptimal = $derived(
    optimalBudgets !== null &&
    optimalBudgets !== undefined &&
    Object.keys(optimalBudgets || {}).length > 0
  );
</script>

<div class="scenario-playground">
  <div class="save-row">
    <input
      class="name-input"
      type="text"
      placeholder="Название сценария (необязательно)"
      bind:value={scenarioName}
    />
    <button
      class="btn-save"
      onclick={saveCurrent}
      disabled={status !== 'idle'}
      title="Сохранить распределение, которое сейчас в слайдерах"
    >
      {status === 'saving-current' ? 'Сохраняю…' : 'Сохранить текущее'}
    </button>
    <button
      class="btn-save btn-save-optimal"
      onclick={saveOptimal}
      disabled={status !== 'idle' || !hasOptimal}
      title={hasOptimal
        ? 'Сохранить результат оптимизатора'
        : 'Сначала запусти «Найти оптимум»'}
    >
      {status === 'saving-optimal' ? 'Сохраняю…' : 'Сохранить оптимум'}
    </button>
    {#if comparison}
      <button class="btn-compare" onclick={loadComparison} disabled={status !== 'idle'}>
        {status === 'comparing' ? '…' : 'Обновить'}
      </button>
    {:else}
      <button class="btn-compare" onclick={loadComparison} disabled={status !== 'idle'}>
        Сравнить сценарии
      </button>
    {/if}
  </div>

  {#if errorMsg}
    <div class="error">{errorMsg}</div>
  {/if}

  {#if comparison}
    {#if !moneyMode}
      <div class="units-warn">
        <TriangleAlert size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /> Бюджеты в native-единицах (TRP + ₽). ROAS несопоставим между сценариями.
        Укажи «Стоимость юнита» в блоке «Проверка», чтобы получить ROAS в ₽.
      </div>
    {/if}
    {#if scenarioNames.length > 0}
      <div class="scenario-chips">
        <span class="chips-label">Сохранённые:</span>
        {#each scenarioNames as name}
          <span class="chip">
            {name}
            <button
              class="chip-del"
              onclick={() => deleteScenario(name)}
              title="Удалить сценарий «{name}»"
              aria-label="Удалить {name}"
            ><X size={14} strokeWidth={1.5} style="vertical-align: -0.15em" /></button>
          </span>
        {/each}
      </div>
    {/if}
    <DataTable
      mode="scenario"
      title="Сравнение сценариев"
      headers={comparison.headers}
      rows={comparison.rows}
      highlightColumn={comparison.headers?.[1]}
    />
  {/if}
</div>

<style>
  .scenario-playground {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .save-row {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }

  .name-input {
    flex: 1;
    min-width: 160px;
    padding: 8px 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px;
    color: var(--text-primary, #e2e8f0);
    font-size: 13px;
    outline: none;
  }
  .name-input:focus { border-color: color-mix(in srgb, var(--accent-primary) 40%, transparent); }
  .name-input::placeholder { color: var(--text-secondary, #94a3b8); }

  .btn-save {
    padding: 8px 14px;
    background: var(--accent-primary, #3b82f6);
    border: none;
    border-radius: 7px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: opacity 0.15s;
  }
  .btn-save:hover:not(:disabled) { opacity: 0.85; }
  .btn-save:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-save-optimal {
    background: var(--success, #10b981);
  }

  .btn-compare {
    padding: 8px 14px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 7px;
    color: var(--text-secondary, #94a3b8);
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .btn-compare:hover:not(:disabled) { border-color: rgba(255,255,255,0.25); color: var(--text-primary, #e2e8f0); }
  .btn-compare:disabled { opacity: 0.5; cursor: not-allowed; }

  .error {
    font-size: 12px;
    color: #ef4444;
    padding: 6px 10px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    border-radius: 6px;
  }

  .units-warn {
    font-size: 12px;
    color: color-mix(in srgb, var(--warning, #f59e0b) 90%, white);
    padding: 8px 12px;
    background: color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent);
    border-radius: 7px;
    line-height: 1.5;
  }

  .scenario-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    font-size: 12px;
  }
  .chips-label {
    color: var(--text-secondary, #94a3b8);
    margin-right: 4px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 4px 3px 10px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 14px;
    color: var(--text-primary, #e2e8f0);
    font-size: 12px;
  }
  .chip-del {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 50%;
    color: var(--text-secondary, #94a3b8);
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    transition: all 0.15s;
  }
  .chip-del:hover {
    background: color-mix(in srgb, var(--danger) 25%, transparent);
    color: #fff;
  }
</style>
