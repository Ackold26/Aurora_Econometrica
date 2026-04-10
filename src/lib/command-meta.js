/**
 * Command metadata and cabinet categorization for Aurora AI.
 * Provides descriptions, examples, and grouping — all frontend-side.
 * CabinetCommand in Rust has only {command, label, group} — no descriptions.
 *
 * @module command-meta
 */

// ─── Cabinet Categories (for NavRail sidebar grouping) ──────────────

/** @type {Array<{name: string, ids: string[]}>} */
export const CABINET_CATEGORIES = [
  {
    name: 'КРЕАТИВНЫЕ',
    ids: ['creative-director', 'copywriter', 'art-director', 'communication-strategist', 'focus-groups'],
  },
  {
    name: 'АНАЛИТИКА',
    ids: ['media-analyst', 'communication-analyst', 'social-listening', 'econometrist'],
  },
  {
    name: 'ЮРИДИЧЕСКИЕ',
    ids: ['lawyer-contracts', 'lawyer-claims', 'lawyer-advertising'],
  },
  {
    name: 'ДОКУМЕНТЫ',
    ids: ['doc-master'],
  },
  {
    name: 'ECONOMETRICA',
    ids: ['data-model', 'analysis', 'reporting'],
  },
];

/**
 * Group cabinets by category for NavRail sidebar.
 * Cabinets not in any category go into "Другое".
 * @param {Array<{id: string, name: string, icon: string, color: string}>} cabinets
 * @returns {Array<{name: string, items: any[]}>}
 */
export function getCategorizedCabinets(cabinets) {
  const result = [];
  const placed = new Set();

  for (const cat of CABINET_CATEGORIES) {
    const items = [];
    for (const id of cat.ids) {
      const cab = cabinets.find(c => c.id === id);
      if (cab) {
        items.push(cab);
        placed.add(id);
      }
    }
    if (items.length > 0) {
      result.push({ name: cat.name, items });
    }
  }

  // Any cabinets not in categories
  const others = cabinets.filter(c => !placed.has(c.id));
  if (others.length > 0) {
    result.push({ name: 'ДРУГОЕ', items: others });
  }

  return result;
}

// ─── Command Metadata ───────────────────────────────────────────────

/**
 * @typedef {Object} CommandMeta
 * @property {string} description - Short description (1 line)
 * @property {string} [example] - Example task prompt
 * @property {string} [category] - Semantic category: create | analyze | edit | test | utility
 * @property {boolean} [needsFile] - Highlight when inbox has files
 * @property {string[]} [phases] - Per-command progress messages
 */

