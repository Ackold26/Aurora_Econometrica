/**
 * Обучающий режим — глобальный toggle + персист completed-флагов по шагам.
 *
 * Поведение:
 *   - Глобальный toggle в /settings: `onboardingEnabled` (default = true для новых
 *     пользователей, false если отключено хотя бы раз). Сохраняется в localStorage.
 *   - Per-step completed flags: `aurora-econ-onboarded:<stepKey>` (0/1).
 *   - Step-компоненты на mount делают `shouldShowOnboarding('<stepKey>')` — если
 *     true (enabled=true + этот шаг ещё не пройден), запускают <PipelineOnboarding />.
 *   - «Пройти все туры заново» (кнопка в /settings) — removeItem всех step-flags.
 */
import { writable } from 'svelte/store';

const ENABLED_KEY = 'aurora-econ-onboarding-enabled';
const STEP_KEY_PREFIX = 'aurora-econ-onboarded:';

/** @type {string[]} Канонические имена шагов с турами. */
export const TOUR_STEP_KEYS = ['import', 'validate', 'model', 'decompose', 'optimize', 'report'];

/** Прочитать enabled из localStorage. Default true (показываем туры новым юзерам). */
function readEnabled() {
  if (typeof window === 'undefined') return true;
  try {
    const v = window.localStorage.getItem(ENABLED_KEY);
    if (v === null) return true; // default on
    return v === '1';
  } catch {
    return true;
  }
}

/** @type {import('svelte/store').Writable<boolean>} */
export const onboardingEnabled = writable(readEnabled());

// Persist на каждое изменение
onboardingEnabled.subscribe((v) => {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(ENABLED_KEY, v ? '1' : '0'); } catch {}
});

/**
 * Проверка: стоит ли показать тур на этом шаге прямо сейчас.
 * @param {string} stepKey
 * @returns {boolean}
 */
export function shouldShowOnboarding(stepKey) {
  if (typeof window === 'undefined') return false;
  try {
    const enabled = window.localStorage.getItem(ENABLED_KEY);
    if (enabled === '0') return false; // глобально выключен
    const seen = window.localStorage.getItem(STEP_KEY_PREFIX + stepKey);
    return !seen;
  } catch {
    return false;
  }
}

/**
 * Отметить шаг как пройденный (тур завершён или пропущен).
 * @param {string} stepKey
 */
export function markOnboardingDone(stepKey) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(STEP_KEY_PREFIX + stepKey, '1'); } catch {}
}

/**
 * Сбросить все completed-флаги (кнопка «Пройти все туры заново» в настройках).
 * НЕ трогает `onboardingEnabled` — если он включён, туры сразу начнут появляться.
 */
export function resetAllOnboarding() {
  if (typeof window === 'undefined') return;
  try {
    for (const key of TOUR_STEP_KEYS) {
      window.localStorage.removeItem(STEP_KEY_PREFIX + key);
    }
    // Совместимость со старым ключом из OptimizeStep (может быть в storage после апгрейда)
    window.localStorage.removeItem('aurora-econ-optimize-onboarded');
  } catch {}
}
