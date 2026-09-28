/**
 * SSOT форматирования периода наблюдений с учётом гранулярности.
 *
 * Используется в ModeDerivedExplanation (порог-предупреждение) и ReportStep
 * (интерпретационные тексты). Единица и порог берутся из гранулярности,
 * не хардкодятся.
 */

/**
 * @typedef {'W' | 'M' | 'Q' | 'D' | string} Granularity
 */

/**
 * Текстовая единица периода («нед» / «мес» / «кв» / «пер») для данной гранулярности.
 *
 * @param {Granularity | null | undefined} granularity
 * @returns {string}
 */
export function periodUnit(granularity) {
  const g = (granularity ?? 'W').toUpperCase();
  if (g === 'W') return 'нед';
  if (g === 'M') return 'мес';
  if (g === 'Q') return 'кв';
  return 'пер';
}

/**
 * Рекомендуемый минимальный порог наблюдений для данной гранулярности.
 * Ниже порога — показывать предупреждение в UI.
 *
 * @param {Granularity | null | undefined} granularity
 * @returns {number}
 */
export function periodThreshold(granularity) {
  const g = (granularity ?? 'W').toUpperCase();
  if (g === 'W') return 52;
  if (g === 'M') return 24;
  if (g === 'Q') return 8;
  return 52; // дефолт — консервативный недельный порог
}

/**
 * Форматирует число наблюдений с правильной единицей и склонением.
 *
 * Примеры:
 *   formatPeriodLabel(36, 'W')  → «36 нед»
 *   formatPeriodLabel(12, 'M')  → «12 мес»
 *
 * @param {number} n - число наблюдений
 * @param {Granularity | null | undefined} granularity
 * @returns {string}
 */
export function formatPeriodLabel(n, granularity) {
  return `${n} ${periodUnit(granularity)}`;
}

/**
 * Русское склонение слова «период» с числом.
 * Вынесено из ReportStep.svelte (L13, math-fix v1.4 Section C, 2026-04-29).
 *
 * Примеры:
 *   ruPeriodForm(1)  → «1 период»
 *   ruPeriodForm(2)  → «2 периода»
 *   ruPeriodForm(21) → «21 период»
 *   ruPeriodForm(5)  → «5 периодов»
 *
 * @param {number} n
 * @returns {string}
 */
export function ruPeriodForm(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} период`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${n} периода`;
  return `${n} периодов`;
}

// ── Края срока плана (L2, s55) ──────────────────────────────────────────────
// Экран шага планирования показывал сырые метки движка («2025-W01 – 2025-W32»),
// а отчёт после s53 – «дек 2024 – авг 2025» (неделя 2025-W01 начинается
// 30.12.2024, поэтому год края на экране и в отчёте расходился). Правило – то же,
// что `format_period_span` движка (engines/narrative_adapter.py): ISO-дата →
// «мес год»; квартал → «I кв. 2026»; год → «2026»; неразборчивая метка – обе как
// есть, без смешения форматов; оба края в одном месяце – один «мес год».
// Правка правила в одном месте требует правки и в другом (сторож – тесты рядом).

const RU_MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const RU_QUARTERS = ['I', 'II', 'III', 'IV'];

/**
 * Метка → {year, month} по первым 10 символам ISO-даты; иначе null.
 *
 * @param {unknown} label
 * @returns {{ year: number, month: number } | null}
 */
function parseIsoLabel(label) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(label ?? ''));
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month };
}

/**
 * Подпись края для квартальных/годовых данных или null.
 *
 * @param {unknown} label
 * @param {Granularity | null | undefined} granularity
 * @returns {string | null}
 */
function quarterOrYearLabel(label, granularity) {
  const s = String(label ?? '').trim();
  let m = /^(\d{4})-Q([1-4])$/.exec(s);
  if (m) return `${RU_QUARTERS[Number(m[2]) - 1]} кв. ${m[1]}`;
  m = /^(\d{4})$/.exec(s);
  if (m) return m[1];
  const d = parseIsoLabel(label);
  if (!d) return null;
  const g = (granularity ?? '').toUpperCase();
  if (g === 'Q') return `${RU_QUARTERS[Math.floor((d.month - 1) / 3)]} кв. ${d.year}`;
  if (g === 'Y') return String(d.year);
  return null;
}

/**
 * Края срока для человека: «дек 2024 – авг 2025» (тире U+2013).
 *
 * Примеры:
 *   formatPeriodSpan('2024-12-30T00:00:00', '2025-08-04T00:00:00', 'W') → «дек 2024 – авг 2025»
 *   formatPeriodSpan('2026-01-01', '2026-10-01', 'Q') → «I кв. 2026 – IV кв. 2026»
 *   formatPeriodSpan('2025-W01', '2025-W32') → «2025-W01 – 2025-W32» (не дата – как есть)
 *
 * @param {unknown} first
 * @param {unknown} last
 * @param {Granularity | null | undefined} [granularity]
 * @returns {string}
 */
export function formatPeriodSpan(first, last, granularity) {
  const qa = quarterOrYearLabel(first, granularity);
  const qb = quarterOrYearLabel(last, granularity);
  if (qa !== null && qb !== null) return qa === qb ? qa : `${qa} – ${qb}`;
  const a = parseIsoLabel(first);
  const b = parseIsoLabel(last);
  if (!a || !b) return `${first} – ${last}`;
  const la = `${RU_MONTHS_SHORT[a.month - 1]} ${a.year}`;
  const lb = `${RU_MONTHS_SHORT[b.month - 1]} ${b.year}`;
  return la === lb ? la : `${la} – ${lb}`;
}

/**
 * Края срока найденного медиаплана из ответа проверки данных
 * (`media_plan_detected`): по датам `future_dates`, а если их нет (старые
 * сохранённые проекты) – по меткам `period_labels`. Нет ни того ни другого – ''.
 *
 * @param {{ future_dates?: unknown[] | null, period_labels?: unknown[] | null, granularity?: string | null } | null | undefined} mp
 * @returns {string}
 */
export function formatMediaPlanSpan(mp) {
  const dates = Array.isArray(mp?.future_dates) ? mp.future_dates.filter(Boolean) : [];
  const labels = Array.isArray(mp?.period_labels) ? mp.period_labels.filter(Boolean) : [];
  const src = dates.length ? dates : labels;
  if (!src.length) return '';
  return formatPeriodSpan(src[0], src[src.length - 1], mp?.granularity);
}

/**
 * Число периодов плана словами по гранулярности: «32 недели», «8 месяцев»,
 * «4 квартала», «2 года», «10 дней»; неизвестная – «N периодов».
 * (Экран сравнивал гранулярность с 'week', а движок отдаёт 'W' – ветка
 * «недель» не срабатывала никогда, и выводилось «32 периодов».)
 *
 * @param {number} n
 * @param {Granularity | null | undefined} granularity
 * @returns {string}
 */
export function ruPlanPeriodsForm(n, granularity) {
  /** @type {Record<string, [string, string, string]>} */
  const forms = {
    W: ['неделя', 'недели', 'недель'],
    M: ['месяц', 'месяца', 'месяцев'],
    Q: ['квартал', 'квартала', 'кварталов'],
    Y: ['год', 'года', 'лет'],
    D: ['день', 'дня', 'дней'],
  };
  const f = forms[(granularity ?? '').toUpperCase()];
  if (!f) return ruPeriodForm(n);
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} ${f[0]}`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${n} ${f[1]}`;
  return `${n} ${f[2]}`;
}
