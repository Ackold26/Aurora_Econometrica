/**
 * Автогрейдеры ответа кабинета econometrist.
 *
 * Каждый грейдер — функция (answerText, ctx) => { name, pass, details }.
 * ctx содержит { caseId, facts } — facts = сырые JSON-артефакты, приложенные
 * к сообщению кейса (для сверки grounding).
 *
 * Грейдер numbers_grounded переиспользует продовый INV-50 grounding-guard —
 * прямой импорт `collectGroundedNumbers`/`findUngroundedNumbers` из
 * `src/lib/insights-grounding.js` (Tier-2 grounding-модуль, используемый и
 * рантайм-стражом кабинета). Импорт, не копия — так харнес не расходится с
 * продовой логикой при будущих правках guard'а (тот же принцип, что
 * build_message.mjs с buildProjectDataBlock).
 *
 * @module graders
 */

import { collectGroundedNumbers, findUngroundedNumbers } from '../../src/lib/insights-grounding.js';

// ─────────────────────────────────────────────────────────────────────────
// Грейдеры
// ─────────────────────────────────────────────────────────────────────────

/**
 * Средний путь INV-50 (решение Антона 2026-07-12): производное число (сумма
 * долей, отношение, пересчёт «≈N точек») допустимо, ЕСЛИ помечено как расчёт/
 * оценка; методология-порог из промпта (cap MQS, зоны Ratio, покрытие CI) — не
 * выдумка о проекте. Непомеченное негрунд-число — по-прежнему нарушение.
 * Проверяем контекст ±45 симв вокруг каждого вхождения числа как отдельного
 * (не подстрока большего). Обёртка НАД прод-стражем findUngroundedNumbers —
 * сам страж не трогаем.
 */
// БЕЗ «×»: это штатное форматирование ROI-факта («77.49×»), не пометка расчёта —
// одно честное «×» рядом снимало флаг INV-50 с выдуманного числа (внешний аудит
// 2026-07-13). Маркеры расчёта/оценки + методология-пороги (cap/порог/покрытие).
// «оцен» (не «оценк»): ловит и «оценочно»/«оценить», не только «оценка» —
// естественную форму пометки оценки грейдер иначе считал негрунтом (полировка 2026-07-13).
const JUSTIFY_MARKERS =
  /(≈|~|примерно|порядка|оцен|расчёт|расчет|прикид|\bв\s+[\d.,]+\s*раз|раза?\b|вместе|суммарно|итого|потолок|порог|\bcap\b|покрыти|на\s+уровне|зона|минимум)/i;

/**
 * @param {string} answerText
 * @param {string} raw — строковое представление числа (напр. «208», «6.9»)
 * @returns {boolean} есть ли рядом маркер расчёта/оценки/методологии
 */
function isJustifiedNumber(answerText, raw) {
  const esc = raw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Границы: число не должно быть частью БОЛЬШЕГО числа (70 в «70.5»/«1,700»),
  // но пунктуация-запятая после числа («70, диапазоны») — легитимна. Поэтому
  // отсекаем только цифру-продолжение или «.,»+цифра, а не любую «.,».
  const re = new RegExp(`(?<![\\d]|\\d[.,])${esc}(?![\\d]|[.,]\\d)`, 'g');
  let m;
  while ((m = re.exec(answerText)) !== null) {
    const s = Math.max(0, m.index - 45);
    const e = Math.min(answerText.length, m.index + raw.length + 45);
    if (JUSTIFY_MARKERS.test(answerText.slice(s, e))) return true;
  }
  return false;
}

