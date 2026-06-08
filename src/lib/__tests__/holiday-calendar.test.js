/**
 * #6 Tier-3/OVB (2026-06-07): фронт-календарь праздников — структурный гард.
 *
 * Имена + порядок ДОЛЖНЫ совпадать с backend HOLIDAY_DEFINITIONS
 * (sidecar/econometrica/utils/holiday_calendar_ru.py). Backend-паритет ручной
 * (нельзя импортить Python из vitest), но этот тест фиксирует ИНВАРИАНТЫ фронт-списка,
 * чтобы случайная правка (дубль/опечатка имени/потеря праздника) краснила CI.
 * Список из 12 ожидаемых имён здесь = снимок backend на 2026-06-07.
 */
import { describe, it, expect } from 'vitest';
import { HOLIDAY_CALENDAR_RU, HOLIDAY_BY_NAME, holidayLabel } from '../holiday-calendar.js';

// Снимок backend HOLIDAY_DEFINITIONS (порядок значим — зеркалит инъекцию dummy).
const BACKEND_NAMES = [
  'holiday_newyear_preshop',
  'holiday_newyear_postsale',
  'holiday_valentine',
  'holiday_defender_day',
  'holiday_march8',
  'holiday_may_holidays',
  'holiday_russia_day',
  'holiday_back_to_school',
  'holiday_unity_day',
  'holiday_black_friday',
  'holiday_cyber_monday',
  'holiday_school_breaks',
];

describe('#6 holiday-calendar фронт-зеркало', () => {
  it('12 праздников, имена и порядок совпадают со снимком backend', () => {
    expect(HOLIDAY_CALENDAR_RU.map((h) => h.name)).toEqual(BACKEND_NAMES);
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
