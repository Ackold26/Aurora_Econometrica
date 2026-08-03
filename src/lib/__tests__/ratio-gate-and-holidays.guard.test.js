/**
 * Сторож запаса данных: чем ГЕЙТИМ, чем ПОКАЗЫВАЕМ и что знает знаменатель.
 *
 * ЗАЧЕМ. Внешний аудит блока P0.2–P0.5 (2026-08-03) нашёл здесь Critical и три
 * High — все об одном: правка P0.3 свела показ запаса данных к эффективному
 * знаменателю, но вместе с показом на него уехали блокировка работы, а часть
 * потребителей осталась со своим числом.
 *
 *   - Critical: кнопка «Подтвердить роли» стала блокироваться по эффективному
 *     запасу. Проект с сырым 4,0 получал 1,7 и не проходил валидацию — пилот,
 *     работавший вчера, вставал на экране; «исключите слабые каналы» из текста
 *     блокировки авто-часть знаменателя не убирает вовсе, выхода не было.
 *   - High: мастер-переключатель «Учитывать праздники РФ» знаменателю неизвестен,
 *     хотя при ВЫКЛ модель праздников не заводит — встроенная справка советует
 *     выключить их при нехватке данных, и совет был инертным.
 *   - High: липкая шапка считала по числу ролей из ответа движка, а сырой запас
 *     рядом — по живым ролям: три числа одной величины на одном экране.
 *   - High: под-шаг «Роли колонок» терял режим и всегда считал по байесовскому.
 *
 * Решение владельца 2026-08-03: показ остаётся эффективным (честное число
 * параметров фактического режима), ГЕЙТ — по знаменателю движка. Экран не
 * вправе быть строже расчёта.
 *
 * ЧТО СТЕРЕЖЁТ ЭТОТ ФАЙЛ — следствия, а не печать чисел: какая ветка выбрана,
 * какую фразу увидит пользователь, совпадает ли фронт с движком.
 */
import { describe, expect, it } from 'vitest';

import { effectiveParamCount, effectiveRatio, gateRatio } from '../ratio-classifier.js';
import { validateInsights, validateRolesInsights, validateConfirmInsights } from '../insights-rules.js';
import validateStepSrc from '../components/pipeline/ValidateStepV13.svelte?raw';

/**
 * Ответ /compute/validate: 40 наблюдений, 10 назначенных столбцов (8 медиа +
 * 2 контроля), 12 авто-праздников. Ровно сценарий Critical из отчёта аудита.
 * @param {{holidays?: number, predictors?: number}} [o]
 */
function mkDetected(o = {}) {
  const holidays = o.holidays ?? 12;
  const predictors = o.predictors ?? 10;
  return {
    n_predictors: predictors,
    n_holidays_auto: holidays,
    n_intercept: 1,
    n_params_effective_bayesian: predictors + holidays + 1,
    n_params_effective_ols: predictors + 1,
    n_params_effective_pretrain: predictors + holidays + 1,
  };
}

describe('гейтовый знаменатель = знаменатель движка', () => {
  it('не зависит от выбранного режима — это нижняя граница числа параметров', () => {
    const d = mkDetected();
    // 40 / (10 + 1) = 3,64 — и в байесе, и в OLS одинаково.
    expect(gateRatio(40, d)).toBeCloseTo(3.64, 2);
    expect(gateRatio(40, d)).toBeCloseTo(effectiveRatio(40, d, 'ols'), 6);
  });

  it('совпадает с числом, которое движок кладёт в ответ (detected.ratio_gate)', () => {
    // Движок: ratio_gate = n_rows / n_params_effective_ols (validator.py).
    // Расхождение этих двух чисел означает, что экран гейтит НЕ тем, чем движок.
    const d = mkDetected();
    const fromEngine = 40 / d.n_params_effective_ols;
    expect(gateRatio(40, d)).toBeCloseTo(fromEngine, 6);
  });

  it('никогда не строже показанного: гейт ≥ эффективного запаса', () => {
    for (const predictors of [3, 10, 25]) {
      for (const obs of [20, 40, 104]) {
        const d = mkDetected({ predictors });
        expect(gateRatio(obs, d)).toBeGreaterThanOrEqual(effectiveRatio(obs, d, 'bayesian'));
      }
    }
  });

  it('сценарий Critical из отчёта: работа не блокируется там, где движок её пропускает', () => {
    const d = mkDetected();
    // Показ честно говорит «мало» (40/23 = 1,7)…
    expect(effectiveRatio(40, d, 'bayesian')).toBeLessThan(2);
    // …но гейт (40/11 = 3,6) выше порога, и кнопка обязана остаться активной.
    expect(gateRatio(40, d)).toBeGreaterThanOrEqual(2);
  });
});

