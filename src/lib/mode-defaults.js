/**
 * Aurora MMM Optimizer v2.0.0 - v1.3.x → v2.0.0 migration helpers.
 *
 * Implements the migration algorithm from PRE_FLIGHT_FIXES.md §B3.
 * Also provides defaultPerChannelInput() and detectExistingMode() helpers
 * for new project setup in Manager mode.
 *
 * Algorithm (5 cases):
 *   Case 1: empty project          → analysisMode='roi',           expertMode=false, no toast
 *   Case 2: pure monetary           → analysisMode='roi',           expertMode=false, no toast
 *   Case 3: pure physical           → analysisMode='effectiveness', expertMode=false, no toast
 *   Case 4: mixed monetary+physical → analysisMode='mixed',         expertMode=true,  TOAST
 *   Case 5: null/unknown values     → analysisMode='mixed',         expertMode=true,  TOAST
 *
 * @module mode-defaults
 */

import { analysisMode, expertMode } from './project-state.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} MigrationResult
 * @property {boolean} migrated            - true if project had v1.3.x data to migrate
 * @property {string}  scenario            - 'new' | 'pure_monetary_to_roi' | 'pure_physical_to_effectiveness' | 'mixed_to_expert' | 'unknown_legacy'
 * @property {boolean} toast               - whether to show migration toast
 * @property {string}  [toastMessage]      - toast body text (RU locale)
 * @property {string}  [toastMessageEn]    - toast body text (EN locale)
 */

// ---------------------------------------------------------------------------
// Toast messages (bilingual per §B3 spec)
// ---------------------------------------------------------------------------

const TOAST_RU =
  'Включён режим эксперта. Ваш проект использует смешанный режим единиц медиа-каналов ' +
  '(часть в ₽, часть в физических метриках). ' +
  'Поканальное управление доступно в режиме эксперта. ' +
  'Переключить режим - Settings.';

const TOAST_EN =
  'Expert mode activated. Your project uses mixed media unit modes ' +
  '(some monetary ₽, some physical metrics). ' +
  'Per-channel control available in Expert UI. ' +
  'Toggle mode in Settings.';

// ---------------------------------------------------------------------------
// Main migration function
// ---------------------------------------------------------------------------

/**
 * Migrate a v1.3.x project to v2.0.0 analysisMode + expertMode.
 * Per PRE_FLIGHT_FIXES.md §B3 algorithm (Cases 1-5).
 *
 * Side effects: calls analysisMode.set() and expertMode.set() from project-state.js.
 * Caller is responsible for showing the toast if result.toast === true.
 *
 * @param {{ perChannelInput?: Record<string, 'monetary'|'physical'|null|string> }} projectState
 * @returns {MigrationResult}
 *
 * @example
 * // Case 2 - pure monetary
 * migrateV13ToV20({ perChannelInput: { TV: 'monetary', Digital: 'monetary' } });
 * // → { migrated: true, scenario: 'pure_monetary_to_roi', toast: false }
 *
 * @example
 * // Case 4 - mixed
 * migrateV13ToV20({ perChannelInput: { TV: 'physical', Digital: 'monetary' } });
 * // → { migrated: true, scenario: 'mixed_to_expert', toast: true, toastMessage: '...' }
 *
 * @example
 * // Case 1 - new/empty
 * migrateV13ToV20({});
 * // → { migrated: false, scenario: 'new', toast: false }
 */
