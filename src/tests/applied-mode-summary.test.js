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
import { analysisMode, expertMode } from '$lib/project-state.js';


// Reset stores before each test
beforeEach(() => {
  analysisMode.set('roi');
  expertMode.set(false);
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
    render(AppliedModeSummary, { props: { channels: makeChannels() } });
    for (const ch of makeChannels()) {
      expect(screen.getByText(ch.name)).toBeInTheDocument();
    }
  });

  it('shows «спенд в ₽» label for all channels in roi mode', () => {
    analysisMode.set('roi');
    const { container } = render(AppliedModeSummary, { props: { channels: makeChannels() } });
    const labels = container.querySelectorAll('.channel-metric');
    for (const label of labels) {
      expect(label.textContent).toContain('спенд в ₽');
    }
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
