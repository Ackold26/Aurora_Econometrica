/**
 * Фаза 4 — Гейт 2: Унит-линт «нет денег на результате» (JS/vitest).
 *
 * Прогоняет kpiView + fmtMetric / weightedPhrase / underBreakevenPhrase
 * на count 'leads' / effectiveness / monetary и ассертит:
 *  - count/effectiveness: метрика-строки НЕ содержат 'mROAS' / 'ROAS' / жёсткого '₽/ед.'
 *    (должно быть '₽/лид' из паспорта для leads)
 *  - count без kpiType (backward-compat): cpuPerLabel='₽/ед.' — допустимо (нет паспорта)
 *  - monetary — контроль: содержит 'ROI' / '×'
 *
 * Стиль: mirrors src/tests/kpi-aware-formatting.test.js.
 */
import { describe, it, expect } from 'vitest';
import {
  kpiView,
  fmtMetric,
  weightedPhrase,
  underBreakevenPhrase,
} from '../lib/kpi-aware-formatting.js';


// ─── Вспомогательные константы ────────────────────────────────────────────

/** Токены, запрещённые в result-фразах для count/effectiveness. */
const FORBIDDEN_RESULT_TOKENS = ['mROAS', 'ROAS'];

/** Проверяет отсутствие запрещённых токенов в строке. */
function assertNoForbiddenTokens(str, label) {
  for (const token of FORBIDDEN_RESULT_TOKENS) {
    expect(str, `${label}: найден запрещённый токен '${token}' в: ${JSON.stringify(str)}`).not.toContain(token);
  }
}


// ─── Гейт 2a: count 'leads' — паспортная единица '₽/лид' ─────────────────

describe('kpi-units-lint: count leads', () => {
  const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'leads', valuePerCountUnit: 80 });

  it('kpiView: metricLabel содержит ₽/лид, не ₽/ед.', () => {
    expect(kpi.metricLabel).toContain('₽/лид');
    expect(kpi.metricLabel).not.toContain('₽/ед.');
    expect(kpi.cpuPerLabel).toBe('₽/лид');
  });

  it('fmtMetric: 0.0125 → 80 ₽/лид (не ₽/ед.)', () => {
    const result = fmtMetric(0.0125, kpi);
    expect(result).toBe('80 ₽/лид');
    assertNoForbiddenTokens(result, 'fmtMetric(count/leads)');
    // Жёсткий '₽/ед.' не должен присутствовать при наличии паспортной единицы
    expect(result).not.toBe('80 ₽/ед.');
  });

  it('fmtMetric: не содержит mROAS / ROAS', () => {
    const result = fmtMetric(0.02, kpi);
    assertNoForbiddenTokens(result, 'fmtMetric(count/leads, 0.02)');
  });

  it('weightedPhrase: CPU портфеля 80 ₽/лид', () => {
    const result = weightedPhrase(0.0125, kpi);
    expect(result).toBe('CPU портфеля 80 ₽/лид');
    assertNoForbiddenTokens(result, 'weightedPhrase(count/leads)');
    // Не должен содержать ₽/ед. — паспортная единица есть
    expect(result).not.toContain('₽/ед.');
  });

  it('underBreakevenPhrase: содержит ₽/лид, не ₽/ед.', () => {
    const result = underBreakevenPhrase(kpi);
    expect(result).toContain('₽/лид');
    expect(result).not.toContain('₽/ед.');
    assertNoForbiddenTokens(result, 'underBreakevenPhrase(count/leads)');
  });

  it('underBreakevenPhrase: не содержит mROAS / ROAS', () => {
    const result = underBreakevenPhrase(kpi);
    assertNoForbiddenTokens(result, 'underBreakevenPhrase(count/leads)');
  });
});


// ─── Гейт 2b: count без kpiType (backward-compat) ─────────────────────────

describe('kpi-units-lint: count без kpiType (backward-compat)', () => {
  const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', valuePerCountUnit: 80 });

  it('fmtMetric: 0.0125 → 80 ₽/ед. (no passport — backward-compat допустимо)', () => {
    // Без kpiType — cpuPerLabel='₽/ед.' это корректное backward-compat поведение.
    // Гейт НЕ запрещает ₽/ед. при отсутствии паспорта — только mROAS/ROAS запрещены.
    const result = fmtMetric(0.0125, kpi);
    expect(result).toBe('80 ₽/ед.');
    assertNoForbiddenTokens(result, 'fmtMetric(count/no-kpiType)');
  });

  it('fmtMetric: не содержит mROAS / ROAS', () => {
    const result = fmtMetric(0.02, kpi);
    assertNoForbiddenTokens(result, 'fmtMetric(count/no-kpiType, 0.02)');
  });

  it('weightedPhrase: не содержит mROAS / ROAS', () => {
    const result = weightedPhrase(0.0125, kpi);
    assertNoForbiddenTokens(result, 'weightedPhrase(count/no-kpiType)');
    // CPU всегда
    expect(result).toContain('CPU');
  });

  it('underBreakevenPhrase: не содержит mROAS / ROAS', () => {
    const result = underBreakevenPhrase(kpi);
    assertNoForbiddenTokens(result, 'underBreakevenPhrase(count/no-kpiType)');
  });
});


// ─── Гейт 2c: count 'sales_packs' ─────────────────────────────────────────

