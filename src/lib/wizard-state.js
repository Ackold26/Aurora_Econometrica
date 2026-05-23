/**
 * Aurora MMM Optimizer v2.0.0 - ScenarioWizard state management.
 *
 * Implements the Wizard State Lifecycle from WIZARD_FLOW_v2_FINAL.md §0.6.
 * State machine: IDLE → WIZARD_PENDING → AUTO_DETECTING →
 *   {ESCAPE | WIZARD_ACTIVE | AUTO_FILLED} → RUNNING → COMPLETED
 *
 * Persistence strategy (§0.6 State persistence table):
 *   - wizardState store     : in-memory, authoritative for active session
 *   - localStorage          : partial state per project, survives abandon/reload
 *   - bundle.json fields    : frozen at RUNNING (Step 6 Run), via Rust backend
 *
 * @module wizard-state
 */

import { writable, derived, get } from 'svelte/store';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * @typedef {'IDLE' | 'WIZARD_PENDING' | 'AUTO_DETECTING' |
 *           'ESCAPE' | 'WIZARD_ACTIVE' | 'AUTO_FILLED' |
 *           'RUNNING' | 'COMPLETED'} WizardLifecycleState
 */

/**
 * @typedef {Object} WizardState
 * @property {WizardLifecycleState} lifecycle
 * @property {number} currentStep                         - 0-6 (0 = pre-step / auto-detect)
 * @property {Record<string, Record<string, any>>} stepData - { step1: {...}, step2: {...}, ... }
 * @property {Record<string, any>} autoDetectResults      - output of auto-detect (WIZARD_FLOW §1.5)
 * @property {Record<string, any>} resolvedFactors        - { F1, F2, F3, F4 }
 * @property {string[]} bestPracticeWarnings
 * @property {string|null} escapeReason                   - 'history_short' | 'launch_like' | 'no_media' | etc.
 */

/**
 * @typedef {Object} InvalidationWarning
 * @property {number} changedStep
 * @property {number[]} invalidatedSteps
 * @property {string} message
 */

// ---------------------------------------------------------------------------
// Allowed lifecycle transitions (per §0.6 state diagram)
// ---------------------------------------------------------------------------

/**
 * Valid (from → to[]) transitions map. Any pair not listed is invalid.
 * @type {Record<WizardLifecycleState, WizardLifecycleState[]>}
 */
const ALLOWED_TRANSITIONS = {
  IDLE:           ['WIZARD_PENDING'],
  WIZARD_PENDING: ['AUTO_DETECTING'],
  AUTO_DETECTING: ['ESCAPE', 'WIZARD_ACTIVE', 'AUTO_FILLED'],
  ESCAPE:         [],
  WIZARD_ACTIVE:  ['RUNNING'],
  AUTO_FILLED:    ['RUNNING'],
  RUNNING:        ['COMPLETED'],
  COMPLETED:      ['WIZARD_ACTIVE'],  // re-edit: reopen wizard in ACTIVE from Step 1
};

// ---------------------------------------------------------------------------
// Back-navigation invalidation rules (per §0.6)
// ---------------------------------------------------------------------------

/**
 * Steps that must be invalidated when a given step changes during back-navigation.
 * Key = step that changed. Value = steps to invalidate.
 * @type {Record<number, number[]>}
 *
 * @example
 * // Step 1 change → invalidate steps 4, 5, 6
 * INVALIDATION_MAP[1] // → [4, 5, 6]
 */
const INVALIDATION_MAP = {
  1: [4, 5, 6],
  2: [3, 4, 5, 6],
  3: [4, 6],
  4: [6],
  5: [6],
  6: [],
};

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const LS_PREFIX = 'aurora-wizard-state-v2-';

/**
 * @param {string} projectId
 * @returns {string}
 */
function lsKey(projectId) {
  return `${LS_PREFIX}${projectId}`;
}

/**
 * Fields of WizardState that are safe to persist (exclude large autoDetectResults).
 * Per §0.6: localStorage stores partial state for resume - not full detect results.
 * @type {string[]}
 */
const PERSIST_FIELDS = ['lifecycle', 'currentStep', 'stepData', 'resolvedFactors', 'bestPracticeWarnings', 'escapeReason'];

