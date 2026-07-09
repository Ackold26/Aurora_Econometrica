/**
 * pipeline-migration.test.js
 *
 * Тесты скелета 7-го шага (planning) в пайплайне:
 * 1. Смоук: PIPELINE_STEPS содержит 7 элементов в правильном порядке.
 * 2. Миграция 6→7: 6-элементный localStorage → 7 элементов, currentStep ремапится (A10).
 * 3. Идемпотентность: 7-элементный вход не изменяется.
 * 4. Миграция currentStep != 5: не меняется.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { PIPELINE_STEPS, loadPipelineMeta } from '$lib/project-state.js';

const META_KEY = 'econ-pipeline-meta';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* jsdom */ }
});

describe('Смоук: PIPELINE_STEPS (7 шагов)', () => {
  it('содержит 7 шагов', () => {
    expect(PIPELINE_STEPS.length).toBe(7);
  });

  it('порядок id шагов верный', () => {
    const ids = PIPELINE_STEPS.map(s => s.id);
    expect(ids).toEqual(['import', 'validate', 'model', 'decompose', 'optimize', 'planning', 'report']);
  });

  it('planning стоит на позиции 5', () => {
    expect(PIPELINE_STEPS[5].id).toBe('planning');
  });

  it('report стоит на позиции 6', () => {
    expect(PIPELINE_STEPS[6].id).toBe('report');
  });
});

describe('Миграция 6→7: вставка planning, ремап currentStep', () => {
  it('вставляет planning[5]=locked, report перемещается на [6], currentStep 5→6 (A10)', () => {
    const legacy6 = {
      currentStep: 5, // старый Report
      steps: [
        { status: 'complete', errorMessage: null },  // import
        { status: 'complete', errorMessage: null },  // validate
        { status: 'complete', errorMessage: null },  // model
        { status: 'complete', errorMessage: null },  // decompose
        { status: 'complete', errorMessage: null },  // optimize
        { status: 'ready',    errorMessage: null },  // report (старый индекс 5)
      ],
    };
    localStorage.setItem(META_KEY, JSON.stringify(legacy6));

    const result = loadPipelineMeta(null);

    expect(result.steps.length).toBe(7);
    // Шаги 0-4 не изменились
    expect(result.steps[0].status).toBe('complete');
    expect(result.steps[1].status).toBe('complete');
    expect(result.steps[2].status).toBe('complete');
    expect(result.steps[3].status).toBe('complete');
    expect(result.steps[4].status).toBe('complete');
    // Planning вставлен как locked
    expect(result.steps[5].status).toBe('locked');
    // Report переехал с 5 на 6 со своим статусом
    expect(result.steps[6].status).toBe('ready');
    // A10: currentStep 5 (старый Report) ремапнулся в 6 (новый Report)
    expect(result.currentStep).toBe(6);
  });
});

describe('Идемпотентность: 7-элементный вход не изменяется', () => {
  it('7 шагов с currentStep=6 возвращается как есть', () => {
    const already7 = {
      currentStep: 6,
      steps: [
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'locked',   errorMessage: null },
        { status: 'ready',    errorMessage: null },
      ],
    };
    localStorage.setItem(META_KEY, JSON.stringify(already7));

    const result = loadPipelineMeta(null);

    expect(result.steps.length).toBe(7);
    expect(result.currentStep).toBe(6);
    expect(result.steps[5].status).toBe('locked');
    expect(result.steps[6].status).toBe('ready');
  });
});

describe('Миграция currentStep != 5 — не меняется', () => {
  it('currentStep=4 (Optimize) не ремапится при миграции 6→7', () => {
    const legacy6 = {
      currentStep: 4, // пользователь на Оптимизации
      steps: [
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'complete', errorMessage: null },
        { status: 'locked',   errorMessage: null },
      ],
    };
    localStorage.setItem(META_KEY, JSON.stringify(legacy6));

    const result = loadPipelineMeta(null);

    expect(result.steps.length).toBe(7);
    // currentStep остаётся 4 — не трогаем
    expect(result.currentStep).toBe(4);
  });

  it('currentStep=0 (Import) не ремапится при миграции 6→7', () => {
    const legacy6 = {
      currentStep: 0,
      steps: [
        { status: 'ready',  errorMessage: null },
        { status: 'locked', errorMessage: null },
        { status: 'locked', errorMessage: null },
        { status: 'locked', errorMessage: null },
        { status: 'locked', errorMessage: null },
        { status: 'locked', errorMessage: null },
      ],
    };
    localStorage.setItem(META_KEY, JSON.stringify(legacy6));

    const result = loadPipelineMeta(null);

    expect(result.steps.length).toBe(7);
    expect(result.currentStep).toBe(0);
  });
});
