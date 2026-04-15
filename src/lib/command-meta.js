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
 * @typedef {Object} BriefFieldOption
 * @property {string} value
 * @property {string} label
 * @property {boolean} [allowInput] - Show inline text input when this option is selected
 * @property {string} [inputPlaceholder]
 */

/**
 * @typedef {Object} BriefField
 * @property {string} id
 * @property {string} label
 * @property {'radio'|'checkboxes'|'text'} type
 * @property {BriefFieldOption[]} [options]
 * @property {string} [default] - Default value for radio
 * @property {string[]} [defaults] - Default selected values for checkboxes
 * @property {string[]} [chips] - Suggestion chips for text field
 * @property {string} [placeholder] - Placeholder for text field
 */

/**
 * @typedef {Object} CommandMeta
 * @property {string} description - Short description (1 line)
 * @property {string} [example] - Example task prompt
 * @property {string} [category] - Semantic category: create | analyze | edit | test | utility
 * @property {boolean} [needsFile] - Highlight when inbox has files
 * @property {BriefField[]} [briefFields] - If present, show CommandBrief panel on click
 */

/** @type {Record<string, CommandMeta>} */
export const COMMAND_META = {
  // ─── lawyer-contracts (15 commands) ───
  '/contract': {
    description: 'Комплексная проверка договора: риски, условия, рекомендации',
    example: 'Проверь договор поставки с ООО "Альфа"',
    category: 'analyze',
    needsFile: true,
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
    briefFields: [
      {
        id: 'slides',
        label: 'Слайды',
        type: 'radio',
        options: [
          { value: 'all', label: 'Все (без перебивок и оглавлений)' },
          { value: 'specific', label: 'Конкретные', allowInput: true, inputPlaceholder: 'напр. 3, 7–10, 15' },
        ],
        default: 'all',
      },
      {
        id: 'audience',
        label: 'Аудитория (уровни комментариев)',
        type: 'checkboxes',
        options: [
          { value: 'ceo', label: 'CEO (стратегия)' },
          { value: 'cmo', label: 'CMO (тактика)' },
          { value: 'bm', label: 'BM (операции)' },
        ],
        defaults: ['ceo', 'cmo', 'bm'],
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Фокус, сравнения, акценты...',
        chips: ['Фокус на выводах', 'Сравнить с Q3', 'Акцент на digital', 'Выделить аномалии'],
      },
    ],
  },
  '/check': {
    description: 'Проверка качества существующих комментариев по чек-листу',
    category: 'analyze',
    needsFile: true,
    briefFields: [
      {
        id: 'areas',
        label: 'Что проверять',
        type: 'checkboxes',
        options: [
          { value: 'action-titles', label: 'Action Titles' },
          { value: 'formula', label: 'Формула Факт+Причина+Влияние' },
          { value: 'data-cemetery', label: 'Кладбище данных' },
          { value: 'exec-summary', label: 'Executive Summary' },
          { value: 'source-accuracy', label: 'Точность источников' },
        ],
        defaults: ['action-titles', 'formula', 'data-cemetery', 'exec-summary', 'source-accuracy'],
      },
      {
        id: 'mode',
        label: 'Режим',
        type: 'radio',
        options: [
          { value: 'checklist', label: 'Только чек-лист (проверка без правок)' },
          { value: 'fix', label: 'Чек-лист + исправить проблемы' },
        ],
        default: 'checklist',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Конкретные слайды, фокус проверки...',
        chips: ['Только слайды 5-15', 'Фокус на digital-блоке', 'Проверить цифры vs графики'],
      },
    ],
  },
  '/action-title': {
    description: 'Генерация заголовков-выводов для слайдов',
    category: 'create',
    needsFile: true,
    briefFields: [
      {
        id: 'level',
        label: 'Уровень SO WHAT',
        type: 'checkboxes',
        options: [
          { value: 'operational', label: 'Operational (менеджеры)' },
          { value: 'tactical', label: 'Tactical (CMO)' },
          { value: 'strategic', label: 'Strategic (CEO)' },
        ],
        defaults: ['tactical'],
      },
      {
        id: 'variants',
        label: 'Вариантов на слайд',
        type: 'radio',
        options: [
          { value: '1', label: '1 (только лучший)' },
          { value: '3', label: '3 (на каждом уровне)' },
        ],
        default: '3',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Конкретные слайды, отрасль, контекст...',
        chips: ['Только слайды с данными', 'Фокус на digital', 'Короче и жёстче'],
      },
    ],
  },
  '/executive-summary': {
    description: 'Executive Summary по Pyramid Principle',
    category: 'create',
    needsFile: true,
    briefFields: [
      {
        id: 'format',
        label: 'Формат',
        type: 'radio',
        options: [
          { value: 'pyramid', label: 'Pyramid Principle (Минто)' },
          { value: 'scr', label: 'SCR (Situation-Complication-Resolution)' },
        ],
        default: 'pyramid',
      },
      {
        id: 'audience',
        label: 'Разметка аудитории',
        type: 'checkboxes',
        options: [
          { value: 'ceo', label: '[CEO] стратегия' },
          { value: 'cmo', label: '[CMO] маркетинг' },
          { value: 'bm', label: '[BM] операции' },
        ],
        defaults: ['ceo', 'cmo', 'bm'],
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Traffic Light, фокус, контекст...',
        chips: ['Добавить Traffic Light Summary', 'Фокус на рекомендациях', 'Сравнить с прошлым периодом'],
      },
    ],
  },
  '/bridges': {
    description: 'Межтематические связки между блоками презентации',
    category: 'create',
    needsFile: true,
    briefFields: [
      {
        id: 'types',
        label: 'Типы связей',
        type: 'checkboxes',
        options: [
          { value: 'causal', label: 'Причинность' },
          { value: 'correlation', label: 'Корреляция' },
          { value: 'contradiction', label: 'Противоречие' },
          { value: 'amplification', label: 'Усиление (мультипликатор)' },
        ],
        defaults: ['causal', 'correlation', 'contradiction', 'amplification'],
      },
      {
        id: 'count',
        label: 'Минимум мостов',
        type: 'radio',
        options: [
          { value: '3', label: '3 (компактно)' },
          { value: '5', label: '5 (стандарт)' },
          { value: '7', label: '7+ (максимум)' },
        ],
        default: '5',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Конкретные блоки, фокус связей...',
        chips: ['Связать медиа и продажи', 'Фокус на digital', 'Каузальные цепочки Binet & Field'],
      },
    ],
  },
  '/batch-analytics': {
    description: 'Пакетная обработка нескольких презентаций',
    category: 'analyze',
    needsFile: true,
    briefFields: [
      {
        id: 'audience',
        label: 'Аудитория (уровни комментариев)',
        type: 'checkboxes',
        options: [
          { value: 'ceo', label: 'CEO (стратегия)' },
          { value: 'cmo', label: 'CMO (тактика)' },
          { value: 'bm', label: 'BM (операции)' },
        ],
        defaults: ['ceo', 'cmo', 'bm'],
      },
      {
        id: 'depth',
        label: 'Глубина анализа',
        type: 'radio',
        options: [
          { value: 'standard', label: 'Стандарт (полный анализ каждого файла)' },
          { value: 'express', label: 'Экспресс (ключевые выводы + сводная)' },
        ],
        default: 'standard',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Общий контекст для всех файлов...',
        chips: ['Единый клиент', 'Сравнить файлы между собой', 'Фокус на аномалиях'],
      },
    ],
  },
  '/data-analysis': {
    description: 'Анализ сырых данных из xlsx/csv до создания слайдов',
    category: 'analyze',
    needsFile: true,
    briefFields: [
      {
        id: 'analyses',
        label: 'Типы анализа',
        type: 'checkboxes',
        options: [
          { value: 'descriptive', label: 'Описательная статистика' },
          { value: 'segmentation', label: 'Сегментация' },
          { value: 'period', label: 'Period-over-period (YoY, MoM)' },
          { value: 'anomalies', label: 'Аномалии и выбросы' },
          { value: 'correlations', label: 'Корреляции' },
        ],
        defaults: ['descriptive', 'segmentation', 'period', 'anomalies', 'correlations'],
      },
      {
        id: 'visualizations',
        label: 'Рекомендации по визуализации',
        type: 'radio',
        options: [
          { value: 'yes', label: 'Да (предложить тип графика для каждого инсайта)' },
          { value: 'no', label: 'Нет (только данные и выводы)' },
        ],
        default: 'yes',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Конкретные метрики, период, гипотезы...',
        chips: ['Фокус на продажах', 'Сравнить каналы', 'Найти драйверы роста'],
      },
    ],
  },
  '/benchmark': {
    description: 'Контекстуализация данных относительно рыночных бенчмарков',
    category: 'analyze',
    briefFields: [
      {
        id: 'metrics',
        label: 'Категории метрик',
        type: 'checkboxes',
        options: [
          { value: 'digital', label: 'Digital (CPM, CTR, CPC)' },
          { value: 'tv', label: 'TV (GRP, охват)' },
          { value: 'ooh', label: 'OOH (CPM, охват)' },
          { value: 'sov', label: 'SOV/SOM/ESOV' },
        ],
        defaults: ['digital', 'tv', 'ooh', 'sov'],
      },
      {
        id: 'market',
        label: 'Рынок',
        type: 'radio',
        options: [
          { value: 'russia', label: 'Россия (РФ 2024-2025)' },
          { value: 'custom', label: 'Другой', allowInput: true, inputPlaceholder: 'напр. СНГ, Казахстан' },
        ],
        default: 'russia',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Отрасль, конкретные метрики, период...',
        chips: ['Фарма', 'FMCG', 'Финансы', 'E-commerce'],
      },
    ],
  },
  '/aurora-index': {
    description: 'Aurora Index: автоматическая диагностика презентации',
    category: 'analyze',
    needsFile: true,
    briefFields: [
      {
        id: 'depth',
        label: 'Глубина анализа',
        type: 'radio',
        options: [
          { value: 'express', label: 'Экспресс (аномалии и блоки)' },
          { value: 'full', label: 'Полный (аномалии + связи + рекомендации)' },
        ],
        default: 'full',
      },
      {
        id: 'extra',
        label: 'Дополнительно',
        type: 'text',
        placeholder: 'Фокус анализа, контекст бренда...',
        chips: ['Сравнить с прошлым периодом', 'Фокус на digital', 'Фокус на конкурентах'],
      },
    ],
  },

  // ─── communication-analyst (10 commands) ───
  '/media-monitor': {
    description: 'Мониторинг медиаполя: охват, тональность, доля голоса',
    category: 'analyze',
    needsFile: true,
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
  },
  '/mmm-prepare': {
    description: 'Подготовка данных для Marketing Mix Modeling',
    category: 'utility',
    needsFile: true,
  },
  '/mmm-model': { description: 'Обучение MMM-модели на подготовленных данных', category: 'analyze', needsFile: true },
  '/mmm-decomposition': { description: 'Декомпозиция продаж по каналам и факторам', category: 'analyze', needsFile: true },
  '/mmm-optimize': { description: 'Оптимизация распределения медиабюджета', category: 'analyze', needsFile: true },
  '/mmm-scenarios': { description: 'Сценарное моделирование what-if по бюджетам', category: 'analyze', needsFile: true },
  '/awareness-forecast': { description: 'Прогноз awareness по медиаплану', category: 'analyze', needsFile: true },
  '/awareness-to-sales': { description: 'Моделирование связи awareness → продажи', category: 'analyze', needsFile: true },
  '/mmm-report': { description: 'Полный отчёт по результатам моделирования', category: 'create', needsFile: true },

  // ─── doc-master (3 commands) ───
  '/plan-to-doc': {
    description: 'Преобразование медиаплана в юридическое приложение к договору',
    category: 'create',
    needsFile: true,
  },
  '/doc-batch': { description: 'Генерация комплектов документов из шаблонов', category: 'create', needsFile: true },
  '/plan-check': { description: 'Проверка медиаплана на полноту и корректность', category: 'analyze', needsFile: true },

  // ─── art-director (10 commands) ───
  '/visual': {
    description: 'Создание визуальной концепции по брифу',
    category: 'create',
  },
  '/edit': { description: 'Редактирование и доработка визуальных материалов', category: 'edit', needsFile: true },
  '/logo': { description: 'Разработка концепции логотипа', category: 'create' },
  '/identity': { description: 'Полная визуальная айдентика бренда', category: 'create' },
  '/packaging': { description: 'Дизайн-концепция упаковки продукта', category: 'create' },
  '/brand-visual': { description: 'Визуальный ДНК бренда: цвета, типографика, стиль', category: 'analyze', needsFile: true },
  '/storyboard': { description: 'Раскадровка рекламного ролика', category: 'create' },
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
 * Get brief fields for a command, if it requires a brief panel.
 * @param {string} command
 * @returns {{ fields: BriefField[] } | null}
 */
export function getCommandBrief(command) {
  const meta = COMMAND_META[command];
  if (!meta?.briefFields) return null;
  return { fields: meta.briefFields };
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