describe('блокировка кнопки считается гейтовым числом, а не показанным', () => {
  it('условие разблокировки читает поле gate', () => {
    // Мутация «вернуть data.ratio в условие» красит этот тест по адресу.
    expect(validateStepSrc).toMatch(/ratioBlockedReason[\s\S]{0,700}data\.gate\s*>=\s*2/);
  });

  it('лекарство из текста блокировки считается тем же числом, что её держит', () => {
    // Иначе продукт обещает «исключите каналы → станет N:1», где N посчитано
    // другой формулой, и после исключения блокировка не снимается.
    expect(validateStepSrc).toMatch(/afterExcludeGate\s*=\s*[\s\S]{0,200}gateRatio\(/);
    // Условие «это поможет» проверяет гейтовое поле, а не показанное.
    const reason = validateStepSrc.slice(
      validateStepSrc.indexOf('const ratioBlockedReason'),
      validateStepSrc.indexOf('const kpiCountBlockedReason'),
    );
    expect(reason).toMatch(/canFix[\s\S]{0,200}afterExcludeGate/);
    expect(reason).not.toMatch(/afterExcludeRatio/);
  });

  it('плашка блокировки не печатает своего числа', () => {
    // Внешний аудит починки (High, 2026-08-03): карточка печатала эффективный
    // запас, плашка под ней — гейтовый, и на одном экране оказывались два разных
    // числа одной величины (0,9 против 1,8). Число показывает карточка, одна;
    // плашка объясняет словами. Мутация «вернуть ${data.gate.toFixed(1)}:1
    // в текст» красит этот тест.
    const reason = validateStepSrc.slice(
      validateStepSrc.indexOf('const ratioBlockedReason'),
      validateStepSrc.indexOf('const kpiCountBlockedReason'),
    );
    const clientText = reason
      .split('\n')
      .filter((/** @type {string} */ l) => !l.trim().startsWith('//'))
      .join('\n');
    expect(clientText).not.toMatch(/toFixed\(\d\)\}:1/);
    expect(clientText).not.toMatch(/\$\{(data\.)?(gate|ratio|after)[^}]*\}/);
  });

  it('показ карточки остаётся эффективным — гейт его не подменил', () => {
    expect(validateStepSrc).toMatch(/const ratio = effectiveRatio\(/);
  });
});

describe('мастер-переключатель праздников доезжает до знаменателя', () => {
  it('выключенные праздники убирают авто-часть в байесовском режиме', () => {
    const d = mkDetected();
    expect(effectiveParamCount(d, 'bayesian', null, true)).toBe(23);
    expect(effectiveParamCount(d, 'bayesian', null, false)).toBe(11);
  });

  it('то же с живым числом ролей (пользователь меняет их на экране)', () => {
    const d = mkDetected();
    expect(effectiveParamCount(d, 'bayesian', 7, true)).toBe(20);
    expect(effectiveParamCount(d, 'bayesian', 7, false)).toBe(8);
  });

  it('в OLS выключение ничего не меняет — праздников там не было и так', () => {
    const d = mkDetected();
    expect(effectiveParamCount(d, 'ols', null, true)).toBe(11);
    expect(effectiveParamCount(d, 'ols', null, false)).toBe(11);
  });

  it('умолчание — праздники учитываются (совместимость со старыми вызовами)', () => {
    const d = mkDetected();
    expect(effectiveParamCount(d, 'bayesian')).toBe(23);
  });

  it('сценарий High из отчёта: совет справки перестал быть инертным', () => {
    const d = mkDetected();
    // Пользователь делает ровно то, что советует справка при нехватке данных.
    const before = effectiveRatio(40, d, 'bayesian', 10, true);
    const after = effectiveRatio(40, d, 'bayesian', 10, false);
    expect(before).toBeLessThan(2);
    expect(after).toBeGreaterThan(before);
    expect(after).toBeGreaterThanOrEqual(3);
  });
});

