/**
 * channel-timeline-click.test.js — ЖИВОЙ компонентный клик-путь drill-чипов (П2-1).
 *
 * Ретест v2.2.0 (2026-07-10, Антон): клики по чипам «Детализация» не раскрывают
 * группы НИ в обычном виде, НИ в fullscreen. Существующий channel-timeline-drill
 * тестирует только ЛОГИКУ planViewSeries (клик-путь компонента был «SKIP» и
 * никогда не существовал) — класс [[feedback_test_asserts_what_agent_claims]].
 *
 * Этот тест монтирует НАСТОЯЩИЙ ChannelTimeline (EChartBase замокан — canvas
 * недоступен в jsdom), кликает чип группы через DOM и проверяет, что мок
 * EChartBase получил НОВЫЙ option с развёрнутыми членами группы.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { flushSync } from 'svelte';

// Мок EChartBase: копим каждый применённый option (проп реактивен — Svelte
// пересоздаёт объект при изменении $derived-цепочки выше).
const appliedOptions = [];
vi.mock('$lib/components/charts/EChartBase.svelte', async () => {
  const { default: MockEChartBase } = await import('./__mocks__/MockEChartBase.svelte');
  return { default: MockEChartBase };
});

import ChannelTimeline from '$lib/components/pipeline/ChannelTimeline.svelte';
import { __getAppliedOptions, __resetAppliedOptions } from './__mocks__/MockEChartBase.svelte';

function fixture() {
  return {
    dates: ['2025-01', '2025-02', '2025-03'],
    series: [
      { name: 'Базовый уровень', role: 'baseline', type: 'baseline', top_group: 'БАЗА', side: 'positive', data: [1000, 1000, 1000] },
      { name: 'Сезонность', role: 'factor', type: 'seasonality', top_group: 'БАЗА', side: 'positive', data: [50, -30, 20] },
      { name: 'Праздники', role: 'factor', type: 'holiday', top_group: 'БАЗА', side: 'positive', data: [10, 0, 5] },
      { name: 'TV', role: 'channel', type: 'media', top_group: 'МЕДИА', side: 'positive', data: [300, 320, 310] },
      { name: 'Digital', role: 'channel', type: 'media', top_group: 'МЕДИА', side: 'positive', data: [200, 210, 190] },
      { name: 'Конкурент TRP', role: 'factor', type: 'signed_competitor', top_group: 'КОНКУРЕНТЫ', side: 'negative', data: [-40, -35, -45] },
    ],
  };
}

/** Число series в последнем применённом option. */
function lastSeriesCount() {
  const opts = __getAppliedOptions();
  const last = opts[opts.length - 1];
  return Array.isArray(last?.series) ? last.series.length : -1;
}

describe('П2-1: живой клик по drill-чипу раскрывает группу (mount + DOM click)', () => {
  beforeEach(() => {
    __resetAppliedOptions();
  });

  it('чипы рендерятся для canonical decomposition_series', async () => {
    const { container } = render(ChannelTimeline, {
      props: { decompositionSeries: fixture(), timeSeries: null, signedFactors: null },
    });
    flushSync();
    const chips = container.querySelectorAll('.drill-chips .chip');
    // «Развернуть всё» + 3 группы (БАЗА/МЕДИА/КОНКУРЕНТЫ); сезонной %-кривой чипа
    // может не быть (seasonalityPctOfBase зависит от формы данных) — не фиксируем.
    expect(chips.length).toBeGreaterThanOrEqual(4);
    const labels = [...chips].map((c) => c.textContent).join(' ');
    expect(labels).toContain('База');
    expect(labels).toContain('Медиа');
  });

  it('клик по чипу МЕДИА → мок EChartBase получает option с членами группы (TV, Digital)', async () => {
    const { container } = render(ChannelTimeline, {
      props: { decompositionSeries: fixture(), timeSeries: null, signedFactors: null },
    });
    flushSync();
    const before = lastSeriesCount();
    expect(before).toBeGreaterThan(0); // initial option применён

    const mediaChip = container.querySelector('.drill-chips .chip[data-drill="МЕДИА"]');
    expect(mediaChip, 'чип МЕДИА должен существовать').toBeTruthy();

    await fireEvent.click(mediaChip);
    flushSync();

    const after = lastSeriesCount();
    // Раскрытие МЕДИА: агрегат (1 серия) заменяется двумя членами (TV+Digital) → серий больше.
    expect(after, `клик по чипу не изменил option (серий было ${before}, стало ${after}) — drill мёртв`).toBeGreaterThan(before);

    const names = (__getAppliedOptions().at(-1)?.series ?? []).map((s) => s.name).join('|');
    expect(names).toContain('TV');
    expect(names).toContain('Digital');
  });

  it('повторный клик сворачивает обратно (toggle)', async () => {
    const { container } = render(ChannelTimeline, {
      props: { decompositionSeries: fixture(), timeSeries: null, signedFactors: null },
    });
    flushSync();
    const chip = container.querySelector('.drill-chips .chip[data-drill="МЕДИА"]');
    await fireEvent.click(chip);
    flushSync();
    const expanded = lastSeriesCount();
    await fireEvent.click(chip);
    flushSync();
    const collapsed = lastSeriesCount();
    expect(collapsed).toBeLessThan(expanded);
  });

  it('«Развернуть всё» разворачивает все группы разом', async () => {
    const { container } = render(ChannelTimeline, {
      props: { decompositionSeries: fixture(), timeSeries: null, signedFactors: null },
    });
    flushSync();
    const before = lastSeriesCount();
    const allChip = container.querySelector('.drill-chips .chip[data-drill="__all__"]');
    expect(allChip).toBeTruthy();
    await fireEvent.click(allChip);
    flushSync();
    const after = lastSeriesCount();
    // 6 членов (3 БАЗА + 2 МЕДИА + 1 КОНКУРЕНТЫ) > 3 агрегатов
    expect(after).toBeGreaterThan(before);
  });
});
