/**
 * mode-defaults.js unit tests - v1.3.x → v2.0.0 migration helpers.
 *
 * Coverage:
 *   - migrateV13ToV20: Cases 1-5 + edge cases
 *   - defaultPerChannelInput: roi / effectiveness / mixed
 *   - detectExistingMode: pure monetary / physical / mixed / empty
 *   - Toast bilingual content
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { migrateV13ToV20, defaultPerChannelInput, detectExistingMode } from '../lib/mode-defaults.js';
import { analysisMode, expertMode } from '../lib/project-state.js';


// Reset stores before each test
beforeEach(() => {
  analysisMode.set('roi');
  expertMode.set(false);
});


// ---------------------------------------------------------------------------
// Suite 1: migrateV13ToV20
// ---------------------------------------------------------------------------
describe('migrateV13ToV20', () => {

  // Case 1: empty project
  it('Case 1: empty projectState → mode=roi, expertMode=false, migrated=false, no toast', () => {
    const result = migrateV13ToV20({});
    expect(result.migrated).toBe(false);
    expect(result.scenario).toBe('new');
    expect(result.toast).toBe(false);
    expect(get(analysisMode)).toBe('roi');
    expect(get(expertMode)).toBe(false);
  });

  it('Case 1: null projectState → same as empty', () => {
    const result = migrateV13ToV20(null);
    expect(result.scenario).toBe('new');
    expect(get(analysisMode)).toBe('roi');
  });

  it('Case 1: perChannelInput is empty object → new project', () => {
    const result = migrateV13ToV20({ perChannelInput: {} });
    expect(result.scenario).toBe('new');
    expect(result.toast).toBe(false);
  });

  // Case 2: pure monetary
  it('Case 2: all monetary → mode=roi, expertMode=false, no toast', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'monetary', Digital: 'monetary', OOH: 'monetary' },
    });
    expect(result.migrated).toBe(true);
    expect(result.scenario).toBe('pure_monetary_to_roi');
    expect(result.toast).toBe(false);
    expect(get(analysisMode)).toBe('roi');
    expect(get(expertMode)).toBe(false);
  });

  it('Case 2: single monetary channel → roi', () => {
    const result = migrateV13ToV20({ perChannelInput: { TV: 'monetary' } });
    expect(result.scenario).toBe('pure_monetary_to_roi');
    expect(get(analysisMode)).toBe('roi');
  });

  // Case 3: pure physical
  it('Case 3: all physical → mode=effectiveness, expertMode=false, no toast', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'physical', OOH: 'physical', Digital: 'physical' },
    });
    expect(result.migrated).toBe(true);
    expect(result.scenario).toBe('pure_physical_to_effectiveness');
    expect(result.toast).toBe(false);
    expect(get(analysisMode)).toBe('effectiveness');
    expect(get(expertMode)).toBe(false);
  });

  it('Case 3: single physical channel → effectiveness', () => {
    const result = migrateV13ToV20({ perChannelInput: { TV: 'physical' } });
    expect(result.scenario).toBe('pure_physical_to_effectiveness');
  });

  // Case 4: mixed monetary + physical
  it('Case 4: mixed monetary+physical → mode=mixed, expertMode=true, toast', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'physical', Digital: 'monetary' },
    });
    expect(result.migrated).toBe(true);
    expect(result.scenario).toBe('mixed_to_expert');
    expect(result.toast).toBe(true);
    expect(get(analysisMode)).toBe('mixed');
    expect(get(expertMode)).toBe(true);
  });

  it('Case 4: 3-channel mixed → mixed_to_expert', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'monetary', Digital: 'physical', OOH: 'monetary' },
    });
    expect(result.scenario).toBe('mixed_to_expert');
    expect(get(expertMode)).toBe(true);
  });

  // Case 5: all unknown/null values
  it('Case 5: all null values → mode=mixed, expertMode=true, toast', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: null, Digital: null },
    });
    expect(result.migrated).toBe(true);
    expect(result.scenario).toBe('unknown_legacy');
    expect(result.toast).toBe(true);
    expect(get(analysisMode)).toBe('mixed');
    expect(get(expertMode)).toBe(true);
  });

  it('Case 5: all unknown string values → unknown_legacy', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'budgets', Digital: 'grps' },
    });
    expect(result.scenario).toBe('unknown_legacy');
    expect(get(analysisMode)).toBe('mixed');
  });

  // Toast message bilingual content
  it('Toast contains both RU + EN message fields when toast=true', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'physical', Digital: 'monetary' },
    });
    expect(result.toast).toBe(true);
    expect(typeof result.toastMessage).toBe('string');
    expect(result.toastMessage.length).toBeGreaterThan(10);
    expect(typeof result.toastMessageEn).toBe('string');
    expect(result.toastMessageEn.length).toBeGreaterThan(10);
  });

  it('Toast RU message contains expected phrases', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: null, Digital: null, OOH: null },
    });
    expect(result.toastMessage).toContain('режим эксперта');
    expect(result.toastMessage).toContain('Settings');
  });

  it('Toast EN message exists and differs from RU', () => {
    const result = migrateV13ToV20({
      perChannelInput: { TV: 'physical', Digital: 'monetary' },
    });
    expect(result.toastMessage).not.toBe(result.toastMessageEn);
  });
});


// ---------------------------------------------------------------------------
// Suite 2: defaultPerChannelInput
// ---------------------------------------------------------------------------
describe('defaultPerChannelInput', () => {
  it('roi mode → all channels monetary', () => {
    const result = defaultPerChannelInput(['TV', 'Digital', 'OOH'], 'roi');
    expect(result).toEqual({ TV: 'monetary', Digital: 'monetary', OOH: 'monetary' });
  });

  it('effectiveness mode → all channels physical', () => {
    const result = defaultPerChannelInput(['TV', 'Digital', 'OOH'], 'effectiveness');
    expect(result).toEqual({ TV: 'physical', Digital: 'physical', OOH: 'physical' });
  });

  it('mixed mode → returns empty map (no uniform default)', () => {
    const result = defaultPerChannelInput(['TV', 'Digital'], 'mixed');
    expect(result).toEqual({});
  });

  it('empty channels array → returns empty map regardless of mode', () => {
    expect(defaultPerChannelInput([], 'roi')).toEqual({});
    expect(defaultPerChannelInput([], 'effectiveness')).toEqual({});
    expect(defaultPerChannelInput([], 'mixed')).toEqual({});
  });

  it('non-array channels → returns empty map', () => {
    // @ts-ignore
    expect(defaultPerChannelInput(null, 'roi')).toEqual({});
    // @ts-ignore
    expect(defaultPerChannelInput(undefined, 'roi')).toEqual({});
  });

  it('single channel roi', () => {
    const result = defaultPerChannelInput(['Print'], 'roi');
    expect(result).toEqual({ Print: 'monetary' });
  });
});


// ---------------------------------------------------------------------------
// Suite 3: detectExistingMode
// ---------------------------------------------------------------------------
describe('detectExistingMode', () => {
  it('all monetary → roi', () => {
    expect(detectExistingMode({ TV: 'monetary', Digital: 'monetary' })).toBe('roi');
  });

  it('single monetary → roi', () => {
    expect(detectExistingMode({ TV: 'monetary' })).toBe('roi');
  });

  it('all physical → effectiveness', () => {
    expect(detectExistingMode({ TV: 'physical', OOH: 'physical' })).toBe('effectiveness');
  });

  it('single physical → effectiveness', () => {
    expect(detectExistingMode({ TV: 'physical' })).toBe('effectiveness');
  });

  it('mixed monetary+physical → mixed', () => {
    expect(detectExistingMode({ TV: 'physical', Digital: 'monetary' })).toBe('mixed');
  });

  it('empty map → roi (safe default)', () => {
    expect(detectExistingMode({})).toBe('roi');
  });

  it('null input → roi (safe default)', () => {
    // @ts-ignore
    expect(detectExistingMode(null)).toBe('roi');
  });

  it('all unknown values (not monetary/physical) → roi (safe default)', () => {
    // @ts-ignore
    expect(detectExistingMode({ TV: null, Digital: 'budgets' })).toBe('roi');
  });
});
