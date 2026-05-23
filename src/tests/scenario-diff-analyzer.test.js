/**
 * scenario-diff-analyzer.js unit tests - v2.0.0 Phase D.
 *
 * Coverage:
 *   - generateDiffNarratives: empty, single, 2, 3 scenarios vs baseline
 *   - generateDiffNarratives: concrete KPI %, budget %, Aurora-opt detection
 *   - generateDiffNarratives: negative uplift narrative
 *   - computePerChannelDiff: same channels sorted by |deltaAbs|
 *   - computePerChannelDiff: missing channels graceful handling
 *   - computePerChannelDiff: zero delta channels included in output
 *   - computePerChannelDiff: output structure verification
 *   - findBestEfficiencyScenario: empty, single, multiple, tie-break
 */
import { describe, it, expect } from 'vitest';
import {
  generateDiffNarratives,
  computePerChannelDiff,
  findBestEfficiencyScenario,
} from '../lib/scenario-diff-analyzer.js';


// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** @returns {import('../lib/scenario-diff-analyzer.js').Scenario} */
function makeBaseline() {
  return {
    id: 'baseline',
    name: 'Базовый',
    budget: 50_000_000,
    predictedKpi: 200_000,
    perChannelAllocation: { TV: 0.40, Digital: 0.35, OOH: 0.15, Print: 0.10 },
  };
}

/** @returns {import('../lib/scenario-diff-analyzer.js').Scenario} */
function makePlanA() {
  return {
    id: 'plan-a',
    name: 'План А',
    budget: 50_000_000,
    predictedKpi: 240_000,
    perChannelAllocation: { TV: 0.25, Digital: 0.50, OOH: 0.15, Print: 0.10 },
  };
}

/** @returns {import('../lib/scenario-diff-analyzer.js').Scenario} */
function makePlanB() {
  return {
    id: 'plan-b',
    name: 'План Б',
    budget: 70_000_000,
    predictedKpi: 270_000,
    perChannelAllocation: { TV: 0.30, Digital: 0.40, OOH: 0.20, Print: 0.10 },
  };
}

/** @returns {import('../lib/scenario-diff-analyzer.js').Scenario} */
function makeAuroraOpt() {
  return {
    id: 'aurora-optimized',
    name: 'Aurora-optimized',
    budget: 50_000_000,
    predictedKpi: 260_000,
    perChannelAllocation: { TV: 0.20, Digital: 0.55, OOH: 0.15, Print: 0.10 },
  };
}

/** Scenario where KPI is lower than baseline (negative uplift) */
/** @returns {import('../lib/scenario-diff-analyzer.js').Scenario} */
function makePlanNeg() {
  return {
    id: 'plan-neg',
    name: 'План Негативный',
    budget: 50_000_000,
    predictedKpi: 160_000,
    perChannelAllocation: { TV: 0.60, Digital: 0.20, OOH: 0.10, Print: 0.10 },
  };
}


// ---------------------------------------------------------------------------
// Suite 1: generateDiffNarratives - basic guards
// ---------------------------------------------------------------------------
describe('generateDiffNarratives - guards', () => {

  it('empty scenarios array → returns empty array', () => {
    const result = generateDiffNarratives([], null);
    expect(result).toEqual([]);
  });

  it('null scenarios → returns empty array', () => {
    const result = generateDiffNarratives(null, null);
    expect(result).toEqual([]);
  });

  it('single scenario without baseline → fallback message (no numeric narratives)', () => {
    const sc = makePlanA();
    const result = generateDiffNarratives([sc], null);
    // Only Section 2 (Aurora vs best user) and Section 3 (efficiency) apply when no baseline.
    // With 1 non-aurora scenario and no baseline: no pair comparison → fallback.
    expect(Array.isArray(result)).toBe(true);
    expect(result.length).toBeGreaterThan(0);
  });

  it('single scenario that IS baseline → excluded from comparison → fallback', () => {
    const baseline = makeBaseline();
    const result = generateDiffNarratives([baseline], baseline);
    expect(Array.isArray(result)).toBe(true);
  });

});


