/**
 * Vitest unit tests для $lib/kpi-aware-formatting.js (v1.3.2).
 *
 * Frontend mirror tests parallel backend tools/test_aurora_html_kpi_aware.py
 * + tools/test_aurora_pptx_kpi_aware.py - те же contract checks для JS helpers.
 *
 * Coverage:
 *   - kpiView: defaults, count, effectiveness, labels override
 *   - fmtMetric / fmtMetricBare: monetary roi / count / effectiveness
 *   - weightedPhrase: count inversion (units/₽ → CPU), legacy ROI×, effectiveness phrase
 *   - underBreakevenPhrase: 3 modes
 *   - channelMetricPhrase / topMetricBenchmark
 */
import { describe, it, expect } from 'vitest';
import {
  kpiView,
  fmtMetric,
  fmtMetricBare,
  weightedPhrase,
  underBreakevenPhrase,
  channelMetricPhrase,
  topMetricBenchmark,
} from '../lib/kpi-aware-formatting.js';


describe('kpiView', () => {
  it('returns legacy defaults when input is empty', () => {
    const v = kpiView({});
    expect(v.kpiKind).toBe('monetary');
    expect(v.mode).toBe('roi');
    expect(v.isLegacy).toBe(true);
    expect(v.metricLabel).toBe('ROI');
    expect(v.metricShort).toBe('ROI');
    expect(v.targetUnit).toBe('₽');
    expect(v.targetAxis).toBe('Продажи, ₽');
    expect(v.vpcu).toBeNull();
  });

  it('handles null input gracefully', () => {
    const v = kpiView(null);
    expect(v.isLegacy).toBe(true);
    expect(v.metricShort).toBe('ROI');
  });

  it('handles undefined input gracefully', () => {
    const v = kpiView(undefined);
    expect(v.isLegacy).toBe(true);
  });

  it('reads count KPI labels', () => {
    const v = kpiView({
      kpiKind: 'count',
      derivedMode: 'roi',
      valuePerCountUnit: 80,
      valuePerCountUnitLabel: '80 ₽/упак',
      labels: {
        metricLabel: 'CPU, ₽/ед.',
        metricShortLabel: 'CPU',
        targetUnitLabel: 'упак / ед.',
        targetAxisLabel: 'Продажи, упак',
      },
    });
    expect(v.kpiKind).toBe('count');
    expect(v.isLegacy).toBe(false);
    expect(v.metricShort).toBe('CPU');
    expect(v.vpcu).toBe(80);
    expect(v.vpcuLabel).toBe('80 ₽/упак');
    expect(v.targetUnit).toBe('упак / ед.');
  });

  it('reads effectiveness mode labels', () => {
    const v = kpiView({
      kpiKind: 'monetary',
      derivedMode: 'effectiveness',
      labels: {
        metricLabel: 'Доля %',
        metricShortLabel: 'Доля',
      },
    });
    expect(v.mode).toBe('effectiveness');
    expect(v.isLegacy).toBe(false);
    expect(v.metricShort).toBe('Доля');
  });

  it('coerces valuePerCountUnit string to number', () => {
    const v = kpiView({ kpiKind: 'count', derivedMode: 'roi', valuePerCountUnit: '120.5' });
    expect(v.vpcu).toBe(120.5);
  });

  it('partial labels merge with defaults', () => {
    const v = kpiView({
      kpiKind: 'monetary',
      derivedMode: 'roi',
      labels: { metricLabel: 'CustomROI' },
    });
    expect(v.metricLabel).toBe('CustomROI');
    // Other labels fall back to defaults
    expect(v.targetUnit).toBe('₽');
  });
});