// ---------------------------------------------------------------------------
// Default / factory
// ---------------------------------------------------------------------------

/**
 * @returns {WizardState}
 */
function defaultWizardState() {
  return {
    lifecycle: 'IDLE',
    currentStep: 0,
    /** @type {Record<string, Record<string, any>>} */
    stepData: {},
    /** @type {Record<string, any>} */
    autoDetectResults: {},
    /** @type {Record<string, any>} */
    resolvedFactors: { F1: null, F2: null, F3: null, F4: null },
    bestPracticeWarnings: [],
    escapeReason: null,
  };
}

// ---------------------------------------------------------------------------
// Core store
// ---------------------------------------------------------------------------

/**
 * Main wizard state store. All wizard logic reads/writes through this.
 * @type {import('svelte/store').Writable<WizardState>}
 */
export const wizardState = writable(defaultWizardState());

// ---------------------------------------------------------------------------
// Derived stores
// ---------------------------------------------------------------------------

/**
 * Current wizard step (0-6). Derived from wizardState.currentStep.
 * @type {import('svelte/store').Readable<number>}
 */
export const currentStep = derived(wizardState, ($ws) => $ws.currentStep);

/**
 * True when wizard is actively shown (WIZARD_ACTIVE or AUTO_FILLED states).
 * RUNNING/COMPLETED are read-only (frozen) - not "active" for interaction.
 * @type {import('svelte/store').Readable<boolean>}
 */
export const isWizardActive = derived(
  wizardState,
  ($ws) => $ws.lifecycle === 'WIZARD_ACTIVE' || $ws.lifecycle === 'AUTO_FILLED',
);

/**
 * True when wizard is in a terminal read-only state (RUNNING or COMPLETED).
 * @type {import('svelte/store').Readable<boolean>}
 */
export const isWizardFrozen = derived(
  wizardState,
  ($ws) => $ws.lifecycle === 'RUNNING' || $ws.lifecycle === 'COMPLETED',
);

/**
 * True if wizard has escaped to Expert mode.
 * @type {import('svelte/store').Readable<boolean>}
 */
export const isWizardEscaped = derived(
  wizardState,
  ($ws) => $ws.lifecycle === 'ESCAPE',
);

/**
 * Resolved factors for downstream components.
 * @type {import('svelte/store').Readable<Object>}
 */
export const resolvedFactors = derived(wizardState, ($ws) => $ws.resolvedFactors);

// ---------------------------------------------------------------------------
// State machine transition
// ---------------------------------------------------------------------------

/**
 * Transition wizard to a new lifecycle state.
 * Validates allowed transitions per §0.6 state diagram.
 * Invalid transitions: logs warning and ignores (does not throw) to avoid crashing UI.
 *
 * @param {WizardLifecycleState} newState
 * @param {Partial<WizardState>} [patch] - optional additional fields to set atomically
 * @returns {boolean} true if transition was applied, false if rejected
 *
 * @example
 * transitionTo('WIZARD_PENDING');
 * transitionTo('AUTO_DETECTING');
 * transitionTo('ESCAPE', { escapeReason: 'history_short' });
 */
export function transitionTo(newState, patch = {}) {
  const current = get(wizardState);
  const allowed = ALLOWED_TRANSITIONS[current.lifecycle] ?? [];

  if (!allowed.includes(newState)) {
    console.warn(
      `[WizardState] Invalid transition: ${current.lifecycle} → ${newState}. ` +
      `Allowed from ${current.lifecycle}: [${allowed.join(', ') || 'none'}]. Ignored.`
    );
    return false;
  }

  wizardState.update((ws) => ({
    ...ws,
    ...patch,
    lifecycle: newState,
  }));

  return true;
}

// ---------------------------------------------------------------------------
// Step navigation
// ---------------------------------------------------------------------------

/**
 * Compute which steps would be invalidated by a change at changedStep.
 * Returns empty array if no invalidation needed.
 *
 * @param {number} changedStep
 * @param {Record<string, Record<string, any>>} currentStepData - current stepData to check if steps actually have data
 * @returns {number[]}
 */