// ---------------------------------------------------------------------------
// Suite 2: generateDiffNarratives - vs baseline narratives
// ---------------------------------------------------------------------------
describe('generateDiffNarratives - vs baseline', () => {

  it('2 scenarios vs baseline → at least 2 narrative strings', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const planB = makePlanB();
    const result = generateDiffNarratives([planA, planB], baseline);
    expect(result.length).toBeGreaterThanOrEqual(2);
  });

  it('3 scenarios vs baseline → at least 3 narrative strings', () => {
    const baseline = makeBaseline();
    const result = generateDiffNarratives([makePlanA(), makePlanB(), makeAuroraOpt()], baseline);
    expect(result.length).toBeGreaterThanOrEqual(3);
  });

  it('narratives contain concrete positive KPI % for planA', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const result = generateDiffNarratives([planA], baseline);
    // planA KPI uplift = (240k - 200k)/200k * 100 = +20.0%
    const joined = result.join(' ');
    expect(joined).toMatch(/\+20\.0%/);
  });

  it('narrative for planB includes budget % increase', () => {
    const baseline = makeBaseline();
    const planB = makePlanB();
    const result = generateDiffNarratives([planB], baseline);
    // budget delta = (70M - 50M)/50M * 100 = +40.0%
    const joined = result.join(' ');
    expect(joined).toMatch(/\+40\.0%/);
  });

  it('narrative mentions baseline name', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const result = generateDiffNarratives([planA], baseline);
    expect(result.join(' ')).toContain('Базовый');
  });

  it('narrative mentions scenario name', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const result = generateDiffNarratives([planA], baseline);
    expect(result.join(' ')).toContain('План А');
  });

  it('negative uplift scenario → «снизит/уступает» phrasing or negative sign', () => {
    const baseline = makeBaseline();
    const planNeg = makePlanNeg();
    const result = generateDiffNarratives([planNeg], baseline);
    // planNeg KPI = 160k vs baseline 200k → delta = -20.0%
    const joined = result.join(' ');
    expect(joined).toMatch(/-20\.0%/);
  });

});


// ---------------------------------------------------------------------------
// Suite 3: generateDiffNarratives - Aurora-optimized detection
// ---------------------------------------------------------------------------
describe('generateDiffNarratives - Aurora-opt detection', () => {

  it('Aurora-optimized scenario is detected by name «aurora» pattern', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const auroraOpt = makeAuroraOpt();
    const result = generateDiffNarratives([planA, auroraOpt], baseline);
    const joined = result.join(' ');
    // Section 2 should generate: Aurora-optimized vs Plan A
    expect(joined).toContain('Aurora-optimized');
  });

  it('Aurora-optimized scenario «превосходит» best user plan when higher KPI', () => {
    const baseline = makeBaseline();
    const planA = makePlanA();
    const auroraOpt = makeAuroraOpt();
    // aurora KPI 260k > planA KPI 240k
    const result = generateDiffNarratives([planA, auroraOpt], baseline);
    expect(result.join(' ')).toContain('превосходит');
  });

  it('Aurora scenario уступает when lower KPI than best user plan', () => {
    const baseline = makeBaseline();
    const weakAurora = {
      id: 'aurora-optimized',
      name: 'Aurora-optimized',
      budget: 50_000_000,
      predictedKpi: 220_000, // less than planB 270k
      perChannelAllocation: { TV: 0.25, Digital: 0.50, OOH: 0.15, Print: 0.10 },
    };
    const planB = makePlanB();
    const result = generateDiffNarratives([planB, weakAurora], baseline);
    expect(result.join(' ')).toContain('уступает');
  });

  it('Scenario with «оптим» in name is treated as Aurora-opt', () => {
    const sc = {
      id: 'opt-1',
      name: 'Оптимальный сценарий',
      budget: 50_000_000,
      predictedKpi: 260_000,
      perChannelAllocation: { TV: 0.20, Digital: 0.60, OOH: 0.20 },
    };
    const userPlan = makePlanA();
    const baseline = makeBaseline();
    const result = generateDiffNarratives([userPlan, sc], baseline);
    expect(result.join(' ')).toContain('Оптимальный');
  });

});


// ---------------------------------------------------------------------------
// Suite 4: computePerChannelDiff - structure and sorting
// ---------------------------------------------------------------------------
describe('computePerChannelDiff - structure', () => {

  it('returns array of ChannelDiff objects', () => {
    const from = makeBaseline();
    const to = makePlanA();
    const result = computePerChannelDiff(from, to);
    expect(Array.isArray(result)).toBe(true);
    expect(result.length).toBeGreaterThan(0);
    result.forEach(d => {
      expect(d).toHaveProperty('channel');
      expect(d).toHaveProperty('fromAlloc');
      expect(d).toHaveProperty('toAlloc');
      expect(d).toHaveProperty('deltaAbs');
      expect(d).toHaveProperty('deltaPct');
    });
  });

  it('sorted by |deltaAbs| descending - largest shift first', () => {
    const from = makeBaseline();
    const to = makePlanA();
    // TV: 0.40→0.25 = -0.15, Digital: 0.35→0.50 = +0.15, OOH: same, Print: same
    const result = computePerChannelDiff(from, to);
    for (let i = 0; i < result.length - 1; i++) {
      expect(Math.abs(result[i].deltaAbs)).toBeGreaterThanOrEqual(Math.abs(result[i + 1].deltaAbs));
    }
  });

  it('deltaAbs = toAlloc - fromAlloc (signed)', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40 } };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.25 } };
    const result = computePerChannelDiff(from, to);
    const tvDiff = result.find(d => d.channel === 'TV');
    expect(tvDiff?.deltaAbs).toBeCloseTo(-0.15);
  });

  it('deltaPct = deltaAbs × 100 (percentage points)', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40 } };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.25 } };
    const result = computePerChannelDiff(from, to);
    const tvDiff = result.find(d => d.channel === 'TV');
    expect(tvDiff?.deltaPct).toBeCloseTo(-15);
  });

  it('zero delta channels are included in output (not filtered)', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.50, OOH: 0.50 } };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.50, OOH: 0.50 } };
    const result = computePerChannelDiff(from, to);
    expect(result.length).toBe(2);
    result.forEach(d => expect(d.deltaAbs).toBeCloseTo(0));
  });

});