describe('fmtMetric', () => {
  it('formats monetary ROI as multiplier', () => {
    const kpi = kpiView({});
    expect(fmtMetric(1.5, kpi)).toBe('1.50×');
    expect(fmtMetric(0.847, kpi)).toBe('0.85×');
    expect(fmtMetric(10, kpi)).toBe('10.00×');
  });

  it('formats count KPI by inverting units/₽ → CPU ₽/ед.', () => {
    // B4 audit fix: backend convention = mathematical units/₽; helper inverts.
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    // 0.0125 units/₽ → CPU 1/0.0125 = 80
    expect(fmtMetric(0.0125, kpi)).toBe('80 ₽/ед.');
    // 0.01 → 100
    expect(fmtMetric(0.01, kpi)).toBe('100 ₽/ед.');
    // Zero / negative → fallback (no signal)
    expect(fmtMetric(0, kpi)).toBe('-');
    expect(fmtMetric(-0.5, kpi)).toBe('-');
  });

  it('formats effectiveness fraction as percent', () => {
    const kpi = kpiView({ kpiKind: 'monetary', derivedMode: 'effectiveness' });
    expect(fmtMetric(0.25, kpi)).toBe('25.0%');
    expect(fmtMetric(0.1234, kpi)).toBe('12.3%');
  });

  it('formats effectiveness value > 1 as percent kept', () => {
    const kpi = kpiView({ kpiKind: 'monetary', derivedMode: 'effectiveness' });
    expect(fmtMetric(25, kpi)).toBe('25%');
    expect(fmtMetric(99.5, kpi)).toBe('100%');
  });

  it('returns fallback for null / undefined / NaN / strings', () => {
    const kpi = kpiView({});
    expect(fmtMetric(null, kpi)).toBe('-');
    expect(fmtMetric(undefined, kpi)).toBe('-');
    expect(fmtMetric('bad', kpi)).toBe('-');
    expect(fmtMetric(NaN, kpi)).toBe('-');
  });

  it('respects custom fallback', () => {
    const kpi = kpiView({});
    expect(fmtMetric(null, kpi, 'N/A')).toBe('N/A');
  });
});


describe('fmtMetricBare (no suffix)', () => {
  it('legacy: 2-decimal number', () => {
    expect(fmtMetricBare(1.5, kpiView({}))).toBe('1.50');
  });

  it('count: inverts to CPU integer (1/x)', () => {
    expect(fmtMetricBare(0.0125, kpiView({ kpiKind: 'count', derivedMode: 'roi' }))).toBe('80');
    expect(fmtMetricBare(0.01, kpiView({ kpiKind: 'count', derivedMode: 'roi' }))).toBe('100');
    expect(fmtMetricBare(0, kpiView({ kpiKind: 'count', derivedMode: 'roi' }))).toBe('-');
  });

  it('effectiveness fraction', () => {
    expect(fmtMetricBare(0.25, kpiView({ derivedMode: 'effectiveness' }))).toBe('25.0');
  });

  it('null safe', () => {
    expect(fmtMetricBare(null, kpiView({}))).toBe('-');
  });
});


describe('weightedPhrase (portfolio aggregate)', () => {
  it('monetary ROI: portfolio multiplier', () => {
    expect(weightedPhrase(1.5, kpiView({}))).toBe('ROI портфеля 1.50×');
    expect(weightedPhrase(0.685, kpiView({}))).toBe('ROI портфеля 0.69×');
  });

  it('count: inverts units/₽ to CPU ₽/ед.', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    // weighted_roi = 0.0125 → CPU = 1/0.0125 = 80
    expect(weightedPhrase(0.0125, kpi)).toBe('CPU портфеля 80 ₽/ед.');
    // 0.01 → 100
    expect(weightedPhrase(0.01, kpi)).toBe('CPU портфеля 100 ₽/ед.');
  });

  it('count zero or negative is safe', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    expect(weightedPhrase(0, kpi)).toBe('CPU портфеля недоступен');
    expect(weightedPhrase(-0.5, kpi)).toBe('CPU портфеля недоступен');
  });

  it('effectiveness ignores numeric value, returns phrase', () => {
    const kpi = kpiView({ derivedMode: 'effectiveness' });
    expect(weightedPhrase(1.0, kpi)).toBe('Средняя доля каналов в портфеле');
    expect(weightedPhrase(0.5, kpi)).toBe('Средняя доля каналов в портфеле');
  });

  it('null returns empty string', () => {
    expect(weightedPhrase(null, kpiView({}))).toBe('');
    expect(weightedPhrase(undefined, kpiView({}))).toBe('');
  });

  it('non-numeric returns empty string', () => {
    expect(weightedPhrase('abc', kpiView({}))).toBe('');
    expect(weightedPhrase(NaN, kpiView({}))).toBe('');
  });
});


