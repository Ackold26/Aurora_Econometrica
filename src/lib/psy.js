/**
 * PSY - поведенческая психология UX.
 * Центральный модуль для всех PSY-фич:
 *   PSY-1: Next Steps (suggestion chips)
 *   PSY-2: Random Insights (факты при загрузке)
 *   PSY-3: Progress Indicator (фазы генерации)
 *   PSY-5: Milestones + эмпатичные ошибки
 */
import { get } from 'svelte/store';
import { createPersistentStore, cabinetOnboarding } from '$lib/store.js';

// ── Data (loaded from content pack) ──

/** @type {Record<string, Array<{id: string, label: string, reason: string}>>} */
let _nextSteps = {};
/** @type {Record<string, string[]>} */
let _insights = {};
/** @type {Record<string, string[]>} */
let _advancedInsights = {};
/** @type {Array<{label: string, minSec: number}>} */
let _progressPhases = [];
/** @type {Record<string, Array<{label: string, minSec: number}>>} */
let _cabinetPhases = {};

/**
 * Initialize PSY data from content pack JSON.
 * Called once from +layout.svelte during app startup.
 * @param {any} data - parsed psy-data.json
 */
export function initPsyData(data) {
  if (data) {
    _nextSteps = data.nextSteps || {};
    _insights = data.insights || {};
    _advancedInsights = data.advancedInsights || {};
    _progressPhases = data.progressPhases || [];
    _cabinetPhases = data.cabinetPhases || {};
  }
}

// ═════════════════════════════════════════════════════
// PSY-1: NEXT STEPS - routing table + suggestion chips
// ═════════════════════════════════════════════════════

/**
 * Получить next steps для кабинета.
 * @param {string} cabinetId
 * @returns {Array<{id: string, label: string, reason: string}>}
 */
export function getNextSteps(cabinetId) {
  return _nextSteps[cabinetId] || [];
}

// ══════════════════════════════════════════════════════
// PSY-2: RANDOM INSIGHTS - факты из методологий
// ══════════════════════════════════════════════════════

/**
 * Получить случайный инсайт для кабинета.
 * PSY-11: с вероятностью ~40% вернёт null (variable reward).
 * После 10+ запросов - шанс продвинутого инсайта.
 * @param {string} cabinetId
 * @param {boolean} [forceShow=false] гарантировать показ (для empty state)
 * @returns {string|null}
 */
export function getRandomInsight(cabinetId, forceShow = false) {
  // Variable reward: показываем не каждый раз
  if (!forceShow && Math.random() > 0.6) return null;

  const data = get(milestones);
  const cabinetUses = data.cabinetRequests[cabinetId] || 0;

  // После 10+ запросов - 40% шанс продвинутого инсайта
  if (cabinetUses >= 10 && Math.random() < 0.4) {
    const advanced = _advancedInsights[cabinetId];
    if (advanced && advanced.length > 0) {
      return advanced[Math.floor(Math.random() * advanced.length)];
    }
  }

  const pool = _insights[cabinetId] || _insights['_generic'] || [];
  return pool[Math.floor(Math.random() * pool.length)] || null;
}

// ══════════════════════════════════════════════════════
// PSY-6: TIME-AWARE GREETING
// ══════════════════════════════════════════════════════

/**
 * Получить time-aware приветствие.
 * @returns {string}
 */
export function getTimeGreeting() {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return 'Доброе утро';
  if (h >= 12 && h < 17) return 'Добрый день';
  if (h >= 17 && h < 22) return 'Добрый вечер';
  return 'Работаем допоздна';
}

/**
 * Получить usage-aware подсказку для кабинета.
 * @param {string} cabinetId
 * @returns {{text: string, isPersonal: boolean}|null}
 */
export function getUsageHint(cabinetId) {
  // Suppress during active onboarding - component provides its own guidance
  const onbState = get(cabinetOnboarding);
  const cab = onbState[cabinetId];
  if (cab && !cab.completed) return null;

  const data = get(milestones);
  const cabinetUses = data.cabinetRequests[cabinetId] || 0;
  const totalUses = data.totalRequests;

  // Первый визит в кабинет
  if (cabinetUses === 0 && totalUses > 0) {
    return { text: 'Первый раз в этом кабинете - загрузите файлы и отправьте задание', isPersonal: true };
  }

  // Редкий пользователь (мало запросов к этому кабинету)
  if (cabinetUses > 0 && cabinetUses < 3 && totalUses > 20) {
    return { text: 'Вы здесь нечасто - попробуйте разные команды справа', isPersonal: true };
  }

  // Частый пользователь этого кабинета - подсказать next steps
  if (cabinetUses >= 10) {
    const next = _nextSteps[cabinetId];
    if (next && next.length > 0) {
      const suggestion = next[Math.floor(Math.random() * next.length)];
      return { text: `Совет: после работы здесь попробуйте «${suggestion.label}» - ${suggestion.reason.toLowerCase()}`, isPersonal: true };
    }
  }

  return null;
}

