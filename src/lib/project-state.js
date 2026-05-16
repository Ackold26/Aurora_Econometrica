/**
 * Econometrica project state - shared across cabinets and pipeline.
 * Phase 1: Extended to 6-step pipeline state machine.
 *
 * A4: localStorage persists only metadata (step statuses, currentStep).
 *     Step data lives exclusively in memory stores.
 * A5: resetDownstream() cascades locked status to all downstream steps.
 *
 * @module project-state
 */
import { writable, derived, get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import { classifyRatio, severityTo3Tier } from './ratio-classifier.js';

/** @type {import('svelte/store').Writable<string|null>} Active project ID */
export const activeProjectId = writable(null);

/** @type {import('svelte/store').Writable<any|null>} Active project info */
export const activeProject = writable(null);

/**
 * @typedef {Object} ProjectData
 * @property {boolean} loaded
 * @property {string|null} file
 * @property {any[]|null} columns
 * @property {any|null} validation
 */

/**
 * @typedef {Object} ModelState
 * @property {boolean} trained
 * @property {any|null} diagnostics
 * @property {any|null} channelParams
 * @property {string|null} picklePath
 */

/**
 * @typedef {Object} PipelineState
 * @property {ProjectData} data
 * @property {ModelState} model
 * @property {any|null} decomposition
 * @property {any|null} optimization
 * @property {any[]} scenarios
 * @property {any|null} awareness
 */

/** @type {import('svelte/store').Writable<PipelineState>} Legacy state for cabinet (chat-first) flow */
export const pipelineState = writable({
  data: { loaded: false, file: null, columns: null, validation: null },
  model: { trained: false, diagnostics: null, channelParams: null, picklePath: null },
  decomposition: null,
  optimization: null,
  scenarios: [],
  awareness: null,
});

/** Legacy pipeline step (0-3) for cabinet breadcrumbs: 0=no data, 1=data ready, 2=model trained, 3=analyzed */
export const pipelineStep = derived(pipelineState, ($s) => {
  if (!$s.data.loaded) return 0;
  if (!$s.model.trained) return 1;
  if (!$s.decomposition) return 2;
  return 3;
});

// ===================================================================
// Phase 1: Visual Pipeline State Machine (6 steps)
// ===================================================================

export const PIPELINE_STEPS = [
  { id: 'import',    label: 'Import',    labelRu: 'Импорт',       icon: '📥' },
  { id: 'validate',  label: 'Validate',  labelRu: 'Валидация',    icon: '✅' },
  { id: 'model',     label: 'Model',     labelRu: 'Модель',       icon: '🧠' },
  { id: 'decompose', label: 'Decompose', labelRu: 'Декомпозиция', icon: '🔬' },
  { id: 'optimize',  label: 'Optimize',  labelRu: 'Оптимизация',  icon: '🎯' },
  { id: 'report',    label: 'Report',    labelRu: 'Отчёт',        icon: '📋' },
];

/**
 * @typedef {'locked'|'ready'|'active'|'complete'|'error'} StepStatus
 */

/**
 * @typedef {Object} StepMeta
 * @property {StepStatus} status
 * @property {string|null} [errorMessage]
 */

const PIPELINE_META_KEY = 'econ-pipeline-meta';

/** @returns {StepMeta[]} */
function defaultStepMeta() {
  return [
    { status: 'ready' },   // Import: always ready
    { status: 'locked' },
    { status: 'locked' },
    { status: 'locked' },
    { status: 'locked' },
    { status: 'locked' },
  ];
}

/**
 * A4: Load step metadata from localStorage (statuses only, no data).
 * @param {string|null} projectId
 * @returns {{ currentStep: number, steps: StepMeta[] }}
 */
function loadPipelineMeta(projectId) {
  try {
    const key = projectId ? `${PIPELINE_META_KEY}-${projectId}` : PIPELINE_META_KEY;
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.steps) && parsed.steps.length === 6) return parsed;
    }
  } catch { /* corrupted - use default */ }
  return { currentStep: 0, steps: defaultStepMeta() };
}

/**
 * A4: Persist only step metadata (statuses + currentStep) to localStorage.
 * @param {string|null} projectId
 * @param {{ currentStep: number, steps: StepMeta[] }} meta
 */
function savePipelineMeta(projectId, meta) {
  try {
    const key = projectId ? `${PIPELINE_META_KEY}-${projectId}` : PIPELINE_META_KEY;
    localStorage.setItem(key, JSON.stringify({
      currentStep: meta.currentStep,
      steps: meta.steps.map(s => ({ status: s.status, errorMessage: s.errorMessage ?? null })),
    }));
  } catch { /* ignore */ }
}

/** @type {import('svelte/store').Writable<number>} Active pipeline step index (0-5) */
export const pipelineCurrentStep = writable(0);

/**
 * Expert mode toggle - persisted in localStorage.
 * false = Marketer mode (simplified, auto-defaults)
 * true = Expert mode (full controls, diagnostics, priors)
 */
function createExpertStore() {
  let initial = false;
  try {
    const v = typeof localStorage !== 'undefined' ? localStorage.getItem('econ-expert-mode') : null;
    if (v) initial = JSON.parse(v);
  } catch { /* use default */ }
  const store = writable(initial);
  store.subscribe(v => {
    try { localStorage.setItem('econ-expert-mode', JSON.stringify(v)); } catch { /* ignore */ }
  });
  return store;
}
/** @type {import('svelte/store').Writable<boolean>} */
export const expertMode = createExpertStore();

// ─── Phase 2 (Planning Mode) - audit pass 2 2026-05-02 ───
// Opt-in planning mode toggle. analyst (default) = current behavior preserved
// byte-exact. planner = Option C per-period Hill summation + forecast horizon
// decoupling. Persisted per session (NOT per project - global preference).

