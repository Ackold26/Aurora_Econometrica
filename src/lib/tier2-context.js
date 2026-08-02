/**
 * Tier 2 (Claude-усилитель инсайтов) — сборка grounding-контекста и промпта.
 *
 * Архитектурный инвариант (INV-50): LLM получает факты модели как ВХОД и
 * переформулирует их — он не считает. Этот модуль:
 *  1. собирает компактную сводку фактов текущего шага пайплайна (для фокуса
 *     LLM, не сырой мегаджейсон);
 *  2. прикладывает уже посчитанные детерминированные Tier-1 инсайты;
 *  3. прикладывает вердикт надёжности модели ДОСЛОВНО (honesty-gate, verbatim);
 *  4. отдаёт grounding-пакет для `insights-grounding.js` (рантайм-страж чисел).
 *
 * Маршрутизацию по шагам (какие stores) делает вызывающий (InsightsPanel уже
 * считает tier1Insights) — здесь её НЕ дублируем (single source).
 *
 * @module tier2-context
 */

import { buildHelpContext } from './program-help.js';
// База окупаемости считается ОДНОЙ функцией на весь фронт: её же читают экраны
// и детерминированные инсайты. Своя копия здесь завела бы второй источник —
// ровно тот дефект, который лечили на ярусах MQS.
import { roiBase } from './kpi-aware-formatting.js';
import { humanizeSource } from './rag-query.js';

/** Шаги пайплайна (совпадает с $pipelineCurrentStep в InsightsPanel). */
export const STEP = /** @type {const} */ ({
  IMPORT: 0,
  VALIDATE: 1,
  MODEL: 2,
  DECOMPOSE: 3,
  OPTIMIZE: 4,
  PLANNING: 5,
  REPORT: 6,
});

/** Безопасно округлить до n знаков (null/НЕ-число → пропустить). @param {any} x @param {number} n */
function r(x, n = 2) {
  const v = Number(x);
  if (!Number.isFinite(v)) return undefined;
  const p = Math.pow(10, n);
  return Math.round(v * p) / p;
}

