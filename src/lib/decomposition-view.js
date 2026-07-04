/**
 * decomposition-view.js — чистая view-логика 4-групповой декомпозиции timeline.
 *
 * SSOT для двухуровневого отображения (Т3, решение Антона 2026-07-04): свёртка
 * серий по верхнему уровню (top_group) в 4 полосы + drill-down раскрытие группы
 * в под-компоненты. Вынесено из ChannelTimeline.svelte, чтобы КОНТРАКТНУЮ логику
 * (тождество свёрнутой суммы == развёрнутой) покрыть vitest — svelte-check её не
 * ловит (урок F-2: golden-контракты падают только под vitest).
 *
 * Backend SSOT (decomposer.build_decomposition_series) уже проставляет top_group
 * на КАЖДОЙ серии и pct_of_base[] на полосе «Сезонность». Здесь — только
 * группировка/агрегация для рендера, БЕЗ echarts/стилей (presentation в компоненте).
 *
 * @typedef {{
 *   name: string,
 *   role?: 'baseline'|'media'|'factor',
 *   type?: string,
 *   group?: string,
 *   top_group?: string,
 *   side?: 'positive'|'negative',
 *   data: number[],
 *   pct_of_base?: number[],
 * }} DecompSeries
 */

/** Верхний уровень 4 групп декомпозиции (порядок стека снизу вверх). */
export const TOP_GROUP_ORDER = ['БАЗА', 'МЕДИА', 'ВНЕШНИЕ ФАКТОРЫ', 'КОНКУРЕНТЫ'];

/**
 * Капс top_group → человекочитаемый заголовок (chips, tooltip, имя агрегата).
 * @type {Record<string, string>}
 */
export const TOP_GROUP_DISPLAY = {
  'БАЗА': 'База',
  'МЕДИА': 'Медиа',
  'ВНЕШНИЕ ФАКТОРЫ': 'Внешние факторы',
  'КОНКУРЕНТЫ': 'Конкуренты',
};

/**
 * Fallback top_group по имени серии — для legacy pickle без поля top_group
 * (decomposition.json до Т2 2026-07-04) и legacy signedFactors-пути. Зеркалит
 * _TOP_GROUP_MAP из decomposer.py, но по отображаемому имени «Группа: имя».
 * @param {string} name
 * @returns {string}
 */
export function fallbackTopGroup(name) {
  const nm = String(name ?? '');
  if (nm === 'Базовый уровень' || nm === 'Базовая линия'
      || nm.startsWith('Сезонность:') || nm.startsWith('Праздники:')) return 'БАЗА';
  if (nm.startsWith('Конкуренты:')) return 'КОНКУРЕНТЫ';
  if (nm.startsWith('Внешние:') || nm.startsWith('Цена:') || nm.startsWith('Погода:')
      || nm.startsWith('Макро-факторы:') || nm.startsWith('Категория:')
      || nm.startsWith('Дистрибуция:')) return 'ВНЕШНИЕ ФАКТОРЫ';
  // Аудит Т3 (А-3): точные имена без префикса — агрегированные факторы SSOT
  // («Сезонность» — ключ агрегации Фурье) и display-имена свёрнутых групп.
  if (nm === 'Сезонность' || nm === 'Праздники' || nm === 'База') return 'БАЗА';
  if (nm === 'Конкуренты') return 'КОНКУРЕНТЫ';
  if (nm === 'Цена' || nm === 'Погода' || nm === 'Макро-факторы' || nm === 'Категория'
      || nm === 'Дистрибуция' || nm === 'Внешние' || nm === 'Внешние факторы') return 'ВНЕШНИЕ ФАКТОРЫ';
  return 'МЕДИА';
}

/**
 * top_group серии: из поля (SSOT) либо fallback по сырому имени.
 * @param {DecompSeries} s
 * @returns {string}
 */
export function topGroupOf(s) {
  const tg = s?.top_group;
  if (tg && TOP_GROUP_ORDER.includes(tg)) return tg;
  return fallbackTopGroup(s?.name ?? '');
}

/**
 * Нормализует ряд к длине n: числа, невалидное → 0, добивка нулями.
 * @param {number[]|undefined} data
 * @param {number} n
 * @returns {number[]}
 */
function normalizeData(data, n) {
  const out = new Array(n).fill(0);
  if (Array.isArray(data)) {
    const lim = Math.min(n, data.length);
    for (let t = 0; t < lim; t++) {
      const v = Number(data[t]);
      out[t] = Number.isFinite(v) ? v : 0;
    }
  }
  return out;
}

/**
 * Список присутствующих top_group в каноническом порядке (для chips).
 * @param {{ series?: DecompSeries[] }} ds
 * @returns {string[]}
 */
export function presentTopGroups(ds) {
  const series = Array.isArray(ds?.series) ? ds.series : [];
  const seen = new Set();
  for (const s of series) seen.add(topGroupOf(s));
  return [
    ...TOP_GROUP_ORDER.filter((g) => seen.has(g)),
    ...[...seen].filter((g) => !TOP_GROUP_ORDER.includes(g)),
  ];
}

/**
 * @typedef {Object} PlanSeries
 * @property {'group'|'member'} kind
 * @property {string} topGroup   — БАЗА/МЕДИА/ВНЕШНИЕ ФАКТОРЫ/КОНКУРЕНТЫ
 * @property {string} name       — member: сырое имя серии; group: человекочитаемое
 * @property {'baseline'|'media'|'factor'|undefined} [role]
 * @property {string|undefined} [type]
 * @property {'positive'|'negative'} side
 * @property {number[]} data
 * @property {number} [memberCount] - для kind='group': число свёрнутых под-компонентов
 */

