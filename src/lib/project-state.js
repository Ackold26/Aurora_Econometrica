/**
 * Econometrica project state — shared across cabinets.
 * Tracks active project, pipeline progress, model results.
 *
 * @module project-state
 */
import { writable, derived } from 'svelte/store';

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

/** @type {import('svelte/store').Writable<PipelineState>} */
export const pipelineState = writable({
  data: { loaded: false, file: null, columns: null, validation: null },
  model: { trained: false, diagnostics: null, channelParams: null, picklePath: null },
  decomposition: null,
  optimization: null,
  scenarios: [],
  awareness: null,
});

/** Current pipeline step (0-3): 0=no data, 1=data ready, 2=model trained, 3=analyzed */
export const pipelineStep = derived(pipelineState, ($s) => {
  if (!$s.data.loaded) return 0;
  if (!$s.model.trained) return 1;
  if (!$s.decomposition) return 2;
  return 3;
});

/** @type {import('svelte/store').Writable<Record<string, string>>} Chart images (base64) by type */
export const chartImages = writable({});

/** @type {import('svelte/store').Writable<boolean>} Sidecar health status */
export const sidecarHealthy = writable(false);

/** @type {import('svelte/store').Writable<boolean>} Is computation running */
export const isComputing = writable(false);

/** @type {import('svelte/store').Writable<string>} Current computation status message */
export const computeStatus = writable('');

/** @type {import('svelte/store').Writable<boolean>} Project completion ceremony active */
export const showCompletion = writable(false);

/** @type {import('svelte/store').Writable<{startTime: number|null, tokensUsed: number, scenarioCount: number}>} Session stats for completion */
export const sessionStats = writable({ startTime: null, tokensUsed: 0, scenarioCount: 0 });

/**
 * Trigger completion ceremony (Peak-End Rule: beautiful ending = positive memory).
 * Call after /mmm-export or /executive completes.
 */
export function triggerCompletion() {
  showCompletion.set(true);
  // Auto-dismiss after 8 seconds
  setTimeout(() => showCompletion.set(false), 8000);
}

/**
 * Reset pipeline state (when switching projects).
 */
export function resetPipeline() {
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
}
