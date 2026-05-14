/**
 * MultiScenarioChart component tests — v2.0.0 Phase D.
 *
 * Chart wraps EChartBase (ECharts, async canvas init). Tests focus on:
 * - DOM structure and conditional rendering (empty state, overflow warning)
 * - No crash for valid scenarios with 1, 3, >5 entries
 * - Baseline prop (grey line metadata) consumed without crash
 * - CI ribbons: no crash when ciLowSeries/ciHighSeries present
 * - Endpoint labels: render on tail (no crash)
 * - kpiLabel prop reflected in chart title
 * - Overflow warning shown when scenarios > maxVisible (default 5)
 *
 * Note: ECharts canvas initialisation is async and does not run in jsdom.
 * We verify wrapper structure and conditional UI blocks, not series data.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import MultiScenarioChart from '$lib/components/pipeline/MultiScenarioChart.svelte';


// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal Scenario object.
 * @param {string} id
 * @param {Partial<{budget: number, kpi: number, dates: string[], predictions: number[]}>} [opts]
 */
function makeScenario(id, opts = {}) {
  return {
    id,
    name: `Сценарий ${id}`,
    budget: opts.budget ?? 50_000_000,
    predictedKpi: opts.kpi ?? 240_000,
    dates: opts.dates ?? ['2024-01', '2024-02', '2024-03'],
    predictions: opts.predictions ?? [220_000, 240_000, 260_000],
    perChannelAllocation: { TV: 0.40, Digital: 0.35, OOH: 0.25 },
  };
}

function makeBaseline() {
  return {
    id: 'baseline',
    name: 'Базовый',
    budget: 50_000_000,
    predictedKpi: 200_000,
    dates: ['2024-01', '2024-02', '2024-03'],
    predictions: [190_000, 200_000, 210_000],
    perChannelAllocation: { TV: 0.40, Digital: 0.35, OOH: 0.25 },
  };
}

/** Build N scenario objects */
function makeScenarios(n) {
  return Array.from({ length: n }, (_, i) => makeScenario(`sc-${i + 1}`));
}


// ---------------------------------------------------------------------------
// Suite 1: Empty and guard states
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — empty state', () => {

  it('renders without crash when scenarios=[] and no baseline', () => {
    expect(() => render(MultiScenarioChart, { props: { scenarios: [] } })).not.toThrow();
  });

  it('shows empty state element when scenarios=[] and no baseline', () => {
    const { container } = render(MultiScenarioChart, { props: { scenarios: [] } });
    expect(container.querySelector('.empty-state')).toBeInTheDocument();
  });

  it('empty state contains «Нет данных» text', () => {
    render(MultiScenarioChart, { props: { scenarios: [] } });
    expect(screen.getByText(/Нет данных/)).toBeInTheDocument();
  });

  it('no overflow warning shown when scenarios=[]', () => {
    const { container } = render(MultiScenarioChart, { props: { scenarios: [] } });
    expect(container.querySelector('.overflow-warn')).toBeNull();
  });

});


// ---------------------------------------------------------------------------
// Suite 2: Single scenario
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — single scenario', () => {

  it('renders without crash with 1 scenario', () => {
    expect(() =>
      render(MultiScenarioChart, { props: { scenarios: makeScenarios(1) } })
    ).not.toThrow();
  });

  it('no overflow warning with 1 scenario', () => {
    const { container } = render(MultiScenarioChart, { props: { scenarios: makeScenarios(1) } });
    expect(container.querySelector('.overflow-warn')).toBeNull();
  });

});


