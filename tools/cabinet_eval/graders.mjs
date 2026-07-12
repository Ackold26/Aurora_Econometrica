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
 * Все числа ответа должны быть ⊆ числам приложенных данных (INV-50).
 * ignoreBelow=10 — годы/шаги/счёт мелких целых часто легитимны и
 * неотличимы от реальных данных (напр. «шаг 3», «за 2 месяца»).
 *
 * @param {string} answerText
 * @param {{ caseId: string, facts: unknown }} ctx
 * @returns {{ name: string, pass: boolean, details: string }}
 */
export function numbersGrounded(answerText, ctx) {
  const bad = findUngroundedNumbers(answerText, { jsonFacts: ctx.facts }, { ignoreBelow: 10 });
  return {
    name: 'numbers_grounded',
    pass: bad.length === 0,
    details:
      bad.length === 0
        ? 'Все числа ответа найдены в приложенных данных проекта.'
        : `Негрунд-числа (не найдены в фактах, INV-50): ${bad.map((b) => b.raw).join(', ')}`,
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
  const paragraphs = answerText
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .slice(0, 2);

  const first = paragraphs[0] || '';
  const firstLine = first.split('\n')[0].trim();
  const isHeadingOrList = /^(#{1,6}\s|[-*•]\s|\d+[.)]\s)/.test(firstLine);
  const takeawayUpfront = firstLine.length > 0 && firstLine.length < 250 && !isHeadingOrList;

  const hasActionBlock = /(Что сделать|Что улучшить|Что собрать|Рекомендаци|Действи|Следующий шаг|Приоритет|Стоит|Совет)/i.test(answerText);

  const pass = takeawayUpfront && hasActionBlock;
  const details = `Вывод в начале (первая строка ${firstLine.length} симв., не заголовок/список): ${takeawayUpfront}; блок действия найден: ${hasActionBlock}.`;
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
