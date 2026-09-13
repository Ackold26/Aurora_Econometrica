/**
 * Сторож места графика прогноза на шаге «Планирование» (задача 5.2б).
 *
 * Веер «история → прогноз» жил ВНУТРИ секции базового плана и показывался только
 * при подтверждённом медиаплане из файла. Без плана в данных клиент мог создать
 * варианты – и не увидеть ни одного графика, то есть сравнивать было негде.
 * Теперь поле вынесено в свою секцию и появляется, как только есть хотя бы одна
 * линия прогноза: базовый план или вариант.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProjectId,
  modelData,
  decomposeData,
  optimizeData,
  mediaPlanDetected,
} from '$lib/project-state.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: Probe } = await import('./EChartOptionProbe.svelte');
  return { default: Probe };
});

import PlanningStep from '$lib/components/pipeline/PlanningStep.svelte';

const futureDates = ['2025-01', '2025-02', '2025-03'];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockImplementation(async (/** @type {string} */ cmd) => {
    if (cmd === 'project_get_dir') return 'D:/tmp/proj';
    // Восстановление результатов проекта отклоняем: у него свой перехват, он
    // молча выходит и НЕ трогает сторы. Иначе оно затирало бы медиаплан-фикстуру
    // (в живом коде он ставится из results/*.json).
    if (cmd === 'project_load_results') throw new Error('нет результатов на диске');
    if (cmd === 'econ_scenario') {
      return {
        status: 'ok',
        predictions: [100, 110, 120],
        predictions_ci_low: [60, 66, 72],
        predictions_ci_high: [140, 154, 168],
        future_dates: futureDates,
        totals: {
          predicted_kpi: 330,
          total_spend_money: 900_000,
          predicted_kpi_ci_low: 198,
          predicted_kpi_ci_high: 462,
        },
        disclaimers: [],
      };
    }
    return null;
  });

  activeProjectId.set('project-1');
  modelData.set({
    diagnostics: {
      mqs: { score: 70, tier_label: 'Хорошее' },
      metrics: { ratio: 4.2 },
      scaled_params: {},
      decays: {},
    },
    channelParams: null, picklePath: 'x', normalization: null,
  });
  decomposeData.set({
    decomposition_series: {
      dates: Array.from({ length: 24 }, (_, i) => `2023-${String((i % 12) + 1).padStart(2, '0')}`),
      series: [{ name: 'ТВ', data: Array.from({ length: 24 }, () => 10) }],
    },
    channels: [{ name: 'ТВ', spend: 100, contribution: 40, roi: 0.4 }],
  });
  optimizeData.set({
    channels: [{ name: 'ТВ', optimal_spend_money: 600_000, current_spend_money: 500_000 }],
    current_kpi: 300,
  });
  mediaPlanDetected.set({
    n_future_periods: 3,
    channels: { ТВ: [300_000, 300_000, 300_000] },
    period_labels: futureDates,
    future_dates: futureDates,
    warnings: [],
    granularity: 'month',
    confirmed: true,
    source_hash: 'hash-1',
  });
});

describe('место графика прогноза', () => {
  it('поле живёт в своей секции, а не внутри блока базового плана', async () => {
    const { container } = render(PlanningStep);

    await waitFor(() => {
      expect(container.querySelector('.forecast-chart-section [data-testid="echart-probe"]')).toBeTruthy();
    }, { timeout: 4000 });

    expect(
      container.querySelector('.baseline-section [data-testid="echart-probe"]'),
      'внутри блока базового плана графика больше нет – иначе он снова окажется заперт за наличием медиаплана в файле',
    ).toBeNull();
  });

  it('на поле одна пара осей, и базовый план на ней подписан', async () => {
    const { container } = render(PlanningStep);

    await waitFor(() => {
      expect(container.querySelector('[data-testid="echart-probe"]')).toBeTruthy();
    }, { timeout: 4000 });

    const probes = container.querySelectorAll('[data-testid="echart-probe"]');
    expect(probes, 'два поля с одними и теми же линиями – это не сравнение, а дубль').toHaveLength(1);
    expect(probes[0].getAttribute('data-legend') ?? '').toContain('Базовый план');
  });
});
