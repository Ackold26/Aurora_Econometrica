/**
 * classifier-patterns service tests - Phase 1.1.
 *
 * Tests cover: cache-with-fallback flow, RegExp compilation from
 * Python-exported patterns, unit label detection. SSOT parity с backend
 * verified в python `test_classifier_patterns_export.py`.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock Tauri invoke BEFORE service import.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

import { invoke as _invoke } from '@tauri-apps/api/core';
const invoke = /** @type {ReturnType<typeof vi.fn>} */ (/** @type {unknown} */ (_invoke));
import {
  ensurePatternsLoaded,
  detectChannelUnitType,
  unitLabelFor,
  _resetCache,
  _getCachedPayload,
} from '$lib/services/classifier-patterns.js';

const BACKEND_PAYLOAD = {
  version: 'v1',
  kinds: {
    monetary: [
      '(?:^|(?<=[_\\s\\-]))spend(?:s|ing)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))budget(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))бюджет(?:ы|а|ов)?(?=[_\\s\\-]|$)',
      '₽',
    ],
    physical: [
      '(?:^|(?<=[_\\s\\-]))trp(?:s)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))показ(?:ы|ов|а)?(?=[_\\s\\-]|$)',
      '(?:^|(?<=[_\\s\\-]))клик(?:ов|и)?(?=[_\\s\\-]|$)',
    ],
  },
  priority: ['monetary', 'physical'],
  unit_label_rules: [
    { pattern: '(?<![a-zA-Zа-яА-Я])(trp|трп)', label: '₽ за 1 TRP' },
    { pattern: '(impression|показ)', label: '₽ за 1000 показов (CPM)' },
    { pattern: '(click|клик)', label: '₽ за 1 клик (CPC)' },
  ],
};

beforeEach(() => {
  _resetCache();
  vi.clearAllMocks();
  invoke.mockReset();
  // Default mock - empty so embedded fallback engages если test не overrides
  invoke.mockResolvedValue(null);
});

describe('ensurePatternsLoaded - backend success', () => {
  it('fetches from backend и cache в memory', async () => {
    invoke.mockResolvedValueOnce(BACKEND_PAYLOAD);
    const payload = await ensurePatternsLoaded();
    expect(invoke).toHaveBeenCalledWith('econ_classifier_patterns');
    expect(payload.version).toBe('v1');
    expect(payload.kinds.monetary).toBeDefined();
  });

  it('idempotent - second call uses memory cache', async () => {
    invoke.mockResolvedValueOnce(BACKEND_PAYLOAD);
    await ensurePatternsLoaded();
    invoke.mockClear();
    await ensurePatternsLoaded();
    expect(invoke).not.toHaveBeenCalled();
  });
});

describe('ensurePatternsLoaded - backend failure → embedded fallback', () => {
  it('uses embedded fallback when backend throws', async () => {
    invoke.mockRejectedValueOnce(new Error('sidecar unreachable'));
    const payload = await ensurePatternsLoaded();
    expect(payload.embedded_fallback).toBe(true);
    expect(payload.kinds.monetary).toBeDefined();
  });

  it('uses embedded fallback when backend returns invalid payload', async () => {
    invoke.mockResolvedValueOnce({ no_kinds: true });
    const payload = await ensurePatternsLoaded();
    expect(payload.embedded_fallback).toBe(true);
  });
});

describe('detectChannelUnitType', () => {
  beforeEach(async () => {
    invoke.mockResolvedValueOnce(BACKEND_PAYLOAD);
    await ensurePatternsLoaded();
  });

  it.each([
    ['OLV Бюджет', 'monetary'],
    ['tv_spend', 'monetary'],
    ['Banners Бюджет', 'monetary'],
    ['TRPs бренд', 'physical'],
    ['Banners Показы', 'physical'],
    ['Social Клики', 'physical'],
  ])('classifies %s as %s', (name, expected) => {
    expect(detectChannelUnitType(name)).toBe(expected);
  });

  it('defaults к monetary для unknown', () => {
    expect(detectChannelUnitType('Unknown channel')).toBe('monetary');
  });

  it('handles empty string', () => {
    expect(detectChannelUnitType('')).toBe('monetary');
  });

  it('handles null/undefined safely', () => {
    // @ts-expect-error - explicit nullish test
    expect(detectChannelUnitType(null)).toBe('monetary');
    // @ts-expect-error - explicit nullish test
    expect(detectChannelUnitType(undefined)).toBe('monetary');
  });

  it('monetary priority overrides physical mention (e.g. "tv_spend" not classified as physical)', () => {
    expect(detectChannelUnitType('tv_spend')).toBe('monetary');
  });
});

describe('unitLabelFor', () => {
  beforeEach(async () => {
    invoke.mockResolvedValueOnce(BACKEND_PAYLOAD);
    await ensurePatternsLoaded();
  });

  it.each([
    ['TRPs бренд (W 25-54)', '₽ за 1 TRP'],
    ['Banners Показы', '₽ за 1000 показов (CPM)'],
    ['Banners Клики', '₽ за 1 клик (CPC)'],
  ])('returns label for %s', (name, expected) => {
    expect(unitLabelFor(name)).toBe(expected);
  });

  it('falls back к generic для unknown', () => {
    expect(unitLabelFor('Mystery metric')).toBe('₽ за 1 единицу');
  });

  it('handles empty/null', () => {
    expect(unitLabelFor('')).toBe('₽ за 1 единицу');
    // @ts-expect-error - explicit nullish test
    expect(unitLabelFor(null)).toBe('₽ за 1 единицу');
  });
});

describe('localStorage cache', () => {
  it('persists payload across calls (when localStorage works)', async () => {
    invoke.mockResolvedValueOnce(BACKEND_PAYLOAD);
    await ensurePatternsLoaded();
    const stored = localStorage.getItem('aurora-classifier-patterns-v1');
    expect(stored).toBeTruthy();
    const parsed = JSON.parse(stored ?? '{}');
    expect(parsed._payload.version).toBe('v1');
    expect(parsed._cached_at).toBeTypeOf('number');
  });
});

describe('lazy initialization', () => {
  it('detectChannelUnitType works без explicit ensurePatternsLoaded (lazy)', () => {
    // Don't call ensurePatternsLoaded; relies on embedded fallback compile.
    _resetCache();
    expect(detectChannelUnitType('tv_spend')).toBe('monetary');
  });

  it('unitLabelFor works без explicit init (lazy)', () => {
    _resetCache();
    expect(unitLabelFor('TRPs бренд')).toBe('₽ за 1 TRP');
  });
});
