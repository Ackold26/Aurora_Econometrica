/**
 * chat-classifier.js — Frontend regex-classifier для перехвата small talk.
 *
 * Перехватывает нерабочие сообщения ДО отправки в Claude CLI.
 * Все ответы вежливо подводят пользователя к рабочей задаче.
 */
import { getTimeGreeting } from '$lib/psy.js';

// ── Data (loaded from content pack) ──

/** @type {Record<string, {regexes: string[], flags: string}>} */
let _patterns = {};
let _safeAfterAssistant = new Set(['greeting', 'farewell', 'offtopic']);
/** @type {Record<string, RegExp[]>|null} */
let _compiledPatterns = null;

/**
 * Initialize classifier data from content pack JSON.
 * Called once from +layout.svelte during app startup.
 * @param {any} data - parsed classifier-data.json
 */
export function initClassifierData(data) {
  if (data) {
    _patterns = data.patterns || {};
    _safeAfterAssistant = new Set(data.safeAfterAssistant || []);
    _compiledPatterns = null; // invalidate cache
  }
}

/**
 * Get compiled RegExp patterns (lazy, cached).
 * @returns {Record<string, RegExp[]>}
 */
function getCompiledPatterns() {
  if (_compiledPatterns) return _compiledPatterns;
  _compiledPatterns = {};
  for (const [category, config] of Object.entries(_patterns)) {
    _compiledPatterns[category] = config.regexes.map(
      r => new RegExp(r, config.flags || 'i')
    );
  }
  return _compiledPatterns;
}

// ════════════════════════════════════════════════════════
// PATTERNS — 9 категорий, 70+ regex'ов (loaded from content pack)
// ════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════
// RESPONSE BUILDER
// ════════════════════════════════════════════════════════

/**
 * Сформировать строку с топ-командами.
 * @param {string[]} topCommands
 * @returns {string}
 */
function commandsBlock(topCommands) {
  if (topCommands.length === 0) {
    return '\n\nОпишите задачу или выберите команду из панели справа.';
  }
  return `\n\nГотов начать? Основные команды:\n${topCommands.map(c => `- **${c}**`).join('\n')}`;
}

/**
 * Сгенерировать ответ, подводящий к работе.
 * @param {string} type
 * @param {{id?: string, name?: string}|null} cabinet
 * @param {string[]} topCommands
 * @returns {string|null}
 */
function buildResponse(type, cabinet, topCommands) {
  const name = cabinet?.name || 'Ассистент';
  const cmds = commandsBlock(topCommands);

  switch (type) {
    case 'greeting':
      return `${getTimeGreeting()}! ${name} на связи — готов к работе.${cmds}`;
    case 'farewell':
      return 'До встречи! Результаты сохранены в папке «Экспорт» на рабочем столе.';
    case 'thanks':
      return 'Рад помочь! Если нужно доработать результат — уточните, что изменить. Или переходите к следующей задаче.';
    case 'status':
      return `Всё в порядке — работаю и жду задание.${cmds}`;
    case 'identity':
      return `Я — ${name}, специализированный ИИ-ассистент в составе Aurora AI. Работаю с профессиональными задачами в рамках своей экспертизы.${cmds}`;
    case 'capabilities':
      return `${name} — вот что я умею:${cmds}\n\nВы также можете описать задачу своими словами.`;
    case 'empty':
      return `Готов к работе. Опишите задачу или выберите команду из панели справа.`;
    case 'compliment':
      return `Спасибо! Давайте направим энергию в дело.${cmds}`;
    case 'offtopic':
      return `Я специализируюсь на рабочих задачах и буду максимально полезен именно в них.${cmds}`;
    default:
      return null;
  }
}

// ════════════════════════════════════════════════════════
// PUBLIC API
// ════════════════════════════════════════════════════════

/**
 * Классифицировать сообщение пользователя.
 * @param {string} text — текст сообщения
 * @param {{id?: string, name?: string}|null} cabinet — активный кабинет
 * @param {string[]} topCommands — labels топ-3 команд кабинета
 * @param {Array<{role: string, content: string}>} chatMessages — текущая история чата
 * @returns {{type: string, response: string}|null} — null = отправлять в Claude
 */
export function classifyMessage(text, cabinet, topCommands, chatMessages) {
  const trimmed = text.trim();

  // ── Защита: НЕ перехватываем задачи ──

  // Slash-команды всегда идут в Claude
  if (trimmed.startsWith('/')) return null;

  // Длинные сообщения (>80 символов) — скорее всего задача
  if (trimmed.length > 80) return null;

  // Сообщения с URL или файлами
  if (/https?:\/\/|www\.|\.pdf|\.docx|\.xlsx|\.pptx|\.csv/i.test(trimmed)) return null;

  // ── Поиск совпадения ──
  let matchedType = null;
  for (const [type, patterns] of Object.entries(getCompiledPatterns())) {
    for (const regex of patterns) {
      if (regex.test(trimmed)) {
        matchedType = type;
        break;
      }
    }
    if (matchedType) break;
  }

  if (!matchedType) return null; // Не совпало → Claude

  // ── Follow-up protection ──
  // После ответа ассистента перехватываем ТОЛЬКО безопасные категории.
  // "ок", "спасибо", "круто" после ответа могут быть follow-up инструкциями.
  const lastMsg = chatMessages[chatMessages.length - 1];
  if (lastMsg?.role === 'assistant' && !_safeAfterAssistant.has(matchedType)) {
    return null; // → Claude (возможный follow-up)
  }

  const response = buildResponse(matchedType, cabinet, topCommands);
  return response ? { type: matchedType, response } : null;
}
