/**
 * Разрешение гейта «Условия ознакомительного использования» (s48, 2026-09-14, третье
 * уточнение внешнего аудита). Раньше это была локальная async IIFE внутри
 * `+layout.svelte::onMount` — вынесена в отдельный модуль с DI на `invoke` (тот же приём,
 * что и у `$lib/global-shortcuts.js`), чтобы гонку «состояние до ответа Rust» можно было
 * воспроизвести прямым вызовом с поддельным, никогда не резолвящимся `invoke`, а не монтируя
 * весь layout — см. `src/tests/trial-consent-gate-race.test.js`.
 *
 * Отказ проверки трактуется как «согласие не подтверждено» (fail-closed) — юридический гейт
 * не должен молча пропускать из-за временной ошибки IPC.
 */
import { trialConsentPromptOpen, trialConsentResolved } from './store.js';

/**
 * @param {(cmd: string, args?: Record<string, unknown>) => Promise<unknown>} invoke - `@tauri-apps/api/core`
 *   `invoke`, передаётся явным параметром ради теста с поддельным/подвешенным промисом.
 */
export async function resolveTrialConsentGate(invoke) {
    try {
        const status = /** @type {{required: boolean}} */ (await invoke('get_trial_consent_status'));
        if (status?.required !== false) trialConsentPromptOpen.set(true);
    } catch {
        trialConsentPromptOpen.set(true);
    } finally {
        trialConsentResolved.set(true);
    }
}