function computeInvalidatedSteps(changedStep, currentStepData) {
  const potentiallyInvalidated = INVALIDATION_MAP[changedStep] ?? [];
  // Only include steps that actually have data (no point warning about empty steps).
  return potentiallyInvalidated.filter(
    (s) => currentStepData[`step${s}`] && Object.keys(currentStepData[`step${s}`]).length > 0
  );
}

/**
 * Advance to the next wizard step.
 * Saves current step data before advancing.
 * Frozen wizard (RUNNING/COMPLETED) - ignores with warning.
 *
 * @param {Record<string, any>} [stepDataForCurrentStep] - data to save for the current step
 * @returns {void}
 *
 * @example
 * nextStep({ taskIntent: 'budget_optimization' });
 */
export function nextStep(stepDataForCurrentStep = {}) {
  const ws = get(wizardState);

  if (ws.lifecycle === 'RUNNING' || ws.lifecycle === 'COMPLETED') {
    console.warn('[WizardState] nextStep() ignored - wizard is frozen in state:', ws.lifecycle);
    return;
  }

  wizardState.update((state) => {
    const newCurrentStep = Math.min(state.currentStep + 1, 6);
    const stepKey = `step${state.currentStep}`;
    return {
      ...state,
      currentStep: newCurrentStep,
      stepData: {
        ...state.stepData,
        ...(Object.keys(stepDataForCurrentStep).length > 0 ? { [stepKey]: stepDataForCurrentStep } : {}),
      },
    };
  });
}

/**
 * Navigate back to the previous wizard step.
 * Per §0.6 back-navigation invalidation rules:
 * if changing a higher-priority step would invalidate downstream steps,
 * this function returns an InvalidationWarning that the UI should display
 * before committing the navigation (call confirmPrevStep to actually go back).
 *
 * If there is no invalidation risk, navigation happens immediately.
 *
 * @returns {InvalidationWarning | null} non-null if UI must show confirmation dialog
 *
 * @example
 * const warning = prevStep();
 * if (warning) {
 *   // Show dialog: warning.message
 *   // On confirm: confirmPrevStep()
 * }
 */
export function prevStep() {
  const ws = get(wizardState);

  if (ws.lifecycle === 'RUNNING' || ws.lifecycle === 'COMPLETED') {
    console.warn('[WizardState] prevStep() ignored - wizard is frozen.');
    return null;
  }

  if (ws.currentStep <= 1) {
    // Already at first step (step 1 = task intent, step 0 = auto-detect pre-step).
    console.warn('[WizardState] prevStep() at first step, cannot go further back.');
    return null;
  }

  const targetStep = ws.currentStep - 1;
  const invalidated = computeInvalidatedSteps(targetStep, ws.stepData);

  if (invalidated.length > 0) {
    // Return warning - caller must show dialog and call confirmPrevStep() on confirm.
    const stepNames = invalidated.map((s) => `Step ${s}`).join(', ');
    return {
      changedStep: targetStep,
      invalidatedSteps: invalidated,
      message: `Изменение этого шага потребует пересмотреть ${stepNames}. Продолжить?`,
    };
  }

  // No invalidation - navigate immediately.
  wizardState.update((state) => ({ ...state, currentStep: targetStep }));
  return null;
}

/**
 * Confirm back navigation after user accepted the invalidation warning.
 * Clears stepData for invalidated steps and goes back.
 *
 * @param {InvalidationWarning} warning - the warning returned by prevStep()
 * @returns {void}
 */
export function confirmPrevStep(warning) {
  wizardState.update((state) => {
    const newStepData = { ...state.stepData };
    for (const s of warning.invalidatedSteps) {
      delete newStepData[`step${s}`];
    }
    return {
      ...state,
      currentStep: warning.changedStep,
      stepData: newStepData,
    };
  });
}

// ---------------------------------------------------------------------------
// Downstream invalidation (explicit)
// ---------------------------------------------------------------------------

/**
 * Clear stepData for all steps with index > fromStep.
 * Called when a step's data changes and downstream steps are no longer valid.
 * Does NOT change currentStep.
 *
 * @param {number} fromStep - steps fromStep+1 .. 6 will be cleared
 * @returns {void}
 *
 * @example
 * // User changed Step 2 data - invalidate steps 3, 4, 5, 6
 * invalidateDownstream(2);
 */
