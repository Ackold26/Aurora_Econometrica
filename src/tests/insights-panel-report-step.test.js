/**
 * Живой прогон 08.09 (ТЕКСТ-1): на шаге «Отчёт» полностью посчитанного проекта панель
 * подсказок писала «Загрузите данные для получения рекомендаций», счётчик 0 — продукт
 * утверждал о себе то, чего нет.
 *
 * Корень: сводка отчёта висела на индексе шага 5, а после того как между «Оптимизацией»
 * и «Отчётом» встал шаг «Планирование» (миграция мастера 6→7), индекс 5 стал
 * Планированием, Отчёт — 6, и панель на Отчёте проваливалась в ветку «нет правил».
 * Сторож привязан к ПОРЯДКУ шагов, а не к числу: вставят ещё один шаг — упадёт снова.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  PIPELINE_STEPS,
  pipelineCurrentStep,
  importData,
  validateData,
  modelData,
  decomposeData,
  optimizeData,
} from '$lib/project-state.js';
import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));

/** Диагностика посчитанной модели (форма results/model-diagnostics.json). */
function diagnosticsFixture() {
  return {
    mqs: {
      score: 70, raw_score: 95.2, tier: 'good', tier_label: 'Хорошее',
      color: '#3b82f6', thinness_cap: 70, ratio: 3.9,
      components: {},
    },
    metrics: {
      r_squared: 0.936, mape_pct: 6.44, n_observations: 60, n_parameters: 20,
      effective_parameters: 15, ratio: 3.9,
    },
    checks: {},
    engine: 'bayesian',
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  importData.set({ file: { name: 'demo.xlsx' }, columns: [{ name: 'Выручка', role: 'kpi' }], rows: 60 });
  validateData.set({
    result: { status: 'ok', columns: [{ name: 'Выручка', role: 'kpi' }, { name: 'ТВ', role: 'media' }] },
    correlationMatrix: null,
    columnHistograms: null,
  });
  modelData.set({ diagnostics: diagnosticsFixture(), channelParams: { 'ТВ': {} }, picklePath: 'x', normalization: null });
  decomposeData.set({
    baseline_pct: 62.4,
    channels: [{ name: 'ТВ', spend: 100, contribution: 40, contribution_pct: 40, roi: 0.4, efficiency_gap: -38.5 }],
  });
  optimizeData.set({ expected_lift_pct: 3.4, total_budget_money: 1000 });
});

describe('панель подсказок на шаге «Отчёт» (ТЕКСТ-1)', () => {
  it('на посчитанном проекте не советует загрузить данные и показывает сводку', async () => {
    const reportIdx = PIPELINE_STEPS.findIndex((s) => s.id === 'report');
    pipelineCurrentStep.set(reportIdx);

    const { container, queryByText } = render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });

    await waitFor(() => expect(container.querySelector('.panel-body')).toBeTruthy());
    expect(
      queryByText(/Загрузите данные для получения рекомендаций/),
      'данные загружены и посчитаны — совет загрузить их продукт давать не вправе',
    ).toBeNull();
    expect(
      container.querySelector('.insight-count')?.textContent,
      'счётчик подсказок на полностью посчитанном проекте не может быть нулём',
    ).not.toBe('0');
  });

  it('на шаге «Планирование» панель молчит нейтрально, а не советует загрузить данные', async () => {
    const planningIdx = PIPELINE_STEPS.findIndex((s) => s.id === 'planning');
    pipelineCurrentStep.set(planningIdx);

    const { queryByText } = render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });

    await waitFor(() => expect(get(pipelineCurrentStep)).toBe(planningIdx));
    expect(queryByText(/Загрузите данные для получения рекомендаций/)).toBeNull();
  });
});
