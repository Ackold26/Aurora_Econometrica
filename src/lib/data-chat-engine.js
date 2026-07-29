/**
 * Data Chat Engine - intent classification + answer formatting.
 * Pure JS, no dependencies. Runs on frontend.
 */

// ── Intent Classification ────────────────────────────────

const INTENTS = {
  profile: {
    phrases: ['тон голоса', 'tone of voice', 'кто конкуренты', 'стоп-слова', 'стоп слова', 'ценности бренда', 'описание бренда', 'покажи профиль', 'профиль бренда'],
    keywords: ['профиль', 'индустрия', 'маркеры', 'конкуренты', 'ценности', 'тон'],
  },
  stats: {
    phrases: ['сколько документов', 'сколько данных', 'сколько векторов', 'сколько файлов', 'покажи данные', 'покажи статистику'],
    keywords: ['статистика', 'количество', 'stats', 'данные'],
  },
  search: {
    phrases: ['что говорят', 'что пишут', 'тональность отзывов', 'найди про', 'найди информацию', 'покажи отзывы', 'покажи упоминания'],
    keywords: ['найди', 'поиск', 'отзывы', 'клиенты', 'упоминания', 'мнения'],
  },
  history: {
    phrases: ['что рекомендовал', 'что предлагал', 'что делал', 'результаты кабинета', 'покажи историю'],
    keywords: ['стратег', 'копирайтер', 'аналитик', 'директор', 'история', 'кабинет'],
  },
  comparison: {
    phrases: ['сравни с', 'чем отличается', 'в чём разница'],
    keywords: ['сравнение', 'сравни', 'vs', 'против'],
  },
  greeting: {
    phrases: ['привет', 'здравствуй', 'помоги', 'что ты умеешь', 'как работает', 'что можешь'],
    keywords: ['привет', 'hello', 'помощь', 'hi', 'хай'],
  },
};

/**
 * Classify user question into intent.
 * @param {string} question
 * @returns {{intent: string, confidence: number}}
 */
export function classifyIntent(question) {
  const q = question.toLowerCase().trim();
  if (!q || q.length < 2) return { intent: 'greeting', confidence: 0 };

  let bestIntent = 'greeting';
  let bestScore = 0;

  for (const [intent, { phrases, keywords }] of Object.entries(INTENTS)) {
    let score = 0;
    for (const phrase of phrases) {
      if (q.includes(phrase)) score += 2.0;
    }
    for (const kw of keywords) {
      if (q.includes(kw)) score += 1.0;
    }
    // On tie: prefer search > comparison > history > profile > stats > greeting
    /** @type {Record<string, number>} */
    const priority = { search: 6, comparison: 5, history: 4, profile: 3, stats: 2, greeting: 1 };
    if (score > bestScore || (score === bestScore && (priority[intent] || 0) > (priority[bestIntent] || 0))) {
      bestScore = score;
      bestIntent = intent;
    }
  }

  // If no strong match and question is long enough → analysis (deep tier)
  if (bestScore < 1.0 && q.length > 15 && bestIntent !== 'greeting') {
    return { intent: 'analysis', confidence: 0.3 };
  }

  const confidence = Math.min(bestScore / 4, 1.0);
  return { intent: bestIntent, confidence };
}

// ── Answer Formatters ────────────────────────────────────

/**
 * @param {any} profile - brand profile from brand_get
 * @returns {{answer: string, chart: object|null, sources: Array<any>, suggestions: string[]}}
 */
