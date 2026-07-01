import { writable, get } from 'svelte/store';

/** @type {import('svelte/store').Writable<{id: string, name: string, description: string, icon: string, color: string}|null>} */
export const activeCabinet = writable(null);

/**
 * @typedef {{role: string, content: string, ts: number, isQuickReply?: boolean, isAutoContinue?: boolean}} ChatMsg
 */

/**
 * Creates a writable store with a max message limit.
 * @param {number} max
 * @returns {import('svelte/store').Writable<ChatMsg[]>}
 */
function createLimitedStore(max = 500) {
    /** @type {import('svelte/store').Writable<ChatMsg[]>} */
    const inner = writable(/** @type {ChatMsg[]} */ ([]));
    return {
        subscribe: inner.subscribe,
        set: (/** @type {ChatMsg[]} */ value) => inner.set(value.length > max ? value.slice(-max) : value),
        update: (/** @type {(msgs: ChatMsg[]) => ChatMsg[]} */ fn) => inner.update(msgs => {
            const result = fn(msgs);
            return result.length > max ? result.slice(-max) : result;
        }),
    };
}
export const messages = createLimitedStore(500);

/** @type {import('svelte/store').Writable<boolean>} */
export const isLoading = writable(false);

/** @type {import('svelte/store').Writable<string|null>} */
export const errorMessage = writable(null);

/** @type {import('svelte/store').Writable<string|null>} */
export const pendingCommand = writable(null);

/**
 * Persistent store that saves to localStorage
 * @template T
 * @param {string} key
 * @param {T} defaultValue
 * @returns {import('svelte/store').Writable<T>}
 */
export function createPersistentStore(key, defaultValue) {
    let initial = defaultValue;
    try {
        const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
        if (stored) initial = JSON.parse(stored);
    } catch { /* corrupted localStorage - use default */ }
    const store = writable(initial);
    store.subscribe(value => {
        try { if (typeof localStorage !== 'undefined') localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota exceeded or private mode */ }
    });
    return store;
}

/** @type {import('svelte/store').Writable<number>} */
export const panelWidth = createPersistentStore('ai-agency-panel-width', 240);

/** @type {import('svelte/store').Writable<boolean>} */
export const hasCompletedOnboarding = createPersistentStore('ai-agency-onboarding-complete', false);

/** @type {import('svelte/store').Writable<'dark'|'light'|'fun'>} */
export const theme = createPersistentStore('ai-agency-theme', 'dark');

/**
 * @typedef {{required: boolean, url: string|null, version: string|null, notes: string|null, checksum: string|null}} UpdateRequiredState
 */

/** @type {import('svelte/store').Writable<UpdateRequiredState>} */
export const updateRequired = writable(/** @type {UpdateRequiredState} */ ({ required: false, url: null, version: null, notes: null, checksum: null }));

/** @type {import('svelte/store').Writable<string[]>} */
export const favoriteCommands = createPersistentStore('ai-agency-favorites', /** @type {string[]} */ ([]));

/** PSY-10: Sticky context - контекст для передачи между кабинетами.
 * @type {import('svelte/store').Writable<string|null>} */
export const stickyContext = writable(null);

// ─── UX Redesign v2.0 stores ───────────────────────────────────────

/** Cabinets loaded once in layout, shared across all pages.
 * @type {import('svelte/store').Writable<Array<{id: string, name: string, description: string, icon: string, color: string}>>} */
export const layoutCabinets = writable(/** @type {any[]} */ ([]));

/** Флаг «попытка загрузки кабинетов в layout завершена» (успех или ошибка). Используется
 * вместо `layoutCabinets.length === 0` как индикатор загрузки: в локальной редакции
 * Econometrica 0 advisor-кабинетов — валидное финальное состояние, а не «ещё грузится».
 * @type {import('svelte/store').Writable<boolean>} */
export const cabinetsLoaded = writable(false);

/** NavRail collapsed state (sidebar mode only).
 * @type {import('svelte/store').Writable<boolean>} */
export const navCollapsed = createPersistentStore('ai-agency-nav-collapsed-v2', false);

/** Last opened cabinet ID for restore on app launch.
 * @type {import('svelte/store').Writable<string|null>} */
export const lastCabinetId = createPersistentStore('ai-agency-last-cabinet', null);

/** Inbox files - updated by FileList, read by CommandGrid for smart highlighting.
 * @type {import('svelte/store').Writable<string[]>} */