// ══════════════════════════════════════════════════════
// PSY-3: PROGRESS INDICATOR - фазы генерации
// ══════════════════════════════════════════════════════

/**
 * Получить текущую фазу по прошедшему времени.
 * @param {number} elapsedSec - секунды с начала генерации
 * @param {string} [cabinetId] - ID кабинета для domain-specific фаз
 * @returns {{label: string, phaseIndex: number, totalPhases: number}}
 */
export function getCurrentPhase(elapsedSec, cabinetId) {
  const phases = (cabinetId && _cabinetPhases[cabinetId]) || _progressPhases;
  if (!phases || phases.length === 0) {
    return { label: 'Обработка...', phaseIndex: 0, totalPhases: 1 };
  }
  let phaseIndex = 0;
  for (let i = phases.length - 1; i >= 0; i--) {
    if (elapsedSec >= phases[i].minSec) {
      phaseIndex = i;
      break;
    }
  }
  return {
    label: phases[phaseIndex].label,
    phaseIndex,
    totalPhases: phases.length,
  };
}

// ══════════════════════════════════════════════════════
// Pipeline progress + configurable safety timeout
// ══════════════════════════════════════════════════════

/** @type {Record<string, number>} Safety timeout per cabinet (ms). Default 90s. */
const SAFETY_TIMEOUTS = {
  'default': 90_000,
  'media-analyst': 600_000,  // 10 min - multi-phase pipeline manages its own phases
  'econometrist': 900_000,   // 15 min - MCMC sampling + PyTensor compilation on Windows
};

/**
 * Get safety timeout for a cabinet.
 * @param {string} cabinetId
 * @returns {number} timeout in milliseconds
 */
export function getSafetyTimeout(cabinetId) {
  return SAFETY_TIMEOUTS[cabinetId] || SAFETY_TIMEOUTS['default'];
}

/** @type {Record<string, Array<{label: string, minSec: number}>>} */
const PIPELINE_PHASES = {
  'map': [
    { label: 'Сканирую структуру презентации...', minSec: 0 },
    { label: 'Определяю тематические блоки...', minSec: 5 },
    { label: 'Строю карту слайдов...', minSec: 12 },
  ],
  'detail': [
    { label: 'Анализирую данные слайдов...', minSec: 0 },
    { label: 'Формирую комментарии...', minSec: 8 },
    { label: 'Проверяю бенчмарки...', minSec: 20 },
    { label: 'Пишу рекомендации...', minSec: 35 },
  ],
  'synthesis': [
    { label: 'Формирую Executive Summary...', minSec: 0 },
    { label: 'Строю межтематические мосты...', minSec: 10 },
    { label: 'Приоритизирую рекомендации...', minSec: 20 },
    { label: 'Финализирую документ...', minSec: 30 },
  ],
};

/**
 * Get pipeline phase label for multi-phase analytics progress.
 * @param {string} phaseName - "map" | "detail" | "synthesis"
 * @param {number} elapsedSec - seconds since this pipeline phase started
 * @param {number} [chunkIndex] - current chunk 0-based (for detail)
 * @param {number} [totalChunks] - total chunks
 * @returns {{label: string, phaseIndex: number, totalPhases: number}}
 */
export function getPipelinePhase(phaseName, elapsedSec, chunkIndex, totalChunks) {
  const phases = PIPELINE_PHASES[phaseName] || PIPELINE_PHASES['detail'];
  let idx = 0;
  for (let i = phases.length - 1; i >= 0; i--) {
    if (elapsedSec >= phases[i].minSec) { idx = i; break; }
  }
  let label = phases[idx].label;
  if (phaseName === 'detail' && (totalChunks || 0) > 1) {
    label = `Чанк ${(chunkIndex || 0) + 1}/${totalChunks}: ${label}`;
  }
  return { label, phaseIndex: idx, totalPhases: phases.length };
}

