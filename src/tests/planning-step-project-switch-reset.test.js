/**
 * Сторож находки 1 внешнего аудита (High, 2026-09-13): числа чужого проекта
 * остаются на экране шага «Планирование» после смены проекта.
 *
 * `baselineForecast` присваивался ровно в одном месте (после удачного
 * `econ_scenario`) и никогда не обнулялся, а `PlanningStep` не размонтируется
 * при смене проекта (visibility-навигация в pipeline/+page.svelte). Смена
 * проекта прямо на шаге «Планирование»: `resetPipeline` чистит `modelData`,
 * `decomposeData`, `mediaPlanDetected`, но `baselineForecast` — локальный
 * `$state` компонента — остаётся от прежнего проекта. У нового проекта
 * медиаплана ещё нет → гейт пересчёта не пускает — числа прежнего проекта
 * остаются бессрочно в панели сравнения (INV-50: число на экране обязано
 * соответствовать источнику).
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

const futureDatesA = ['2025-01', '2025-02', '2025-03'];

function decomposeFixture() {
  return {
    decomposition_series: {
      dates: Array.from({ length: 24 }, (_, i) => `2023-${String((i % 12) + 1).padStart(2, '0')}`),
      series: [{ name: 'ТВ', data: Array.from({ length: 24 }, () => 10) }],
    },
    channels: [{ name: 'ТВ', spend: 100, contribution: 40, roi: 0.4 }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockImplementation(async (/** @type {string} */ cmd) => {
    if (cmd === 'project_get_dir') return 'D:/tmp/proj';
    if (cmd === 'project_load_results') throw new Error('нет результатов на диске');
    if (cmd === 'econ_scenario') {
      return {
        status: 'ok',
        predictions: [100, 110, 120],
        predictions_ci_low: [60, 66, 72],
        predictions_ci_high: [140, 154, 168],
        future_dates: futureDatesA,
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

  activeProjectId.set('project-A');
  modelData.set({
    diagnostics: {
      mqs: { score: 70, tier_label: 'Хорошее' },
      metrics: { ratio: 4.2 },
      scaled_params: {},
      decays: {},
    },
    channelParams: null, picklePath: 'x', normalization: null,
  });
  decomposeData.set(decomposeFixture());
  optimizeData.set({
    channels: [{ name: 'ТВ', optimal_spend_money: 600_000, current_spend_money: 500_000 }],
    current_kpi: 300,
  });
  mediaPlanDetected.set({
    n_future_periods: 3,
    channels: { ТВ: [300_000, 300_000, 300_000] },
    period_labels: futureDatesA,
    future_dates: futureDatesA,
    warnings: [],
    granularity: 'month',
    confirmed: true,
    source_hash: 'hash-A',
  });
});

describe('сброс состояния «Планирование» при смене проекта', () => {
  it('базовый прогноз проекта А не остаётся на экране после переключения на проект Б', async () => {
    const { container } = render(PlanningStep);

    // Прогноз проекта А построен и виден в сравнении.
    await waitFor(() => {
      const probe = container.querySelector('[data-testid="echart-probe"]');
      expect(probe?.getAttribute('data-legend') ?? '').toContain('Базовый план');
      expect(container.querySelector('.baseline-summary-card')).toBeTruthy();
    }, { timeout: 4000 });

    // Переключение на проект Б прямо на шаге «Планирование»: resetPipeline
    // чистит общие сторы, у Б своего медиаплана ещё нет.
    modelData.set({
      diagnostics: {
        mqs: { score: 60, tier_label: 'Среднее' },
        metrics: { ratio: 3.1 },
        scaled_params: {},
        decays: {},
      },
      channelParams: null, picklePath: 'y', normalization: null,
    });
    decomposeData.set(decomposeFixture());
    optimizeData.set({
      channels: [{ name: 'ТВ', optimal_spend_money: 400_000, current_spend_money: 350_000 }],
      current_kpi: 200,
    });
    mediaPlanDetected.set(null);
    activeProjectId.set('project-B');

    await waitFor(() => {
      expect(
        container.querySelector('.baseline-summary-card'),
        'карточка базового плана проекта А не обязана держаться на экране проекта Б без медиаплана',
      ).toBeNull();
      const probe = container.querySelector('[data-testid="echart-probe"]');
      expect(
        probe?.getAttribute('data-legend') ?? '',
        'легенда графика не обязана содержать «Базовый план» проекта А на экране проекта Б',
      ).not.toContain('Базовый план');
    }, { timeout: 4000 });
  });
});
