/**
 * Vitest unit tests для formatSpend / formatKpiValue (Фаза 1b).
 *
 * Проверяют семантические форматтеры из $lib/format-numbers.js.
 */
import { describe, it, expect } from 'vitest';
import { formatSpend, formatKpiValue, formatMoney } from '../lib/format-numbers.js';


describe('formatSpend', () => {
  it('всегда возвращает ₽', () => {
    expect(formatSpend(5.8e9)).toContain('₽');
  });

  it('compact: 5.8e9 → 5.8 млрд ₽', () => {
    expect(formatSpend(5.8e9)).toBe('5.8 млрд ₽');
  });

  it('compact: 1.5e6 → 1.5 млн ₽', () => {
    expect(formatSpend(1.5e6)).toBe('1.5 млн ₽');
  });

  it('null → -', () => {
    expect(formatSpend(null)).toBe('-');
  });

  it('ведёт себя идентично formatMoney для денежных величин', () => {
    expect(formatSpend(5.8e9)).toBe(formatMoney(5.8e9));
  });
});


describe('formatKpiValue', () => {
  it('sales_packs (count): содержит упак.', () => {
    expect(formatKpiValue(5.8e6, { kpiType: 'sales_packs' })).toContain('упак.');
  });

  it('sales_packs (count): НЕ содержит ₽', () => {
    const result = formatKpiValue(5.8e6, { kpiType: 'sales_packs' });
    expect(result).not.toContain('₽');
  });

  it('sales_packs (count): 5.8e6 → 5.8 млн упак.', () => {
    expect(formatKpiValue(5.8e6, { kpiType: 'sales_packs' })).toBe('5.8 млн упак.');
  });

  it('sales (monetary): содержит ₽', () => {
    expect(formatKpiValue(5.8e9, { kpiType: 'sales' })).toContain('₽');
  });

  it('sales (monetary): 5.8e9 → 5.8 млрд ₽', () => {
    expect(formatKpiValue(5.8e9, { kpiType: 'sales' })).toBe('5.8 млрд ₽');
  });

  it('leads (count): содержит лид.', () => {
    expect(formatKpiValue(1.2e6, { kpiType: 'leads' })).toContain('лид.');
  });

  it('revenue (monetary): содержит ₽', () => {
    expect(formatKpiValue(2.5e9, { kpiType: 'revenue' })).toContain('₽');
  });

  it('без kpiType → fallback к formatMoney', () => {
    expect(formatKpiValue(5.8e9, {})).toBe('5.8 млрд ₽');
    expect(formatKpiValue(5.8e9, {})).toContain('₽');
  });

  it('null → -', () => {
    expect(formatKpiValue(null, { kpiType: 'leads' })).toBe('-');
  });

  it('неизвестный kpiType → fallback к formatMoney', () => {
    const result = formatKpiValue(5e9, { kpiType: 'unknown_xyz' });
    expect(result).toContain('₽');
  });
});
