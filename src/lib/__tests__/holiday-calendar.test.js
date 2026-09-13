// @ts-nocheck — node-side тест (fs/path/url); svelte-check checkJs не имеет
// @types/node в scope. Логика проверяется через vitest, не через типы.
/**
 * #6 Tier-3/OVB (2026-06-07): фронт-календарь праздников — структурный гард.
 *
 * Имена + порядок ДОЛЖНЫ совпадать с backend HOLIDAY_DEFINITIONS
 * (sidecar/econometrica/utils/holiday_calendar_ru.py). Этот тест фиксирует
 * ИНВАРИАНТЫ фронт-списка, чтобы случайная правка (дубль/опечатка имени/
 * потеря праздника) краснила CI.
 *
 * 🔴 13.09.2026: раньше здесь был ЗАМОРОЖЕННЫЙ снимок backend-имён
 * (`BACKEND_NAMES`), вписанный прямо в этот файл. Он сверял фронт САМ С
 * СОБОЙ (обе стороны — фронтовые артефакты) и не мог поймать расхождение с
 * настоящим движком: когда в moveler.py добавили 13-е событие (Пасху), тест
 * остался зелёным, а фронт молча отстал на одно событие. Теперь имена читаются
 * ЖИВЫМ разбором backend-файла (единственный источник истины), не копией.
 * Путь взят СТРОГО вне dist/ и _internal/ (там лежат копии собранного пакета,
 * они устаревают и дали бы ложный зелёный — тот же класс ошибки, что уже
 * стоил нам расхождения на 13-м празднике).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { HOLIDAY_CALENDAR_RU, HOLIDAY_BY_NAME, holidayLabel } from '../holiday-calendar.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// СТРОГО исходник движка, не dist/_internal копия сборки.
const BACKEND_PATH = resolve(
  __dirname,
  '../../../sidecar/econometrica/utils/holiday_calendar_ru.py',
);

/**
 * Читает имена событий из HOLIDAY_DEFINITIONS backend-файла разбором regexp.
 * Ловит только строковые литералы `'name': '...'` (записи определений) —
 * НЕ ссылки вида `'name': h_def['name']` (используются в describe_holiday_windows
 * / get_holiday_metadata для сборки ответа, там значение не строковый литерал,
 * и regex их не матчит).
 * @returns {string[]}
 */
function readBackendHolidayNames() {
  const source = readFileSync(BACKEND_PATH, 'utf-8');
  const names = [];
  const re = /'name':\s*'([^']+)'/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    names.push(m[1]);
  }
  return names;
}

describe('#6 holiday-calendar фронт-зеркало (живая сверка с backend)', () => {
  it('имена и порядок совпадают с HOLIDAY_DEFINITIONS в holiday_calendar_ru.py', () => {
    const backendNames = readBackendHolidayNames();
    const frontNames = HOLIDAY_CALENDAR_RU.map((h) => h.name);

    const missingOnFront = backendNames.filter((n) => !frontNames.includes(n));
    const extraOnFront = frontNames.filter((n) => !backendNames.includes(n));

    expect(
      frontNames,
      `Расхождение фронта (${BACKEND_PATH}) с backend HOLIDAY_DEFINITIONS.\n` +
        `Backend (${backendNames.length}): ${backendNames.join(', ')}\n` +
        `Фронт (${frontNames.length}): ${frontNames.join(', ')}\n` +
        (missingOnFront.length ? `На фронте НЕТ, но есть в backend: ${missingOnFront.join(', ')}\n` : '') +
        (extraOnFront.length ? `На фронте ЕСТЬ лишние (нет в backend): ${extraOnFront.join(', ')}\n` : '') +
        'Обнови HOLIDAY_CALENDAR_RU в src/lib/holiday-calendar.js.',
    ).toEqual(backendNames);
  });

  it('все имена с префиксом holiday_ и уникальны', () => {
    const names = HOLIDAY_CALENDAR_RU.map((h) => h.name);
    expect(names.every((n) => /^holiday_/.test(n))).toBe(true);
    expect(new Set(names).size).toBe(names.length);
  });

  it('у каждого непустой RU-лейбл и hint', () => {
    for (const h of HOLIDAY_CALENDAR_RU) {
      expect(h.label && h.label.trim().length).toBeTruthy();
      expect(h.hint && h.hint.trim().length).toBeTruthy();
    }
  });

  it('HOLIDAY_BY_NAME покрывает все праздники', () => {
    for (const h of HOLIDAY_CALENDAR_RU) {
      expect(HOLIDAY_BY_NAME[h.name]).toBe(h);
    }
  });

  it('holidayLabel: известное имя → лейбл, неизвестное → само имя', () => {
    expect(holidayLabel('holiday_march8')).toBe('8 марта');
    expect(holidayLabel('holiday_unknown_xyz')).toBe('holiday_unknown_xyz');
  });
});