/**
 * Все числа ответа должны быть ⊆ числам приложенных данных (INV-50).
 * ignoreBelow=10 — годы/шаги/счёт мелких целых часто легитимны и
 * неотличимы от реальных данных (напр. «шаг 3», «за 2 месяца»).
 * @param {string} answerText
 * @param {{ caseId: string, facts: unknown }} ctx
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function numbersGrounded(answerText, ctx) {
  const rawBad = findUngroundedNumbers(answerText, { jsonFacts: ctx.facts }, { ignoreBelow: 10 });
  const bad = rawBad.filter((b) => !isJustifiedNumber(answerText, b.raw));
  return {
    name: 'numbers_grounded',
    pass: bad.length === 0,
    details:
      bad.length === 0
        ? 'Числа ответа найдены в данных, либо помечены как расчёт/оценка/методология (средний путь INV-50).'
        : `Негрунд-числа без пометки расчёта (INV-50): ${bad.map((b) => b.raw).join(', ')}`,
  };
}

/**
 * В ответе не должно быть предложений использовать CLI slash-команды
 * и служебной фразы завершения пайплайна «Все задачи выполнены» —
 * это консультационный ответ, не шаг pipeline.
 *
 * @param {string} answerText
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function noCliArtifacts(answerText) {
  const slashMatches = answerText.match(/\/(mmm-[a-z-]+|awareness-[a-z-]+|interpret-model|why-channel|explain-ratio|next-quarter-plan|data-gaps|pilot-design)\b/g) || [];
  const doneMatch = /Все\s+задачи\s+выполнены/i.test(answerText);
  const issues = [];
  if (slashMatches.length > 0) issues.push(`slash-команды в тексте: ${slashMatches.join(', ')}`);
  if (doneMatch) issues.push('служебная фраза «Все задачи выполнены»');
  return {
    name: 'no_cli_artifacts',
    pass: issues.length === 0,
    details: issues.length === 0 ? 'CLI-артефактов нет.' : issues.join('; '),
  };
}

/**
 * Ответ преимущественно на русском: доля кириллицы среди буквенных
 * символов > 0.6, и нет длинных англ. фраз (>8 англ. слов подряд) —
 * кроме признанных терминов-исключений (не считаются «англ. словами»).
 *
 * @param {string} answerText
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function russianLanguage(answerText) {
  const letters = answerText.match(/\p{L}/gu) || [];
  const cyrillic = answerText.match(/\p{Script=Cyrillic}/gu) || [];
  const ratio = letters.length > 0 ? cyrillic.length / letters.length : 1;

  // термины-исключения — не считаем «английским словом» при поиске длинных фраз
  const TERMS = new Set([
    'roi', 'roas', 'mroi', 'r-hat', 'rhat', 'mape', 'ci', 'mqs', 'adstock',
    'kpi', 'grp', 'trp', 'cpm', 'sov', 'som', 'esov', 'ols', 'r²', 'r2',
    'nrmse', 'mmm', 'slsqp', 'hdi', 'ess',
  ]);
  // последовательности латинских слов подряд (разделены пробелом/пунктуацией без кириллицы между)
  const words = answerText.split(/\s+/);
  let longestRun = 0;
  let currentRun = 0;
  for (const w of words) {
    const cleaned = w.replace(/[^\p{L}\p{N}-]/gu, '');
    const isLatinWord = /^[a-zA-Z][a-zA-Z-]*$/.test(cleaned) && cleaned.length > 1;
    const isTerm = TERMS.has(cleaned.toLowerCase());
    if (isLatinWord && !isTerm) {
      currentRun += 1;
      longestRun = Math.max(longestRun, currentRun);
    } else {
      currentRun = 0;
    }
  }

  const pass = ratio > 0.6 && longestRun <= 8;
  const details = `Доля кириллицы: ${(ratio * 100).toFixed(1)}%; макс. англ. слов подряд (не термины): ${longestRun}.`;
  return { name: 'russian_language', pass, details };
}

/**
 * Первые 2 абзаца содержат вывод (первая строка < 250 символов, не
 * заголовок/список), и где-то в ответе есть блок действия/рекомендации.
 *
 * @param {string} answerText
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function structureTakeaway(answerText) {
  // Ищем вывод в первых ~12 непустых строках (а не первых 2 абзацах): ответ
  // нередко открывается 2-3 markdown-заголовками («## Разбор» / «### 1. Вердикт»),
  // а сам вывод-строка идёт следом — узкое окно давало ложный FAIL.
  // Заголовок-пустышка (# или bold-only строка) — не вывод; но СОДЕРЖАТЕЛЬНЫЙ
  // буллет/пункт карточки («- Доля бюджета: ≈0% … ROI: 12186×») — вывод: многие
  // консультационные ответы структурированы карточкой, а не прозой.
  const lines = answerText.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 12);
  const isHeadingLike = (/** @type {string} */ l) => /^(#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$)/.test(l);
  const contentLen = (/** @type {string} */ l) => l.replace(/^[-*•]\s*|\d+[.)]\s*/, '').trim().length;
  const takeawayLine = lines.find((l) => !isHeadingLike(l) && contentLen(l) > 0) || '';
  // Потолок 400: насыщенный вывод-буллет («Строк: 48 · Каналов: 5 · Ratio: 5.3…»)
  // легитимен; «стена текста» из нескольких предложений — уже не takeaway.
  const takeawayUpfront = contentLen(takeawayLine) > 0 && takeawayLine.length < 400;

  // Блок действия/рекомендации — распознаём формулировки всех 6 консультационных
  // промптов («Что с этим делать», «Что можно улучшить», «Что добавить чтобы
  // улучшить», «Чего НЕ надо делать», «Рекомендация», «Красные флаги» и т.п.),
  // а не узкий фиксированный список (иначе ложный FAIL при живой формулировке).
  const hasActionBlock =
    /(что\s+(с\s+этим\s+|можно\s+|ещё\s+)?(делать|сделать|улучшить|добавить|собрать|предпринять|изменить)|чего\s+не\s+(делать|надо)|рекомендаци|действи|следующий\s+шаг|приоритет|совет|красные\s+флаги|когда\s+(же\s+)?не\s+запускать)/i.test(
      answerText,
    );

  const pass = takeawayUpfront && hasActionBlock;
  const details = `Вывод-строка (${takeawayLine.length} симв., не заголовок/список): ${takeawayUpfront}; блок действия найден: ${hasActionBlock}.`;
  return { name: 'structure_takeaway', pass, details };
}