// ══════════════════════════════════════════════════════
// PSY-5: MILESTONES - достижения + session summary
// ══════════════════════════════════════════════════════

/**
 * @typedef {{
 *   totalRequests: number,
 *   cabinetRequests: Record<string, number>,
 *   firstRequestTs: number|null,
 *   achievements: string[]
 * }} MilestoneData
 */

/** @type {import('svelte/store').Writable<MilestoneData>} */
export const milestones = createPersistentStore('ai-agency-milestones', {
  totalRequests: 0,
  cabinetRequests: {},
  firstRequestTs: null,
  achievements: [],
});

/**
 * @typedef {{id: string, title: string, description: string, threshold: number}} Achievement
 */

/** @type {Achievement[]} */
const ACHIEVEMENTS = [
  { id: 'first-request', title: 'Первый шаг', description: 'Отправлен первый запрос', threshold: 1 },
  { id: 'ten-requests', title: 'Набираю обороты', description: '10 запросов выполнено', threshold: 10 },
  { id: 'fifty-requests', title: 'Опытный пользователь', description: '50 запросов выполнено', threshold: 50 },
  { id: 'hundred-requests', title: 'Профессионал', description: '100 запросов выполнено', threshold: 100 },
];

/**
 * Зарегистрировать запрос и вернуть новое достижение (если есть).
 * @param {string} cabinetId
 * @returns {{title: string, description: string}|null}
 */
export function trackRequest(cabinetId) {
  const prev = get(milestones);
  // Deep copy - не мутируем объект store напрямую
  const totalRequests = prev.totalRequests + 1;
  const cabinetRequests = { ...prev.cabinetRequests, [cabinetId]: (prev.cabinetRequests[cabinetId] || 0) + 1 };
  const firstRequestTs = prev.firstRequestTs || Date.now();
  const achievements = [...prev.achievements];

  let newAchievement = null;
  for (const a of ACHIEVEMENTS) {
    if (totalRequests === a.threshold && !achievements.includes(a.id)) {
      achievements.push(a.id);
      newAchievement = { title: a.title, description: a.description };
      break;
    }
  }

  milestones.set({ totalRequests, cabinetRequests, firstRequestTs, achievements });
  return newAchievement;
}

// ══════════════════════════════════════════════════════
// PSY-5: ЭМПАТИЧНЫЕ ОШИБКИ
// ══════════════════════════════════════════════════════

/** @type {Record<string, {emoji: string, message: string, tip: string}>} */
const EMPATHETIC_ERRORS = {
  'CL-004': {
    emoji: '\u23F3',
    message: 'Сервер перегружен запросами',
    tip: 'Подождите минуту - обычно это проходит быстро. Ваш запрос не потерялся.',
  },
  'CL-005': {
    emoji: '\u26A1',
    message: 'Сервер временно недоступен',
    tip: 'Высокая нагрузка на серверах Claude. Попробуйте через пару минут.',
  },
  'CL-006': {
    emoji: '\uD83D\uDD11',
    message: 'Проблема с авторизацией',
    tip: 'Проверьте лицензию в настройках. Если проблема повторяется - обратитесь в поддержку.',
  },
  'CL-007': {
    emoji: '\uD83C\uDF10',
    message: 'Нет подключения к серверу',
    tip: 'Проверьте интернет-соединение. Как только связь восстановится - всё заработает.',
  },
  'CL-008': {
    emoji: '\uD83D\uDEE0\uFE0F',
    message: 'Что-то пошло не так',
    tip: 'Попробуйте повторить запрос. Если ошибка повторяется - очистите чат и начните заново.',
  },
};

/**
 * Преобразовать сухую ошибку Claude в эмпатичное сообщение.
 * @param {string} errorText - исходный текст ошибки
 * @returns {{emoji: string, message: string, tip: string, code: string|null}}
 */
export function getEmpathyError(errorText) {
  const codeMatch = errorText.match(/\[CL-(\d+)\]/);
  const code = codeMatch ? `CL-${codeMatch[1]}` : null;
  const empathetic = code ? EMPATHETIC_ERRORS[code] : null;

  if (empathetic) {
    return { ...empathetic, code };
  }

  return {
    emoji: '\uD83D\uDEE0\uFE0F',
    message: 'Произошла ошибка',
    tip: errorText.replace(/\[CL-\d+\]\s*/, ''),
    code,
  };
}

