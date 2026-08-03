/**
 * SSOT ratio-классификатор для Aurora MMM Optimizer.
 *
 * Ratio = observations / predictors. Это ключевая метрика статистической
 * надёжности модели. Аврора использует 5 коридоров (Антон 2026-05-16
 * запросил стандартизацию после рассогласованности RatioInfoCard /
 * ModeDerivedExplanation / sticky header «Критически мало» при 2.8).
 *
 * Все UI-компоненты которые показывают label / tone / описание ratio
 * должны импортировать `classifyRatio()` отсюда. Это гарантирует, что
 * пользователь видит одинаковые слова и цвета в:
 *   - sticky header валидации (project-state.validationHeaderMetrics)
 *   - RatioInfoCard (большая карточка Manager mode)
 *   - ModeDerivedExplanation (финальная сводка под-шага «Подтверждение»)
 *   - inline инсайтах InsightsPanel
 */

/**
 * 5-коридорные пороги ratio. Cross-referenced с insights-rules.js и
 * validator.py (backend). Менять только синхронно во всех 3 местах.
 */
export const RATIO_THRESHOLDS = Object.freeze({
  /** < 1 - модель НЕ определяется: параметров ≥ наблюдений, нет степеней свободы
   *  (df = n_obs - n_params ≤ 0). В OLS X'X вырождена - единственного решения нет.
   *  Это методологический пол: только здесь «ошибка/невозможно» (SEV-1, 2026-06-02). */
  DEGENERATE: 1,
  /** < 2 - критически мало (df > 0, модель идентифицируема, но только направление).
   *  = минимальный приемлемый порог (MIN_RATIO). Раньше был error/красный - но при
   *  1≤ratio<2 модель реально обучается (Кагоцел 1.7 сошёлся), поэтому warning, не error. */
  ERROR: 2,
  /** 2 - 3 - warning-high (между минимумом и стандартом) */
  HIGH_WARNING: 3,
  /** 3 - 4 - warning (ниже рекомендуемого) */
  WARNING: 4,
  /** 4 - 6 - info (рекомендуемый уровень), >= 6 - success (идеально) */
  IDEAL: 6,
});

/**
 * @typedef {'error'|'warning-high'|'warning'|'info'|'success'|'unknown'} RatioSeverity
 * @typedef {'danger'|'warn-strong'|'warn'|'info'|'success'|'neutral'} RatioTone
 *
 * @typedef {{
 *   severity: RatioSeverity,
 *   label: string,
 *   description: string,
 *   tone: RatioTone,
 *   bandLabel: string,
 * }} RatioClassification
 */

/**
 * Классифицирует ratio данных в один из 5 коридоров + edge-case unknown.
 *
 * @param {number | null | undefined} ratio
 * @returns {RatioClassification}
 */
