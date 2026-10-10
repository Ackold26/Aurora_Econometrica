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
import { describe, it, expect, afterEach } from 'vitest';
import { get } from 'svelte/store';
import {
  effectiveParamCount,
  effectiveRatio,
} from '../ratio-classifier.js';
import { validateInsights, modelPreTrainingInsights } from '../insights-rules.js';
import { validateData, validationHeaderMetrics, modelEngine, modelChannelEnabled, resolveChannelEnabled } from '../project-state.js';
// s61 (А2): исходник экрана «Валидация» как текст – карточка запаса на подшаге
// «Роли колонок» обязана считать медиа тем же фильтром, что и шапка.
import validateStepSrc from '../components/pipeline/ValidateStepV13.svelte?raw';

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

/**
 * s61 (А2): один источник числа каналов / переменных / запаса данных.
 *
 * Корень. Пары «бюджет + физическая метрика»: в обучение идёт одна половина пары,
 * вторая выключается картой включённости, но роль у неё остаётся `media`. Шапка
 * шага считала по ролям – «8 каналов, 11 переменных, запас 1.9 – критически
 * мало», а обучение получало 4 канала и запас 2.3. Теперь счёт – по включённым.
 */
describe('А2: шапка считает медиа по ВКЛЮЧЁННЫМ в модель колонкам', () => {
  afterEach(() => {
    modelChannelEnabled.set({});
    modelEngine.set('bayesian');
  });

  /** @returns {any} */
  const header = () => /** @type {any} */ (get(validationHeaderMetrics));

  it('пары: 8 медиа-ролей, 4 выключены → 4 канала, 6 переменных, запас по 6', () => {
    const result = makeResult();
    modelEngine.set('bayesian');
    validateData.set(asValidateData(result));
    modelChannelEnabled.set({ media_4: false, media_5: false, media_6: false, media_7: false });

    const h = header();
    expect(h.activeMedia).toBe(4);
    expect(h.activeControls).toBe(2);
    expect(h.nPredictors).toBe(6);
    // 6 назначенных + 12 праздников + свободный член = 19 параметров.
    expect(h.nParamsEffectivePretrain).toBe(19);
    expect(h.ratio).toBeCloseTo(52 / 19, 6);
    expect(h.ratio.toFixed(1)).toBe('2.7');
    expect(h.ratio).toBeCloseTo(effectiveRatio(52, result.detected, 'bayesian', 6), 6);
    expect(h.ratioRaw).toBeCloseTo(52 / 6, 6);
  });

  it('тот же проект в режиме OLS: 52 / (6 + 1) = 7.4', () => {
    validateData.set(asValidateData(makeResult()));
    modelChannelEnabled.set({ media_4: false, media_5: false, media_6: false, media_7: false });
    modelEngine.set('ols');
    expect(header().nPredictors).toBe(6);
    expect(header().ratio).toBeCloseTo(52 / 7, 6);
  });

  it('пустая карта и карта без false → счёт прежний (нет ключа = включена)', () => {
    const result = makeResult();
    modelEngine.set('bayesian');
    validateData.set(asValidateData(result));

    modelChannelEnabled.set({});
    expect(header().activeMedia).toBe(8);
    expect(header().nPredictors).toBe(10);
    expect(header().ratio).toBeCloseTo(52 / 23, 6);

    // Развязка до выбора: часть ключей true, остальных ключей нет вовсе.
    modelChannelEnabled.set({ media_0: true, media_1: true });
    expect(header().activeMedia).toBe(8);
    expect(header().nPredictors).toBe(10);
  });

  it('реагирует на смену карты без смены результата проверки', () => {
    validateData.set(asValidateData(makeResult()));
    modelChannelEnabled.set({});
    expect(header().activeMedia).toBe(8);
    modelChannelEnabled.set({ media_0: false });
    expect(header().activeMedia).toBe(7);
    modelChannelEnabled.set({ media_0: true });
    expect(header().activeMedia).toBe(8);
  });

  it('файл без пар с разреженным каналом (нулей > 80 %): автоотключение меняет число уже на «Валидации»', () => {
    // Для владельца: это правда о будущем обучении – панель обучения такой канал
    // по умолчанию не включает, и шапка теперь показывает то же, что уйдёт в модель.
    const result = makeResult();
    result.columns[7].stats = { zeros_pct: 92, vif: 2 }; // media_7 – разреженный
    modelEngine.set('bayesian');
    validateData.set(asValidateData(result));
    const media = result.columns.filter((c) => c.role === 'media');
    const map = resolveChannelEnabled(media, {});
    expect(map.media_7).toBe(false);
    modelChannelEnabled.set(map);

    const h = header();
    expect(h.activeMedia).toBe(7);
    expect(h.nPredictors).toBe(9);
    expect(h.ratio).toBeCloseTo(52 / 22, 6); // 9 + 12 + 1
    // Тот же файл, пока карта не выставлена: прежние 8 каналов и 2.3.
    modelChannelEnabled.set({});
    expect(header().activeMedia).toBe(8);
    expect(header().ratio).toBeCloseTo(52 / 23, 6);
  });

  it('все медиа выключены → каналов 0, готовность данных не выше 20', () => {
    const result = makeResult();
    validateData.set(asValidateData(result));
    modelChannelEnabled.set(Object.fromEntries(
      result.columns.filter((c) => c.role === 'media').map((c) => [c.name, false]),
    ));
    expect(header().activeMedia).toBe(0);
    expect(header().mqs).toBeLessThanOrEqual(20);
  });

  it('карточка запаса на «Ролях колонок» считает медиа тем же фильтром включённости', () => {
    const card = validateStepSrc.slice(
      validateStepSrc.indexOf('const ratioCardData'),
      validateStepSrc.indexOf('const ratioBlockedReason'),
    );
    expect(card.length).toBeGreaterThan(0);
    // Мутация «вернуть счёт по ролям» красит этот тест.
    expect(card).toMatch(/activeCols\s*=\s*cols\.filter\([\s\S]{0,120}c\?\.role === 'media' && isModelColumnEnabled\(\$modelChannelEnabled, c\?\.name\)/);
    // Слабый канал, уже выключенный из модели, второй раз не вычитается.
    expect(card).toMatch(/weakEnabledCount\s*=\s*weakMedia\.filter\([\s\S]{0,120}isModelColumnEnabled\(\$modelChannelEnabled, c\?\.name\)/);
    expect(card).toMatch(/const nAfter = nPredictors - weakEnabledCount;/);
  });
});
