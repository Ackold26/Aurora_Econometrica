/**
 * Фаза 4 — Гейт 4 (ОПЦИОНАЛЬНЫЙ): Contract-паритет Python↔JS подписей.
 *
 * Проверяет что для каждого kpi_type из реестра JS kpiView возвращает
 * cpu_per_label и result_unit_short (targetUnit), совпадающие с паспортом getDisplay().
 *
 * Логика дешёвая: оба (Python kpi_labels и JS kpi-aware-formatting) читают
 * один источник истины (kpi_display_registry.json → сгенерированный JS).
 * Этот тест ловит случай, когда сгенерированный файл был изменён вручную
 * или kpiView содержит явный override, расходящийся с реестром.
 *
 * Стиль: mirrors src/tests/kpi-aware-formatting.test.js.
 */
import { describe, it, expect } from 'vitest';
import { kpiView } from '../lib/kpi-aware-formatting.js';
import { getDisplay, allDisplayTypes } from '../lib/kpi/kpi-display.js';


describe('kpi-contract-parity: JS kpiView совпадает с паспортом getDisplay', () => {
  // Получаем все зарегистрированные типы KPI
  const allTypes = allDisplayTypes();

  for (const kpiType of allTypes) {
    const passport = getDisplay(kpiType);
    const isCount = passport.kpi_kind === 'count';

    if (!isCount) {
      // monetary/proportional — kpiType игнорируется в kpiView (нет count-ветки)
      // достаточно проверить что вызов не падает
      it(`getDisplay('${kpiType}') — monetary/proportional, kpiView не падает`, () => {
        expect(() => kpiView({ kpiKind: 'monetary', derivedMode: 'roi', kpiType })).not.toThrow();
      });
      continue;
    }

    it(`count/${kpiType}: kpiView.cpuPerLabel совпадает с паспортом`, () => {
      const view = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType });
      expect(view.cpuPerLabel).toBe(passport.cpu_per_label);
    });

    it(`count/${kpiType}: kpiView.targetUnit совпадает с паспортом result_unit_short`, () => {
      const view = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType });
      expect(view.targetUnit).toBe(passport.result_unit_short);
    });

    it(`count/${kpiType}: kpiView.targetAxis совпадает с паспортом result_axis_label`, () => {
      const view = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType });
      expect(view.targetAxis).toBe(passport.result_axis_label);
    });
  }
});


describe('kpi-contract-parity: Python-совместимость key-значений', () => {
  // Точечная проверка значений, которые Python kpi_labels.py возвращает явно.
  // Если эти тесты падают — JS и Python расходятся в паспорте.

  it('leads: cpuPerLabel = ₽/лид (matches Python get_display(leads).cpu_per_label)', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'leads' });
    expect(v.cpuPerLabel).toBe('₽/лид');
  });

  it('leads: targetAxis = Лиды (matches Python target_axis_label(count, kpi_type=leads))', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'leads' });
    expect(v.targetAxis).toBe('Лиды');
  });

  it('sales_packs: cpuPerLabel = ₽/упак. (matches Python)', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'sales_packs' });
    expect(v.cpuPerLabel).toBe('₽/упак.');
  });

  it('sales_packs: targetAxis содержит упак (matches Python)', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'sales_packs' });
    expect(v.targetAxis).toContain('упак');
  });

  it('registrations: cpuPerLabel = ₽/рег.', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'registrations' });
    expect(v.cpuPerLabel).toBe('₽/рег.');
  });

  it('subscriptions: cpuPerLabel = ₽/подписку', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'subscriptions' });
    expect(v.cpuPerLabel).toBe('₽/подписку');
  });

  it('count_custom: cpuPerLabel = ₽/ед. (generic backward-compat)', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'count_custom' });
    expect(v.cpuPerLabel).toBe('₽/ед.');
  });

  it('monetary (no kpiType): cpuPerLabel = ₽/ед. (legacy default)', () => {
    const v = kpiView({ kpiKind: 'monetary', derivedMode: 'roi' });
    expect(v.cpuPerLabel).toBe('₽/ед.');
  });
});
