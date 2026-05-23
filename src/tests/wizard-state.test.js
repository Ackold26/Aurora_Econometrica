/**
 * wizard-state.js unit tests - v2.0.0 state machine + lifecycle.
 *
 * Coverage:
 *   - Initial state defaults
 *   - transitionTo: valid + invalid transitions
 *   - nextStep / prevStep / confirmPrevStep navigation
 *   - resetWizard
 *   - persistToLocalStorage / loadFromLocalStorage round-trip
 *   - applyAutoDetectResults: ESCAPE / WIZARD_ACTIVE / AUTO_FILLED branches
 *   - saveStepData / getStepData helpers
 *   - invalidateDownstream
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import {
  wizardState,
  currentStep,
  isWizardActive,
  isWizardFrozen,
  isWizardEscaped,
  transitionTo,
  nextStep,
  prevStep,
  confirmPrevStep,
  resetWizard,
  applyAutoDetectResults,
  persistToLocalStorage,
  loadFromLocalStorage,
  clearLocalStorage,
  saveStepData,
  getStepData,
  invalidateDownstream,
} from '../lib/wizard-state.js';


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getState() {
  return get(wizardState);
}

/**
 * Bring wizard to WIZARD_ACTIVE at the given step quickly.
 * @param {number} step
 */
function activateAtStep(step) {
  resetWizard();
  // IDLE → WIZARD_PENDING → AUTO_DETECTING → WIZARD_ACTIVE
  transitionTo('WIZARD_PENDING');
  transitionTo('AUTO_DETECTING');
  transitionTo('WIZARD_ACTIVE', { currentStep: step });
}

// ---------------------------------------------------------------------------
// Reset before each test to avoid state bleed
// ---------------------------------------------------------------------------
beforeEach(() => {
  resetWizard();
  localStorage.clear();
});


