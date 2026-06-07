/**
 * #6 OVB-guardrail (2026-06-07): insight по неинформативным контролям.
 *
 * modelInsights читает diagnostics.per_control_contraction и подсказывает убрать
 * неинформативные контроли (contraction<0.1, posterior≈prior) — OVB-safe, не меняет
 * media-ROI и честный MQS. Информативные убирать нельзя (OVB + нечестный рост MQS).
 * Рамка честности: цель — чистота модели, НЕ накрутка балла.
 */
import { describe, it, expect } from 'vitest';
import { modelInsights } from '../insights-rules.js';

/** @param {Record<string, number>} pcc */
function diagWithControls(pcc) {
  return {
    diagnostics: {
      metrics: { r_squared: 0.97, mape_pct: 6.5, r_hat_max: 1.0, divergences: 1, ratio: 2.4 },
      mqs: { score: 70, tier_label: 'Хорошее', thinness_cap: 70 },
      per_control_contraction: pcc,
    },
    channelParams: { OLV: {} },
  };
}

describe('#6 OVB-guardrail insight', () => {
  it('подсказывает убрать неинформативные (contraction<0.1), считает корректно', () => {
    const ins = modelInsights(
      diagWithControls({ rare1: 0.02, rare2: 0.06, queries: 0.93, comp: 0.94 }), 2.4);
    const hint = /** @type {any} */ (ins.find((/** @type {any} */ i) => /Контроли:/.test(i.text)));
    expect(hint).toBeTruthy();
    expect(hint.text).toMatch(/2 из 4/);            // 2 неинформативных из 4
    expect(hint.tip).toMatch(/rare1/);              // перечисляет неинформативные
    expect(hint.tip).toMatch(/omitted variable bias/i);  // предупреждает про OVB
  });

  it('честная рамка: удаление НЕ подаётся как способ поднять MQS', () => {
    const ins = modelInsights(diagWithControls({ rare1: 0.02, queries: 0.93 }), 2.4);
    const hint = /** @type {any} */ (ins.find((/** @type {any} */ i) => /Контроли:/.test(i.text)));
    expect(hint.tip).toMatch(/не накрутк|чистота модели/i);
    expect(hint.tip).toMatch(/НЕ изменит ROI|честный MQS/);
  });

  it('нет подсказки если все контроли информативны', () => {
    const ins = modelInsights(diagWithControls({ a: 0.5, b: 0.9 }), 2.4);
    expect(ins.find((/** @type {any} */ i) => /Контроли:/.test(i.text))).toBeFalsy();
  });

  it('нет подсказки если per_control_contraction отсутствует (legacy)', () => {
    const data = {
      diagnostics: {
        metrics: { r_squared: 0.97, mape_pct: 6.5, r_hat_max: 1.0, divergences: 1, ratio: 2.4 },
        mqs: { score: 70, tier_label: 'Хорошее', thinness_cap: 70 },
      },
      channelParams: { OLV: {} },
    };
    expect(modelInsights(data, 2.4).find((/** @type {any} */ i) => /Контроли:/.test(i.text))).toBeFalsy();
  });
});
