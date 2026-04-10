/**
 * PSY — поведенческая психология UX.
 * Центральный модуль для всех PSY-фич:
 *   PSY-1: Next Steps (suggestion chips)
 *   PSY-2: Random Insights (факты при загрузке)
 *   PSY-3: Progress Indicator (фазы генерации)
 *   PSY-5: Milestones + эмпатичные ошибки
 */
import { get } from 'svelte/store';
import { createPersistentStore } from '$lib/store.js';

// ═════════════════���════════════════════════════════════
// PSY-1: NEXT STEPS — routing table + suggestion chips
// ════════════════════════════════════════���═════════════

/**
 * Routing table: после работы в кабинете X → предложить кабинеты Y.
 * Ключ = cabinet_id, значение = массив {id, label, reason}.
 * @type {Record<string, Array<{id: string, label: string, reason: string}>>}
 */
export const NEXT_STEPS = {
  'media-analyst': [
    { id: 'communication-analyst', label: 'Анализ коммуникаций', reason: 'Оценить медиаполе' },
    { id: 'communication-strategist', label: 'Стратегия', reason: 'Разработать план' },
    { id: 'social-listening', label: 'Соцсети', reason: 'Мониторинг реакций' },
  ],
  'communication-analyst': [
    { id: 'communication-strategist', label: 'Стратегия', reason: 'На основе анализа' },
    { id: 'creative-director', label: 'Креативный директор', reason: 'Создать концепцию' },
  ],
  'communication-strategist': [
    { id: 'creative-director', label: 'Креативный директор', reason: 'Реализовать стратегию' },
    { id: 'copywriter', label: 'Копирайтер', reason: 'Написать тексты' },
  ],
  'creative-director': [
    { id: 'copywriter', label: 'Копирайтер', reason: 'Тексты по брифу' },
    { id: 'art-director', label: 'Арт-директор', reason: 'Визуальная концепция' },
    { id: 'focus-groups', label: 'Фокус-группы', reason: 'Протестировать идею' },
  ],
  'copywriter': [
    { id: 'art-director', label: 'Арт-директор', reason: 'Визуалы к текстам' },
    { id: 'lawyer-advertising', label: 'Юрист — Реклама', reason: 'Проверить текст' },
    { id: 'focus-groups', label: 'Фокус-группы', reason: 'Тестирование' },
  ],
  'art-director': [
    { id: 'focus-groups', label: 'Фокус-группы', reason: 'Тестирование визуала' },
    { id: 'lawyer-advertising', label: 'Юрист — Реклама', reason: 'Проверить макет' },
    { id: 'copywriter', label: 'Копирайтер', reason: 'Тексты к визуалу' },
  ],
  'focus-groups': [
    { id: 'creative-director', label: 'Креативный директор', reason: 'Доработать по фидбэку' },
    { id: 'copywriter', label: 'Копирайтер', reason: 'Скорректировать тексты' },
  ],
  'social-listening': [
    { id: 'media-analyst', label: 'Медиа-аналитик', reason: 'Глубокий анализ' },
    { id: 'communication-strategist', label: 'Стратегия', reason: 'Реагирование' },
  ],
  'lawyer-contracts': [
    { id: 'lawyer-claims', label: 'Юрист — Претензии', reason: 'Риски по договору' },
  ],
  'lawyer-claims': [
    { id: 'lawyer-contracts', label: 'Юрист — Договоры', reason: 'Скорректировать договор' },
  ],
  'lawyer-advertising': [
    { id: 'copywriter', label: 'Копирайтер', reason: 'Исправить замечания' },
    { id: 'art-director', label: 'Арт-директор', reason: 'Скорректировать макет' },
  ],
  'doc-master': [],
  'econometrist': [
    { id: 'communication-strategist', label: 'Стратегия', reason: 'На основе данных' },
    { id: 'media-analyst', label: 'Медиа-аналитик', reason: 'Контекст рынка' },
  ],
  // ── Econometrica pipeline ──
  'data-model': [
    { id: 'analysis', label: 'Анализ', reason: 'Декомпозиция и оптимизация бюджета' },
  ],
  'analysis': [
    { id: 'reporting', label: 'Отчёты', reason: 'Executive Summary для руководства' },
  ],
  'reporting': [],
};

/**
 * Получить next steps для кабинета.
 * @param {string} cabinetId
 * @returns {Array<{id: string, label: string, reason: string}>}
 */
export function getNextSteps(cabinetId) {
  return NEXT_STEPS[cabinetId] || [];
}

