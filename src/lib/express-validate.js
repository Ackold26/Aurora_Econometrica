/**
 * П1-ядро (волна UXP, одобрено Антоном 2026-07-03): экспресс-подтверждение
 * Валидации для happy-path — «Автоматика уже настроила шаг: принять и
 * продолжить» одним нажатием вместо 5 под-шагов подтверждений.
 *
 * Узкие гейты (безопасность выше охвата): только денежный KPI (цена единицы
 * не нужна), только чистая валидация (детект грязи данных обязан остаться
 * на штатном пути), только валидный по детекту KPI. Каналы принимаются
 * «все в рублях» (режим ROI) — ровно то, что сделал бы пользователь,
 * пройдя под-шаги без правок; физические каналы (TRP) требуют цены
 * единицы → это НЕ happy-path, экспресс не предлагается, если детект
 * классифицировал канал как физический.
 *
 * Полная перестройка «Валидация одним экраном» (сводка всех решений
 * с точечным редактированием) — после живой GUI-сессии: перестройку
 * экрана первого дня клиента нельзя катить без click-path (уроки C3).
 */

/** Человеческие ярлыки денежных KPI (гейт допускает только их). */
const MONETARY_LABELS = {
  sales: 'Выручка',
  revenue: 'Выручка',
  profit: 'Прибыль',
};

/**
 * Решить, доступно ли экспресс-подтверждение, и собрать план применения.
 *
 * @param {object} args
 * @param {any} args.validateResult - $validateData.result (детект ролей).
 * @param {string} args.currentKPI - выбранный (обычно предвыбранный) KPI id.
 * @param {boolean} args.kpiUnavailable - KPI вне available_kpi_types (UX-2).
 * @param {'monetary'|'count'|string} args.kpiKind - вид выбранного KPI.
 * @param {(name: string) => boolean} [args.isPhysicalChannel] - классификатор
 *   канала (детект «физических» единиц: TRP/GRP/показы). Необязателен:
 *   без него физичность определяется грубой эвристикой по имени.
 * @returns {{
 *   eligible: boolean,
 *   reason: string,
 *   kpiLabel: string,
 *   mediaChannels: string[],
 *   uniform: Record<string, 'monetary'>,
 * }}
 */
export function buildExpressPlan({
  validateResult,
  currentKPI,
  kpiUnavailable,
  kpiKind,
  isPhysicalChannel,
}) {
  /** @type {{eligible: boolean, reason: string, kpiLabel: string, mediaChannels: string[], uniform: Record<string, 'monetary'>}} */
  const out = {
    eligible: false,
    reason: '',
    kpiLabel: MONETARY_LABELS[/** @type {keyof typeof MONETARY_LABELS} */ (currentKPI)] ?? currentKPI,
    mediaChannels: [],
    uniform: {},
  };
  if (!validateResult) {
    out.reason = 'нет результата валидации';
    return out;
  }
  if (validateResult.status === 'error') {
    out.reason = 'валидация нашла критичные проблемы данных — нужен штатный путь';
    return out;
  }
  if (!currentKPI || kpiUnavailable) {
    out.reason = 'KPI не определён или недоступен по данным';
    return out;
  }
  if (kpiKind !== 'monetary') {
    out.reason = 'KPI в штуках требует цену единицы — нужен штатный путь';
    return out;
  }
  const cols = Array.isArray(validateResult.columns) ? validateResult.columns : [];
  const media = cols
    .filter((/** @type {any} */ c) => c?.role === 'media')
    .map((/** @type {any} */ c) => String(c.name));
  if (media.length < 2) {
    out.reason = 'меньше двух медиа-каналов — MMM не собрать';
    return out;
  }
  const physical = media.filter((/** @type {string} */ name) => (
    typeof isPhysicalChannel === 'function'
      ? isPhysicalChannel(name)
      : /\b(?:trp|grp|ooh|показ|impress)/i.test(name)
  ));
  if (physical.length > 0) {
    out.reason = `каналы в физических единицах (${physical.join(', ')}) требуют цену единицы — нужен штатный путь`;
    return out;
  }
  out.mediaChannels = media;
  for (const name of media) out.uniform[name] = 'monetary';
  out.eligible = true;
  out.reason = 'happy-path: денежный KPI, чистые данные, все каналы в рублях';
  return out;
}
