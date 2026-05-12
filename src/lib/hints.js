/**
 * Contextual hints system - adaptive, non-intrusive, dismissable.
 * Hints appear based on user's current context and are shown only once.
 * User can disable all hints globally.
 */
import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'ai-agency-dismissed-hints';
const GLOBAL_KEY = 'ai-agency-hints-enabled';

/** @type {import('svelte/store').Writable<Set<string>>} */
export const dismissedHints = writable(loadDismissed());

/** @type {import('svelte/store').Writable<boolean>} */
export const hintsEnabled = writable(loadGlobalToggle());

function loadDismissed() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}

function loadGlobalToggle() {
  try {
    const raw = localStorage.getItem(GLOBAL_KEY);
    return raw === null ? true : JSON.parse(raw);
  } catch { return true; }
}

// Persist on change
dismissedHints.subscribe(s => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...s])); } catch {}
});
hintsEnabled.subscribe(v => {
  try { localStorage.setItem(GLOBAL_KEY, JSON.stringify(v)); } catch {}
});

/** Dismiss a specific hint forever
 * @param {string} hintId */
export function dismissHint(hintId) {
  dismissedHints.update(s => { s.add(hintId); return new Set(s); });
}

/** Check if a hint should be shown
 * @param {string} hintId */
export function shouldShow(hintId) {
  return get(hintsEnabled) && !get(dismissedHints).has(hintId);
}

/** Reset all dismissed hints (for testing or settings) */
export function resetAllHints() {
  dismissedHints.set(new Set());
}

/** Toggle all hints on/off
 * @param {boolean} enabled */
export function toggleHints(enabled) {
  hintsEnabled.set(enabled);
}

// ── Hint Definitions ──────────────────────────────────

/**
 * @typedef {{
 *   id: string,
 *   text: string,
 *   detail?: string,
 *   position?: 'top'|'bottom'|'left'|'right'
 * }} HintDef
 */

/** All workflow hints, keyed by id */
export const HINTS = {
  // ── Workflow list page ──
  'wf-welcome': {
    id: 'wf-welcome',
    text: 'Workflow - визуальный конструктор рабочих процессов',
    detail: 'Выберите шаблон, чтобы создать готовый workflow из экспертных кабинетов, или соберите свой с нуля.',
  },
  'wf-templates': {
    id: 'wf-templates',
    text: 'Шаблоны - быстрый старт',
    detail: 'Каждый шаблон - проверенная цепочка кабинетов для типичной задачи. Вы сможете изменить её после создания.',
  },
  'wf-need-brand': {
    id: 'wf-need-brand',
    text: 'Для workflow нужен бренд',
    detail: 'Workflow привязан к бренду - все кабинеты будут использовать его контекст: тон, маркеры, стоп-слова.',
  },

  // ── Editor page ──
  'wf-editor-intro': {
    id: 'wf-editor-intro',
    text: 'Это ваш workflow',
    detail: 'Каждая карточка - шаг, который выполнит один из кабинетов. Нажмите "+" между шагами, чтобы добавить новый.',
  },
  'wf-add-step': {
    id: 'wf-add-step',
    text: 'Нажмите "+", чтобы добавить шаг',
    detail: 'Система подскажет, какой кабинет лучше добавить следующим, исходя из логики работы.',
  },
  'wf-suggestion-banner': {
    id: 'wf-suggestion-banner',
    text: 'Рекомендация системы',
    detail: 'Жёлтая полоска сверху - подсказка на основе анализа вашего workflow. Например, если есть копирайтер, но нет юридической проверки.',
  },
  'wf-run-button': {
    id: 'wf-run-button',
    text: 'Запуск выполнит все шаги по очереди',
    detail: 'Каждый кабинет получит контекст бренда и результаты предыдущего шага. Параллельные ветки запустятся одновременно.',
  },
  'wf-execution-running': {
    id: 'wf-execution-running',
    text: 'Workflow выполняется',
    detail: 'Текущий шаг подсвечен. Вы можете отменить выполнение кнопкой "Отменить". Результаты сохранятся в Brand Hub.',
  },
  'wf-name-edit': {
    id: 'wf-name-edit',
    text: 'Нажмите на название, чтобы переименовать',
    detail: 'Все изменения сохраняются автоматически.',
  },

  // ── Step types ──
  'wf-parallel-explain': {
    id: 'wf-parallel-explain',
    text: 'Параллельные шаги выполняются одновременно',
    detail: 'Например, копирайтер пишет тексты, а арт-директор готовит визуалы - не нужно ждать друг друга.',
  },
  'wf-loop-explain': {
    id: 'wf-loop-explain',
    text: 'Цикл - итеративная доработка',
    detail: 'Работа → ревью → доработка. Повторяется указанное количество раз или пока качество не будет достаточным.',
  },

  // ── After execution ──
  'wf-execution-done': {
    id: 'wf-execution-done',
    text: 'Workflow завершён!',
    detail: 'Результаты каждого шага сохранены в Brand Hub. Откройте кабинет, чтобы увидеть экспортированные файлы.',
  },
  // ── Pipeline ──
  'pipeline-brief': {
    id: 'pipeline-brief',
    text: 'Бриф передаётся каждому шагу',
    detail: 'Напишите бриф - он будет автоматически передан каждому AI-эксперту в пайплайне вместе с результатами предыдущих шагов.',
  },
  'pipeline-export': {
    id: 'pipeline-export',
    text: 'Экспорт результатов',
    detail: 'После завершения пайплайна вы можете экспортировать все результаты в ZIP-архив с организованными папками по шагам.',
  },
};