// ════════════════════════════════════════════���═════════
// PSY-2: RANDOM INSIGHTS — факты из методологий
// ═══════════════════���═══════════════════════════════���══

/** @type {Record<string, string[]>} */
const INSIGHTS = {
  'media-analyst': [
    'Медиааналитика выявляет не только что говорят, но и что замалчивают',
    'Тональность упоминаний важнее их количества',
    'Share of Voice — один из ключевых KPI медиаприсутствия',
    'Пик информационного повода — первые 72 часа',
  ],
  'communication-analyst': [
    'Самые эффективные сообщения решают конкретную проблему аудитории',
    'Анализ конкурентных коммуникаций — основа дифференциации',
    'Восприятие бренда формируется за 7 секунд',
    'Консистентность сообщений увеличивает узнаваемость на 80%',
  ],
  'communication-strategist': [
    'Стратегия без тактики — мечта, тактика без стратегии — хаос',
    'Лучшие стратегии умещаются на одной странице',
    'PESO-модель: Paid, Earned, Shared, Owned — четыре канала влияния',
    'Стратегическое сообщение работает, когда его можно пересказать за 10 секунд',
  ],
  'creative-director': [
    'Сильный бриф — 80% успеха креативной работы',
    'Лучшие идеи рождаются на стыке инсайта и ограничений',
    'Креативная концепция должна работать в любом формате — от баннера до ТВ',
    'Правило трёх: не больше 3 ключевых сообщений в одной кампании',
  ],
  'copywriter': [
    'Заголовок читают в 5 раз чаще, чем основной текст',
    'Активный залог делает текст на 20-30% убедительнее',
    'Идеальная длина предложения для рекламы — 8-12 слов',
    'Call-to-action с глаголом действия повышает конверсию',
  ],
  'art-director': [
    'Визуальная иерархия направляет взгляд за 3 секунды',
    'Правило 60-30-10: основной цвет, вторичный, акцент',
    'Белое пространство — не пустота, а инструмент фокусировки',
    'Контраст — главный инструмент привлечения внимания',
  ],
  'focus-groups': [
    'Оптимальный размер фокус-группы — 6-8 человек',
    'Первые 5 минут определяют динамику всей дискуссии',
    'Невербальные реакции часто информативнее вербальных',
    'Хороший модератор задаёт вопросы, а не даёт ответы',
  ],
  'social-listening': [
    'Пользователи делятся негативным опытом в 2 раза чаще, чем позитивным',
    'Скорость реакции на упоминание влияет на лояльность',
    'Микроинфлюенсеры дают в 7 раз больше вовлечённости, чем макро',
    'Эмодзи в социальных сетях повышают engagement на 25%',
  ],
  // ── Econometrica: insights при ожидании MCMC (Variable Rewards + Labor Illusion) ──
  'data-model': [
    'Закон убывающей отдачи: удвоение бюджета канала НИКОГДА не удваивает продажи',
    'Bayesian MCMC даёт распределение ROI, а не точку — вы видите уверенность, а не иллюзию точности',
    'Adstock ТВ: рекламный ролик работает 2-8 недель после окончания флайта',
    'Geometric adstock (digital): мгновенный пик, быстрый спад. Weibull (TV): отложенный пик, медленный спад',
    'MMM изобрели в 1960-х для ТВ-рекламы. Тогда считали вручную на перфокартах',
    'Binet & Field: бренды с SOV > SOM растут. +10% ESOV = +0.5% доли рынка',
    'R²=0.82 означает "82% вариации объяснено". Не "модель верна на 82%"',
    'PyMC-Marketing: байесовский подход работает даже с 30 наблюдениями, если priors правильные',
  ],
  'analysis': [
    'Share of Spend vs Share of Effect — самая важная таблица для CMO',
    'Marginal ROI важнее среднего: средний говорит о прошлом, маргинальный — о будущем',
    'Response curves показывают точку насыщения — после неё каждый рубль приносит всё меньше',
    'Оптимизация сплита может дать +10-15% продаж при ТОМ ЖЕ бюджете',
    'What-if: вместо "попробуем" → "модель предсказывает +12% при таком сплите"',
    'Simpson\'s Paradox: канал может быть эффективным в целом, но неэффективным в каждом сегменте',
  ],
  'reporting': [
    'Pyramid Principle: главный вывод — первым. Детали — для тех, кто хочет копнуть глубже',
    'CMO тратит на отчёт 90 секунд. Вывод должен быть на первой странице',
    'Эластичность awareness→sales нелинейна — есть оптимум, после которого рост замедляется',
    'Лучший отчёт — тот, после которого принимают решение, а не просят ещё данных',
    'Awareness без consideration — иллюзия. S-кривая покажет порог реальных покупок',
  ],
  'lawyer-contracts': [
    'Недействительная оговорка не делает недействительным весь договор',
    'Преамбула договора — контекст для толкования спорных условий',
    'Существенные условия — то, без чего договор не считается заключённым',
    'Force majeure не освобождает от обязательства, а приостанавливает его',
  ],
  'lawyer-claims': [
    'Досудебная претензия — обязательный этап для большинства споров',
    'Срок исковой давности — 3 года по общему правилу',
    'Правильная фиксация нарушения — основа успешной претензии',
    'Мировое соглашение экономит в среднем 60% от судебных расходов',
  ],
  'lawyer-advertising': [
    'Реклама без маркировки — штраф до 500 000 рублей',
    'Слово "лучший" в рекламе требует документального подтверждения',
    'Сравнительная реклама допустима, но с ограничениями',
    'Скрытая реклама запрещена Законом о рекламе (ст. 7)',
  ],
  'doc-master': [
    'Хорошая документация экономит до 40% времени команды',
    'README — витрина проекта, первые 3 строки решают всё',
    'Документация, которую не обновляют, хуже её отсутствия',
    'Один скриншот заменяет 100 слов в технической документации',
  ],
  'econometrist': [
    'Корреляция не означает причинно-следственную связь',
    'Модель хороша не когда идеально подогнана, а когда предсказывает',
    'Мультиколлинеарность — тихий убийца регрессионных моделей',
    'R-квадрат > 0.9 в маркетинге — повод насторожиться, а не радоваться',
  ],
};