export function formatProfileAnswer(profile) {
  const tov = profile.tone_of_voice || {};
  // Count how rich the profile is - celebrate completeness
  const filled = [profile.industry, profile.description, Object.keys(tov).length > 0,
    (profile.markers || []).length > 0, (profile.values || []).length > 0,
    (profile.competitors || []).length > 0].filter(Boolean).length;
  const richness = filled >= 5 ? 'Отличный профиль – данные детальные!' : filled >= 3 ? 'Хороший профиль.' : 'Профиль пока базовый – добавьте больше данных для точных рекомендаций.';

  const parts = [`## ${profile.name}\n`, `*${richness}*\n`];

  if (profile.industry) parts.push(`**Индустрия:** ${profile.industry}\n`);
  if (profile.description) parts.push(`${profile.description}\n`);

  if (Object.keys(tov).length > 0) {
    parts.push(`\n### Тон голоса`);
    if (tov.style) parts.push(`- **Стиль:** ${tov.style}`);
    if (tov.register) parts.push(`- **Регистр:** ${tov.register}`);
    if (tov.humor) parts.push(`- **Юмор:** ${tov.humor}`);
    if (tov.formality) parts.push(`- **Формальность:** ${tov.formality}`);
  }

  const markers = profile.markers || [];
  if (markers.length > 0) parts.push(`\n### Маркеры бренда\n${markers.map(/** @param {any} m */ m => `\`${m}\``).join(', ')}`);

  const stopWords = profile.stop_words || [];
  if (stopWords.length > 0) parts.push(`\n### Стоп-слова\n${stopWords.map(/** @param {any} s */ s => `~~${s}~~`).join(', ')}`);

  const values = profile.values || [];
  if (values.length > 0) parts.push(`\n### Ценности\n${values.join(' · ')}`);

  const competitors = profile.competitors || [];
  if (competitors.length > 0) {
    parts.push(`\n### Конкуренты`);
    competitors.forEach(/** @param {any} c */ c => parts.push(`- **${c.name}** (${(c.keywords || []).join(', ')})`));
  }

  return {
    answer: parts.join('\n'),
    chart: null,
    sources: [{ text: 'Профиль бренда', source: 'profile.json', score: 1.0 }],
    suggestions: generateSuggestions('profile', profile),
  };
}

/**
 * @param {any} stats - from brand_stats
 * @param {string} brandName
 */
export function formatStatsAnswer(stats, brandName) {
  const total = (stats.vectors || 0) + (stats.documents || 0) + (stats.raw_data_files || 0);

  if (total === 0) {
    return {
      answer: `## Данные ${brandName}\n\nДанные ещё не загружены. Загрузите документы в Brand Hub, чтобы начать работу.\n\n> Каждый загруженный документ автоматически разбивается на смысловые фрагменты и индексируется для мгновенного поиска.`,
      chart: null,
      sources: [],
      suggestions: ['Покажи профиль бренда'],
    };
  }

  // Proactive insight based on data shape
  let insight = '';
  if (stats.vectors > 0 && stats.raw_data_files === 0) {
    insight = '\n\n> 💡 **Совет:** подключите парсер данных – отзывы клиентов из соцсетей и маркетплейсов значительно обогатят базу знаний бренда.';
  } else if (stats.raw_data_files > 5) {
    insight = '\n\n> 💡 База обогащена данными парсинга – попробуйте спросить «что говорят клиенты?» для анализа отзывов.';
  }

  return {
    answer: `## Статистика Brand Hub: ${brandName}\n\nВ базе бренда содержится **${stats.vectors}** векторных записей, **${stats.documents}** документов и **${stats.raw_data_files}** файлов парсинга.${insight}`,
    chart: {
      type: 'stat',
      data: [
        { label: 'Векторов', value: stats.vectors || 0 },
        { label: 'Документов', value: stats.documents || 0 },
        { label: 'Парсинг', value: stats.raw_data_files || 0 },
      ],
    },
    sources: [{ text: 'Статистика Brand Hub', source: 'stats API', score: 1.0 }],
    suggestions: generateSuggestions('stats', null),
  };
}

/**
 * @param {any} searchResult - from brand_search (has .results array)
 * @param {string} question
 */
