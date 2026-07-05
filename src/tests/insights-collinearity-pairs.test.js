/**
 * insights-collinearity-pairs.test.js — аудит 2026-07-05 (доезд №2 до
 * инсайт-слоя): validateInsights обязан говорить о парах «бюджет + натуральная
 * метрика» то же, что CorrelationHeatmap — «ожидаемо», а не пугать
 * «Мультиколлинеарностью» на встроенном примере. Реальные кросс-канальные
 * корреляции остаются warning'ом.
 */
import { describe, it, expect } from 'vitest';
import { validateInsights } from '../lib/insights-rules.js';

/** Минимальный validate-result: только то, что читает правило корреляций. */
function mkResult(correlations) {
  return {
    status: 'ok',
    detected: { date: 'date', kpi: ['sales_rub'], media: [], control: [], ratio: 5 },
    columns: [],
    correlations,
  };
}

const collinearity = (insights) =>
  insights.filter(i => (i.text ?? '').includes('Мультиколлинеарность'));
const pairInfo = (insights) =>
  insights.filter(i => (i.text ?? '').includes('«бюджет + натуральная метрика»'));

describe('validateInsights: пары каналов в правиле мультиколлинеарности', () => {
  it('пара канала НЕ попадает в warning, вместо неё спокойная info-строка', () => {
    const out = validateInsights(mkResult({
      tv_spend: { tv_trp: 0.99 },
      tv_trp: { tv_spend: 0.99 },
    }));
    expect(collinearity(out)).toHaveLength(0);
    const info = pairInfo(out);
    expect(info).toHaveLength(1);
    expect(info[0].severity).toBe('info');
    expect(info[0].text).toContain('1 пара');
    expect(info[0].tip).toContain('одна колонка пары');
  });

  it('реальная кросс-канальная корреляция остаётся warning', () => {
    const out = validateInsights(mkResult({
      tv_spend: { digital_spend: 0.9 },
      digital_spend: { tv_spend: 0.9 },
    }));
    const warn = collinearity(out);
    expect(warn).toHaveLength(1);
    expect(warn[0].severity).toBe('warning');
    expect(warn[0].text).toContain('tv_spend');
    expect(pairInfo(out)).toHaveLength(0);
  });

  it('смесь: пары уходят в info, кросс-канальные — в warning (счёт верный)', () => {
    const out = validateInsights(mkResult({
      tv_spend: { tv_trp: 0.995, digital_spend: 0.9 },
      tv_trp: { tv_spend: 0.995 },
      digital_spend: { tv_spend: 0.9, digital_impressions: 0.99 },
      digital_impressions: { digital_spend: 0.99 },
    }));
    const warn = collinearity(out);
    expect(warn).toHaveLength(1);
    expect(warn[0].text).toContain('tv_spend ↔ digital_spend');
    expect(warn[0].text).not.toContain('tv_trp');
    const info = pairInfo(out);
    expect(info).toHaveLength(1);
    expect(info[0].text).toContain('2 пары');
  });

  it('ниже порога 0.85 — ни warning, ни info', () => {
    const out = validateInsights(mkResult({
      tv_spend: { tv_trp: 0.7 },
      tv_trp: { tv_spend: 0.7 },
    }));
    expect(collinearity(out)).toHaveLength(0);
    expect(pairInfo(out)).toHaveLength(0);
  });
});