/** Универсальные инсайты — если для кабинета нет специфических */
const GENERIC_INSIGHTS = [
  'AI лучше всего работает с чёткими и конкретными заданиями',
  'Контекст из загруженных файлов значительно повышает качество результата',
  'Сложную задачу лучше разбить на несколько простых запросов',
  'Уточняющие вопросы после первого ответа — нормальная практика',
];

/** Продвинутые инсайты — после 10+ запросов к кабинету
 * @type {Record<string, string[]>} */
const ADVANCED_INSIGHTS = {
  'media-analyst': [
    'Анализ тональности без контекста отрасли даёт до 30% ложных срабатываний',
    'Лучшие медиааналитики измеряют не coverage, а impact на бизнес-метрики',
  ],
  'communication-strategist': [
    'Стратегия, которую нельзя объяснить стажёру за 2 минуты, слишком сложна для реализации',
    'Message House без proof points — декларация, не стратегия',
  ],
  'creative-director': [
    'Креативная концепция, которая не вызывает дискомфорта — скорее всего, безопасная и неэффективная',
    'Лучший тест идеи: можете ли вы описать её одним предложением без "и"?',
  ],
  'copywriter': [
    'A/B тесты показывают: конкретные цифры в заголовках дают +37% CTR',
    'Правило Хемингуэя: если можно убрать слово без потери смысла — убирайте',
  ],
  'art-director': [
    'Если нужно объяснять макет словами — макет не работает',
    'Mobile-first не значит "уменьшить десктоп" — это другое мышление',
  ],
  'lawyer-advertising': [
    'ФАС штрафует чаще за некорректное сравнение, чем за отсутствие маркировки',
    'Рекламные акции с условиями мелким шрифтом — системный риск',
  ],
  // ── Econometrica advanced insights ──
  'data-model': [
    'Информативные priors (Bayesian) — это не "подгонка", а использование экспертного знания. Uninformative priors = притворство, что вы ничего не знаете',
    'NUTS sampler > Metropolis по скорости сходимости. Если есть C-компилятор — используйте NUTS',
  ],
  'analysis': [
    'Omitted Variable Bias: если не включить дистрибуцию в модель, TV "украдёт" её эффект — ROI TV будет завышен',
    'Мультиколлинеарность: если TV и OOH ходят вместе (корр >0.8), модель не может их разделить. Решение: объединить или использовать ridge priors',
  ],
  'reporting': [
    'Модель — это инструмент мышления, не оракул. Доверительные интервалы — не погрешность, а мера нашего незнания',
    'Три уровня рекомендации: ВЫСОКАЯ (данные + логика), СРЕДНЯЯ (модель), НИЗКАЯ (гипотеза)',
  ],
};

/**
 * Получить случайный инсайт для кабинета.
 * PSY-11: с вероятностью ~40% вернёт null (variable reward).
 * После 10+ запросов — шанс продвинутого инсайта.
 * @param {string} cabinetId
 * @param {boolean} [forceShow=false] гарантировать показ (для empty state)
 * @returns {string|null}
 */
