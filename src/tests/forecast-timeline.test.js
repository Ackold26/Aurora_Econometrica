/**
 * forecast-timeline.test.js — сборка таймлайна "история-fit + прогнозные хвосты".
 * Зеркалит инварианты, доказанные probe `tools/probe_forecast_scenarios_kagocel.py`.
 */
import { describe, it, expect } from 'vitest';
import {
  nextMonths,
  buildBaselineFromDiagnostics,
  buildScenarioTails,
  assembleScenarioTimeline,
} from '../lib/forecast-timeline.js';

describe('nextMonths', () => {
  it('продолжает помесячно, без дубля последней даты, строго возрастает', () => {
    const out = nextMonths('2025-07-01', 5);
    expect(out).toEqual(['2025-08-01', '2025-09-01', '2025-10-01', '2025-11-01', '2025-12-01']);
    expect(out).not.toContain('2025-07-01');
    for (let i = 1; i < out.length; i++) expect(out[i] > out[i - 1]).toBe(true);
  });

  it('переносит год через декабрь', () => {
    expect(nextMonths('2025-11-01', 3)).toEqual(['2025-12-01', '2026-01-01', '2026-02-01']);
  });

  it('сохраняет формат YYYY-MM', () => {
    expect(nextMonths('2025-12', 2)).toEqual(['2026-01', '2026-02']);
  });

  it('возвращает [] на пустой/невалидный вход или n<=0', () => {
    expect(nextMonths('', 5)).toEqual([]);
    expect(nextMonths('not-a-date', 5)).toEqual([]);
    expect(nextMonths('2025-07-01', 0)).toEqual([]);
    expect(nextMonths('2025-07-01', -3)).toEqual([]);
  });
});

describe('buildBaselineFromDiagnostics', () => {
  it('строит baseline из actual_vs_predicted.predicted (fit-линия)', () => {
    const diag = {
      actual_vs_predicted: {
        dates: ['2025-01-01', '2025-02-01'],
        actual: [100, 110],
        predicted: [101, 109],
      },
    };
    const b = buildBaselineFromDiagnostics(diag);
    expect(b).not.toBeNull();
    expect(b.dates).toEqual(['2025-01-01', '2025-02-01']);
    expect(b.predictions).toEqual([101, 109]); // fit, НЕ actual
  });

  it('null когда диагностики нет', () => {
    expect(buildBaselineFromDiagnostics(null)).toBeNull();
    expect(buildBaselineFromDiagnostics({})).toBeNull();
    expect(buildBaselineFromDiagnostics({ actual_vs_predicted: { dates: [], predicted: [] } })).toBeNull();
  });

  it('обрезает до min(dates, predicted)', () => {
    const b = buildBaselineFromDiagnostics({
      actual_vs_predicted: { dates: ['a', 'b', 'c'], predicted: [1, 2] },
    });
    expect(b.dates).toEqual(['a', 'b']);
    expect(b.predictions).toEqual([1, 2]);
  });
});

