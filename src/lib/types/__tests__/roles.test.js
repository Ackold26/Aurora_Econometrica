/**
 * roles.js tests - Phase 2.5 shared role enum.
 */
import { describe, it, expect } from 'vitest';
import {
  ROLES,
  EXCLUDED_DISPLAY_ROLES,
  TARGET_ROLES,
  MEDIA_ROLES,
  CONTROL_ROLES,
  isExcludedRole,
  isMediaRole,
  isControlRole,
  isTargetRole,
} from '$lib/types/roles.js';


describe('ROLES enum', () => {
  it('exposes all 16 documented roles', () => {
    const expected = [
      'kpi', 'target_monetary', 'target_count',
      'media', 'monetary', 'physical',
      'control', 'signed_competitor', 'signed_price', 'signed_weather', 'signed_macro',
      'holiday', 'date', 'unused', 'excluded', 'unknown',
    ];
    const values = Object.values(ROLES);
    for (const e of expected) {
      expect(values).toContain(e);
    }
  });

  it('is frozen (immutable)', () => {
    expect(Object.isFrozen(ROLES)).toBe(true);
  });
});


describe('Role category sets', () => {
  it('EXCLUDED_DISPLAY_ROLES contains unused/excluded/unknown', () => {
    expect(EXCLUDED_DISPLAY_ROLES.has('unused')).toBe(true);
    expect(EXCLUDED_DISPLAY_ROLES.has('excluded')).toBe(true);
    expect(EXCLUDED_DISPLAY_ROLES.has('unknown')).toBe(true);
  });

  it('TARGET_ROLES contains kpi/target_monetary/target_count', () => {
    expect(TARGET_ROLES.has('kpi')).toBe(true);
    expect(TARGET_ROLES.has('target_monetary')).toBe(true);
    expect(TARGET_ROLES.has('target_count')).toBe(true);
  });

  it('MEDIA_ROLES contains media/monetary/physical', () => {
    expect(MEDIA_ROLES.has('media')).toBe(true);
    expect(MEDIA_ROLES.has('monetary')).toBe(true);
    expect(MEDIA_ROLES.has('physical')).toBe(true);
  });

  it('CONTROL_ROLES contains control + signed_* + holiday', () => {
    expect(CONTROL_ROLES.has('control')).toBe(true);
    expect(CONTROL_ROLES.has('signed_competitor')).toBe(true);
    expect(CONTROL_ROLES.has('signed_price')).toBe(true);
    expect(CONTROL_ROLES.has('signed_weather')).toBe(true);
    expect(CONTROL_ROLES.has('signed_macro')).toBe(true);
    expect(CONTROL_ROLES.has('holiday')).toBe(true);
  });
});


describe('isExcludedRole', () => {
  it.each([
    ['unused', true],
    ['excluded', true],
    ['unknown', true],
    [null, true],
    [undefined, true],
    ['media', false],
    ['kpi', false],
    ['control', false],
    ['arbitrary_string', false],
  ])('isExcludedRole(%s) === %s', (role, expected) => {
    expect(isExcludedRole(role)).toBe(expected);
  });
});


describe('isMediaRole', () => {
  it.each([
    ['media', true],
    ['monetary', true],
    ['physical', true],
    [null, false],
    ['kpi', false],
    ['control', false],
  ])('isMediaRole(%s) === %s', (role, expected) => {
    expect(isMediaRole(role)).toBe(expected);
  });
});


describe('isControlRole', () => {
  it.each([
    ['control', true],
    ['signed_competitor', true],
    ['signed_price', true],
    ['signed_weather', true],
    ['signed_macro', true],
    ['holiday', true],
    ['media', false],
    ['kpi', false],
    [null, false],
  ])('isControlRole(%s) === %s', (role, expected) => {
    expect(isControlRole(role)).toBe(expected);
  });
});


describe('isTargetRole', () => {
  it.each([
    ['kpi', true],
    ['target_monetary', true],
    ['target_count', true],
    ['media', false],
    ['control', false],
    [null, false],
  ])('isTargetRole(%s) === %s', (role, expected) => {
    expect(isTargetRole(role)).toBe(expected);
  });
});
