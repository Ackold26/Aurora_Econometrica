/**
 * Сторож графика «{KPI} – Прогноз по сценариям» на шаге «Планирование»
 * (живой прогон владельца 14.09, две находки):
 *
 *   а) карточка не разворачивалась на весь экран и не меняла размер вручную,
 *      хотя у соседних графиков это уже работает (запись c8f4a49b: ExpandableCard
 *      плюс метка data-echart в EChartBase);
 *   б) сравнивать сценарии было негде: линии базового плана и вариантов должны
 *      лежать в ОДНИХ осях, иначе выбирать между вариантами, листая графики по
 *      одному, нельзя – а выбор и есть смысл шага.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';

// ECharts в jsdom холст не поднимает – подменяем EChartBase зондом настройки.
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: Probe } = await import('./EChartOptionProbe.svelte');
  return { default: Probe };
});

import ContinuationChart from '$lib/components/pipeline/ContinuationChart.svelte';

const historical = {
  dates: ['2024-01', '2024-02', '2024-03'],
  actuals: [100, 110, 120],
};

/** @param {string} name @param {number} shift */
const line = (name, shift) => ({
  name,
  dates: ['2024-03', '2024-04', '2024-05'],
  predictions: [120 + shift, 130 + shift, 140 + shift],
  ciLow: [110 + shift, 120 + shift, 130 + shift],
  ciHigh: [130 + shift, 140 + shift, 150 + shift],
});

describe('разворот карточки прогноза (задача 5.2а)', () => {
  it('даёт кнопку «Развернуть» – тем же приёмом, что у соседних графиков', () => {
    const { getByLabelText } = render(ContinuationChart, {
      props: { historical, scenarios: [line('Базовый план', 0)], kpiLabel: 'Доход (₽)' },
    });
    expect(getByLabelText('Развернуть')).toBeTruthy();
  });

  it('несёт заголовок карточки с названием метрики', () => {
    const { getByText } = render(ContinuationChart, {
      props: { historical, scenarios: [line('Базовый план', 0)], kpiLabel: 'Доход (₽)' },
    });
    expect(getByText('Доход (₽) - Прогноз по сценариям')).toBeTruthy();
  });

  it('отдаёт графику метку data-echart – по ней карточка раздаёт высоту в развороте', () => {
    const { container } = render(ContinuationChart, {
      props: { historical, scenarios: [line('Базовый план', 0)], kpiLabel: 'Доход (₽)' },
    });
    expect(container.querySelector('[data-echart]')).toBeTruthy();
  });
});

describe('несколько сценариев в одних осях (задача 5.2б)', () => {
  it('рисует базовый план и оба варианта ОДНИМ графиком', () => {
    const { container } = render(ContinuationChart, {
      props: {
        historical,
        scenarios: [line('Базовый план', 0), line('Вариант 1', 10), line('Вариант 2', -10)],
        kpiLabel: 'Доход (₽)',
        maxScenarios: 6,
      },
    });
    const probes = container.querySelectorAll('[data-testid="echart-probe"]');
    expect(probes, 'поле должно быть одно – сравнивать можно только в общих осях').toHaveLength(1);

    const legend = probes[0].getAttribute('data-legend') ?? '';
    expect(legend).toContain('Базовый план');
    expect(legend).toContain('Вариант 1');
    expect(legend).toContain('Вариант 2');
    expect(legend).toContain('Факт');
  });

  it('НЕ теряет варианты сверх показанных: предупреждает, сколько скрыто', () => {
    const scenarios = Array.from({ length: 4 }, (_, i) => line(`Вариант ${i + 1}`, i));
    const { container, getByRole } = render(ContinuationChart, {
      props: { historical, scenarios, kpiLabel: 'Доход (₽)', maxScenarios: 2 },
    });
    expect(getByRole('alert').textContent).toMatch(/первые 2 из 4 сценариев/);
    const legend = container.querySelector('[data-testid="echart-probe"]')?.getAttribute('data-legend') ?? '';
    expect(legend).toContain('Вариант 2');
    expect(legend).not.toContain('Вариант 3');
  });

  it('при пределе выше числа сценариев предупреждения нет', () => {
    const scenarios = Array.from({ length: 4 }, (_, i) => line(`Вариант ${i + 1}`, i));
    const { queryByRole } = render(ContinuationChart, {
      props: { historical, scenarios, kpiLabel: 'Доход (₽)', maxScenarios: 6 },
    });
    expect(queryByRole('alert')).toBeNull();
  });
});