/** Убрать ключи со значением undefined (компактность промпта). @param {Record<string, any>} o */
function compact(o) {
  /** @type {Record<string, any>} */
  const out = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

/**
 * Компактная сводка фактов декомпозиции (шаг 3): главные числа по каналам.
 * @param {any} dec
 */
function summarizeDecompose(dec) {
  if (!dec || !Array.isArray(dec.channels)) return {};
  return compact({
    total_sales: r(dec.total_sales ?? dec.total_sales_money, 0),
    baseline_pct: r(dec.baseline_pct, 1),
    media_contribution: r(dec.media_contribution ?? dec.media_contribution_money, 0),
    channels: dec.channels.map(/** @param {any} c */ (c) => compact({
      name: c.display_name || c.name,
      roi: r(c.roi),
      roi_ci_low: r(c.roi_ci_low),
      roi_ci_high: r(c.roi_ci_high),
      contribution_pct: r(c.contribution_pct, 1),
      share_of_spend: r(c.share_of_spend, 1),
      share_of_effect: r(c.share_of_effect, 1),
      efficiency_gap: r(c.efficiency_gap, 1),
      verdict: c.verdict,
    })),
  });
}

/**
 * Компактная сводка фактов оптимизации (шаг 4).
 * @param {any} opt
 */
function summarizeOptimize(opt) {
  if (!opt) return {};
  return compact({
    expected_lift_pct: r(opt.expected_lift_pct, 1),
    total_budget_money: r(opt.total_budget_money ?? opt.total_budget, 0),
    binding_constraints: opt.binding_constraints,
    channels: Array.isArray(opt.channels)
      ? opt.channels.map(/** @param {any} c */ (c) => compact({
          name: c.display_name || c.name,
          current_spend: r(c.current_spend, 0),
          optimal_spend: r(c.optimal_spend, 0),
          delta_pct: r(c.delta_pct, 1),
          mroi_current: r(c.mroi_current),
          mroi_optimal: r(c.mroi_optimal),
        }))
      : undefined,
  });
}

/**
 * Компактная сводка диагностики модели (шаг 2).
 * @param {any} mod
 */
function summarizeModel(mod) {
  const d = mod?.diagnostics || {};
  const m = d.metrics || {};
  const mqs = d.mqs || {};
  return compact({
    r_hat_max: r(m.r_hat_max, 3),
    divergences: m.divergences,
    ratio: r(m.ratio ?? d.ratio, 1),
    r_squared: r(m.r_squared, 3),
    mape_pct: r(m.mape_pct, 2),
    mqs_score: mqs.score,
    mqs_tier: mqs.tier_label,
    channels: mod?.channelParams ? Object.keys(mod.channelParams) : undefined,
  });
}

/**
 * Извлечь вердикт надёжности модели (honesty-gate) ДОСЛОВНО.
 * Источник — optimization.json `model_reliability`. Передаём как есть (любые
 * поля: verdict / reason / reasons / caveat_text), LLM не пересчитывает.
 * @param {any} opt
 * @returns {{ verdict?: string, caveat_text?: string, reason?: string, reasons?: string[] } | null}
 */
function extractHonesty(opt) {
  const mr = opt?.model_reliability;
  if (!mr || typeof mr !== 'object') return null;
  return compact({
    verdict: mr.verdict,
    caveat_text: mr.caveat_text,
    reason: mr.reason,
    reasons: Array.isArray(mr.reasons) ? mr.reasons : undefined,
  });
}

/**
 * @typedef {Object} MethodologyHit
 * @property {string} text
 * @property {string} source
 * @property {string} [title]
 * @property {number} [score]
 */

/**
 * @typedef {Object} Tier2Context
 * @property {number} step
 * @property {Array<{severity:string,text:string,tip?:string}>} tier1Insights
 * @property {Record<string, any>} facts — компактная сводка для промпта
 * @property {ReturnType<typeof extractHonesty>} honesty — verbatim или null
 * @property {string} help — справочный контекст программы (карта + термины)
 * @property {MethodologyHit[] | null} methodology — выдержки из RAG-библиотеки первоисточников
 * @property {{ jsonFacts: unknown[], insightTexts: any[] }} grounding — для guard
 */

/**
 * Убрать из артефакта оптимизации служебную телеметрию, которой нет в промпте
 * (Аврора не может её легитимно цитировать) — иначе её числа расширяют
 * поверхность СЛУЧАЙНЫХ совпадений по значащим цифрам и маскируют галлюцинации
 * от стража (live-probe 2026-07-11: выдуманное «137%» сошлось со служебным
 * slsqp best_objective −141.79 по 2 значащим цифрам).
 * @param {any} opt
 */
function stripOptTelemetry(opt) {
  if (!opt || typeof opt !== 'object') return opt ?? {};
  const { slsqp_diagnostics, response_curves, ...rest } = opt;
  return rest;
}

/**
 * Собрать Tier-2 контекст для текущего шага.
 * facts = компактная сводка (фокус промпта). grounding.jsonFacts = ПОЛНЫЕ
 * факты шага (богатый набор, чтобы guard не флагал легитимное цитирование).
 *
 * @param {{
 *   step: number,
 *   question?: string,
 *   tier1Insights?: Array<{severity:string,text:string,tip?:string}>,
 *   val?: any, mod?: any, dec?: any, opt?: any,
 *   methodology?: MethodologyHit[] | null,
 *   kpiType?: string, kpiKind?: string, valuePerCountUnit?: number|null,
 *   derivedMode?: string,
 * }} input
 * @returns {Tier2Context}
 */
export function buildTier2Context(input) {
  const {
    step, question, tier1Insights = [], val, mod, dec, opt, methodology,
    kpiType, kpiKind, valuePerCountUnit, derivedMode,
  } = input;

  /** @type {Record<string, any>} */
  let facts = {};
  /** @type {unknown} */
  let fullFacts = {};
  /** @type {ReturnType<typeof extractHonesty>} */
  let honesty = null;

  switch (step) {
    case STEP.MODEL:
      facts = summarizeModel(mod);
      fullFacts = mod ?? {};
      break;
    case STEP.DECOMPOSE:
      facts = summarizeDecompose(dec);
      fullFacts = dec ?? {};
      break;
    case STEP.OPTIMIZE:
      facts = summarizeOptimize(opt);
      fullFacts = stripOptTelemetry(opt);
      honesty = extractHonesty(opt);
      break;
    case STEP.PLANNING:
    // Планирование квартала опирается на весь результат (модель + декомпозиция +
    // оптимизация) — та же сводка фактов, что и на отчёте.
    case STEP.REPORT:
      facts = compact({
        model: summarizeModel(mod),
        decompose: summarizeDecompose(dec),
        optimize: summarizeOptimize(opt),
      });
      fullFacts = { mod: mod ?? {}, dec: dec ?? {}, opt: stripOptTelemetry(opt) };
      honesty = extractHonesty(opt);
      break;
    default:
      facts = val?.result ? { validation: 'см. инсайты' } : {};
      fullFacts = val ?? {};
  }

  // База окупаемости — единственный источник для правила 7: слово «прибыльный»
  // законно только когда база «прибыль». Кладётся ПОСЛЕ switch: там facts
  // присваивается целиком, и поле, добавленное раньше, потерялось бы.
  // 🔴 `mode` передавать ОБЯЗАТЕЛЬНО: без него ветка «режим эффективности →
  // базы нет» не срабатывает, и советник называет базу «оборот» там, где экран
  // декомпозиции (он `mode` передаёт) честно говорит «не определена». Вход
  // единой функции обязан собираться одинаково во всех слоях, иначе «единый
  // источник» соблюдён формально, а результат расходится. Внешний аудит,
  // High, 2026-08-02.
  facts.roi_base = roiBase({
    kpiType, kpiKind, vpcu: valuePerCountUnit, mode: derivedMode,
  });

  // Справочный контекст программы (карта + релевантные термины). Идёт в промпт
  // И в grounding: его числа — методологические нормативы из справки (пороги
  // R-hat / MAPE / R², минимум наблюдений), их цитирование легитимно, поэтому
  // они должны считаться grounded, иначе рантайм-страж ложно пометит (INV-50).
  const help = buildHelpContext({ step, question });

  // Канон методологии из RAG-библиотеки первоисточников (узел Б). null/пусто —
  // отсутствует (сервер недоступен / гейт не пройден — graceful на фронте).
  const methodologyList =
    Array.isArray(methodology) && methodology.length > 0 ? methodology : null;

  // jsonFacts — массив источников grounded-чисел: факты модели, вердикт
  // надёжности (caveat_text honesty попадает в промпт — числа должны быть
  // grounded; для optimize/report honesty ⊂ fullFacts, но включаем явно —
  // defense-in-depth), справка, методология. collectGroundedNumbers рекурсивно
  // их обойдёт — числа-нормативы из канона (например, «критерий 3σ») легитимно
  // цитировать, страж не должен их флагать.
  /** @type {unknown[]} */
  const jsonFacts = [fullFacts];
  if (honesty) jsonFacts.push(honesty);
  if (help) jsonFacts.push(help);
  if (methodologyList) jsonFacts.push(methodologyList);

  return {
    step,
    tier1Insights,
    facts,
    honesty,
    help,
    methodology: methodologyList,
    grounding: {
      jsonFacts,
      insightTexts: tier1Insights,
    },
  };
}

/** Системные правила Tier 2 (INV-50 + стиль). Экспортируется для тестов. */
export const TIER2_SYSTEM_RULES = [
  'Ты – Аврора, встроенный ассистент-эконометрист в MMM-оптимизаторе Aurora AI.',
  'Тон деловой и профессиональный. БЕЗ приветствий, БЕЗ обращения к пользователю по',
  'имени, без «я Аврора» и без светской беседы – сразу по существу. Объясняешь',
  'результаты УЖЕ посчитанной модели простым языком и помогаешь принять решение.',
  '',
  'ЖЕЛЕЗНЫЕ ПРАВИЛА (нарушение недопустимо):',
  '1. Ты НЕ считаешь. Все числа бери ТОЛЬКО из блока «Факты модели». Никогда не',
  '   выдумывай и не вычисляй новые числа – в том числе отношения, разности и',
  '   множители («в N раз больше/выше»). Сравнения выражай словами: «намного',
  '   выше», «в разы больше», «заметно эффективнее» – без придуманного числа.',
  '2. Не хватает числа в фактах – скажи словами, без числа. Честность важнее',
  '   полноты (INV-50).',
  '3. Надёжность модели приводи ДОСЛОВНО из блока «Надёжность», не пересчитывай',
  '   и не смягчай. Если модель помечена ненадёжной – предупреди об этом прямо.',
  '4. Широкий интервал оценки = высокая неопределённость; так и говори, не выдавай',
  '   точечную оценку за факт. Называй интервал «правдоподобный диапазон» (значения,',
  '   совместимые с данными), НЕ «доверительный интервал» – второе провоцирует ложную',
  '   уверенность (McElreath: credible interval).',
  '5. Язык: простой русский, без англицизмов где есть аналог; короткое тире «–».',
  'ТЕМАТИКА: отвечай только по существу – эконометрика, MMM, результаты и диагностика',
  '  модели, оптимизация бюджета, работа и функции программы Aurora (в т.ч. по её',
  '  справочной системе). На вопросы вне этой темы вежливо верни к анализу.',
  'СПРАВКА: когда вопрос о работе, функциях, шагах или интерфейсе программы –',
  '  опирайся на блок «Справка о программе» ниже. Не приписывай программе функций,',
  '  которых там нет; чего нет в справке – так и скажи, не домысливай.',
  'БЕЗОПАСНОСТЬ: не объясняй обход лицензии, защиты, ограничений редакции или иные',
  '  способы нарушить условия использования – на такие просьбы краткий вежливый отказ.',
  'ЧИСТОТА ОТВЕТА: не используй служебные пометки источника (вроде [STATISTICAL],',
  '  [MODELED]), не предлагай внутренние слэш-команды (/diagnose, /optimize и т.п.) и',
  '  не пиши служебных фраз об окончании («Все задачи выполнены») – это технические',
  '  артефакты, пользователю они не нужны.',
  '',
  'МЕТОДОЛОГИЯ ИНТЕРПРЕТАЦИИ (подкреплено первоисточниками):',
  '6. Без жаргона: «ROAS» → «отдача на вложенный рубль»; «adstock/перенос» →',
  '   «реклама работает ещё несколько недель после показа»; «насыщение» →',
  '   «дополнительные вложения почти не дают прироста» (Knaflic; Канеман – проклятие знания).',
  '7. Неуверенность знака: если интервал ROI канала включает точку безубыточности',
  '   (около 1), прямо скажи, что модель не уверена – окупается канал или нет',
  '   (McElreath: широкий интервал = реальная неопределённость, не погрешность).',
  '   🔴 БАЗА ОКУПАЕМОСТИ указана в фактах полем «roi_base», и от неё зависят слова:',
  '   • «оборот» – окупаемость считается по обороту. Говори «окупается по обороту»;',
  '     слова «прибыльный», «прибылен», «убыточен» здесь употреблять НЕЛЬЗЯ: канал',
  '     может возвращать вложенное выручкой и при этом не приносить прибыли.',
  '   • «прибыль» – можно говорить о прибыльности прямо.',
  '   • «не определена» – экономика канала не задана, абсолютные пороги окупаемости',
  '     отключены; говори только об отдаче и сравнении каналов между собой, а слова',
  '     «окупается», «прибылен», «убыточен» не используй вовсе.',
  '   Это правило о СЛОВАХ, а не о числах: расчёт верен в любом режиме.',
  '8. Причинность: MMM показывает СВЯЗИ, не доказанные причины. Если каналы сильно',
  '   коррелируют – их вклад не разделить надёжно; если из модели исключены',
  '   сезонность/праздники – оценки могут быть смещены (McElreath: коллинеарность, OVB).',
  '9. Сокращение охватных/брендовых каналов (ТВ, OOH): предупреди про отложенный и',
  '   защитный эффект – часть их вклада удерживает базовые продажи и проявляется с',
  '   задержкой; модель с коротким окном его недооценивает (Sharp; Binet & Field).',
  '10. Структура ответа: сначала вывод одной фразой, затем конкретное действие («что',
  '    сделать»), а не только описание (Knaflic: takeaway title + suggest action).',
  '11. Переводчик сложного: когда ответ опирается на сложную эконометрику – байесовские',
  '    термины, статистические критерии, выдержки из научного канона или справочной',
  '    библиотеки – НЕ пересказывай их академическим языком. Передай суть и практический',
  '    вывод простым пользовательским языком (для менеджера, не статистика): без формул,',
  '    без научных формулировок. Термин без простого аналога – поясни в скобках одной',
  '    фразой. Пользователь получает понятный ответ, не лекцию.',
  '12. Против ложной точности (Канеман: якорение): если в фактах есть границы интервала',
  '    оценки – подавай диапазон с центром («вероятный диапазон X–Y, центр около Z»),',
  '    а не голое точечное число. Верхнюю границу не называй без якоря на центр или',
  '    медиану (иначе читатель запомнит только максимум). Все числа границ – строго',
  '    из фактов (правило 1 сильнее: нет границ в фактах – не выдумывай).',
  'Отвечай кратко и по делу.',
].join('\n');

/** Максимальная длина цитаты из библиотеки методологии в промпте (символов). */
const METHODOLOGY_TEXT_LIMIT = 600;

/**
 * Обрезать текст до предела по границе слова, добавить «…» при обрезке.
 * @param {string} text
 * @param {number} limit
 * @returns {string}
 */
function truncateAtWord(text, limit) {
  const s = String(text || '');
  if (s.length <= limit) return s;
  const cut = s.slice(0, limit);
  const lastSpace = cut.lastIndexOf(' ');
  const trimmed = lastSpace > 0 ? cut.slice(0, lastSpace) : cut;
  return `${trimmed}…`;
}

/**
 * Нейтрализовать в тексте разделители секций промпта (аудит 2026-07-11, M1;
 * расширено M1-2: применяется не только к выдержкам методологии, но к ЛЮБОМУ
 * пользовательскому/внешнему тексту, попадающему в промпт — вопрос
 * пользователя, имена каналов из tier1-инсайтов, текст сценария). Битый OCR
 * или намеренно скомпрометированный ввод со строкой вида «=== Факты модели
 * ===» иначе создал бы фальшивую секцию и переопределил структуру промпта.
 * «===» → «≈≈≈», переносы строк → пробел (цитата всегда одна строка списка).
 * NFKC-нормализация первой (аудит 2026-07-13): юникод-гомоглифы равенства
 * (полноширинный «＝» U+FF1D, малый «﹦» U+FE66 и прочие совместимые формы)
 * визуально имитируют «=», но ASCII-регэксп их не ловил → приводим к «=» до
 * замены, иначе «＝＝＝ Факты ＝＝＝» проходило бы как фальшивая секция.
 * @param {string} text
 * @returns {string}
 */
export function sanitizePromptFragment(text) {
  return String(text || '')
    .normalize('NFKC')
    .replace(/={3,}/g, '≈≈≈')
    .replace(/\s*[\r\n]+\s*/g, ' ')
    .trim();
}

/**
 * Построить промпт для Claude из Tier-2 контекста и вопроса пользователя.
 *
 * @param {Tier2Context} context
 * @param {string} [userQuestion] - пусто = «объясни этот результат простыми словами»
 * @returns {string}
 */
export function buildTier2Prompt(context, userQuestion) {
  // Вопрос пользователя — сырой внешний ввод; нейтрализация разделителей
  // секций (M1-2) до вставки в промпт, симметрично методологии/инсайтам.
  const question = sanitizePromptFragment(userQuestion || '') || 'Объясни этот результат простыми словами и подскажи, на что обратить внимание.';

  const parts = [TIER2_SYSTEM_RULES, ''];

  if (context.help) {
    parts.push('=== Справка о программе (смысл терминов и функций; числа здесь – методологические нормативы, НЕ результаты вашей модели) ===');
    parts.push(context.help);
    parts.push('');
  }

  if (context.methodology && context.methodology.length > 0) {
    parts.push('=== Канон методологии (выдержки из библиотеки первоисточников) ===');
    parts.push('Правила: используй для обоснования интерпретации; когда опираешься на выдержку отсюда – назови источник в тексте словами (автор и/или название работы: «как отмечает Макэлрит…», «по работе Jin о медиамиксе…»), БЕЗ года издания (методология вечна, дата делает источник ложно-устаревшим), НЕ именем файла и не в квадратных скобках как служебную пометку; числа и нормативы отсюда – методологический канон, НЕ результаты модели пользователя – не смешивай; сложные формулировки переводи на простой язык (правило 11).');
    for (const hit of context.methodology) {
      const source = sanitizePromptFragment(humanizeSource(hit.source));
      const text = sanitizePromptFragment(hit.text);
      parts.push(`- [«${source}»] ${truncateAtWord(text, METHODOLOGY_TEXT_LIMIT)}`);
    }
    parts.push('');
  }

  parts.push('=== Факты модели (единственный источник чисел) ===');
  parts.push(JSON.stringify(context.facts, null, 2));
  parts.push('');

  if (context.tier1Insights.length > 0) {
    parts.push('=== Уже отмечено системой (детерминированные инсайты) ===');
    for (const ins of context.tier1Insights) {
      // Тексты инсайтов несут имена колонок/каналов из пользовательских данных
      // (не фиксированный текст) — та же нейтрализация разделителей, что и
      // для выдержек методологии (M1-2).
      const text = sanitizePromptFragment(ins.text);
      const tip = ins.tip ? ` (${sanitizePromptFragment(ins.tip)})` : '';
      parts.push(`- [${ins.severity}] ${text}${tip}`);
    }
    parts.push('');
  }

  if (context.honesty) {
    parts.push('=== Надёжность модели (приводить ДОСЛОВНО) ===');
    parts.push(JSON.stringify(context.honesty, null, 2));
    parts.push('');
  }

  parts.push('=== Вопрос пользователя ===');
  parts.push(question);

  return parts.join('\n');
}
