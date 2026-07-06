/**
 * channel-pairs.test.js — пары «бюджет ₽ + Media KPI» (решение Антона 2026-07-05).
 * Контракты: группировка колонок в каналы по базе имени; развязка выбора в
 * per-колоночный план (выбранная сторона on, парная альтернатива off).
 */
import { describe, it, expect } from 'vitest';
import {
  parseChannelMetric,
  groupChannelColumns,
  resolvePairSelection,
  declaredPairKeys,
  isDeclaredPair,
} from '../lib/channel-pairs.js';

describe('parseChannelMetric', () => {
  it('распознаёт денежные и физические суффиксы, срезая базу', () => {
    expect(parseChannelMetric('tv_spend')).toEqual({ base: 'tv', metric: 'monetary' });
    expect(parseChannelMetric('tv_trp')).toEqual({ base: 'tv', metric: 'physical' });
    expect(parseChannelMetric('tv_grp')).toEqual({ base: 'tv', metric: 'physical' });
    expect(parseChannelMetric('digital_impressions')).toEqual({ base: 'digital', metric: 'physical' });
    expect(parseChannelMetric('retail_media_spend')).toEqual({ base: 'retail_media', metric: 'monetary' });
    expect(parseChannelMetric('performance_clicks')).toEqual({ base: 'performance', metric: 'physical' });
    expect(parseChannelMetric('apteka_contacts')).toEqual({ base: 'apteka', metric: 'physical' });
  });
  it('колонка без суффикса — самостоятельный канал без метрики', () => {
    expect(parseChannelMetric('TV федеральное')).toEqual({ base: 'TV федеральное', metric: null });
  });
  it('русские маркеры', () => {
    expect(parseChannelMetric('ТВ бюджет')).toEqual({ base: 'ТВ', metric: 'monetary' });
    expect(parseChannelMetric('ООН показы')).toEqual({ base: 'ООН', metric: 'physical' });
  });
});

describe('groupChannelColumns', () => {
  const cols = [
    'tv_spend', 'tv_trp',
    'digital_spend', 'digital_impressions',
    'ooh_spend', 'ooh_contacts',
    'performance_spend', 'performance_clicks',
  ];
  it('пары синтетических примеров группируются в 4 канала', () => {
    const { channels, byChannel } = groupChannelColumns(cols);
    expect(channels).toEqual(['tv', 'digital', 'ooh', 'performance']);
    expect(byChannel['tv']).toEqual({ monetary: ['tv_spend'], physical: ['tv_trp'] });
    expect(byChannel['performance']).toEqual({
      monetary: ['performance_spend'], physical: ['performance_clicks'],
    });
  });
  it('одиночная колонка — канал с одной стороной (metric=null → monetary)', () => {
    // «Бюджет» в середине имени (хвост «ДО НДС») — канал остаётся полным именем:
    // денежная колонка без физического парника, парного поведения нет.
    const { channels, byChannel } = groupChannelColumns(['OLV Бюджет ДО НДС', 'Статьи']);
    expect(channels).toEqual(['OLV Бюджет ДО НДС', 'Статьи']);
    expect(byChannel['OLV Бюджет ДО НДС'].monetary).toEqual(['OLV Бюджет ДО НДС']);
    expect(byChannel['Статьи']).toEqual({ monetary: ['Статьи'], physical: [] });
  });
  it('пустой вход', () => {
    expect(groupChannelColumns([])).toEqual({ channels: [], byChannel: {} });
  });
});

describe('resolvePairSelection', () => {
  const { byChannel } = groupChannelColumns([
    'tv_spend', 'tv_trp', 'digital_spend', 'digital_impressions', 'Статьи',
  ]);

  it('ROI-выбор: spend on со своей метрикой, физ-половина off', () => {
    const { perColumn, enable, disable } = resolvePairSelection(byChannel, {
      tv: 'monetary', digital: 'monetary', 'Статьи': 'monetary',
    });
    expect(perColumn).toEqual({
      tv_spend: 'monetary', digital_spend: 'monetary', 'Статьи': 'monetary',
    });
    expect(enable.sort()).toEqual(['digital_spend', 'tv_spend', 'Статьи'].sort());
    expect(disable.sort()).toEqual(['digital_impressions', 'tv_trp'].sort());
  });

  it('Эффективность: физ on, spend off; одиночный канал остаётся своей стороной', () => {
    const { perColumn, disable } = resolvePairSelection(byChannel, {
      tv: 'physical', digital: 'physical', 'Статьи': 'physical',
    });
    expect(perColumn['tv_trp']).toBe('physical');
    expect(perColumn['digital_impressions']).toBe('physical');
    // у «Статьи» физической стороны нет → включается денежная (единственная)
    expect(perColumn['Статьи']).toBe('monetary');
    expect(disable.sort()).toEqual(['digital_spend', 'tv_spend'].sort());
  });

  it('смешанный выбор per каналу', () => {
    const { perColumn, disable } = resolvePairSelection(byChannel, {
      tv: 'monetary', digital: 'physical',
    });
    expect(perColumn['tv_spend']).toBe('monetary');
    expect(perColumn['digital_impressions']).toBe('physical');
    expect(disable).toContain('tv_trp');
    expect(disable).toContain('digital_spend');
  });

  it('дефолт без выбора — деньги, если есть', () => {
    const { perColumn } = resolvePairSelection(byChannel, {});
    expect(perColumn['tv_spend']).toBe('monetary');
    expect(perColumn['digital_spend']).toBe('monetary');
  });
});

