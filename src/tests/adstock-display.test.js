/**
 * П6-1: резолвинг отображаемого значения adstock в Эксперт-режиме.
 *
 * Критерий приёмки:
 * - auto + не обучено  → 'auto'   (плейсхолдер «Авто…»)
 * - auto + обучено(geometric) → 'geometric_auto'  (особый маркер)
 * - явный weibull → 'weibull'
 * - явный geometric → 'geometric'
 */
import { describe, it, expect } from 'vitest';
import { resolveAdstockDisplayValue, adstockDisplayLabel } from '$lib/adstock-display.js';

describe('resolveAdstockDisplayValue — резолвинг для per-channel <select>', () => {
  it('auto + не обучено (resolvedType=null) → "auto"', () => {
    expect(resolveAdstockDisplayValue('auto', null)).toBe('auto');
  });

  it('auto + не обучено (resolvedType=undefined) → "auto"', () => {
    expect(resolveAdstockDisplayValue('auto', undefined)).toBe('auto');
  });

  it('auto + не обучено (resolvedType="") → "auto"', () => {
    expect(resolveAdstockDisplayValue('auto', '')).toBe('auto');
  });

  it('auto + обучено с geometric → "geometric_auto"', () => {
    expect(resolveAdstockDisplayValue('auto', 'geometric')).toBe('geometric_auto');
  });

  it('auto + обучено с weibull → "weibull_auto"', () => {
    expect(resolveAdstockDisplayValue('auto', 'weibull')).toBe('weibull_auto');
  });

  it('явный geometric (не auto) → "geometric"', () => {
    expect(resolveAdstockDisplayValue('geometric', null)).toBe('geometric');
    expect(resolveAdstockDisplayValue('geometric', 'weibull')).toBe('geometric');
  });

  it('явный weibull (не auto) → "weibull"', () => {
    expect(resolveAdstockDisplayValue('weibull', null)).toBe('weibull');
    expect(resolveAdstockDisplayValue('weibull', 'geometric')).toBe('weibull');
  });
});

describe('adstockDisplayLabel — человекочитаемые метки', () => {
  it('"auto" → содержит "Авто"', () => {
    expect(adstockDisplayLabel('auto')).toMatch(/Авто/);
  });

  it('"geometric" → содержит "Геометрический"', () => {
    expect(adstockDisplayLabel('geometric')).toMatch(/Геометрический/);
  });

  it('"weibull" → содержит "Вейбулл"', () => {
    expect(adstockDisplayLabel('weibull')).toMatch(/Вейбулл/);
  });

  it('"geometric_auto" → содержит "Геометрический" и "авто"', () => {
    const label = adstockDisplayLabel('geometric_auto');
    expect(label).toMatch(/Геометрический/i);
    expect(label).toMatch(/авто/i);
  });

  it('"weibull_auto" → содержит "Вейбулл" и "авто"', () => {
    const label = adstockDisplayLabel('weibull_auto');
    expect(label).toMatch(/Вейбулл/i);
    expect(label).toMatch(/авто/i);
  });
});
