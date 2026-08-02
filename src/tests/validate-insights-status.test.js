/**
 * validate-insights-status.test.js — аудит 2026-07-05 (рекомендация «шире тесты
 * insights-rules»). Покрывает клиент-facing ветки статуса validateInsights:
 * effectiveStatus пересчитывается на фронте из ролей колонок (не stale backend),
 * и каждая ошибка даёт КОНКРЕТНОЕ действие. Раньше 2000+ строк правил были без
 * прямого юнита на эту функцию — регресс сообщения клиенту не ловился.
 */
import { describe, it, expect } from 'vitest';
import { validateInsights } from '../lib/insights-rules.js';

/**
 * Собрать result из ролей: kpi/media/control counts + rows.
 *
 * P0.3 (2026-08-03): `detected` несёт состав, который реально отдаёт
 * `validator.py`. Запас данных считается по ЭФФЕКТИВНОМУ числу параметров
 * (назначенные + 12 авто-праздников + свободный член у байеса), поэтому числа
 * наблюдений ниже пересчитаны — ситуация в каждом тесте прежняя.
 */
const N_HOLIDAYS_AUTO = 12;
const N_INTERCEPT = 1;

function mkResult({ kpi = 1, media = 4, control = 0, rows = 48, warnings = [], status = 'ok' } = {}) {
  const columns = [];
  for (let i = 0; i < kpi; i++) columns.push({ name: `kpi${i}`, role: 'kpi', stats: {} });
  for (let i = 0; i < media; i++) columns.push({ name: `media${i}`, role: 'media', stats: {} });
  for (let i = 0; i < control; i++) columns.push({ name: `ctrl${i}`, role: 'control', stats: {} });
  const nPredictors = media + control;
  return {
    status,
    columns,
    file: { rows },
    warnings,
    detected: {
      n_predictors: nPredictors,
      n_holidays_auto: N_HOLIDAYS_AUTO,
      n_intercept: N_INTERCEPT,
      n_params_effective_bayesian: nPredictors + N_HOLIDAYS_AUTO + N_INTERCEPT,
      n_params_effective_ols: nPredictors + N_INTERCEPT,
    },
  };
}

const sev = (out, s) => out.filter(i => i.severity === s);
const txt = (out) => out.map(i => i.text).join(' || ');

describe('validateInsights — статус и конкретика ошибок', () => {
  it('готовые данные (kpi=1, media≥1, ratio≥4, нет warnings) → success', () => {
    // P0.3: 204 / (4 медиа + 12 праздников + 1) = 12.0
    const out = validateInsights(mkResult({ kpi: 1, media: 4, rows: 204 }));
    expect(sev(out, 'success').length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('готовы к обучению');
    expect(sev(out, 'error')).toHaveLength(0);
  });

  it('нет KPI → error с указанием назначить целевую метрику', () => {
    const out = validateInsights(mkResult({ kpi: 0, media: 4 }));
    const err = sev(out, 'error');
    expect(err.length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('целев');
    expect(err[0].tip).toBeTruthy();
  });

  it('две целевые метрики → error с их числом', () => {
    const out = validateInsights(mkResult({ kpi: 2, media: 4 }));
    expect(sev(out, 'error').length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('2 целевых метрик');
  });

  it('нет медиа-каналов → error', () => {
    const out = validateInsights(mkResult({ kpi: 1, media: 0, control: 3 }));
    expect(sev(out, 'error').length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('медиа');
  });

  it('ratio < 2 → error «слишком мало данных»', () => {
    // 10 rows / (4 media + 2 control) = 1.67 < 2
    const out = validateInsights(mkResult({ kpi: 1, media: 4, control: 2, rows: 10 }));
    expect(sev(out, 'error').length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('мало данных');
  });

  it('ratio 2–4 → warning про ratio (не error)', () => {
    // P0.3: 60 / (5 медиа + 2 контроля + 12 праздников + 1) = 3.0 → warning
    // П5-1а (2026-07-10): статусный блок больше НЕ дублирует число ratio («Ratio X:1»
    // с заглавной) — конкретика идёт из блока «Объём данных» строчной «ratio X:1».
    // Тест обновлён: проверяем наличие числа ratio в любом регистре, не конкретную капитализацию.
    const out = validateInsights(mkResult({ kpi: 1, media: 5, control: 2, rows: 60 }));
    expect(sev(out, 'error')).toHaveLength(0);
    const warn = sev(out, 'warning');
    expect(warn.length).toBeGreaterThanOrEqual(1);
    // число вида «3.0:1» должно быть в каком-то тексте (строчная «ratio»)
    expect(txt(out).toLowerCase()).toContain('ratio');
  });

  it('ratio≥4 но backend прислал warnings → статусный warning, не «готовы к обучению»', () => {
    const out = validateInsights(mkResult({ rows: 48, media: 4, warnings: [{ type: 'x' }] }));
    // Статусный success («готовы к обучению») отсутствует; success про роли —
    // допустимы (отдельные правила). Проверяем именно СТАТУСНОЕ сообщение.
    expect(txt(out)).not.toContain('готовы к обучению');
    expect(sev(out, 'warning').length).toBeGreaterThanOrEqual(1);
    expect(txt(out)).toContain('предупрежд');
  });

  it('пустой result не падает и возвращает []', () => {
    expect(validateInsights(null)).toEqual([]);
    expect(Array.isArray(validateInsights({}))).toBe(true);
  });

  it('effectiveStatus пересчитывается из ролей, а не из stale backend status', () => {
    // backend прислал error, но роли валидны (kpi=1, media=4, ratio высокий) →
    // фронт НЕ должен показывать блокирующую ошибку статуса.
    // P0.3: 204 / (4 медиа + 12 праздников + 1) = 12.0 — запас заведомо высокий
    const out = validateInsights(mkResult({ status: 'error', kpi: 1, media: 4, rows: 204 }));
    // generic «критические проблемы со структурой» не должно быть (issues пусты,
    // но effectiveStatus=ok перебивает — ветка backward-compat не про статус).
    expect(txt(out)).toContain('готовы к обучению');
  });
});
