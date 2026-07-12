/**
 * INV-50 grounding guard для Tier 2 (Claude-усилитель инсайтов).
 *
 * Назначение: дать LLM-слою архитектурную НЕВОЗМОЖНОСТЬ соврать про число.
 * Tier 2 получает факты модели как контекст и ПЕРЕФОРМУЛИРУЕТ их — он не
 * считает. Этот модуль проверяет инвариант: каждое число в ответе LLM должно
 * присутствовать в фактах модели (Tier-1 инсайты + JSON результатов). Любое
 * число, которого там нет, — потенциальная галлюцинация (INV-50 нарушение).
 *
 * Двойная роль:
 *  1. Прокси-гейт (Фаза 0): тестируется на реальной фикстуре прогона ДО
 *     постройки Tier 2 — фиксирует контракт и ловит регрессии.
 *  2. Рантайм-страж (Фаза 1+): тот же `findUngroundedNumbers()` применяется к
 *     живому ответу Claude — негрунд-числа подсвечиваются/фильтруются.
 *
 * Сознательные компромиссы (Фаза 0, документированы):
 *  - Сверка ПО МОДУЛЮ значения (знак-агностично): в тексте часто опускают знак
 *    («разрыв 29 пунктов» при факте efficiency_gap=-28.8). Для MMM опасна
 *    выдуманная ВЕЛИЧИНА, не знак. → matchNum использует abs.
 *  - Толеранс округления (LLM пишет «ROI 77.5» при факте 77.49; «12 тыс» при
 *    12186): относительный допуск + совпадение по 2–4 значащим цифрам.
 *  - Числа из строковых полей фактов (имена каналов «W 25-54», нарратив
 *    `insight`) тоже считаются grounded — LLM вправе цитировать что угодно из
 *    фактов. Флагается только истинно НОВОЕ число.
 *  - Истинно-производное число (40.7+11.9, которого нет в фактах напрямую)
 *    может быть ложно помечено. Это безопасный перекос: guard строг, и его
 *    строгость согласована с промпт-инструкцией Tier 2 «не вычисляй новых
 *    чисел». В Фазе 0 false-positive дешевле false-negative.
 *
 * @module insights-grounding
 */

/** Масштабные суффиксы (рус + лат). */
const SCALE = /** @type {const} */ ({
  'млрд': 1e9,
  'млн': 1e6,
  'тыс': 1e3,
  'тысяч': 1e3,
  'тысяча': 1e3,
  'тысячи': 1e3,
  'k': 1e3,
  'm': 1e6,
  'b': 1e9,
});

// Число с опциональной группировкой тысяч (пробел/NBSP/narrow-NBSP по 3 цифры),
// десятичной частью (точка или запятая), знаком и масштабным/процентным
// суффиксом. Глобальный + ignorecase.
const NUM_RE =
  /(-?\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?)\s*(млрд|млн|тысяч[аи]?|тыс|k|m|b)?/gi;

/**
 * @typedef {Object} ExtractedNumber
 * @property {string} raw   — исходная подстрока (для диагностики)
 * @property {number} value — нормализованное числовое значение (с учётом масштаба)
 */

/**
 * Извлекает все числовые величины из текста.
 * Понимает: «1 234 567», «12186.08», «43,3%», «77.5×», «6 млн», «11,2 млрд»,
 * «-28.8», «1.05», «2,4:1» (→ 2.4 и 1).
 *
 * @param {string | null | undefined} text
 * @returns {ExtractedNumber[]}
 */
export function extractNumbers(text) {
  /** @type {ExtractedNumber[]} */
  const out = [];
  if (typeof text !== 'string' || text.length === 0) return out;

  NUM_RE.lastIndex = 0;
  let m;
  while ((m = NUM_RE.exec(text)) !== null) {
    // Защита от потенциального нулевого совпадения (suffix-группа опциональна).
    if (m.index === NUM_RE.lastIndex) NUM_RE.lastIndex += 1;

    const numStr = m[1];
    if (!numStr) continue;
    // Убрать разделители тысяч, нормализовать десятичную запятую к точке.
    const cleaned = numStr.replace(/[\s  ]/g, '').replace(',', '.');
    let value = Number.parseFloat(cleaned);
    if (!Number.isFinite(value)) continue;

    const suffix = (m[2] || '').toLowerCase();
    if (suffix) {
      // Точное совпадение по таблице (тысяч/тысячи/тысяча → тыс уже покрыты).
      const key = suffix.startsWith('тысяч') ? 'тыс' : suffix;
      const scale = /** @type {Record<string, number>} */ (SCALE)[key];
      if (scale) value *= scale;
    }
    out.push({ raw: m[0].trim(), value });
  }
  return out;
}

/**
 * Округление к N значащим цифрам (знак-агностично на входе ожидается abs).
 * @param {number} x
 * @param {number} sig
 * @returns {number}
 */
function roundSig(x, sig) {
  if (x === 0) return 0;
  const d = Math.ceil(Math.log10(Math.abs(x)));
  const power = sig - d;
  const mag = Math.pow(10, power);
  return Math.round(x * mag) / mag;
}

