/**
 * Инъекция данных проекта в сообщение консультационных команд econometrist.
 *
 * Контракт этих команд (CLAUDE.md кабинета) описывает чтение JSON-артефактов
 * пайплайна (`model-diagnostics.json`, `decomposition.json`, `optimization.json`)
 * из workspace, но runtime-restriction запрещает env-пути, и ни один код не
 * кладёт эти файлы в workspace консультационного кабинета — Claude физически
 * не может их прочитать. Правило проекта №10 (CLAUDE.md): «Pipeline context —
 * inject в message, не файл». Этот модуль строит текстовый блок с данными
 * проекта и прикладывает его к сообщению команды перед отправкой.
 *
 * @module econ-project-context
 */

/** Slash-команды, которым нужны данные проекта (консультационный кабинет econometrist). */
export const ECON_DATA_COMMANDS = [
  '/interpret-model',
  '/why-channel',
  '/explain-ratio',
  '/pilot-design',
  '/next-quarter-plan',
  '/data-gaps',
];

/**
 * Убрать из артефакта оптимизации служебную телеметрию — та же логика, что
 * stripOptTelemetry в tier2-context.js (её числа не для цитирования, только
 * расширяют поверхность случайных совпадений в промпте).
 * @param {any} opt
 * @returns {any}
 */
function stripOptTelemetry(opt) {
  if (!opt || typeof opt !== 'object') return opt ?? null;
  const { slsqp_diagnostics, response_curves, ...rest } = opt;
  return rest;
}

/**
 * Отрендерить один артефакт секции: JSON компактно или «нет – шаг … не пройден».
 * @param {any} data
 * @param {string} stepLabel - название шага для сообщения об отсутствии (например «Модель»)
 * @returns {string}
 */
function renderArtifact(data, stepLabel) {
  if (data === null || data === undefined) {
    return `нет – шаг «${stepLabel}» не пройден`;
  }
  return JSON.stringify(data);
}

/**
 * Компактная выжимка валидации для блока данных: команды explain-ratio и
 * data-gaps опираются на ratio/предикторы/частоту — весь validation.result
 * класть нельзя (сырые статистики колонок раздувают промпт), берём решающее.
 * @param {any} val - содержимое стора validateData
 * @returns {any|null}
 */
function summarizeValidation(val) {
  const r = val?.result;
  if (!r || typeof r !== 'object') return null;
  const cols = Array.isArray(r.columns) ? r.columns : [];
  const names = (/** @type {string} */ role) =>
    cols.filter((/** @type {any} */ c) => c.role === role).map((/** @type {any} */ c) => c.name);
  const out = {
    ratio: r.detected?.ratio ?? r.ratio ?? null,
    n_rows: r.file?.rows ?? r.n_rows ?? null,
    date_frequency: r.detected?.date_frequency ?? r.date_frequency ?? null,
    media_columns: names('media'),
    control_columns: names('control'),
    kpi_columns: names('kpi'),
    high_correlations: r.high_correlations ?? r.correlationWarnings ?? null,
  };
  // Пустая выжимка (ни одного заполненного поля) — считаем, что валидации нет.
  const hasAny = Object.values(out).some((v) => v !== null && (!Array.isArray(v) || v.length > 0));
  return hasAny ? out : null;
}

/**
 * Построить текстовый блок с данными проекта для приложения к сообщению.
 *
 * @param {{
 *   mod?: any,
 *   dec?: any,
 *   opt?: any,
 *   val?: any,
 *   projectMeta?: {name?: string|null, kpi_type?: string|null, period?: string|null}|null,
 * }} input
 * @returns {string}
 */
export function buildProjectDataBlock({ mod, dec, opt, val, projectMeta } = {}) {
  const lines = [
    '',
    '',
    '=== Данные проекта (приложены приложением) ===',
    '[model-diagnostics]',
    renderArtifact(mod, 'Модель'),
    '[decomposition]',
    renderArtifact(dec, 'Декомпозиция'),
    '[optimization]',
    renderArtifact(opt ? stripOptTelemetry(opt) : opt, 'Оптимизация'),
    '[validation]',
    renderArtifact(summarizeValidation(val), 'Валидация'),
  ];

  if (projectMeta && typeof projectMeta === 'object') {
    lines.push('[project]', JSON.stringify(projectMeta));
  }

  return lines.join('\n');
}