/**
 * Planning mode toggle for OptimizeStep. Phase 2 - Aurora Econometrica next-gen
 * mode. analyst = look at past performance (current behavior); planner = future
 * allocation для planning horizon.
 * @returns {import('svelte/store').Writable<'analyst'|'planner'>}
 */
function createPlanningModeStore() {
  /** @type {'analyst'|'planner'} */
  let initial = 'analyst';
  try {
    const v = typeof localStorage !== 'undefined' ? localStorage.getItem('econ-planning-mode') : null;
    if (v === 'planner' || v === 'analyst') initial = v;
  } catch { /* default */ }
  const store = writable(/** @type {'analyst'|'planner'} */ (initial));
  store.subscribe(v => {
    try { localStorage.setItem('econ-planning-mode', v); } catch { /* ignore */ }
  });
  return store;
}
/** @type {import('svelte/store').Writable<'analyst'|'planner'>} */
export const planningMode = createPlanningModeStore();

/**
 * Forecast configuration for planning mode. Reactive: changes trigger forecast-
 * scaling preview (see OptimizeStep $effect). Cleared when planningMode = analyst.
 * @typedef {{
 *   periods: number | null,
 *   periodLabel: string | null,
 *   budgetMoney: number | null,
 *   inflationPerChannel: Record<string, number> | null,
 * }} ForecastConfig
 *
 * @type {import('svelte/store').Writable<ForecastConfig>}
 */
export const forecastConfig = writable({
  periods: null,
  periodLabel: null,
  budgetMoney: null,
  inflationPerChannel: null,
});

/**
 * Cached forecast-context preview (from /compute/forecast-context endpoint).
 * Populated when planning mode activated; cleared on project change.
 * @typedef {{
 *   training_granularity: string | null,
 *   seasonality_detected: { period: number, autocorr: number } | null,
 *   train_n_periods: number,
 *   train_x_norm_quantiles: Record<string, Record<string, number>>,
 *   forecast_horizon_max_multiplier: number,
 *   forecast_horizon_warn_multiplier: number,
 * } | null}
 *
 * @type {import('svelte/store').Writable<any>}
 */
export const forecastContext = writable(null);

/** @type {import('svelte/store').Writable<StepMeta[]>} Step metadata (statuses only, no data) */
export const pipelineStepMeta = writable(defaultStepMeta());

// --- A4: In-memory data stores - never persisted to localStorage ---

/**
 * Imported file state. Optional fields populated после econ_data_preview:
 * - shape: {rows, cols} от backend preview response
 * - fileName: original filename (для UI display)
 *
 * @type {import('svelte/store').Writable<{
 *   file: string|null,
 *   columns: any[]|null,
 *   rows: any[]|null,
 *   shape?: {rows: number, cols: number}|null,
 *   fileName?: string|null
 * }>}
 */
export const importData = writable({ file: null, columns: null, rows: null });

/** @type {import('svelte/store').Writable<{result: any|null, correlationMatrix: any|null, columnHistograms: any|null}>} */
export const validateData = writable({ result: null, correlationMatrix: null, columnHistograms: null });

/**
 * v2.1.0 (rc2 U-05 fix): текущий под-шаг внутри Валидации.
 * Значения соответствуют ValidateStepV13.subStep:
 *   -2 = «Целевая метрика» (KPISelector + AnalysisModeSelector)
 *   -1 = «Роли колонок» (ColumnMapperConfirm)
 *    0 = legacy backward compat
 *    1 = value per count unit (для count KPIs)
 *    2 = «Метрики каналов» (AppliedModeSummary / PerChannelInputSelector)
 *    3 = «Подтверждение» (ModeDerivedExplanation)
 *
 * Используется InsightsPanel для контекстной маршрутизации - на каждом
 * под-шаге свой набор инсайтов (Целевая метрика - про выбор режима/KPI,
 * Роли колонок - про роли, и т.д.).
 *
 * @type {import('svelte/store').Writable<-2 | -1 | 0 | 1 | 2 | 3>}
 */
export const validateSubStep = writable(-2);

/**
 * v2.1.0 (пилот 2026-05-17): имя KPI колонки, выбранной юзером на Валидации.
 * ConfigPanel читает этот store для initial selectedKpi - чтобы при смене
 * KPI на Валидации dropdown на шаге Модель показал тот же выбор.
 *
 * Раньше ConfigPanel брал validation.columns.filter(role='kpi')[0].name
 * (первый KPI alphabetically) - что давало «Продажи в руб. бренд» когда
 * Антон выбирал «Продажи в уп. бренд».
 *
 * @type {import('svelte/store').Writable<string | null>}
 */
export const chosenKpiColumn = writable(/** @type {string | null} */ (null));

/**
 * v2.1.0 (пилот 2026-05-16): writable набор active media-каналов на шаге
 * Модель. Ключ - имя канала, значение - включён (галочка стоит) или нет.
 *
 * ConfigPanel при каждом тоггле / init пишет состояние. InsightsPanel и
 * прочие читают, чтобы инсайты («10 медиаканалов»), оценка времени и
 * adstock-меток были согласованы с реально активными каналами, не со всеми
 * media-ролями из validateResult.
 *
 * @type {import('svelte/store').Writable<Record<string, boolean>>}
 */
export const modelChannelEnabled = writable(/** @type {Record<string, boolean>} */ ({}));

/**
 * Derived: names of active media channels on шаге Модель (filter по
 * modelChannelEnabled === true). Источник правды для insights / adstock /
 * time estimate.
 *
 * @type {import('svelte/store').Readable<string[]>}
 */
