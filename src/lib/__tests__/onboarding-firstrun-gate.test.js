/**
 * ONBOARD-1 (2026-06-02): на первом прогоне (FirstRunTour ещё не пройден/пропущен)
 * per-step коуч-марки приглушаются - иначе дублируют только что показанный тур.
 * После завершения/пропуска тура - always-on (решение Антона 2026-04-22).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { shouldShowOnboarding } from '../onboarding-state.js';

const TOUR_KEY = 'aurora.firstRunTourCompleted';
const ENABLED_KEY = 'aurora-econ-onboarding-enabled';

beforeEach(() => {
  localStorage.clear();
});

describe('ONBOARD-1 коуч-марки приглушены на первом прогоне', () => {
  it('FirstRunTour НЕ пройден (first-run) → коуч-марки скрыты', () => {
    // тур ещё не завершён → ключа нет
    expect(shouldShowOnboarding('import')).toBe(false);
  });

  it('FirstRunTour пройден + онбординг включён (default) → коуч-марки показываются', () => {
    localStorage.setItem(TOUR_KEY, '1');
    // ENABLED_KEY не задан → default on
    expect(shouldShowOnboarding('import')).toBe(true);
  });

  it('FirstRunTour пройден, но онбординг выключен в Settings → скрыты', () => {
    localStorage.setItem(TOUR_KEY, '1');
    localStorage.setItem(ENABLED_KEY, '0');
    expect(shouldShowOnboarding('optimize')).toBe(false);
  });

  it('тур пройден + явно включён → показываются', () => {
    localStorage.setItem(TOUR_KEY, '1');
    localStorage.setItem(ENABLED_KEY, '1');
    expect(shouldShowOnboarding('validate')).toBe(true);
  });
});
