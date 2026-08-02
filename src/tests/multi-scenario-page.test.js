/**
 * MultiScenarioPage component tests - v2.0.0 Phase D.
 *
 * Coverage:
 *   - Empty scenarios → empty state с CTA text
 *   - Single scenario without baseline → «нужно ≥2» message
 *   - Multi scenarios → comparison table renders
 *   - Sortable columns: clicking header toggles sort
 *   - Per-channel breakdown <details> collapsible
 *   - Diff narratives section renders
 *   - Action dropdowns: Export, Accept, Duplicate, Delete
 *   - Outside click closes dropdowns
 *   - onAccept callback fires with correct scenario
 *
 * Note: MultiScenarioChart (ECharts wrapper) is mocked to avoid
 * canvas/async-init issues in jsdom.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import MultiScenarioPage from '$lib/components/pipeline/MultiScenarioPage.svelte';

// Mock MultiScenarioChart to avoid ECharts canvas init in jsdom
vi.mock('$lib/components/pipeline/MultiScenarioChart.svelte', async () => {
  const { default: ChartStub } = await import('./MultiScenarioChartStub.svelte').catch(() => ({
    default: null,
  }));
  if (ChartStub) return { default: ChartStub };
  // Inline minimal stub if file doesn't exist yet
  return {
    default: class {
      constructor() {}
      $destroy() {}
    },
  };
});


// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

/** @param {string} id */
function makeScenario(id, opts = {}) {
  return {
    id,
    name: opts.name ?? `Сценарий ${id}`,
    budget: opts.budget ?? 50_000_000,
    predictedKpi: opts.kpi ?? 240_000,
    ciLow: 220_000,
    ciHigh: 260_000,
    dates: ['2024-01', '2024-02', '2024-03'],
    predictions: [220_000, 240_000, 260_000],
    perChannelAllocation: opts.channels ?? { TV: 0.40, Digital: 0.35, OOH: 0.25 },
  };
}

function makeBaseline() {
  return {
    id: 'baseline',
    name: 'Базовый',
    budget: 50_000_000,
    predictedKpi: 200_000,
    ciLow: 185_000,
    ciHigh: 215_000,
    dates: ['2024-01', '2024-02', '2024-03'],
    predictions: [190_000, 200_000, 210_000],
    perChannelAllocation: { TV: 0.40, Digital: 0.35, OOH: 0.25 },
  };
}


// ---------------------------------------------------------------------------
// Suite 1: Empty / single scenario states
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - empty and single states', () => {

  it('empty scenarios → empty-state element rendered', () => {
    const { container } = render(MultiScenarioPage, { props: { scenarios: [] } });
    expect(container.querySelector('.empty-state')).toBeInTheDocument();
  });

  it('empty state contains CTA text about adding scenarios', () => {
    render(MultiScenarioPage, { props: { scenarios: [] } });
    expect(screen.getByText(/Нет сценариев для сравнения/)).toBeInTheDocument();
  });

  it('empty state has role=status', () => {
    const { container } = render(MultiScenarioPage, { props: { scenarios: [] } });
    expect(container.querySelector('[role="status"]')).toBeInTheDocument();
  });

  it('single scenario without baseline → «нужно ≥2» message', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1')], baseline: null },
    });
    expect(screen.getByText(/≥2/)).toBeInTheDocument();
  });

  it('single scenario without baseline → single-state element, NOT empty-state', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1')], baseline: null },
    });
    expect(container.querySelector('.single-state')).toBeInTheDocument();
    expect(container.querySelector('.empty-state')).toBeNull();
  });

  it('single scenario WITH baseline → shows table (not single-state)', () => {
    const { container } = render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1')],
        baseline: makeBaseline(),
      },
    });
    expect(container.querySelector('.single-state')).toBeNull();
    expect(container.querySelector('.comparison-table')).toBeInTheDocument();
  });

});


