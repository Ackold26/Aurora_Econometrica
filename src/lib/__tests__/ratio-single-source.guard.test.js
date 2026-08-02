/**
 * P0.3 (2026-08-03): сторож единого знаменателя «Запаса данных».
 *
 * Корень. До этой правки знаменатель считался в шести местах тремя разными
 * формулами — причём две из них жили внутри ОДНОЙ функции `validateInsights`.
 * Пользователь на одном экране видел «Запас данных 5,2 — Рекомендуемый
 * уровень» в шапке и «Критически мало данных: ratio 2,3:1» в советах под ней.
 * Замер: 52 наблюдения, 8 медиа + 2 контроля.
 *
 * Решение владельца: всё к эффективному — показываем и красим по числу
 * параметров, которое модель заведёт НА САМОМ ДЕЛЕ.
 *
 * 🔴 Знаменателей ДВА, по режиму: байесовский заводит авто-праздники, OLS не
 * заводит ни одного (в `ols_modeler.py` генератора праздников нет вовсе).
 * Единая константа «+13 всегда» соврала бы для OLS ровно настолько, насколько
 * сырой знаменатель врал для байеса. Поэтому сторож проверяет ОБА режима.
 */
import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
  effectiveParamCount,
  effectiveRatio,
} from '../ratio-classifier.js';
import { validateInsights, modelPreTrainingInsights } from '../insights-rules.js';
import { validateData, validationHeaderMetrics, modelEngine } from '../project-state.js';

/** 52 наблюдения, 8 медиа + 2 контроля — состав как отдаёт validator.py. */
function makeResult() {
  const columns = [];
  for (let i = 0; i < 8; i++) {
    columns.push({ name: `media_${i}`, role: 'media', stats: { zeros_pct: 5, vif: 2 } });
  }
  for (let i = 0; i < 2; i++) {
    columns.push({ name: `ctrl_${i}`, role: 'control', stats: { zeros_pct: 0 } });
  }
  columns.push({ name: 'sales', role: 'kpi', stats: { zeros_pct: 0 } });
  columns.push({ name: 'date', role: 'date', stats: {} });
  return {
    columns,
    file: { rows: 52 },
    detected: {
      rows: 52,
      n_rows: 52,
      n_predictors: 10,
      n_holidays_auto: 12,
      n_intercept: 1,
      n_params_effective_bayesian: 23,
      n_params_effective_ols: 11,
    },
  };
}

/** Обёртка стора «Валидация»: сторы ждут полную форму, тесту важен только result.
 * @param {any} result
 * @returns {any} */
function asValidateData(result) {
  return { result, correlationMatrix: null, columnHistograms: null };
}

/** Все числа вида «X.Y:1», упомянутые в наборе подсказок.
 * @param {any[]} insights */
function ratiosMentioned(insights) {
  const found = new Set();
  for (const ins of insights) {
    const text = `${ins.text ?? ''} ${ins.tip ?? ''}`;
    for (const m of text.matchAll(/(\d+[.,]\d+):1/g)) {
      found.add(m[1].replace(',', '.'));
    }
  }
  return found;
}

describe('P0.3: знаменатель «Запаса данных» — один источник', () => {
  it('байесовский режим: 52 / 23 параметра = 2.3', () => {
    const r = makeResult();
    expect(effectiveParamCount(r.detected, 'bayesian')).toBe(23);
    expect(effectiveRatio(52, r.detected, 'bayesian')).toBeCloseTo(2.26, 2);
  });

  it('режим OLS: праздников нет, 52 / 11 параметров = 4.7', () => {
    const r = makeResult();
    expect(effectiveParamCount(r.detected, 'ols')).toBe(11);
    expect(effectiveRatio(52, r.detected, 'ols')).toBeCloseTo(4.73, 2);
  });

  it('шапка и советы называют ОДНО число, а не разные', () => {
    const result = makeResult();
    modelEngine.set('bayesian');
    validateData.set(asValidateData(result));

    const header = /** @type {any} */ (get(validationHeaderMetrics));
    const shown = header.ratio.toFixed(1);
    expect(shown).toBe('2.3');

    // Ни одна подсказка не имеет права называть другое значение запаса.
    // Раньше здесь соседствовали 5.2 (шапка) и 2.3 (советы).
    const mentioned = ratiosMentioned([
      ...validateInsights(result, 'roi', 'bayesian'),
      ...modelPreTrainingInsights(result, undefined, 'bayesian'),
    ]);
    for (const value of mentioned) {
      // Значения «после исключения слабых каналов» легитимно выше текущего —
      // они про другую, гипотетическую конфигурацию. Запрещено ровно одно:
      // повторение СЫРОГО знаменателя (52/10 = 5.2) как текущего запаса.
      expect(value).not.toBe('5.2');
    }
  });

  it('при нехватке запаса продукт не успокаивает пользователя', () => {
    // Прямое следствие знаменателя, а не его печать. Блок готовности ветвится
    // по запасу: при ≥4 он говорит «Данные готовы к моделированию» либо
    // «N предупреждений не блокируют моделирование». На сыром знаменателе
    // (5.2) сюда попадал проект с фактическим запасом 2.3 — и получал
    // успокаивающую формулировку на данных, которых не хватает.
    const result = makeResult();
    const texts = validateInsights(result, 'roi', 'bayesian')
      .map((i) => i.text ?? '')
      .join(' || ');
    expect(texts).not.toContain('готовы к моделированию');
    expect(texts).not.toContain('не блокируют моделирование');
  });

  it('сырой запас остаётся доступен справочно, но не красит статус', () => {
    const result = makeResult();
    modelEngine.set('bayesian');
    validateData.set(asValidateData(result));
    const header = /** @type {any} */ (get(validationHeaderMetrics));
    expect(header.ratioRaw).toBeCloseTo(5.2, 1);
    // Статус обязан идти от эффективного (2.3 → «мало»), а не от сырого
    // (5.2 → «рекомендуемый уровень»). Иначе вернётся тот самый скачок
    // «зелёное до обучения, красное после».
    expect(header.ratioStatus).not.toBe('ok');
  });

  it('смена режима меняет запас данных на том же проекте', () => {
    const result = makeResult();
    validateData.set(asValidateData(result));

    modelEngine.set('bayesian');
    const bayes = /** @type {any} */ (get(validationHeaderMetrics)).ratio;
    modelEngine.set('ols');
    const ols = /** @type {any} */ (get(validationHeaderMetrics)).ratio;

    expect(bayes).toBeLessThan(ols);
    expect(bayes).toBeCloseTo(2.26, 2);
    expect(ols).toBeCloseTo(4.73, 2);
  });

  it('проект, сохранённый до P0.3 (нет новых полей), не падает', () => {
    const legacy = { n_predictors: 10, n_params_effective_pretrain: 23 };
    expect(effectiveParamCount(legacy, 'bayesian')).toBe(23);
    // Для OLS новых полей нет — собираем консервативно, без праздников.
    expect(effectiveParamCount(legacy, 'ols')).toBe(11);
  });
});
