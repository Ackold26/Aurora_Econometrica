/**
 * Две шкалы не расходятся НА ЭКРАНЕ (2026-08-09).
 *
 * Дефект доказан зондом: при R-hat 1.06 и нуле расхождений показатель качества
 * даёт MQS 88 «Отличное», а честностный гейт оптимизатора — `refused=true`.
 * Панель выводов при этом писала «Результаты надёжны для принятия решений»,
 * выводя вердикт ТОЛЬКО из ступени (`mqsIsDependable`). Слова «refused» в
 * `insights-rules.js` не встречалось вовсе — про отказ панель не знала в
 * принципе. Пользователь читал на одном экране «переброска отключена» и
 * «результаты надёжны».
 *
 * Это была двенадцатая поверхность дефекта — в исходной карте мест её не было,
 * нашлась финальным поиском по сигнатуре класса.
 *
 * 🔴 Гейтим ДЕЙСТВИЕ, не ДАННЫЕ: каждая проверка «фраза пришла» имеет парную
 * «балл и ступень остались». Спрятать показатели — это другой дефект.
 */
import { describe, it, expect } from 'vitest';
import { modelInsights, reportInsights } from '../insights-rules.js';
import { RELIABILITY_STATEMENT_REFUSED } from '../mqs-tiers.js';

const ENDORSEMENTS = ['Результаты надёжны для принятия решений', 'Результаты надёжны.'];

/**
 * Доказанный зондом расклад: расчёт не сошёлся, показатель отличный,
 * данных при этом достаточно (иначе сработала бы оговорка о тонких данных).
 * @param {string|null} verdict
 * @returns {any}
 */
function modelData(verdict) {
  return {
    diagnostics: {
      metrics: {
        r_squared: 0.97, mape_pct: 3.0, r_hat_max: 1.06,
        divergences: 0, ratio: 12, n_observations: 120, n_parameters: 10,
      },
      mqs: { score: 88, tier_label: 'Отличное', tier: 'excellent' },
      ...(verdict ? { honesty_verdict: verdict } : {}),
    },
    channelParams: { OLV: {}, Banners: {}, Social: {} },
  };
}

/**
 * @param {boolean} refused
 * @returns {any}
 */
function reportCtx(refused) {
  return {
    mod: modelData(refused ? 'unreliable' : 'reliable'),
    dec: { baseline_pct: 60, channels: [{ name: 'TV', contribution_pct: 40, roi: 2.1 }] },
    opt: {
      expected_lift_pct: 12,
      total_budget_money: 5_000_000,
      model_reliability: {
        verdict: refused ? 'unreliable' : 'reliable',
        refused,
        caveat_text: refused ? 'Модель не завершила расчёт корректно' : '',
      },
    },
  };
}

/** @param {any[]} insights */
const joined = (insights) => insights.map((i) => `${i.text} ${i.tip ?? ''}`).join('\n');

describe('панель выводов модели', () => {
  it('при отказе не обещает надёжность, а несёт согласованную фразу', () => {
    const text = joined(modelInsights(modelData('unreliable')));
    for (const phrase of ENDORSEMENTS) {
      expect(text, `расчёт не сошёлся, а панель обещает «${phrase}»`).not.toContain(phrase);
    }
    expect(text).toContain(RELIABILITY_STATEMENT_REFUSED);
  });

  it('при отказе балл и ступень остаются на экране', () => {
    const text = joined(modelInsights(modelData('unreliable')));
    expect(text).toContain('MQS = 88');
    expect(text).toContain('Отличное');
  });

  it('у сошедшейся модели текст прежний', () => {
    const text = joined(modelInsights(modelData('reliable')));
    expect(text).toContain('Результаты надёжны для принятия решений');
    expect(text).not.toContain(RELIABILITY_STATEMENT_REFUSED);
  });

  it('без штампа надёжности поведение прежнее — старые проекты не ломаются', () => {
    const text = joined(modelInsights(modelData(null)));
    expect(text).not.toContain(RELIABILITY_STATEMENT_REFUSED);
  });
});

describe('сводка отчёта', () => {
  it('при отказе не обещает надёжность, а несёт согласованную фразу', () => {
    const text = joined(reportInsights(reportCtx(true)));
    for (const phrase of ENDORSEMENTS) {
      expect(text, `расчёт не сошёлся, а сводка обещает «${phrase}»`).not.toContain(phrase);
    }
    expect(text).toContain(RELIABILITY_STATEMENT_REFUSED);
  });

  it('при отказе балл и ступень остаются в сводке', () => {
    const text = joined(reportInsights(reportCtx(true)));
    expect(text).toContain('MQS 88');
    expect(text).toContain('Отличное');
  });

  it('у сошедшейся модели текст прежний', () => {
    const text = joined(reportInsights(reportCtx(false)));
    expect(text).toContain('Результаты надёжны');
    expect(text).not.toContain(RELIABILITY_STATEMENT_REFUSED);
  });
});