// ---------------------------------------------------------------------------
// Suite 3: Multiple scenarios
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — multiple scenarios', () => {

  it('renders without crash with 3 scenarios', () => {
    expect(() =>
      render(MultiScenarioChart, { props: { scenarios: makeScenarios(3) } })
    ).not.toThrow();
  });

  it('renders without crash with exactly maxVisible=5 scenarios', () => {
    expect(() =>
      render(MultiScenarioChart, { props: { scenarios: makeScenarios(5) } })
    ).not.toThrow();
  });

  it('overflow warning shown when scenarios.length > maxVisible (default 5)', () => {
    const { container } = render(MultiScenarioChart, {
      props: { scenarios: makeScenarios(7) },
    });
    expect(container.querySelector('.overflow-warn')).toBeInTheDocument();
  });

  it('overflow warning includes total scenario count', () => {
    render(MultiScenarioChart, { props: { scenarios: makeScenarios(7) } });
    expect(screen.getByText(/7/)).toBeInTheDocument();
  });

  it('overflow warning has role=alert', () => {
    const { container } = render(MultiScenarioChart, {
      props: { scenarios: makeScenarios(7) },
    });
    expect(container.querySelector('[role="alert"]')).toBeInTheDocument();
  });

  it('no overflow warning when scenarios.length === maxVisible custom', () => {
    const { container } = render(MultiScenarioChart, {
      props: { scenarios: makeScenarios(3), maxVisible: 3 },
    });
    expect(container.querySelector('.overflow-warn')).toBeNull();
  });

  it('overflow warning appears when scenarios > custom maxVisible=2', () => {
    const { container } = render(MultiScenarioChart, {
      props: { scenarios: makeScenarios(4), maxVisible: 2 },
    });
    expect(container.querySelector('.overflow-warn')).toBeInTheDocument();
  });

});


// ---------------------------------------------------------------------------
// Suite 4: baseline prop
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — baseline prop', () => {

  it('renders without crash when baseline provided', () => {
    expect(() =>
      render(MultiScenarioChart, {
        props: { scenarios: makeScenarios(2), baseline: makeBaseline() },
      })
    ).not.toThrow();
  });

  it('no empty state when baseline provided even with 0 scenarios', () => {
    // baseline alone provides dates → no empty state (allDates from baseline)
    const { container } = render(MultiScenarioChart, {
      props: { scenarios: [], baseline: makeBaseline() },
    });
    // With baseline having dates, allDates.length > 0 → EChartBase shown, not empty state
    expect(container.querySelector('.empty-state')).toBeNull();
  });

});


// ---------------------------------------------------------------------------
// Suite 5: CI ribbons
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — CI ribbons', () => {

  it('renders without crash when ciLowSeries/ciHighSeries provided', () => {
    const sc = {
      ...makeScenario('sc-1'),
      ciLowSeries: [210_000, 228_000, 246_000],
      ciHighSeries: [230_000, 252_000, 274_000],
    };
    expect(() =>
      render(MultiScenarioChart, { props: { scenarios: [sc] } })
    ).not.toThrow();
  });

  it('renders without crash when CI series partially missing (only ciLow)', () => {
    const sc = {
      ...makeScenario('sc-1'),
      ciLowSeries: [210_000, 228_000, 246_000],
      // no ciHighSeries
    };
    expect(() =>
      render(MultiScenarioChart, { props: { scenarios: [sc] } })
    ).not.toThrow();
  });

});


// ---------------------------------------------------------------------------
// Suite 6: kpiLabel prop
// ---------------------------------------------------------------------------
describe('MultiScenarioChart — kpiLabel prop', () => {

  it('chart title contains kpiLabel value', () => {
    render(MultiScenarioChart, {
      props: { scenarios: makeScenarios(1), kpiLabel: 'Продажи' },
    });
    expect(screen.getByText(/Продажи — Сравнение сценариев/)).toBeInTheDocument();
  });

  it('default kpiLabel = «KPI» appears in title', () => {
    render(MultiScenarioChart, { props: { scenarios: makeScenarios(1) } });
    expect(screen.getByText(/KPI — Сравнение сценариев/)).toBeInTheDocument();
  });

  it('custom kpiLabel renders in chart title without crash', () => {
    expect(() =>
      render(MultiScenarioChart, {
        props: { scenarios: makeScenarios(2), kpiLabel: 'GRP' },
      })
    ).not.toThrow();
  });

});
