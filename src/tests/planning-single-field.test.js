/**
 * Сторож «поле сравнения одно» (задача 5.2б).
 *
 * На шаге «Планирование» одни и те же линии рисовались дважды: веер история →
 * прогноз в секции базового плана и второе поле внутри таблицы сравнения. Второе
 * поле шагу не нужно: сравнивать сценарии надо в одних осях, а не в двух похожих.
 * Поэтому MultiScenarioPage умеет НЕ рисовать своего графика (showChart={false}),
 * и шаг этим пользуется; отдельная страница сравнения – рисует, там поле своё.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('$lib/components/pipeline/MultiScenarioChart.svelte', async () => {
  const { default: ChartStub } = await import('./MultiScenarioChartStub.svelte');
  return { default: ChartStub };
});

import MultiScenarioPage from '$lib/components/pipeline/MultiScenarioPage.svelte';

/** @param {string} id @param {number} kpi */
const scenario = (id, kpi) => ({
  id,
  name: `Вариант ${id}`,
  budget: 1_000_000,
  predictedKpi: kpi,
  ciLow: kpi * 0.9,
  ciHigh: kpi * 1.1,
  perChannelAllocation: { ТВ: 600_000, Диджитал: 400_000 },
  dates: ['2024-04', '2024-05'],
  predictions: [kpi / 2, kpi / 2],
});

const baseline = {
  id: 'baseline',
  name: 'Базовый план',
  budget: 900_000,
  predictedKpi: 900,
  ciLow: 850,
  ciHigh: 950,
  perChannelAllocation: { ТВ: 500_000, Диджитал: 400_000 },
  dates: ['2024-04', '2024-05'],
  predictions: [450, 450],
};

describe('MultiScenarioPage – своё поле графика выключается', () => {
  it('по умолчанию рисует своё поле (страница сравнения на нём и держится)', () => {
    const { container } = render(MultiScenarioPage, {
      props: { scenarios: [scenario('a', 1000), scenario('b', 1100)], kpiLabel: 'Доход (₽)' },
    });
    expect(container.querySelector('[data-testid="multi-scenario-chart-stub"]')).toBeTruthy();
  });

  it('при showChart={false} поля не рисует, а таблицу оставляет', () => {
    const { container } = render(MultiScenarioPage, {
      props: {
        scenarios: [scenario('a', 1000), scenario('b', 1100)],
        showChart: false,
        kpiLabel: 'Доход (₽)',
      },
    });
    expect(
      container.querySelector('[data-testid="multi-scenario-chart-stub"]'),
      'второе поле с теми же линиями шагу «Планирование» не нужно',
    ).toBeNull();
    expect(container.querySelector('.comparison-table')).toBeTruthy();
  });
});

describe('MultiScenarioPage – базовый план как опорный сценарий', () => {
  it('с базовым планом сравнивает даже ОДИН вариант и даёт колонку Δ%', () => {
    const { container, queryByText } = render(MultiScenarioPage, {
      props: {
        scenarios: [scenario('a', 1000)],
        baseline,
        showChart: false,
        kpiLabel: 'Доход (₽)',
      },
    });
    expect(
      queryByText(/Нужно ≥2 сценария для сравнения/),
      'базовый план – полноценная вторая линия сравнения',
    ).toBeNull();
    expect(container.querySelector('.col-uplift'), 'колонка Δ% появляется только при базовом плане').toBeTruthy();
    expect(container.querySelector('.baseline-row')).toBeTruthy();
  });

  it('без базового плана один вариант сравнивать не с чем – так и говорит', () => {
    const { queryByText, container } = render(MultiScenarioPage, {
      props: { scenarios: [scenario('a', 1000)], baseline: null, showChart: false, kpiLabel: 'Доход (₽)' },
    });
    expect(queryByText(/Нужно ≥2 сценария для сравнения/)).toBeTruthy();
    expect(container.querySelector('.col-uplift')).toBeNull();
  });
});
