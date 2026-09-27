/**
 * s50 (27.09.2026): доля канала на экране «Декомпозиция» в режиме «Эффективность».
 *
 * share_of_effect от движка УЖЕ в процентах (decomposer.py: contribution_pct =
 * round(... * 100, 1), share_of_effect = contribution_pct). Экран умножал его на 100
 * ещё раз – «8750.0%» вместо «87.5%», – а пороги цвета (0.20 / 0.05) были рассчитаны
 * на долю, не на проценты: «хорошим» оказывался любой канал. Плюс карточка
 * «Что мы видим» печатала долю лидера целым («88%»), тогда как строка таблицы
 * и отчёт показывают 87.5.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import {
  decomposeData, modelData, pipelineStepMeta, expertMode, derivedMode, kpiKind,
} from '$lib/project-state.js';
import DecomposeStep from '$lib/components/pipeline/DecomposeStep.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

/** Разбор в форме results/decomposition.json: доли 87.5 / 7.5 / 5.0, разрывы в пределах ±10 пп. */
function decompositionFixture() {
  const ch = (/** @type {string} */ name, /** @type {number} */ contribution, /** @type {number} */ pct) => ({
    name, spend: 100_000_000, contribution, contribution_pct: pct, share_of_effect: pct,
    share_of_spend: pct, efficiency_gap: 0, roi: 1.2, category: 'mixed',
    verdict: 'Эффективен', verdict_tone: 'good',
  });
  return {
    status: 'ok',
    baseline_pct: 40.0,
    channels: [
      ch('Канал A', 875_000_000, 87.5),
      ch('Канал B', 75_000_000, 7.5),
      ch('Канал C', 50_000_000, 5.0),
    ],
    waterfall: {
      labels: ['База', 'Канал A', 'Канал B', 'Канал C', 'Итого'],
      values: [700_000_000, 875_000_000, 75_000_000, 50_000_000, 1_700_000_000],
      types: ['total', 'positive', 'positive', 'positive', 'total'],
    },
    time_series: { dates: ['2025-01-31', '2025-02-28'], baseline: [1, 2], channels: {} },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  expertMode.set(false);
  kpiKind.set('monetary');
  derivedMode.set('effectiveness');
  pipelineStepMeta.set([
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'complete', errorMessage: null },
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'ready', errorMessage: null },
  ]);
  modelData.set({ diagnostics: { mqs: { score: 70 } }, channelParams: {}, picklePath: 'x', normalization: null });
  decomposeData.set(decompositionFixture());
});

/** Ячейка метрики строки канала (4-й столбец таблицы: «Доля %» в режиме «Эффективность»). */
function metricCell(/** @type {HTMLElement} */ container, /** @type {string} */ name) {
  const row = [...container.querySelectorAll('tbody tr')]
    .find((tr) => tr.querySelector('.ch-name')?.textContent?.includes(name));
  expect(row, `строка канала ${name} не найдена`).toBeTruthy();
  return /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (row).querySelectorAll('td')[3]);
}

describe('доля канала на экране «Декомпозиция» (s50)', () => {
  it('share_of_effect 87.5 показывается как «87.5%», а не «8750.0%»', async () => {
    const { container } = render(DecomposeStep);
    await waitFor(() => expect(container.querySelector('tbody tr')).toBeTruthy());

    expect(metricCell(container, 'Канал A').textContent?.trim()).toBe('87.5%');
    expect(metricCell(container, 'Канал B').textContent?.trim()).toBe('7.5%');
    expect(metricCell(container, 'Канал C').textContent?.trim()).toBe('5.0%');
    expect(container.textContent).not.toContain('8750');
  });

  it('цвет «хороший» только при доле выше 20%, «средний» – выше 5%', async () => {
    const { container } = render(DecomposeStep);
    await waitFor(() => expect(container.querySelector('tbody tr')).toBeTruthy());

    expect(metricCell(container, 'Канал A').classList.contains('roi-good')).toBe(true);
    const b = metricCell(container, 'Канал B');
    expect(b.classList.contains('roi-good'), '7.5% – не «хороший»').toBe(false);
    expect(b.classList.contains('roi-mid')).toBe(true);
    expect(metricCell(container, 'Канал C').classList.contains('roi-bad')).toBe(true);
  });

  it('фолбэк без готовой доли: вклад от суммы ВСЕХ каналов, в процентах', async () => {
    const fx = decompositionFixture();
    for (const c of fx.channels) {
      delete (/** @type {any} */ (c)).share_of_effect;
      delete (/** @type {any} */ (c)).contribution_pct;
    }
    decomposeData.set(fx);
    const { container } = render(DecomposeStep);
    await waitFor(() => expect(container.querySelector('tbody tr')).toBeTruthy());

    expect(metricCell(container, 'Канал A').textContent?.trim()).toBe('87.5%');
    expect(metricCell(container, 'Канал A').classList.contains('roi-good')).toBe(true);
  });

  it('карточка «Что мы видим» называет долю лидера с одной десятой – как строка таблицы', async () => {
    const { findByText } = render(DecomposeStep);
    expect(await findByText(/Канал A даёт 87\.5% медиа-вклада/)).toBeTruthy();
  });
});