describe('declaredPairKeys / isDeclaredPair (аннотация карты корреляций)', () => {
  const labels = [
    'date', 'sales_rub',
    'tv_spend', 'tv_trp',
    'digital_spend', 'digital_impressions',
    'competitor_trp', 'price_index', 'category_sales',
  ];
  it('пара канала распознаётся в обе стороны', () => {
    const keys = declaredPairKeys(labels);
    expect(isDeclaredPair(keys, 'tv_spend', 'tv_trp')).toBe(true);
    expect(isDeclaredPair(keys, 'tv_trp', 'tv_spend')).toBe(true);
    expect(isDeclaredPair(keys, 'digital_spend', 'digital_impressions')).toBe(true);
  });
  it('кросс-канальные и непарные сочетания НЕ пары', () => {
    const keys = declaredPairKeys(labels);
    expect(isDeclaredPair(keys, 'tv_spend', 'digital_impressions')).toBe(false);
    expect(isDeclaredPair(keys, 'tv_spend', 'digital_spend')).toBe(false);
    expect(isDeclaredPair(keys, 'competitor_trp', 'tv_trp')).toBe(false);
    expect(isDeclaredPair(keys, 'price_index', 'category_sales')).toBe(false);
  });
  it('KPI/контролы не образуют ложных пар (sales_rub — не парник)', () => {
    const keys = declaredPairKeys(labels);
    expect(isDeclaredPair(keys, 'sales_rub', 'tv_trp')).toBe(false);
    expect(isDeclaredPair(keys, 'sales_rub', 'tv_spend')).toBe(false);
  });
  it('competitor_trp не пара к чьему-либо spend (у базы competitor нет ₽-стороны)', () => {
    const keys = declaredPairKeys(['competitor_trp', 'tv_spend', 'tv_trp']);
    expect(isDeclaredPair(keys, 'competitor_trp', 'tv_spend')).toBe(false);
  });
  it('пустой вход — пустой набор', () => {
    expect(declaredPairKeys([]).size).toBe(0);
  });
});

// ─── R2 (2026-07-06): F-A1-1 — contacts-пара и русский «Контакты» ──────────
// Дыра: ooh_contacts не попадал в physical, потому что «contacts» не был
// в PHYSICAL_SUFFIX_RE (он был в PHYSICAL_PATTERNS Python, но не в JS).
// contacts? уже есть в PHYSICAL_SUFFIX_RE согласно channel-pairs.js строка 19.
// Этот тест — регрессионная ловушка: если кто-то уберёт contacts из RE,
// ooh_contacts вернётся в unknown→monetary и счётчик «исключим» слетит.
describe('contacts-пара (F-A1-1): ooh_spend + ooh_contacts', () => {
  const cols = ['ooh_spend', 'ooh_contacts'];

  it('ooh_contacts распознаётся как physical', () => {
    expect(parseChannelMetric('ooh_contacts')).toEqual({ base: 'ooh', metric: 'physical' });
  });
  it('ooh_spend распознаётся как monetary', () => {
    expect(parseChannelMetric('ooh_spend')).toEqual({ base: 'ooh', metric: 'monetary' });
  });
  it('пара группируется в один канал ooh', () => {
    const { channels, byChannel } = groupChannelColumns(cols);
    expect(channels).toEqual(['ooh']);
    expect(byChannel['ooh']).toEqual({ monetary: ['ooh_spend'], physical: ['ooh_contacts'] });
  });
  it('ROI-выбор: spend включается, contacts исключается (disable)', () => {
    const { byChannel } = groupChannelColumns(cols);
    const { enable, disable } = resolvePairSelection(byChannel, { ooh: 'monetary' });
    expect(enable).toContain('ooh_spend');
    expect(disable).toContain('ooh_contacts');
  });
  it('contacts — объявленная пара spend (isDeclaredPair)', () => {
    const keys = declaredPairKeys(cols);
    expect(isDeclaredPair(keys, 'ooh_spend', 'ooh_contacts')).toBe(true);
    expect(isDeclaredPair(keys, 'ooh_contacts', 'ooh_spend')).toBe(true);
  });
});

describe('русские «Контакты» (F-A1-1 кириллица)', () => {
  it('«Наружка Контакты» → physical (контакт[а-яё]* в PHYSICAL_SUFFIX_RE)', () => {
    expect(parseChannelMetric('Наружка Контакты')).toMatchObject({ metric: 'physical' });
  });
  it('«OOH Контакты» и «OOH Бюджет» образуют пару в канале OOH', () => {
    const { byChannel } = groupChannelColumns(['OOH Бюджет', 'OOH Контакты']);
    expect(byChannel['OOH']).toBeDefined();
    expect(byChannel['OOH'].monetary).toContain('OOH Бюджет');
    expect(byChannel['OOH'].physical).toContain('OOH Контакты');
  });
});
