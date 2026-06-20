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

/** Шаги пайплайна (совпадает с $pipelineCurrentStep в InsightsPanel). */
export const STEP = /** @type {const} */ ({
  IMPORT: 0,
  VALIDATE: 1,
  MODEL: 2,
  DECOMPOSE: 3,
  OPTIMIZE: 4,
  REPORT: 5,
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
 * @typedef {Object} Tier2Context
 * @property {number} step
 * @property {Array<{severity:string,text:string,tip?:string}>} tier1Insights
 * @property {Record<string, any>} facts — компактная сводка для промпта
 * @property {ReturnType<typeof extractHonesty>} honesty — verbatim или null
 * @property {{ jsonFacts: unknown, insightTexts: any[] }} grounding — для guard
 */

/**
 * Собрать Tier-2 контекст для текущего шага.
 * facts = компактная сводка (фокус промпта). grounding.jsonFacts = ПОЛНЫЕ
 * факты шага (богатый набор, чтобы guard не флагал легитимное цитирование).
 *
 * @param {{
 *   step: number,
 *   tier1Insights?: Array<{severity:string,text:string,tip?:string}>,
 *   val?: any, mod?: any, dec?: any, opt?: any,
 * }} input
 * @returns {Tier2Context}
 */
export function buildTier2Context(input) {
  const { step, tier1Insights = [], val, mod, dec, opt } = input;

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
      fullFacts = opt ?? {};
      honesty = extractHonesty(opt);
      break;
    case STEP.REPORT:
      facts = compact({
        model: summarizeModel(mod),
        decompose: summarizeDecompose(dec),
        optimize: summarizeOptimize(opt),
      });
      fullFacts = { mod: mod ?? {}, dec: dec ?? {}, opt: opt ?? {} };
      honesty = extractHonesty(opt);
      break;
    default:
      facts = val?.result ? { validation: 'см. инсайты' } : {};
      fullFacts = val ?? {};
  }

  return {
    step,
    tier1Insights,
    facts,
    honesty,
    grounding: { jsonFacts: fullFacts, insightTexts: tier1Insights },
  };
}

/** Системные правила Tier 2 (INV-50 + стиль). Экспортируется для тестов. */
export const TIER2_SYSTEM_RULES = [
  'Ты — встроенный ассистент-эконометрист в MMM-оптимизаторе Aurora. Объясняешь',
  'результаты УЖЕ посчитанной модели простым языком и помогаешь принять решение.',
  '',
  'ЖЕЛЕЗНЫЕ ПРАВИЛА (нарушение недопустимо):',
  '1. Ты НЕ считаешь. Все числа бери ТОЛЬКО из блока «Факты модели». Никогда не',
  '   выдумывай и не вычисляй новые числа.',
  '2. Не хватает числа в фактах — скажи словами, без числа. Честность важнее',
  '   полноты (INV-50).',
  '3. Надёжность модели приводи ДОСЛОВНО из блока «Надёжность», не пересчитывай',
  '   и не смягчай. Если модель помечена ненадёжной — предупреди об этом прямо.',
  '4. Широкий доверительный интервал = высокая неопределённость; так и говори,',
  '   не выдавай точечную оценку за факт.',
  '5. Язык: простой русский, без англицизмов где есть аналог; короткое тире «–».',
  'Отвечай кратко и по делу.',
].join('\n');

/**
 * Построить промпт для Claude из Tier-2 контекста и вопроса пользователя.
 *
 * @param {Tier2Context} context
 * @param {string} [userQuestion] — пусто = «объясни этот результат простыми словами»
 * @returns {string}
 */
export function buildTier2Prompt(context, userQuestion) {
  const question = (userQuestion || '').trim() || 'Объясни этот результат простыми словами и подскажи, на что обратить внимание.';

  const parts = [TIER2_SYSTEM_RULES, ''];

  parts.push('=== Факты модели (единственный источник чисел) ===');
  parts.push(JSON.stringify(context.facts, null, 2));
  parts.push('');

  if (context.tier1Insights.length > 0) {
    parts.push('=== Уже отмечено системой (детерминированные инсайты) ===');
    for (const ins of context.tier1Insights) {
      const tip = ins.tip ? ` (${ins.tip})` : '';
      parts.push(`- [${ins.severity}] ${ins.text}${tip}`);
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
