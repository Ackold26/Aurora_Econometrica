/**
 * Locale parsing tests — Phase 2.11 / Audit Q2.
 *
 * Tests RU locale decimal parsing for numeric inputs. parseFloat() in
 * JavaScript handles ASCII '.' but не ',' (Russian decimal separator).
 * Customer typing «25,50» (their natural format) → parseFloat returns 25
 * (lost decimals) or NaN.
 *
 * This module covers:
 * - Pure parseFloat behaviour baseline (documents JS standard)
 * - A locale-aware helper that customers can use (if/when added)
 *
 * Phase 2.11 scope: baseline + recommendation. Implementation of
 * locale-aware parser deferred к Phase 2.x когда AppliedModeSummary
 * inputs reviewed for full RU locale support.
 */
import { describe, it, expect } from 'vitest';


describe('JavaScript parseFloat — RU locale baseline', () => {
  it('parses ASCII decimal correctly', () => {
    expect(parseFloat('25.50')).toBe(25.5);
  });

  it('parseFloat does NOT handle comma decimal', () => {
    // «25,50» в Russian locale → JavaScript stops at comma, returns 25
    expect(parseFloat('25,50')).toBe(25);
  });

  it('parseFloat handles negative numbers', () => {
    expect(parseFloat('-100')).toBe(-100);
  });

  it('parseFloat returns NaN for non-numeric', () => {
    expect(parseFloat('abc')).toBeNaN();
  });

  it('parseFloat handles space separator (RU thousands)', () => {
    // «25 000.50» — parseFloat stops at first space → returns 25
    expect(parseFloat('25 000.50')).toBe(25);
  });
});


/**
 * Locale-aware parse helper (recommended for AppliedModeSummary inputs).
 * Not yet imported into component — documenting expected behaviour.
 *
 * @param {string} value User input string
 * @returns {number | NaN}
 */
function parseRuFloat(value) {
  if (typeof value !== 'string') return NaN;
  // Replace RU decimal comma → dot, remove spaces (thousand separator)
  const normalized = value.replace(/\s/g, '').replace(',', '.');
  return parseFloat(normalized);
}


describe('parseRuFloat helper (recommended pattern)', () => {
  it.each([
    ['25.50', 25.5],
    ['25,50', 25.5],
    ['25 000', 25000],
    ['25 000,50', 25000.5],
    ['-100', -100],
    ['0', 0],
    ['0.001', 0.001],
  ])('parseRuFloat(%s) === %s', (input, expected) => {
    expect(parseRuFloat(input)).toBe(expected);
  });

  it('returns NaN for empty string', () => {
    expect(parseRuFloat('')).toBeNaN();
  });

  it('returns NaN for non-numeric', () => {
    expect(parseRuFloat('abc')).toBeNaN();
  });
});