export function classifyRatio(ratio) {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) {
    return {
      severity: 'unknown',
      label: 'Не определено',
      description: 'Ratio данных не рассчитано – убедитесь, что роли колонок назначены',
      tone: 'neutral',
      bandLabel: '',
    };
  }
  if (ratio < RATIO_THRESHOLDS.DEGENERATE) {
    // SEV-1 (2026-06-02): методологический пол идентифицируемости. df ≤ 0 →
    // оценка не существует. Единственная зона настоящей «ошибки/невозможности».
    return {
      severity: 'error',
      label: 'Модель не определяется',
      description: 'Переменных не меньше, чем точек данных – у модели нет единственного решения (нет степеней свободы). Уберите каналы или соберите больше истории.',
      tone: 'danger',
      bandLabel: 'вырождена, df ≤ 0',
    };
  }
  if (ratio < RATIO_THRESHOLDS.ERROR) {
    // SEV-1 (2026-06-02): 1 ≤ ratio < 2 - модель идентифицируема и реально
    // обучается (Кагоцел 1.7), просто слабо. Не «ошибка» (красный), а высокий
    // warning (оранжевый): результаты только как направление, не абсолют.
    return {
      severity: 'warning-high',
      label: 'Критически мало',
      description: 'Данных хватает только на направление (что наращивать, что сокращать), не на точные цифры – высокий риск переобучения. Приемлемо для пилота как ориентир.',
      tone: 'warn-strong',
      bandLabel: 'ниже минимума 2:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.HIGH_WARNING) {
    return {
      severity: 'warning-high',
      label: 'Ниже минимума',
      description: 'Модель сойдётся, но правдоподобные диапазоны будут очень широкими – используйте результаты как ориентир',
      tone: 'warn-strong',
      bandLabel: 'между минимумом 2:1 и стандартом 4:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.WARNING) {
    return {
      severity: 'warning',
      label: 'Ниже рекомендуемого',
      description: 'Модель работает, но с широкими правдоподобными диапазонами – результаты как качественные ориентиры',
      tone: 'warn',
      bandLabel: 'ниже рекомендуемого 4:1',
    };
  }
  if (ratio < RATIO_THRESHOLDS.IDEAL) {
    return {
      severity: 'info',
      label: 'Рекомендуемый уровень',
      // F-A1-9: ratio описывает только ОБЪЁМ данных (наблюдений на переменную).
      // Слова «надёжность» здесь нет — достаточность данных ≠ качество модели.
      description: 'Достаточный объём данных. Для ещё более узких правдоподобных диапазонов нужно ≥6:1',
      tone: 'info',
      bandLabel: 'рекомендуемый 4:1',
    };
  }
  return {
    severity: 'success',
    label: 'Высокий объём данных',
    // F-A1-9: «Идеально» убрано — ratio говорит только об объёме, не о качестве.
    description: 'Узкие правдоподобные диапазоны – оптимальный объём наблюдений на переменную',
    tone: 'success',
    bandLabel: 'идеально ≥ 6:1',
  };
}

/**
 * Маппинг 5-уровневой severity к legacy 3-tier (ok / warn / bad) - для
 * компонентов которые ещё используют traffic-light pill.
 *
 * @param {RatioSeverity} severity
 * @returns {'ok'|'warn'|'bad'|'na'}
 */
export function severityTo3Tier(severity) {
  if (severity === 'unknown') return 'na';
  if (severity === 'success' || severity === 'info') return 'ok';
  if (severity === 'warning') return 'warn';
  return 'bad';
}

/**
 * P0.3 (2026-08-03, решение владельца «всё к эффективному»): ЕДИНЫЙ источник
 * знаменателя «Запаса данных» на всех экранах до обучения.
 *
 * Зачем отдельная функция, а не расчёт по месту. До этой правки знаменатель
 * считался в шести местах тремя разными формулами — причём две из них жили
 * внутри одной функции `validateInsights`. Пользователь на одном экране видел
 * «Запас данных 5,2 — Рекомендуемый уровень» в шапке и «Критически мало
 * данных: ratio 2,3:1» в советах под ней.
 *
 * 🔴 Знаменателей ДВА, по режиму моделирования:
 *   - байесовский заводит авто-праздники РФ (их инжектит `modeler.py` в
 *     контроли) + свободный член;
 *   - OLS не заводит ни одного праздника (в `ols_modeler.py` генератора нет
 *     вовсе) — только свободный член.
 * Единая константа «+13 всегда» соврала бы для OLS ровно настолько, насколько
 * сырой знаменатель врёт для байеса.
 *
 * Состав приходит из `validator.py` (`detected.n_params_effective_*`); здесь
 * только выбор по режиму — собирать состав на фронте нельзя, это завело бы
 * второй источник истины.
 *
 * 🔴 Мастер-переключатель праздников (внешний аудит, High, 2026-08-03). Экран
 * «Учитывать праздники РФ» шлёт в обучение `use_holidays`, и при ВЫКЛ движок
 * не заводит ни одного праздника (`modeler.py`: инъекция под флагом). Валидация
 * идёт раньше и флага не знает, поэтому авто-часть корректируется здесь. Без
 * этого встроенная справка советует выключить праздники при нехватке данных,
 * пользователь так и делает, а число на экране не двигается.
 *
 * @param {any} detected  блок `result.detected` из ответа /compute/validate
 * @param {'bayesian'|'ols'|string|null|undefined} engine  текущий режим
 * @param {number|null} [nPredictorsOverride]  актуальное число назначенных
 *   столбцов, когда пользователь меняет роли на лету и число из ответа движка
 *   уже устарело. Авто-часть (праздники, свободный член) берётся из ответа —
 *   она от ролей не зависит.
 * @param {boolean} [useHolidays]  состояние мастер-переключателя праздников;
 *   при `false` авто-праздники не заводятся ни в одном режиме.
 * @param {number} [disabledHolidaysCount]  сколько авто-праздников пользователь
 *   отключил ПОШТУЧНО на той же панели. Внешний аудит починки (Medium,
 *   2026-08-03): мастер-переключатель знаменателю передали, а слой ниже — нет,
 *   и он остался инертным. `modeler.py` пропускает такие праздники поимённо
 *   (`if hcol in disabled_holidays: continue`), то есть состав модели меняется
 *   ровно так же, как от мастер-флага.
 * @returns {number} число параметров, которое модель заведёт на самом деле
 */
export function effectiveParamCount(detected, engine, nPredictorsOverride = null, useHolidays = true, disabledHolidaysCount = 0) {
  const nPredictors = Number(detected?.n_predictors ?? 0) || 0;
  const noHolidays = engine === 'ols' || useHolidays === false;
  const disabled = Math.max(Number(disabledHolidaysCount) || 0, 0);

  /**
   * Авто-праздники за вычетом отключённых поштучно, но не меньше нуля.
   * @param {number} base
   * @returns {number}
   */
  const autoHolidays = (base) => (noHolidays ? 0 : Math.max(base - disabled, 0));

  if (nPredictorsOverride != null && Number.isFinite(Number(nPredictorsOverride))) {
    const live = Number(nPredictorsOverride);
    const intercept = Number(detected?.n_intercept ?? 1) || 1;
    const holidays = autoHolidays(Number(detected?.n_holidays_auto ?? 12) || 0);
    return Math.max(live + holidays + intercept, 1);
  }

  // Поштучное отключение вычитается и из готового числа движка: оно посчитано
  // при валидации, когда список отключённых ещё не известен.
  if (!noHolidays && disabled > 0) {
    const fromBackendFull = Number(detected?.n_params_effective_bayesian ?? detected?.n_params_effective_pretrain);
    if (Number.isFinite(fromBackendFull) && fromBackendFull > 0) {
      const auto = Number(detected?.n_holidays_auto ?? 12) || 0;
      return Math.max(fromBackendFull - Math.min(disabled, auto), 1);
    }
  }

  // Праздники выключены мастер-флагом: готовое байесовское число из ответа
  // движка их уже включает, а OLS-число — нет и никогда не включало. Значит
  // при ВЫКЛ обе ветки сходятся к одному знаменателю «предикторы + свободный
  // член», и брать его надо из OLS-поля, а не вычитать из байесовского.
  const fromBackend = noHolidays
    ? detected?.n_params_effective_ols
    : (detected?.n_params_effective_bayesian ?? detected?.n_params_effective_pretrain);
  const parsed = Number(fromBackend);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  // Запасной путь для проектов, сохранённых до P0.3 (в ответе нет новых
  // полей): собираем по тем же правилам, что и движок. Праздников берём 12 —
  // семантический дедуп без списка колонок здесь не воспроизвести, поэтому
  // оценка консервативная (знаменатель не меньше фактического).
  const N_HOLIDAYS_DEFAULT = 12;
  const N_INTERCEPT = 1;
  return noHolidays
    ? nPredictors + N_INTERCEPT
    : nPredictors + N_HOLIDAYS_DEFAULT + N_INTERCEPT;
}

/**
 * Запас данных по эффективному знаменателю — то, что показывается и гейтится.
 *
 * @param {number} nObs      число наблюдений
 * @param {any} detected     блок `result.detected`
 * @param {'bayesian'|'ols'|string|null|undefined} engine
 * @param {number|null} [nPredictorsOverride]  см. effectiveParamCount
 * @param {boolean} [useHolidays]  см. effectiveParamCount
 * @param {number} [disabledHolidaysCount]  см. effectiveParamCount
 * @returns {number} наблюдений на фактический параметр, 0 если посчитать не из чего
 */
export function effectiveRatio(nObs, detected, engine, nPredictorsOverride = null, useHolidays = true, disabledHolidaysCount = 0) {
  const obs = Number(nObs) || 0;
  const params = effectiveParamCount(detected, engine, nPredictorsOverride, useHolidays, disabledHolidaysCount);
  if (obs <= 0 || params <= 0) return 0;
  return obs / params;
}

/**
 * 🔴 ЗАПАС ДАННЫХ ДЛЯ ГЕЙТА — то, чем блокируется работа, а не то, что показано.
 *
 * Решение владельца 2026-08-03 по Critical внешнего аудита: показ остаётся
 * эффективным (честное число параметров фактического режима), а жёсткая
 * блокировка кнопки «Подтвердить роли» считается по САМОМУ МЯГКОМУ
 * знаменателю — тому же, которым гейтит движок (`validator.py`: `ratio_gate`
 * по `n_params_effective_ols`).
 *
 * Зачем расходятся показ и гейт. Правка P0.3 перевела на эффективный
 * знаменатель и показ, и блокировку — а вместе с ней и порог. Проект с сырым
 * запасом 4,0 получал 1,7 и переставал проходить валидацию: действующий пилот
 * вставал на экране, который вчера пропускал его дальше. При этом «лекарство»
 * из текста блокировки (исключить малоактивные каналы) авто-часть знаменателя
 * не убирает вовсе — выхода у пользователя не оставалось.
 *
 * Почему именно OLS-знаменатель, а не сырой. Он ровно повторяет гейт движка:
 * фронт перестаёт быть строже расчёта, и «критически мало» на экране означает
 * то же, что «критически мало» в сообщениях движка — мало для ЛЮБОГО режима.
 * Сырой (obs / назначенные столбцы) завёл бы на фронте третью формулу, не
 * совпадающую ни с показом, ни с движком.
 *
 * @param {number} nObs      число наблюдений
 * @param {any} detected     блок `result.detected`
 * @param {number|null} [nPredictorsOverride]  живое число назначенных столбцов
 * @returns {number} запас данных по гейтовому знаменателю, 0 если не из чего считать
 */
export function gateRatio(nObs, detected, nPredictorsOverride = null) {
  // Режим передаётся жёстко 'ols': гейтовый знаменатель от выбора пользователя
  // не зависит по определению — это нижняя граница числа параметров.
  return effectiveRatio(nObs, detected, 'ols', nPredictorsOverride);
}