/**
 * Совпадают ли два числа в пределах допуска (знак-агностично, по модулю).
 * Grounded ⟺ относительный допуск ИЛИ совпадение по 2–4 значащим цифрам.
 *
 * @param {number} v        — число из ответа LLM
 * @param {number} f        — число-факт
 * @param {number} relTol   — относительный допуск (доля), напр. 0.01 = 1%
 * @returns {boolean}
 */
function matchNum(v, f, relTol) {
  const a = Math.abs(v);
  const b = Math.abs(f);
  const denom = Math.max(b, 1);
  if (Math.abs(a - b) <= relTol * denom) return true;
  for (const sig of [2, 3, 4]) {
    if (roundSig(a, sig) === roundSig(b, sig)) return true;
  }
  return false;
}

/**
 * @typedef {Object} GroundedSet
 * @property {number[]} values — все числа-факты (по модулю не приводятся; abs в matchNum)
 * @property {(v: number, relTol?: number) => boolean} has — есть ли grounded-совпадение
 */

/**
 * Рекурсивно собирает множество допустимых чисел из фактов модели.
 * Источники:
 *  - числовые листья JSON (results: decomposition/optimization/diagnostics);
 *  - числа внутри строковых листьев (имена каналов, verdict-тексты, нарратив
 *    `insight`) — LLM вправе их цитировать;
 *  - тексты Tier-1 инсайтов (insight.text + insight.tip).
 *
 * @param {{
 *   jsonFacts?: unknown,
 *   insightTexts?: Array<string | { text?: string, tip?: string }>,
 * }} sources
 * @returns {GroundedSet}
 */
export function collectGroundedNumbers(sources = {}) {
  /** @type {number[]} */
  const values = [];
  const seen = new Set();

  /** @param {number} n */
  const add = (n) => {
    if (!Number.isFinite(n)) return;
    if (seen.has(n)) return;
    seen.add(n);
    values.push(n);
  };

  /** @param {unknown} node */
  const walk = (node) => {
    if (node === null || node === undefined) return;
    if (typeof node === 'number') {
      add(node);
      return;
    }
    if (typeof node === 'string') {
      for (const e of extractNumbers(node)) add(e.value);
      return;
    }
    if (Array.isArray(node)) {
      for (const item of node) walk(item);
      return;
    }
    if (typeof node === 'object') {
      for (const v of Object.values(/** @type {Record<string, unknown>} */ (node))) walk(v);
    }
  };

  if (sources.jsonFacts !== undefined) walk(sources.jsonFacts);

  if (Array.isArray(sources.insightTexts)) {
    for (const ins of sources.insightTexts) {
      if (typeof ins === 'string') {
        for (const e of extractNumbers(ins)) add(e.value);
      } else if (ins && typeof ins === 'object') {
        for (const e of extractNumbers(ins.text || '')) add(e.value);
        for (const e of extractNumbers(ins.tip || '')) add(e.value);
      }
    }
  }

  return {
    values,
    has(v, relTol = 0.01) {
      for (const f of values) {
        if (matchNum(v, f, relTol)) return true;
      }
      return false;
    },
  };
}

/**
 * Возвращает числа из ответа LLM, которых НЕТ в фактах (потенциальные
 * галлюцинации). Пустой массив ⟺ INV-50 соблюдён.
 *
 * @param {string} answerText
 * @param {{
 *   jsonFacts?: unknown,
 *   insightTexts?: Array<string | { text?: string, tip?: string }>,
 * }} facts
 * @param {{ relTol?: number, ignoreBelow?: number }} [opts]
 *   relTol — относительный допуск сверки (дефолт 0.01).
 *   ignoreBelow — игнорировать «мелкие» целые |v| < ignoreBelow (годы, счёт,
 *     номера шагов часто легитимны и неотличимы); дефолт 0 = проверять всё.
 * @returns {ExtractedNumber[]}
 */
export function findUngroundedNumbers(answerText, facts, opts = {}) {
  const relTol = opts.relTol ?? 0.01;
  const ignoreBelow = opts.ignoreBelow ?? 0;
  const grounded = collectGroundedNumbers(facts);
  const nums = extractNumbers(answerText);
  /** @type {ExtractedNumber[]} */
  const bad = [];
  for (const n of nums) {
    if (ignoreBelow > 0 && Number.isInteger(n.value) && Math.abs(n.value) < ignoreBelow) {
      continue;
    }
    if (!grounded.has(n.value, relTol)) bad.push(n);
  }
  return bad;
}

/**
 * Бросает исключение, если в ответе LLM есть негрунд-числа (для guard-тестов
 * и рантайм-страховки в строгом режиме).
 *
 * @param {string} answerText
 * @param {Parameters<typeof findUngroundedNumbers>[1]} facts
 * @param {Parameters<typeof findUngroundedNumbers>[2]} [opts]
 * @returns {void}
 */
export function assertGrounded(answerText, facts, opts) {
  const bad = findUngroundedNumbers(answerText, facts, opts);
  if (bad.length > 0) {
    throw new Error(
      `INV-50 violation: ungrounded numbers in LLM answer: ${bad.map((b) => b.raw).join(', ')}`,
    );
  }
}