export const modelEnabledMediaNames = derived(modelChannelEnabled, ($map) => {
  return Object.entries($map).filter(([, v]) => v).map(([k]) => k);
});

/**
 * Derived store: ключевые параметры валидации для sticky header.
 * Reactively пересчитывается при смене ролей columns / запуска валидации.
 * Возвращает null если валидация не выполнена.
 *
 * @type {import('svelte/store').Readable<{
 *   ratio: number,
 *   ratioStatus: 'ok'|'warn'|'bad',
 *   ratioSeverity: 'error'|'warning-high'|'warning'|'info'|'success'|'unknown',
 *   ratioMessage: string,
 *   ratioLabel: string,
 *   ratioTone: 'danger'|'warn-strong'|'warn'|'info'|'success'|'neutral',
 *   maxVif: number|null,
 *   vifStatus: 'ok'|'warn'|'bad'|'na',
 *   nObs: number,
 *   nPredictors: number,
 *   activeMedia: number,
 *   activeControls: number,
 *   periodStatus: 'ok'|'warn'|'bad',
 *   mqs: number,
 *   mqsStatus: 'ok'|'warn'|'bad'
 * } | null>}
 */
export const validationHeaderMetrics = derived(validateData, ($vd) => {
  const result = $vd?.result;
  if (!result) return null;

  // v2.1.0 (пилот 2026-05-16 B-02): ratio считается из ТЕКУЩИХ ролей колонок,
  // не из stale `result.detected.ratio` (которое было посчитано один раз
  // при первом econ_validate и не пересчитывается при frontend exclusions).
  // Эконометрически - ratio = n_observations / (media + control predictors).
  // Согласовано с ValidateStepV13.ratioCardData (single source of truth).
  const nObs = Number(result.file?.rows ?? result.detected?.n_rows ?? 0) || 0;
  const cols = /** @type {any[]} */ (result.columns ?? []);
  const mediaCols = cols.filter(c => c.role === 'media');
  const activeMedia = mediaCols.length;
  const controlCols = cols.filter(c => c.role === 'control');
  const activeControls = controlCols.length;
  const nPredictors = activeMedia + activeControls;
  const ratio = nObs > 0 && nPredictors > 0 ? nObs / nPredictors : 0;

  // VIF max - collinearity worst-case среди media каналов
  const vifs = mediaCols
    .map(c => Number(c.stats?.vif))
    .filter(v => Number.isFinite(v));
  const maxVif = vifs.length ? Math.max(...vifs) : null;

  // MQS prognosis heuristic - sanity check готовности данных до обучения
  let score = 100;
  if (ratio < 2) score -= 40;
  else if (ratio < 4) score -= 25;
  else if (ratio < 10) score -= 10;
  if (maxVif != null) {
    if (maxVif > 10) score -= 25;
    else if (maxVif > 5) score -= 10;
  }
  if (nObs < 12) score -= 25;
  else if (nObs < 24) score -= 8;
  if (activeMedia === 0) score = Math.min(score, 20);
  const mqs = Math.max(0, Math.min(100, score));

  /**
   * @param {number} v @param {number} okMin @param {number} warnMin
   * @returns {'ok'|'warn'|'bad'}
   */
  const tierUp = (v, okMin, warnMin) => v >= okMin ? 'ok' : (v >= warnMin ? 'warn' : 'bad');
  /**
   * @param {number} v @param {number} okMax @param {number} warnMax
   * @returns {'ok'|'warn'|'bad'}
   */
  const tierDown = (v, okMax, warnMax) => v <= okMax ? 'ok' : (v <= warnMax ? 'warn' : 'bad');

  // v2.1.0 (пилот 2026-05-16, стандартизация ratio): SSOT-классификатор
  // вернёт severity / label / description / tone в одном объекте. Все UI-
  // компоненты импортируют classifyRatio из ratio-classifier.js, чтобы не
  // плодить рассогласованные пороги и тексты (Антон: «надо стандартизировать
  // оценки по коридорам ratio»).
  const ratioClass = classifyRatio(ratio);
  const ratioSeverity = ratioClass.severity;
  const ratioMessage = ratioClass.description;
  const ratioLabel = ratioClass.label;
  const ratioTone = ratioClass.tone;
  // ratioStatus - legacy 3-tier для traffic-light UI badges (где нет места
  // на 5 коридоров). Через severityTo3Tier чтобы маппинг был согласован.
  const ratioStatusAligned = /** @type {'ok'|'warn'|'bad'} */ (
    severityTo3Tier(ratioSeverity) === 'na' ? 'bad' : severityTo3Tier(ratioSeverity)
  );

  return {
    ratio,
    ratioStatus: ratioStatusAligned,
    /** v2.1.0: расширенная severity (5 уровней) для UI badges и инсайтов */
    ratioSeverity,
    ratioMessage,
    /** v2.1.0 (пилот 2026-05-16): короткий label из ratio-classifier SSOT. */
    ratioLabel,
    /** v2.1.0 (пилот 2026-05-16): tone для CSS из ratio-classifier SSOT. */
    ratioTone,
    maxVif,
    vifStatus: maxVif == null ? /** @type {'na'} */ ('na') : tierDown(maxVif, 5, 10),
    nObs,
    nPredictors,
    activeMedia,
    activeControls,
    periodStatus: tierUp(nObs, 24, 12),
    mqs,
    mqsStatus: tierUp(mqs, 80, 60),
  };
});

/**
 * v2.1.0 (пилот 2026-05-16 B-02): alias для validationHeaderMetrics с понятным
 * именем для использования в derived components. Это single source of truth
 * для всех validation metrics (ratio, VIF, nObs, MQS, severity).
 *
 * Раньше: sticky header / RatioInfoCard / Insights считали ratio из разных
 * источников - получали разные значения одновременно (state propagation bug).
 *
 * Теперь: все читают `validationMetrics` (или его alias) - гарантия sync.
 */