/** @type {Record<string, CommandMeta>} */
export const COMMAND_META = {
  // ─── lawyer-contracts (15 commands) ───
  '/contract': {
    description: 'Комплексная проверка договора: риски, условия, рекомендации',
    example: 'Проверь договор поставки с ООО "Альфа"',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю текст договора', 'Анализирую условия', 'Ищу правовые риски', 'Формирую заключение'],
  },
  '/contract-batch': { description: 'Пакетная проверка нескольких договоров', category: 'analyze', needsFile: true },
  '/contract-риски': { description: 'Быстрый анализ только рисков без полного заключения', category: 'analyze', needsFile: true },
  '/contract-counter-docx': { description: 'Редлайн-разметка правок в Word-документе', category: 'edit', needsFile: true },
  '/contract-counter': { description: 'Создание протокола разногласий к договору', category: 'edit', needsFile: true },
  '/contract-сравнить': { description: 'Сравнение двух версий договора: что изменилось', category: 'analyze', needsFile: true },
  '/contract-template': { description: 'Генерация шаблона договора по описанию сделки', category: 'create' },
  '/contract-deadlines': { description: 'Извлечение всех сроков и дедлайнов из договора', category: 'analyze', needsFile: true },
  '/contract-add-notes': { description: 'Добавление заметок и комментариев к договору', category: 'edit', needsFile: true },
  '/contract-checklist': { description: 'Экспресс чек-лист: ключевые точки проверки', category: 'analyze', needsFile: true },
  '/contract-агентский': { description: 'Специализированная проверка агентского договора', category: 'analyze', needsFile: true },
  '/contract-услуги': { description: 'Специализированная проверка договора оказания услуг', category: 'analyze', needsFile: true },
  '/contract-подрядчик': { description: 'Специализированная проверка договора подряда', category: 'analyze', needsFile: true },
  '/contract-renewal-check': { description: 'Проверка условий автопролонгации и расторжения', category: 'analyze', needsFile: true },
  '/contract-international': { description: 'Анализ международного контракта с учётом юрисдикций', category: 'analyze', needsFile: true },

  // ─── lawyer-advertising (15 commands) ───
  '/qa': {
    description: 'Проверка рекламных материалов на соответствие ФЗ «О рекламе»',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю материал', 'Проверяю требования закона', 'Ищу нарушения', 'Формирую заключение'],
  },
  '/qa-batch': { description: 'Пакетная проверка нескольких рекламных материалов', category: 'analyze', needsFile: true },
  '/qa-fix-docx': { description: 'Правки рекламного текста с отслеживанием в Word', category: 'edit', needsFile: true },
  '/qa-fix': { description: 'Верификация внесённых правок после замечаний', category: 'analyze', needsFile: true },
  '/qa-stats': { description: 'Статистика нарушений: категории, частота, тренды', category: 'analyze', needsFile: true },
  '/qa-фарма': { description: 'Проверка рекламы фармпрепаратов и БАДов', category: 'analyze', needsFile: true },
  '/qa-fmcg': { description: 'Проверка рекламы товаров повседневного спроса', category: 'analyze', needsFile: true },
  '/qa-финансы': { description: 'Проверка рекламы финансовых услуг и инструментов', category: 'analyze', needsFile: true },
  '/qa-b2b': { description: 'Проверка рекламы B2B-продуктов и услуг', category: 'analyze', needsFile: true },
  '/qa-манифест': { description: 'Проверка манифестов и имиджевых текстов', category: 'analyze', needsFile: true },
  '/qa-template': { description: 'Шаблоны безопасных формулировок для рекламы', category: 'utility' },
  '/qa-ord': { description: 'Проверка маркировки рекламы по закону об ОРД', category: 'analyze', needsFile: true },
  '/qa-platform': { description: 'Проверка соответствия правилам рекламной площадки', category: 'analyze', needsFile: true },
  '/qa-visual-brief': { description: 'Визуальный чек-лист требований к макету', category: 'create', needsFile: true },

  // ─── lawyer-claims (10 commands) ───
  '/pretension-write': {
    description: 'Составление претензии с правовым обоснованием',
    category: 'create',
    phases: ['Анализирую ситуацию', 'Подбираю правовые основания', 'Составляю текст претензии'],
  },
  '/pretension-reply': { description: 'Подготовка ответа на полученную претензию', category: 'create', needsFile: true },
  '/pretension-analyze': { description: 'Правовой анализ претензии: перспективы и риски', category: 'analyze', needsFile: true },
  '/pretension-timeline': { description: 'Хронология событий и сроков по спору', category: 'analyze', needsFile: true },
  '/nda-draft': { description: 'Составление NDA под конкретную ситуацию', category: 'create' },
  '/nda-analyze': { description: 'Анализ NDA: пробелы, риски, рекомендации', category: 'analyze', needsFile: true },
  '/nda-counter': { description: 'Протокол разногласий к NDA', category: 'edit', needsFile: true },
  '/nda-counter-docx': { description: 'Редлайн-разметка правок NDA в Word', category: 'edit', needsFile: true },
  '/settlement-plan': { description: 'План досудебного урегулирования спора', category: 'create', needsFile: true },
  '/nda-breach-response': { description: 'Стратегия реагирования на утечку по NDA', category: 'create', needsFile: true },

  // ─── copywriter (7 commands) ───
  '/write': {
    description: 'Создание текста в стиле и голосе бренда',
    example: 'Напиши пост для Telegram про запуск нового продукта',
    category: 'create',
    phases: ['Изучаю бриф', 'Подбираю тон и стиль', 'Генерирую варианты', 'Финализирую текст'],
  },
  '/adapt': { description: 'Адаптация готового текста под другой формат или канал', category: 'edit', needsFile: true },
  '/audit': { description: 'Проверка текста: стиль, грамматика, tone of voice', category: 'analyze', needsFile: true },
  '/pack': { description: 'Мультиформатный пакет текстов из одного брифа', category: 'create' },
  '/mine': { description: 'Извлечение ключевых сообщений бренда из материалов', category: 'analyze', needsFile: true },
  '/brand-setup': { description: 'Настройка голоса бренда: стиль, тон, словарь', category: 'utility' },
  '/format-add': { description: 'Добавление пользовательского формата текста', category: 'utility' },

  // ─── creative-director (9 commands) ───
  '/cycle': {
    description: 'Полный цикл: от брифа до креативных концепций',
    example: 'Разработай креативную кампанию для нового йогурта',
    category: 'create',
    phases: ['Анализирую бриф', 'Исследую аудиторию', 'Генерирую концепции', 'Оформляю презентацию'],
  },
  '/creative-audit': { description: 'Аудит существующего креатива: сильные и слабые стороны', category: 'analyze', needsFile: true },
  '/brand-memory': { description: 'Извлечение ДНК бренда из материалов и коммуникаций', category: 'analyze', needsFile: true },
  '/creative-strategy': { description: 'Креативная стратегия: инсайт, территория, Big Idea', category: 'create' },
  '/creative': { description: 'Генерация креативных концепций по брифу', category: 'create' },
  '/ad-variants': { description: 'Множество вариантов рекламных объявлений', category: 'create' },
  '/format-creative': { description: 'Адаптация креатива под конкретные форматы площадок', category: 'create' },
  '/competitive-creative': { description: 'Деконструкция креатива конкурента: приёмы и механики', category: 'analyze', needsFile: true },
  '/reference-library': { description: 'Подборка референсов и кейсов по категории', category: 'utility' },

  // ─── communication-strategist (8 commands) ───
  '/strategy': {
    description: 'Полный цикл коммуникационной стратегии',
    example: 'Разработай коммуникационную стратегию для IT-стартапа',
    category: 'create',
    phases: ['Анализирую рынок', 'Определяю позиционирование', 'Формирую сообщения', 'Строю план'],
  },
  '/positioning': { description: 'Разработка платформы позиционирования бренда', category: 'create' },
  '/brief': { description: 'Структурированный креативный бриф', category: 'create' },
  '/messages': { description: 'Messaging Framework: ключевые сообщения по аудиториям', category: 'create' },
  '/comm-audit': { description: 'Аудит текущих коммуникаций бренда: каналы, тон, охват', category: 'analyze', needsFile: true },
  '/quick-diagnostics': { description: 'Экспресс-диагностика бренда за 5 минут', category: 'analyze' },
  '/cep-audit': { description: 'Аудит точек входа в категорию (Category Entry Points)', category: 'analyze' },
  '/crisis-strategy': { description: 'Антикризисная коммуникационная стратегия', category: 'create' },

  // ─── focus-groups (7 commands) ───
  '/strategy-fg': {
    description: 'Стратегическая фокус-группа: позиционирование и восприятие',
    category: 'test',
    phases: ['Формирую состав группы', 'Провожу модерацию', 'Анализирую ответы', 'Формирую выводы'],
  },
  '/creative-fg': { description: 'Тестирование креативных материалов на фокус-группе', category: 'test', needsFile: true },
  '/concept-test': { description: 'Тест концепций: оценка привлекательности и понятности', category: 'test' },
  '/packaging-test': { description: 'Тест восприятия дизайна упаковки', category: 'test', needsFile: true },
  '/name-test': { description: 'Тест вариантов названий: ассоциации и запоминаемость', category: 'test' },
  '/ux-journey': { description: 'Тест пользовательского пути: UX, сайт, приложение', category: 'test' },
  '/message-prioritization': { description: 'Приоритизация сообщений по значимости для ЦА', category: 'test' },

  // ─── media-analyst (8 commands) ───
  '/analytics': {
    description: 'Аналитические комментарии к слайдам презентации',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю слайды', 'Выявляю тренды', 'Сравниваю с бенчмарками', 'Формирую выводы'],
  },
  '/check': { description: 'Проверка качества существующих комментариев по чек-листу', category: 'analyze', needsFile: true },
  '/action-title': { description: 'Генерация заголовков-выводов для слайдов', category: 'create', needsFile: true },
  '/executive-summary': { description: 'Executive Summary по Pyramid Principle', category: 'create', needsFile: true },
  '/bridges': { description: 'Межтематические связки между блоками презентации', category: 'create', needsFile: true },
  '/batch-analytics': { description: 'Пакетная обработка нескольких презентаций', category: 'analyze', needsFile: true },
  '/data-analysis': { description: 'Анализ сырых данных из xlsx/csv до создания слайдов', category: 'analyze', needsFile: true },
  '/benchmark': { description: 'Контекстуализация данных относительно рыночных бенчмарков', category: 'analyze' },

  // ─── communication-analyst (10 commands) ───
  '/media-monitor': {
    description: 'Мониторинг медиаполя: охват, тональность, доля голоса',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю данные мониторинга', 'Классифицирую публикации', 'Считаю метрики', 'Формирую отчёт'],
  },
  '/sentiment': { description: 'Анализ тональности публикаций и упоминаний', category: 'analyze', needsFile: true },
  '/effectiveness': { description: 'Отчёт по эффективности PR и коммуникаций', category: 'analyze', needsFile: true },
  '/competitors': { description: 'Конкурентный анализ медиаактивности', category: 'analyze', needsFile: true },
  '/key-messages': { description: 'Оценка проникновения ключевых сообщений в медиа', category: 'analyze', needsFile: true },
  '/crisis-analysis': { description: 'Анализ кризисной ситуации в медиаполе', category: 'analyze', needsFile: true },
  '/narrative-tracking': { description: 'Отслеживание нарративов и их эволюции', category: 'analyze', needsFile: true },
  '/influencer-impact': { description: 'Анализ влияния лидеров мнений на бренд', category: 'analyze', needsFile: true },
  '/pr-attribution': { description: 'Атрибуция PR-активностей к бизнес-результатам', category: 'analyze', needsFile: true },

  // ─── social-listening (9 commands) ───
  '/search-reviews': {
    description: 'Поиск и систематизация отзывов о бренде',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю данные', 'Классифицирую отзывы', 'Выявляю паттерны', 'Формирую отчёт'],
  },
  '/analyze-sentiment': { description: 'Детальный анализ тональности отзывов', category: 'analyze', needsFile: true },
  '/report': { description: 'Сводный отчёт по результатам social listening', category: 'create', needsFile: true },
  '/track-mentions': { description: 'Отслеживание упоминаний бренда в соцсетях', category: 'analyze', needsFile: true },
  '/competitors-buzz': { description: 'Анализ обсуждений конкурентов в социальных медиа', category: 'analyze', needsFile: true },
  '/crisis-alert': { description: 'Выявление и оценка кризисных сигналов', category: 'analyze', needsFile: true },
  '/jtbd-extraction': { description: 'Извлечение Jobs To Be Done из отзывов потребителей', category: 'analyze', needsFile: true },
  '/trend-detection': { description: 'Обнаружение трендов и тем в обсуждениях', category: 'analyze', needsFile: true },

  // ─── shared across analyst cabinets ───
  '/batch-analysis': { description: 'Мета-анализ нескольких блоков данных', category: 'analyze', needsFile: true },

  // ─── econometrist (9 commands) ───
  '/mmm-full': {
    description: 'Полный цикл: от сырых данных до оптимального бюджета',
    example: 'Загрузите xlsx с продажами и медиабюджетами',
    category: 'analyze',
    needsFile: true,
    phases: ['Валидирую данные', 'Строю модель', 'Декомпозирую продажи', 'Оптимизирую бюджет', 'Моделирую сценарии', 'Формирую отчёт'],
  },
  '/mmm-prepare': {
    description: 'Подготовка данных для Marketing Mix Modeling',
    category: 'utility',
    needsFile: true,
    phases: ['Читаю данные', 'Проверяю качество', 'Трансформирую переменные', 'Формирую датасет'],
  },
  '/mmm-model': { description: 'Обучение MMM-модели на подготовленных данных', category: 'analyze', needsFile: true, phases: ['Загружаю данные', 'Строю модель', 'Сэмплирую MCMC', 'Проверяю диагностику'] },
  '/mmm-decomposition': { description: 'Декомпозиция продаж по каналам и факторам', category: 'analyze', needsFile: true, phases: ['Загружаю модель', 'Рассчитываю вклады', 'Строю графики'] },
  '/mmm-optimize': { description: 'Оптимизация распределения медиабюджета', category: 'analyze', needsFile: true, phases: ['Строю response curves', 'Оптимизирую сплит', 'Сравниваю варианты'] },
  '/mmm-scenarios': { description: 'Сценарное моделирование what-if по бюджетам', category: 'analyze', needsFile: true, phases: ['Генерирую сценарии', 'Рассчитываю прогнозы', 'Сравниваю результаты'] },
  '/awareness-forecast': { description: 'Прогноз awareness по медиаплану', category: 'analyze', needsFile: true, phases: ['Читаю данные', 'Строю модель awareness', 'Прогнозирую динамику'] },
  '/awareness-to-sales': { description: 'Моделирование связи awareness → продажи', category: 'analyze', needsFile: true, phases: ['Анализирую связь', 'Строю S-кривую', 'Оцениваю эластичность'] },
  '/mmm-report': { description: 'Полный отчёт по результатам моделирования', category: 'create', needsFile: true, phases: ['Компилирую результаты', 'Формирую Executive Summary', 'Оформляю отчёт'] },

  // ─── doc-master (3 commands) ───
  '/plan-to-doc': {
    description: 'Преобразование медиаплана в юридическое приложение к договору',
    category: 'create',
    needsFile: true,
    phases: ['Читаю медиаплан', 'Форматирую в приложение', 'Проверяю реквизиты'],
  },
  '/doc-batch': { description: 'Генерация комплектов документов из шаблонов', category: 'create', needsFile: true },
  '/plan-check': { description: 'Проверка медиаплана на полноту и корректность', category: 'analyze', needsFile: true },

  // ─── art-director (10 commands) ───
  '/visual': {
    description: 'Создание визуальной концепции по брифу',
    category: 'create',
    phases: ['Анализирую бриф', 'Подбираю стилистику', 'Генерирую концепции', 'Оформляю результат'],
  },
  '/edit': { description: 'Редактирование и доработка визуальных материалов', category: 'edit', needsFile: true },
  '/logo': { description: 'Разработка концепции логотипа', category: 'create' },
  '/identity': { description: 'Полная визуальная айдентика бренда', category: 'create' },
  '/packaging': { description: 'Дизайн-концепция упаковки продукта', category: 'create' },
  '/brand-visual': { description: 'Визуальный ДНК бренда: цвета, типографика, стиль', category: 'analyze', needsFile: true },
  '/storyboard': { description: 'Раскадровка рекламного ролика', category: 'create' },

  // ─── Econometrica: data-model (4 commands) ───
  '/validate': {
    description: 'Проверка готовности данных для моделирования',
    category: 'analyze',
    needsFile: true,
    phases: ['Читаю данные', 'Проверяю структуру', 'Анализирую корреляции', 'Формирую отчёт'],
  },
  '/configure': { description: 'Предложить конфигурацию модели по данным', category: 'analyze', needsFile: true, phases: ['Анализирую столбцы', 'Определяю каналы', 'Предлагаю настройки'] },
  '/train': { description: 'Обучить байесовскую MMM-модель', category: 'analyze', needsFile: true, phases: ['Компилирую модель', 'Сэмплирую MCMC', 'Проверяю диагностику'] },
  '/diagnose': { description: 'Диагностика обученной модели', category: 'analyze', phases: ['Загружаю результаты', 'Проверяю сходимость', 'Оцениваю качество'] },

  // ─── Econometrica: analysis (4 commands) ───
  '/decompose': { description: 'Декомпозиция продаж по каналам', category: 'analyze', phases: ['Рассчитываю вклады', 'Строю waterfall', 'Формирую выводы'] },
  '/optimize': { description: 'Оптимальное распределение медиабюджета', category: 'analyze', phases: ['Строю response curves', 'Оптимизирую сплит', 'Сравниваю варианты'] },
  '/scenario': { description: 'Прогноз по медиаплану / сценарию', category: 'analyze', needsFile: true, phases: ['Загружаю медиаплан', 'Рассчитываю прогноз'] },
  '/compare': { description: 'Сравнить несколько сценариев', category: 'analyze', phases: ['Загружаю сценарии', 'Рассчитываю разницу', 'Формирую рекомендации'] },

  // ─── Econometrica: reporting (4 commands) ───
  '/awareness': { description: 'Прогноз уровня знания бренда', category: 'analyze', needsFile: true, phases: ['Строю модель awareness', 'Прогнозирую динамику', 'Анализирую ESOV'] },
  '/funnel': { description: 'Моделирование воронки media → awareness → sales', category: 'analyze', needsFile: true, phases: ['Строю S-кривую', 'Оцениваю эластичность'] },
  '/executive': { description: 'Executive Summary для руководства', category: 'create', phases: ['Компилирую результаты', 'Формирую тезисы', 'Оформляю отчёт'] },
  '/mmm-export': { description: 'Полный отчёт MMM (xlsx + docx)', category: 'create', phases: ['Собираю данные', 'Формирую отчёт', 'Экспортирую файлы'] },
};

