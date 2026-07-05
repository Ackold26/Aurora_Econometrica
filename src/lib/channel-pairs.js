/**
 * channel-pairs.js — группировка парных медиа-колонок «бюджет ₽ + натуральный
 * Media KPI» одного канала (решение Антона 2026-07-05: примеры и клиентские
 * файлы несут ОБЕ колонки, чтобы проходить обе модели — ROI и Эффективность).
 *
 * Чистая логика (vitest): base канала = имя колонки без суффикса метрики;
 * `tv_spend` + `tv_trp` → канал `tv` {monetary:[tv_spend], physical:[tv_trp]}.
 * В МОДЕЛЬ одновременно идёт ОДНА колонка пары — resolvePairSelection
 * разворачивает выбор юзера {база: метрика} в per-колоночный план
 * (включить выбранные, выключить парные альтернативы) — все существующие
 * потребители (cpp-гейт, unit_costs, train-config) остаются на колонках.
 */

// ₽-маркеры и физические маркеры суффикса колонки (единый источник;
// перенесено из pipeline/+page.svelte — там теперь импорт отсюда).
// NB: в JS \w = [A-Za-z0-9_] (кириллицу НЕ включает) → русские словоформы
// закрываем явным [а-яё]* («показы/показов», «клики», «бюджета»...).
export const MONETARY_SUFFIX_RE = /(?:^|[_\s-])(?:spend(?:s|ing)?|budget|cost(?:s)?|expense|бюджет[а-яё]*|расход[а-яё]*|затрат[а-яё]*|rub|usd|eur)(?=[_\s-]|$)/i;
export const PHYSICAL_SUFFIX_RE = /(?:^|[_\s-])(?:impressions?|impr|clicks?|visits?|reach|contacts?|grps?|trps?|показ[а-яё]*|клик[а-яё]*|визит[а-яё]*|охват[а-яё]*|просмотр[а-яё]*|грп[а-яё]*|трп[а-яё]*)(?=[_\s-]|$)/i;

/** Хвостовой суффикс метрики для среза базы канала (те же словоформы). */
const TAIL_METRIC_RE = /[_\s-](?:spend(?:s|ing)?|budget|cost(?:s)?|expense|бюджет[а-яё]*|расход[а-яё]*|затрат[а-яё]*|rub|usd|eur|impressions?|impr|clicks?|visits?|reach|contacts?|grps?|trps?|показ[а-яё]*|клик[а-яё]*|визит[а-яё]*|охват[а-яё]*|просмотр[а-яё]*|грп[а-яё]*|трп[а-яё]*)$/i;

/**
 * Разбор имени медиа-колонки: база канала + вид метрики.
 * @param {string} name
 * @returns {{ base: string, metric: 'monetary'|'physical'|null }}
 */
export function parseChannelMetric(name) {
  const nm = String(name ?? '');
  const metric = MONETARY_SUFFIX_RE.test(nm) ? 'monetary'
    : PHYSICAL_SUFFIX_RE.test(nm) ? 'physical'
    : null;
  const base = metric ? nm.replace(TAIL_METRIC_RE, '').trim() || nm : nm;
  return { base, metric };
}

/**
 * Группировка media-колонок в каналы с доступными метриками.
 * Колонка без распознанного суффикса — самостоятельный канал (metric считается
 * monetary, прежнее поведение +page).
 * @param {string[]} mediaColumnNames
 * @returns {{ channels: string[], byChannel: Record<string, {monetary: string[], physical: string[]}> }}
 */
export function groupChannelColumns(mediaColumnNames) {
  /** @type {Record<string, {monetary: string[], physical: string[]}>} */
  const byChannel = {};
  /** @type {string[]} */
  const channels = [];
  for (const name of mediaColumnNames ?? []) {
    const { base, metric } = parseChannelMetric(name);
    if (!byChannel[base]) {
      byChannel[base] = { monetary: [], physical: [] };
      channels.push(base);
    }
    byChannel[base][metric ?? 'monetary'].push(name);
  }
  return { channels, byChannel };
}

/**
 * Ключи декларированных пар «бюджет ₽ × натуральный KPI» одного канала —
 * для аннотации на карте корреляций (аудит 2026-07-05: пара by-design даёт
 * r≈0.99, пугать клиента «Мультиколлинеарностью» на встроенном примере нельзя;
 * в модель уходит одна колонка пары — риска в модели нет).
 * @param {string[]} columnNames - имена колонок (labels матрицы корреляций).
 * @returns {Set<string>} ключи вида 'a|||b' (обе ориентации).
 */
export function declaredPairKeys(columnNames) {
  const { byChannel } = groupChannelColumns(columnNames);
  /** @type {Set<string>} */
  const keys = new Set();
  for (const base of Object.keys(byChannel)) {
    const { monetary, physical } = byChannel[base];
    for (const m of monetary) {
      for (const p of physical) {
        keys.add(`${m}|||${p}`);
        keys.add(`${p}|||${m}`);
      }
    }
  }
  return keys;
}

/**
 * Пара колонок — декларированная пара канала?
 * @param {Set<string>} pairKeys - из declaredPairKeys.
 * @param {string} a
 * @param {string} b
 */
export function isDeclaredPair(pairKeys, a, b) {
  return pairKeys.has(`${a}|||${b}`);
}

/**
 * Развернуть выбор по базам в план per-колонок.
 * Для каждой базы: выбранная сторона включается (с её метрикой), противоположная
 * сторона ПАРЫ выключается из модели. База с одной стороной — включается как есть.
 * @param {Record<string, {monetary: string[], physical: string[]}>} byChannel
 * @param {Record<string, 'monetary'|'physical'>} selection - {база: метрика}
 * @returns {{ perColumn: Record<string, 'monetary'|'physical'>, enable: string[], disable: string[] }}
 */
export function resolvePairSelection(byChannel, selection) {
  /** @type {Record<string, 'monetary'|'physical'>} */
  const perColumn = {};
  /** @type {string[]} */
  const enable = [];
  /** @type {string[]} */
  const disable = [];
  for (const base of Object.keys(byChannel ?? {})) {
    const opts = byChannel[base];
    const hasM = opts.monetary.length > 0;
    const hasP = opts.physical.length > 0;
    const pick = selection?.[base]
      ?? (hasM ? 'monetary' : 'physical'); // дефолт: деньги, если есть
    const chosen = pick === 'physical' && hasP ? 'physical'
      : pick === 'monetary' && hasM ? 'monetary'
      : hasM ? 'monetary' : 'physical';
    const chosenCols = chosen === 'monetary' ? opts.monetary : opts.physical;
    const otherCols = chosen === 'monetary' ? opts.physical : opts.monetary;
    for (const c of chosenCols) {
      perColumn[c] = chosen;
      enable.push(c);
    }
    for (const c of otherCols) disable.push(c);
  }
  return { perColumn, enable, disable };
}
