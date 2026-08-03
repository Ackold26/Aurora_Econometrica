/**
 * Сторож показа проверки канона «отрицательный базовый уровень» (P0.6).
 *
 * ЗАЧЕМ. Правило этой линии: «функция есть» ≠ «функция подключена» ≠ «функция
 * отдаёт обещанное». В этом же продукте уже находились написанный и никем не
 * вызванный сертификат методологии и торнадо чувствительности. Расчёт базы
 * считается при обучении и кладётся в диагностику — этот файл стережёт, что он
 * доезжает до глаз пользователя и говорит по делу.
 *
 * ЧТО СТЕРЕЖЁТ — следствия, а не наличие кода: появляется ли текст, каким он
 * становится на провале и на границе, и — отдельно — молчит ли продукт там, где
 * проверка недоступна. Молчание здесь важнее текста: у OLS апостериорных выборок
 * нет вовсе, и «проверка недоступна» нельзя подавать как «проверка пройдена».
 */
import { describe, expect, it } from 'vitest';

import { modelInsights } from '../insights-rules.js';

/**
 * Диагностика здоровой обученной модели + подставляемая проверка базы.
 * @param {any} negativeBaseline
 */
function mkModel(negativeBaseline) {
  return {
    diagnostics: {
      metrics: {
        r_squared: 0.82, mape_pct: 8.5, r_hat_max: 1.01, divergences: 0,
        ratio: 6.2, n_observations: 60, n_parameters: 10,
      },
      mqs: { score: 78, tier: 'good', tier_label: 'Хорошее' },
      checks: { ratio: true },
      ...(negativeBaseline === undefined ? {} : { negative_baseline: negativeBaseline }),
    },
    channelParams: { ТВ: {}, Диджитал: {} },
  };
}

const texts = (/** @type {{text?: string}[]} */ list) => list.map(i => i.text ?? '').join('\n');

describe('отрицательный базовый уровень доезжает до экрана', () => {
  it('провал: пользователь узнаёт, что ROI завышен', () => {
    const out = modelInsights(mkModel({
      prob_negative: 0.95, verdict: 'fail', baseline_mean: -1200,
    }));
    const t = texts(out);
    expect(t).toMatch(/базовый уровень продаж уходит в минус/i);
    expect(t).toMatch(/95%/);
    // Главное следствие названо прямо: завышен не «показатель», а ROI и советы.
    expect(t).toMatch(/вклад каналов завышен/i);
    expect(out.some(i => i.severity === 'error')).toBe(true);
  });

  it('провал: подсказка называет ДЕЙСТВИЕ, а не диагноз', () => {
    const out = modelInsights(mkModel({ prob_negative: 0.9, verdict: 'fail' }));
    const tip = out.find(i => /базовый уровень/i.test(i.text ?? ''))?.tip ?? '';
    expect(tip).toMatch(/контрольн/i);
    expect(tip).toMatch(/переобучите|сократите/i);
  });

  it('граница: предупреждение мягче и говорит о верхней границе ROI', () => {
    const out = modelInsights(mkModel({ prob_negative: 0.45, verdict: 'watch' }));
    const t = texts(out);
    expect(t).toMatch(/близок к нулю/i);
    expect(t).toMatch(/верхнюю границу/i);
    expect(out.some(i => i.severity === 'error' && /базовый уровень/i.test(i.text ?? ''))).toBe(false);
  });

  it('годно: продукт молчит — сторож, срабатывающий всегда, бесполезен', () => {
    const out = modelInsights(mkModel({ prob_negative: 0.01, verdict: 'ok' }));
    expect(texts(out)).not.toMatch(/базовый уровень продаж/i);
  });

  it('проверка неприменима по данным: молчим, а не показываем успех', () => {
    // 🔴 Замер 2026-08-03: при малом разбросе продаж база не может уйти в минус
    // в принципе (нужны десятки сигм приора свободного члена), поэтому движок
    // отдаёт `not_applicable` вместо «годно». На экране это ничего не значит
    // для пользователя — и уж точно не должно читаться как пройденная проверка.
    const out = modelInsights(mkModel({
      prob_negative: 0.0, verdict: 'not_applicable', detectable: false, sigmas_needed: 25.9,
    }));
    expect(texts(out)).not.toMatch(/базовый уровень продаж/i);
  });

  it('проверка недоступна (OLS, старые модели): молчим, а не рапортуем успех', () => {
    // Ключа нет вовсе — модель обучена до P0.6 либо в режиме OLS.
    expect(texts(modelInsights(mkModel(undefined)))).not.toMatch(/базовый уровень продаж/i);
    // Ключ есть, но пустой — расчёт не смог отработать (вырожденный масштаб).
    expect(texts(modelInsights(mkModel(null)))).not.toMatch(/базовый уровень продаж/i);
    expect(texts(modelInsights(mkModel({})))).not.toMatch(/базовый уровень продаж/i);
  });

  it('клиентский текст без англицизмов и длинного тире', () => {
    // Проверяем СВОЙ инсайт: соседние тексты продукта — не предмет этого сторожа.
    const out = modelInsights(mkModel({ prob_negative: 0.95, verdict: 'fail' }));
    const мой = out.filter(i => /базовый уровень/i.test(i.text ?? ''));
    expect(мой).toHaveLength(1);
    const текст = `${мой[0].text ?? ''} ${мой[0].tip ?? ''}`;
    expect(текст).not.toContain('—');
    expect(текст).not.toMatch(/baseline|intercept|posterior|prior/i);
  });
});
