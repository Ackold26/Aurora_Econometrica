/**
 * Cabinet-specific onboarding configurations.
 * Each cabinet can define a "3 Steps to Wow" flow.
 * @module onboarding-config
 */

import { get } from 'svelte/store';
import { cabinetOnboarding } from './store.js';

/**
 * @typedef {Object} OnboardingStep
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {string} [focusCommand] - Command to highlight in step 2
 * @property {string[]} [nextActions] - Commands to show in step 3
 * @property {'hasFiles'|'hasResponse'|'manual'} triggerCondition
 */

/**
 * @typedef {Object} OnboardingConfig
 * @property {OnboardingStep[]} steps
 * @property {string[]} noviceCommands - Commands visible for <5 requests
 */

// ── Data (loaded from content pack) ──

/** @type {Record<string, OnboardingConfig>} */
let _configs = {};

/**
 * Initialize onboarding data from content pack JSON.
 * Called once from +layout.svelte during app startup.
 * @param {any} data - parsed onboarding-data.json
 */
export function initOnboardingData(data) {
  if (data) {
    _configs = data.configs || {};
  }
}

/**
 * Get onboarding config for a cabinet. Returns null if no config defined.
 * @param {string} cabinetId
 * @returns {OnboardingConfig|null}
 */
export function getOnboardingConfig(cabinetId) {
  return _configs[cabinetId] || null;
}

/**
 * Check if cabinet onboarding should be shown.
 * Shows when: config exists, virgin cabinet (0 requests), not completed.
 * @param {string} cabinetId
 * @param {Record<string, number>} cabinetRequests - from milestones store
 * @param {Record<string, {step: number, completed: boolean}>} onboardingState
 * @returns {boolean}
 */
export function shouldShowOnboarding(cabinetId, cabinetRequests, onboardingState) {
  if (!_configs[cabinetId]) return false;
  if (onboardingState[cabinetId]?.completed) return false;
  // Show if never used OR onboarding started but not finished
  const uses = cabinetRequests[cabinetId] || 0;
  return uses === 0 || (onboardingState[cabinetId]?.step != null && !onboardingState[cabinetId]?.completed);
}

/**
 * Get current onboarding step (0-based).
 * @param {string} cabinetId
 * @returns {number}
 */
export function getOnboardingStep(cabinetId) {
  const state = get(cabinetOnboarding);
  return state[cabinetId]?.step ?? 0;
}

/**
 * Advance to next step.
 * @param {string} cabinetId
 */
export function advanceOnboardingStep(cabinetId) {
  cabinetOnboarding.update(s => {
    const current = s[cabinetId]?.step ?? 0;
    return { ...s, [cabinetId]: { step: current + 1, completed: false } };
  });
}

/**
 * Complete onboarding for a cabinet.
 * @param {string} cabinetId
 */
export function completeOnboarding(cabinetId) {
  const config = _configs[cabinetId];
  const totalSteps = config?.steps.length ?? 3;
  cabinetOnboarding.update(s => ({
    ...s,
    [cabinetId]: { step: totalSteps, completed: true },
  }));
}

/**
 * Skip onboarding (immediate complete).
 * @param {string} cabinetId
 */
export function skipOnboarding(cabinetId) {
  completeOnboarding(cabinetId);
}