describe('режим доезжает до под-шага «Роли колонок»', () => {
  /** Минимальный ответ валидации: 52 наблюдения, 8 медиа + 2 контроля. */
  const result = {
    file: { rows: 52 },
    detected: mkDetected(),
    columns: [
      { name: 'date', role: 'date' },
      { name: 'sales', role: 'kpi', stats: { zeros_pct: 0 } },
      ...Array.from({ length: 8 }, (_, i) => ({
        name: `media_${i}`, role: 'media', stats: { zeros_pct: 5, cv: 40 },
      })),
      ...Array.from({ length: 2 }, (_, i) => ({
        name: `ctrl_${i}`, role: 'control', stats: { zeros_pct: 0, cv: 30 },
      })),
    ],
    issues: [],
    warnings: [],
  };

  const texts = (/** @type {{text?: string}[]} */ list) => list.map(i => i.text ?? '').join('\n');

  it('делегирование не теряет режим: OLS и байес дают разные тексты', () => {
    const bayes = texts(validateRolesInsights(result, 'roi', 'bayesian'));
    const ols = texts(validateRolesInsights(result, 'roi', 'ols'));
    expect(bayes).not.toEqual(ols);
  });

  it('совпадает с прямым вызовом того же режима — общий источник, не копия', () => {
    expect(validateRolesInsights(result, 'roi', 'ols'))
      .toEqual(validateInsights(result, 'roi', 'ols'));
  });

  it('мастер-переключатель тоже доезжает через делегирование', () => {
    const on = texts(validateRolesInsights(result, 'roi', 'bayesian', true));
    const off = texts(validateRolesInsights(result, 'roi', 'bayesian', false));
    expect(on).not.toEqual(off);
  });

  it('умолчания сохранены — старые вызовы считают как раньше', () => {
    expect(validateRolesInsights(result, 'roi'))
      .toEqual(validateInsights(result, 'roi', 'bayesian', true));
  });
});

describe('поштучное отключение праздников доезжает до знаменателя', () => {
  // Внешний аудит починки (Medium, 2026-08-03): мастер-переключатель знаменателю
  // передали, а слой ниже — нет. `modeler.py` пропускает отключённые праздники
  // поимённо, значит состав модели меняется ровно так же, как от мастер-флага:
  // пользователь снимает 10 из 12 праздников, модель заводит 13 параметров,
  // а экран продолжает показывать 23 и прежний вердикт.
  const d = mkDetected();

  it('отключённые поштучно вычитаются из авто-части', () => {
    expect(effectiveParamCount(d, 'bayesian', null, true, 0)).toBe(23);
    expect(effectiveParamCount(d, 'bayesian', null, true, 10)).toBe(13);
  });

  it('то же с живым числом ролей', () => {
    expect(effectiveParamCount(d, 'bayesian', 7, true, 10)).toBe(10);
  });

  it('нельзя вычесть больше, чем есть авто-праздников', () => {
    expect(effectiveParamCount(d, 'bayesian', null, true, 99)).toBe(11);
    expect(effectiveParamCount(d, 'bayesian', 7, true, 99)).toBe(8);
  });

  it('в OLS и при выключенном мастер-флаге ничего не меняется', () => {
    expect(effectiveParamCount(d, 'ols', null, true, 10)).toBe(11);
    expect(effectiveParamCount(d, 'bayesian', null, false, 10)).toBe(11);
  });

  it('сценарий из отчёта: экран перестал показывать прежнее число', () => {
    const before = effectiveRatio(40, d, 'bayesian', 10, true, 0);
    const after = effectiveRatio(40, d, 'bayesian', 10, true, 10);
    expect(before).toBeCloseTo(1.74, 2);
    expect(after).toBeCloseTo(3.08, 2);
  });
});

describe('под-шаг «Подтверждение» считает тем же источником', () => {
  // Внешний аудит починки (High, 2026-08-03): у него оставалась своя формула —
  // всегда байесовская, всегда с 12 праздниками, — и он ПЕЧАТАЛ это число.
  // Через один клик пользователь видел 3,6 и 1,7. Рассинхрон создала правка P0.3.
  const result = {
    file: { rows: 40 },
    detected: mkDetected(),
    columns: [
      { name: 'sales', role: 'kpi', stats: { zeros_pct: 0 } },
      ...Array.from({ length: 8 }, (_, i) => ({ name: `m${i}`, role: 'media', stats: { zeros_pct: 5, cv: 40 } })),
      ...Array.from({ length: 2 }, (_, i) => ({ name: `c${i}`, role: 'control', stats: { zeros_pct: 0, cv: 30 } })),
    ],
    issues: [], warnings: [],
  };
  const num = (/** @type {{text?: string}[]} */ list) => {
    const m = list.map(i => i.text ?? '').join('\n').match(/(\d+[.,]\d):1/);
    return m ? Number(m[1].replace(',', '.')) : null;
  };

  it('OLS: «Подтверждение» и «Роли колонок» показывают одно число', () => {
    expect(num(validateConfirmInsights(result, {}, 'ols')))
      .toBe(num(validateRolesInsights(result, 'roi', 'ols')));
  });

  it('мастер-переключатель праздников доезжает и сюда', () => {
    const on = num(validateConfirmInsights(result, {}, 'bayesian', true));
    const off = num(validateConfirmInsights(result, {}, 'bayesian', false));
    expect(on).not.toBe(off);
    expect(off).toBe(num(validateConfirmInsights(result, {}, 'ols')));
  });
});
