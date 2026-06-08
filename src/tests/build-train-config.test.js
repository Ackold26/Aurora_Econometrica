/**
 * buildTrainConfig — verbatim-порт inline-сборки ConfigPanel.svelte:336-365
 * (extract 2026-06-06, enabler для synthetic-truth).
 *
 * Этот тест = БАЙТ-В-БАЙТ спецификация выхода (golden выведен вручную из inline-логики)
 * + покрытие всех условных веток (mcmc_override, kpi_unit_cost, дефолты `|| ...`).
 * Цель: не дать extract'у тихо разойтись с inline (другой дефолт / порядок / оператор →
 * ДРУГАЯ модель на обучении → synthetic-truth ложно обвинит движок в баге extract'а).
 * Второй адверсариальный слой (live-дифф против inline на реальном проекте) — гейт
 * ПЕРЕД первым train через эту функцию (synthetic-truth блок).
 */
import { describe, it, expect } from 'vitest';
import { buildTrainConfig } from '$lib/train-config.js';

/**
 * Полностью заполненный реалистичный снимок (OTC-подобный, bayesian + advanced + count KPI).
 * Каждое поле осмысленно дёргает соответствующую ветку сборки.
 * @param {Record<string, any>} [overrides]
 */
function baseState(overrides = {}) {
  return {
    projectDir: 'C:\\proj\\otc',
    dataFile: 'data.xlsx',
    kpiColumn: 'sales_units',
    mediaColumns: ['tv', 'digital'],
    controlColumns: ['competitor_spend', 'price'],
    dateColumn: 'week',
    channelAdstock: { tv: 'weibull' }, // digital отсутствует → дефолт 'geometric'
    engine: 'bayesian',
    showAdvanced: true,
    mcmcChains: 4,
    mcmcDraws: 2000,
    mcmcTune: 2000,
    unitCosts: { tv: 5000, digital: 1200 },
    kpiType: 'sales',
    valuePerCountUnit: 150,
    kpiKind: 'count',
    mergeRules: { tv: ['tv_fed', 'tv_reg'] },
    channelCategories: { tv: 'brand', digital: 'performance' },
    disabledHolidays: ['holiday_defender_day', 'holiday_russia_day'],
    ...overrides,
  };
}

describe('buildTrainConfig — байт-в-байт спецификация (golden)', () => {
  it('полный снимок: bayesian + advanced + count KPI → точная shape config', () => {
    const config = buildTrainConfig(baseState());
    // Golden выведен ВРУЧНУЮ из inline ConfigPanel.svelte:336-365.
    expect(config).toEqual({
      project_dir: 'C:\\proj\\otc',
      data_file: 'data.xlsx',
      kpi_column: 'sales_units',
      media_columns: ['tv', 'digital'],
      control_columns: ['competitor_spend', 'price'],
      date_column: 'week',
      adstock_config: { tv: 'weibull', digital: 'geometric' },
      mcmc_override: { chains: 4, draws: 2000, tune: 2000 },
      unit_costs: { tv: 5000, digital: 1200 },
      kpi_type: 'sales',
      kpi_unit_cost: 150,
      merge_rules: { tv: ['tv_fed', 'tv_reg'] },
      mode: 'bayesian',
      channel_categories: { tv: 'brand', digital: 'performance' },
      disabled_holidays: ['holiday_defender_day', 'holiday_russia_day'],
    });
  });

  it('порядок ключей идентичен inline (контракт TrainStartRequest)', () => {
    const config = buildTrainConfig(baseState());
    expect(Object.keys(config)).toEqual([
      'project_dir',
      'data_file',
      'kpi_column',
      'media_columns',
      'control_columns',
      'date_column',
      'adstock_config',
      'mcmc_override',
      'unit_costs',
      'kpi_type',
      'kpi_unit_cost',
      'merge_rules',
      'mode',
      'channel_categories',
      'disabled_holidays',
    ]);
  });

  it('дефолты при пустых/отсутствующих входах (|| {} / || sales / || date / || geometric)', () => {
    const config = buildTrainConfig({
      projectDir: 'p',
      dataFile: 'd',
      kpiColumn: 'k',
      mediaColumns: ['radio'],
      controlColumns: [],
      dateColumn: undefined,
      channelAdstock: {},
      engine: 'bayesian',
      showAdvanced: false,
      mcmcChains: 4,
      mcmcDraws: 2000,
      mcmcTune: 2000,
      unitCosts: undefined,
      kpiType: undefined,
      valuePerCountUnit: undefined,
      kpiKind: 'monetary',
      mergeRules: {},
      channelCategories: undefined,
      disabledHolidays: undefined,
    });
    expect(config).toEqual({
      project_dir: 'p',
      data_file: 'd',
      kpi_column: 'k',
      media_columns: ['radio'],
      control_columns: [],
      date_column: 'date', // dateColumn undefined → 'date'
      adstock_config: { radio: 'geometric' }, // отсутствует в channelAdstock → дефолт
      mcmc_override: null, // showAdvanced=false → null
      unit_costs: {}, // undefined → {}
      kpi_type: 'sales', // undefined → 'sales'
      kpi_unit_cost: null, // kpiKind !== 'count' → null
      merge_rules: {},
      mode: 'bayesian',
      channel_categories: {}, // undefined → {}
      disabled_holidays: [], // undefined → []
    });
  });
});

