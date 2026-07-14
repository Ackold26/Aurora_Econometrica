/**
 * forecast-timeline.js — сборка единого таймлайна «история (model fit) + N прогнозных
 * хвостов сценариев» для MultiScenarioChart / MultiScenarioPage из вывода движка.
 *
 * Источники доказаны probe `tools/probe_forecast_scenarios_kagocel.py` (Кагоцел 0706):
 *  - baseline-история = `modelData.diagnostics.actual_vs_predicted` → линия `predicted`
 *    (model fit, сглажена; непрерывно стыкуется с прогнозом). НЕ Σ decomposition_series
 *    (расходится с fit на ~20% из-за signed-факторов); НЕ `time_series.kpi_values`
 *    (такого ключа нет — ошибка инвентаризации, опровергнута probe).
 *  - прогнозные хвосты = `econ_compare().scenarios[]` → per-period `predictions` +
 *    per-period CI-веер `predictions_ci_low` / `predictions_ci_high` (из predict_scenario).
 *  - прогнозные даты = продолжение помесячно от последней даты истории.
 *
 * INV-50: CI-веер берётся ИЗ движка (единый источник HDI), не пересчитывается на фронте.
 * Pure-функции (без invoke/store) — тестируемы изолированно.
 */

/**
 * Продолжить помесячный таймлайн на `n` точек вперёд от `lastDate`.
 * Сохраняет формат входа: 'YYYY-MM' → 'YYYY-MM'; 'YYYY-MM-DD' → 'YYYY-MM-01'
 * (помесячные данные MMM = первое число месяца). Корректно переносит год.
 *
 * @param {string} lastDate последняя дата истории
 * @param {number} n число прогнозных периодов
 * @returns {string[]} массив дат-продолжений (строго возрастает, без дубля lastDate)
 */
export function nextMonths(lastDate, n) {
  const s = String(lastDate ?? '');
  const m = s.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  if (!m || !Number.isFinite(n) || n <= 0) return [];
  let year = Number(m[1]);
  let month = Number(m[2]); // 1..12
  const day = m[3] ?? null; // сохраняем день истории для формат-консистентности оси
  /** @type {string[]} */
  const out = [];
  for (let i = 0; i < n; i++) {
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
    const mm = String(month).padStart(2, '0');
    out.push(day ? `${year}-${mm}-${day}` : `${year}-${mm}`);
  }
  return out;
}

/**
 * Достать baseline-историю (model fit) из диагностики модели.
 * @param {any} modelDiagnostics значение `modelData.diagnostics`
 * @returns {{ id: string, name: string, dates: string[], predictions: number[] } | null}
 */
export function buildBaselineFromDiagnostics(modelDiagnostics) {
  const avp = modelDiagnostics?.actual_vs_predicted ?? null;
  const dates = Array.isArray(avp?.dates) ? avp.dates : [];
  const fit = Array.isArray(avp?.predicted) ? avp.predicted : [];
  if (dates.length === 0 || fit.length === 0) return null;
  const n = Math.min(dates.length, fit.length);
  return {
    id: 'baseline',
    name: 'История (модель)',
    dates: dates.slice(0, n),
    predictions: fit.slice(0, n),
  };
}

/**
 * Собрать массив сценариев-хвостов из результата `econ_compare` в форму, которую
 * ждёт MultiScenarioChart (dates продолжают историю вперёд; CI-веер из движка,
 * graceful null для старых сценариев без per-period band).
 *
 * Единицы (money/native) выбираются ГЛОБАЛЬНО по флагам compare_scenarios, НЕ
 * per-scenario fallback (INV-50): иначе непокрытый unit_costs сценарий показал бы
 * native, а покрытый — money, под одним заголовком таблицы = несопоставимо.
 *
 * Семантика дат: хвост кладётся ВПЕРЁД от конца истории — это forward-прогноз
 * (deliverable «Прогноз продаж по сценариям»). Ретроспективный what-if на
 * тренировочном горизонте — отдельный компонент ScenarioCompare, не эта страница.
 *
 * @param {any} compareResult ответ `invoke('econ_compare')`
 * @param {string|null} lastHistDate последняя дата истории (для продолжения вперёд)
 * @returns {Array<object>} scenarios для MultiScenarioPage/Chart
 */
