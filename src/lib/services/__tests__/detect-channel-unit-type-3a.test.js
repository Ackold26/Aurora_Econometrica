/**
 * 3A (2026-06-02): жёсткий блок CPP для не-денежных каналов в ROI-режиме держится
 * на detectChannelUnitType: канал → 'physical' → гейт allChannelsConfigured
 * (ValidateStepV13:755) требует unit_cost>0. Если детект сломается (вернёт
 * 'monetary' для TRP/GRP/кликов), гейт тихо отвалится и вернётся артефакт ROI.
 * Этот тест фиксирует детект на РЕАЛЬНЫХ именах каналов Kagocel.
 *
 * Решение Антона (2026-06-02): форсить CPP только в ROI-режиме; backward-compat
 * не нужен (новый проект). Для новых проектов flow уже детектит + гейтит - тест
 * защищает этот контракт от регрессии.
 */
import { describe, it, expect } from 'vitest';
import { detectChannelUnitType } from '../classifier-patterns.js';

describe('3A detectChannelUnitType — не-денежные каналы → physical (гейт CPP)', () => {
  it('реальные не-денежные каналы Kagocel/MMX → physical', () => {
    expect(detectChannelUnitType('TRPs бренд (W 25-54)')).toBe('physical');
    expect(detectChannelUnitType('OLV Показы')).toBe('physical');
    expect(detectChannelUnitType('Banners Показы')).toBe('physical');
    expect(detectChannelUnitType('Performance Клики')).toBe('physical');
    expect(detectChannelUnitType('TV GRP')).toBe('physical');
  });

  it('денежные каналы (бюджет/₽) → monetary (CPP не нужен)', () => {
    expect(detectChannelUnitType('OLV Бюджет до НДС до АК')).toBe('monetary');
    expect(detectChannelUnitType('Social Бюджет ДО НДС до АК')).toBe('monetary');
    expect(detectChannelUnitType('Retail Media бюджет до НДС до АК')).toBe('monetary');
    expect(detectChannelUnitType('TV Spend')).toBe('monetary');
  });

  it('смешанное имя (и бюджет, и trp) → monetary (есть деньги — CPP не требуется)', () => {
    // Контракт detectChannelUnitType: при совпадении обоих → monetary
    // (деньги уже есть, конверсия не нужна). Документируем намеренно.
    expect(detectChannelUnitType('TRP бюджет')).toBe('monetary');
  });

  it('пустое/мусорное имя → monetary (безопасный дефолт)', () => {
    expect(detectChannelUnitType('')).toBe('monetary');
    expect(detectChannelUnitType('Прочее')).toBe('monetary');
  });
});
