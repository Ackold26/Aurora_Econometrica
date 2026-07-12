/**
 * Тематизация запроса к RAG-библиотеке первоисточников (узел Б) + читаемая
 * атрибуция источника.
 *
 * Живой прогон (2026-07-11) вскрыл два дефекта Tier 2:
 *  1. В econ_rag_search уходил голый вопрос пользователя → возвращались общие
 *     байесовские книги (McElreath, Gelman), а не MMM-специфика (Jin 2017 про
 *     carryover/shape был бы релевантнее вопросу «почему такой ROI»).
 *  2. Источник приходит как имя файла
 *     («Jin_2017_Bayesian_Media_Mix_Modeling_Carryover_and_Shape_Effects»),
 *     Аврора цитирует его сырым, а не «по работе Jin о медиамиксе…».
 *
 * buildRagQuery добавляет к вопросу домен-термины текущего шага пайплайна,
 * ДВУЯЗЫЧНО — корпус наполовину англоязычный, чисто русский запрос топит
 * англ. книги (боевой приём Knowledge_Library, см. CLAUDE.md проекта).
 * humanizeSource превращает имя файла в читаемую атрибуцию для промпта.
 *
 * @module rag-query
 */

/** Максимальная длина итогового запроса к econ_rag_search (символов). */
const QUERY_LIMIT = 400;

/**
 * Домен-термины по шагу пайплайна (STEP из tier2-context.js), двуязычно.
 * @type {Record<number, string>}
 */
const STEP_TERMS = {
  1: 'коллинеарность multicollinearity confounder смешивающая переменная omitted variable bias ratio наблюдений предикторы', // VALIDATE
  2: 'байесовская диагностика Bayesian diagnostics convergence сходимость R-hat prior predictive check приорные распределения MCMC', // MODEL
  3: 'вклад канала adstock перенос carryover эффект saturation насыщение response curve кривая отклика decomposition декомпозиция attribution', // DECOMPOSE
  4: 'оптимизация бюджета budget allocation маржинальная отдача marginal ROI mROI saturation насыщение diminishing returns убывающая отдача', // OPTIMIZE
  5: 'marketing mix modeling MMM интерпретация результатов декомпозиция оптимизация', // REPORT
};

/** Термины по умолчанию — шаг вне карты (например IMPORT=0) или не задан. */
const DEFAULT_TERMS = 'marketing mix modeling эконометрика медиамикс интерпретация';

/**
 * Термины-уточнение по типу канала для why-channel вопросов.
 * @type {Record<string, string>}
 */
const CHANNEL_TYPE_TERMS = {
  reach: 'охватный брендовый канал brand reach ТВ',
  performance: 'performance канал прямой отклик',
};

/**
 * Собрать тематизированный запрос к econ_rag_search: вопрос пользователя +
 * домен-термины текущего шага (двуязычно), опционально уточнение по типу
 * канала. Обрезается до QUERY_LIMIT символов.
 *
 * @param {{ question?: string, step?: number, focusChannelType?: 'reach'|'performance'|string }} input
 * @returns {string}
 */
export function buildRagQuery({ question, step, focusChannelType } = {}) {
  const q = String(question || '').trim();
  const terms = (step !== undefined && STEP_TERMS[step]) || DEFAULT_TERMS;
  const channelTerms = focusChannelType ? CHANNEL_TYPE_TERMS[focusChannelType] : undefined;

  const pieces = [q, terms, channelTerms].filter(Boolean);
  const full = pieces.join(' ');
  if (full.length <= QUERY_LIMIT) return full;

  // Обрезать ВОПРОС, а не термины: домен-термины — главная ценность запроса
  // (ради них петля и делалась), их вытеснение длинным вопросом тихо ломает
  // тематизацию. Гарантируем термины целиком, вопросу отдаём остаток лимита.
  const tail = [terms, channelTerms].filter(Boolean).join(' ');
  if (tail.length >= QUERY_LIMIT || !q) {
    // Термины сами длиннее лимита (край) — обрежем их по слову, вопрос опустим.
    const cut = tail.slice(0, QUERY_LIMIT);
    const sp = cut.lastIndexOf(' ');
    return sp > 0 ? cut.slice(0, sp) : cut;
  }
  const budget = QUERY_LIMIT - tail.length - 1; // −1 на разделитель
  const qCut = q.slice(0, budget);
  const qSp = qCut.lastIndexOf(' ');
  const qTrimmed = qSp > 0 ? qCut.slice(0, qSp) : qCut;
  return `${qTrimmed} ${tail}`.trim();
}

