/**
 * insights-kpi-count-aware.test.js
 *
 * Фаза 3, пласт 3: проверяет что инсайт-функции не генерируют
 * денежно-результатные фразы («mROAS ×», «каждый рубль ... продаж») для
 * count-KPI и режима effectiveness, а для monetary (isLegacy) сохраняют
 * прежние формулировки (backward-compat).
 *
 * Покрываемые функции: optimizeInsights, decomposeInsights.
 * Точки правки (строки после патча):
 *   ≈1861 — tip про «рубль даёт меньше рубля продаж»
 *   ≈2039 — tip «предельная отдача следующего ₽ затрат»
 *   ≈2044 — text «mROAS X×» одного канала → KPI-aware
 *   ≈2094 — shiftDescription «каждый рубль ещё работает на полную»
 */
import { describe, it, expect } from 'vitest';
import { optimizeInsights, decomposeInsights } from '../lib/insights-rules.js';
import { kpiView } from '../lib/kpi-aware-formatting.js';

// ─── фикстуры ────────────────────────────────────────────────────────────────

/** kpi-объект для денежного ROI (isLegacy = true). */
const kpiMonetary = kpiView({});

/** kpi-объект для счётной метрики «лиды» (isLegacy = false). */
const kpiCountLeads = kpiView({ kpiKind: 'count', derivedMode: 'roi', kpiType: 'leads', valuePerCountUnit: 1000 });

/** kpi-объект без kpiType (backward-compat для count). */
const kpiCountGeneric = kpiView({ kpiKind: 'count', derivedMode: 'roi' });

/** kpi-объект для режима effectiveness. */
const kpiEffectiveness = kpiView({ kpiKind: 'monetary', derivedMode: 'effectiveness' });

/**
 * Минимальный объект результата optimizeInsights с несколькими каналами.
 * lift = 0 → ветка «оптимизатор не нашёл выигрыша».
 */
function mkOptData({ lift = 0, twoActiveChannels = true } = {}) {
  const base = 1_000_000;
  const optimal = base * (1 + lift / 100);
  if (twoActiveChannels) {
    return {
      objective: optimal,
      objective_current: base,
      total_budget: 10_000_000,
      total_current: 10_000_000,
      total_optimal: 10_000_000,
      channels: [
        {
          name: 'TV',
          current_spend: 5_000_000,
          optimal_spend: 4_000_000,   // снижается
          mroi_current: 0.7,
          roi: 1.5,
          action: 'Hold',
        },
        {
          name: 'Digital',
          current_spend: 5_000_000,
          optimal_spend: 6_000_000,   // растёт
          mroi_current: 1.8,
          roi: 2.2,
          action: 'Scale',
        },
      ],
    };
  }
  // Один активный канал
  return {
    objective: optimal,
    objective_current: base,
    total_budget: 5_000_000,
    total_current: 5_000_000,
    total_optimal: 5_000_000,
    channels: [
      {
        name: 'TV',
        current_spend: 5_000_000,
        optimal_spend: 5_000_000,
        mroi_current: 1.2,
        roi: 1.8,
        action: 'Hold',
      },
      {
        name: 'Digital',
        current_spend: 0,
        optimal_spend: 0,
        mroi_current: 0,
        roi: 0,
        action: 'Hold',
      },
    ],
  };
}

/**
 * Минимальный объект для decomposeInsights.
 */
function mkDecData() {
  return {
    baseline_pct: 65,
    channels: [
      { name: 'TV',      spend: 5_000_000, contribution: 800_000, contribution_pct: 60, roi: 1.5 },
      { name: 'Digital', spend: 3_000_000, contribution: 600_000, contribution_pct: 40, roi: 2.1 },
    ],
  };
}

// ─── helpers ─────────────────────────────────────────────────────────────────

/** Собирает все тексты + tip инсайтов в одну строку для удобного поиска. */
function allContent(insights) {
  return insights.map(i => `${i.text ?? ''} ||| ${i.tip ?? ''}`).join('\n');
}

// ─── count KPI: проблемные фразы НЕ появляются ───────────────────────────────

