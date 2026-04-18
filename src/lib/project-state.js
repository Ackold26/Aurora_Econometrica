/**
 * Econometrica project state — shared across cabinets and pipeline.
 * Phase 1: Extended to 6-step pipeline state machine.
 *
 * A4: localStorage persists only metadata (step statuses, currentStep).
 *     Step data lives exclusively in memory stores.
 * A5: resetDownstream() cascades locked status to all downstream steps.
 *
 * @module project-state
 */
import { writable, derived, get } from 'svelte/store';

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
  } catch { /* corrupted — use default */ }
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
 * Expert mode toggle — persisted in localStorage.
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

/** @type {import('svelte/store').Writable<StepMeta[]>} Step metadata (statuses only, no data) */
export const pipelineStepMeta = writable(defaultStepMeta());

// --- A4: In-memory data stores — never persisted to localStorage ---

/** @type {import('svelte/store').Writable<{file: string|null, columns: any[]|null, rows: any[]|null}>} */
export const importData = writable({ file: null, columns: null, rows: null });

/** @type {import('svelte/store').Writable<{result: any|null, correlationMatrix: any|null, columnHistograms: any|null}>} */
export const validateData = writable({ result: null, correlationMatrix: null, columnHistograms: null });

/**
 * Analysis objective — determines which metric to prefer for paired channels.
 *   'roi'           → keep budgets (measure monetary return)
 *   'effectiveness' → keep natural metrics (impressions/clicks/visits)
 *   'manual'        → user chooses per-channel (current behavior)
 * @type {import('svelte/store').Writable<'roi' | 'effectiveness' | 'manual'>}
 */
export const analysisObjective = writable('roi');

/** @type {import('svelte/store').Writable<{diagnostics: any|null, channelParams: any|null, picklePath: string|null}>} */
export const modelData = writable({ diagnostics: null, channelParams: null, picklePath: null });

/** @type {import('svelte/store').Writable<any|null>} */
export const decomposeData = writable(null);

/** @type {import('svelte/store').Writable<any|null>} */
export const optimizeData = writable(null);

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
  if (fromStep < 2) modelData.set({ diagnostics: null, channelParams: null, picklePath: null });
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
 * Does NOT auto-advance — user clicks "Далее" manually to review results.
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
 * @param {string} [message]
 */
export function setStepError(step, message) {
  pipelineStepMeta.update(steps => {
    const copy = steps.map(s => ({ ...s }));
    copy[step] = { status: 'error', errorMessage: message ?? null };
    return copy;
  });
  const pid = get(activeProjectId);
  savePipelineMeta(pid, { currentStep: get(pipelineCurrentStep), steps: get(pipelineStepMeta) });
}

/**
 * Load pipeline metadata for a project from localStorage.
 * Data stores start empty (A4 — data is never persisted).
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
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null });
  decomposeData.set(null);
  optimizeData.set(null);
  reportData.set(null);
}

/**
 * Full reset for a fresh analysis — clears active project, wipes all pipeline
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
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null });
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
}