export function invalidateDownstream(fromStep) {
  wizardState.update((state) => {
    const newStepData = { ...state.stepData };
    for (let s = fromStep + 1; s <= 6; s++) {
      delete newStepData[`step${s}`];
    }
    return { ...state, stepData: newStepData };
  });
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

/**
 * Reset wizard to IDLE state. Clears all step data and auto-detect results.
 * Call when: data re-import (§0.6 edge case), new project, or user explicitly resets.
 *
 * @returns {void}
 *
 * @example
 * resetWizard();
 */
export function resetWizard() {
  wizardState.set(defaultWizardState());
}

// ---------------------------------------------------------------------------
// Auto-detect results integration
// ---------------------------------------------------------------------------

/**
 * Apply auto-detect results to wizard state (§1.5 output structure).
 * Determines which lifecycle state to transition to based on resolve confidence.
 *
 * Transition logic per §0.6:
 *   - All F1+F2+F3 resolved (confidence ≥ 0.95 each) AND quality gates pass → AUTO_FILLED
 *   - Quality gate fail → ESCAPE
 *   - Otherwise → WIZARD_ACTIVE
 *
 * @param {{
 *   resolved_factors?: Record<string, any>,
 *   best_practice_warnings?: Array<{recommendation?: string, [key: string]: any}>,
 *   data_signature?: {
 *     quality_gates?: Record<string, string>,
 *     channels?: Array<{confidence: number, [key: string]: any}>,
 *     target_candidates?: Array<{confidence: number, [key: string]: any}>,
 *     [key: string]: any
 *   },
 *   [key: string]: any
 * }} detectResults - full auto-detect output (§1.5 schema)
 * @returns {WizardLifecycleState} the state transitioned to
 */
export function applyAutoDetectResults(detectResults) {
  const { resolved_factors, best_practice_warnings, data_signature } = detectResults;

  // Check quality gate failures → ESCAPE
  const qualityGates = data_signature?.quality_gates ?? {};
  const hasBlock = Object.values(qualityGates).some(
    (v) => typeof v === 'string' && v.startsWith('fail')
  );

  if (hasBlock) {
    const escapeReason = qualityGates.history_minimum?.startsWith('fail')
      ? 'history_short'
      : qualityGates.active_advertising?.startsWith('fail')
        ? 'launch_like'
        : 'quality_gate_fail';

    transitionTo('ESCAPE', {
      autoDetectResults: detectResults,
      resolvedFactors: resolved_factors ?? { F1: null, F2: null, F3: null, F4: null },
      bestPracticeWarnings: best_practice_warnings?.map((w) => w.recommendation ?? '') ?? [],
      escapeReason,
    });
    return 'ESCAPE';
  }

  // Check if all 3 auto-resolvable factors are confident (F4 always needs wizard)
  const CONFIDENCE_THRESHOLD = 0.95;
  const channels = data_signature?.channels ?? [];
  const targetCandidates = data_signature?.target_candidates ?? [];

  const f1Resolved = resolved_factors?.F1_activity != null;
  const f2Confident =
    targetCandidates.length > 0 &&
    targetCandidates[0]?.confidence >= CONFIDENCE_THRESHOLD &&
    targetCandidates.length === 1; // unambiguous
  const f3Confident =
    channels.length > 0 &&
    channels.every((ch) => ch.confidence >= CONFIDENCE_THRESHOLD);

  const allFactorsResolved = f1Resolved && f2Confident && f3Confident;

  if (allFactorsResolved) {
    transitionTo('AUTO_FILLED', {
      autoDetectResults: detectResults,
      resolvedFactors: {
        F1: resolved_factors?.F1_activity,
        F2: resolved_factors?.F2_output,
        F3: resolved_factors?.F3_media_input,
        F4: null, // always requires wizard question
      },
      bestPracticeWarnings: best_practice_warnings?.map((w) => w.recommendation ?? '') ?? [],
      currentStep: 6, // skip straight to Step 6 summary + Run
    });
    return 'AUTO_FILLED';
  }

  // Partial resolution - show wizard steps
  transitionTo('WIZARD_ACTIVE', {
    autoDetectResults: detectResults,
    resolvedFactors: {
      F1: resolved_factors?.F1_activity,
      F2: f2Confident ? resolved_factors?.F2_output : null,
      F3: f3Confident ? resolved_factors?.F3_media_input : null,
      F4: null,
    },
    bestPracticeWarnings: best_practice_warnings?.map((w) => w.recommendation ?? '') ?? [],
    currentStep: 1, // Start at Step 1 (task intent)
  });
  return 'WIZARD_ACTIVE';
}

// ---------------------------------------------------------------------------
// localStorage persistence
// ---------------------------------------------------------------------------

/**
 * Persist partial wizard state to localStorage for resume on project re-open.
 * Per §0.6: saved on every step submit. Large fields (autoDetectResults) are excluded.
 *
 * @param {string} projectId
 * @returns {void}
 *
 * @example
 * persistToLocalStorage('proj-abc123');
 */
export function persistToLocalStorage(projectId) {
  if (!projectId) return;
  try {
    const ws = get(wizardState);
    /** @type {Partial<WizardState>} */
    const partial = {};
    for (const field of PERSIST_FIELDS) {
      // @ts-ignore - iterating known keys
      partial[field] = ws[field];
    }
    const key = lsKey(projectId);
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(key, JSON.stringify(partial));
    }
  } catch (e) {
    console.warn('[WizardState] persistToLocalStorage failed:', e);
  }
}

