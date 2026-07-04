/**
 * П1-ядро (волна UXP, 2026-07-03): buildExpressPlan — гейты экспресс-
 * подтверждения Валидации. Безопасность выше охвата: любое сомнение →
 * eligible=false со внятной причиной (штатный путь под-шагов).
 */
import { describe, it, expect } from 'vitest';
import { buildExpressPlan } from '$lib/express-validate.js';

const CLEAN_RESULT = {
  status: 'ok',
  columns: [
    { name: 'Date', role: 'date' },
    { name: 'Продажи в руб', role: 'kpi' },
    { name: 'OLV Бюджет', role: 'media' },
    { name: 'Banners Бюджет', role: 'media' },
    { name: 'Social Бюджет', role: 'media' },
  ],
};

function plan(overrides = {}) {
  return buildExpressPlan({
    validateResult: CLEAN_RESULT,
    currentKPI: 'sales',
    kpiUnavailable: false,
    kpiKind: 'monetary',
    ...overrides,
  });
}

describe('buildExpressPlan — happy-path', () => {
  it('чистые данные + денежный KPI + рублёвые каналы → eligible с планом', () => {
    const p = plan();
    expect(p.eligible).toBe(true);
    expect(p.kpiLabel).toBe('Выручка');
    expect(p.mediaChannels).toEqual(['OLV Бюджет', 'Banners Бюджет', 'Social Бюджет']);
    expect(p.uniform).toEqual({
      'OLV Бюджет': 'monetary',
      'Banners Бюджет': 'monetary',
      'Social Бюджет': 'monetary',
    });
  });

  it('profit тоже денежный — ярлык «Прибыль»', () => {
    const p = plan({ currentKPI: 'profit' });
    expect(p.eligible).toBe(true);
    expect(p.kpiLabel).toBe('Прибыль');
  });
});

describe('buildExpressPlan — гейты (любое сомнение → штатный путь)', () => {
  it('нет результата валидации → не предлагаем', () => {
    const p = plan({ validateResult: null });
    expect(p.eligible).toBe(false);
    expect(p.reason).toMatch(/нет результата/);
  });

  it('валидация со status=error (грязные данные) → штатный путь', () => {
    const p = plan({ validateResult: { ...CLEAN_RESULT, status: 'error' } });
    expect(p.eligible).toBe(false);
    expect(p.reason).toMatch(/критичные проблемы/);
  });

  it('KPI недоступен по данным (UX-2) → штатный путь', () => {
    const p = plan({ kpiUnavailable: true });
    expect(p.eligible).toBe(false);
  });

  it('count-KPI (нужна цена единицы) → штатный путь', () => {
    const p = plan({ currentKPI: 'leads', kpiKind: 'count' });
    expect(p.eligible).toBe(false);
    expect(p.reason).toMatch(/цену единицы/);
  });

  it('ПАРА spend+TRP НЕ блокирует: uniform по ₽, физ-половина в disable', () => {
    const paired = {
      status: 'ok',
      columns: [
        ...CLEAN_RESULT.columns,
        { name: 'tv_spend', role: 'media' },
        { name: 'tv_trp', role: 'media' },
      ],
    };
    const p = plan({ validateResult: paired });
    expect(p.eligible).toBe(true);
    expect(p.uniform['tv_spend']).toBe('monetary');
    expect(p.uniform['tv_trp']).toBeUndefined();
    expect(p.disable).toContain('tv_trp');
  });

  it('физический канал (TRP) по эвристике имени → штатный путь', () => {
    const withTrp = {
      status: 'ok',
      columns: [
        ...CLEAN_RESULT.columns,
        { name: 'TRPs бренд (W 25-54)', role: 'media' },
      ],
    };
    const p = plan({ validateResult: withTrp });
    expect(p.eligible).toBe(false);
    expect(p.reason).toMatch(/физических единицах/);
    expect(p.reason).toContain('TRPs бренд');
  });

  it('внешний классификатор каналов имеет приоритет над эвристикой', () => {
    const p = plan({ isPhysicalChannel: (name) => name === 'Social Бюджет' });
    expect(p.eligible).toBe(false);
    expect(p.reason).toContain('Social Бюджет');
  });

  it('меньше двух медиа-каналов → штатный путь', () => {
    const single = {
      status: 'ok',
      columns: [
        { name: 'Продажи', role: 'kpi' },
        { name: 'ТВ', role: 'media' },
      ],
    };
    const p = plan({ validateResult: single });
    expect(p.eligible).toBe(false);
    expect(p.reason).toMatch(/меньше двух/);
  });
});