// ---------------------------------------------------------------------------
// Suite 2: Comparison table
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - comparison table', () => {

  it('comparison table renders with 2 scenarios', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(container.querySelector('.comparison-table')).toBeInTheDocument();
  });

  it('table contains scenario names as rows', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1', { name: 'Альфа' }), makeScenario('sc-2', { name: 'Бета' })],
      },
    });
    // Use getAllByText - scenario names appear in the table (at least one instance)
    expect(screen.getAllByText('Альфа').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Бета').length).toBeGreaterThan(0);
  });

  it('baseline row shows «базовый» badge', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1')],
        baseline: makeBaseline(),
      },
    });
    expect(screen.getByText('базовый')).toBeInTheDocument();
  });

  it('Δ% column header present when baseline provided', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1')],
        baseline: makeBaseline(),
      },
    });
    // Δ% header should appear
    expect(screen.getByText(/Δ%/)).toBeInTheDocument();
  });

  it('Δ% column NOT present without baseline', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.queryByText(/Δ%/)).toBeNull();
  });

  it('scenario count badge shows in header', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.getByText(/2 сценари/)).toBeInTheDocument();
  });

});


// ---------------------------------------------------------------------------
// Suite 3: Sortable columns
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - sortable columns', () => {

  it('clicking «Бюджет» header does not throw', async () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const budgetHeader = container.querySelector('th.col-budget.sortable');
    expect(budgetHeader).toBeInTheDocument();
    await expect(fireEvent.click(budgetHeader)).resolves.not.toThrow();
  });

  it('clicking «Сценарий» name header twice reverses sort (asc → desc indicator)', async () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const nameHeader = container.querySelector('th.col-name.sortable');
    await fireEvent.click(nameHeader);
    // Clicking a new column sets descending → indicator should be ▼
    expect(nameHeader.textContent).toMatch(/▼/);
    // Click again on same column → ascending ▲
    await fireEvent.click(nameHeader);
    expect(nameHeader.textContent).toMatch(/▲/);
  });

  it('initial sort column (kpi) shows ▼ indicator by default', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const kpiHeader = container.querySelector('th.col-kpi.sortable');
    expect(kpiHeader.textContent).toMatch(/▼/);
  });

});


// ---------------------------------------------------------------------------
// Suite 4: Per-channel breakdown collapsible
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - per-channel breakdown', () => {

  it('breakdown <details> element is present', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(container.querySelector('details.breakdown-block')).toBeInTheDocument();
  });

  it('breakdown is closed by default (open attribute not set)', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const details = container.querySelector('details.breakdown-block');
    expect(details.open).toBe(false);
  });

  it('breakdown summary text contains «Распределение по каналам»', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.getByText(/Распределение по каналам/)).toBeInTheDocument();
  });

  it('channel count badge appears in summary when channels present', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    // scenarios have 3 channels (TV, Digital, OOH)
    expect(screen.getByText(/3 каналов/)).toBeInTheDocument();
  });

  it('clicking summary opens breakdown', async () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const summary = container.querySelector('details.breakdown-block summary');
    await fireEvent.click(summary);
    const details = container.querySelector('details.breakdown-block');
    expect(details.open).toBe(true);
  });

});


// ---------------------------------------------------------------------------
// Suite 5: Diff narratives section
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - diff narratives section', () => {

  it('analysis block is present in DOM', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(container.querySelector('.analysis-block')).toBeInTheDocument();
  });

  it('«Анализ» title rendered in narrative section', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.getByText('Анализ')).toBeInTheDocument();
  });

  it('narrative list rendered when scenarios have KPI data', () => {
    const baseline = makeBaseline();
    const sc = makeScenario('sc-1', { kpi: 260_000 });
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [sc], baseline },
    });
    // generateDiffNarratives produces at least one narrative
    expect(container.querySelector('.narrative-list')).toBeInTheDocument();
  });

});


// ---------------------------------------------------------------------------
// Suite 6: Action dropdowns
// ---------------------------------------------------------------------------
describe('MultiScenarioPage - Export dropdown', () => {

  it('Export button is present', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.getByRole('button', { name: /Экспорт/ })).toBeInTheDocument();
  });

  it('clicking Export button opens dropdown menu', async () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(container.querySelector('[role="menu"]')).toBeInTheDocument();
  });

  it('Export dropdown contains CSV option', async () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(screen.getByText(/CSV/)).toBeInTheDocument();
  });

  it('Export dropdown contains Excel option', async () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(screen.getByText(/Excel/)).toBeInTheDocument();
  });

  // P0.4 (2026-08-03): кнопка PPTX убрана — вела на несуществующую Rust-команду
  // export_scenarios_pptx (её нет в src-tauri/src/), фронт ловил ошибку и
  // подставлял заглушку «PPTX export временно недоступен». Тест перевёрнут:
  // теперь стережёт ОТСУТСТВИЕ обещания, которое продукт не мог выполнить.
  it('Export dropdown does not offer PPTX (no working backend command)', async () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(screen.queryByText(/PPTX/)).not.toBeInTheDocument();
  });

  it('Export button aria-expanded=false initially', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    expect(exportBtn.getAttribute('aria-expanded')).toBe('false');
  });

  it('Export button aria-expanded=true after click', async () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(exportBtn.getAttribute('aria-expanded')).toBe('true');
  });

  it('clicking outside closes the Export dropdown', async () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    expect(container.querySelector('[role="menu"]')).toBeInTheDocument();
    // Simulate outside click via document click event
    await fireEvent.click(document.body);
    expect(container.querySelector('[role="menu"]')).toBeNull();
  });

});


