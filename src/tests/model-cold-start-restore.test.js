/**
 * G-2 (2026-07-04, живой GUI-прогон): холодный старт готового проекта.
 *
 * Класс дефекта: шов между стором и локальным флагом компонента.
 * restoreProjectResults гидрирует modelData.diagnostics с диска, но блок
 * результатов ModelTrainingStep гейтился на ЛОКАЛЬНЫЙ stepState==='trained',
 * который стартует 'idle' и меняется лишь при живом обучении. Итог: пользователь,
 * открывший сохранённый проект, не видел модель, витрину E1 и историю E3 —
 * петля доверия работала только внутри одной живой сессии после обучения.
 *
 * Контракт фикса: если диагностика восстановлена извне (без обучения) и задача
 * обучения не активна — блок результатов (#model-results-anchor) раскрывается.
 * Юнит на restoreProjectResults этого не ловит (стор гидрируется корректно) —
 * дефект интеграционный, между стором и компонентом.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { modelData, validateData, perChannelInput, unitCosts, analysisMode } from '$lib/project-state.js';
import ModelTrainingStep from '$lib/components/pipeline/ModelTrainingStep.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

// Заглушка графика сходимости — убирает echarts/zrender disposal-шум в jsdom
// (тест проверяет раскрытие блока результатов, не содержимое графиков).
vi.mock('$lib/components/pipeline/ConvergenceDashboard.svelte', async () => ({
  default: (await import('./ConvergenceDashboardStub.svelte')).default,
}));

/** Диагностика в форме results/model-diagnostics.json (усечённая, но валидная). */
function diagnosticsFixture() {
  return {
    mqs: {
      score: 70, raw_score: 95.2, tier: 'good', tier_label: 'Хорошее',
      color: '#3b82f6', thinness_cap: 70, ratio: 2.38,
      components: {
        r_squared: { value: 0.9763, score: 97.6 },
        mape: { value: 6.44, score: 87.1 },
        convergence: { r_hat_max: 1, divergences: 0, score: 100 },
      },
    },
    metrics: {
      r_squared: 0.9763, mape_pct: 6.44, rmse: 27623063.97, r_hat_max: 1,
      divergences: 0, n_observations: 31, n_parameters: 20,
      effective_parameters: 13, ratio: 2.4, ratio_nominal: 1.6,
      mcmc: { chains: 4, draws: 2000, tune: 2000, target_accept: 0.95 },
    },
    checks: {},
    actual_vs_predicted: { actual: [1, 2, 3], predicted: [1.1, 1.9, 3.1], dates: ['2025-01', '2025-02', '2025-03'] },
    per_param_rhat: {},
    engine: 'bayesian',
  };
}

/** invoke-маршрутизатор: спокойные заглушки, задача обучения НЕ активна. */
function mockInvokeIdle() {
  vi.mocked(invoke).mockImplementation(async (cmd) => {
    if (cmd === 'econ_train_progress') return { status: 'idle' };
    if (cmd === 'project_get_dir') return 'C:/fake/project';
    if (cmd === 'econ_backtest') return { status: 'not_found' };
    if (cmd === 'econ_model_history') return { generations: [] };
    return null;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  try { localStorage.clear(); } catch { /* jsdom */ }
  modelData.set({ diagnostics: null, channelParams: null, picklePath: null, normalization: null });
  validateData.set({ result: { columns: [{ name: 'tv_trp', role: 'media' }] }, correlationMatrix: null, columnHistograms: null });
  perChannelInput.set({ tv_trp: 'physical' });
  unitCosts.set({});
  analysisMode.set('roi');
});

describe('G-2 холодный старт: восстановление модели без обучения', () => {
  it('контроль: без диагностики блок результатов скрыт (форма обучения)', async () => {
    mockInvokeIdle();
    const { container } = render(ModelTrainingStep);
    // Дать onMount/effect'ам отработать.
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector('#model-results-anchor')).toBeFalsy();
  });

  it('фикс: восстановленная извне диагностика раскрывает блок результатов', async () => {
    mockInvokeIdle();
    // Симулируем restoreProjectResults: диагностика в сторе ДО монтирования шага.
    modelData.set({
      diagnostics: diagnosticsFixture(),
      channelParams: null,
      picklePath: 'C:/fake/project/models/latest.pkl',
      normalization: null,
    });
    const { container } = render(ModelTrainingStep);
    await waitFor(
      () => { expect(container.querySelector('#model-results-anchor')).toBeTruthy(); },
      { timeout: 2000 },
    );
  });
});
