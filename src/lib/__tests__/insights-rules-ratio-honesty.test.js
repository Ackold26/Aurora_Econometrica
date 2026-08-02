/**
 * INV-50 live-audit (2026-06-07): честный Ratio в инсайтах качества модели.
 *
 * Корень (live-проход перед rc10): шаги Модель/Отчёт показывали «Ratio 4.4:1»
 * (ssotRatio = obs/назначенные колонки) и из-за этого ГЛУШИЛИ варнинг
 * переобучения (isThin = ratio<4 → false при 4.4), хотя честный backend
 * effective ratio = 2.4 (obs/effective_params, posterior contraction) < 4 и
 * MQS честно капнут до 70. Это «второй слой» того же un-cap, что сняли с
 * MQS-score 2026-06-07 (один корень, N слоёв).
 *
 * Гейт: post-train инсайты берут backend effective ratio (m.ratio) и для
 * отображения, и для isThin — совпадая с MQS-cap/вердиктом. ssotRatio остаётся
 * лишь fallback при отсутствии backend-ratio.
 */
import { describe, it, expect } from 'vitest';
import { modelInsights, reportInsights } from '../insights-rules.js';

/** Кагоцел-подобная диагностика: честный effective ratio 2.4 < 4, MQS капнут до 70. */
function diagThin() {
  return {
    diagnostics: {
      metrics: { r_squared: 0.9763, mape_pct: 6.46, r_hat_max: 1.0, divergences: 1, ratio: 2.4 },
      mqs: { score: 70, tier_label: 'Хорошее', thinness_cap: 70 },
    },
    channelParams: { OLV: {}, Banners: {}, Social: {}, Performance: {}, TRPs: {} },
  };
}

const SSOT_OPTIMISTIC = 4.4; // obs/каналы — оптимистичный media-ratio (был источником лжи)

describe('INV-50: modelInsights берёт честный effective ratio, не ssotRatio', () => {
  it('показывает Ratio 2.4:1 (а не 4.4:1) даже когда передан ssotRatio=4.4', () => {
    const insights = modelInsights(diagThin(), SSOT_OPTIMISTIC);
    const text = insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');
    expect(text).toMatch(/Ratio 2\.4:1/);
    expect(text).not.toMatch(/Ratio 4\.4:1/);
  });

  it('варнинг переобучения НЕ заглушён (effective ratio 2.4 < 4)', () => {
    const insights = modelInsights(diagThin(), SSOT_OPTIMISTIC);
    const hasThinWarning = insights.some(
      (/** @type {any} */ i) =>
        (i.severity === 'warning' || i.severity === 'warning-high' || i.severity === 'error') &&
        /переобучен|мало|ориентир/i.test(`${i.text} ${i.tip || ''}`)
    );
    expect(hasThinWarning).toBe(true);
  });

  it('fallback: при отсутствии backend-ratio используется ssotRatio', () => {
    // diagnostics есть, но metrics без ratio (legacy / backend не дал) → fallback на ssotRatio
    const data = {
      diagnostics: {
        metrics: { r_squared: 0.9763, mape_pct: 6.46, r_hat_max: 1.0, divergences: 1 },
        mqs: { score: 70, tier_label: 'Хорошее', thinness_cap: 70 },
      },
      channelParams: { OLV: {}, Banners: {}, Social: {}, Performance: {}, TRPs: {} },
    };
    // Где проверяем. Блок качества reportInsights печатает «Ratio N:1» в любой
    // ветке, поэтому запасной путь там наблюдаем всегда. В modelInsights число
    // появляется только в ветке сниженного балла: прежде тест ловил его там,
    // потому что MQS 70 попадал в ветку «приемлемое качество» по старой шкале
    // 80/60. По канону (85/70/55/40) 70 — это «Хорошее», ветка другая, и
    // подстроки там нет. Инвариант теста прежний, изменилась поверхность
    // наблюдения — сам запасной путь исправен (см. проверку ниже).
    const rep = reportInsights({
      mod: data,
      dec: { baseline_pct: 83, channels: [] },
      opt: { expected_lift_pct: 5.7, total_budget_money: 2_342_802_669 },
      ssotRatio: SSOT_OPTIMISTIC,
    });
    const modelLine = rep.find((/** @type {any} */ i) => /Модель:/.test(i.text));
    expect(modelLine).toBeTruthy();
    expect(modelLine?.text).toMatch(/Ratio 4\.4:1/);

    // 4.4 классифицируется как «достаточный» → варнинга переобучения нет,
    // и честное 2.4 из backend'а не подставляется (его в этих данных нет).
    const insights = modelInsights(data, SSOT_OPTIMISTIC);
    const text = insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');
    expect(text).not.toMatch(/Ratio 2\.4:1/);
    expect(text).not.toMatch(/Данных мало/);
  });
});

describe('INV-50: reportInsights берёт честный effective ratio, не ssotRatio', () => {
  it('блок качества показывает Ratio 2.4:1 и ветку «данных мало» при ssotRatio=4.4', () => {
    const insights = reportInsights({
      mod: diagThin(),
      dec: { baseline_pct: 83, channels: [] },
      opt: { expected_lift_pct: 5.7, total_budget_money: 2_342_802_669 },
      ssotRatio: SSOT_OPTIMISTIC,
    });
    const modelLine = insights.find((/** @type {any} */ i) => /Модель:/.test(i.text));
    expect(modelLine).toBeTruthy();
    expect(modelLine?.text).toMatch(/Ratio 2\.4:1/);
    expect(modelLine?.text).not.toMatch(/Ratio 4\.4:1/);
    // isThin (2.4 < 4) → ветка предупреждения о переобучении
    expect(modelLine?.severity).toBe('warning');
    expect(modelLine?.text).toMatch(/Данных мало/);
  });
});