export const validationMetrics = validationHeaderMetrics;

/**
 * Trust Level 2: стоимость 1 юнита канала в валюте KPI (CPP/CPM).
 * Для каналов в рублях - 1.0 или отсутствие ключа.
 * Загружается из project.unit_costs при активации проекта, сохраняется через project_update.
 * @type {import('svelte/store').Writable<Record<string, number>>}
 */
export const unitCosts = writable({});
// Phase 2 audit pass 4 - per-channel annual inflation pct (CPP/CPM rate).
// Customer enters current cost (latest training year) + annual rate; backend
// computes training-period weighted-average для math-correct ROI/mROAS.
/** @type {import('svelte/store').Writable<Record<string, number>>} */
export const unitCostInflation = writable(/** @type {Record<string, number>} */ ({}));

/**
 * Phase 1.3 (v2.0.1) - persist per-channel UI mode preference.
 * Tracks whether user заполняет unit_cost через 'budget' (total ₽) or
 * 'unit' (price + inflation) mode. Survives reload через project.json.
 *
 * Audit P-03 fix: previously local $state в AppliedModeSummary - reload
 * losed mode preference, user re-decided every time.
 *
 * @type {import('svelte/store').Writable<Record<string, 'budget' | 'unit'>>}
 */
export const unitCostInputMode = writable(/** @type {Record<string, 'budget' | 'unit'>} */ ({}));

/**
 * Phase 1.3 (v2.0.1) - raw budget input string per channel (для UI restore).
 * Stored как string чтобы preserve user typing (e.g. partial "50000",
 * locale comma «50,5»). Backend derives unit_cost = budget / Σ(units).
 *
 * @type {import('svelte/store').Writable<Record<string, number>>}
 */
export const budgetInputs = writable(/** @type {Record<string, number>} */ ({}));

// Sync unitCosts + inflation from activeProject when it loads/changes.
// Audit pass 5 fix (BUG B1): when activeProject is set but doesn't include
// `unit_cost_inflation_pct` field (legacy projects), reset store к {}. Without
// this, switch project A (with inflation) → project B (legacy) leaves store
// with A's inflation values applied к B incorrectly.
activeProject.subscribe((p) => {
  if (!p) {
    unitCosts.set({});
    unitCostInflation.set({});
    unitCostInputMode.set({});
    budgetInputs.set({});
    return;
  }
  if (p.unit_costs && typeof p.unit_costs === 'object') {
    unitCosts.set(/** @type {Record<string, number>} */ (p.unit_costs));
  } else {
    unitCosts.set({});
  }
  if (p.unit_cost_inflation_pct && typeof p.unit_cost_inflation_pct === 'object') {
    unitCostInflation.set(/** @type {Record<string, number>} */ (p.unit_cost_inflation_pct));
  } else {
    unitCostInflation.set({});  // ← always reset when project switches
  }
  // Phase 1.3 (v2.0.1): hydrate UI mode preference + budget input restore.
  // Source: project.json `unit_cost_input_mode` + `budget_inputs` (Phase 1.2
  // extended save_kpi_settings persists в settings/v13_kpi.json - но
  // activeProject loader merges flat). Reset на project switch (avoid leakage).
  if (p.unit_cost_input_mode && typeof p.unit_cost_input_mode === 'object') {
    unitCostInputMode.set(/** @type {Record<string, 'budget' | 'unit'>} */ (p.unit_cost_input_mode));
  } else {
    unitCostInputMode.set({});
  }
  if (p.budget_inputs && typeof p.budget_inputs === 'object') {
    budgetInputs.set(/** @type {Record<string, number>} */ (p.budget_inputs));
  } else {
    budgetInputs.set({});
  }
});

/**
 * Trust Level 3 (v1.1.0): brand vs performance channel categorization.
 * Values: 'brand' / 'performance' / 'mixed'.
 * Auto-suggested by backend /utils/auto_suggest_categories на mount Validate шага.
 * Manual override через ChannelCategoriesPanel popup.
 * Persisted в project.json через project_update (backend применяет orphan cleanup
 * при изменении media_columns).
 * @type {import('svelte/store').Writable<Record<string, 'brand' | 'performance' | 'mixed'>>}
 */
export const channelCategories = writable({});

activeProject.subscribe((p) => {
  if (p && p.channel_categories && typeof p.channel_categories === 'object') {
    channelCategories.set(/** @type {Record<string, 'brand' | 'performance' | 'mixed'>} */ (p.channel_categories));
  } else if (!p) {
    channelCategories.set({});
  }
});

/**
 * Reactive cleanup orphaned channel_categories entries при изменении media_columns
 * на frontend (post-audit fix 2026-04-27): backend project.rs уже cleanup'ит при
 * project_update, но UI store должен sync immediately для consistent badge display.
 * @param {string[]} mediaColumns
 */
export function syncChannelCategoriesToMedia(mediaColumns) {
  const current = get(channelCategories);
  const mediaSet = new Set(mediaColumns);
  /** @type {Record<string, 'brand' | 'performance' | 'mixed'>} */
  const cleaned = {};
  let hadOrphans = false;
  for (const [ch, cat] of Object.entries(current)) {
    if (mediaSet.has(ch)) {
      cleaned[ch] = cat;
    } else {
      hadOrphans = true;
    }
  }
  if (hadOrphans) {
    channelCategories.set(cleaned);
  }
}

