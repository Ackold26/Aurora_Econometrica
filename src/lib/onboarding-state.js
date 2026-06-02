/**
 * Обучающий режим - только глобальный toggle (без per-step completion).
 *
 * Поведение (с 2026-04-22 по запросу Антона):
 *   - Туры показываются ВСЕГДА пока onboardingEnabled=true (default true).
 *   - В самом туре есть кнопки «Далее» / «Пропустить» / «Отключить в настройках».
 *   - Пропустить = закрыть тур локально (до следующего визита шага).
 *   - Отключить = снять глобальный toggle → больше ни один тур не появится
 *     пока пользователь не включит обратно в Settings.
 *
 * Per-step completion flags удалены в этой ревизии - считаем что пользователь
 * либо хочет туры (тогда каждый раз новый контекст), либо нет (тогда выключил).
 * Старые ключи `aurora-econ-onboarded:<step>` очищаются автоматически при load.
 */
import { writable } from 'svelte/store';

const ENABLED_KEY = 'aurora-econ-onboarding-enabled';
const LEGACY_STEP_PREFIX = 'aurora-econ-onboarded:';
// ONBOARD-1 (2026-06-02): ключ завершения FirstRunTour. На первом прогоне (тур ещё
// не пройден) per-step коуч-марки приглушаются - тур только что всё показал. После
// тура always-on (решение 2026-04-22) для возвращающихся юзеров.
const FIRST_RUN_TOUR_KEY = 'aurora.firstRunTourCompleted';

/** @type {string[]} Канонические имена шагов с турами (используется для диагностики). */
export const TOUR_STEP_KEYS = ['import', 'validate', 'model', 'decompose', 'optimize', 'report'];

/** Прочитать enabled из localStorage. Default true - туры показываем новым юзерам. */
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

/** One-time очистка legacy per-step flags - больше не используются. */
function cleanupLegacyStepFlags() {
  if (typeof window === 'undefined') return;
  try {
    for (const key of TOUR_STEP_KEYS) {
      window.localStorage.removeItem(LEGACY_STEP_PREFIX + key);
    }
    window.localStorage.removeItem('aurora-econ-optimize-onboarded');
  } catch {}
}
cleanupLegacyStepFlags();

/** @type {import('svelte/store').Writable<boolean>} */
export const onboardingEnabled = writable(readEnabled());

// Persist на каждое изменение
onboardingEnabled.subscribe((v) => {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(ENABLED_KEY, v ? '1' : '0'); } catch {}
});

/**
 * Проверка: стоит ли показать тур на этом шаге прямо сейчас.
 * Теперь = просто проверка глобального toggle. Per-step состояние НЕ хранится.
 * @param {string} _stepKey - принимается для API-совместимости, но не используется.
 * @returns {boolean}
 */
export function shouldShowOnboarding(_stepKey) {
  if (typeof window === 'undefined') return false;
  try {
    // ONBOARD-1: на первом прогоне (FirstRunTour ещё не пройден/не пропущен)
    // коуч-марки приглушаем - иначе дублируют только что показанный тур.
    if (window.localStorage.getItem(FIRST_RUN_TOUR_KEY) === null) return false;
    const v = window.localStorage.getItem(ENABLED_KEY);
    if (v === null) return true; // default on
    return v === '1';
  } catch {
    return false;
  }
}

/**
 * Отключить онбординг глобально. Вызывается из кнопки «Отключить в настройках»
 * внутри тура - пользователь сразу видит эффект (тур закрывается + больше не
 * появится пока не включит обратно в Settings).
 */
export function disableOnboarding() {
  onboardingEnabled.set(false);
}

/**
 * API-совместимость - старые вызовы markOnboardingDone / resetAllOnboarding
 * остаются работоспособными как no-op. Новая логика их не требует.
 * @param {string} _stepKey
 */
export function markOnboardingDone(_stepKey) { /* no-op */ }
export function resetAllOnboarding() { cleanupLegacyStepFlags(); }
