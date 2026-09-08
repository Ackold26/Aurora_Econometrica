/**
 * Внешний аудит 08.09 (Medium-2): реактивность шага «Декомпозиция» была ОДНОСТОРОННЕЙ.
 *
 * Переход `idle → done` пересчитывался, обратного `done → idle` не было. Компоненты
 * шагов живут в DOM постоянно (routes/pipeline/+page.svelte — переключение видимостью,
 * без `{#key}`), поэтому смена проекта их не перемонтирует и локальное состояние шага
 * не сбрасывается. Открыв проект А с посчитанным разбором и переключившись на проект Б
 * без разбора, пользователь получал: `decomposeData` = null → блок результатов не
 * рисуется (`stepState === 'done' && data`), ветка `idle` не рисуется тоже (состояние
 * осталось `done`) → на экране один заголовок шага. Тот самый пустой экран, ради
 * которого ветку `idle` и заводили.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { decomposeData, modelData, pipelineStepMeta, expertMode } from '$lib/project-state.js';
import DecomposeStep from '$lib/components/pipeline/DecomposeStep.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

// Графики к делу не относятся — важно, какая ВЕТКА шага рисуется.
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

/** Разбор в форме results/decomposition.json (усечённый, но достаточный для отрисовки). */
function decompositionFixture() {
  return {
    status: 'ok',
    baseline_pct: 62.4,
    total_contribution: 12191236278,
    channels: [
      {
        name: 'ТВ бюджет', spend: 1025996024, contribution: 438884506, contribution_pct: 3.6,
        roi: 0.43, efficiency_gap: -38.5, share_of_spend: 42.1, share_of_effect: 3.6,
        category: 'brand_reach', verdict: 'Перенасыщен', verdict_tone: 'bad',
      },
      {
        name: 'Онлайн-видео бюджет', spend: 506593262, contribution: 6388207730, contribution_pct: 52.4,
        roi: 12.61, efficiency_gap: 31.6, share_of_spend: 20.8, share_of_effect: 52.4,
        category: 'performance', verdict: 'Высокоэффективен', verdict_tone: 'good',
      },
    ],
    waterfall: {
      labels: ['База', 'ТВ бюджет', 'Онлайн-видео бюджет', 'Итого'],
      values: [7000000000, 438884506, 6388207730, 12191236278],
      types: ['total', 'positive', 'positive', 'total'],
    },
    time_series: { dates: ['2025-01-31', '2025-02-28'], baseline: [1, 2], channels: {} },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  expertMode.set(false);
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'ready', errorMessage: null },
  ]);
  modelData.set({ diagnostics: { mqs: { score: 70 } }, channelParams: { 'ТВ бюджет': {} }, picklePath: 'x', normalization: null });
  decomposeData.set(decompositionFixture());
});

describe('шаг «Декомпозиция» при смене проекта (Medium-2)', () => {
  it('когда разбор исчезает из стора, шаг возвращается в ветку «ещё не считался», а не показывает пустой экран', async () => {
    const { container, queryByText } = render(DecomposeStep);

    // Исходно: разбор проекта А посчитан — ветки «ещё не считался» на экране нет.
    await waitFor(() => expect(container.querySelector('.decompose-step')).toBeTruthy());
    expect(queryByText(/в этой сессии ещё не считался/)).toBeNull();

    // Смена проекта: loadPipelineForProject делает decomposeData.set(null).
    decomposeData.set(null);

    await waitFor(() => {
      expect(
        queryByText(/в этой сессии ещё не считался/),
        'шаг остался в состоянии «готово» с пустыми данными — на экране один заголовок',
      ).toBeTruthy();
    });
    expect(container.querySelector('.idle-state'), 'ветка idle обязана быть отрисована').toBeTruthy();
  });
});