/**
 * Русская плюрализация: 1 шаг, 2 шага, 5 шагов, 21 шаг, 22 шага...
 * @param {number} n
 * @param {string} one - 1 (шаг)
 * @param {string} few - 2-4 (шага)
 * @param {string} many - 5-20 (шагов)
 * @returns {string}
 */
export function pluralRu(n, one, few, many) {
  const abs = Math.abs(n);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod100 >= 11 && mod100 <= 19) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

/**
 * Сообщение при загрузке файла (Endowed Progress Effect).
 * Даёт ощущение уже начатого прогресса - повышает мотивацию завершить задачу.
 * @param {number} fileCount
 * @param {string} [fileName]
 * @returns {string}
 */
export function getEndowedProgressMessage(fileCount, fileName, cabinetId = undefined) {
  if (cabinetId) {
    const onbState = get(cabinetOnboarding);
    const cab = onbState[cabinetId];
    if (cab && !cab.completed && (cab.step ?? 0) === 0) {
      return 'Файл загружен - переходим к анализу';
    }
  }
  if (fileCount === 1 && fileName) {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (ext === 'pptx') return `Презентация загружена. Этап 1 из 5 выполнен - выберите команду для анализа.`;
    if (ext === 'xlsx' || ext === 'csv') return `Данные загружены. Готово к анализу.`;
  }
  return `${fileCount} ${pluralRu(fileCount, 'файл загружен', 'файла загружено', 'файлов загружено')}. Выберите команду для работы.`;
}

// ════════════════════════════════════════════════════════
// PSY-4: WORKFLOW CELEBRATION - утилиты
// ═══════════════════════════════════════════════════��══

/**
 * Оценить сэкономленное время по количеству шагов workflow.
 * Базовая оценка: каждый кабинет экономит ~45 минут ручной работы.
 * @param {number} stepCount
 * @param {number} executionTimeSec - реальное время выполнения
 * @returns {{savedMinutes: number, savedHours: string, efficiency: string}}
 */
export function estimateSavedTime(stepCount, executionTimeSec) {
  const manualMinutes = stepCount * 45;
  const actualMinutes = Math.ceil(executionTimeSec / 60);
  const savedMinutes = Math.max(manualMinutes - actualMinutes, 0);
  const savedHours = savedMinutes >= 60
    ? `${Math.floor(savedMinutes / 60)}ч ${savedMinutes % 60}мин`
    : `${savedMinutes} мин`;

  const efficiency = manualMinutes > 0
    ? `${Math.max(0, Math.round((1 - actualMinutes / manualMinutes) * 100))}%`
    : '0%';

  return { savedMinutes, savedHours, efficiency };
}

// ══════════════════════════════════════════════════════
// PSY-13: RESPONSE ACTIONS - cabinet-aware quick actions
// ══════════════════════════════════════════════════════

/** @type {Record<string, Array<{label: string, prefix: string}>>} */
const RESPONSE_ACTIONS = {
  'default': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Переделать', prefix: 'Переделай: ' },
    { label: 'Короче', prefix: 'Сократи ' },
  ],
  'lawyer-contracts': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Дополнить', prefix: 'Добавь в документ: ' },
    { label: 'Риски', prefix: 'Выдели основные риски ' },
  ],
  'lawyer-claims': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Усилить', prefix: 'Усиль аргументацию: ' },
    { label: 'Альтернатива', prefix: 'Предложи альтернативный подход ' },
  ],
  'lawyer-advertising': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Дополнить', prefix: 'Добавь: ' },
    { label: 'Риски ФАС', prefix: 'Оцени риски ФАС ' },
  ],
  'media-analyst': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Глубже', prefix: 'Разбери подробнее: ' },
    { label: 'Рекомендации', prefix: 'Дай конкретные рекомендации ' },
  ],
  'copywriter': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Переписать', prefix: 'Перепиши в другом тоне: ' },
    { label: 'Варианты', prefix: 'Дай 3 варианта ' },
  ],
  'creative-director': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Развить', prefix: 'Развей идею: ' },
    { label: 'Альтернатива', prefix: 'Предложи альтернативу ' },
  ],
  'art-director': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Детали', prefix: 'Детализируй: ' },
    { label: 'Референсы', prefix: 'Подбери референсы ' },
  ],
  'communication-analyst': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Сравнить', prefix: 'Сравни с: ' },
    { label: 'Рекомендации', prefix: 'Дай рекомендации ' },
  ],
  'communication-strategist': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Детализировать', prefix: 'Детализируй: ' },
    { label: 'Тактика', prefix: 'Предложи тактический план ' },
  ],
  'social-listening': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Тренды', prefix: 'Покажи тренды ' },
    { label: 'Рекомендации', prefix: 'Дай рекомендации по реагированию ' },
  ],
  'econometrist': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Другая модель', prefix: 'Попробуй другую модель: ' },
    { label: 'Визуализация', prefix: 'Визуализируй результаты ' },
  ],
  'focus-groups': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Другой сегмент', prefix: 'Проведи для сегмента: ' },
    { label: 'Выводы', prefix: 'Сформулируй ключевые выводы ' },
  ],
  'doc-master': [
    { label: 'Уточнить', prefix: 'Уточни: ' },
    { label: 'Переструктурировать', prefix: 'Переструктурируй: ' },
    { label: 'Дополнить', prefix: 'Добавь раздел: ' },
  ],
};