/**
 * Get metadata for a command. Returns null if not found.
 * @param {string} command - Slash command (e.g., "/contract")
 * @returns {CommandMeta|null}
 */
export function getCommandMeta(command) {
  return COMMAND_META[command] || null;
}

/**
 * Get commands that need files (for smart highlighting).
 * @param {string} _cabinetId - Currently unused, reserved for filtering
 * @returns {string[]} Array of command strings with needsFile: true
 */
export function getFileCommands(_cabinetId) {
  return Object.entries(COMMAND_META)
    .filter(([, meta]) => meta.needsFile)
    .map(([cmd]) => cmd);
}

// ─── Product names and filtering ─────────────────────────────────────

/** @type {Record<string, string>} */
const PRODUCT_NAMES = {
  agency: 'Aurora AI - Agency',
  legal: 'Aurora AI - Legal',
  creative: 'Aurora AI - Creative',
  media: 'Aurora AI - Insights Hub',
  docmaster: 'Aurora AI - Docu-master',
  'creative-hub': 'Aurora AI - Creative Hub',
};

/**
 * Get human-readable product name.
 * @param {string} productType
 * @returns {string}
 */
export function getProductName(productType) {
  return PRODUCT_NAMES[productType] || 'Aurora AI';
}

// ─── Product-specific cabinet filtering ─────────────────────────────

/** @type {Record<string, string[]|null>} */
const PRODUCT_CABINETS = {
  legal: ['lawyer-contracts', 'lawyer-claims', 'lawyer-advertising'],
  creative: ['creative-director', 'communication-strategist', 'focus-groups', 'copywriter', 'art-director'],
  media: ['media-analyst', 'communication-analyst', 'social-listening', 'econometrist'],
  docmaster: ['doc-master'],
  econometrica: ['data-model', 'analysis', 'reporting'],
  agency: null,
  'creative-hub': null,
};

/**
 * Filter cabinets by product type. Agency/Creative Hub → all, others → subset.
 * @param {any[]} cabinets
 * @param {string} productType
 * @returns {any[]}
 */
export function filterCabinetsByProduct(cabinets, productType) {
  const allowed = PRODUCT_CABINETS[productType];
  if (!allowed) return cabinets;
  return cabinets.filter(c => allowed.includes(c.id));
}