describe('underBreakevenPhrase', () => {
  it('legacy returns mROAS condition', () => {
    expect(underBreakevenPhrase(kpiView({}))).toBe('mROAS < 1×');
  });

  it('count with vpcu returns CPU vs ценность', () => {
    const kpi = kpiView({
      kpiKind: 'count', derivedMode: 'roi', valuePerCountUnit: 80,
    });
    expect(underBreakevenPhrase(kpi)).toContain('CPU >');
    expect(underBreakevenPhrase(kpi)).toContain('80');
  });

  it('count without vpcu returns generic phrase', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    expect(underBreakevenPhrase(kpi)).toContain('ценности единицы');
  });

  it('effectiveness returns benchmark phrase', () => {
    const kpi = kpiView({ derivedMode: 'effectiveness' });
    expect(underBreakevenPhrase(kpi)).toBe('доля < бенчмарка');
  });
});


describe('channelMetricPhrase', () => {
  it('returns formatted phrase for monetary roi channel', () => {
    const kpi = kpiView({});
    const ch = { name: 'TV', mroas: 1.5 };
    const phrase = channelMetricPhrase(ch, kpi);
    expect(phrase).toEqual({ short: 'ROI', value: '1.50×' });
  });

  it('falls back to roi field when mroas is missing', () => {
    const kpi = kpiView({});
    const ch = { name: 'TV', roi: 2.3 };
    const phrase = channelMetricPhrase(ch, kpi);
    expect(phrase?.value).toBe('2.30×');
  });

  it('returns null когда нет ни mroas ни roi', () => {
    const kpi = kpiView({});
    expect(channelMetricPhrase({ name: 'TV' }, kpi)).toBeNull();
  });

  it('returns null when channel object is null', () => {
    expect(channelMetricPhrase(null, kpiView({}))).toBeNull();
  });

  it('uses count format with inversion когда KPI count', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    // mroas 0.01 units/₽ → CPU 100
    const phrase = channelMetricPhrase({ name: 'TV', mroas: 0.01 }, kpi);
    expect(phrase?.value).toBe('100 ₽/ед.');
    // metricShort default when labels not given. After B3 fix derived = 'CPU' для count.
    expect(phrase?.short).toBe('CPU');
  });
});


describe('topMetricBenchmark', () => {
  it('legacy: ROI ≥ 2×', () => {
    expect(topMetricBenchmark(kpiView({}))).toBe('ROI ≥ 2×');
  });

  it('count with vpcu: CPU ≤ half vpcu', () => {
    const kpi = kpiView({
      kpiKind: 'count', derivedMode: 'roi', valuePerCountUnit: 80,
    });
    const out = topMetricBenchmark(kpi);
    expect(out).toContain('CPU ≤ 40');
    expect(out).toContain('₽/ед.');
  });

  it('count without vpcu: generic phrase', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    expect(topMetricBenchmark(kpi)).toContain('CPU вдвое ниже ценности');
  });

  it('effectiveness: Доля ≥ 30%', () => {
    expect(topMetricBenchmark(kpiView({ derivedMode: 'effectiveness' }))).toBe('Доля ≥ 30%');
  });
});


describe('Parity with Python kpi_labels.py contract', () => {
  // Sanity checks что frontend контракт matches backend ожидания.
  it('count: weighted ROI 0.0125 inverts to CPU 80 (matches Python)', () => {
    const kpi = kpiView({ kpiKind: 'count', derivedMode: 'roi' });
    expect(weightedPhrase(0.0125, kpi)).toBe('CPU портфеля 80 ₽/ед.');
  });

  it('effectiveness fraction 0.25 → 25.0% (matches Python)', () => {
    const kpi = kpiView({ derivedMode: 'effectiveness' });
    expect(fmtMetric(0.25, kpi)).toBe('25.0%');
  });

  it('monetary 1.5 → 1.50× (matches Python aurora_html/sections.py)', () => {
    expect(fmtMetric(1.5, kpiView({}))).toBe('1.50×');
  });
});