/**
 * v2.0.0 (ADR-019): explicit Manager mode choice (supersedes ADR-015 derived state).
 *
 *   'roi'           → all media channels in ₽ (monetary input). Model computes ROI/CPU.
 *   'effectiveness' → all media channels in physical metrics (TRP/impressions/clicks).
 *                     Model computes share-of-contribution percentages.
 *   'mixed'         → per-channel choice (Expert mode only; requires unit_costs).
 *
 * Default = 'roi'. Set explicitly через AnalysisModeSelector.svelte в Manager mode,
 * или через wizard auto-detect migration logic для existing v1.3.x projects.
 *
 * Per INV-30 (MMM single-unit preference) - Manager mode видит только 'roi' / 'effectiveness'.
 * 'mixed' доступен только в Expert mode (см. expertMode store).
 *
 * @type {import('svelte/store').Writable<'roi' | 'effectiveness' | 'mixed'>}
 */
export const analysisMode = writable('roi');

/**
 * @deprecated v2.0.0: backward-compat alias for legacy ValidateStep / InsightsPanel /
 * UnitCostsPanel. Derived from `analysisMode` - 'mixed' maps to 'manual' (старое имя).
 *
 * Legacy code путь:
 *   $analysisObjective === 'roi'           ↔ $analysisMode === 'roi'
 *   $analysisObjective === 'effectiveness' ↔ $analysisMode === 'effectiveness'
 *   $analysisObjective === 'manual'        ↔ $analysisMode === 'mixed'
 *
 * Legacy ValidateStep.svelte (deprecated) writes to analysisObjective -
 * compatibility shim ниже (analysisObjectiveLegacyShim) синхронизирует обратно.
 *
 * Будет удалён в v3.0+ после full deprecation legacy ValidateStep.
 *
 * @type {import('svelte/store').Readable<'roi' | 'effectiveness' | 'manual'>}
 */
export const analysisObjective = derived(
  analysisMode,
  ($mode) => ($mode === 'mixed' ? 'manual' : $mode),
);

/**
 * Compatibility setter shim для legacy code что вызывает `analysisObjective.set(...)`.
 * Маршрутизирует write обратно в `analysisMode`.
 *
 * Usage в legacy code (e.g., ValidateStep.svelte:176):
 *   import { analysisObjectiveLegacyShim as analysisObjective } from '$lib/project-state.js';
 *   analysisObjective.set('effectiveness');
 *
 * @type {any}
 */
export const analysisObjectiveLegacyShim = {
  /** @param {'roi' | 'effectiveness' | 'manual'} value */
  set(value) {
    const mapped = value === 'manual' ? 'mixed' : value;
    analysisMode.set(/** @type {'roi' | 'effectiveness' | 'mixed'} */ (mapped));
  },
  /** @param {(v: 'roi' | 'effectiveness' | 'manual') => 'roi' | 'effectiveness' | 'manual'} updater */
  update(updater) {
    const current = get(analysisMode);
    const legacyCurrent = current === 'mixed' ? 'manual' : current;
    const updated = updater(/** @type {'roi' | 'effectiveness' | 'manual'} */ (legacyCurrent));
    const mapped = updated === 'manual' ? 'mixed' : updated;
    analysisMode.set(/** @type {'roi' | 'effectiveness' | 'mixed'} */ (mapped));
  },
  subscribe: analysisObjective.subscribe,
};

/**
 * v1.3.0: KPI kind selector (per ADR-016).
 * 'monetary' → target в ₽ (sales, revenue, profit). Главная метрика канала ROI.
 * 'count'    → target в штуках (sales_packs, leads, registrations, и т.д.). CPU vs value.
 * @type {import('svelte/store').Writable<'monetary' | 'count'>}
 */
export const kpiKind = writable('monetary');

/**
 * v1.3.0: KPI type (specific). Один из ['sales', 'revenue', 'profit', 'sales_packs',
 * 'leads', 'registrations', 'loyalty_cards', 'subscriptions', 'app_installs', 'count_custom'].
 * @type {import('svelte/store').Writable<string>}
 */
export const kpiType = writable('sales');

/**
 * v1.3.0: per-channel input metric selection (per ADR-015).
 * {channel_name: 'monetary' | 'physical'} - выбор юзера на шаге Валидация.
 * @type {import('svelte/store').Writable<Record<string, 'monetary' | 'physical'>>}
 */
export const perChannelInput = writable({});

/**
 * v1.3.0: derived mode - computed automatically from perChannelInput (ADR-015).
 * Не writable юзером - обновляется когда меняется perChannelInput.
 * @type {import('svelte/store').Writable<'roi' | 'effectiveness' | 'manual'>}
 */
export const derivedMode = writable('roi');

/**
 * v1.3.0: value per count unit (per ADR-016).
 * Для KPI=count хранит ценность одной единицы (₽). UI label per kpiType.
 * @type {import('svelte/store').Writable<number | null>}
 */
export const valuePerCountUnit = writable(null);

/**
 * v1.3.0: source флаг - 'auto' (auto-detected) | 'manual' (user input) | 'imported' (из bundle) | null.
 * @type {import('svelte/store').Writable<string | null>}
 */
export const valuePerCountUnitSource = writable(null);

/**
 * v1.3.0: feature flag для нового derived-mode UX.
 * true → новый KPISelector + PerChannelInputSelector flow.
 * false → старый ObjectiveSelector (v1.2 behavior).
 * Default true для v1.3.0 ship.
 * @type {import('svelte/store').Writable<boolean>}
 */
export const useDerivedModeUX = writable(true);

/**
 * v1.3.0: hide WhyThisStep / inline tooltips / adaptive insights toggle (educational).
 * false (default) → подсказки видны (novice mode).
 * true → скрытие для experts (mastery toggle in Settings).
 * @type {import('svelte/store').Writable<boolean>}
 */
