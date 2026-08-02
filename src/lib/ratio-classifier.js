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
 * @param {any} detected  блок `result.detected` из ответа /compute/validate
 * @param {'bayesian'|'ols'|string|null|undefined} engine  текущий режим
 * @param {number|null} [nPredictorsOverride]  актуальное число назначенных
 *   столбцов, когда пользователь меняет роли на лету и число из ответа движка
 *   уже устарело. Авто-часть (праздники, свободный член) берётся из ответа —
 *   она от ролей не зависит.
 * @returns {number} число параметров, которое модель заведёт на самом деле
 */
export function effectiveParamCount(detected, engine, nPredictorsOverride = null) {
  const nPredictors = Number(detected?.n_predictors ?? 0) || 0;
  const isOls = engine === 'ols';

  if (nPredictorsOverride != null && Number.isFinite(Number(nPredictorsOverride))) {
    const live = Number(nPredictorsOverride);
    const intercept = Number(detected?.n_intercept ?? 1) || 1;
    const holidays = isOls ? 0 : (Number(detected?.n_holidays_auto ?? 12) || 0);
    return Math.max(live + holidays + intercept, 1);
  }

  const fromBackend = isOls
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
  return isOls
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
 * @returns {number} наблюдений на фактический параметр, 0 если посчитать не из чего
 */
export function effectiveRatio(nObs, detected, engine, nPredictorsOverride = null) {
  const obs = Number(nObs) || 0;
  const params = effectiveParamCount(detected, engine, nPredictorsOverride);
  if (obs <= 0 || params <= 0) return 0;
  return obs / params;
}