// ---------------------------------------------------------------------------
// Suite 1: Initial state
// ---------------------------------------------------------------------------
describe('Initial state', () => {
  it('lifecycle is IDLE after reset', () => {
    expect(getState().lifecycle).toBe('IDLE');
  });

  it('currentStep is 0 after reset', () => {
    expect(getState().currentStep).toBe(0);
  });

  it('isWizardActive is false initially', () => {
    expect(get(isWizardActive)).toBe(false);
  });

  it('isWizardFrozen is false initially', () => {
    expect(get(isWizardFrozen)).toBe(false);
  });

  it('isWizardEscaped is false initially', () => {
    expect(get(isWizardEscaped)).toBe(false);
  });

  it('stepData is empty object initially', () => {
    expect(getState().stepData).toEqual({});
  });

  it('resolvedFactors all null initially', () => {
    const rf = getState().resolvedFactors;
    expect(rf.F1).toBeNull();
    expect(rf.F2).toBeNull();
    expect(rf.F3).toBeNull();
    expect(rf.F4).toBeNull();
  });

  it('escapeReason is null initially', () => {
    expect(getState().escapeReason).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// Suite 2: transitionTo
// ---------------------------------------------------------------------------
describe('transitionTo', () => {
  it('IDLE → WIZARD_PENDING succeeds, returns true', () => {
    const result = transitionTo('WIZARD_PENDING');
    expect(result).toBe(true);
    expect(getState().lifecycle).toBe('WIZARD_PENDING');
  });

  it('WIZARD_PENDING → AUTO_DETECTING succeeds', () => {
    transitionTo('WIZARD_PENDING');
    const result = transitionTo('AUTO_DETECTING');
    expect(result).toBe(true);
    expect(getState().lifecycle).toBe('AUTO_DETECTING');
  });

  it('AUTO_DETECTING → ESCAPE succeeds', () => {
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    const result = transitionTo('ESCAPE', { escapeReason: 'history_short' });
    expect(result).toBe(true);
    expect(getState().lifecycle).toBe('ESCAPE');
    expect(getState().escapeReason).toBe('history_short');
  });

  it('AUTO_DETECTING → WIZARD_ACTIVE succeeds', () => {
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    const result = transitionTo('WIZARD_ACTIVE');
    expect(result).toBe(true);
    expect(get(isWizardActive)).toBe(true);
  });

  it('AUTO_DETECTING → AUTO_FILLED succeeds, isWizardActive is true', () => {
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('AUTO_FILLED');
    expect(getState().lifecycle).toBe('AUTO_FILLED');
    expect(get(isWizardActive)).toBe(true);
  });

  it('invalid transition RUNNING → WIZARD_ACTIVE is rejected + returns false', () => {
    // Bring to RUNNING via valid path
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('WIZARD_ACTIVE');
    transitionTo('RUNNING');
    const result = transitionTo('WIZARD_ACTIVE');
    expect(result).toBe(false);
    expect(getState().lifecycle).toBe('RUNNING');
  });

  it('invalid transition IDLE → ESCAPE is rejected', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const result = transitionTo('ESCAPE');
    expect(result).toBe(false);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('patch fields applied atomically on valid transition', () => {
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('WIZARD_ACTIVE', { currentStep: 3 });
    const s = getState();
    expect(s.lifecycle).toBe('WIZARD_ACTIVE');
    expect(s.currentStep).toBe(3);
  });
});


// ---------------------------------------------------------------------------
// Suite 3: nextStep
// ---------------------------------------------------------------------------
describe('nextStep', () => {
  it('advances currentStep by 1', () => {
    activateAtStep(1);
    nextStep();
    expect(getState().currentStep).toBe(2);
  });

  it('saves stepData for current step', () => {
    activateAtStep(1);
    nextStep({ taskIntent: 'budget_optimization' });
    expect(getState().stepData.step1).toEqual({ taskIntent: 'budget_optimization' });
  });

  it('does not advance beyond step 6', () => {
    activateAtStep(6);
    nextStep();
    expect(getState().currentStep).toBe(6);
  });

  it('does not advance when RUNNING (frozen)', () => {
    activateAtStep(2);
    transitionTo('RUNNING');
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    nextStep();
    expect(getState().currentStep).toBe(2);
    warnSpy.mockRestore();
  });

  it('does not advance when COMPLETED (frozen)', () => {
    activateAtStep(6);
    transitionTo('RUNNING');
    transitionTo('COMPLETED');
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    nextStep();
    expect(getState().currentStep).toBe(6);
    warnSpy.mockRestore();
  });
});


// ---------------------------------------------------------------------------
// Suite 4: prevStep
// ---------------------------------------------------------------------------
describe('prevStep', () => {
  it('returns null and logs warning at step 1 (cannot go further back)', () => {
    activateAtStep(1);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const result = prevStep();
    expect(result).toBeNull();
    expect(getState().currentStep).toBe(1);
    warnSpy.mockRestore();
  });

  it('returns null when COMPLETED (frozen)', () => {
    activateAtStep(4);
    transitionTo('RUNNING');
    transitionTo('COMPLETED');
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const result = prevStep();
    expect(result).toBeNull();
    warnSpy.mockRestore();
  });

  it('navigates back immediately when no invalidation', () => {
    activateAtStep(3);
    // No stepData filled for downstream steps
    const result = prevStep();
    expect(result).toBeNull();
    expect(getState().currentStep).toBe(2);
  });

  it('returns InvalidationWarning when downstream steps have data', () => {
    activateAtStep(4);
    // Seed downstream step data to trigger invalidation
    saveStepData(4, { budget: 1000000 });
    saveStepData(6, { summary: true });
    // Now go from step 4 → step 3: should warn about step 4, 6
    // Actually at step 4, prevStep targets step 3; INVALIDATION_MAP[3] = [4,6]
    const warning = prevStep();
    expect(warning).not.toBeNull();
    expect(warning?.changedStep).toBe(3);
    expect(warning?.invalidatedSteps.length).toBeGreaterThan(0);
    expect(typeof warning?.message).toBe('string');
  });
});


// ---------------------------------------------------------------------------
// Suite 5: confirmPrevStep
// ---------------------------------------------------------------------------
describe('confirmPrevStep', () => {
  it('clears invalidated step data and goes to changedStep', () => {
    activateAtStep(4);
    saveStepData(4, { budget: 500000 });
    saveStepData(6, { summary: 'done' });
    // Manually build warning as prevStep would return
    const warning = { changedStep: 3, invalidatedSteps: [4, 6], message: 'Продолжить?' };
    confirmPrevStep(warning);
    const state = getState();
    expect(state.currentStep).toBe(3);
    expect(state.stepData.step4).toBeUndefined();
    expect(state.stepData.step6).toBeUndefined();
  });

  it('preserves unaffected step data', () => {
    activateAtStep(4);
    saveStepData(1, { taskIntent: 'decompose' });
    saveStepData(4, { budget: 100 });
    const warning = { changedStep: 3, invalidatedSteps: [4], message: 'msg' };
    confirmPrevStep(warning);
    expect(getState().stepData.step1).toEqual({ taskIntent: 'decompose' });
  });
});


// ---------------------------------------------------------------------------
// Suite 6: resetWizard
// ---------------------------------------------------------------------------
describe('resetWizard', () => {
  it('resets lifecycle to IDLE', () => {
    activateAtStep(3);
    resetWizard();
    expect(getState().lifecycle).toBe('IDLE');
  });

  it('clears stepData', () => {
    activateAtStep(2);
    saveStepData(1, { x: 1 });
    resetWizard();
    expect(getState().stepData).toEqual({});
  });

  it('resets currentStep to 0', () => {
    activateAtStep(5);
    resetWizard();
    expect(getState().currentStep).toBe(0);
  });

  it('clears escapeReason', () => {
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
    transitionTo('ESCAPE', { escapeReason: 'launch_like' });
    resetWizard();
    expect(getState().escapeReason).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// Suite 7: localStorage round-trip
// ---------------------------------------------------------------------------
describe('persistToLocalStorage / loadFromLocalStorage', () => {
  it('persists and restores lifecycle + currentStep', () => {
    activateAtStep(3);
    persistToLocalStorage('proj-test-001');
    resetWizard();
    const restored = loadFromLocalStorage('proj-test-001');
    expect(restored).toBe(true);
    expect(getState().lifecycle).toBe('WIZARD_ACTIVE');
    expect(getState().currentStep).toBe(3);
  });

  it('does not persist autoDetectResults (large field excluded)', () => {
    activateAtStep(2);
    wizardState.update(s => ({ ...s, autoDetectResults: { big: true } }));
    persistToLocalStorage('proj-test-002');
    resetWizard();
    loadFromLocalStorage('proj-test-002');
    expect(getState().autoDetectResults).toEqual({});
  });

  it('returns false when no saved state', () => {
    const result = loadFromLocalStorage('no-such-project');
    expect(result).toBe(false);
  });

  it('clears invalid lifecycle entry on load', () => {
    localStorage.setItem('aurora-wizard-state-v2-proj-bad', JSON.stringify({ lifecycle: 'INVALID_STATE', currentStep: 1 }));
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const result = loadFromLocalStorage('proj-bad');
    expect(result).toBe(false);
    warnSpy.mockRestore();
  });

  it('clearLocalStorage removes the key', () => {
    activateAtStep(1);
    persistToLocalStorage('proj-del');
    clearLocalStorage('proj-del');
    const result = loadFromLocalStorage('proj-del');
    expect(result).toBe(false);
  });

  it('persists and restores bestPracticeWarnings', () => {
    activateAtStep(2);
    wizardState.update(s => ({ ...s, bestPracticeWarnings: ['warn-A', 'warn-B'] }));
    persistToLocalStorage('proj-warn');
    resetWizard();
    loadFromLocalStorage('proj-warn');
    expect(getState().bestPracticeWarnings).toEqual(['warn-A', 'warn-B']);
  });
});


// ---------------------------------------------------------------------------
// Suite 8: applyAutoDetectResults
// ---------------------------------------------------------------------------
describe('applyAutoDetectResults', () => {
  beforeEach(() => {
    resetWizard();
    // Must be in AUTO_DETECTING to allow further transitions
    transitionTo('WIZARD_PENDING');
    transitionTo('AUTO_DETECTING');
  });

  it('transitions to ESCAPE when quality gate fails (history_minimum)', () => {
    const result = applyAutoDetectResults({
      data_signature: { quality_gates: { history_minimum: 'fail:only_12_months' } },
    });
    expect(result).toBe('ESCAPE');
    expect(getState().lifecycle).toBe('ESCAPE');
    expect(getState().escapeReason).toBe('history_short');
  });

  it('transitions to ESCAPE when active_advertising gate fails', () => {
    const result = applyAutoDetectResults({
      data_signature: { quality_gates: { active_advertising: 'fail:below_50pct' } },
    });
    expect(result).toBe('ESCAPE');
    expect(getState().escapeReason).toBe('launch_like');
  });

  it('transitions to AUTO_FILLED when all factors confident + no quality gate fail', () => {
    const result = applyAutoDetectResults({
      resolved_factors: { F1_activity: 'weekly', F2_output: 'sales', F3_media_input: {} },
      data_signature: {
        quality_gates: {},
        target_candidates: [{ column: 'sales', confidence: 0.97 }],
        channels: [
          { name: 'TV', confidence: 0.98 },
          { name: 'Digital', confidence: 0.96 },
        ],
      },
    });
    expect(result).toBe('AUTO_FILLED');
    expect(getState().lifecycle).toBe('AUTO_FILLED');
  });

  it('transitions to WIZARD_ACTIVE when partial confidence', () => {
    const result = applyAutoDetectResults({
      resolved_factors: { F1_activity: 'monthly', F2_output: null, F3_media_input: null },
      data_signature: {
        quality_gates: {},
        target_candidates: [],
        channels: [],
      },
    });
    expect(result).toBe('WIZARD_ACTIVE');
    expect(getState().lifecycle).toBe('WIZARD_ACTIVE');
    expect(getState().currentStep).toBe(1);
  });

  it('AUTO_FILLED sets currentStep to 6 (skip straight to summary)', () => {
    applyAutoDetectResults({
      resolved_factors: { F1_activity: 'weekly', F2_output: 'sales', F3_media_input: {} },
      data_signature: {
        quality_gates: {},
        target_candidates: [{ column: 'sales', confidence: 0.99 }],
        channels: [{ name: 'TV', confidence: 0.97 }],
      },
    });
    expect(getState().currentStep).toBe(6);
  });

  it('populates bestPracticeWarnings from detect results', () => {
    applyAutoDetectResults({
      best_practice_warnings: [
        { recommendation: 'Добавьте больше истории' },
        { recommendation: 'Проверьте аномалии' },
      ],
      data_signature: {
        quality_gates: {},
        target_candidates: [],
        channels: [],
      },
    });
    const warnings = getState().bestPracticeWarnings;
    expect(warnings).toContain('Добавьте больше истории');
    expect(warnings).toContain('Проверьте аномалии');
  });
});


// ---------------------------------------------------------------------------
// Suite 9: invalidateDownstream
// ---------------------------------------------------------------------------
describe('invalidateDownstream', () => {
  it('removes stepData for all steps after fromStep', () => {
    activateAtStep(4);
    saveStepData(3, { confirmed: true });
    saveStepData(4, { budget: 100 });
    saveStepData(5, { context: true });
    saveStepData(6, { run: true });
    invalidateDownstream(3);
    const sd = getState().stepData;
    expect(sd.step3).toBeDefined(); // step3 itself preserved
    expect(sd.step4).toBeUndefined();
    expect(sd.step5).toBeUndefined();
    expect(sd.step6).toBeUndefined();
  });

  it('does not change currentStep', () => {
    activateAtStep(4);
    invalidateDownstream(2);
    expect(getState().currentStep).toBe(4);
  });
});
