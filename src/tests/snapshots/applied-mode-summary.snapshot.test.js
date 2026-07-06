/**
 * AppliedModeSummary semantic-queries regression - H-17 (Партия 5).
 *
 * Заменяет full HTML blob snapshots на behavioural assertions через
 * @testing-library/svelte queries. Audit F-02 / F-11 identified prior
 * snapshot approach как fragile rubber-stamp pattern: любая CSS-change
 * меняет svelte-* hash classes → все 6 snapshots break → developer
 * runs --update-snapshots without real review → regression net useless.
 *
 * Semantic approach:
 * - getByRole / getByText / getByTestId queries assert behavioural contracts
 * - Decoupled от svelte content-hash classes
 * - Поломка теста = real regression, not CSS-cosmetic change
 *
 * Same 6 cases coverage:
 *   1. ROI mode with 4 channels (1 physical unconverted)
 *   2. ROI mode with TRPs converted (unit_cost set)
 *   3. Effectiveness mode
 *   4. Mixed mode (Expert)
 *   5. Empty channels (placeholder)
 *   6. ROI with no excluded
 *
 * File name kept (`.snapshot.test.js`) для consistency с tracker docs;
 * физически уже не snapshot. .snap file будет удалён.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import AppliedModeSummary from '$lib/components/pipeline/AppliedModeSummary.svelte';
import { analysisMode, expertMode, unitCosts, unitCostInflation } from '$lib/project-state.js';
import { patternsReady } from '$lib/services/classifier-patterns.js';


function realisticChannels() {
  return [
    { name: 'OLV Бюджет', detectedType: 'monetary' },
    { name: 'Banners Бюджет', detectedType: 'monetary' },
    { name: 'Social Бюджет', detectedType: 'monetary' },
    { name: 'TRPs бренд', detectedType: 'physical' },
  ];
}

function excludedSample() {
  return ['Retail Media бюджет', 'Радио в руб.', 'Пресса в руб.', 'ООН в руб.'];
}

function channelSumsSample() {
  return {
    'OLV Бюджет': 50000000,
    'Banners Бюджет': 30000000,
    'Social Бюджет': 15000000,
    'TRPs бренд': 1500,
  };
}


beforeEach(() => {
  analysisMode.set('roi');
  expertMode.set(false);
  unitCosts.set({});
  unitCostInflation.set({});
  patternsReady.set(true);
});


describe('AppliedModeSummary - semantic regression (H-17)', () => {
  it('case 1: ROI mode с 1 physical TRP unconverted → incompat banner + uc-editor', () => {
    const { getByTestId, getByText, queryByText, container } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });

    // Header reflects ROI mode - root <aside> с aria-label.
    expect(container.querySelector('aside[aria-label="Применённый режим анализа"]')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Все каналы будут поданы в модель как ₽/i })).toBeInTheDocument();
    // mode-badge ROI режим (use queryAll because text может встречаться в badge + kicker)
    expect(container.querySelector('.mode-badge--roi')).toBeInTheDocument();
    // Incompat warning visible (1 physical unconverted)
    const banner = getByTestId('incompat-banner');
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain('1');
    // uc-inputs panel rendered с editor для TRP канала
    expect(getByTestId('uc-inputs')).toBeInTheDocument();
    const editor = within(getByTestId('uc-inputs')).getByTestId('uc-editor');
    expect(editor.getAttribute('data-channel')).toBe('TRPs бренд');
    // Channel list: 4 items, TRP отмечен incompatible
    const list = screen.getByRole('list', { name: /Список каналов/i });
    const items = within(list).getAllByRole('listitem');
    expect(items.length).toBe(4);
    const trpItem = items.find((li) => li.textContent?.includes('TRPs бренд'));
    expect(trpItem?.classList.contains('incompatible')).toBe(true);
    // Excluded toggle с count 4
    expect(getByTestId('excluded-toggle').textContent).toContain('4');
    // CTA «Управлять вручную» (Expert не активен)
    expect(getByText(/Управлять вручную/)).toBeInTheDocument();
    // Skeleton не показывается (patternsReady=true)
    expect(queryByText(/Подгружаем правила/)).toBeNull();
  });

  it('case 2: ROI + TRP converted (unit_cost set) → no banner, converted state', () => {
    unitCosts.set({ 'TRPs бренд': 25000 });
    const { getByTestId, queryByTestId } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });

    // Incompat banner отсутствует
    expect(queryByTestId('incompat-banner')).toBeNull();
    // uc-editor has --converted class
    const editor = getByTestId('uc-editor');
    expect(editor.classList.contains('uc-row--converted')).toBe(true);
    // Channel list: TRP item теперь `converted`
    const list = screen.getByRole('list', { name: /Список каналов/i });
    const trpItem = within(list)
      .getAllByRole('listitem')
      .find((li) => li.textContent?.includes('TRPs бренд'));
    expect(trpItem?.classList.contains('converted')).toBe(true);
    // Channel metric содержит «конвертация в ₽»
    expect(trpItem?.textContent).toMatch(/конвертация в ₽/);
  });

  it('case 3: Effectiveness mode → physical-metric header, no uc-inputs', () => {
    analysisMode.set('effectiveness');
    const { queryByTestId } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });

    expect(screen.getByRole('heading', { name: /физические метрики/i })).toBeInTheDocument();
    expect(screen.getByText(/Эффективность/)).toBeInTheDocument();
    expect(queryByTestId('incompat-banner')).toBeNull();
    expect(queryByTestId('uc-inputs')).toBeNull();
    // CTA «Управлять вручную» доступна (NOT expertMode)
    expect(screen.getByText(/Управлять вручную/)).toBeInTheDocument();
  });

  it('case 4: Mixed + Expert mode → expert note, no CTA button', () => {
    analysisMode.set('mixed');
    expertMode.set(true);
    const { queryByRole } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });

    expect(screen.getByRole('heading', { name: /смешанном режиме/i })).toBeInTheDocument();
    expect(screen.getByText(/Смешанный/)).toBeInTheDocument();
    // CTA hidden когда expert mode active
    expect(queryByRole('button', { name: /Управлять вручную/i })).toBeNull();
    // Expert note instead
    expect(screen.getByText(/Поканальный выбор единиц/)).toBeInTheDocument();
  });

  it('case 5: Empty channels → EmptyState placeholder', () => {
    const { getByTestId, queryByRole } = render(AppliedModeSummary, {
      props: { channels: [], channelSums: {}, excludedChannelNames: [] },
    });

    // H-10a: EmptyState rendered
    expect(getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText(/Каналы не определены/)).toBeInTheDocument();
    expect(queryByRole('list', { name: /Список каналов/i })).toBeNull();
  });

  it('case 6: ROI, 2 monetary, no excluded → no incompat banner, no excluded toggle', () => {
    const { getByTestId, queryByTestId } = render(AppliedModeSummary, {
      props: {
        channels: [
          { name: 'TV', detectedType: 'monetary' },
          { name: 'OOH', detectedType: 'monetary' },
        ],
        channelSums: { TV: 10000000, OOH: 5000000 },
        excludedChannelNames: [],
      },
    });

    expect(getByTestId('channel-counts').textContent).toContain('2');
    expect(queryByTestId('excluded-toggle')).toBeNull();
    expect(queryByTestId('incompat-banner')).toBeNull();
    const list = screen.getByRole('list', { name: /Список каналов/i });
    const items = within(list).getAllByRole('listitem');
    expect(items.length).toBe(2);
    items.forEach((li) => {
      expect(li.textContent).toMatch(/спенд в ₽/);
    });
  });
});
