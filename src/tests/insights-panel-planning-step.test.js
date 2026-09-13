/**
 * Живой прогон владельца 14.09: на шаге «Планирование» панель подсказок писала
 * «Для этого шага подсказок нет» – единственный шаг мастера, где она молчала,
 * при том что на «Оптимизации» подсказки работают.
 *
 * Сторож привязан к ПОРЯДКУ шагов (id 'planning'), а не к числу: вставят ещё
 * один шаг – маршрутизация сдвинется, и это будет видно здесь.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import {
  PIPELINE_STEPS,
  pipelineCurrentStep,
  importData,
  validateData,
  modelData,
  decomposeData,
  optimizeData,
  mediaPlanDetected,
  mediaPlanProbeStatus,
} from '$lib/project-state.js';
import { planningLiveState } from '$lib/planning-live-state.js';
import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));

const planningIdx = PIPELINE_STEPS.findIndex((s) => s.id === 'planning');

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  importData.set({ file: { name: 'demo.xlsx' }, columns: [{ name: 'Выручка', role: 'kpi' }], rows: 60 });
  validateData.set({
    result: { status: 'ok', columns: [{ name: 'Выручка', role: 'kpi' }, { name: 'ТВ', role: 'media' }] },
    correlationMatrix: null,
    columnHistograms: null,
  });
  modelData.set({
    diagnostics: {
      mqs: { score: 70, tier_label: 'Хорошее' },
      metrics: { r_squared: 0.93, mape_pct: 6.4, n_observations: 60, ratio: 3.9 },
    },
    channelParams: null, picklePath: 'x', normalization: null,
  });
  decomposeData.set({
    decomposition_series: {
      dates: Array.from({ length: 36 }, (_, i) => `2022-${String((i % 12) + 1).padStart(2, '0')}`),
      series: [{ name: 'ТВ', data: Array.from({ length: 36 }, () => 10) }],
    },
    channels: [{ name: 'ТВ', spend: 100, contribution: 40, roi: 0.4 }],
  });
  optimizeData.set({ expected_lift_pct: 3.4, total_budget_money: 1000 });
  mediaPlanDetected.set({ n_future_periods: 12, channels: { ТВ: [1, 1] }, warnings: [], confirmed: true });
  mediaPlanProbeStatus.set('found');
  planningLiveState.set({ baseline: null, variants: [] });
});

describe('панель подсказок на шаге «Планирование»', () => {
  it('не молчит: при широком диапазоне прогноза выдаёт подсказку с числом', async () => {
    planningLiveState.set({
      baseline: { totalKpi: 1000, totalSpend: 500_000, ciLowTotal: 600, ciHighTotal: 1400 },
      variants: [],
    });
    pipelineCurrentStep.set(planningIdx);

    const { container, queryByText, findByText } = render(InsightsPanel, {
      props: { collapsed: false, onToggle: () => {} },
    });

    await waitFor(() => expect(container.querySelector('.panel-body')).toBeTruthy());
    expect(await findByText(/ширина 80% от прогноза/)).toBeTruthy();
    expect(queryByText(/Для этого шага подсказок нет/)).toBeNull();
    expect(container.querySelector('.insight-count')?.textContent).not.toBe('0');
  });

  it('молчит там, где сказать нечего: ни один порог не перейдён – ни одной подсказки', async () => {
    // План найден, горизонт 12 на 36 периодах истории, качество «Хорошее»,
    // прогноз ещё не посчитан, вариантов нет – все пороги ниже своих границ.
    planningLiveState.set({ baseline: null, variants: [] });
    pipelineCurrentStep.set(planningIdx);

    const { container, findByText } = render(InsightsPanel, {
      props: { collapsed: false, onToggle: () => {} },
    });

    await waitFor(() => expect(container.querySelector('.panel-body')).toBeTruthy());
    expect(
      await findByText(/Для этого шага подсказок нет/),
      'панель обязана молчать, когда ни один порог не перейдён, а не печатать шаблон',
    ).toBeTruthy();
  });
});
