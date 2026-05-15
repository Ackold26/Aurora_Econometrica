<script>
  /**
   * ValidateStepV13 - v1.3.0 new Validate flow (per ADR-015 P0.9).
   *
   * Orchestrates 4 sub-steps:
   *   1. KPISelector - choose target KPI type.
   *   2. ValuePerCountUnitInput - for count KPIs only.
   *   3. PerChannelInputSelector - for each channel choose monetary vs physical.
   *   4. ModeDerivedExplanation - show derived mode + continue.
   *
   * Backward compat: if `useDerivedModeUX` store is false, parent uses
   * ObjectiveSelector (v1.2 flow) вместо этого component.
   *
   * @component ValidateStepV13
   */

  import { invoke } from '@tauri-apps/api/core';
  import { get } from 'svelte/store';
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
  import { validateInsights } from '$lib/insights-rules.js';
  import {
    analysisObjective, expertMode, analysisMode,
    // H-16 (audit): Phase 1.3 persistence stores — нужны в save flow.
    unitCosts, unitCostInflation, unitCostInputMode, budgetInputs,
  } from '$lib/project-state.js';
  import KPISelector from './KPISelector.svelte';
  import ValuePerCountUnitInput from './ValuePerCountUnitInput.svelte';
  import PerChannelInputSelector from './PerChannelInputSelector.svelte';
  import ModeDerivedExplanation from './ModeDerivedExplanation.svelte';
  // v2.0.0 (ADR-019): mode selector + applied summary integrated as Manager UX layer
  import AnalysisModeSelector from './AnalysisModeSelector.svelte';
  import AppliedModeSummary from './AppliedModeSummary.svelte';
  import WhyThisStep from './WhyThisStep.svelte';
  // v1.3.2: ColumnMapperConfirm - preflight role confirmation перед KPISelector.
  // Backend column_detection делает auto-classify; этот компонент показывает
  // detected roles в read-only table с possibility override.
  import ColumnMapperConfirm from './ColumnMapperConfirm.svelte';
  import RatioInfoCard from './RatioInfoCard.svelte';
  // Phase 1.1 (SSOT): detection через shared service вместо inline regex.
  // Service fetches patterns from backend `/api/static/classifier-patterns-v1.json`,
  // caches в localStorage, falls back к embedded patterns если backend down.
  // Replaces previous v2.0.1 hotfix inline MONETARY_RE/PHYSICAL_RE — теперь
  // single source of truth с column_detection.py.
  import { detectChannelUnitType as detectChannelType } from '$lib/services/classifier-patterns.js';

  /** Channel sums (Σ единиц за весь период) из validateData. Используется
   *  AppliedModeSummary для derivation unit_cost из «общего бюджета»
   *  (budget / sum = ₽ за 1 единицу). */
  const channelSums = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return {};
    /** @type {Record<string, number>} */
    const sums = {};
    for (const c of cols) {
      if (c?.role === 'media' && typeof c?.stats?.sum === 'number') {
        sums[c.name] = c.stats.sum;
      }
    }
    return sums;
  });

  /** UX gap fix (v2.0.1): имена media каналов которые были исключены
   *  (role='unused' или 'excluded'). Чтобы пользователь видел на «Метрики
   *  каналов» что было автоматически вырезано (ratioRecommendation rule,
   *  zeros% > 50%, и т.д.) и мог осознанно вернуть. Включаются ТОЛЬКО колонки
   *  c media-keywords чтобы не показывать excluded controls / kpi candidates. */
  const excludedMediaNames = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return [];
    /** @type {string[]} */
    const out = [];
    for (const c of cols) {
      if (c?.role !== 'unused' && c?.role !== 'excluded') continue;
      const name = c?.name ?? '';
      // Heuristic via SSOT classifier service (Phase 1.1): detect type → если
      // physical/monetary классифицирован, считаем это media-related column.
      // detectChannelType returns 'monetary' || 'physical'. Anything matching
      // patterns considered media-related; default monetary не информативен
      // for excluded media — но эти cols прошли prior validator role='unused'.
      // Simple inclusion: any column с recognised unit type considered media.
      if (detectChannelType(name) !== 'monetary' || /[₽]|бюджет|budget|spend|trp|показ/i.test(name)) {
        out.push(name);
      }
    }
    return out;
  });

  // Audit fix v1.3.0: monetaryColumnHint теперь auto-detected из validateData
  // (если не передан явно). Hardcoded 'sales_rub' ломал auto-detect для
  // не-стандартных schemas (revenue / выручка / sales).
  const { onComplete = undefined, channels = [], availableMetricsByChannel = {}, columnStats = {}, monetaryColumnHint = '' } = $props();

  /** v1.3.2 audit fix (M3): preflight role confirmation step. Когда false →
   *  show ColumnMapperConfirm перед KPISelector flow. После confirm flips к
   *  true и далее идёт обычный 4-substep KPI flow.
   *
   *  Persisted to localStorage per projectId - юзер confirm-ит роли один раз
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
  /** Guard против повторного запуска при reactive updates. */
  let validateAttempted = $state(false);

  async function autoRunValidate() {
    const imp = get(importData);
    if (!imp?.file) {
      validateError = 'Сначала загрузите файл на шаге Импорт.';
      return;
    }
    validateAttempted = true;
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

  /** Manual retry button - resets attempt flag и пытается заново. */
  function retryValidate() {
    validateError = null;
    validateAttempted = false;
    autoRunValidate();
  }

  /** Reactive auto-trigger - ждёт пока $importData.file populated (race
   *  condition при открытии .aurora archive: ValidateStepV13 mounts ДО
   *  того как importData filled из bundle). Запускается ОДИН раз когда
   *  все conditions выполнены. */
  $effect(() => {
    const file = $importData?.file;
    const cols = $validateData?.result?.columns;
    const hasFile = !!file;
    const needsValidation = !Array.isArray(cols) || cols.length === 0;
    if (hasFile && needsValidation && !validating && !validateAttempted) {
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
    // proportional KPIs (awareness) out_of_scope_v13 - treat as monetary fallback.
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
      // No monetary column found - silently skip auto-suggest.
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
        // H-16 (audit): Phase 1.3 store persistence — earlier версия не
        // передавала unit_costs / inflation / mode_for / budget_inputs к
        // backend. Reload терял состояние. Теперь полный snapshot.
        await invoke('econ_save_kpi_settings', {
          projectDir: $activeProject.path,
          valuePerCountUnit: currentValuePerUnit,
          valuePerCountUnitLabel: valueLabel,
          valuePerCountUnitSource: $valuePerCountUnitSource,
          perChannelInput: currentPerChannel,
          kpiKind: currentKpiKind,
          unitCosts: $unitCosts ?? null,
          unitCostInflation: $unitCostInflation ?? null,
          modeFor: $unitCostInputMode ?? null,
          budgetInputs: $budgetInputs ?? null,
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
  // v1.3.2: sort by role priority - Дата сверху, потом KPI, потом media,
  // control, excluded в конце. Стабильная sort внутри роли (preserve original
  // order). Includes col.stats для recommendation heuristic.
  /** @type {Record<string, number>} */
  const ROLE_SORT_PRIORITY = {
    date: 0,
    kpi: 1,
    media: 2,
    control: 3,
    excluded: 4,
  };
  const detectedColumns = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return [];
    const mapped = cols.map((/** @type {any} */ c, /** @type {number} */ idx) => ({
      _origIdx: idx,
      name: c?.name ?? '-',
      kind: c?.kind ?? c?.dtype ?? null,
      stats: c?.stats ?? null,
      role: (c?.role === 'unused' || c?.role === 'unknown' || c?.role == null)
        ? 'excluded'
        : c.role,
    }));
    // Stable sort: role priority → original order.
    mapped.sort((a, b) => {
      const pa = ROLE_SORT_PRIORITY[a.role] ?? 99;
      const pb = ROLE_SORT_PRIORITY[b.role] ?? 99;
      if (pa !== pb) return pa - pb;
      return a._origIdx - b._origIdx;
    });
    return mapped.map(({ _origIdx, ...rest }) => rest);
  });

  /**
   * v1.3.2: Ratio info card data — computed from validateData + columns stats.
   * weakChannels = media каналы с >50% нулей (можно исключить для повышения ratio).
   * afterExcludeRatio = ratio после исключения weak channels.
   */
  const ratioCardData = $derived.by(() => {
    const result = $validateData?.result;
    if (!result) return null;
    const cols = Array.isArray(result.columns) ? result.columns : [];
    /** Active media + control каналы (без excluded). */
    const activeCols = cols.filter((/** @type {any} */ c) =>
      c?.role === 'media' || c?.role === 'control'
    );
    const nPredictors = activeCols.length;
    const nObs = result.file?.rows ?? result.detected?.n_rows ?? 0;
    if (nPredictors === 0 || nObs === 0) return null;
    const ratio = nObs / nPredictors;
    // Weak: media каналы с >50% нулей.
    const weakMedia = cols.filter((/** @type {any} */ c) =>
      c?.role === 'media' && Number(c?.stats?.zeros_pct ?? 0) > 50
    );
    const afterExclude = nPredictors - weakMedia.length > 0
      ? nObs / (nPredictors - weakMedia.length)
      : null;
    return {
      ratio,
      nObs,
      nPredictors,
      weakChannelsCount: weakMedia.length,
      weakChannelNames: weakMedia.map((/** @type {any} */ c) => c?.name).filter(Boolean),
      afterExcludeRatio: afterExclude,
    };
  });

  /**
   * v1.3.2: hard-block reason для «Подтвердить роли» button. Когда ratio
   * <2:1 (минимальный порог для запуска модели), кнопка disabled с
   * объяснением — нельзя продолжить до улучшения data quality.
   * Reason text включает текущее значение, требуемый минимум, и actionable
   * recommendation (исключить N weak каналов).
   */
  const ratioBlockedReason = $derived.by(() => {
    const data = ratioCardData;
    if (!data) return null;
    if (data.ratio >= 2) return null;  // unblock at ratio >= 2:1
    const after = data.afterExcludeRatio;
    const canFix = data.weakChannelsCount > 0 && after != null && after >= 2;
    let reason = `Текущий ratio ${data.ratio.toFixed(1)}:1 ниже минимального 2:1 — модель «выучит» точки вместо закономерности. `;
    if (canFix) {
      reason += `Исключите ${data.weakChannelsCount} малоактивн${data.weakChannelsCount === 1 ? 'ый канал' : data.weakChannelsCount < 5 ? 'ых канала' : 'ых каналов'} (кнопка «Применить рекомендацию» выше) → ratio станет ${after.toFixed(1)}:1.`;
    } else {
      reason += `Добавьте больше истории (≥52 недель) или сократите число каналов в модели.`;
    }
    return reason;
  });

  /**
   * Apply ratio recommendation: excludes weak media channels (>50% zeros).
   * Reuses setColumnRolesBulk → role='unused'.
   */
  function applyRatioRecommendation() {
    const data = ratioCardData;
    if (!data || data.weakChannelNames.length === 0) return;
    const val = get(validateData);
    if (!val?.result?.columns) return;
    const updated = setColumnRolesBulk(val.result.columns, data.weakChannelNames, 'unused');
    validateData.set({ ...val, result: { ...val.result, columns: updated } });
    const projectId = get(activeProjectId);
    if (projectId) {
      const updates = buildProjectUpdates(updated);
      invoke('project_update', { projectId, updates }).catch(() => { /* silent */ });
    }
  }

  /**
   * v1.3.2: insights-driven recommendations.
   * Compute validateInsights using same function как InsightsPanel - ensures
   * two systems show consistent advice. Insight с action.type='exclude' или
   * 'keep_only' identifies columns to drop; ColumnMapperConfirm.recommendationFor
   * читает этот список и показывает «Исключить» соответственно.
   *
   * Audit fix (Антон 2026-05-13): фильтруем только severity 'warning' и 'error'.
   * severity='info' insights - это objective-optimization suggestions (ROI mode
   * предлагает paired budget вместо TRPs), не data-quality issues. Они могут
   * рекомендовать excludить ВАЖНЫЕ каналы (TRPs Бренд = >90% бюджета TV).
   * «Исключить» badge должен срабатывать только на жёсткие data-quality
   * проблемы (всего нулей, неактивный канал, дубликат low-quality), не на
   * оптимизационные suggestions. Info insights остаются в InsightsPanel
   * где юзер может explicit «Применить» через button.
   */
  const insightExcludeMap = $derived.by(() => {
    const result = $validateData?.result;
    if (!result) return {};
    const objective = $analysisObjective || 'roi';
    /** @type {Record<string, string>} */
    const map = {};
    try {
      const insights = validateInsights(result, objective);
      for (const ins of (insights || [])) {
        // Filter: только жёсткие issues (warning + error), не optimization tips.
        if (ins?.severity !== 'warning' && ins?.severity !== 'error') continue;
        const act = ins?.action;
        if (!act) continue;
        /** @type {string[]} */
        let excludeList = [];
        if (act.type === 'exclude' && Array.isArray(act.columns)) {
          excludeList = act.columns;
        } else if (act.type === 'keep_only' && Array.isArray(act.exclude)) {
          excludeList = act.exclude;
        }
        for (const colName of excludeList) {
          if (typeof colName === 'string' && colName && !map[colName]) {
            map[colName] = ins.text || act.label || 'Рекомендовано исключить (по результатам анализа).';
          }
        }
      }
    } catch (e) {
      console.warn('insights compute failed:', e);
    }
    return map;
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

  /**
   * v1.3.2: Сбросить шаг - вернуть Validate к исходному состоянию (как при
   * первой загрузке проекта). Очищает все user overrides и forces re-validate
   * через backend (econ_validate перепишет result.columns с auto-detected
   * roles).
   *
   * Steps:
   * 1. Reset KPI state stores (kpiType, kpiKind, perChannelInput, derivedMode,
   *    valuePerCountUnit, valuePerCountUnitSource).
   * 2. Reset rolesConfirmed flag + localStorage key.
   * 3. Reset subStep к 0.
   * 4. Clear validateData → $effect auto-triggers fresh validation.
   * 5. (Best-effort) reset excluded_columns в project.json чтобы backend
   *    auto-detection вернул pristine result.
   */
  async function handleResetStep() {
    if (validating) return;
    // 1. Reset KPI state stores.
    kpiType.set('sales');
    kpiKind.set('monetary');
    perChannelInput.set({});
    derivedMode.set('roi');
    valuePerCountUnit.set(null);
    valuePerCountUnitSource.set(null);
    // 2. Reset confirmation flag + localStorage.
    rolesConfirmed = false;
    persistRolesConfirmed(false);
    // 3. Reset substep.
    subStep = 0;
    currentKPI = 'sales';
    currentValuePerUnit = null;
    currentPerChannel = {};
    autoSuggestedValue = null;
    // 4. Reset persisted exclusion list в project (best-effort).
    const projectId = get(activeProjectId);
    if (projectId) {
      try {
        await invoke('project_update', {
          projectId,
          updates: { excluded_columns: [] },
        });
      } catch { /* best-effort */ }
    }
    // 5. Clear validateData → $effect picks up empty state и запускает fresh
    //    validation через autoRunValidate.
    validateAttempted = false;
    validateError = null;
    validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
    // $effect notices needsValidation=true → calls autoRunValidate.
  }

  /**
   * v1.3.2: real-time role change на каждое dropdown click в ColumnMapperConfirm.
   * Сразу пишет в validateData → InsightsPanel + recommendations
   * пересчитываются reactively. Эквивалент connecting в InsightsPanel.applyAction.
   *
   * @param {string} colName
   * @param {string} uiRole - UI-level role (kpi/media/control/date/excluded)
   */
  function handleRoleChange(colName, uiRole) {
    const val = get(validateData);
    if (!val?.result?.columns) return;
    const canonical = uiRole === 'excluded' ? 'unused' : uiRole;
    const updated = setColumnRolesBulk(val.result.columns, [colName], canonical);
    validateData.set({
      ...val,
      result: { ...val.result, columns: updated },
    });
    // Persist project.json (best-effort).
    const projectId = get(activeProjectId);
    if (projectId) {
      const updates = buildProjectUpdates(updated);
      invoke('project_update', { projectId, updates }).catch(() => { /* silent */ });
    }
  }

  /** @param {Record<string, string>} mapping - column name → role chosen by user */
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
      // Persist project.json (best-effort, non-blocking - matches InsightsPanel pattern).
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
    <!-- v1.3.2: «Сбросить шаг» - кнопка справа от substep nav, возвращает к
         состоянию загрузки проекта (re-runs validate, clears all overrides). -->
    <button
      type="button"
      class="reset-step-btn"
      onclick={handleResetStep}
      disabled={validating}
      title="Вернуть шаг к исходному состоянию: убрать все ваши изменения ролей и KPI, перезапустить автоматическое определение."
    >
      Сбросить шаг
    </button>
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
      <p class="loading-detail">Программа проверяет колонки и определяет роли - обычно занимает 2-5 секунд.</p>
    </div>
  {:else if validateError}
    <div class="validation-error" role="alert">
      <p class="error-title">Не удалось проверить данные</p>
      <p class="error-detail">{validateError}</p>
      <button type="button" class="btn-retry" onclick={retryValidate}>
        Повторить попытку
      </button>
    </div>
  {:else if !rolesConfirmed}
    <!-- v1.3.2: Ratio info card сверху - critical signal для data quality
         decision до выбора ролей. Manager mode: visual indicator + apply
         button. Expert mode: breakdown с weak channel names + thresholds. -->
    {#if ratioCardData}
      <div class="ratio-card-wrapper">
        <RatioInfoCard
          ratio={ratioCardData.ratio}
          nObs={ratioCardData.nObs}
          nPredictors={ratioCardData.nPredictors}
          weakChannelsCount={ratioCardData.weakChannelsCount}
          weakChannelNames={ratioCardData.weakChannelNames}
          afterExcludeRatio={ratioCardData.afterExcludeRatio}
          expertMode={$expertMode}
          onApplyExclude={applyRatioRecommendation}
        />
      </div>
    {/if}
    <ColumnMapperConfirm
      columns={detectedColumns}
      validateResult={$validateData?.result ?? null}
      insightExcludeMap={insightExcludeMap}
      onConfirm={handleRolesConfirm}
      onRoleChange={handleRoleChange}
      blockedReason={ratioBlockedReason}
    />
  {:else if subStep === 0}
    <!-- v2.0.0 (ADR-019): AnalysisModeSelector сверху Step 0.
         Manager mode выбирает ROI / Эффективность одним кликом.
         Expert mode видит дополнительную «Смешанный» опцию. -->
    <AnalysisModeSelector
      onSelect={(mode) => {
        // Auto-fill perChannelInput uniformly per chosen mode.
        const uniformValue = mode === 'effectiveness' ? 'physical' : 'monetary';
        const currentChannels = Object.keys(get(perChannelInput) || {});
        if (currentChannels.length > 0) {
          /** @type {Record<string, 'monetary' | 'physical'>} */
          const next = {};
          for (const ch of currentChannels) {
            next[ch] = uniformValue;
          }
          perChannelInput.set(next);
        }
      }}
    />
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
    <!-- v2.0.0 (ADR-019 §1): dual-mode rendering.
         Manager mode → AppliedModeSummary (read-only сводка + CTA «Включить Expert»).
         Expert mode → existing PerChannelInputSelector (per-channel control).
         Each component self-conditions via $expertMode store. -->
    <AppliedModeSummary
      channels={channels.map((name) => ({
        name,
        detectedType: $perChannelInput?.[name] ?? detectChannelType(name),
      }))}
      channelSums={channelSums}
      excludedChannelNames={excludedMediaNames}
      onRestoreChannel={(name) => handleRoleChange(name, 'media')}
    />
    <PerChannelInputSelector
      channels={channels}
      availableMetricsByChannel={availableMetricsByChannel}
      columnStats={columnStats}
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
  /* v1.3.2: Ratio info card wrapper — отступ перед ColumnMapperConfirm. */
  .ratio-card-wrapper {
    padding: 14px 32px 0;
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  }

  /* v1.3.2: «Сбросить шаг» - premium tier-1 ghost button справа от substep nav. */
  .reset-step-btn {
    margin-left: auto;
    padding: 5px 12px;
    border-radius: 3px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    color: var(--text-muted, #94a3b8);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .reset-step-btn:hover:not(:disabled) {
    border-color: var(--gold, #c9a449);
    color: var(--gold, #c9a449);
    background: color-mix(in srgb, var(--gold, #c9a449) 6%, transparent);
  }
  .reset-step-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
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