describe('buildScenarioTails', () => {
  const compareResult = {
    status: 'ok',
    money_mode: true,
    comparison: { kpi_money_mode: true },
    scenarios: [
      {
        scenario_name: 'Базовый',
        n_periods: 3,
        predictions: [300, 310, 320],
        predictions_ci_low: [280, 290, 300],
        predictions_ci_high: [320, 330, 340],
        forecast_periods: 12,
        forecast_period_label: '2026 год',
        totals: {
          total_spend: 1000, total_spend_money: 5000,
          predicted_kpi: 930, predicted_kpi_money: 46500,
          predicted_kpi_ci_low: 900, predicted_kpi_ci_high: 960,
        },
        per_channel_spend: { native: { TV: 500 }, money: { TV: 2500 } },
      },
    ],
  };

  it('продолжает даты от истории и маппит per-period кривую + CI-веер', () => {
    const tails = buildScenarioTails(compareResult, '2025-07-01');
    expect(tails).toHaveLength(1);
    const t = tails[0];
    expect(t.dates).toEqual(['2025-08-01', '2025-09-01', '2025-10-01']);
    expect(t.predictions).toEqual([300, 310, 320]);
    expect(t.ciLowSeries).toEqual([280, 290, 300]);
    expect(t.ciHighSeries).toEqual([320, 330, 340]);
  });

  it('money-единицы когда глобальные флаги money_mode/kpi_money_mode = true', () => {
    const t = buildScenarioTails(compareResult, '2025-07-01')[0];
    expect(t.budget).toBe(5000);
    expect(t.predictedKpi).toBe(46500);
    expect(t.perChannelAllocation).toEqual({ TV: 2500 });
  });

  it('A1 (INV-50): глобальный money_mode=false → ВСЕ сценарии native, без смешения единиц', () => {
    // Реальный кейс Кагоцела: «ноль активности» обнуляет has_money глобально,
    // но у покрытых сценариев есть total_spend_money — per-field fallback смешал бы.
    const mixed = {
      status: 'ok',
      money_mode: false,                       // has_money глобально false
      comparison: { kpi_money_mode: false },
      scenarios: [
        { scenario_name: 'A', n_periods: 1, predictions: [300],
          totals: { total_spend: 36, total_spend_money: 378, predicted_kpi: 1000, predicted_kpi_money: 1000 },
          per_channel_spend: { native: {}, money: {} } },
        { scenario_name: 'C-ноль', n_periods: 1, predictions: [286],
          totals: { total_spend: 0, total_spend_money: null, predicted_kpi: 800, predicted_kpi_money: 800 },
          per_channel_spend: { native: {}, money: null } },
      ],
    };
    const tails = buildScenarioTails(mixed, '2025-07-01');
    // ОБА в native: A=36 (НЕ 378 money), C=0 — сопоставимо под одним заголовком
    expect(tails[0].budget).toBe(36);
    expect(tails[1].budget).toBe(0);
  });

  it('C1: band отдаётся ТОЛЬКО при совпадении длины с кривой (иначе undefined, без обрыва ленты)', () => {
    const badBand = {
      money_mode: false,
      scenarios: [{
        scenario_name: 'corrupt', n_periods: 3, predictions: [1, 2, 3],
        predictions_ci_low: [1, 2], predictions_ci_high: [3, 4], // длина 2 != 3
        totals: { total_spend: 1, predicted_kpi: 6 },
        per_channel_spend: { native: {}, money: null },
      }],
    };
    const t = buildScenarioTails(badBand, '2025-07-01')[0];
    expect(t.ciLowSeries).toBeUndefined();
    expect(t.ciHighSeries).toBeUndefined();
    // даты ведутся от длины кривой (3), не от потенциально расходящегося n_periods
    expect(t.dates).toHaveLength(3);
  });

  it('B1: forecast_periods/label проброшены (horizon-контекст)', () => {
    const t = buildScenarioTails(compareResult, '2025-07-01')[0];
    expect(t.forecastPeriods).toBe(12);
    expect(t.forecastPeriodLabel).toBe('2026 год');
  });

  it('graceful: старый сценарий без per-period band → ciLowSeries undefined (chart рисует линию без ленты)', () => {
    const legacy = {
      scenarios: [{
        scenario_name: 'Старый', n_periods: 2, predictions: [10, 20],
        totals: { total_spend: 1, predicted_kpi: 30 },
        per_channel_spend: { native: {}, money: null },
      }],
    };
    const t = buildScenarioTails(legacy, '2025-07-01')[0];
    expect(t.ciLowSeries).toBeUndefined();
    expect(t.ciHighSeries).toBeUndefined();
    expect(t.budget).toBe(1); // fallback к native когда money нет
    expect(t.predictedKpi).toBe(30);
  });

  it('пустой/без сценариев → []', () => {
    expect(buildScenarioTails(null, '2025-07-01')).toEqual([]);
    expect(buildScenarioTails({ scenarios: [] }, '2025-07-01')).toEqual([]);
  });

  it('без истории (lastHistDate=null) → даты хвоста пусты, кривая сохранена', () => {
    const t = buildScenarioTails(compareResult, null)[0];
    expect(t.dates).toEqual([]);
    expect(t.predictions).toEqual([300, 310, 320]);
  });
});

describe('assembleScenarioTimeline (интеграция: шов история↔прогноз)', () => {
  it('прогнозные даты начинаются СРАЗУ после последней даты истории (непрерывный шов)', () => {
    const diag = {
      actual_vs_predicted: {
        dates: ['2025-05-01', '2025-06-01', '2025-07-01'],
        actual: [150, 160, 177],
        predicted: [155, 162, 175],
      },
    };
    const compareResult = {
      scenarios: [{
        scenario_name: 'S1', n_periods: 2, predictions: [200, 210],
        predictions_ci_low: [190, 195], predictions_ci_high: [210, 225],
        totals: { total_spend: 1, predicted_kpi: 410 },
        per_channel_spend: { native: {}, money: null },
      }],
    };
    const { baseline, scenarios } = assembleScenarioTimeline(compareResult, diag);
    expect(baseline.predictions).toEqual([155, 162, 175]);
    const combined = [...baseline.dates, ...scenarios[0].dates];
    expect(combined).toEqual(['2025-05-01', '2025-06-01', '2025-07-01', '2025-08-01', '2025-09-01']);
    // нет дублей, строго возрастает (непрерывность таймлайна)
    expect(new Set(combined).size).toBe(combined.length);
    for (let i = 1; i < combined.length; i++) expect(combined[i] > combined[i - 1]).toBe(true);
  });

  it('без модели → baseline null, scenarios без дат, но не падает', () => {
    const { baseline, scenarios } = assembleScenarioTimeline(
      { scenarios: [{ scenario_name: 'X', predictions: [1], totals: {}, per_channel_spend: {} }] },
      null,
    );
    expect(baseline).toBeNull();
    expect(scenarios[0].dates).toEqual([]);
  });
});