export const hideEducationalHints = writable(false);

/**
 * v1.3.0: показ Intro Tutorial при первом запуске свежей установки.
 * true → tutorial показывается. После завершения / skip → false.
 * Persisted в localStorage as 'aurora-intro-completed'.
 * @type {import('svelte/store').Writable<boolean>}
 */
export const showIntroTutorial = writable(false);

/**
 * v1.3.0: глобальный glossary panel toggle (Ctrl+K).
 * @type {import('svelte/store').Writable<boolean>}
 */
export const showGlossaryPanel = writable(false);

/**
 * v1.0.16: модель-движок selector (Import шаг).
 * 'bayesian' (default, NUTS NumPyro) - полный posterior, CI, ~20-60 сек train.
 * 'ols' (Sprint 2 small-data fallback) - closed-form OLS, frequentist β CI,
 *   ~2-5 сек, для n<30 наблюдений где Bayesian funnel/divergences likely.
 * Auto-recommend: n<30 → OLS, n≥30 → Bayesian. Customer может override.
 * @type {import('svelte/store').Writable<'bayesian' | 'ols'>}
 */
export const modelEngine = writable('bayesian');

/** @type {import('svelte/store').Writable<{diagnostics: any|null, channelParams: any|null, picklePath: string|null, normalization?: {y_mean: number, y_std: number}|null}>} */
export const modelData = writable({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });

/**
 * v2.1.0 (пилот 2026-05-17): snapshot конфигурации на момент последнего
 * обучения. Используется для детекции stale model - если юзер изменил
 * роли колонок / KPI в Валидации после обучения, modelData.diagnostics
 * и pickle всё ещё содержат старые controls, и декомпозиция показывает
 * лишние факторы. Сравнение с current validateData даёт banner
 * «модель устарела».
 *
 * @type {import('svelte/store').Writable<{
 *   kpi: string,
 *   media: string[],
 *   control: string[]
 * } | null>}
 */
