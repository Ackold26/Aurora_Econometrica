/**
 * G-1 (2026-07-04, решение Антона «открывать на последнем шаге»): при открытии
 * сохранённого проекта с результатами reconcileStepMetaFromDisk ведёт
 * pipelineCurrentStep на последний ПРОЙДЕННЫЙ (complete) шаг.
 *
 * Без этого currentStep=0 (Импорт) + monotonic visual invariant PipelineStepper
 * (шаг впереди текущего со статусом complete понижается до ready) → готовая
 * работа выглядит непройденной. Юнит на reconcile-статусы этого не ловил —
 * дефект в позиции курсора, не в статусах шагов.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProject, activeProjectId, pipelineCurrentStep, pipelineStepMeta, resetPipeline,
} from '$lib/project-state.js';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

/** Мок диска: заданные шаги имеют результаты. */
function mockResults({ model = true, decompose = true, optimize = true, validation = false } = {}) {
  vi.mocked(invoke).mockImplementation(async (cmd) => {
    if (cmd === 'project_load_results') {
      return {
        modelDiagnostics: model ? { mqs: { score: 70 } } : null,
        decomposition: decompose ? { time_series: { dates: ['2025-01', '2025-02'] } } : null,
        optimization: optimize ? { channels: [] } : null,
        validation: validation ? { columns: [] } : null,
      };
    }
    if (cmd === 'project_get') return { id: get(activeProjectId) };
    return null;
  });
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  try { localStorage.clear(); } catch { /* jsdom */ }
});

describe('G-1: открытие проекта ведёт на последний пройденный шаг', () => {
  it('завершённый проект (model+decompose+optimize) → currentStep на Оптимизацию (4)', async () => {
    mockResults({ model: true, decompose: true, optimize: true });
    activeProjectId.set('p-g1');
    activeProject.set(/** @type {any} */ ({ id: 'p-g1' }));
    pipelineCurrentStep.set(0); // открытие на Импорте
    resetPipeline('p-g1');
    await new Promise((r) => setTimeout(r, 80)); // async restore → reconcile
    expect(get(pipelineCurrentStep)).toBe(4); // Optimize = последний complete
    const statuses = get(pipelineStepMeta).map((s) => s.status);
    expect(statuses[2]).toBe('complete'); // Model
    expect(statuses[3]).toBe('complete'); // Decompose
    expect(statuses[4]).toBe('complete'); // Optimize
  });

  it('только модель обучена (без decompose/optimize) → currentStep на Модель (2)', async () => {
    mockResults({ model: true, decompose: false, optimize: false });
    activeProjectId.set('p-g1b');
    activeProject.set(/** @type {any} */ ({ id: 'p-g1b' }));
    pipelineCurrentStep.set(0);
    resetPipeline('p-g1b');
    await new Promise((r) => setTimeout(r, 80));
    expect(get(pipelineCurrentStep)).toBe(2); // Model = последний complete
  });

  it('НЕ откатывает назад, если сохранённая позиция дальше последнего complete', async () => {
    mockResults({ model: true, decompose: false, optimize: false });
    // Сохранённая позиция (юзер работал на Декомпозиции) — resetPipeline читает
    // её из localStorage через loadPipelineForProject, не из set() до вызова.
    localStorage.setItem('econ-pipeline-meta-p-g1c', JSON.stringify({
      currentStep: 3,
      steps: [
        { status: 'complete', errorMessage: null }, { status: 'ready', errorMessage: null },
        { status: 'complete', errorMessage: null }, { status: 'ready', errorMessage: null },
        { status: 'locked', errorMessage: null }, { status: 'locked', errorMessage: null },
      ],
    }));
    activeProjectId.set('p-g1c');
    activeProject.set(/** @type {any} */ ({ id: 'p-g1c' }));
    resetPipeline('p-g1c');
    await new Promise((r) => setTimeout(r, 80));
    // lastComplete = 2 (Model) < 3 → НЕ откатываем на 2, оставляем 3.
    expect(get(pipelineCurrentStep)).toBe(3);
  });
});
