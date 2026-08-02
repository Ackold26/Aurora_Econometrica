/**
 * Единый источник порогов MQS для интерфейса — зеркало
 * `sidecar/econometrica/utils/diagnostics.py::_MQS_TIERS`.
 *
 * ЗАЧЕМ. Инцидент L16 (2026-04-29): MQS=70 показывался «Хорошее» в одном месте и
 * «приемлемо» в другом, потому что пороги жили копиями. Тогда владельцем шкалы
 * объявили `mqs_tier_info()` в Python, и отчёты (HTML/PPTX) на него перевели —
 * а интерфейс остался со СВОЕЙ лестницей 80/60. Внешний аудит 2026-07-26 нашёл
 * рецидив: при MQS=70 слайд говорит «Хорошее», панель выводов — «приемлемое
 * качество»; при MQS=82 канон даёт «Хорошее», а подсказка виджета — «≥ 80 -
 * отлично» рядом с ярлыком «Хорошее» в том же самом окне.
 *
 * ПРАВИЛО. Ни один файл интерфейса не держит числовых порогов MQS. Ветвление —
 * по имени уровня (`tier`), а не по числу. Текст шкалы для подсказок собирается
 * функцией `mqsScaleText()`, а не пишется руками. Оба правила стережёт
 * `__tests__/mqs-tiers.guard.test.js`, он же сверяет эту таблицу с питоновской.
 *
 * ГРАНИЦА. Ярлык посчитанной метрики по-прежнему приходит с бэкенда
 * (`mqsView().tierLabel`) — он и есть канон. Таблица ниже нужна там, где надо
 * решить «какой текст/цвет показать» до получения ярлыка либо когда ярлыка нет.
 * Отсутствие метрики обрабатывает вызывающий код: «нет числа — нет подписи».
 */

/**
 * @typedef {Object} MqsTier
 * @property {number} min    нижняя граница уровня, включительно
 * @property {'excellent'|'good'|'acceptable'|'weak'|'poor'} tier
 * @property {string} label  клиентский ярлык (русский)
 * @property {string} color  цвет уровня
 */

/**
 * Порядок — от старшего уровня к младшему, как в питоновском каноне.
 * @type {ReadonlyArray<MqsTier>}
 */
export const MQS_TIERS = Object.freeze([
  Object.freeze({ min: 85, tier: /** @type {const} */ ('excellent'), label: 'Отличное', color: '#22c55e' }),
  Object.freeze({ min: 70, tier: /** @type {const} */ ('good'), label: 'Хорошее', color: '#3b82f6' }),
  Object.freeze({ min: 55, tier: /** @type {const} */ ('acceptable'), label: 'Приемлемое', color: '#f59e0b' }),
  Object.freeze({ min: 40, tier: /** @type {const} */ ('weak'), label: 'Слабое', color: '#f97316' }),
  Object.freeze({ min: 0, tier: /** @type {const} */ ('poor'), label: 'Ненадёжное', color: '#ef4444' }),
]);

/**
 * Уровень качества по посчитанному баллу.
 *
 * Возвращает `null`, когда балла нет — вызывающий обязан показать честное
 * отсутствие, а не подставлять ноль или средний уровень. Настоящий ноль
 * (`0`) — валидное измерение и даёт уровень «Ненадёжное».
 *
 * @param {number|null|undefined} score
 * @returns {MqsTier|null}
 */
export function mqsTierInfo(score) {
  if (score == null) return null;
  const n = Number(score);
  if (!Number.isFinite(n)) return null;
  for (const t of MQS_TIERS) {
    if (n >= t.min) return t;
  }
  return MQS_TIERS[MQS_TIERS.length - 1];
}

/**
 * Тон для оформления (три ступени, как принято в интерфейсе).
 *
 * `excellent`/`good` → 'good'; `acceptable` → 'warn'; `weak`/`poor` → 'bad'.
 * При отсутствии балла — `null`: нечего красить, показывается отсутствие.
 *
 * @param {number|null|undefined} score
 * @returns {'good'|'warn'|'bad'|null}
 */
export function mqsTone(score) {
  const info = mqsTierInfo(score);
  if (info == null) return null;
  if (info.tier === 'excellent' || info.tier === 'good') return 'good';
  if (info.tier === 'acceptable') return 'warn';
  return 'bad';
}

/**
 * Проходит ли модель порог, начиная с которого на её выводы можно опираться
 * в планировании. Канон — уровень «Хорошее» и выше.
 *
 * Заведено, чтобы прикладной код не сравнивал числа руками ради одной и той же
 * мысли «модель достаточно хороша».
 *
 * @param {number|null|undefined} score
 * @returns {boolean} false и при отсутствии балла — недоказанное не считается доказанным
 */
export function mqsIsDependable(score) {
  const info = mqsTierInfo(score);
  return info != null && (info.tier === 'excellent' || info.tier === 'good');
}

/**
 * Текст шкалы для подсказок — собирается из порогов, чтобы описание не разошлось
 * с поведением. Пример: «85–100 – Отличное, 70–84 – Хорошее, … 0–39 – Ненадёжное».
 *
 * Тире короткое (клиентский текст линейки). Целочисленные диапазоны без знаков
 * ≤/≥/< (единая форма с Rust-зеркалом `mqs_tiers.rs::mqs_scale_text`, находка
 * внешнего аудита 2026-07-27 — прежняя запись «70–< 85» читалась как опечатка,
 * а Rust рядом печатал «70 ≤ MQS < 85» - понятно программисту, не клиенту-
 * маркетологу). Верхняя граница каждого диапазона — целое число ПЕРЕД нижней
 * границей следующего уровня (85 → верхняя граница «Хорошего» = 84), поэтому
 * диапазоны не пересекаются текстуально ни на одном числе, оставаясь в
 * согласии с поведением «нижняя граница включительно» (`mqsTierInfo`).
 *
 * @returns {string}
 */
export function mqsScaleText() {
  const parts = MQS_TIERS.map((t, i) => {
    const upper = i === 0 ? 100 : MQS_TIERS[i - 1].min - 1;
    return `${t.min}–${upper} – ${t.label}`;
  });
  return parts.join(', ');
}