export function getRandomInsight(cabinetId, forceShow = false) {
  // Variable reward: показываем не каждый раз
  if (!forceShow && Math.random() > 0.6) return null;

  const data = get(milestones);
  const cabinetUses = data.cabinetRequests[cabinetId] || 0;

  // После 10+ запросов — 40% шанс продвинутого инсайта
  if (cabinetUses >= 10 && Math.random() < 0.4) {
    const advanced = ADVANCED_INSIGHTS[cabinetId];
    if (advanced && advanced.length > 0) {
      return advanced[Math.floor(Math.random() * advanced.length)];
    }
  }

  const pool = INSIGHTS[cabinetId] || GENERIC_INSIGHTS;
  return pool[Math.floor(Math.random() * pool.length)];
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
  const data = get(milestones);
  const cabinetUses = data.cabinetRequests[cabinetId] || 0;
  const totalUses = data.totalRequests;

  // Первый визит в кабинет
  if (cabinetUses === 0 && totalUses > 0) {
    return { text: 'Первый раз в этом кабинете — загрузите файлы и отправьте задание', isPersonal: true };
  }

  // Редкий пользователь (мало запросов к этому кабинету)
  if (cabinetUses > 0 && cabinetUses < 3 && totalUses > 20) {
    return { text: 'Вы здесь нечасто — попробуйте разные команды справа', isPersonal: true };
  }

  // Частый пользователь этого кабинета — подсказать next steps
  if (cabinetUses >= 10) {
    const next = NEXT_STEPS[cabinetId];
    if (next && next.length > 0) {
      const suggestion = next[Math.floor(Math.random() * next.length)];
      return { text: `Совет: после работы здесь попробуйте «${suggestion.label}» — ${suggestion.reason.toLowerCase()}`, isPersonal: true };
    }
  }

  return null;
}

// ══════════════════════════════════════════════════════
// PSY-3: PROGRESS INDICATOR — фазы генерации
// ═══════════════════════════════════════════════���══════

/**
 * Фазы AI-генерации с примерным таймингом (fallback).
 * @type {Array<{label: string, minSec: number}>}
 */
export const PROGRESS_PHASES = [
  { label: 'Анализирую контекст...', minSec: 0 },
  { label: 'Подготавливаю рабочее пространство...', minSec: 3 },
  { label: 'Формирую стратегию ответа...', minSec: 8 },
  { label: 'Генерирую результат...', minSec: 15 },
  { label: 'Финализирую и форматирую...', minSec: 30 },
];

// ══════════════════════════════════════════════════════
// PSY-3+: CABINET-SPECIFIC PHASES — domain-specific прогресс
// ══════════════════════════════════════════════════════

/**
 * Создать массив фаз из 5 глаголов.
 * @param {string[]} verbs — 5 строк без "..."
 * @returns {Array<{label: string, minSec: number}>}
 */
function makePhases(verbs) {
  const timings = [0, 3, 8, 15, 30];
  return verbs.map((v, i) => ({ label: `${v}...`, minSec: timings[i] }));
}