export const inboxFiles = writable(/** @type {string[]} */ ([]));

/** Cached cabinet commands - loaded by CommandGrid, consumed by ChatPanel for quickStart/classifier.
 * @type {import('svelte/store').Writable<Array<{command: string, label: string, group: string}>>} */
export const cabinetCommands = writable(/** @type {any[]} */ ([]));

/** Recent commands per cabinet.
 * @type {import('svelte/store').Writable<Record<string, string[]>>} */
export const recentCommands = createPersistentStore('ai-agency-recent-cmds', /** @type {Record<string, string[]>} */ ({}));

/**
 * Record a recently used command for a cabinet.
 * @param {string} cabinetId
 * @param {string} command
 */
export function recordRecentCommand(cabinetId, command) {
    recentCommands.update(all => {
        const list = (all[cabinetId] || []).filter(c => c !== command);
        list.unshift(command);
        return { ...all, [cabinetId]: list.slice(0, 5) };
    });
}

/**
 * Get recent commands for a cabinet.
 * @param {string} cabinetId
 * @param {number} [limit=4]
 * @returns {string[]}
 */
export function getRecentCommands(cabinetId, limit = 4) {
    const all = get(recentCommands);
    return (all[cabinetId] || []).slice(0, limit);
}

/** Cycle through 3 themes: dark → light → fun → dark. */
export function cycleTheme() {
    const current = get(theme);
    const next = current === 'dark' ? 'light' : current === 'light' ? 'fun' : 'dark';
    theme.set(next);
}

/** @deprecated Use cycleTheme() instead. Kept for backward compatibility. */
export function toggleTheme() {
    cycleTheme();
}

/** @type {Record<string, string>} */
export const THEME_LABELS = { dark: 'Dark', light: 'Light', fun: 'Fun' };

/** @type {Record<string, string>} */
export const THEME_ICONS = { dark: '\u{1F319}', light: '\u{2600}', fun: '\u{1F308}' };

/** Cabinet-specific onboarding state: {cabinetId: {step: number, completed: boolean}}
 * @type {import('svelte/store').Writable<Record<string, {step: number, completed: boolean}>>} */
export const cabinetOnboarding = createPersistentStore('ai-agency-cabinet-onboarding', {});

/** License/auth error from layout - shared so +page.svelte can display it.
 * @type {import('svelte/store').Writable<string|null>} */
export const licenseError = writable(null);

/** Согласие на облачную обработку (облачная редакция).
 * advisorsEnabled — собрана ли облачная редакция (кабинеты-советники на Anthropic);
 * granted — дал ли пользователь согласие на облачную обработку;
 * loaded — статус получен с бэкенда (до этого гейт не срабатывает).
 * Graceful: без согласия MMM-анализ доступен полностью, заблокированы только советники.
 * @type {import('svelte/store').Writable<{advisorsEnabled: boolean, granted: boolean, loaded: boolean}>} */
export const cloudConsent = writable({ advisorsEnabled: false, granted: false, loaded: false });

/** Открыт ли экран согласия (prompt-triggered: первый запуск или вход в кабинет-советник).
 * @type {import('svelte/store').Writable<boolean>} */
export const cloudConsentPromptOpen = writable(false);

// ── Таймер сессии (Aurora design SSOT §11) ─────────────────────────────────
// Отсчёт с запуска приложения. Управление: стоп/пуск (одиночный клик) + сброс (двойной клик).
// Сбрасывается при перезапуске приложения. Эталон DocMaster.

/** @typedef {{accumulated: number, segmentStart: number, running: boolean}} TimerState
 * @type {import('svelte/store').Writable<TimerState>} */
export const timerState = writable({ accumulated: 0, segmentStart: Date.now(), running: true });

/** Текущее значение таймера в мс.
 * @param {TimerState} s */
export function timerElapsedMs(s) {
    return s.accumulated + (s.running ? Date.now() - s.segmentStart : 0);
}

/** Стоп ↔ пуск/продолжение (одиночный клик). */
export function toggleTimer() {
    timerState.update(s => s.running
        ? { accumulated: s.accumulated + (Date.now() - s.segmentStart), segmentStart: s.segmentStart, running: false }
        : { accumulated: s.accumulated, segmentStart: Date.now(), running: true });
}

/** Сброс на 00:00:00 (двойной клик); отсчёт продолжается. */
export function resetTimer() {
    timerState.set({ accumulated: 0, segmentStart: Date.now(), running: true });
}
