<script>
  /**
   * ValidateStepV13 — v1.3.0 new Validate flow (per ADR-015 P0.9).
   *
   * Orchestrates 4 sub-steps:
   *   1. KPISelector — choose target KPI type.
   *   2. ValuePerCountUnitInput — for count KPIs only.
   *   3. PerChannelInputSelector — for each channel choose monetary vs physical.
   *   4. ModeDerivedExplanation — show derived mode + continue.
   *
   * Backward compat: if `useDerivedModeUX` store is false, parent uses
   * ObjectiveSelector (v1.2 flow) вместо этого component.
   *
   * @component ValidateStepV13
   */

  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
  import { onMount } from 'svelte';
  import {
    kpiType, kpiKind, perChannelInput, derivedMode,
    valuePerCountUnit, valuePerCountUnitSource,
    activeProject, activeProjectId, validateData, importData,
    completeStep, setStepError,
  } from '$lib/project-state.js';
  import {
    deriveModeWithExplanation,
    kpiKindForType,
    valuePerCountUnitLabel,
  } from '$lib/mode-derivation.js';
  import { setColumnRolesBulk, buildProjectUpdates } from '$lib/column-roles.js';
  import KPISelector from './KPISelector.svelte';
  import ValuePerCountUnitInput from './ValuePerCountUnitInput.svelte';
  import PerChannelInputSelector from './PerChannelInputSelector.svelte';
  import ModeDerivedExplanation from './ModeDerivedExplanation.svelte';
  import WhyThisStep from './WhyThisStep.svelte';
  // v1.3.2: ColumnMapperConfirm — preflight role confirmation перед KPISelector.
  // Backend column_detection делает auto-classify; этот компонент показывает
  // detected roles в read-only table с possibility override.
  import ColumnMapperConfirm from './ColumnMapperConfirm.svelte';

  // Audit fix v1.3.0: monetaryColumnHint теперь auto-detected из validateData
  // (если не передан явно). Hardcoded 'sales_rub' ломал auto-detect для
  // не-стандартных schemas (revenue / выручка / sales).
  const { onComplete = undefined, channels = [], availableMetricsByChannel = {}, monetaryColumnHint = '' } = $props();

  /** v1.3.2 audit fix (M3): preflight role confirmation step. Когда false →
   *  show ColumnMapperConfirm перед KPISelector flow. После confirm flips к
   *  true и далее идёт обычный 4-substep KPI flow.
   *
   *  Persisted to localStorage per projectId — юзер confirm-ит роли один раз
   *  на проект; повторное mount читает state. Reset через goBack button.
   *  Key format: `aurora-econ:roles-confirmed:{projectId}`. */
  const ROLES_CONFIRMED_KEY_PREFIX = 'aurora-econ:roles-confirmed:';

  function loadRolesConfirmed() {
    try {
      const pid = get(activeProjectId);
      if (!pid) return false;
      return localStorage.getItem(ROLES_CONFIRMED_KEY_PREFIX + pid) === '1';
    } catch {
      return false;  // localStorage может быть unavailable
    }
  }

  /** @param {boolean} value */
  function persistRolesConfirmed(value) {
    try {
      const pid = get(activeProjectId);
      if (!pid) return;
      if (value) {
        localStorage.setItem(ROLES_CONFIRMED_KEY_PREFIX + pid, '1');
      } else {
        localStorage.removeItem(ROLES_CONFIRMED_KEY_PREFIX + pid);
      }
    } catch { /* best-effort */ }
  }

  let rolesConfirmed = $state(loadRolesConfirmed());

  /** v1.3.2 audit fix: auto-trigger validate если imported file есть но
   *  validate result отсутствует (например при открытии .aurora bundle где
   *  validate state не persisted). Без этого ColumnMapperConfirm показывал
   *  пустую таблицу. */
  let validating = $state(false);
  /** @type {string | null} */
  let validateError = $state(null);

  async function autoRunValidate() {
    const imp = get(importData);
    if (!imp?.file) {
      validateError = 'Сначала загрузите файл на шаге Импорт.';
      return;
    }
    validating = true;
    validateError = null;
    try {
      const projectId = get(activeProjectId);
      /** @type {any} */
      const res = await invoke('econ_validate', {
        filePath: imp.file,
        projectDir: projectId || null,
      });
      if (res?.status === 'error' && !res.columns) {
        validateError = res.message ?? 'Ошибка валидации';
        setStepError(1, validateError);
        return;
      }
      validateData.set({
        result: res,
        correlationMatrix: res.full_correlation_matrix ?? null,
        columnHistograms: null,
      });
      if (res?.status !== 'error') {
        completeStep(1);
      }
    } catch (e) {
      validateError = `Ошибка валидации: ${e}`;
      setStepError(1, String(e));
    } finally {
      validating = false;
    }
  }

  onMount(() => {
    // Auto-trigger validate если данные не загружены ещё в store.
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols) || cols.length === 0) {
      autoRunValidate();
    }
  });
  /** @type {0 | 1 | 2 | 3} */
  let subStep = $state(0);
  /** @type {string} */
  let currentKPI = $state($kpiType);
  /** @type {number | null} */
  let currentValuePerUnit = $state($valuePerCountUnit);
  /** @type {Record<string, 'monetary' | 'physical'>} */
  let currentPerChannel = $state(/** @type {Record<string, 'monetary' | 'physical'>} */ ($perChannelInput || {}));
  /** @type {any} */
  let autoSuggestedValue = $state(null);
  let busy = $state(false);

  const currentKpiKind = $derived(kpiKindForType(currentKPI));
  const valueLabel = $derived(valuePerCountUnitLabel(currentKPI));
  const skipValueStep = $derived(currentKpiKind === 'monetary');
  const modeAndExplanation = $derived(
    deriveModeWithExplanation(currentPerChannel || {})
  );

  /** @param {string} id */
  async function handleKPISelect(id) {
    currentKPI = id;
    kpiType.set(id);
    const kind = kpiKindForType(id);
    // proportional KPIs (awareness) out_of_scope_v13 — treat as monetary fallback.
    const safeKind = /** @type {'monetary' | 'count'} */ (kind === 'count' ? 'count' : 'monetary');
    kpiKind.set(safeKind);

    // Skip ValuePerCountUnitInput for monetary KPIs.
    if (kind === 'monetary') {
      subStep = 2;
    } else {
      // Try auto-detect value per count unit.
      await tryAutoDetectValue(id);
      subStep = 1;
    }
  }

  /** @param {string} kpiTypeId */
  /**
   * Audit fix v1.3.0: auto-detect monetary column из validateData (вместо hardcoded 'sales_rub').
   * Looks for column with role='target' OR с типичными monetary именами.
   * Returns first match или null.
   * @returns {string | null}
   */
  function detectMonetaryColumn() {
    if (monetaryColumnHint) return monetaryColumnHint;  // explicit override
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return null;
    // Try role='kpi' or role='target' first
    const targetCol = cols.find((/** @type {any} */ c) => c?.role === 'kpi' || c?.role === 'target');
    if (targetCol) return targetCol.name;
    // Fallback: name heuristic
    const monetaryRe = /(?:^|[_\s-])(?:sales|revenue|profit|gmv|выручка|продажи)(?:[_\s-]|$|_rub|_money)/i;
    for (const c of cols) {
      if (monetaryRe.test(c?.name ?? '')) return c.name;
    }
    return null;
  }

  /** @param {string} kpiTypeId */
  async function tryAutoDetectValue(kpiTypeId) {
    if (!$activeProject?.path) {
      autoSuggestedValue = null;
      return;
    }
    const monetaryCol = detectMonetaryColumn();
    if (!monetaryCol) {
      // No monetary column found — silently skip auto-suggest.
      autoSuggestedValue = null;
      return;
    }
    busy = true;
    try {
      const countColumnHint = kpiTypeId === 'count_custom' ? kpiTypeId : kpiTypeId;

      const result = await invoke('econ_auto_detect_price', {
        projectDir: $activeProject.path,
        monetaryColumn: monetaryCol,
        countColumn: countColumnHint,
      });
      if (result?.value !== null && result?.value !== undefined) {
        autoSuggestedValue = result;
      } else {
        autoSuggestedValue = null;
      }
    } catch (e) {
      console.warn('Auto-detect value failed (silent):', e);
      autoSuggestedValue = null;
    } finally {
      busy = false;
    }
  }

  /** @param {{value: number, source: string}} arg */
  function handleValueConfirm({ value, source }) {
    currentValuePerUnit = value;
    valuePerCountUnit.set(value);
    valuePerCountUnitSource.set(source);
    subStep = 2;
  }

  function handleValueSkip() {
    valuePerCountUnit.set(null);
    valuePerCountUnitSource.set(null);
    subStep = 2;
  }

  /** @param {Record<string, string>} selection */
  function handlePerChannelConfirm(selection) {
    const typed = /** @type {Record<string, 'monetary' | 'physical'>} */ (selection);
    currentPerChannel = typed;
    perChannelInput.set(typed);
    // Derive mode locally + sync to store.
    const m = deriveModeWithExplanation(typed);
    derivedMode.set(/** @type {'roi' | 'effectiveness' | 'manual'} */ (m.mode));
    subStep = 3;
  }

  async function handleContinue() {
    busy = true;
    try {
      // Persist KPI settings to backend.
      if ($activeProject?.path) {
        await invoke('econ_save_kpi_settings', {
          projectDir: $activeProject.path,
          valuePerCountUnit: currentValuePerUnit,
          valuePerCountUnitLabel: valueLabel,
          valuePerCountUnitSource: $valuePerCountUnitSource,
          perChannelInput: currentPerChannel,
          kpiKind: currentKpiKind,
        });
      }
      onComplete?.({
        kpiType: currentKPI,
        kpiKind: currentKpiKind,
        valuePerCountUnit: currentValuePerUnit,
        perChannelInput: currentPerChannel,
        derivedMode: modeAndExplanation.mode,
      });
    } catch (e) {
      console.error('Save KPI settings failed:', e);
    } finally {
      busy = false;
    }
  }

  /**
   * Audit fix v1.3.0: linear back navigation (не skip skipValueStep).
   * Prevents user confusion при switching KPI type after substep 2.
   * v1.3.2: subStep 0 + rolesConfirmed → goBack returns к ColumnMapperConfirm.
   */
  function goBack() {
    if (subStep === 0 && rolesConfirmed) {
      rolesConfirmed = false;
      persistRolesConfirmed(false);
      return;
    }
    if (subStep === 1) subStep = 0;
    else if (subStep === 2) subStep = skipValueStep ? 0 : 1;
    else if (subStep === 3) subStep = 2;
  }

  // v1.3.2: ColumnMapperConfirm columns derived из validateData.result.columns.
  // Преобразуем canonical role vocabulary → ColumnMapperConfirm dropdown set
  // (kpi/media/control/date/excluded). 'unused' и 'unknown' маппим в 'excluded'.
  const detectedColumns = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return [];
    return cols.map((/** @type {any} */ c) => ({
      name: c?.name ?? '—',
      kind: c?.kind ?? c?.dtype ?? null,
      role: (c?.role === 'unused' || c?.role === 'unknown' || c?.role == null)
        ? 'excluded'
        : c.role,
    }));
  });

  // v1.3.2 audit fix (B2): substep-nav stage descriptors. Explicit mapping
  // displayIdx ↔ subStep prevents off-by-one на skipValueStep collapse.
  const navStages = $derived.by(() => {
    /** @type {Array<{label: string, subStep: number}>} */
    const stages = [
      { label: 'Роли колонок', subStep: -1 },
      { label: 'Целевая метрика', subStep: 0 },
      { label: 'Ценность единицы', subStep: 1 },
      { label: 'Метрики каналов', subStep: 2 },
      { label: 'Подтверждение', subStep: 3 },
    ];
    return skipValueStep
      ? stages.filter(s => s.subStep !== 1)
      : stages;
  });

  /** @param {Record<string, string>} mapping — column name → role chosen by user */
  async function handleRolesConfirm(mapping) {
    // Persist overrides обратно к validateData.result.columns + project.json.
    const val = get(validateData);
    if (val?.result?.columns) {
      // ColumnMapperConfirm uses 'excluded' → canonical vocabulary use 'unused'.
      /** @type {Record<string, string[]>} */
      const byRole = {};
      for (const [name, uiRole] of Object.entries(mapping)) {
        const canonical = uiRole === 'excluded' ? 'unused' : uiRole;
        if (!byRole[canonical]) byRole[canonical] = [];
        byRole[canonical].push(name);
      }
      let updated = val.result.columns;
      for (const [role, names] of Object.entries(byRole)) {
        updated = setColumnRolesBulk(updated, names, role);
      }
      // Apply local store update (immutable).
      validateData.set({
        ...val,
        result: { ...val.result, columns: updated },
      });
      // Persist project.json (best-effort, non-blocking — matches InsightsPanel pattern).
      const projectId = get(activeProjectId);
      if (projectId) {
        const updates = buildProjectUpdates(updated);
        invoke('project_update', { projectId, updates }).catch(() => { /* silent */ });
      }
    }
    rolesConfirmed = true;
    persistRolesConfirmed(true);
    subStep = 0;
  }