export function migrateV13ToV20(projectState) {
  const pcInput = projectState?.perChannelInput ?? {};
  const channels = Object.keys(pcInput);

  // Case 1: empty project (new project, no v1.3.x data)
  if (channels.length === 0) {
    analysisMode.set('roi');
    expertMode.set(false);
    return {
      migrated: false,
      scenario: 'new',
      toast: false,
    };
  }

  // Classify values - treat null / undefined / unexpected strings as unknown
  const monetary = channels.filter((ch) => pcInput[ch] === 'monetary');
  const physical = channels.filter((ch) => pcInput[ch] === 'physical');
  const unknown  = channels.filter((ch) => pcInput[ch] !== 'monetary' && pcInput[ch] !== 'physical');

  // Case 5: all values are unknown/null (legacy bundle without per-channel field, fallback)
  // This check comes before Case 2/3 because unknown.length > 0 with mixed cases.
  // If ALL are unknown - it's a fully unrecognized legacy bundle.
  if (unknown.length === channels.length) {
    analysisMode.set('mixed');
    expertMode.set(true);
    return {
      migrated: true,
      scenario: 'unknown_legacy',
      toast: true,
      toastMessage: TOAST_RU,
      toastMessageEn: TOAST_EN,
    };
  }

  // Case 2: pure monetary (all known channels are monetary, no physical, maybe unknowns)
  // Strict: require zero unknown for a clean pure-monetary call.
  if (monetary.length > 0 && physical.length === 0 && unknown.length === 0) {
    analysisMode.set('roi');
    expertMode.set(false);
    return {
      migrated: true,
      scenario: 'pure_monetary_to_roi',
      toast: false,
    };
  }

  // Case 3: pure physical (all known channels are physical, no monetary, maybe unknowns)
  if (physical.length > 0 && monetary.length === 0 && unknown.length === 0) {
    analysisMode.set('effectiveness');
    expertMode.set(false);
    return {
      migrated: true,
      scenario: 'pure_physical_to_effectiveness',
      toast: false,
    };
  }

  // Case 4 + fallback for partial-unknown: mixed (some monetary + some physical, or any unknown alongside known)
  // Covers: mixed monetary+physical, monetary+unknown, physical+unknown, etc.
  analysisMode.set('mixed');
  expertMode.set(true);

  const scenario = monetary.length > 0 && physical.length > 0
    ? 'mixed_to_expert'
    : 'unknown_legacy';

  return {
    migrated: true,
    scenario,
    toast: true,
    toastMessage: TOAST_RU,
    toastMessageEn: TOAST_EN,
  };
}

// ---------------------------------------------------------------------------
// Default per-channel input for new projects
// ---------------------------------------------------------------------------

/**
 * Build a default perChannelInput map for a new project in Manager mode.
 * Manager mode offers two clean modes (roi / effectiveness); mixed requires Expert.
 *
 * @param {string[]} channels - channel names from auto-detect or user input
 * @param {'roi' | 'effectiveness' | 'mixed'} mode - target analysis mode
 * @returns {Record<string, 'monetary' | 'physical'>}
 *
 * @example
 * defaultPerChannelInput(['TV', 'Digital', 'OOH'], 'roi');
 * // → { TV: 'monetary', Digital: 'monetary', OOH: 'monetary' }
 *
 * @example
 * defaultPerChannelInput(['TV', 'Digital', 'OOH'], 'effectiveness');
 * // → { TV: 'physical', Digital: 'physical', OOH: 'physical' }
 *
 * @example
 * // Mixed mode: no single default - returns empty map (caller sets per-channel)
 * defaultPerChannelInput(['TV', 'Digital'], 'mixed');
 * // → {}
 */
export function defaultPerChannelInput(channels, mode) {
  if (!Array.isArray(channels) || channels.length === 0) return {};

  if (mode === 'roi') {
    return Object.fromEntries(channels.map((ch) => [ch, 'monetary']));
  }

  if (mode === 'effectiveness') {
    return Object.fromEntries(channels.map((ch) => [ch, 'physical']));
  }

  // mixed - no uniform default; caller must specify per-channel
  return {};
}

// ---------------------------------------------------------------------------
// Detect existing mode from perChannelInput
// ---------------------------------------------------------------------------

/**
 * Infer the current analysis mode from a perChannelInput map.
 * Returns the most specific mode that accurately describes the data.
 *
 * @param {Record<string, 'monetary' | 'physical'>} pcInput
 * @returns {'roi' | 'effectiveness' | 'mixed'}
 *
 * @example
 * detectExistingMode({ TV: 'monetary', Digital: 'monetary' }); // → 'roi'
 * detectExistingMode({ TV: 'physical', OOH: 'physical' });     // → 'effectiveness'
 * detectExistingMode({ TV: 'physical', Digital: 'monetary' }); // → 'mixed'
 * detectExistingMode({});                                        // → 'roi' (default)
 */
export function detectExistingMode(pcInput) {
  if (!pcInput || Object.keys(pcInput).length === 0) {
    return 'roi'; // default per INV-30
  }

  const values = Object.values(pcInput).filter(
    (v) => v === 'monetary' || v === 'physical',
  );

  if (values.length === 0) return 'roi'; // all unknown - safe default

  const hasMonetary = values.includes('monetary');
  const hasPhysical = values.includes('physical');

  if (hasMonetary && !hasPhysical) return 'roi';
  if (hasPhysical && !hasMonetary) return 'effectiveness';
  return 'mixed';
}