describe('kpi-units-lint: count sales_packs', () => {
  const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'sales_packs', valuePerCountUnit: 200 });

  it('cpuPerLabel — ₽/упак.', () => {
    expect(kpi.cpuPerLabel).toBe('₽/упак.');
  });

  it('fmtMetric: 0.01 → 100 ₽/упак.', () => {
    const result = fmtMetric(0.01, kpi);
    expect(result).toBe('100 ₽/упак.');
    assertNoForbiddenTokens(result, 'fmtMetric(count/sales_packs)');
  });

  it('weightedPhrase: не содержит mROAS / ROAS', () => {
    const result = weightedPhrase(0.01, kpi);
    assertNoForbiddenTokens(result, 'weightedPhrase(count/sales_packs)');
    expect(result).toContain('CPU');
  });

  it('underBreakevenPhrase: содержит ₽/упак., не mROAS', () => {
    const result = underBreakevenPhrase(kpi);
    expect(result).toContain('₽/упак.');
    assertNoForbiddenTokens(result, 'underBreakevenPhrase(count/sales_packs)');
  });
});


// ─── Гейт 2d: effectiveness ────────────────────────────────────────────────

describe('kpi-units-lint: effectiveness', () => {
  const kpi = kpiView({ kpiKind: 'monetary', derivedMode: 'effectiveness' });

  it('kpiView: metricLabel = Доля %', () => {
    expect(kpi.metricLabel).toBe('Доля %');
    expect(kpi.metricShort).toBe('Доля');
    assertNoForbiddenTokens(kpi.metricLabel, 'kpiView(effectiveness).metricLabel');
  });

  it('fmtMetric: 0.25 → 25.0% (не ROAS)', () => {
    const result = fmtMetric(0.25, kpi);
    expect(result).toBe('25.0%');
    assertNoForbiddenTokens(result, 'fmtMetric(effectiveness)');
  });

  it('weightedPhrase: Средняя доля каналов в портфеле (нет mROAS)', () => {
    const result = weightedPhrase(0.5, kpi);
    assertNoForbiddenTokens(result, 'weightedPhrase(effectiveness)');
    expect(result).toContain('доля');
  });

  it('underBreakevenPhrase: доля < бенчмарка', () => {
    const result = underBreakevenPhrase(kpi);
    expect(result).toBe('доля < бенчмарка');
    assertNoForbiddenTokens(result, 'underBreakevenPhrase(effectiveness)');
  });

  it('targetAxis не содержит Продажи, ₽ (баг Фазы 1b закрыт)', () => {
    // Фикс Фазы 1b: effectiveness c count-KPI раньше давал 'Продажи, ₽'
    const kpiCountEff = kpiView({ kpiKind: 'count', derivedMode: 'effectiveness', kpiType: 'sales_packs' });
    expect(kpiCountEff.targetAxis).not.toBe('Продажи, ₽');
    expect(kpiCountEff.targetAxis).toContain('упак');
  });
});


// ─── Гейт 2e: monetary — контроль (ROI/× ДОЛЖНЫ присутствовать) ───────────

describe('kpi-units-lint: monetary контроль (гейт не переусердствует)', () => {
  const kpi = kpiView({});  // defaults = monetary roi legacy

  it('fmtMetric: 1.5 → 1.50× (содержит ×)', () => {
    const result = fmtMetric(1.5, kpi);
    expect(result).toBe('1.50×');
    expect(result).toContain('×');
  });

  it('weightedPhrase: ROI портфеля 1.50×', () => {
    const result = weightedPhrase(1.5, kpi);
    expect(result).toContain('ROI');
    expect(result).toContain('×');
  });

  it('underBreakevenPhrase: mROAS < 1×', () => {
    const result = underBreakevenPhrase(kpi);
    expect(result).toBe('mROAS < 1×');
  });

  it('kpiView: metricLabel = ROI, targetAxis содержит ₽', () => {
    expect(kpi.metricLabel).toBe('ROI');
    expect(kpi.targetAxis).toContain('₽');
  });
});


// ─── Гейт 2f: матрица kpiType × fmtMetric ─────────────────────────────────

describe('kpi-units-lint: матрица kpiType × fmtMetric', () => {
  const CASES = [
    { kpiType: 'leads',       cpuPerLabel: '₽/лид',     mroas: 0.0125, expected: '80 ₽/лид' },
    { kpiType: 'sales_packs', cpuPerLabel: '₽/упак.',   mroas: 0.01,   expected: '100 ₽/упак.' },
    { kpiType: 'registrations', cpuPerLabel: '₽/рег.', mroas: 0.005,  expected: '200 ₽/рег.' },
  ];

  for (const { kpiType, cpuPerLabel, mroas, expected } of CASES) {
    it(`fmtMetric count/${kpiType}: ${mroas} → ${expected}`, () => {
      const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType });
      const result = fmtMetric(mroas, kpi);
      expect(result).toBe(expected);
      assertNoForbiddenTokens(result, `fmtMetric(count/${kpiType})`);
    });

    it(`kpiView count/${kpiType}: cpuPerLabel = ${cpuPerLabel}`, () => {
      const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType });
      expect(kpi.cpuPerLabel).toBe(cpuPerLabel);
    });
  }
});
