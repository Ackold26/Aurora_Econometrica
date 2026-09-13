/**
 * s46: поведенческий сторож кнопки «Сообщить о проблеме» в ШАПКЕ мастера
 * (`src/routes/pipeline/+layout.svelte::reportProblemFromHeader`).
 *
 * Находка внешнего аудита 13.09.2026 (повторная проверка): единственное место блока, у
 * которого поведенческой проверки по-прежнему нет — `grep -rln "reportProblemFromHeader"
 * src/tests src/lib/__tests__` не находил ничего. Держится ТОЛЬКО на текстовом стороже
 * `guard_left_position_egress.rs::pipeline_error_screens_and_header_offer_a_way_to_report_a_problem`,
 * который ищет подстроку «обращени» в исходнике и красит одинаково удаление вызова и
 * `return;` первой строкой обработчика (действие мертво, текст цел).
 *
 * Этот файл рендерит НАСТОЯЩИЙ `+layout.svelte` (не изолированную копию разметки — иначе
 * тест и продукт разошлись бы независимо друг от друга) и кликает по кнопке шапки, проверяя
 * то же поведение, что и `feedback-report-button.test.js` для окон ошибок: вызов
 * `open_feedback_form` РОВНО один раз с экраном текущего шага и пустым текстом ошибки (в
 * шапке взять текст ошибки неоткуда — это не окно сбоя).
 *
 * Тяжёлые дочерние компоненты (ProjectSelector, InsightsPanel), не относящиеся к кнопке
 * шапки, в рендер не попадают вовсе: подобран pipelineCurrentStep=1 (Валидация) без
 * результата валидации — на этом шаге ProjectSelector (виден только на шаге 0) и
 * InsightsPanel (скрыт при isObjectiveOverlay) не монтируются, их моки не нужны.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { invoke } from '@tauri-apps/api/core';
import {
  pipelineCurrentStep, pipelineStepMeta, activeProjectId, activeProject,
  validateData, importData, expertMode,
} from '$lib/project-state.js';
import { productType } from '$lib/creative-store.js';
import Layout from '../routes/pipeline/+layout.svelte';

vi.mock('$app/navigation', () => ({
  goto: vi.fn(),
}));

/** Пустой снимок содержимого страницы — сама страница (`children`) кнопке шапки не нужна. */
function emptyChildrenSnippet() {
  return createRawSnippet(() => ({
    render: () => '<div data-testid="children-stub"></div>',
  }));
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockResolvedValue(null);
  productType.set('econometrica');
  pipelineCurrentStep.set(1); // «Валидация» — вне ProjectSelector (шаг 0) и InsightsPanel (objective overlay)
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
  activeProjectId.set(null);
  activeProject.set(null);
  validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
  importData.set({ file: null, columns: null, rows: null });
  expertMode.set(false);
});

describe('Кнопка «Сообщить о проблеме» в шапке мастера — нажатие действительно зовёт open_feedback_form', () => {
  it('вызывает команду ровно один раз с экраном текущего шага и пустым oshibka', async () => {
    render(Layout, { props: { children: emptyChildrenSnippet() } });

    const btn = screen.getByRole('button', { name: /Сообщить о проблеме/ });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('open_feedback_form', { ekran: 'Валидация', oshibka: '' });
    });

    const feedbackCalls = vi.mocked(invoke).mock.calls.filter(([cmd]) => cmd === 'open_feedback_form');
    expect(feedbackCalls).toHaveLength(1);
  });
});
