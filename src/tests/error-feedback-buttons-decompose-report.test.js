/**
 * s46: кнопка «Сообщить о проблеме» в окне ошибки шагов «Декомпозиция» и «Отчёт».
 * См. error-feedback-buttons-import-validate.test.js — тот же принцип: реальное
 * состояние ошибки через мок invoke, не чтение текста исходника. *
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
  activeProjectId, decomposeData, modelData, optimizeData, pipelineStepMeta, expertMode,
} from '$lib/project-state.js';
import DecomposeStep from '$lib/components/pipeline/DecomposeStep.svelte';
import ReportStep from '$lib/components/pipeline/ReportStep.svelte';

// Графики к делу не относятся (canvas недоступен в jsdom) — тот же приём, что и в
// decompose-step-project-switch.test.js.
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  expertMode.set(false);
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
});

describe('DecomposeStep — окно ошибки после отказа декомпозиции', () => {
  it('econ_decompose отказал → баннер с кнопкой обращения (ekran="Декомпозиция")', async () => {
    modelData.set({ diagnostics: { mqs: { score: 70 } }, channelParams: { 'ТВ бюджет': {} }, picklePath: 'x', normalization: null });
    decomposeData.set(null);
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'project_get_dir') return 'C:/fake/project';
      if (cmd === 'econ_decompose') throw new Error('движок недоступен');
      return null;
    });
    activeProjectId.set('p-test-decompose');

    render(DecomposeStep);

    await waitFor(() => {
      expect(screen.getByText(/движок недоступен/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();

    // Обращение уходит с экраном и текстом ошибки ЭТОГО шага, а не просто
    // «кнопка нарисована» (находка 3 аудита s47).
    await fireEvent.click(screen.getByRole('button', { name: /Сообщить о проблеме/ }));
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
        ekran: 'Декомпозиция',
        oshibka: expect.stringContaining('движок недоступен'),
      });
    });

  });
});

describe('ReportStep — окно ошибки после отказа генерации отчёта', () => {
  it('econ_export_pptx отказал → баннер с кнопкой обращения (ekran="Отчёт")', async () => {
    modelData.set({ diagnostics: { mqs: { score: 70 } }, channelParams: { 'ТВ бюджет': {} }, picklePath: 'x', normalization: null });
    decomposeData.set({ status: 'ok', channels: [], total_contribution: 1000, baseline_pct: 60 });
    optimizeData.set({ status: 'ok', channels: [], expected_lift_pct: 5 });
    activeProjectId.set('p-test-report');
    vi.mocked(invoke).mockImplementation(async (cmd) => {
      if (cmd === 'econ_export_pptx') return { status: 'error', message: 'Сборка PPTX не удалась' };
      return null;
    });

    render(ReportStep);

    const btn = await screen.findByRole('button', { name: /Создать отчёт/ });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(screen.getByText('Сборка PPTX не удалась')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Сообщить о проблеме/ })).toBeInTheDocument();

    // Обращение уходит с экраном и текстом ошибки ЭТОГО шага, а не просто
    // «кнопка нарисована» (находка 3 аудита s47).
    await fireEvent.click(screen.getByRole('button', { name: /Сообщить о проблеме/ }));
    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_feedback_form', {
        ekran: 'Отчёт',
        oshibka: expect.stringContaining('Сборка PPTX не удалась'),
      });
    });

  });
});
