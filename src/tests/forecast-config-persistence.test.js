/**
 * F-018 regression — verify `budgetManuallyEdited` flag persistence
 * через forecastConfig localStorage subscriber.
 *
 * Pre-F-018 bug: ForecastHorizonPicker инициализировал
 * `budgetManuallyEdited = budgetInput !== null` после reload — любой
 * restored budget (включая auto-suggested) считался manual → presets
 * не пересчитывали бюджет. Fix: персистим явный флаг в store.
 *
 * Этот тест проверяет contract на уровне store:
 *   - hydrate флаг из localStorage когда есть
 *   - default false для legacy payload без поля
 *   - subscribe пишет payload с флагом обратно
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

const FORECAST_CONFIG_KEY = 'econ-forecast-config';

beforeEach(() => {
  vi.resetModules();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('forecastConfig persistence — budgetManuallyEdited flag (F-018)', () => {
  it('hydrates budgetManuallyEdited=true from localStorage', async () => {
    localStorage.setItem(
      FORECAST_CONFIG_KEY,
      JSON.stringify({
        periods: 6,
        periodLabel: 'Полугодие',
        budgetMoney: 50_000_000,
        inflationPerChannel: null,
        budgetManuallyEdited: true,
      }),
    );
    const { forecastConfig } = await import('$lib/project-state.js');
    const cfg = get(forecastConfig);
    expect(cfg.budgetManuallyEdited).toBe(true);
    expect(cfg.budgetMoney).toBe(50_000_000);
  });

  it('hydrates budgetManuallyEdited=false from localStorage', async () => {
    localStorage.setItem(
      FORECAST_CONFIG_KEY,
      JSON.stringify({
        periods: 3,
        periodLabel: 'Квартал',
        budgetMoney: 25_000_000,
        inflationPerChannel: null,
        budgetManuallyEdited: false,
      }),
    );
    const { forecastConfig } = await import('$lib/project-state.js');
    expect(get(forecastConfig).budgetManuallyEdited).toBe(false);
  });

  it('defaults budgetManuallyEdited to false для legacy payload без поля', async () => {
    localStorage.setItem(
      FORECAST_CONFIG_KEY,
      JSON.stringify({
        periods: 12,
        periodLabel: 'Год',
        budgetMoney: 100_000_000,
        inflationPerChannel: null,
      }),
    );
    const { forecastConfig } = await import('$lib/project-state.js');
    expect(get(forecastConfig).budgetManuallyEdited).toBe(false);
  });

  it('persists budgetManuallyEdited через subscriber после update', async () => {
    const { forecastConfig } = await import('$lib/project-state.js');
    forecastConfig.set({
      periods: 6,
      periodLabel: 'Полугодие',
      budgetMoney: 80_000_000,
      inflationPerChannel: null,
      budgetManuallyEdited: true,
    });
    const raw = localStorage.getItem(FORECAST_CONFIG_KEY);
    expect(raw).not.toBeNull();
    const payload = JSON.parse(/** @type {string} */ (raw));
    expect(payload.budgetManuallyEdited).toBe(true);
    expect(payload.budgetMoney).toBe(80_000_000);
  });

  it('ignores non-boolean budgetManuallyEdited (corrupted payload)', async () => {
    localStorage.setItem(
      FORECAST_CONFIG_KEY,
      JSON.stringify({
        periods: 3,
        periodLabel: 'Квартал',
        budgetMoney: 10_000_000,
        inflationPerChannel: null,
        budgetManuallyEdited: 'yes',
      }),
    );
    const { forecastConfig } = await import('$lib/project-state.js');
    expect(get(forecastConfig).budgetManuallyEdited).toBe(false);
  });

  it('coerces undefined v.budgetManuallyEdited в false при write', async () => {
    const { forecastConfig } = await import('$lib/project-state.js');
    // @ts-expect-error — simulate caller forgetting field
    forecastConfig.set({
      periods: 6,
      periodLabel: 'Полугодие',
      budgetMoney: 50_000_000,
      inflationPerChannel: null,
    });
    const payload = JSON.parse(
      /** @type {string} */ (localStorage.getItem(FORECAST_CONFIG_KEY)),
    );
    expect(payload.budgetManuallyEdited).toBe(false);
  });
});
