/**
 * «Нет числа — нет подписи» на ЭКРАНЕ (2026-07-26).
 *
 * Флагманская находка волны: несчитанная оценка качества модели показывалась
 * как результат измерения. В отчётах это починено (sections.py, builder.py —
 * «оценка не выполнялась»), а панель выводов в интерфейсе продолжала брать
 * `_mqsV?.score ?? 0` и рисовать «MQS = 0 () - модель требует доработки»:
 * в файле правда, на экране — нет. Пользователь принимает по этой панели
 * решение о медиабюджете, и ноль читается как приговор модели, а не как
 * «не оценивали».
 *
 * Гейт: при отсутствии (и при нечисловом значении) метрики панель не
 * показывает балл вовсе и говорит об отсутствии оценки прямо.
 */
import { describe, it, expect } from 'vitest';
import { modelInsights } from '../insights-rules.js';

/**
 * Обученная модель, метрики есть, оценка качества НЕ посчитана.
 * @returns {any}
 */
function dataWithoutMqs() {
  return {
    diagnostics: {
      metrics: { r_squared: 0.91, mape_pct: 7.4, r_hat_max: 1.0, divergences: 0, ratio: 6.2 },
    },
    channelParams: { OLV: {}, Banners: {}, Social: {} },
  };
}

/**
 * Та же модель, но оценка реально равна нулю — это измерение, его показываем.
 * @returns {any}
 */
function dataWithZeroMqs() {
  const d = dataWithoutMqs();
  d.diagnostics.mqs = { score: 0, tier_label: 'Ненадёжное' };
  return d;
}

/**
 * @param {number} score
 * @param {string} tierLabel
 * @returns {any}
 */
function dataWithScore(score, tierLabel) {
  const d = dataWithoutMqs();
  d.diagnostics.mqs = { score, tier_label: tierLabel };
  return d;
}

/** @param {any[]} insights @returns {string} */
const textOf = (insights) =>
  insights.map((/** @type {any} */ i) => `${i.text}\n${i.tip || ''}`).join('\n');

describe('панель выводов: несчитанная оценка качества не подставляется нулём', () => {
  it('без метрики балл не показывается вовсе', () => {
    const text = textOf(modelInsights(dataWithoutMqs(), undefined));
    expect(text).not.toMatch(/MQS\s*=\s*0\b/);
    expect(text).not.toMatch(/MQS\s*=\s*\d/);
  });

  it('без метрики сказано прямо, что оценка не рассчитана', () => {
    const text = textOf(modelInsights(dataWithoutMqs(), undefined));
    expect(text).toMatch(/не рассчитана/i);
  });

  it('отсутствие оценки не выдаётся за низкое качество', () => {
    const insights = modelInsights(dataWithoutMqs(), undefined);
    const verdict = insights.find((/** @type {any} */ i) => /MQS|оценка качества/i.test(i.text));
    expect(verdict).toBeDefined();
    expect(verdict?.text).not.toMatch(/требует доработки/i);
    expect(verdict?.severity).toBe('info');
  });

  it('реальный ноль остаётся видимым — это измерение, а не пропуск', () => {
    const text = textOf(modelInsights(dataWithZeroMqs(), undefined));
    expect(text).toMatch(/MQS\s*=\s*0\s*\(Ненадёжное\)/);
    expect(text).toMatch(/требует доработки/i);
  });

  it('регресс: посчитанный балл по-прежнему показывается с уровнем', () => {
    const high = textOf(modelInsights(dataWithScore(88, 'Отличное'), undefined));
    expect(high).toMatch(/MQS\s*=\s*88\s*\(Отличное\)/);

    const mid = textOf(modelInsights(dataWithScore(65, 'Приемлемое'), undefined));
    expect(mid).toMatch(/MQS\s*=\s*65\s*\(Приемлемое\)/);
  });

  it('без балла блок «что повышает доверие» не показывается', () => {
    // Метрики отличные — прежде это давало «доверяй модели» без единого
    // основания в виде оценки качества.
    const text = textOf(modelInsights(dataWithoutMqs(), undefined));
    expect(text).not.toMatch(/Что повышает доверие/i);
  });
});
