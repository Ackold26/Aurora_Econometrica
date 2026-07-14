/**
 * Блок 2 (2026-07-06): SSOT period-format.js — единица, порог, склонение.
 *
 * Проверяет правильность единиц и порогов для всех гранулярностей,
 * а также склонение ruPeriodForm для крайних и стандартных значений.
 */
import { describe, it, expect } from 'vitest';
import { periodUnit, periodThreshold, formatPeriodLabel, ruPeriodForm } from '../period-format.js';

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
