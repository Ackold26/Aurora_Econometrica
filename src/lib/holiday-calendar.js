/**
 * #6 Tier-3/OVB (2026-06-07): фронт-зеркало 12 авто-праздников РФ для UI-панели
 * отключения (HolidayControlsPanel). Имена + порядок ДОЛЖНЫ совпадать с backend
 * `sidecar/econometrica/utils/holiday_calendar_ru.py::HOLIDAY_DEFINITIONS`
 * (SSOT для генерации dummy при обучении). Здесь только display-лейблы (RU) +
 * краткое пояснение для tooltip — backend оперирует machine-именами.
 *
 * ⚠️ СИНХРОНИЗАЦИЯ: при изменении списка праздников в holiday_calendar_ru.py —
 * обновить здесь. Паритет имён покрыт тестом `holiday-calendar.test.js` (сверяет
 * фронт-имена с порядком/составом из этого же файла; backend-паритет — ручной,
 * 12 праздников hardcoded и стабильны с ADR-019, opt-out был отложен до v2.2.0).
 *
 * @typedef {{ name: string, label: string, hint: string }} HolidayDef
 */

/** @type {HolidayDef[]} — порядок = backend HOLIDAY_DEFINITIONS */
export const HOLIDAY_CALENDAR_RU = [
  { name: 'holiday_newyear_preshop',  label: 'Новогодние закупки',      hint: 'Закупки подарков перед Новым годом (15–31 декабря)' },
  { name: 'holiday_newyear_postsale', label: 'Новогодние распродажи',   hint: 'Распродажи + январские каникулы (25 дек — 8 янв)' },
  { name: 'holiday_valentine',        label: 'День св. Валентина',      hint: '1–14 февраля' },
  { name: 'holiday_defender_day',     label: '23 февраля',              hint: 'Покупки к Дню защитника Отечества (15–23 февраля)' },
  { name: 'holiday_march8',           label: '8 марта',                 hint: 'Покупки к Международному женскому дню (1–8 марта)' },
  { name: 'holiday_may_holidays',     label: 'Майские праздники',       hint: '28 апреля — 9 мая' },
  { name: 'holiday_russia_day',       label: 'День России',             hint: '11–12 июня' },
  { name: 'holiday_back_to_school',   label: 'Снова в школу',           hint: '15 августа — 1 сентября' },
  { name: 'holiday_unity_day',        label: 'День народного единства', hint: '3–4 ноября' },
  { name: 'holiday_black_friday',     label: 'Чёрная пятница',          hint: 'Последняя пятница ноября + выходные' },
  { name: 'holiday_cyber_monday',     label: 'Киберпонедельник',        hint: 'Понедельник после Чёрной пятницы' },
  { name: 'holiday_school_breaks',    label: 'Школьные каникулы',       hint: 'Осенние / зимние / весенние / летние окна' },
];

/** @type {Record<string, HolidayDef>} быстрый доступ по machine-имени */
export const HOLIDAY_BY_NAME = Object.fromEntries(
  HOLIDAY_CALENDAR_RU.map((h) => [h.name, h])
);

/**
 * RU-лейбл по machine-имени (fallback — само имя, если праздник не в календаре).
 * @param {string} name
 * @returns {string}
 */
export function holidayLabel(name) {
  return HOLIDAY_BY_NAME[name]?.label ?? name;
}