export function buildScenarioTails(compareResult, lastHistDate) {
  const raw = Array.isArray(compareResult?.scenarios) ? compareResult.scenarios : [];
  // has_money / kpi_money_mode = ALL-or-nothing (compare_scenarios). Решают единицы для ВСЕХ.
  const moneyMode = Boolean(compareResult?.money_mode);
  const kpiMoneyMode = Boolean(compareResult?.comparison?.kpi_money_mode);
  return raw.map((/** @type {any} */ sc, /** @type {number} */ idx) => {
    const totals = sc?.totals ?? {};
    const predictions = Array.isArray(sc?.predictions) ? sc.predictions : [];
    // Даты ведём от ДЛИНЫ кривой (не от отдельного поля n_periods) → гарантирует
    // dates.length == predictions.length (иначе alignToTimeline молча гэпует ленту).
    const horizon = predictions.length;
    const dates = lastHistDate && horizon > 0 ? nextMonths(lastHistDate, horizon) : [];
    // CI-веер только если длина ОБОИХ массивов == длине кривой (иначе обрыв ленты).
    const rawLow = sc?.predictions_ci_low;
    const rawHigh = sc?.predictions_ci_high;
    const bandOk = Array.isArray(rawLow) && Array.isArray(rawHigh)
      && rawLow.length === horizon && rawHigh.length === horizon;
    // Band-массивы есть, но длина не совпала с кривой → лента дропается (graceful), но это
    // СИГНАЛ бага движка (band должен строиться по тем же n_periods) — не прятать молча.
    if (!bandOk && (Array.isArray(rawLow) || Array.isArray(rawHigh))) {
      console.warn(
        `[forecast-timeline] CI-веер «${sc?.scenario_name}» отброшен: длина band `
        + `(${rawLow?.length}/${rawHigh?.length}) != кривой (${horizon}). Проверь scenario.py.`,
      );
    }
    const perChannel = sc?.per_channel_spend?.money ?? sc?.per_channel_spend?.native ?? {};
    return {
      id: `sc-${idx}-${sc?.scenario_name ?? idx}`,
      name: sc?.scenario_name ?? `Сценарий ${idx + 1}`,
      budget: moneyMode ? (totals.total_spend_money ?? 0) : (totals.total_spend ?? 0),
      predictedKpi: kpiMoneyMode
        ? (totals.predicted_kpi_money ?? totals.predicted_kpi ?? 0)
        : (totals.predicted_kpi ?? 0),
      ciLow: totals.predicted_kpi_ci_low ?? undefined,
      ciHigh: totals.predicted_kpi_ci_high ?? undefined,
      dates,
      predictions,
      ciLowSeries: bandOk ? rawLow : undefined,
      ciHighSeries: bandOk ? rawHigh : undefined,
      perChannelAllocation: perChannel,
      // Horizon-контекст (планировочный горизонт сценария, если был задан planning-mode).
      forecastPeriods: sc?.forecast_periods ?? null,
      forecastPeriodLabel: sc?.forecast_period_label ?? null,
      // A3/OPP-03 (2026-07-03): маркер экстраполяции пишется движком в
      // scenario-JSON (F-04), но этот маппер его резал — compare-страница
      // молчала о выходе плана за наблюдавшийся диапазон.
      extrapolation: sc?.extrapolation ?? null,
    };
  });
}

/**
 * Полная сборка: baseline (история-fit) + scenarios (прогнозные хвосты) на едином таймлайне.
 *
 * @param {any} compareResult ответ `invoke('econ_compare')`
 * @param {any} modelDiagnostics значение `modelData.diagnostics`
 * @returns {{ scenarios: Array<object>, baseline: object | null }}
 */
export function assembleScenarioTimeline(compareResult, modelDiagnostics) {
  const baseline = buildBaselineFromDiagnostics(modelDiagnostics);
  const lastHistDate = baseline ? baseline.dates[baseline.dates.length - 1] : null;
  const scenarios = buildScenarioTails(compareResult, lastHistDate);
  return { scenarios, baseline };
}
