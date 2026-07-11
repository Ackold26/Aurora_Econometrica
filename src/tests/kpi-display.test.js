import { describe, it, expect } from 'vitest';
import { plural, getDisplay, currencySymbol } from '$lib/kpi/kpi-display.js';

const leadForms = ['лид', 'лида', 'лидов'];

describe('plural', () => {
  it.each([
    [1, 0], [2, 1], [5, 2], [11, 2], [21, 0], [22, 1], [12, 2], [114, 2],
  ])('plural(%i) → forms[%i]', (n, idx) => {
    expect(plural(n, leadForms)).toBe(leadForms[idx]);
  });
});

describe('getDisplay', () => {
  it('leads → count, forms[0]=лид, cpu_per_label=₽/лид', () => {
    const d = getDisplay('leads');
    expect(d.kpi_kind).toBe('count');
    expect(d.result_forms[0]).toBe('лид');
    expect(d.cpu_per_label).toBe('₽/лид');
  });

  it('sales → monetary, cpu_per_label null', () => {
    const d = getDisplay('sales');
    expect(d.kpi_kind).toBe('monetary');
    expect(d.cpu_per_label).toBeNull();
  });

  it('count_custom с customForms подменяет forms', () => {
    const d = getDisplay('count_custom', ['визит', 'визита', 'визитов']);
    expect(d.result_forms).toEqual(['визит', 'визита', 'визитов']);
  });
});

describe('currencySymbol', () => {
  it('возвращает ₽', () => {
    expect(currencySymbol()).toBe('₽');
  });
});