/** @type {Record<string, Array<{label: string, minSec: number}>>} */
const CABINET_PHASES = {
  'media-analyst': makePhases([
    'Сканирую медиаполе', 'Оцениваю тональность', 'Сравниваю с бенчмарками',
    'Формирую инсайты', 'Готовлю рекомендации',
  ]),
  'communication-analyst': makePhases([
    'Анализирую коммуникации', 'Оцениваю эффективность каналов', 'Строю коммуникационную карту',
    'Выявляю закономерности', 'Готовлю рекомендации',
  ]),
  'communication-strategist': makePhases([
    'Изучаю контекст', 'Анализирую аудиторию', 'Разрабатываю стратегию',
    'Прорабатываю тактику', 'Оформляю документ',
  ]),
  'creative-director': makePhases([
    'Анализирую контекст бренда', 'Генерирую идеи', 'Развиваю концепцию',
    'Прорабатываю детали', 'Оформляю бриф',
  ]),
  'copywriter': makePhases([
    'Изучаю бриф', 'Подбираю тон и стиль', 'Пишу текст',
    'Шлифую формулировки', 'Финальная вычитка',
  ]),
  'art-director': makePhases([
    'Анализирую визуальный контекст', 'Подбираю стилистику', 'Разрабатываю концепцию',
    'Прорабатываю детали', 'Финализирую макет',
  ]),
  'focus-groups': makePhases([
    'Формирую сегменты', 'Готовлю гайд обсуждения', 'Моделирую реакции',
    'Анализирую паттерны', 'Формирую выводы',
  ]),
  'social-listening': makePhases([
    'Сканирую социальные сети', 'Анализирую упоминания', 'Оцениваю sentiment',
    'Выявляю тренды', 'Формирую отчёт',
  ]),
  'lawyer-contracts': makePhases([
    'Изучаю документ', 'Проверяю существенные условия', 'Анализирую риски',
    'Формирую замечания', 'Готовлю заключение',
  ]),
  'lawyer-claims': makePhases([
    'Изучаю обстоятельства', 'Анализирую правовую базу', 'Оцениваю перспективы',
    'Формирую позицию', 'Готовлю документ',
  ]),
  'lawyer-advertising': makePhases([
    'Проверяю рекламные материалы', 'Сверяю с ФЗ «О рекламе»', 'Анализирую риски ФАС',
    'Формирую рекомендации', 'Готовлю заключение',
  ]),
  'econometrist': [
    { label: 'Загружаю данные...', minSec: 0 },
    { label: 'Строю байесовскую модель...', minSec: 10 },
    { label: 'MCMC-сэмплирование...', minSec: 30 },
    { label: 'Проверяю конвергенцию...', minSec: 120 },
    { label: 'Рассчитываю ROI и декомпозицию...', minSec: 300 },
    { label: 'Оформляю результаты...', minSec: 600 },
  ],
  'doc-master': makePhases([
    'Анализирую структуру', 'Обрабатываю содержание', 'Форматирую документ',
    'Проверяю качество', 'Финализирую',
  ]),
};

/**
 * Получить текущую фазу по прошедшему времени.
 * @param {number} elapsedSec - секунды с начала генерации
 * @param {string} [cabinetId] - ID кабинета для domain-specific фаз
 * @returns {{label: string, phaseIndex: number, totalPhases: number}}
 */
export function getCurrentPhase(elapsedSec, cabinetId) {
  const phases = (cabinetId && CABINET_PHASES[cabinetId]) || PROGRESS_PHASES;
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
  'media-analyst': 600_000,  // 10 min — multi-phase pipeline manages its own phases
  'econometrist': 900_000,   // 15 min — MCMC sampling + PyTensor compilation on Windows
  // Econometrica cabinets
  'data-model': 900_000,     // 15 min — MCMC training
  'analysis': 300_000,       // 5 min — optimization + scenarios
  'reporting': 300_000,      // 5 min — Claude report generation
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
// PSY-5: MILESTONES — достижения + session summary
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
  // Deep copy — не мутируем объект store напрямую
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
    tip: 'Подождите минуту — обычно это проходит быстро. Ваш запрос не потерялся.',
  },
  'CL-005': {
    emoji: '\u26A1',
    message: 'Сервер временно недоступен',
    tip: 'Высокая нагрузка на серверах Claude. Попробуйте через пару минут.',
  },
  'CL-006': {
    emoji: '\uD83D\uDD11',
    message: 'Проблема с авторизацией',
    tip: 'Проверьте лицензию в настройках. Если проблема повторяется — обратитесь в поддержку.',
  },
  'CL-007': {
    emoji: '\uD83C\uDF10',
    message: 'Нет подключения к серверу',
    tip: 'Проверьте интернет-соединение. Как только связь восстановится — всё заработает.',
  },
  'CL-008': {
    emoji: '\uD83D\uDEE0\uFE0F',
    message: 'Что-то пошло не так',
    tip: 'Попробуйте повторить запрос. Если ошибка повторяется — очистите чат и начните заново.',
  },
};

/**
 * Преобразовать сухую ошибку Claude в эмпатичное сообщение.
 * @param {string} errorText — исходный текст ошибки
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

// ════════════════════════════════════════════════════════
// PSY-4: WORKFLOW CELEBRATION — утилиты
// ═══════════════════════════════════════════════════��══

/**
 * Оценить сэкономленное время по количеству шагов workflow.
 * Базовая оценка: каждый кабинет экономит ~45 минут ручной работы.
 * @param {number} stepCount
 * @param {number} executionTimeSec — реальное время выполнения
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
// PSY-13: RESPONSE ACTIONS — cabinet-aware quick actions
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
// PSY-9: CABINET MASTERY — счётчик на карточках
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
// PSY-8: SESSION ARC — трекинг сессии кабинета
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
  // Валидация: если startTs старше 24 часов — сессия stale, игнорируем
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