/**
 * Load wizard partial state from localStorage (project-scoped key).
 * Merges with defaultWizardState() - missing fields use defaults.
 * Resets autoDetectResults (not persisted - too large, re-run on reload).
 *
 * @param {string} projectId
 * @returns {boolean} true if a saved state was found and restored
 *
 * @example
 * const restored = loadFromLocalStorage('proj-abc123');
 * if (restored) { ... }
 */
export function loadFromLocalStorage(projectId) {
  if (!projectId) return false;
  try {
    const key = lsKey(projectId);
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
    if (!raw) return false;

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return false;

    // Validate lifecycle field to reject corrupted storage
    const lifecycle = /** @type {WizardLifecycleState} */ (parsed.lifecycle);
    const validLifecycles = Object.keys(ALLOWED_TRANSITIONS);
    if (!validLifecycles.includes(lifecycle)) {
      console.warn('[WizardState] Invalid lifecycle in localStorage, clearing:', lifecycle);
      clearLocalStorage(projectId);
      return false;
    }

    wizardState.update((current) => ({
      ...current,
      ...parsed,
      // autoDetectResults never persisted - always reset on reload
      autoDetectResults: {},
      // Ensure resolvedFactors has all 4 keys even from older persisted state
      resolvedFactors: {
        F1: null, F2: null, F3: null, F4: null,
        ...(parsed.resolvedFactors ?? {}),
      },
    }));

    return true;
  } catch (e) {
    console.warn('[WizardState] loadFromLocalStorage failed:', e);
    return false;
  }
}

/**
 * Clear persisted wizard state for a project.
 * Call after training completes (state frozen in bundle) or project deleted.
 *
 * @param {string} projectId
 * @returns {void}
 */
export function clearLocalStorage(projectId) {
  if (!projectId) return;
  try {
    const key = lsKey(projectId);
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(key);
    }
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Save step data helper
// ---------------------------------------------------------------------------

/**
 * Save data for a specific wizard step. Used by step components on submit.
 * Also persists to localStorage if projectId is provided.
 *
 * @param {number} step - step number (1-6)
 * @param {Record<string, any>} data - step-specific data to save
 * @param {string} [projectId] - if provided, also persist to localStorage
 * @returns {void}
 *
 * @example
 * saveStepData(1, { taskIntent: 'budget_optimization' }, projectId);
 */
export function saveStepData(step, data, projectId) {
  wizardState.update((state) => ({
    ...state,
    stepData: {
      ...state.stepData,
      [`step${step}`]: data,
    },
  }));
  if (projectId) persistToLocalStorage(projectId);
}

/**
 * Get saved data for a specific wizard step.
 *
 * @param {number} step
 * @returns {Record<string, any>|null}
 */
export function getStepData(step) {
  const ws = get(wizardState);
  return ws.stepData[`step${step}`] ?? null;
}