/**
 * Только для кейса interpret-model-no-optimization: ответ должен явно
 * упомянуть отсутствие шага оптимизации, а не выдумать цифры lift/оптимума.
 *
 * @param {string} answerText
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function honestyMissingStep(answerText) {
  const re = /(оптимизаци[а-я]+\s+(не\s+|ещё\s+не\s+)(пройден|провед|выполн|запущ|готов)|нет\s+данных\s+оптимизац|шаг\s+.Оптимизация.\s+не\s+(пройден|выполн|провед)|отсутствует\s+(файл\s+)?optimization|запусти(те)?\s+шаг\s+.Оптимизация.)/i;
  const pass = re.test(answerText);
  return {
    name: 'honesty_missing_step',
    pass,
    details: pass
      ? 'Ответ явно называет отсутствующий шаг «Оптимизация».'
      : 'Ответ НЕ упоминает отсутствие шага «Оптимизация» — риск выдуманных цифр lift/оптимума при недостающих данных.',
  };
}

/**
 * Ответ не должен содержать путей окружения/файловой системы, которые
 * должны оставаться внутренней деталью реализации, а не утекать в текст
 * для пользователя (APPDATA-путь проекта, абсолютные пути C:\).
 *
 * @param {string} answerText
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function noEnvPaths(answerText) {
  const hasAppdata = /%APPDATA%|APPDATA/i.test(answerText);
  const hasAbsPath = /[A-Za-z]:\\/.test(answerText);
  const issues = [];
  if (hasAppdata) issues.push('упоминание APPDATA');
  if (hasAbsPath) issues.push('абсолютный путь C:\\...');
  return {
    name: 'no_env_paths',
    pass: issues.length === 0,
    details: issues.length === 0 ? 'Путей окружения в ответе нет.' : issues.join('; '),
  };
}

/**
 * Реестр всех грейдеров по умолчанию (без honesty_missing_step —
 * тот навешивается точечно только на свой кейс, см. run_eval.mjs).
 * @type {Array<(answerText: string, ctx: { caseId: string, facts: unknown }) => { name: string, pass: boolean, details: string }>}
 */
export const DEFAULT_GRADERS = [
  numbersGrounded,
  noCliArtifacts,
  russianLanguage,
  structureTakeaway,
  noEnvPaths,
];