// v2.1.0 (пилот 2026-05-17 audit H-2): localStorage persistence чтобы
// stale-banner работал после reload Tauri окна (раньше lastTrainedConfig
// был null после reload → modelStaleStatus всегда stale=false → банера нет).
const LAST_TRAINED_KEY = 'aurora-last-trained-config';
const initialLastTrained = /** @type {{kpi: string, media: string[], control: string[]} | null} */ ((() => {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(LAST_TRAINED_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
})());
export const lastTrainedConfig = writable(initialLastTrained);
if (typeof localStorage !== 'undefined') {
  lastTrainedConfig.subscribe((v) => {
    try {
      if (v == null) localStorage.removeItem(LAST_TRAINED_KEY);
      else localStorage.setItem(LAST_TRAINED_KEY, JSON.stringify(v));
    } catch { /* quota / private mode */ }
  });
}

/**
 * Derived store: проверяет staleness обученной модели.
 * stale = true когда trained config расходится с current validation
 * roles (media / control / kpi). Возвращает причину для banner UI.
 *
 * @type {import('svelte/store').Readable<{
 *   stale: boolean,
 *   reason: string,
 *   diff: string[]
 * }>}
 */
export const modelStaleStatus = derived(
  [modelData, validateData, lastTrainedConfig],
  ([$m, $v, $tc]) => {
    if (!$m?.diagnostics || !$tc) return { stale: false, reason: '', diff: [] };
    const cur = /** @type {any[]} */ ($v?.result?.columns || []);
    const curMedia = cur.filter(c => c?.role === 'media').map(c => c.name).sort();
    const curControl = cur.filter(c => c?.role === 'control').map(c => c.name).sort();
    const curKpi = cur.find(c => c?.role === 'kpi')?.name ?? '';
    const tm = [...($tc.media || [])].sort();
    const tc = [...($tc.control || [])].sort();
    /** @type {string[]} */
    const diff = [];
    if (curKpi !== $tc.kpi) diff.push(`KPI: «${$tc.kpi}» → «${curKpi}»`);
    if (curMedia.length !== tm.length || curMedia.some((x, i) => x !== tm[i])) {
      diff.push(`Медиа-каналы: было ${tm.length}, стало ${curMedia.length}`);
    }
    if (curControl.length !== tc.length || curControl.some((x, i) => x !== tc[i])) {
      diff.push(`Контрольные: было ${tc.length}, стало ${curControl.length}`);
    }
    if (diff.length === 0) return { stale: false, reason: '', diff: [] };
    return {
      stale: true,
      reason: 'Конфигурация изменилась после обучения. Текущие результаты содержат факторы предыдущей версии. Переобучите модель.',
      diff,
    };
  }
);

/** @type {import('svelte/store').Writable<any|null>} */
export const decomposeData = writable(null);

/** @type {import('svelte/store').Writable<any|null>} */
export const optimizeData = writable(null);

/**
 * Восстановить данные pipeline из `results/*.json` при активации проекта.
 *
 * Предыстория: до S9 stepMeta кешируется в localStorage, но сами данные шагов
 * (modelData/decomposeData/optimizeData) - только в памяти. После перезапуска
 * app stepper показывает ✓ (complete из localStorage), а ReportStep видит
 * пустые сторы и кричит «данных нет». Эта функция читает results/*.json
 * через Rust-команду и заполняет сторы - приводит UI в консистентное состояние.
 *
 * Ограничения: channelParams / normalization лежат в pickle (не JSON), поэтому
 * re-train модели требуется для повторной оптимизации. Для Report + Insights
 * хватает diagnostics (из model-diagnostics.json) + decompose + optimize.
 *
 * @param {string | null} pid - project id; при null - ничего не делает.
 */
async function restoreProjectResults(pid) {
  if (!pid) return;
  try {
    const r = /** @type {any} */ (await invoke('project_load_results', { projectId: pid }));
    const hasValidation = Boolean(r.validation);
    const hasModel = Boolean(r.modelDiagnostics);
    const hasDecompose = Boolean(r.decomposition);
    const hasOptimize = Boolean(r.optimization);

    if (hasModel) {
      modelData.update(m => ({
        ...m,
        diagnostics: r.modelDiagnostics,
        normalization: r.modelDiagnostics?.normalization ?? m.normalization,
      }));
    }
    if (hasDecompose) decomposeData.set(r.decomposition);
    if (hasOptimize) optimizeData.set(r.optimization);
    if (hasValidation) {
      validateData.set({
        result: r.validation,
        correlationMatrix: r.validation?.full_correlation_matrix ?? null,
        columnHistograms: null, // histograms не сохраняются отдельно
      });
    }

    // Синхронизировать stepMeta с реальным наличием данных на диске.
    // Иначе остаточный status='error' с прошлых сессий висит на шагах,
    // до которых пользователь ещё не дошёл (например, «Декомпозиция ❌»
    // пока работаешь на «Валидация»).
    reconcileStepMetaFromDisk({ hasValidation, hasModel, hasDecompose, hasOptimize });
  } catch (e) {
    // Silent: отсутствие results/* - норма для нового проекта.
    console.warn('restoreProjectResults skipped:', e);
  }
}

/**
 * Привести stepMeta в соответствие с фактическими результатами на диске.
 * Шаг с данными → complete. Шаг без данных, но с complete-предшественником → ready.
 * Остальные → locked. Все error-статусы, не подкреплённые данными, сбрасываются.
 *
 * @param {{hasValidation: boolean, hasModel: boolean, hasDecompose: boolean, hasOptimize: boolean}} flags
 */
function reconcileStepMetaFromDisk(flags) {
  const { hasValidation, hasModel, hasDecompose, hasOptimize } = flags;
  // Monotonic invariant: если есть данные на любом downstream шаге, все upstream
  // шаги успешно прошли (по построению pipeline). Step 0 (Import) → complete если
  // ЛЮБОЙ из validate/model/decompose/optimize отработал - без этого нельзя было.
  // Это исправляет race condition где reconcile перезаписывал live-set complete
  // на ready при временном отсутствии validation.json.
  const importDone = hasValidation || hasModel || hasDecompose || hasOptimize;
  const stepStatuses = /** @type {StepStatus[]} */ ([
    importDone   ? 'complete' : 'ready',          // 0 - Import
    hasValidation ? 'complete' : (importDone ? 'ready' : 'locked'),    // 1 - Validate
    hasModel     ? 'complete' : (hasValidation ? 'ready' : 'locked'),  // 2 - Model
    hasDecompose ? 'complete' : (hasModel ? 'ready' : 'locked'),       // 3 - Decompose
    hasOptimize  ? 'complete' : (hasDecompose ? 'ready' : 'locked'),   // 4 - Optimize
    (hasDecompose && hasOptimize) ? 'ready' : 'locked',                // 5 - Report
  ]);
  pipelineStepMeta.set(stepStatuses.map(status => ({ status, errorMessage: null })));

  // Persist pristine state в localStorage + поправить currentStep если он указывает
  // на шаг который теперь locked (после сброса error).
  const curStep = get(pipelineCurrentStep);
  const curStatus = stepStatuses[curStep];
  if (curStatus === 'locked') {
    // Откатиться к последнему complete шагу или к ready.
    const lastUsable = stepStatuses.findLastIndex(s => s === 'complete' || s === 'ready');
    if (lastUsable >= 0 && lastUsable !== curStep) {
      pipelineCurrentStep.set(lastUsable);
    }
  }
  savePipelineMeta(get(activeProjectId), {
    currentStep: get(pipelineCurrentStep),
    steps: get(pipelineStepMeta),
  });
}

// Автовосстановление при смене активного проекта (и при cold start после
// восстановления activeProjectId из backend). Выполняется один раз per pid.
let _lastRestoredPid = /** @type {string | null} */ (null);
activeProjectId.subscribe((pid) => {
  if (pid && pid !== _lastRestoredPid) {
    _lastRestoredPid = pid;
    restoreProjectResults(pid);
  } else if (!pid) {
    _lastRestoredPid = null;
  }
});

/**
 * Live-state оптимизатора - положение слайдеров в блоке B до нажатия «Оптимизировать».
 * Нужно InsightsPanel'у для реактивного пересчёта mROAS/saturation на каждое движение.
 * @type {import('svelte/store').Writable<{
 *   channelBudgets: Record<string, number>,
 *   channelMinPct: Record<string, number>,
 *   channelMaxPct: Record<string, number>,
 *   globalMinPct: number,
 *   globalMaxPct: number,
 * }>}
 */
export const optimizeLiveState = writable({
  channelBudgets: {},
  channelMinPct: {},
  channelMaxPct: {},
  globalMinPct: 50,
  globalMaxPct: 150,
});

/** @type {import('svelte/store').Writable<any|null>} */
export const reportData = writable(null);

/**
 * A5: Reset all downstream step data and lock their statuses.
 * Call when an upstream step's input changes (re-import, config change, etc.).
 * All steps with index > fromStep are cleared and locked.
 * @param {number} fromStep - the step that changed; steps fromStep+1..5 are reset
 */
export function resetDownstream(fromStep) {
  if (fromStep < 1) validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
  if (fromStep < 2) modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  if (fromStep < 3) decomposeData.set(null);
  if (fromStep < 4) optimizeData.set(null);
  if (fromStep < 5) reportData.set(null);

  pipelineStepMeta.update(steps =>
    steps.map((s, i) => i <= fromStep ? s : { status: 'locked', errorMessage: null })
  );

  const pid = get(activeProjectId);
  savePipelineMeta(pid, { currentStep: get(pipelineCurrentStep), steps: get(pipelineStepMeta) });
}

/**
 * Mark a step complete and unlock the next step.
 * Does NOT auto-advance - user clicks "Далее" manually to review results.
 * @param {number} step - step index (0-5)
 */
export function completeStep(step) {
  pipelineStepMeta.update(steps => {
    const copy = steps.map(s => ({ ...s }));
    copy[step] = { ...copy[step], status: 'complete', errorMessage: null };
    if (step + 1 < 6) copy[step + 1] = { ...copy[step + 1], status: 'ready' };
    return copy;
  });

  const pid = get(activeProjectId);
  savePipelineMeta(pid, { currentStep: get(pipelineCurrentStep), steps: get(pipelineStepMeta) });
}

/**
 * Mark a step as errored.
 * @param {number} step
 * @param {string|null} [message]
 */
export function setStepError(step, message) {
  pipelineStepMeta.update(steps => {
    const copy = steps.map(s => ({ ...s }));
    if (message) {
      copy[step] = { status: 'error', errorMessage: message };
    } else {
      // Clear error: если статус был 'error', откатываемся к 'ready'.
      // Иначе (complete / ready / locked) оставляем как есть.
      // Иначе вызов setStepError(n, null) из retry-flow ложно устанавливал
      // status='error' с пустым сообщением → залипший "Ошибка" badge без текста.
      if (copy[step].status === 'error') {
        copy[step] = { status: 'ready', errorMessage: null };
      } else {
        copy[step] = { ...copy[step], errorMessage: null };
      }
    }
    return copy;
  });
  const pid = get(activeProjectId);
  savePipelineMeta(pid, { currentStep: get(pipelineCurrentStep), steps: get(pipelineStepMeta) });
}

/**
 * Load pipeline metadata for a project from localStorage.
 * Data stores start empty (A4 - data is never persisted).
 * Call when switching projects.
 * @param {string|null} projectId
 */
export function loadPipelineForProject(projectId) {
  const meta = loadPipelineMeta(projectId);
  pipelineCurrentStep.set(meta.currentStep);
  pipelineStepMeta.set(meta.steps);
  // A4: data stores always reset (never persisted)
  importData.set({ file: null, columns: null, rows: null });
  validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  decomposeData.set(null);
  optimizeData.set(null);
  reportData.set(null);
}

/**
 * Full reset for a fresh analysis - clears active project, wipes all pipeline
 * data, returns user to step 0 with a clean stepper. Used by "Новый анализ"
 * button on the main screen.
 */
export function resetForNewAnalysis() {
  activeProjectId.set(null);
  activeProject.set(null);
  pipelineCurrentStep.set(0);
  pipelineStepMeta.set(defaultStepMeta());
  importData.set({ file: null, columns: null, rows: null });
  validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  decomposeData.set(null);
  optimizeData.set(null);
  reportData.set(null);
  chartImages.set({});
  isComputing.set(false);
  computeStatus.set('');
}

// ===================================================================
// Shared stores (used by both pipeline and cabinet)
// ===================================================================

/** @type {import('svelte/store').Writable<Record<string, string>>} Chart images (base64) by type */
export const chartImages = writable({});

/** @type {import('svelte/store').Writable<boolean>} Sidecar health status */
export const sidecarHealthy = writable(false);

/** @type {import('svelte/store').Writable<string>} Sidecar status message for footer (C5) */
export const sidecarStatus = writable('');

/** @type {import('svelte/store').Writable<boolean>} Is computation running */
export const isComputing = writable(false);

/** @type {import('svelte/store').Writable<string>} Current computation status message */
export const computeStatus = writable('');

/** @type {import('svelte/store').Writable<boolean>} Project completion ceremony active */
export const showCompletion = writable(false);

/** @type {import('svelte/store').Writable<{startTime: number|null, tokensUsed: number, scenarioCount: number}>} */
export const sessionStats = writable({ startTime: null, tokensUsed: 0, scenarioCount: 0 });

/**
 * Trigger completion ceremony (Peak-End Rule: beautiful ending = positive memory).
 * Call after /mmm-export or /executive completes.
 */
export function triggerCompletion() {
  showCompletion.set(true);
  setTimeout(() => showCompletion.set(false), 8000);
}

/**
 * Reset legacy cabinet pipeline state (when switching projects).
 * @param {string|null} [projectId]
 */
export function resetPipeline(projectId) {
  pipelineState.set({
    data: { loaded: false, file: null, columns: null, validation: null },
    model: { trained: false, diagnostics: null, channelParams: null, picklePath: null },
    decomposition: null,
    optimization: null,
    scenarios: [],
    awareness: null,
  });
  chartImages.set({});
  isComputing.set(false);
  computeStatus.set('');
  loadPipelineForProject(projectId ?? null);

  // Если передан projectId - перечитать результаты с диска (validation,
  // modelDiagnostics, decompose, optimize). Без этого: пользователь
  // переключил проект → stores сброшены → ReportStep показывает
  // «данные предыдущих шагов недоступны», хотя они есть в JSON-файлах.
  // Fix для race: _lastRestoredPid в subscribe может блокировать повторный
  // вызов для того же pid. Здесь вызываем явно обходя guard.
  if (projectId) {
    _lastRestoredPid = null;  // сброс guard'а чтобы subscribe позволил
    restoreProjectResults(projectId);
  }
}