// ---------------------------------------------------------------------------
// Suite 5: computePerChannelDiff - missing channels
// ---------------------------------------------------------------------------
describe('computePerChannelDiff - missing channels', () => {

  it('channel only in «from» → toAlloc=0, deltaAbs negative', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40, Radio: 0.20 } };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40 } };
    const result = computePerChannelDiff(from, to);
    const radio = result.find(d => d.channel === 'Radio');
    expect(radio).toBeDefined();
    expect(radio?.fromAlloc).toBeCloseTo(0.20);
    expect(radio?.toAlloc).toBeCloseTo(0);
    expect(radio?.deltaAbs).toBeCloseTo(-0.20);
  });

  it('channel only in «to» → fromAlloc=0, deltaAbs positive', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40 } };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1, perChannelAllocation: { TV: 0.40, Cinema: 0.15 } };
    const result = computePerChannelDiff(from, to);
    const cinema = result.find(d => d.channel === 'Cinema');
    expect(cinema).toBeDefined();
    expect(cinema?.fromAlloc).toBeCloseTo(0);
    expect(cinema?.toAlloc).toBeCloseTo(0.15);
    expect(cinema?.deltaAbs).toBeCloseTo(0.15);
  });

  it('empty perChannelAllocation on both sides → returns empty array', () => {
    const from = { id: 'f', name: 'F', budget: 1, predictedKpi: 1 };
    const to   = { id: 't', name: 'T', budget: 1, predictedKpi: 1 };
    const result = computePerChannelDiff(from, to);
    expect(result).toEqual([]);
  });

  it('null scenarios handled gracefully (no crash)', () => {
    expect(() => computePerChannelDiff(null, null)).not.toThrow();
    const result = computePerChannelDiff(null, null);
    expect(result).toEqual([]);
  });

});


// ---------------------------------------------------------------------------
// Suite 6: findBestEfficiencyScenario
// ---------------------------------------------------------------------------
describe('findBestEfficiencyScenario', () => {

  it('empty array → returns null', () => {
    expect(findBestEfficiencyScenario([])).toBeNull();
  });

  it('null input → returns null', () => {
    expect(findBestEfficiencyScenario(null)).toBeNull();
  });

  it('single valid scenario → returns that scenario', () => {
    const sc = makePlanA();
    expect(findBestEfficiencyScenario([sc])).toBe(sc);
  });

  it('multiple scenarios → returns highest KPI/budget ratio', () => {
    // planA: 240k / 50M = 0.0048
    // planB: 270k / 70M ≈ 0.00386  (lower efficiency despite higher KPI)
    const planA = makePlanA();
    const planB = makePlanB();
    const result = findBestEfficiencyScenario([planA, planB]);
    expect(result?.id).toBe('plan-a');
  });

  it('aurora-optimized wins if it has highest KPI/budget', () => {
    // aurora: 260k / 50M = 0.0052 (best)
    const planA = makePlanA();     // 240k / 50M = 0.0048
    const auroraOpt = makeAuroraOpt(); // 260k / 50M = 0.0052
    const result = findBestEfficiencyScenario([planA, auroraOpt]);
    expect(result?.id).toBe('aurora-optimized');
  });

  it('scenarios with zero budget are excluded from candidates', () => {
    const zeroBudget = { id: 'z', name: 'Zero', budget: 0, predictedKpi: 999_999 };
    const planA = makePlanA();
    const result = findBestEfficiencyScenario([zeroBudget, planA]);
    expect(result?.id).toBe('plan-a');
  });

  it('scenarios with zero/negative predictedKpi are excluded', () => {
    const zeroKpi = { id: 'z', name: 'ZeroKpi', budget: 1_000_000, predictedKpi: 0 };
    const planA = makePlanA();
    const result = findBestEfficiencyScenario([zeroKpi, planA]);
    expect(result?.id).toBe('plan-a');
  });

  it('tie-break: equal ratio → first occurrence returned (reduce stays with earlier)', () => {
    const sc1 = { id: 'sc1', name: 'SC1', budget: 1_000_000, predictedKpi: 100 };
    const sc2 = { id: 'sc2', name: 'SC2', budget: 1_000_000, predictedKpi: 100 };
    const result = findBestEfficiencyScenario([sc1, sc2]);
    // reduce returns best; when effSc === effBest it keeps best → sc1 stays
    expect(result?.id).toBe('sc1');
  });

  it('all invalid scenarios → returns null', () => {
    const bad = [
      { id: 'a', name: 'A', budget: 0, predictedKpi: 100 },
      { id: 'b', name: 'B', budget: 100, predictedKpi: 0 },
    ];
    expect(findBestEfficiencyScenario(bad)).toBeNull();
  });

});