describe('MultiScenarioPage - Accept dropdown', () => {

  it('Accept button NOT rendered when onAccept not provided', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')], onAccept: null },
    });
    expect(screen.queryByRole('button', { name: /Принять сценарий/ })).toBeNull();
  });

  it('Accept button rendered when onAccept provided', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1'), makeScenario('sc-2')],
        onAccept: vi.fn(),
      },
    });
    expect(screen.getByRole('button', { name: /Принять сценарий/ })).toBeInTheDocument();
  });

  it('clicking Accept button opens dropdown with scenario names', async () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [
          makeScenario('sc-1', { name: 'Альфа' }),
          makeScenario('sc-2', { name: 'Бета' }),
        ],
        onAccept: vi.fn(),
      },
    });
    const acceptBtn = screen.getByRole('button', { name: /Принять сценарий/ });
    await fireEvent.click(acceptBtn);
    expect(screen.getAllByText('Альфа').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Бета').length).toBeGreaterThan(0);
  });

  it('onAccept callback fires with correct scenario when dropdown item clicked', async () => {
    const onAccept = vi.fn();
    const sc1 = makeScenario('sc-1', { name: 'Альфа' });
    const sc2 = makeScenario('sc-2', { name: 'Бета' });
    render(MultiScenarioPage, {
      props: { scenarios: [sc1, sc2], onAccept },
    });
    const acceptBtn = screen.getByRole('button', { name: /Принять сценарий/ });
    await fireEvent.click(acceptBtn);
    // Find and click the «Альфа» menu item
    const menuItems = screen.getAllByText('Альфа');
    // Last one should be inside the dropdown menu
    await fireEvent.click(menuItems[menuItems.length - 1]);
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onAccept.mock.calls[0][0].id).toBe('sc-1');
  });

});


describe('MultiScenarioPage - Duplicate and Delete dropdowns', () => {

  it('Duplicate button NOT rendered when onDuplicate not provided', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.queryByRole('button', { name: /Дублировать/ })).toBeNull();
  });

  it('Duplicate button rendered when onDuplicate provided', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1'), makeScenario('sc-2')],
        onDuplicate: vi.fn(),
      },
    });
    expect(screen.getByRole('button', { name: /Дублировать/ })).toBeInTheDocument();
  });

  it('Delete button NOT rendered when onDelete not provided', () => {
    render(MultiScenarioPage, {
      props: { scenarios: [makeScenario('sc-1'), makeScenario('sc-2')] },
    });
    expect(screen.queryByRole('button', { name: /Удалить/ })).toBeNull();
  });

  it('Delete button rendered when onDelete provided', () => {
    render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1'), makeScenario('sc-2')],
        onDelete: vi.fn(),
      },
    });
    expect(screen.getByRole('button', { name: /Удалить/ })).toBeInTheDocument();
  });

  it('opening Export closes other open dropdowns', async () => {
    const { container } = render(MultiScenarioPage, {
      props: {
        scenarios: [makeScenario('sc-1'), makeScenario('sc-2')],
        onAccept: vi.fn(),
      },
    });
    // Open Accept first
    const acceptBtn = screen.getByRole('button', { name: /Принять сценарий/ });
    await fireEvent.click(acceptBtn);
    const menus1 = container.querySelectorAll('[role="menu"]');
    expect(menus1.length).toBe(1);
    // Now click Export - should close Accept and open Export
    const exportBtn = screen.getByRole('button', { name: /Экспорт/ });
    await fireEvent.click(exportBtn);
    const menus2 = container.querySelectorAll('[role="menu"]');
    // Only one menu at a time
    expect(menus2.length).toBe(1);
    expect(screen.getByText(/CSV/)).toBeInTheDocument();
  });

});
