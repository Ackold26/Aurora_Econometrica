/**
 * s46: кнопка «Сообщить о проблеме» в окне ошибки шагов «Оптимизация» и «Модель».
 * См. error-feedback-buttons-import-validate.test.js — тот же принцип.
 *
 * ModelTrainingStep: ConfigPanel и TrainingProgress — тяжёлые самостоятельные
 * компоненты (форма настроек / опрос бэкенда по задаче), их логика не предмет этого
 * теста. Подменяются лёгкими моками (тот же приём, что EChartBase в других тестах
 * шагов), которые воспроизводят ровно тот вызов, который делают настоящие компоненты:
 * onTrainingStarted(taskId) → onError(msg). Цепочка ModelTrainingStep.handleTrainingStarted
 * → activeTaskId/stepState → TrainingProgress.onError → handleError → errorMessage
 * остаётся настоящей. *
 * Находка 3 внешнего аудита s47 (Medium, 2026-09-14): проверки утверждали
 * только ПРИСУТСТВИЕ кнопки. Аудитор подменил `ekran="Оптимизация"` на
 * `"Импорт"` – проверка осталась зелёной, то есть была слепа к тому, что
 * обещает её имя: обращение из «Оптимизации» ушло бы в поддержку с пометкой
 * «Импорт», и разбор пошёл бы не туда. Теперь каждая проверка нажимает кнопку
 * и судит ОБА поля обращения: имя экрана и то, что в причину отказа уходит
 * текст ошибки ЭТОГО шага.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProjectId, decomposeData, modelData, pipelineStepMeta, expertMode, validateData,
} from '$lib/project-state.js';
import OptimizeStep from '$lib/components/pipeline/OptimizeStep.svelte';
import ModelTrainingStep from '$lib/components/pipeline/ModelTrainingStep.svelte';

vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});
vi.mock('$lib/components/ConfigPanel.svelte', async () => {
  const { default: MockConfigPanel } = await import('./__mocks__/MockConfigPanel.svelte');
  return { default: MockConfigPanel };
});
vi.mock('$lib/components/pipeline/TrainingProgress.svelte', async () => {
  const { default: MockTrainingProgress } = await import('./__mocks__/MockTrainingProgress.svelte');
  return { default: MockTrainingProgress };
});

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockResolvedValue(null);
  expertMode.set(false);
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
});

describe('OptimizeStep — окно ошибки после отказа оптимизации', () => {
  it('econ_optimize отказал → баннер с кнопкой обращения (ekran="Оптимизация")', async () => {
    modelData.set({ diagnostics: { mqs: { score: 70 } }, channelParams: { 'ТВ бюджет': {} }, picklePath: 'x', normalization: null });
    decomposeData.set({
      status: 'ok', baseline_pct: 60, total_contribution: 1000,
      channels: [{ name: 'ТВ бюджет', spend: 100, contribution: 50, contribution_pct: 5, roi: 0.5, category: 'brand_reach' }],
      waterfall: { labels: [], values: [], types: [] },
      time_series: { dates: [], baseline: [], channels: {} },
    });
    activeProjectId.set('p-test-optimize');
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'project_get_dir') return 'C:/fake/project';
      if (cmd === 'econ_optimize') throw new Error('решатель не сошёлся');
      return null;
    });

    render(OptimizeStep);

    const btn = await screen.findByRole('button', { name: /Оптимизировать бюджет/ });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(screen.getByText(/решатель не сошёлся/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();

    // Обращение уходит с экраном и текстом ошибки ЭТОГО шага, а не просто
    // «кнопка нарисована» (находка 3 аудита s47).
    await fireEvent.click(screen.getByRole('button', { name: /Сообщить о проблеме/ }));
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
        ekran: 'Оптимизация',
        oshibka: expect.stringContaining('решатель не сошёлся'),
      });
    });

  });
});

describe('ModelTrainingStep — окно ошибки после отказа обучения', () => {
  it('TrainingProgress сообщает об отказе → баннер с кнопкой обращения (ekran="Модель")', async () => {
    validateData.set({ result: { status: 'ok', columns: [] } });

    render(ModelTrainingStep);

    const startBtn = await screen.findByTestId('mock-config-start');
    await fireEvent.click(startBtn);

    await waitFor(() => {
      expect(screen.getByText('Мок: обучение отказало')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();

    // Обращение уходит с экраном и текстом ошибки ЭТОГО шага, а не просто
    // «кнопка нарисована» (находка 3 аудита s47).
    await fireEvent.click(screen.getByRole('button', { name: /Сообщить о проблеме/ }));
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
        ekran: 'Модель',
        oshibka: expect.stringContaining('Мок: обучение отказало'),
      });
    });

  });
});