</script>

<div class="validate-v13">
  <!-- Sub-step progress indicator -->
  <!-- v1.3.2 audit fix (B2): explicit subStep mapping via navStages $derived
       чтобы skipValueStep collapse не ломал нумерацию dots. -->
  <nav class="substep-nav">
    {#each navStages as stage, displayIdx}
      {@const isPreflight = stage.subStep === -1}
      {@const isActive = isPreflight ? !rolesConfirmed : (rolesConfirmed && stage.subStep === subStep)}
      {@const isDone = isPreflight ? rolesConfirmed : (rolesConfirmed && stage.subStep < subStep)}
      <div class="substep-dot" class:active={isActive} class:done={isDone}>
        <span class="dot-number">{displayIdx + 1}</span>
        <span class="dot-label">{stage.label}</span>
      </div>
    {/each}
  </nav>

  {#if rolesConfirmed && subStep > 0}
    <button class="back-link" onclick={goBack}>← Назад</button>
  {:else if rolesConfirmed && subStep === 0}
    <button class="back-link" onclick={goBack}>← Изменить роли колонок</button>
  {/if}

  {#if validating}
    <div class="validation-loading" role="status" aria-live="polite">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p class="loading-title">Анализируем данные</p>
      <p class="loading-detail">Программа проверяет колонки и определяет роли — обычно занимает 2-5 секунд.</p>
    </div>
  {:else if validateError}
    <div class="validation-error" role="alert">
      <p class="error-title">Не удалось проверить данные</p>
      <p class="error-detail">{validateError}</p>
      <button type="button" class="btn-retry" onclick={autoRunValidate}>
        Повторить попытку
      </button>
    </div>
  {:else if !rolesConfirmed}
    <ColumnMapperConfirm columns={detectedColumns} onConfirm={handleRolesConfirm} />
  {:else if subStep === 0}
    <KPISelector onSelect={handleKPISelect} currentKPI={currentKPI} />
  {:else if subStep === 1}
    <ValuePerCountUnitInput
      kpiType={currentKPI}
      label={valueLabel}
      autoValue={autoSuggestedValue}
      currentValue={currentValuePerUnit}
      onConfirm={handleValueConfirm}
      onSkip={handleValueSkip}
    />
  {:else if subStep === 2}
    <PerChannelInputSelector
      channels={channels}
      availableMetricsByChannel={availableMetricsByChannel}
      currentSelection={currentPerChannel}
      onConfirm={handlePerChannelConfirm}
    />
  {:else if subStep === 3}
    <ModeDerivedExplanation
      derivedMode={modeAndExplanation.mode}
      explanation={modeAndExplanation.explanation}
      perChannelInput={currentPerChannel}
      kpiKind={currentKpiKind}
      onContinue={handleContinue}
    />
  {/if}

  {#if busy}
    <div class="busy-overlay">Сохраняем...</div>
  {/if}
</div>

<style>
  .validate-v13 {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 0;
    width: 100%;
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
    position: relative;
  }
  .substep-nav {
    display: flex;
    gap: 0;
    align-items: center;
    padding: 12px 24px;
    background: var(--bg-surface-quiet);
    border-bottom: 1px solid var(--border-subtle);
  }
  .substep-dot {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    font-size: 11px;
    color: var(--text-muted);
    border-radius: 999px;
    position: relative;
  }
  .substep-dot:not(:last-child)::after {
    content: '';
    position: absolute;
    right: -10px;
    width: 16px;
    height: 1px;
    background: var(--border);
  }
  .substep-dot.active {
    background: color-mix(in srgb, var(--accent-primary) 12%, transparent);
    color: var(--accent-primary);
    font-weight: 600;
  }
  .substep-dot.done { color: var(--success, #4ade80); }
  .dot-number {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--bg-card);
    border: 1px solid currentColor;
    font-size: 10px;
    font-weight: 700;
  }
  .dot-label { font-size: 11px; }

  .back-link {
    background: none;
    border: none;
    color: var(--accent-primary);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    padding: 4px 24px;
    text-align: left;
    text-decoration: none;
    margin: 0;
  }
  .back-link:hover { text-decoration: underline; }

  .busy-overlay {
    position: absolute;
    inset: 0;
    background: color-mix(in srgb, var(--bg-card) 80%, transparent);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    color: var(--text-muted);
    backdrop-filter: blur(2px);
  }

  /* v1.3.2: auto-validate loading / error states (премиум tier-1) */
  .validation-loading,
  .validation-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 80px 24px;
    max-width: 480px;
    margin: 60px auto 0;
    text-align: center;
  }
  .loading-spinner {
    width: 32px;
    height: 32px;
    border: 2px solid color-mix(in srgb, var(--gold, #c9a449) 20%, transparent);
    border-top-color: var(--gold, #c9a449);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  .loading-title,
  .error-title {
    margin: 0;
    font-family: var(--font-serif, Georgia), serif;
    font-size: 18px;
    font-weight: 400;
    color: var(--text-primary);
  }
  .loading-detail,
  .error-detail {
    margin: 0;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text-secondary);
  }
  .btn-retry {
    margin-top: 4px;
    padding: 9px 18px;
    border-radius: 3px;
    background: var(--text-primary);
    color: var(--bg-card, #0f172a);
    border: none;
    font: inherit;
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: transform 0.15s;
  }
  .btn-retry:hover {
    transform: translateY(-1px);
  }
</style>
