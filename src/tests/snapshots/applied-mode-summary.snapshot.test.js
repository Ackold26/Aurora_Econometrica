/**
 * AppliedModeSummary snapshot regression baselines — Phase 0.1.
 *
 * Цель: regression net перед Phase 1+ changes (SSOT classifier replace,
 * Persistence stores, Migration UI). Snapshot фиксирует current rendering
 * state post-v2.0.1 hotfix (commits 61feac7 + 26879f1 + 43a7939). Any
 * Phase 1+ visual change → snapshot diff в CI/local → manual review.
 *
 * Не Playwright — recon agent выявил Tauri+Playwright 30s startup
 * overhead. Snapshot tests через existing vitest infra: fast, reliable.
 *
 * Snapshots stored inline (`.toMatchInlineSnapshot`) для visibility в diff.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import AppliedModeSummary from '$lib/components/pipeline/AppliedModeSummary.svelte';
import { analysisMode, expertMode, unitCosts, unitCostInflation } from '$lib/project-state.js';


/** Realistic Кагоцел-shape channels: 3 monetary digital + 1 physical TRP. */
function realisticChannels() {
  return [
    { name: 'OLV Бюджет', detectedType: 'monetary' },
    { name: 'Banners Бюджет', detectedType: 'monetary' },
    { name: 'Social Бюджет', detectedType: 'monetary' },
    { name: 'TRPs бренд', detectedType: 'physical' },
  ];
}

/** Excluded channels list (Retail Media + Радио + Пресса + ООН). */
function excludedSample() {
  return ['Retail Media бюджет', 'Радио в руб.', 'Пресса в руб.', 'ООН в руб.'];
}

/** Channel sums для budget mode preview math. */
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
});


describe('AppliedModeSummary — snapshot regression', () => {
  it('ROI mode with 4 channels (1 physical) — baseline', () => {
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('ROI mode with TRPs converted (unit_cost set) — baseline', () => {
    unitCosts.set({ 'TRPs бренд': 25000 });
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('Effectiveness mode with same channels — baseline', () => {
    analysisMode.set('effectiveness');
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('Mixed mode (Expert) — baseline', () => {
    analysisMode.set('mixed');
    expertMode.set(true);
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: realisticChannels(),
        channelSums: channelSumsSample(),
        excludedChannelNames: excludedSample(),
      },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('Empty channels (placeholder) — baseline', () => {
    const { container } = render(AppliedModeSummary, {
      props: { channels: [], channelSums: {}, excludedChannelNames: [] },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('ROI with no excluded — baseline', () => {
    const { container } = render(AppliedModeSummary, {
      props: {
        channels: [
          { name: 'TV', detectedType: 'monetary' },
          { name: 'OOH', detectedType: 'monetary' },
        ],
        channelSums: { TV: 10000000, OOH: 5000000 },
        excludedChannelNames: [],
      },
    });
    expect(container.innerHTML).toMatchSnapshot();
  });
});