/**
 * Год источника: первое 19xx/20xx число в строке. Без \b — в именах файлов
 * год отделён «_», который сам входит в \w, и граница слова не срабатывает.
 * Используется как РАЗДЕЛИТЕЛЬ «авторы_ГОД_название» — сам год в атрибуцию НЕ
 * попадает (решение Антона 2026-07-12: даты делают источник «датированным»,
 * методология вечна → упоминаем автора + название, без года).
 * @param {string} s
 */
function findYear(s) {
  const m = s.match(/(19|20)\d{2}/);
  return m ? m[0] : null;
}

/**
 * Превратить имя файла источника RAG-библиотеки в читаемую атрибуцию для
 * промпта («по работе Jin „Bayesian Media Mix Modeling…“»), не в сырое имя
 * файла и БЕЗ года. Не падает на неожиданном формате — fallback возвращает
 * исходное имя с «_» → « ».
 *
 * Примеры:
 *  - Jin_2017_Bayesian_Media_Mix_Modeling_Carryover_and_Shape_Effects
 *      → «Jin, „Bayesian Media Mix Modeling Carryover and Shape Effects“»
 *  - Statistical_Rethinking_-_Richard_McElreath → «McElreath, „Statistical Rethinking“»
 *  - Bayesian_Workflow_-_Andrew_Gelman → «Gelman, „Bayesian Workflow“»
 *  - Hernan_Robins_2025_Causal_Inference_What_If → «Hernan & Robins, „Causal Inference What If“»
 *  - Chan_Perry_2017_Challenges_... → «Chan & Perry, „Challenges and Opportunities“»
 *
 * @param {string} fileName
 * @returns {string}
 */
export function humanizeSource(fileName) {
  const raw = String(fileName || '').trim();
  if (!raw) return raw;

  try {
    // Отрезать расширение файла, если есть (.pdf/.txt/...).
    const noExt = raw.replace(/\.[a-zA-Z0-9]{1,5}$/, '');
    const year = findYear(noExt);

    // Паттерн «Название - Имя Фамилия» (Gelman/McElreath): тире-разделитель,
    // фамилия — последний токен после тире.
    const dashMatch = noExt.split(/_-_|-/).map((p) => p.trim()).filter(Boolean);
    if (!year && dashMatch.length >= 2) {
      const titlePart = dashMatch[0].replace(/_/g, ' ').trim();
      const authorPart = dashMatch[dashMatch.length - 1].replace(/_/g, ' ').trim();
      const authorTokens = authorPart.split(/\s+/).filter(Boolean);
      if (titlePart && authorTokens.length > 0) {
        const surname = authorTokens[authorTokens.length - 1];
        return `${surname}, «${titlePart}»`;
      }
    }

    if (year) {
      // Формат «Авторы_ГОД_Название»: год — только разделитель, в атрибуцию
      // НЕ идёт. Авторы — до года, название — после.
      const idx = noExt.indexOf(year);
      const beforeYear = noExt.slice(0, idx).replace(/[_\s]+$/, '');
      const afterYear = noExt.slice(idx + year.length).replace(/^[_\s]+/, '');
      const tokens = beforeYear.split(/_+/).filter(Boolean);
      const surnames = tokens.filter((t) => /^[A-ZА-ЯЁ][a-zа-яё]+$/.test(t));
      const authors = surnames.length >= 2
        ? surnames.join(' & ')
        : (surnames.length === 1 ? surnames[0] : tokens.join(' '));
      const title = afterYear.replace(/_/g, ' ').trim();
      if (authors && title) return `${authors}, «${title}»`;
      if (authors) return authors;      // авторы есть, названия нет
      if (title) return `«${title}»`;   // только название
      // ни авторов, ни названия вокруг года — отдать имя без года (fallback ниже).
    }
  } catch {
    // падать нельзя — ниже fallback
  }

  return raw.replace(/_/g, ' ').trim();
}