export function formatSearchAnswer(searchResult, question) {
  const results = searchResult?.results || [];

  if (results.length === 0) {
    return {
      answer: `По запросу «${question}» ничего не найдено в базе бренда.\n\nПопробуйте переформулировать или загрузите дополнительные документы.`,
      chart: null,
      sources: [],
      suggestions: ['Какие данные есть в Brand Hub?', 'Покажи профиль бренда'],
    };
  }

  // Frame results as discovery, not dry list
  const topScore = results[0]?.score || 0;
  const qualityLabel = topScore > 0.25 ? 'Нашёл точные совпадения!' : 'Вот что удалось найти:';
  const parts = [`## ${qualityLabel}\n`];

  results.slice(0, 5).forEach((/** @type {any} */ r, /** @type {number} */ i) => {
    const excerpt = r.text.length > 150 ? r.text.slice(0, 150) + '...' : r.text;
    const scorePct = Math.round((r.score || 0) * 100);
    parts.push(`${i + 1}. **${r.source}** - ${excerpt}`);
  });

  if (results.length > 5) {
    parts.push(`\n*...и ещё ${results.length - 5} результатов в базе*`);
  }

  // Proactive insight
  if (results.length >= 5) {
    parts.push(`\n> 💡 Много данных по этой теме. Нажмите **Глубокий анализ** для детального разбора.`);
  }

  return {
    answer: parts.join('\n'),
    chart: null,
    sources: results.map(/** @param {any} r */ r => ({ text: r.text, source: r.source, score: r.score })),
    suggestions: generateSuggestions('search', null),
  };
}

/**
 * @param {Array<any>} historyResults - from brand_history_search
 */
export function formatHistoryAnswer(historyResults) {
  if (!historyResults || historyResults.length === 0) {
    return {
      answer: `В истории кабинетов пока пусто.\n\nИстория появится автоматически, когда вы начнёте работать с кабинетами – каждый результат сохраняется.`,
      chart: null,
      sources: [],
      suggestions: ['Покажи профиль бренда', 'Какие данные есть?'],
    };
  }

  const parts = [`## Из истории кабинетов\n`, `Нашёл **${historyResults.length}** совпадений:\n`];
  historyResults.slice(0, 8).forEach(r => {
    parts.push(`- **${r.cabinet}** / ${r.filename}: ${r.excerpt}`);
  });

  return {
    answer: parts.join('\n'),
    chart: null,
    sources: historyResults.map(r => ({ text: r.excerpt, source: `${r.cabinet}/${r.filename}`, score: 0.8 })),
    suggestions: generateSuggestions('history', null),
  };
}

/**
 * @param {any} profile - brand profile
 * @param {any} searchResult - search for competitor mentions
 * @param {string} competitorName
 */
export function formatComparisonAnswer(profile, searchResult, competitorName) {
  const results = searchResult?.results || [];
  const competitors = profile.competitors || [];
  const comp = competitors.find(/** @param {any} c */ c => c.name.toLowerCase().includes(competitorName.toLowerCase()));

  const parts = [`## Сравнение с ${comp?.name || competitorName}\n`];

  if (comp) {
    parts.push(`**Конкурент:** ${comp.name}`);
    if (comp.keywords?.length) parts.push(`**Ключевые слова:** ${comp.keywords.join(', ')}`);
  }

  if (results.length > 0) {
    parts.push(`\n### Упоминания в данных бренда\n`);
    results.slice(0, 3).forEach(/** @param {any} r */ r => {
      const excerpt = r.text.length > 150 ? r.text.slice(0, 150) + '...' : r.text;
      parts.push(`- ${excerpt}`);
    });
  } else {
    parts.push(`\nВ базе пока нет упоминаний **${comp?.name || competitorName}**. Загрузите аналитические отчёты – и я смогу провести полное сравнение.`);
  }

  return {
    answer: parts.join('\n'),
    chart: null,
    sources: results.map(/** @param {any} r */ r => ({ text: r.text, source: r.source, score: r.score })),
    suggestions: generateSuggestions('comparison', profile),
  };
}

/**
 * @param {string} brandName
 */
