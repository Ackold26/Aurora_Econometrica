/**
 * AppliedModeSummary component tests — v2.0.0.
 *
 * Tests:
 *   - Header text «Все каналы в ₽» for roi / «физические метрики» for effectiveness
 *   - Channel list renders correct count
 *   - CTA «Управлять вручную» visible when NOT expertMode
 *   - CTA hidden when expertMode=true (expert active note shows instead)
 *   - CTA click sets expertMode store = true
 *   - Empty channels list renders without error (placeholder shown)
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import AppliedModeSummary from '$lib/components/pipeline/AppliedModeSummary.svelte';
import {
  analysisMode, expertMode, unitCosts, unitCostInflation,
  unitCostInputMode, budgetInputs,
} from '$lib/project-state.js';


// Reset stores before each test
beforeEach(() => {
  analysisMode.set('roi');
  expertMode.set(false);
  unitCosts.set({});
  unitCostInflation.set({});
  // Phase 1.3 — reset new persistence stores чтобы избежать state leakage
  unitCostInputMode.set({});
  budgetInputs.set({});
});

/** Sample channel list */
function makeChannels() {
  return [
    { name: 'TV', detectedType: 'monetary' },
    { name: 'Digital', detectedType: 'physical' },
    { name: 'OOH', detectedType: 'monetary' },
  ];
}


