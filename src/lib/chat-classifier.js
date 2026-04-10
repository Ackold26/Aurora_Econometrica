/**
 * chat-classifier.js — Frontend regex-classifier для перехвата small talk.
 *
 * Перехватывает нерабочие сообщения ДО отправки в Claude CLI.
 * Все ответы вежливо подводят пользователя к рабочей задаче.
 */
import { getTimeGreeting } from '$lib/psy.js';

// ════════════════════════════════════════════════════════
// PATTERNS — 9 категорий, 70+ regex'ов
// ════════════════════════════════════════════════════════

/** @type {Record<string, RegExp[]>} */
const PATTERNS = {
  // ── Приветствия ──
  greeting: [
    /^привет/i,
    /^здравствуй/i,
    /^добрый\s+(день|утро|вечер)/i,
    /^доброе\s+утро/i,
    /^доброго\s+(дня|утра|вечера|времени\s+суток)/i,
    /^хай\b/i,
    /^хелло[у]?\b/i,
    /^hello\b/i,
    /^hi\b/i,
    /^hey\b/i,
    /^yo\b/i,
    /^приветик/i,
    /^приветствую/i,
    /^салют/i,
    /^здарова/i,
    /^здоров[а]?\b/i,
    /^ку\b/i,
    /^good\s+(morning|afternoon|evening)/i,
  ],

  // ── Прощания ──
  farewell: [
    /^пока\b/i,
    /^до свидания/i,
    /^до встречи/i,
    /^всего доброго/i,
    /^всего хорошего/i,
    /^удачи\b/i,
    /^до связи/i,
    /^bye\b/i,
    /^goodbye/i,
    /^good\s*bye/i,
    /^до завтра/i,
    /^спокойной\s+ночи/i,
    /^увидимся/i,
    /^бывай/i,
  ],

  // ── Благодарности ──
  thanks: [
    /^спасибо/i,
    /^благодарю/i,
    /^благодарствую/i,
    /^thanks?\b/i,
    /^thank\s+you/i,
    /^thx\b/i,
    /^мерси/i,
    /^спс\b/i,
    /^отлично[,!.\s]*$/i,
    /^класс[!.\s]*$/i,
    /^круто[!.\s]*$/i,
    /^супер[!.\s]*$/i,
    /^замечательно[!.\s]*$/i,
    /^прекрасно[!.\s]*$/i,
    /^великолепно[!.\s]*$/i,
    /^молодец[!.\s]*$/i,
    /^хорошо\s+сделано/i,
    /^ты\s+лучш/i,
  ],

  // ── Как дела / статус ──
  status: [
    /^как\s+(ты|дела|жизнь|настроение|поживаешь|сам)/i,
    /^что\s+нового/i,
    /^как\s+оно/i,
    /^чем\s+занимаешься/i,
    /^how\s+are\s+you/i,
    /^what'?s\s+up/i,
    /^как\s+сам/i,
    /^ну\s+как\s+ты/i,
  ],

  // ── Кто ты / идентичность ──
  identity: [
    /^кто\s+ты/i,
    /^ты\s+кто/i,
    /^что\s+ты\s+за/i,
    /^ты\s+(бот|робот|ии|ai|искусственный)/i,
    /^who\s+are\s+you/i,
    /^are\s+you\s+(a\s+)?(bot|ai|robot)/i,
    /^ты\s+живой/i,
    /^ты\s+настоящ/i,
    /^как\s+тебя\s+зовут/i,
    /^what'?s\s+your\s+name/i,
    /^представься/i,
  ],

  // ── Что умеешь / возможности ──
  capabilities: [
    /^что\s+(ты\s+)?(умеешь|можешь|делаешь)/i,
    /^на\s+что\s+(ты\s+)?способ/i,
    /^какие\s+(у\s+тебя\s+)?возможности/i,
    /^что\s+ты\s+знаешь/i,
    /^чем\s+(ты\s+)?(можешь|мож)\s+помочь/i,
    /^help\s*[.!?]*$/i,
    /^помощь\s*[.!?]*$/i,
    /^помоги\s*[.!?]*$/i,
    /^подскажи\s*[.!?]*$/i,
    /^что\s+делать\s*[.!?]*$/i,
    /^как\s+начать\s*[.!?]*$/i,
    /^с\s+чего\s+начать\s*[.!?]*$/i,
    /^what\s+can\s+you\s+do/i,
    /^покажи\s+(команды|возможности|меню)/i,
    /^какие\s+команды/i,
    /^список\s+команд/i,
  ],

  // ── Пустые / бессмысленные сообщения ──
  empty: [
    /^[.\s!?…]+$/,
    /^(ок[ей]?|okay|ok|ладно|угу|ага|ну|да|нет|не|хм+|эм+|ммм*)\s*[.!?]*$/i,
    /^(тест|test|testing|проверка|1234?5?|hello\s+world)\s*[.!?]*$/i,
    /^ы+$/i,
    /^а+$/i,
    /^о+$/i,
    /^(lol|lmao|haha|хаха|ахах|ржу|кек)\s*$/i,
    /^[)(;:]+$/,
  ],

  // ── Комплименты / лесть ──
  compliment: [
    /^ты\s+(классн|крут|умн|хорош|молодец|гений|талант)/i,
    /^какой\s+ты\s+(умн|классн|крут)/i,
    /^you'?re?\s+(great|awesome|amazing|smart)/i,
    /^impressive/i,
    /^впечатляет/i,
    /^ничего\s+себе/i,
    /^вау/i,
    /^wow/i,
  ],

  // ── Off-topic / разговоры о жизни ──
  offtopic: [
    /^(расскажи|поговорим?|давай\s+поговорим)\s+(о\s+|про\s+)?(жизн|погод|фильм|музык|книг|кот|собак)/i,
    /^какая\s+погода/i,
    /^расскажи\s+(анекдот|шутк|историю|сказку)/i,
    /^пошути/i,
    /^поиграем/i,
    /^давай\s+поиграем/i,
    /^tell\s+me\s+(a\s+)?joke/i,
    /^sing/i,
    /^спой/i,
    /^какой\s+сегодня\s+день/i,
    /^сколько\s+времени/i,
    /^который\s+час/i,
  ],
};

/**
 * Категории, безопасные для перехвата даже после ответа ассистента.
 * Остальные (thanks, empty, compliment, status, identity, capabilities)
 * после ответа ассистента НЕ перехватываются — могут быть follow-up.
 */
const SAFE_AFTER_ASSISTANT = new Set(['greeting', 'farewell', 'offtopic']);

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
  for (const [type, patterns] of Object.entries(PATTERNS)) {
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
  if (lastMsg?.role === 'assistant' && !SAFE_AFTER_ASSISTANT.has(matchedType)) {
    return null; // → Claude (возможный follow-up)
  }

  const response = buildResponse(matchedType, cabinet, topCommands);
  return response ? { type: matchedType, response } : null;
}