export function formatGreetingAnswer(brandName) {
  // Vary the greeting slightly for freshness (variable reward)
  const greetings = [
    `Привет! Рад помочь с брендом **${brandName}**.`,
    `Здравствуйте! Готов рассказать всё о **${brandName}**.`,
    `Привет! Давайте разберёмся в данных **${brandName}**.`,
  ];
  const greeting = greetings[Math.floor(Math.random() * greetings.length)];

  return {
    answer: `${greeting}\n\nЯ знаю о:\n- 🎤 Тоне голоса, маркерах и стоп-словах\n- 📊 Статистике и объёме данных\n- 🔍 Содержимом документов и отзывов\n- 📜 Результатах работы кабинетов\n- ⚔️ Конкурентах и сравнениях\n\nПросто спросите – или выберите подсказку ниже.`,
    chart: null,
    sources: [],
    suggestions: ['Какой тон голоса?', 'Сколько данных в Brand Hub?', 'Покажи профиль бренда'],
  };
}

// ── Suggestion Generator ────────────────────────────────

/**
 * @param {string} intent - current intent
 * @param {any} brandData - profile or null
 * @returns {string[]}
 */
export function generateSuggestions(intent, brandData) {
  // Curiosity-driven suggestions: provoke exploration, not just "show X"
  const base = {
    profile: ['А сколько данных в базе?', 'Что говорят клиенты?'],
    stats: ['Какой тон голоса?', 'Поищи упоминания продукта'],
    search: ['Интересно, а какой профиль бренда?', 'Покажи статистику'],
    history: ['Что ещё рекомендовал стратег?', 'А что в профиле бренда?'],
    comparison: ['А что говорят клиенты?', 'Покажи полный профиль'],
    greeting: [],
    analysis: ['Покажи профиль бренда', 'Сколько данных?'],
  };

  const suggestions = [...(/** @type {Record<string, string[]>} */ (base)[intent] || [])];

  if (brandData?.competitors?.length > 0) {
    suggestions.push(`Сравни с ${brandData.competitors[0].name}`);
  }

  return suggestions.slice(0, 3);
}

/**
 * Generate initial suggestions based on actual brand data.
 * @param {any} profile
 * @param {any} stats
 * @returns {Array<{question: string, subtitle: string, icon: string}>}
 */
export function generateInitialSuggestions(profile, stats) {
  const items = [];

  // Curiosity-driven: tease SPECIFIC facts, not generic questions
  const markers = profile?.markers || [];
  const stopWords = profile?.stop_words || [];
  const tov = profile?.tone_of_voice || {};

  if (tov.style) {
    items.push({ question: 'Какой тон голоса у бренда?', subtitle: `Стиль: ${tov.style}`, icon: '🎤' });
  }

  if (stats?.vectors > 0) {
    items.push({ question: 'Сколько данных в Brand Hub?', subtitle: `${stats.vectors} записей в базе`, icon: '📊' });
  }

  if (markers.length > 0) {
    items.push({ question: 'Что содержится в документах бренда?', subtitle: `${markers.length} маркеров, ${stopWords.length} стоп-слов`, icon: '🔍' });
  } else if (stats?.vectors > 0) {
    items.push({ question: 'Что содержится в документах бренда?', subtitle: 'Поиск по базе знаний', icon: '🔍' });
  }

  if (profile?.competitors?.length > 0) {
    const compName = profile.competitors[0].name;
    items.push({ question: `Сравни с ${compName}`, subtitle: `${profile.competitors.length} конкурентов в базе`, icon: '⚔️' });
  }

  if (items.length < 3) {
    items.push({ question: 'Покажи профиль бренда', subtitle: 'Все данные бренда', icon: '📋' });
  }

  return items.slice(0, 4);
}

/**
 * Extract competitor name from comparison question.
 * @param {string} question
 * @param {Array<any>} competitors
 * @returns {string|null}
 */
export function extractCompetitorName(question, competitors) {
  const q = question.toLowerCase();
  for (const c of (competitors || [])) {
    if (q.includes(c.name.toLowerCase())) return c.name;
    for (const kw of (c.keywords || [])) {
      if (q.includes(kw.toLowerCase())) return c.name;
    }
  }
  // Try to extract after "сравни с"
  const match = q.match(/сравни\s+с\s+(\S+)/);
  return match ? match[1] : null;
}
