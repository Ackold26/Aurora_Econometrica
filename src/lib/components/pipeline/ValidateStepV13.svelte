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
  // v2.1.0 (пилот 2026-05-16): плавные переходы между под-шагами Валидации.
  import { fly, fade } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { prefersReducedMotion } from '$lib/stores/a11y.js';
  import {
    kpiType, kpiKind, perChannelInput, derivedMode,
    valuePerCountUnit, valuePerCountUnitSource,
    activeProject, activeProjectId, validateData, importData,
    completeStep, setStepError, lockStep, pipelineStepMeta, pipelineCurrentStep,
    // NAV-2/3A Minimal-plus (2026-06-05): чистые предикаты вместо inline-логики.
    cppSatisfied, shouldRelockModel,
    // v2.1.0 (rc2 U-05): sync subStep в store для InsightsPanel routing.
    validateSubStep,
    // v2.1.0 (пилот 2026-05-17): persist KPI выбор → ConfigPanel.
    chosenKpiColumn,
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
    // H-16 (audit): Phase 1.3 persistence stores - нужны в save flow.
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
  import ExpertValidatePanel from './ExpertValidatePanel.svelte';
  import CorrelationHeatmap from './CorrelationHeatmap.svelte';
  // Phase 1.1 (SSOT): detection через shared service вместо inline regex.
  // Service fetches patterns from backend `/api/static/classifier-patterns-v1.json`,
  // caches в localStorage, falls back к embedded patterns если backend down.
  // Replaces previous v2.0.1 hotfix inline MONETARY_RE/PHYSICAL_RE - теперь
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
      // for excluded media - но эти cols прошли prior validator role='unused'.
      // Simple inclusion: any column с recognised unit type considered media.
      // v2.1.0 (пилот 2026-05-17 audit H-2): расширенный pattern - покрывает
      // GRP / OLV / Banner / Radio / OOH / Press / Performance / Social /
      // Search / Click / Visit / View / Impression / Reach / показ /
      // визит / просмотр / охват. Раньше отсутствие GRP/OLV/Banners
      // приводило к тому что excluded канал не появлялся в badge «N
      // исключено» в AppliedModeSummary.
      const mediaRegex = /[₽]|бюджет|budget|spend|cost|trp|grp|olv|banner|баннер|радио|radio|ooh|пресс|press|perform|social|search|click|клик|visit|визит|view|просмотр|impress|показ|reach|охват/i;
      if (detectChannelType(name) !== 'monetary' || mediaRegex.test(name)) {
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
   *  v2.0.1-rc2 REORDER (Антон's FB pilot 2026-05-15): KPISelector теперь
   *  ПЕРВЫЙ preflight, ColumnMapperConfirm - ВТОРОЙ. Логика: определяем
   *  цель (ROI vs Эффективность) → потом role classification фильтрованных
   *  колонок (sales_rub KPI → скрыть *уп., и наоборот).
   *
   *  Persisted to localStorage per projectId - юзер confirm-ит один раз
   *  на проект; повторное mount читает state. Reset через goBack button.
   *  Keys:
   *    `aurora-econ:kpi-confirmed:{projectId}` - KPI gate (new)
   *    `aurora-econ:roles-confirmed:{projectId}` - Roles gate
   *  Backward compat: если rolesConfirmed=true (legacy old flow), но
   *  kpiConfirmed=false → автоматически kpiConfirmed=true (user уже прошёл
   *  KPI step в старом flow). */
  const ROLES_CONFIRMED_KEY_PREFIX = 'aurora-econ:roles-confirmed:';
  const KPI_CONFIRMED_KEY_PREFIX = 'aurora-econ:kpi-confirmed:';

  function loadRolesConfirmed() {
    try {
      const pid = get(activeProjectId);
      if (!pid) return false;
      return localStorage.getItem(ROLES_CONFIRMED_KEY_PREFIX + pid) === '1';
    } catch {
      return false;  // localStorage может быть unavailable
    }
  }

  function loadKpiConfirmed() {
    try {
      const pid = get(activeProjectId);
      if (!pid) return false;
      const explicit = localStorage.getItem(KPI_CONFIRMED_KEY_PREFIX + pid) === '1';
      if (explicit) return true;
      // Backward compat: legacy roles-confirmed implies KPI was selected.
      const legacyRoles = localStorage.getItem(ROLES_CONFIRMED_KEY_PREFIX + pid) === '1';
      return legacyRoles;
    } catch {
      return false;
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

  /** @param {boolean} value */
  function persistKpiConfirmed(value) {
    try {
      const pid = get(activeProjectId);
      if (!pid) return;
      if (value) {
        localStorage.setItem(KPI_CONFIRMED_KEY_PREFIX + pid, '1');
      } else {
        localStorage.removeItem(KPI_CONFIRMED_KEY_PREFIX + pid);
      }
    } catch { /* best-effort */ }
  }

  let kpiConfirmed = $state(loadKpiConfirmed());
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
      // NAV-2/3A-FOOTER-BYPASS fix (Вариант B, 2026-06-04): НЕ разлочиваем Модель
      // здесь. Авто-валидация показывает результаты (validateData), но Модель
      // (stepMeta[2]) остаётся locked до прохождения CPP-гейта на подшаге «Метрики каналов»
      // (handlePerChannelConfirm). Иначе футерная «Далее» (pipeline/+layout goNext) обходила
      // CPP-гейт: Модель='ready' сразу после автовалидации → goNext перескакивал
      // подшаги «Метрики каналов» (physical+ROI без unit_cost → ROI-артефакт класса
      // TRPs 12186×). completeStep(1) перенесён в handlePerChannelConfirm (за CPP-гейтом).
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
  /**
   * v2.0.1-rc2 REORDER: substep states extended:
   *   -2 → KPISelector (new preflight, ПЕРВЫЙ)
   *   -1 → ColumnMapperConfirm (preflight, ВТОРОЙ; filtered под выбранный KPI)
   *    0 → AnalysisModeSelector + KPI confirm-edit panel (deprecated path; используется backward compat для legacy projects где kpiConfirmed setрешалось inside subStep=0)
   *    1 → ValuePerCountUnitInput (skip для monetary KPI)
   *    2 → AppliedModeSummary + PerChannelInputSelector
   *    3 → ModeDerivedExplanation
   *
   * Initial state - depends on confirmation flags:
   *   - !kpiConfirmed → -2 (KPI preflight)
   *   - kpiConfirmed && !rolesConfirmed → -1 (Roles preflight)
   *   - both true → 0 (legacy flow re-enters here; new code skips к 1/2)
   *
   * @type {-2 | -1 | 0 | 1 | 2 | 3}
   */
  let subStep = $state(
    !kpiConfirmed ? -2 : (!rolesConfirmed ? -1 : 0)
  );
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

  // ─── v2.1.0 (пилот 2026-05-16): анимация переходов между под-шагами ───
  // Отслеживаем направление: forward (правый сдвиг) vs back (левый сдвиг).
  // prefers-reduced-motion → duration 0 (мгновенно).
  // Type-cast subStep к number чтобы избежать narrowing к initial type literal
  // (subStep declared как `-2 | -1 | 0 | 1 | 2 | 3` union).
  /** @type {number} */
  let prevSubStepIdx = $state(/** @type {number} */ (subStep));
  let substepDir = $state(/** @type {'forward' | 'back'} */ ('forward'));
  $effect(() => {
    const current = /** @type {number} */ (subStep);
    if (current !== prevSubStepIdx) {
      substepDir = current > prevSubStepIdx ? 'forward' : 'back';
      prevSubStepIdx = current;
    }
  });
  const substepTransitionMs = $derived($prefersReducedMotion ? 0 : 260);
  const substepFlyOffset = $derived(
    $prefersReducedMotion ? 0 : (substepDir === 'forward' ? 32 : -32)
  );

  // v2.1.0 (rc2 U-05): sync subStep в store, чтобы InsightsPanel мог
  // показывать контекстные инсайты для текущего под-шага Валидации.
  $effect(() => {
    validateSubStep.set(/** @type {-2 | -1 | 0 | 1 | 2 | 3} */ (subStep));
  });

  /**
   * v2.1.0 (пилот 2026-05-16): handleKPISelect теперь ТОЛЬКО устанавливает
   * выбор (подсветку карточки). Конфирм и переход на следующий под-шаг
   * выполняет confirmKpiAndProceed() через явную кнопку «Далее».
   *
   * Раньше клик на карточку = и выбор, и confirm, и переход одновременно —
   * не давал пользователю передумать. После пилота 2026-05-16 разделено
   * для корректного UX: выбираешь → видишь подсветку → жмёшь «Далее».
   *
   * @param {string} id
   */
  function handleKPISelect(id) {
    currentKPI = id;
    kpiType.set(id);
    const kind = kpiKindForType(id);
    // proportional KPIs (awareness) out_of_scope_v13 - treat as monetary fallback.
    const safeKind = /** @type {'monetary' | 'count'} */ (kind === 'count' ? 'count' : 'monetary');
    kpiKind.set(safeKind);
  }

  /**
   * v2.1.0: явное подтверждение выбора KPI через кнопку «Далее».
   * Запускает persist + переход на следующий под-шаг.
   */
  async function confirmKpiAndProceed() {
    if (!currentKPI) return;  // защита от вызова без выбора
    const kind = kpiKindForType(currentKPI);

    kpiConfirmed = true;
    persistKpiConfirmed(true);

    // Если roles ещё не confirmed → next preflight = Roles.
    if (!rolesConfirmed) {
      if (kind === 'count') {
        await tryAutoDetectValue(currentKPI);
      }
      subStep = -1;
      return;
    }

    // Legacy path: оба confirmed, продолжаем в обычный flow.
    if (kind === 'monetary') {
      subStep = 2;
    } else {
      await tryAutoDetectValue(currentKPI);
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
    if (!$activeProjectId) {
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

      const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: $activeProjectId }));
      const result = await invoke('econ_auto_detect_price', {
        projectDir,
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

  // 3A (verified live 2026-06-03): флаг «physical-канал без CPP в Expert-режиме».
  let expertCppMissing = $state(false);

  /** @param {Record<string, string>} selection */
  function handlePerChannelConfirm(selection) {
    const typed = /** @type {Record<string, 'monetary' | 'physical'>} */ (selection);
    currentPerChannel = typed;
    perChannelInput.set(typed);
    // 3A (verified live 2026-06-03 desktop-control): Expert-путь должен соблюдать
    // тот же CPP-гейт, что Manager (allChannelsConfigured). Раньше handlePerChannelConfirm
    // НЕ проверял → physical-канал без CPP в ROI-режиме обучался с unit_cost=1.0 →
    // артефакт ROI (12186×). Блокируем продвижение, пока CPP/бюджет не задан.
    if (get(analysisMode) === 'roi') {
      const costs = get(unitCosts) ?? {};
      const missing = Object.keys(typed).some(
        (name) => typed[name] === 'physical'
          && !(typeof costs[name] === 'number' && /** @type {number} */ (costs[name]) > 0)
      );
      if (missing) {
        expertCppMissing = true;
        return; // не продвигаем; выбор сохранён, баннер просит задать CPP
      }
    }
    expertCppMissing = false;
    // Derive mode locally + sync to store.
    const m = deriveModeWithExplanation(typed);
    derivedMode.set(/** @type {'roi' | 'effectiveness' | 'manual'} */ (m.mode));
    // NAV-2/3A-FOOTER-BYPASS fix (Вариант B, 2026-06-04): разлочиваем Модель ЗДЕСЬ —
    // после прохождения CPP-гейта (выше: physical+ROI без unit_cost → early-return) и
    // только на ЕДИНСТВЕННОЙ точке перехода на подшаг 3 «Подтверждение». До этого Модель
    // (stepMeta[2]) locked → футер «Далее» (pipeline/+layout goNext) disabled, перескок
    // подшагов/CPP-гейта невозможен. Финальный переход подшаг 3 → Модель делает футерная
    // «Далее» (контентная кнопка в ModeDerivedExplanation убрана — инфо-строка), поэтому
    // completeStep здесь, а НЕ в handleContinue (он не привязан к кнопке = мёртв).
    completeStep(1);
    subStep = 3;
  }

  async function handleContinue() {
    busy = true;
    try {
      // Persist KPI settings to backend.
      if ($activeProjectId) {
        // H-16 (audit): Phase 1.3 store persistence - earlier версия не
        // передавала unit_costs / inflation / mode_for / budget_inputs к
        // backend. Reload терял состояние. Теперь полный snapshot.
        const projectDir = /** @type {string} */ (await invoke('project_get_dir', { projectId: $activeProjectId }));
        await invoke('econ_save_kpi_settings', {
          projectDir,
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
   * v1.3.2: subStep 0 + rolesConfirmed → goBack returns к ColumnMapperConfirm.
   * v2.0.1-rc2 REORDER (Антон pilot 2026-05-15): добавлены steps -2 (KPI),
   * -1 (Roles). Back chain: -1 → -2; 1 → -1; 2 → (skipValueStep ? -1 : 1);
   * 3 → 2. Сброс confirmation flags при отступлении.
   */
  function goBack() {
    if (subStep === -1) {
      // Из Roles preflight назад → к KPI preflight, сбросить kpiConfirmed.
      kpiConfirmed = false;
      persistKpiConfirmed(false);
      subStep = -2;
      return;
    }
    if (subStep === 1) {
      // Из ValuePerCountUnit → назад к Roles preflight, сбросить rolesConfirmed.
      rolesConfirmed = false;
      persistRolesConfirmed(false);
      subStep = -1;
      return;
    }
    if (subStep === 2) {
      subStep = skipValueStep ? -1 : 1;
      if (skipValueStep) {
        rolesConfirmed = false;
        persistRolesConfirmed(false);
      }
      return;
    }
    if (subStep === 3) {
      subStep = 2;
      return;
    }
    // subStep === 0 (legacy backward compat): отступаем к -1.
    if (subStep === 0) {
      rolesConfirmed = false;
      persistRolesConfirmed(false);
      subStep = -1;
      return;
    }
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
   * v2.0.1-rc2 REORDER: KPI-driven фильтрация колонок для ColumnMapperConfirm.
   * После выбора KPI скрываем irrelevant unit-mismatch колонки. Логика mirrors
   * design doc `docs/v2_0_0_design/REORDER_SUBSTEPS_v2_1_0.md`:
   * - sales_rub KPI → скрыть `*в уп.*`, `*в шт.*` (count-only sales)
   * - count KPI (sales_packs/leads/etc.) → скрыть `*в руб.*`, revenue, выручка, profit
   * - Always show: date, media, KPI itself
   *
   * Edge cases:
   * - kpiConfirmed=false → no filter (показываем все cols).
   * - currentKpiKind null/undefined → fallback на 'monetary' filter.
   */
  const filteredColumns = $derived.by(() => {
    const all = detectedColumns;
    if (!kpiConfirmed || !Array.isArray(all) || all.length === 0) return all;
    const kind = currentKpiKind;
    return all.filter((c) => {
      // Always show: date, media, KPI itself.
      if (c.role === 'date' || c.role === 'media' || c.role === 'kpi') return true;
      const name = String(c.name ?? '');
      if (kind === 'monetary') {
        // Hide count-only sales cols (sales_rub KPI выбран → «в уп.» irrelevant).
        if (/(в уп\.|в шт\.|в pack)/i.test(name)) return false;
      } else if (kind === 'count') {
        // Hide ₽-only sales cols (count KPI → «в руб.» irrelevant).
        if (/(в руб|revenue|выручка|profit)/i.test(name)) return false;
      }
      return true;
    });
  });

  /**
   * v1.3.2: Ratio info card data - computed from validateData + columns stats.
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
   * объяснением - нельзя продолжить до улучшения data quality.
   * Reason text включает текущее значение, требуемый минимум, и actionable
   * recommendation (исключить N weak каналов).
   */
  const ratioBlockedReason = $derived.by(() => {
    const data = ratioCardData;
    if (!data) return null;
    if (data.ratio >= 2) return null;  // unblock at ratio >= 2:1
    const after = data.afterExcludeRatio;
    const canFix = data.weakChannelsCount > 0 && after != null && after >= 2;
    let reason = `Текущий ratio ${data.ratio.toFixed(1)}:1 ниже минимального 2:1 - модель «выучит» точки вместо закономерности. `;
    if (canFix) {
      reason += `Исключите ${data.weakChannelsCount} малоактивн${data.weakChannelsCount === 1 ? 'ый канал' : data.weakChannelsCount < 5 ? 'ых канала' : 'ых каналов'} (кнопка «Применить рекомендацию» выше) → ratio станет ${after.toFixed(1)}:1.`;
    } else {
      reason += `Добавьте больше истории (≥52 недель) или сократите число каналов в модели.`;
    }
    return reason;
  });

  /**
   * v2.1.0 (rc2 retry): hard-block если 0 или >1 целевых метрик.
   * MMM-модель ОБЯЗАНА обучаться на ОДНОЙ зависимой переменной (KPI).
   * Раньше backend silently выбирал первую при множественных KPI -
   * пользователь не понимал результат. Теперь явная блокировка с
   * подсказкой что делать.
   */
  const kpiCountBlockedReason = $derived.by(() => {
    const cols = $validateData?.result?.columns;
    if (!Array.isArray(cols)) return null;
    const kpiCols = cols.filter((/** @type {any} */ c) => c?.role === 'kpi');
    if (kpiCols.length === 1) return null;  // ровно одна - OK
    if (kpiCols.length === 0) {
      return 'Не выбрана целевая метрика. MMM-модель требует одну колонку с ролью «Целевая метрика» - выберите её в таблице ниже.';
    }
    // > 1 KPI - блок с предложением выбрать одну
    const names = kpiCols.map((/** @type {any} */ c) => `«${c.name}»`).join(', ');
    return `Найдено ${kpiCols.length} целевых метрик: ${names}. MMM-модель обучается на одной зависимой переменной. Оставьте одну (главную для текущего режима), остальные отметьте как «Не использовать».`;
  });

  /** Объединённый blockedReason: ratio priority > KPI count priority */
  const validateBlockedReason = $derived(
    ratioBlockedReason ?? kpiCountBlockedReason
  );

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

  /**
   * U-01/4d (пилот 2026-05-16): проверка готовности всех каналов в Manager mode.
   * Кнопка «Далее» активна когда:
   *   - все physical-каналы в ROI mode имеют unit_cost > 0 (CPP-конверсия задана)
   *   - В effectiveness mode physical-каналы готовы без конверсии
   *   - monetary-каналы всегда готовы (бюджет в ₽ уже есть)
   * Mirrors логику AppliedModeSummary.incompatibleCount.
   */
  // NAV-2/3A Minimal-plus (2026-06-05): делегат к SSOT-предикату cppSatisfied
  // (project-state.js). Единственное определение CPP-гейта; тот же предикат
  // защищает chokepoint completeStep(1). channels = prop (media из validateData,
  // +page.svelte:39-45). Поведение байт-в-байт с прежним inline $derived.by.
  const allChannelsConfigured = $derived(cppSatisfied({
    channels,
    perChannelInput: $perChannelInput,
    unitCosts: $unitCosts,
    analysisMode: $analysisMode,
  }));

  // NAV-2/3A-FOOTER-BYPASS guard (2026-06-04): completeStep(1) — one-way latch (никогда не
  // ре-локает). Если Модель ('ready') разлочена, но пользователь НЕ на финальном подшаге
  // «Подтверждение» (subStep < 3) ИЛИ CPP-гейт перестал быть удовлетворён (goBack 3→2,
  // изменил канал на physical, убрал unit_cost, ИЛИ reload посреди валидации с subStep=-2 и
  // Модель='ready' от reconcileStepMetaFromDisk) — ре-локаем Модель. Иначе футер «Далее»
  // (pipeline/+layout goNext проверяет только status !== 'locked', НЕ allChannelsConfigured)
  // перескочит CPP-гейт → physical+ROI без unit_cost → ROI-артефакт (TRPs 12186×). Легитимный
  // разлок — ТОЛЬКО handlePerChannelConfirm (за CPP-гейтом). 'complete' (обучена) не трогаем.
  $effect(() => {
    if ($pipelineCurrentStep !== 1) return;  // контекстный скоуп — guard живёт только на шаге Валидация
    if (shouldRelockModel({ subStep, cppSatisfied: allChannelsConfigured, status: $pipelineStepMeta[2]?.status })) {
      lockStep(2);
    }
  });

  /**
   * U-01/4d (пилот 2026-05-16): подтверждение метрик каналов в Manager mode.
   * Формирует currentPerChannel из perChannelInput store (или auto-detected типов)
   * и вызывает handlePerChannelConfirm → subStep = 3.
   */
  function confirmMetricsAndProceed() {
    /** @type {Record<string, 'monetary' | 'physical'>} */
    const snapshot = {};
    for (const name of channels) {
      const t = $perChannelInput?.[name] ?? detectChannelType(name);
      snapshot[name] = /** @type {'monetary' | 'physical'} */ (t === 'physical' ? 'physical' : 'monetary');
    }
    handlePerChannelConfirm(snapshot);
  }

  // v2.0.1-rc2 REORDER: КPI preflight first (subStep=-2), Roles preflight
  // second (subStep=-1). Legacy subStep=0 (AnalysisModeSelector + KPI panel)
  // удалён из nav - теперь KPI selection происходит в preflight, panel не
  // нужен. Если existing project имеет subStep=0 (backward compat) - nav
  // показывает «Подтверждение» как next active.
  const navStages = $derived.by(() => {
    /** @type {Array<{label: string, subStep: number}>} */
    const stages = [
      { label: 'Целевая метрика', subStep: -2 },
      { label: 'Роли колонок', subStep: -1 },
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
    // 2. Reset confirmation flags + localStorage.
    // v2.0.1-rc2 REORDER: reset обоих gates.
    kpiConfirmed = false;
    persistKpiConfirmed(false);
    rolesConfirmed = false;
    persistRolesConfirmed(false);
    // 3. Reset substep к новому первому preflight.
    subStep = -2;
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
    // v2.1.0 (пилот 2026-05-17 audit H-8): real-time KPI persistence.
    // Раньше chosenKpiColumn писалось только на handleRolesConfirm -
    // ConfigPanel читал stale значение после dropdown override.
    if (canonical === 'kpi') {
      chosenKpiColumn.set(colName);
    } else {
      // Если юзер снял role='kpi' с колонки - проверим, какая ещё имеет KPI.
      const stillKpi = updated.find((c) => c.role === 'kpi');
      if (stillKpi) chosenKpiColumn.set(stillKpi.name);
    }
    // Persist project.json (best-effort).
    const projectId = get(activeProjectId);
    if (projectId) {
      const updates = buildProjectUpdates(updated);
      invoke('project_update', { projectId, updates }).catch(() => { /* silent */ });
    }
  }

  /** @param {Record<string, string>} mapping - column name → role chosen by user */
  async function handleRolesConfirm(mapping) {
    // v2.1.0 (пилот 2026-05-17): persist выбор KPI колонки чтобы ConfigPanel
    // не сбрасывал dropdown на «первый KPI alphabetically».
    {
      const kpiName = Object.entries(mapping)
        .find(([, role]) => role === 'kpi')?.[0];
      if (kpiName) chosenKpiColumn.set(kpiName);
    }
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
    // v2.0.1-rc2 REORDER: после подтверждения ролей → переход напрямую к
    // ValuePerCountUnit (count KPI) или к Channels (monetary KPI).
    // Прежний KPI substep (=0) удалён - KPI уже выбран в preflight.
    subStep = skipValueStep ? 2 : 1;
  }
</script>

<div class="validate-v13">
  <!-- Sub-step progress indicator -->
  <!-- v1.3.2 audit fix (B2): explicit subStep mapping via navStages $derived
       чтобы skipValueStep collapse не ломал нумерацию dots. -->
  <nav class="substep-nav">
    {#each navStages as stage, displayIdx}
      {@const stageIdx = stage.subStep}
      {@const isActive = stageIdx === subStep}
      {@const isDone = (
        (stageIdx === -2 && kpiConfirmed) ||
        (stageIdx === -1 && rolesConfirmed) ||
        (stageIdx >= 0 && rolesConfirmed && stageIdx < subStep)
      )}
      <!-- NAV-2 (2026-06-02): клик по ПРОЙДЕННОМу (done) подшагу возвращает к нему.
           Вперёд (не-done) - только через контентную «Далее» с гейтами валидации. -->
      <button
        type="button"
        class="substep-dot"
        class:active={isActive}
        class:done={isDone}
        class:clickable={isDone && !isActive}
        disabled={!isDone || isActive}
        title={isDone && !isActive ? 'Вернуться к этому подшагу' : ''}
        onclick={() => { if (isDone && !isActive) subStep = /** @type {-2 | -1 | 0 | 1 | 2 | 3} */ (stageIdx); }}
      >
        <span class="dot-number">{displayIdx + 1}</span>
        <span class="dot-label">{stage.label}</span>
      </button>
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

  {#if subStep === -1}
    <button class="back-link" onclick={goBack}>← Изменить целевую метрику</button>
  {:else if subStep >= 1}
    <button class="back-link" onclick={goBack}>← Назад</button>
  {:else if subStep === 0}
    <!-- Legacy backward compat path - не должен triggered в new flow. -->
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
  {:else}
  <!-- v2.1.0 (пилот 2026-05-16): плавный переход между под-шагами Валидации.
       {#key subStep} форсит remount при смене, fly/fade даёт направленный slide. -->
  {#key subStep}
  <div
    class="substep-frame"
    in:fly={{ x: substepFlyOffset, duration: substepTransitionMs, easing: cubicOut, delay: substepTransitionMs > 0 ? 60 : 0 }}
    out:fade={{ duration: substepTransitionMs / 2 }}
  >
  {#if subStep === -2}
    <!-- v2.0.1-rc2 REORDER (Антон pilot 2026-05-15): KPI preflight FIRST.
         Сначала AnalysisModeSelector (ROI / Эффективность / Mixed Expert),
         потом KPISelector - после select переходим к Roles preflight. -->
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
    <div data-tour-step="kpi-selector">
      <KPISelector
        onSelect={handleKPISelect}
        currentKPI={currentKPI}
        availableKpiTypes={$validateData?.result?.available_kpi_types ?? null}
      />
    </div>
    <!-- v2.1.0 (пилот 2026-05-16): явная кнопка «Далее» под KPISelector.
         Раньше клик на карточку сразу переключал под-шаг — пользователь
         не мог пересмотреть выбор. Теперь выбор подсвечивается,
         подтверждение через эту кнопку. -->
    <div class="substep-footer">
      <button
        type="button"
        class="substep-next-btn"
        onclick={confirmKpiAndProceed}
        disabled={!currentKPI}
      >
        Далее ▶
      </button>
    </div>
  {:else if subStep === -1}
    <!-- v2.0.1-rc2 REORDER: Roles preflight, ColumnMapperConfirm с
         filteredColumns под выбранный KPI. Ratio card + insight exclude
         pattern preserved из старого flow. -->
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
      columns={filteredColumns}
      validateResult={$validateData?.result ?? null}
      insightExcludeMap={insightExcludeMap}
      onConfirm={handleRolesConfirm}
      onRoleChange={handleRoleChange}
      blockedReason={validateBlockedReason}
    />
  {:else if subStep === 0}
    <!-- Legacy backward compat: old projects где flow дошёл к subStep=0 -
         показываем AnalysisModeSelector + KPISelector (старая логика). После
         КPI select перешли к subStep=2 (если monetary) или 1 (если count).
         Новые projects никогда не достигают subStep=0. -->
    <AnalysisModeSelector
      onSelect={(mode) => {
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
    <!-- U-01/4d (пилот 2026-05-16): Manager mode — явная кнопка «Далее».
         Без Expert mode пользователь не мог активировать глобальную кнопку
         «Далее» в footer pipeline — она была заблокирована пока не пройдена
         PerChannelInputSelector. UX-антипаттерн: корректно настроенные каналы
         (₽-бюджет / physical с CPP) требовали обязательного захода в Expert.
         Теперь Manager-path сам подтверждает через confirmMetricsAndProceed(). -->
    {#if !$expertMode}
      <div class="substep-footer">
        <button
          type="button"
          class="substep-next-btn"
          onclick={confirmMetricsAndProceed}
          disabled={!allChannelsConfigured}
          title={allChannelsConfigured
            ? 'Перейти к подтверждению режима анализа'
            : 'Укажите стоимость 1 единицы (CPP) для всех физических каналов в ROI-режиме'}
        >
          Далее ▶
        </button>
      </div>
    {/if}
    {#if expertCppMissing}
      <div class="expert-cpp-banner" role="alert">
        ⚠ Для физических каналов (TRP / показы / клики) в ROI-режиме укажите стоимость
        единицы (CPP/CPM) или общий бюджет ₽ выше - без этого ROI канала некорректен
        (точки трактуются как рубли). Либо переключите канал на «₽-бюджет» или исключите.
      </div>
    {/if}
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
  </div>
  {/key}
  {/if}

  {#if $expertMode && $validateData?.result}
    <section class="expert-extras">
      <header class="expert-header">
        <h3>Расширенная диагностика</h3>
        <p class="expert-lead">
          Дополнительные показатели для аналитиков: матрица корреляций,
          мультиколлинеарность (VIF), детальные статистики по колонкам.
        </p>
      </header>
      <CorrelationHeatmap
        correlationMatrix={$validateData?.result?.full_correlation_matrix ?? { labels: [], matrix: [] }}
        highCorrelations={$validateData?.result?.high_correlations ?? []}
      />
      <ExpertValidatePanel />
    </section>
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
    /* v2.1.0 (пилот 2026-05-16): убран overflow-y - родительский .pipeline-main
       уже скроллится. Двойной scroll давал два scrollbar подряд. */
    box-sizing: border-box;
    position: relative;
  }
  /* v2.1.0 (пилот 2026-05-16): обёртка для плавного перехода между под-шагами. */
  .substep-frame {
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: 100%;
  }
  @media (prefers-reduced-motion: reduce) {
    .substep-frame {
      transform: none !important;
    }
  }

  /* v2.1.0 (пилот 2026-05-16): footer с кнопкой «Далее» под KPISelector. */
  .substep-footer {
    display: flex;
    justify-content: flex-end;
    padding: 16px 24px 8px;
  }
  /* 3A (2026-06-03): баннер про незаданный CPP в Expert-режиме (ROI). */
  .expert-cpp-banner {
    margin: 0 0 12px;
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--gold, #d4a843);
    background: color-mix(in srgb, var(--gold, #d4a843) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--gold, #d4a843) 35%, transparent);
  }
  .substep-next-btn {
    padding: 10px 20px;
    border-radius: 8px;
    background: var(--accent-primary);
    color: #fff;
    border: none;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s, transform 0.1s;
  }
  .substep-next-btn:hover { opacity: 0.9; }
  .substep-next-btn:active { transform: translateY(1px); }
  .substep-next-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .substep-nav {
    display: flex;
    gap: 0;
    align-items: center;
    padding: 12px 24px;
    background: var(--bg-surface-quiet);
    border-bottom: 1px solid var(--border-subtle);
  }
  /* v1.3.2: Ratio info card wrapper - отступ перед ColumnMapperConfirm. */
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
    /* NAV-2: точка теперь button - сбрасываем дефолты, чтобы выглядеть как был div. */
    background: none;
    border: none;
    font-family: inherit;
    cursor: default;
  }
  .substep-dot.clickable { cursor: pointer; }
  .substep-dot.clickable:hover {
    background: color-mix(in srgb, var(--success, #4ade80) 12%, transparent);
  }
  .substep-dot:disabled { cursor: default; }
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

  /* v2.1.0 п.5.6: static spinner ring */
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      border-color: color-mix(in srgb, var(--accent-primary) 70%, transparent);
    }
  }

  /* M-02 (пилот 2026-05-16): Expert mode расширенная диагностика */
  .expert-extras {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 20px 24px;
    margin-top: 8px;
    border-top: 1px solid var(--border-subtle);
    background: color-mix(in srgb, var(--accent-primary) 4%, transparent);
  }
  .expert-header h3 {
    margin: 0 0 4px;
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }
  .expert-lead {
    margin: 0 0 12px;
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
</style>
