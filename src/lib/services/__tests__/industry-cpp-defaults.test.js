/**
 * Industry CPP defaults tests - Phase 4.1.
 */
import { describe, it, expect } from 'vitest';
import {
  INDUSTRY_CPP_TABLE,
  detectUnitType,
  suggestUnitCostDefault,
  validateUnitCost,
  listIndustries,
} from '$lib/services/industry-cpp-defaults.js';


describe('INDUSTRY_CPP_TABLE', () => {
  it('is frozen (immutable)', () => {
    expect(Object.isFrozen(INDUSTRY_CPP_TABLE)).toBe(true);
  });

  it('contains 8 industries', () => {
    const industries = Object.keys(INDUSTRY_CPP_TABLE);
    expect(industries).toEqual(
      expect.arrayContaining(['pharma_otc', 'pharma_rx', 'fmcg', 'retail', 'saas', 'finance', 'b2b', 'unknown']),
    );
    expect(industries.length).toBe(8);
  });

  it('pharma_otc has TRP / CPM / CPC entries', () => {
    expect(INDUSTRY_CPP_TABLE.pharma_otc.trp).toBeDefined();
    expect(INDUSTRY_CPP_TABLE.pharma_otc.cpm).toBeDefined();
    expect(INDUSTRY_CPP_TABLE.pharma_otc.cpc).toBeDefined();
  });

  it('ranges have valid min ≤ typical ≤ max', () => {
    for (const [industry, units] of Object.entries(INDUSTRY_CPP_TABLE)) {
      for (const [unit, range] of Object.entries(units)) {
        if (!range) continue;
        expect(range.min).toBeLessThanOrEqual(range.typical);
        expect(range.typical).toBeLessThanOrEqual(range.max);
      }
    }
  });

  it('confidence values are valid', () => {
    const validConfidences = ['high', 'medium', 'low'];
    for (const units of Object.values(INDUSTRY_CPP_TABLE)) {
      for (const range of Object.values(units)) {
        if (!range) continue;
        expect(validConfidences).toContain(range.confidence);
      }
    }
  });
});


describe('detectUnitType', () => {
  it.each([
    ['TRPs бренд', 'trp'],
    ['trp_brand', 'trp'],
    ['GRP_total', 'grp'],
    ['Banners Показы', 'cpm'],
    ['impressions_total', 'cpm'],
    ['Banners Клики', 'cpc'],
    ['clicks_search', 'cpc'],
    ['Просмотры', 'cpv'],
    ['conversion_events', 'cpa'],
    ['OLV Бюджет', null],
    ['Unknown', null],
    ['', null],
  ])('detectUnitType(%s) === %s', (channel, expected) => {
    expect(detectUnitType(channel)).toBe(expected);
  });

  it('handles null safely', () => {
    // @ts-expect-error testing runtime null safety (signature is string)
    expect(detectUnitType(null)).toBe(null);
  });
});


describe('suggestUnitCostDefault', () => {
  it('returns null для unknown channel pattern', () => {
    expect(suggestUnitCostDefault('Mystery Bucket')).toBe(null);
  });

  it('suggests TRP cost for pharma OTC', () => {
    const result = suggestUnitCostDefault('TRPs бренд', 'pharma_otc');
    if (!result) throw new Error('expected non-null result');
    expect(result.value).toBe(800_000);
    expect(result.range.min).toBe(400_000);
    expect(result.range.max).toBe(1_500_000);
    expect(result.confidence).toBe('high');
  });

  it('suggests CPM for FMCG', () => {
    const result = suggestUnitCostDefault('Banners Показы', 'fmcg');
    if (!result) throw new Error('expected non-null result');
    expect(result.value).toBe(280);
    expect(result.confidence).toBe('high');
  });

  it('falls back на unknown industry если specific missing', () => {
    // pharma_rx не имеет 'trp' entry → falls back на unknown.trp
    const result = suggestUnitCostDefault('TRPs', 'pharma_rx');
    if (!result) throw new Error('expected non-null result');
    expect(result.confidence).toBe('low');  // generic fallback marker
  });

  it('uses unknown industry as default', () => {
    const result = suggestUnitCostDefault('TRPs бренд');  // no industry arg
    if (!result) throw new Error('expected non-null result');
    expect(result.confidence).toBe('low');
  });

  it('includes source attribution когда available', () => {
    const result = suggestUnitCostDefault('TRPs', 'pharma_otc');
    if (!result) throw new Error('expected non-null result');
    expect(result.source).toMatch(/Mediascope/);
  });
});


describe('validateUnitCost', () => {
  it('rejects non-positive values', () => {
    const result = validateUnitCost(0, 'TRPs бренд', 'pharma_otc');
    expect(result.valid).toBe(false);
    expect(result.severity).toBe('error');
  });

  it('rejects NaN', () => {
    const result = validateUnitCost(NaN, 'TRPs бренд', 'pharma_otc');
    expect(result.valid).toBe(false);
  });

  it('accepts typical value', () => {
    const result = validateUnitCost(800_000, 'TRPs бренд', 'pharma_otc');
    expect(result.valid).toBe(true);
    expect(result.severity).toBe('ok');
  });

  it('warns когда below typical range', () => {
    const result = validateUnitCost(100_000, 'TRPs бренд', 'pharma_otc');
    expect(result.valid).toBe(true);
    expect(result.severity).toBe('warning');
    expect(result.message).toMatch(/ниже/);
  });

  it('warns когда above typical range', () => {
    const result = validateUnitCost(5_000_000, 'TRPs бренд', 'pharma_otc');
    expect(result.valid).toBe(true);
    expect(result.severity).toBe('warning');
    expect(result.message).toMatch(/выше/);
  });

  it('ok когда channel pattern not detected (no validation)', () => {
    const result = validateUnitCost(1, 'Mystery Bucket', 'pharma_otc');
    expect(result.valid).toBe(true);
    expect(result.severity).toBe('ok');
  });
});


describe('listIndustries', () => {
  it('returns 8 industry codes', () => {
    const list = listIndustries();
    expect(list.length).toBe(8);
    expect(list).toContain('pharma_otc');
    expect(list).toContain('unknown');
  });
});
