/**
 * Аудит s50 (M-1): доля лидера в медиа-вкладе на панели выводов и шаге «Отчёт»
 * округлялась целым (`contribution_pct.toFixed(0)` → «88%») рядом со столбцом
 * «Доля» шага «Декомпозиция», который уже показывал одну десятую («87.5») —
 * расхождение на соседних экранах одного продукта (INV-50: число на экране
 * равно расчёту, подпись – часть числа).
 *
 * Правка: ReportStep.svelte переведён на общий помощник
 * format-numbers.js:formatChannelSharePct (тот же, что DecomposeStep/insights-rules).
 * Три поверхности шага «Отчёт», показывающие ту же долю лидера (87.5%):
 * сопроводительный текст письма (resultsSummary), блок интерпретации
 * (interpretationDecomposition), FAQ (faqItems).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { invoke } from '@tauri-apps/api/core';
import { modelData, decomposeData, optimizeData, activeProjectId } from '$lib/project-state.js';
import ReportStep from '$lib/components/pipeline/ReportStep.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock('@tauri-apps/plugin-opener', () => ({ openPath: vi.fn() }));
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

/** Три канала: 87.5 / 7.5 / 5.0 — те же числа, что в фикстуре движка
 * (test_channel_share_single_source.py:_dec_875), для единой картины
 * фронт/движок на одном примере. */
function channelsFixture() {
  return [
    { name: 'Канал A', spend: 1_000_000, contribution: 875, contribution_pct: 87.5, roi: 1.5, efficiency_gap: 0 },
    { name: 'Канал B', spend: 200_000, contribution: 75, contribution_pct: 7.5, roi: 1.2, efficiency_gap: 0 },
    { name: 'Канал C', spend: 100_000, contribution: 50, contribution_pct: 5.0, roi: 0.8, efficiency_gap: 0 },
  ];
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockResolvedValue(null);
  activeProjectId.set(null); // onMount reload/recompute пропускается — данные уже в store
  modelData.set({
    diagnostics: {
      mqs: { score: 82, tier: 'good' },
      metrics: { r_squared: 0.9, mape_pct: 5.0, r_hat_max: 1.01, divergences: 0, ratio: 5.0 },
    },
    channelParams: { 'Канал A': {} },
    picklePath: 'x',
    normalization: null,
  });
  decomposeData.set({ baseline_pct: 40, channels: channelsFixture() });
  optimizeData.set({ expected_lift_pct: 3.0, total_budget_money: 1_000_000 });
});

describe('ReportStep — доля лидера в медиа-вкладе с одной десятой (аудит s50 M-1)', () => {
  it('сопроводительный текст письма показывает 87.5%, не 88%', async () => {
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Сопроводительный текст для письма/ }));
    const text = screen.getByText(/Главный драйвер/).closest('.cover-content')?.textContent ?? '';
    expect(text).toContain('87.5%');
    expect(text).not.toContain('88%');
  });

  it('блок «Как интерпретировать» показывает 87.5%, не 88%', async () => {
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Как интерпретировать модель и результаты/ }));
    const text = screen.getByText(/Главный медиа-драйвер/).closest('.info-body')?.textContent ?? '';
    expect(text).toContain('87.5%');
    expect(text).not.toContain('88%');
  });

  it('FAQ «Почему топ-канал показал самый большой вклад» показывает 87.5%, не 88%', async () => {
    render(ReportStep);
    await fireEvent.click(screen.getByRole('button', { name: /Часто задаваемые вопросы по этой модели/ }));
    const text = screen.getByText(/самый большой вклад/).closest('.faq-item')?.textContent ?? '';
    expect(text).toContain('87.5%');
    expect(text).not.toContain('88%');
  });
});