describe('AppliedModeSummary', () => {

  // ─── Header text by mode ─────────────────────────────────────────────────

  it('renders «Все каналы будут поданы в модель как ₽» when analysisMode=roi', () => {
    analysisMode.set('roi');
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.getByText(/Все каналы будут поданы в модель как ₽/)).toBeInTheDocument();
  });

  it('renders «Все каналы будут поданы в модель как физические метрики» when analysisMode=effectiveness', () => {
    analysisMode.set('effectiveness');
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.getByText(/физические метрики/)).toBeInTheDocument();
  });

  it('renders «смешанном режиме» header when analysisMode=mixed', () => {
    analysisMode.set('mixed');
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.getByText(/смешанном режиме/)).toBeInTheDocument();
  });

  // ─── Mode badge ──────────────────────────────────────────────────────────

  it('shows ROI режим badge when analysisMode=roi', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, { props: { channels: [] } });
    const badge = container.querySelector('.mode-badge--roi');
    expect(badge).toBeInTheDocument();
    expect(badge?.textContent?.trim()).toBe('ROI режим');
  });

  it('shows Эффективность badge when analysisMode=effectiveness', () => {
    analysisMode.set('effectiveness');
    const { container } = render(AppliedModeSummary, { props: { channels: [] } });
    expect(container.querySelector('.mode-badge--effectiveness')).toBeInTheDocument();
  });

  it('shows Смешанный badge when analysisMode=mixed', () => {
    analysisMode.set('mixed');
    const { container } = render(AppliedModeSummary, { props: { channels: [] } });
    expect(container.querySelector('.mode-badge--mixed')).toBeInTheDocument();
  });

  // ─── Channel list ────────────────────────────────────────────────────────

  it('renders channel list items — correct count', () => {
    const { container } = render(AppliedModeSummary, { props: { channels: makeChannels() } });
    const items = container.querySelectorAll('.channel-item');
    expect(items.length).toBe(3);
  });

  it('renders each channel name in the list', () => {
    const { container } = render(AppliedModeSummary, { props: { channels: makeChannels() } });
    const list = container.querySelector('.channel-list');
    expect(list).toBeInTheDocument();
    for (const ch of makeChannels()) {
      // Имя может появляться также в .uc-inputs (для physical channels в ROI mode) — scope к channel-list.
      expect(list?.textContent).toContain(ch.name);
    }
  });

  it('shows «спенд в ₽» label for monetary channels in roi mode', () => {
    analysisMode.set('roi');
    const channels = [
      { name: 'TV', detectedType: 'monetary' },
      { name: 'OOH', detectedType: 'monetary' },
    ];
    const { container } = render(AppliedModeSummary, { props: { channels } });
    const labels = container.querySelectorAll('.channel-metric');
    for (const label of labels) {
      expect(label.textContent).toContain('спенд в ₽');
    }
  });

  // BUG #2 fix (v2.0.1): physical-only канал в ROI mode = incompatible, не «спенд в ₽».
  it('shows warning label for physical channels in roi mode (BUG #2 fix)', () => {
    analysisMode.set('roi');
    const channels = [
      { name: 'TRPs бренд', detectedType: 'physical' },
    ];
    const { container } = render(AppliedModeSummary, { props: { channels } });
    const label = container.querySelector('.channel-metric');
    expect(label?.textContent).toContain('нужна конвертация в ₽');
    expect(label?.textContent).not.toContain('спенд в ₽');
    expect(label?.classList.contains('metric-incompat')).toBe(true);
  });

  it('banner mentions both conversion options (budget OR unit cost + inflation)', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    const banner = container.querySelector('[data-testid="incompat-banner"]');
    expect(banner).toBeInTheDocument();
    expect(banner?.textContent).toContain('общий бюджет');
    expect(banner?.textContent).toContain('стоимость 1 единицы');
    expect(banner?.textContent).toContain('роста стоимости');
    // Не должен упоминать Expert mode как требование — Антон 2026-05-14
    expect(banner?.textContent).not.toContain('Expert');
  });

  it('marks incompatible channel item with class.incompatible in roi mode', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }  // Digital is physical
    });
    const items = container.querySelectorAll('.channel-item');
    const incompatItems = Array.from(items).filter((el) => el.classList.contains('incompatible'));
    expect(incompatItems.length).toBe(1);  // только Digital
  });

  it('renders incompat-banner when ROI mode has physical channels', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }  // 1 physical
    });
    const banner = container.querySelector('[data-testid="incompat-banner"]');
    expect(banner).toBeInTheDocument();
    expect(banner?.textContent).toMatch(/1\s+канал/);
  });

  it('does NOT render incompat-banner when ROI mode has only monetary channels', () => {
    analysisMode.set('roi');
    const channels = [
      { name: 'TV', detectedType: 'monetary' },
      { name: 'OOH', detectedType: 'monetary' },
    ];
    const { container } = render(AppliedModeSummary, { props: { channels } });
    expect(container.querySelector('[data-testid="incompat-banner"]')).toBeNull();
  });

  it('does NOT render incompat-banner in effectiveness mode even with physical channels', () => {
    analysisMode.set('effectiveness');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    expect(container.querySelector('[data-testid="incompat-banner"]')).toBeNull();
  });

  // ─── UX gap fix v2.0.1: excluded channels summary ──────────────────────────

  it('shows active channels count pill', () => {
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    const pill = container.querySelector('.count-pill--active');
    expect(pill).toBeInTheDocument();
    expect(pill?.textContent).toContain('3');
  });

  it('shows excluded count pill when excludedChannelNames provided', () => {
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: makeChannels(),
        excludedChannelNames: ['Retail Media бюджет', 'Радио в руб.', 'Пресса в руб.', 'ООН в руб.'],
      }
    });
    const pill = container.querySelector('.count-pill--excluded');
    expect(pill).toBeInTheDocument();
    expect(pill?.textContent).toContain('4');
  });

  it('does NOT show excluded pill when list is empty', () => {
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels(), excludedChannelNames: [] }
    });
    expect(container.querySelector('.count-pill--excluded')).toBeNull();
  });

  it('clicking excluded pill expands list with names', async () => {
    const { container, getByTestId } = render(AppliedModeSummary, {
      props: {
        channels: makeChannels(),
        excludedChannelNames: ['Retail Media', 'Радио'],
      }
    });
    expect(container.querySelector('[data-testid="excluded-list"]')).toBeNull();
    const toggle = getByTestId('excluded-toggle');
    await fireEvent.click(toggle);
    const list = container.querySelector('[data-testid="excluded-list"]');
    expect(list).toBeInTheDocument();
    expect(list?.textContent).toContain('Retail Media');
    expect(list?.textContent).toContain('Радио');
  });

  // ─── BUG #2 fix v2.0.1: inline unit_cost inputs ────────────────────────────

  it('renders uc-inputs block when ROI mode has physical channels', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    const block = container.querySelector('[data-testid="uc-inputs"]');
    expect(block).toBeInTheDocument();
    // 1 physical (Digital) → 1 row.
    const rows = block?.querySelectorAll('.uc-row');
    expect(rows?.length).toBe(1);
  });

  it('does NOT render uc-inputs when channels are all monetary in ROI', () => {
    analysisMode.set('roi');
    const channels = [{ name: 'TV', detectedType: 'monetary' }];
    const { container } = render(AppliedModeSummary, { props: { channels } });
    expect(container.querySelector('[data-testid="uc-inputs"]')).toBeNull();
  });

  it('does NOT render uc-inputs in effectiveness mode', () => {
    analysisMode.set('effectiveness');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    expect(container.querySelector('[data-testid="uc-inputs"]')).toBeNull();
  });

  it('two mode buttons render for each physical channel: budget + unit', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    const row = container.querySelector('.uc-row');
    const btns = row?.querySelectorAll('.uc-mode-btn');
    expect(btns?.length).toBe(2);
    expect(btns?.[0].textContent?.trim()).toBe('Общий бюджет ₽');
    expect(btns?.[1].textContent?.trim()).toMatch(/Цена 1 ед/);
  });

  it('default mode is «budget» (бренд-менеджер знает бюджет, не CPP)', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, {
      props: { channels: makeChannels() }
    });
    const activeBtn = container.querySelector('.uc-mode-btn.active');
    expect(activeBtn?.textContent?.trim()).toMatch(/Общий бюджет/);
  });

  it('typing unit_cost > 0 stores it in $unitCosts and marks channel converted', async () => {
    analysisMode.set('roi');
    const channels = [{ name: 'TRP', detectedType: 'physical' }];
    const { container, getByTestId } = render(AppliedModeSummary, {
      props: { channels, channelSums: { TRP: 100 } }
    });
    // Default is 'budget' mode — switch to unit first.
    const unitBtn = Array.from(container.querySelectorAll('.uc-mode-btn'))
      .find((b) => b.textContent?.includes('Цена 1 ед'));
    await fireEvent.click(/** @type {Element} */ (unitBtn));
    const input = getByTestId('uc-unit-input-TRP');
    expect(input).toBeInTheDocument();
    await fireEvent.input(input, { target: { value: '25000' } });
    expect(get(unitCosts).TRP).toBe(25000);
    // Канал стал converted → больше не incompatible → banner исчез.
    expect(container.querySelector('[data-testid="incompat-banner"]')).toBeNull();
    // Channel-list row показывает converted state.
    const items = container.querySelectorAll('.channel-item.converted');
    expect(items.length).toBe(1);
  });

  it('mode toggle to «budget» derives unit_cost = budget / sum', async () => {
    analysisMode.set('roi');
    const channels = [{ name: 'TRP', detectedType: 'physical' }];
    const { container, getByTestId } = render(AppliedModeSummary, {
      props: { channels, channelSums: { TRP: 200 } }
    });
    // Switch to budget mode.
    const budgetBtn = Array.from(container.querySelectorAll('.uc-mode-btn'))
      .find((b) => b.textContent?.includes('Общий бюджет'));
    expect(budgetBtn).toBeDefined();
    await fireEvent.click(/** @type {Element} */ (budgetBtn));
    const budgetInput = getByTestId('uc-budget-input-TRP');
    expect(budgetInput).toBeInTheDocument();
    await fireEvent.input(budgetInput, { target: { value: '50000' } });
    // 50000 / 200 = 250 ₽/ед.
    expect(get(unitCosts).TRP).toBe(250);
  });

  it('inflation input stores value to $unitCostInflation', async () => {
    analysisMode.set('roi');
    const channels = [{ name: 'TRP', detectedType: 'physical' }];
    const { container, getByTestId } = render(AppliedModeSummary, {
      props: { channels, channelSums: { TRP: 100 } }
    });
    // Default is 'budget' mode — switch to unit first.
    const unitBtn = Array.from(container.querySelectorAll('.uc-mode-btn'))
      .find((b) => b.textContent?.includes('Цена 1 ед'));
    await fireEvent.click(/** @type {Element} */ (unitBtn));
    const inflInput = getByTestId('uc-infl-input-TRP');
    expect(inflInput).toBeInTheDocument();
    await fireEvent.input(inflInput, { target: { value: '15' } });
    expect(get(unitCostInflation).TRP).toBe(15);
  });

  it('empty unit_cost input clears the store entry', async () => {
    analysisMode.set('roi');
    unitCosts.set({ TRP: 1000 });
    const channels = [{ name: 'TRP', detectedType: 'physical' }];
    const { container, getByTestId } = render(AppliedModeSummary, {
      props: { channels, channelSums: { TRP: 100 } }
    });
    // Default is 'budget' mode — switch to unit first.
    const unitBtn = Array.from(container.querySelectorAll('.uc-mode-btn'))
      .find((b) => b.textContent?.includes('Цена 1 ед'));
    await fireEvent.click(/** @type {Element} */ (unitBtn));
    const input = getByTestId('uc-unit-input-TRP');
    await fireEvent.input(input, { target: { value: '' } });
    expect(get(unitCosts).TRP).toBeUndefined();
  });

  it('shows physical metric label for all channels in effectiveness mode', () => {
    analysisMode.set('effectiveness');
    const channels = [
      { name: 'TV', detectedType: 'physical' },
      { name: 'Digital', detectedType: 'physical' },
    ];
    const { container } = render(AppliedModeSummary, { props: { channels } });
    const labels = container.querySelectorAll('.channel-metric');
    for (const label of labels) {
      expect(label.textContent).toContain('физ. метрика');
    }
  });

  // ─── Empty channels ──────────────────────────────────────────────────────

  it('renders without error when channels=[] (empty)', () => {
    expect(() => render(AppliedModeSummary, { props: { channels: [] } })).not.toThrow();
  });

  it('shows placeholder text when channels is empty', () => {
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.getByText(/Каналы определятся после импорта данных/)).toBeInTheDocument();
  });

  it('does NOT render channel-list when channels is empty', () => {
    const { container } = render(AppliedModeSummary, { props: { channels: [] } });
    expect(container.querySelector('.channel-list')).toBeNull();
  });

  // ─── CTA Expert button ───────────────────────────────────────────────────

  it('CTA «Управлять вручную» visible when expertMode=false', () => {
    expertMode.set(false);
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.getByText(/Управлять вручную/)).toBeInTheDocument();
  });

  it('CTA hidden when expertMode=true', () => {
    expertMode.set(true);
    render(AppliedModeSummary, { props: { channels: [] } });
    expect(screen.queryByText(/Управлять вручную/)).toBeNull();
  });

  it('expert active note shown when expertMode=true', () => {
    expertMode.set(true);
    render(AppliedModeSummary, { props: { channels: [] } });
    // .expert-active-note should be present
    expect(screen.getByText(/Expert mode включён/)).toBeInTheDocument();
  });

  it('clicking CTA sets expertMode store = true', async () => {
    expertMode.set(false);
    render(AppliedModeSummary, { props: { channels: [] } });
    const ctaBtn = screen.getByRole('button', { name: /Управлять вручную/ });
    await fireEvent.click(ctaBtn);
    expect(get(expertMode)).toBe(true);
  });

  it('renders without channels prop at all (uses default [])', () => {
    expect(() => render(AppliedModeSummary)).not.toThrow();
  });
});