/**
 * Получить quick actions для кабинета.
 * @param {string} [cabinetId]
 * @returns {Array<{label: string, prefix: string}>}
 */
export function getResponseActions(cabinetId) {
  return RESPONSE_ACTIONS[cabinetId || ''] || RESPONSE_ACTIONS['default'];
}

// ══════════════════════════════════════════════════════
// PSY-9: CABINET MASTERY - счётчик на карточках
// ══════════════════════════════════════════════════════

/**
 * Получить количество запросов к кабинету.
 * @param {string} cabinetId
 * @returns {number}
 */
export function getCabinetUsageCount(cabinetId) {
  const data = get(milestones);
  return data.cabinetRequests[cabinetId] || 0;
}

// ══════════════════════════════════════════════════════
// C4: CABINET MASTERY SYSTEM (Self-Determination Theory, Deci & Ryan 1985)
// Уровни мастерства создают идентичность и стремление к росту.
// ══════════════════════════════════════════════════════

/** @typedef {{ threshold: number, title: string, icon: string }} MasteryTier */

/** @type {Record<string, MasteryTier[]>} */
const CABINET_MASTERY = {
  'media-analyst':            [{ threshold: 5, title: 'Практик', icon: '📊' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'communication-analyst':    [{ threshold: 5, title: 'Практик', icon: '📡' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'communication-strategist': [{ threshold: 5, title: 'Практик', icon: '🗺️' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'social-listening':         [{ threshold: 5, title: 'Практик', icon: '🔍' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'focus-groups':             [{ threshold: 5, title: 'Практик', icon: '💬' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'creative-director':        [{ threshold: 5, title: 'Практик', icon: '🎨' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'lawyer-contracts':         [{ threshold: 5, title: 'Практик', icon: '📝' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'lawyer-claims':            [{ threshold: 5, title: 'Практик', icon: '⚖️' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'lawyer-advertising':       [{ threshold: 5, title: 'Практик', icon: '📣' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'doc-master':               [{ threshold: 5, title: 'Практик', icon: '📚' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'econometrist':             [{ threshold: 5, title: 'Практик', icon: '📈' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'copywriter':               [{ threshold: 5, title: 'Практик', icon: '✍️' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
  'art-director':             [{ threshold: 5, title: 'Практик', icon: '🖼️' }, { threshold: 20, title: 'Эксперт', icon: '🎯' }, { threshold: 50, title: 'Мастер', icon: '👑' }],
};

/**
 * Получить текущий уровень мастерства в кабинете.
 * @param {string} cabinetId
 * @returns {{ current: MasteryTier|null, next: MasteryTier|null, uses: number }|null}
 */
export function getCabinetMastery(cabinetId) {
  const tiers = CABINET_MASTERY[cabinetId];
  if (!tiers) return null;
  const uses = get(milestones).cabinetRequests[cabinetId] || 0;
  let current = null;
  let next = tiers[0];
  for (const tier of tiers) {
    if (uses >= tier.threshold) { current = tier; next = tiers[tiers.indexOf(tier) + 1] || null; }
  }
  return { current, next, uses };
}

// ══════════════════════════════════════════════════════
// PSY-8: SESSION ARC - трекинг сессии кабинета
// ══════════════════════════════════════════════════════

/** @type {import('svelte/store').Writable<{cabinetId: string|null, startTs: number, messageCount: number}>} */
export const currentSession = createPersistentStore('ai-agency-current-session', {
  cabinetId: null,
  startTs: 0,
  messageCount: 0,
});

/**
 * Начать трекинг сессии кабинета.
 * @param {string} cabinetId
 */
export function startSession(cabinetId) {
  currentSession.set({ cabinetId, startTs: Date.now(), messageCount: 0 });
}

/** Инкрементировать счётчик сообщений сессии. */
export function incrementSessionMessages() {
  const s = get(currentSession);
  currentSession.set({ ...s, messageCount: s.messageCount + 1 });
}

/**
 * Завершить сессию и вернуть summary.
 * @returns {{cabinetId: string, durationMin: number, messageCount: number, requests: number}|null}
 */
export function endSession() {
  const s = get(currentSession);
  currentSession.set({ cabinetId: null, startTs: 0, messageCount: 0 });
  if (!s.cabinetId || s.messageCount === 0) return null;
  // Валидация: если startTs старше 24 часов - сессия stale, игнорируем
  const ageMs = Date.now() - s.startTs;
  if (ageMs > 24 * 60 * 60 * 1000 || ageMs < 0) return null;
  const durationMin = Math.max(1, Math.round(ageMs / 60000));
  const requests = Math.ceil(s.messageCount / 2);
  return { cabinetId: s.cabinetId, durationMin, messageCount: s.messageCount, requests };
}

// ══════════════════════════════════════════════════════
// PSY-UX2: VARIABLE CELEBRATIONS
// ══════════════════════════════════════════════════════

/**
 * @typedef {'confetti'|'glow-pulse'|'streak'|'time-saved'|'mastery-tier'} CelebrationType
 */

/** @type {Array<{type: CelebrationType, weight: number}>} */
const CELEBRATIONS = [
  { type: 'confetti', weight: 3 },
  { type: 'glow-pulse', weight: 3 },
  { type: 'streak', weight: 2 },
  { type: 'time-saved', weight: 2 },
];

const MASTERY_TIERS = [10, 25, 50, 100, 250];

/**
 * Pick a celebration type. Mastery tier triggers on threshold counts.
 * @param {number} commandUsageCount
 * @returns {{type: CelebrationType, tier?: number}}
 */
export function pickCelebration(commandUsageCount) {
  if (MASTERY_TIERS.includes(commandUsageCount)) {
    return { type: 'mastery-tier', tier: commandUsageCount };
  }
  const totalWeight = CELEBRATIONS.reduce((sum, c) => sum + c.weight, 0);
  let r = Math.random() * totalWeight;
  for (const c of CELEBRATIONS) {
    r -= c.weight;
    if (r <= 0) return { type: c.type };
  }
  return { type: 'confetti' };
}

// ══════════════════════════════════════════════════════
// PSY-UX2: PENDING WORK (Zeigarnik Effect)
// ══════════════════════════════════════════════════════

const PENDING_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days

/**
 * Save pending (unfinished) work for a cabinet.
 * @param {string} cabinetId
 * @param {string} command
 * @param {string} preview
 */
export function savePendingWork(cabinetId, command, preview) {
  try {
    localStorage.setItem(`ai-pending-${cabinetId}`, JSON.stringify({
      command,
      preview: preview.slice(0, 100),
      ts: Date.now(),
    }));
  } catch { /* quota */ }
}

/**
 * Get pending work for a cabinet (if within TTL).
 * @param {string} cabinetId
 * @returns {{command: string, preview: string, ts: number}|null}
 */
export function getPendingWork(cabinetId) {
  try {
    const raw = localStorage.getItem(`ai-pending-${cabinetId}`);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (Date.now() - data.ts > PENDING_TTL) {
      localStorage.removeItem(`ai-pending-${cabinetId}`);
      return null;
    }
    return data;
  } catch { return null; }
}

/**
 * Clear pending work for a cabinet (after export/completion).
 * @param {string} cabinetId
 */
export function clearPendingWork(cabinetId) {
  try { localStorage.removeItem(`ai-pending-${cabinetId}`); } catch { /* ok */ }
}

// ══════════════════════════════════════════════════════
// C6: CONTEXT-AWARE POST-ANALYSIS INSIGHTS (Specificity Effect, Nisbett & Ross 1980)
// Конкретный инсайт из данных убедительнее generic фразы.
// ══════════════════════════════════════════════════════

/**
 * Нормализовать строку числа: убрать ~, ≈, пробелы, заменить запятую.
 * @param {string} s
 * @returns {number}
 */
function parseMetricValue(s) {
  return parseFloat(s.replace(/[~≈\s]/g, '').replace('−', '-').replace(',', '.'));
}

/**
 * Извлечь ключевую метрику из ответа media-analyst и вернуть конкретный инсайт.
 * Приоритет: ESOV → SOV+SOM → SOV → GRP/TRP → охват/reach → бюджет.
 *
 * @param {string} content - текст ответа ассистента
 * @param {string} cabinetId - ID кабинета
 * @returns {string|null} - инсайт ≤70 символов или null
 */
export function getContextInsight(content, cabinetId) {
  if (cabinetId !== 'media-analyst') return null;
  if (!content || content.length < 50) return null;

  // 1. ESOV явно указан (Binet & Field: ключевой предиктор роста)
  const esovMatch = content.match(/ESOV[:\s=]+([+\-−~≈]?\d+[.,]?\d*)\s*%/i);
  if (esovMatch) {
    const v = parseMetricValue(esovMatch[1]);
    if (!isNaN(v)) {
      if (v > 0) return `ESOV +${v}% - бренд опережает рынок по голосу`;
      if (v < 0) return `ESOV ${v}% - голос ниже SOM, давление конкурентов`;
      return `ESOV ≈ 0% - нейтральная медиапозиция`;
    }
  }

  // 2. SOV + SOM → вычислить ESOV
  const sovMatch = content.match(/\bSOV[:\s=]+([~≈]?\d+[.,]?\d*)\s*%/i);
  const somMatch = content.match(/\bSOM[:\s=]+([~≈]?\d+[.,]?\d*)\s*%/i);
  if (sovMatch && somMatch) {
    const sov = parseMetricValue(sovMatch[1]);
    const som = parseMetricValue(somMatch[1]);
    if (!isNaN(sov) && !isNaN(som)) {
      const esov = Math.round((sov - som) * 10) / 10;
      if (esov > 0) return `SOV ${sov}% vs SOM ${som}% → ESOV +${esov}%`;
      if (esov < 0) return `SOV ${sov}% vs SOM ${som}% → ESOV ${esov}%`;
      return `SOV = SOM ${sov}% - нейтральная позиция`;
    }
  }

  // 3. SOV (без SOM)
  if (sovMatch) {
    const v = parseMetricValue(sovMatch[1]);
    if (!isNaN(v)) {
      if (v >= 30) return `SOV ${v}% - сильное медиаприсутствие в категории`;
      if (v >= 10) return `SOV ${v}% - умеренное медиаприсутствие`;
      return `SOV ${v}% - низкий голос в категории`;
    }
  }

  // 4. GRP / TRP
  const grpMatch = content.match(/(\d[\d\s]{0,6})\s*(GRP|TRP)\b|(?:GRP|TRP)[:\s=]+(\d[\d\s]{0,6})/i);
  if (grpMatch) {
    const rawNum = ((grpMatch[1] || grpMatch[3]) ?? '').replace(/\s/g, '');
    const v = parseInt(rawNum, 10);
    const label = (grpMatch[2] || 'GRP').toUpperCase();
    if (!isNaN(v) && v > 0 && v < 100000) {
      if (v >= 500) return `${v} ${label} - высокое медиадавление`;
      if (v >= 200) return `${v} ${label} - умеренное медиадавление`;
      return `${v} ${label} - низкое медиадавление`;
    }
  }

  // 5. Охват / reach
  const reachMatch = content.match(/(?:охват|reach)[^\d]{0,25}(\d+[.,]?\d*)\s*%/i);
  if (reachMatch) {
    const v = parseMetricValue(reachMatch[1]);
    if (!isNaN(v) && v > 0 && v <= 100) {
      if (v >= 70) return `Охват ${v}% - широкое покрытие аудитории`;
      if (v >= 40) return `Охват ${v}% целевой аудитории`;
      return `Охват ${v}% - ниже рекомендуемых 60%`;
    }
  }

  // 6. Бюджет в млн ₽ / руб
  const budgetMatch = content.match(/([~≈]?\d+[.,]?\d*)\s*млн\s*(?:₽|руб)/i);
  if (budgetMatch) {
    return `Бюджет ~${budgetMatch[1]} млн ₽ выявлен в анализе`;
  }

  return null;
}