describe('buildTrainConfig — mcmc_override ветки', () => {
  it('bayesian + showAdvanced → объект из mcmc-параметров', () => {
    const config = buildTrainConfig(baseState({ engine: 'bayesian', showAdvanced: true, mcmcChains: 2, mcmcDraws: 500, mcmcTune: 800 }));
    expect(config.mcmc_override).toEqual({ chains: 2, draws: 500, tune: 800 });
  });

  it('bayesian + !showAdvanced → null', () => {
    const config = buildTrainConfig(baseState({ engine: 'bayesian', showAdvanced: false }));
    expect(config.mcmc_override).toBeNull();
  });

  it('ols (даже с showAdvanced) → null + mode=ols', () => {
    const config = buildTrainConfig(baseState({ engine: 'ols', showAdvanced: true }));
    expect(config.mcmc_override).toBeNull();
    expect(config.mode).toBe('ols');
  });
});

describe('buildTrainConfig — kpi_unit_cost ветки (count KPI)', () => {
  it('count + положительное число → значение', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'count', valuePerCountUnit: 42 })).kpi_unit_cost).toBe(42);
  });

  it('count + 0 → null', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'count', valuePerCountUnit: 0 })).kpi_unit_cost).toBeNull();
  });

  it('count + отрицательное → null', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'count', valuePerCountUnit: -5 })).kpi_unit_cost).toBeNull();
  });

  it('count + null → null', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'count', valuePerCountUnit: null })).kpi_unit_cost).toBeNull();
  });

  it('count + NaN → null (typeof number, но не > 0)', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'count', valuePerCountUnit: NaN })).kpi_unit_cost).toBeNull();
  });

  it('monetary (не count) + валидное значение → null', () => {
    expect(buildTrainConfig(baseState({ kpiKind: 'monetary', valuePerCountUnit: 150 })).kpi_unit_cost).toBeNull();
  });
});

describe('buildTrainConfig — adstock_config', () => {
  it('каждый media-канал получает свой adstock или geometric-дефолт', () => {
    const config = buildTrainConfig(baseState({
      mediaColumns: ['tv', 'ooh', 'digital'],
      channelAdstock: { tv: 'weibull', digital: 'geometric' }, // ooh отсутствует
    }));
    expect(config.adstock_config).toEqual({ tv: 'weibull', ooh: 'geometric', digital: 'geometric' });
  });

  it('пустой список каналов → пустой adstock_config + пустой media_columns', () => {
    const config = buildTrainConfig(baseState({ mediaColumns: [] }));
    expect(config.adstock_config).toEqual({});
    expect(config.media_columns).toEqual([]);
  });
});
