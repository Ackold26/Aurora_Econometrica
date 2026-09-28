/**
 * Блок 2 (2026-07-06): SSOT period-format.js — единица, порог, склонение.
 *
 * Проверяет правильность единиц и порогов для всех гранулярностей,
 * а также склонение ruPeriodForm для крайних и стандартных значений.
 */
import { describe, it, expect } from 'vitest';
import {
  periodUnit, periodThreshold, formatPeriodLabel, ruPeriodForm,
  formatPeriodSpan, formatMediaPlanSpan, ruPlanPeriodsForm,
} from '../period-format.js';

describe('periodUnit — текстовая единица по гранулярности', () => {
  it('W → нед', () => expect(periodUnit('W')).toBe('нед'));
  it('w (нижний регистр) → нед', () => expect(periodUnit('w')).toBe('нед'));
  it('M → мес', () => expect(periodUnit('M')).toBe('мес'));
  it('Q → кв', () => expect(periodUnit('Q')).toBe('кв'));
  it('неизвестная гранулярность → пер', () => expect(periodUnit('D')).toBe('пер'));
  it('null дефолт → нед', () => expect(periodUnit(null)).toBe('нед'));
  it('undefined дефолт → нед', () => expect(periodUnit(undefined)).toBe('нед'));
});

describe('periodThreshold — минимальный порог наблюдений', () => {
  it('W → 52', () => expect(periodThreshold('W')).toBe(52));
  it('M → 24', () => expect(periodThreshold('M')).toBe(24));
  it('Q → 8', () => expect(periodThreshold('Q')).toBe(8));
  it('неизвестная гранулярность → консервативный дефолт 52', () => expect(periodThreshold('D')).toBe(52));
  it('null дефолт → 52', () => expect(periodThreshold(null)).toBe(52));
});

describe('formatPeriodLabel — метка наблюдений', () => {
  it('недельный: 36 нед', () => expect(formatPeriodLabel(36, 'W')).toBe('36 нед'));
  it('месячный: 12 мес', () => expect(formatPeriodLabel(12, 'M')).toBe('12 мес'));
  it('квартальный: 8 кв', () => expect(formatPeriodLabel(8, 'Q')).toBe('8 кв'));
});

describe('ruPeriodForm — склонение «период»', () => {
  // недельный кейс: n = 1, 2, 5
  it('1 → «1 период»', () => expect(ruPeriodForm(1)).toBe('1 период'));
  it('2 → «2 периода»', () => expect(ruPeriodForm(2)).toBe('2 периода'));
  it('5 → «5 периодов»', () => expect(ruPeriodForm(5)).toBe('5 периодов'));

  // месячный кейс: краевые значения
  it('11 → «11 периодов» (исключение мод100=11)', () => expect(ruPeriodForm(11)).toBe('11 периодов'));
  it('12 → «12 периодов» (исключение мод100=12)', () => expect(ruPeriodForm(12)).toBe('12 периодов'));
  it('21 → «21 период» (мод10=1, мод100=21)', () => expect(ruPeriodForm(21)).toBe('21 период'));
  it('24 → «24 периода»', () => expect(ruPeriodForm(24)).toBe('24 периода'));
  it('52 → «52 периода»', () => expect(ruPeriodForm(52)).toBe('52 периода'));
  it('100 → «100 периодов»', () => expect(ruPeriodForm(100)).toBe('100 периодов'));
  it('101 → «101 период»', () => expect(ruPeriodForm(101)).toBe('101 период'));
});

// L2 (s55): экран шага планирования показывал «2025-W01 – 2025-W32», отчёт –
// «дек 2024 – авг 2025». Ожидания ниже сняты с format_period_span движка
// (engines/narrative_adapter.py) на тех же входах – экран и отчёт согласованы.
describe('formatPeriodSpan – края срока как в отчёте', () => {
  it('недельные ISO-даты → «мес год», год края по дате, а не по ISO-неделе', () =>
    expect(formatPeriodSpan('2024-12-30T00:00:00', '2025-08-04T00:00:00', 'W')).toBe('дек 2024 – авг 2025'));
  it('тире – U+2013', () =>
    expect(formatPeriodSpan('2024-12-30', '2025-08-04', 'W')).toContain(' – '));
  it('месячные без гранулярности', () =>
    expect(formatPeriodSpan('2025-01-01', '2025-08-01')).toBe('янв 2025 – авг 2025'));
  it('оба края в одном месяце → один «мес год»', () =>
    expect(formatPeriodSpan('2025-03-03', '2025-03-24', 'W')).toBe('мар 2025'));
  it('квартальные метки начала периода → кварталы, край не съезжает', () =>
    expect(formatPeriodSpan('2026-01-01', '2026-10-01', 'Q')).toBe('I кв. 2026 – IV кв. 2026'));
  it('метки «2026-Q1»/«2026» движка разбираются и без гранулярности', () => {
    expect(formatPeriodSpan('2026-Q1', '2026-Q4')).toBe('I кв. 2026 – IV кв. 2026');
    expect(formatPeriodSpan('2044', '2047')).toBe('2044 – 2047');
  });
  it('годовые даты → годы', () =>
    expect(formatPeriodSpan('2044-01-01', '2047-01-01', 'Y')).toBe('2044 – 2047'));
  it('неразборчивая метка → обе как есть, без смешения форматов', () =>
    expect(formatPeriodSpan('2025-W01', '2025-08-04T00:00:00', 'W')).toBe('2025-W01 – 2025-08-04T00:00:00'));
});

describe('formatMediaPlanSpan – ответ проверки данных', () => {
  const mp = {
    granularity: 'W',
    period_labels: ['2025-W01', '2025-W02', '2025-W32'],
    future_dates: ['2024-12-30T00:00:00', '2025-01-06T00:00:00', '2025-08-04T00:00:00'],
  };
  it('берёт даты future_dates, а не ISO-недели', () =>
    expect(formatMediaPlanSpan(mp)).toBe('дек 2024 – авг 2025'));
  it('старый проект без future_dates → метки как есть', () =>
    expect(formatMediaPlanSpan({ ...mp, future_dates: undefined })).toBe('2025-W01 – 2025-W32'));
  it('пустой план → пустая строка (скобки на экране не выводятся)', () => {
    expect(formatMediaPlanSpan({ period_labels: [], future_dates: [] })).toBe('');
    expect(formatMediaPlanSpan(null)).toBe('');
  });
});

describe('ruPlanPeriodsForm – число периодов плана словами', () => {
  it('движок отдаёт W → недели (раньше выводилось «32 периодов»)', () =>
    expect(ruPlanPeriodsForm(32, 'W')).toBe('32 недели'));
  it('склонение недель', () => {
    expect(ruPlanPeriodsForm(1, 'W')).toBe('1 неделя');
    expect(ruPlanPeriodsForm(5, 'W')).toBe('5 недель');
    expect(ruPlanPeriodsForm(12, 'W')).toBe('12 недель');
    expect(ruPlanPeriodsForm(21, 'W')).toBe('21 неделя');
  });
  it('месяцы, кварталы, годы', () => {
    expect(ruPlanPeriodsForm(8, 'M')).toBe('8 месяцев');
    expect(ruPlanPeriodsForm(3, 'Q')).toBe('3 квартала');
    expect(ruPlanPeriodsForm(5, 'Y')).toBe('5 лет');
  });
  it('неизвестная гранулярность → «периода/периодов»', () => {
    expect(ruPlanPeriodsForm(32, 'unknown')).toBe('32 периода');
    expect(ruPlanPeriodsForm(32, null)).toBe('32 периода');
  });
});