/**
 * Логический план серий по состоянию раскрытия.
 *   • свёрнутая группа → ОДНА агрегированная полоса (поэлементная Σ членов);
 *   • раскрытая группа → её члены отдельными полосами (исходный порядок).
 *
 * Тождество (гарантируется конструкцией и проверяется тестом): для любого
 * expanded поэлементная сумма data всех plan-серий равна сумме data всех
 * исходных ds.series. Стек-назначение (side) агрегата — по знаку суммарного
 * вклада группы; на данные не влияет.
 *
 * @param {{ dates?: string[], series?: DecompSeries[] }} ds
 * @param {Set<string>|Iterable<string>} [expanded] - раскрытые top_group
 * @returns {{ plan: PlanSeries[], groups: {topGroup:string, memberCount:number, expanded:boolean}[], n:number }}
 */
export function planViewSeries(ds, expanded) {
  const series = Array.isArray(ds?.series) ? ds.series : [];
  const expandedSet = expanded instanceof Set ? expanded : new Set(expanded ?? []);
  const n = series.reduce(
    (m, s) => Math.max(m, Array.isArray(s?.data) ? s.data.length : 0),
    0,
  );

  /** @type {Map<string, DecompSeries[]>} */
  const byGroup = new Map();
  for (const s of series) {
    const tg = topGroupOf(s);
    if (!byGroup.has(tg)) byGroup.set(tg, []);
    /** @type {DecompSeries[]} */ (byGroup.get(tg)).push(s);
  }

  const orderedGroups = [
    ...TOP_GROUP_ORDER.filter((g) => byGroup.has(g)),
    ...[...byGroup.keys()].filter((g) => !TOP_GROUP_ORDER.includes(g)),
  ];

  /** @type {PlanSeries[]} */
  const plan = [];
  /** @type {{topGroup:string, memberCount:number, expanded:boolean}[]} */
  const groups = [];

  for (const tg of orderedGroups) {
    const members = byGroup.get(tg) ?? [];
    const isExpanded = expandedSet.has(tg);
    groups.push({ topGroup: tg, memberCount: members.length, expanded: isExpanded });

    if (isExpanded) {
      for (const s of members) {
        plan.push({
          kind: 'member',
          topGroup: tg,
          name: s.name,
          role: s.role,
          type: s.type,
          side: s.side === 'negative' ? 'negative' : 'positive',
          data: normalizeData(s.data, n),
        });
      }
    } else {
      const agg = new Array(n).fill(0);
      for (const s of members) {
        const d = normalizeData(s.data, n);
        for (let t = 0; t < n; t++) agg[t] += d[t];
      }
      const sum = agg.reduce((a, b) => a + b, 0);
      plan.push({
        kind: 'group',
        topGroup: tg,
        name: TOP_GROUP_DISPLAY[tg] ?? tg,
        side: sum < 0 ? 'negative' : 'positive',
        data: agg,
        memberCount: members.length,
      });
    }
  }

  return { plan, groups, n };
}

/**
 * Симметричная граница %-оси сезонной кривой: наименьшее кратное step,
 * покрывающее max|pct|. Симметрия min=-bound / max=+bound центрирует ноль
 * оси — волна ±% читается вокруг нулевой линии (аудит Т3, А-4).
 * @param {number[]|null|undefined} pct
 * @param {number} [step]
 * @returns {number}
 */
export function symmetricPctBound(pct, step = 5) {
  const list = Array.isArray(pct) ? pct : [];
  let maxAbs = 0;
  for (const v of list) {
    const n = Math.abs(Number(v));
    if (Number.isFinite(n) && n > maxAbs) maxAbs = n;
  }
  if (!(maxAbs > 0)) return step;
  return Math.ceil(maxAbs / step) * step;
}

/**
 * Стабильная identity echarts-серии для universalTransition (П1 плавное
 * раскрытие) и регрессии (П3). Все серии одной top_group несут ОДИН groupId →
 * при переходе свёрнуто↔развёрнуто ECharts морфит агрегат ↔ составляющие
 * (one-to-many divide по groupId). id уникален в пределах option (kind+topGroup+
 * name; name члена в пределах группы уникален).
 * @param {{kind:'group'|'member', topGroup:string, name:string}} p
 * @returns {{ id: string, groupId: string }}
 */
export function seriesIdentity(p) {
  const groupId = p.topGroup;
  const id = p.kind === 'group' ? `grp:${p.topGroup}` : `mem:${p.topGroup}:${p.name}`;
  return { id, groupId };
}

/**
 * Помесячная сезонность «% к базе» (pct_of_base) из серии «Сезонность».
 * Дериватив-подача (решение Антона: мультипликативно «февраль +60% к базе»),
 * не стековая полоса — извлекается независимо от свёртки/раскрытия.
 * @param {{ series?: DecompSeries[] }} ds
 * @returns {number[]|null}
 */
export function seasonalityPctOfBase(ds) {
  const series = Array.isArray(ds?.series) ? ds.series : [];
  const season = series.find(
    (s) => s?.type === 'seasonality' && Array.isArray(s.pct_of_base) && s.pct_of_base.length > 0,
  );
  if (!season || !season.pct_of_base) return null;
  return season.pct_of_base.map((v) => {
    const num = Number(v);
    return Number.isFinite(num) ? num : 0;
  });
}