describe('optimizeInsights — count KPI: денежно-результатные фразы запрещены', () => {

  it('lift≈0: tip не содержит «рубля продаж» для count (лиды)', () => {
    const data = mkOptData({ lift: 0 });
    const ctx = {
      dec: { channels: mkDecData().channels },
      kpi: kpiCountLeads,
    };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    expect(content).not.toMatch(/рубл[яьей]+ продаж/i);
    expect(content).not.toMatch(/меньше 1 рубля продаж/i);
  });

  it('lift≈0: tip не содержит «рубля продаж» для count generic', () => {
    const data = mkOptData({ lift: 0 });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiCountGeneric };
    const insights = optimizeInsights(data, ctx);
    expect(allContent(insights)).not.toMatch(/меньше 1 рубля продаж/i);
  });

  it('lift≈0: tip не содержит «рубля продаж» для effectiveness', () => {
    const data = mkOptData({ lift: 0 });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiEffectiveness };
    const insights = optimizeInsights(data, ctx);
    expect(allContent(insights)).not.toMatch(/меньше 1 рубля продаж/i);
  });

  it('2 канала: tip про предельную отдачу НЕ содержит «следующего рубля» (без «затрат») для count', () => {
    const data = mkOptData({ lift: 0, twoActiveChannels: true });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiCountLeads };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    // Допустимо «следующего ₽ затрат», недопустимо «следующего рубля» без «затрат»
    const hasOldPhrase = /следующего рубля(?!\s+затрат)/i.test(content);
    expect(hasOldPhrase).toBe(false);
  });

  it('1 активный канал: text не содержит «mROAS X×» для count', () => {
    const data = mkOptData({ twoActiveChannels: false });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiCountLeads };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    // «mROAS 1.20×» — денежный формат, недопустимо для count
    expect(content).not.toMatch(/mROAS\s+[\d.]+×/i);
  });

  it('перекладка: shiftDescription не содержит «каждый рубль ещё работает» для count', () => {
    // lift > 5 → ветка с перекладкой (оба канала значимо меняются)
    const data = mkOptData({ lift: 10, twoActiveChannels: true });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiCountLeads };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    expect(content).not.toMatch(/каждый рубль ещё работает на полную/i);
  });

});

// ─── monetary KPI: backward-compat — прежние фразы сохранены ─────────────────

describe('optimizeInsights — monetary KPI (isLegacy): backward-compat', () => {

  it('lift≈0: tip содержит старую фразу «меньше 1 рубля продаж»', () => {
    const data = mkOptData({ lift: 0 });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiMonetary };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    expect(content).toMatch(/меньше 1 рубля продаж/i);
  });

  it('2 канала: tip про mROAS содержит «следующий рубль в канал» для monetary', () => {
    const data = mkOptData({ lift: 0, twoActiveChannels: true });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiMonetary };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    expect(content).toMatch(/следующий рубль в канал/i);
  });

  it('перекладка: shiftDescription содержит «каждый рубль ещё работает на полную» для monetary', () => {
    const data = mkOptData({ lift: 10, twoActiveChannels: true });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiMonetary };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    expect(content).toMatch(/каждый рубль ещё работает на полную/i);
  });

  it('1 активный канал: text содержит «mROAS X×» для monetary', () => {
    const data = mkOptData({ twoActiveChannels: false });
    const ctx = { dec: { channels: mkDecData().channels }, kpi: kpiMonetary };
    const insights = optimizeInsights(data, ctx);
    const content = allContent(insights);
    // Для monetary ожидаем формат ×
    expect(content).toMatch(/mROAS|ROI.*×|×.*ROI/i);
  });

});

// ─── decomposeInsights: дополнительная страховка на ROI-фразу ────────────────

describe('decomposeInsights — monetary: «рублей продаж» только в isLegacy-ветке', () => {

  it('monetary: лучший ROI содержит «рублей продаж»', () => {
    const data = mkDecData();
    const insights = decomposeInsights(data, kpiMonetary);
    const content = allContent(insights);
    // Строка 1637 под isLegacy — должна присутствовать
    expect(content).toMatch(/рублей продаж/i);
  });

  it('count leads: лучший CPU НЕ содержит «рублей продаж»', () => {
    const data = mkDecData();
    const insights = decomposeInsights(data, kpiCountLeads);
    const content = allContent(insights);
    expect(content).not.toMatch(/рублей продаж/i);
  });

  it('effectiveness: не содержит «рублей продаж»', () => {
    const data = mkDecData();
    const insights = decomposeInsights(data, kpiEffectiveness);
    const content = allContent(insights);
    expect(content).not.toMatch(/рублей продаж/i);
  });

});
