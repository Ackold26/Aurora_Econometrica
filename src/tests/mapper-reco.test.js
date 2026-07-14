/**
 * mapper-reco.test.js — unit-тесты чистых хелперов kindSpecificReco (R2 2026-07-06).
 *
 * Закрываемые симптомы:
 *   F-A1-2: category_sales в роли control → должен давать 'keep' «Оставить: контроль
 *            категории», а не 'exclude' «Исключить» (старый kpiLikeRe ловил 'sales').
 *   F-A1-3: «рыночные продажи»/«конкурентные продажи» → позитивные бейджи,
 *            а не ложный «Альтернативная цель».
 */
import { describe, it, expect } from 'vitest';
import { kindSpecificReco, recoCategoryControl, recoCompetitorControl, recoAlternativeTarget } from '../lib/mapper-reco.js';

describe('kindSpecificReco: category в роли control', () => {
  it('F-A1-2: category + role=control → keep «Оставить: контроль категории»', () => {
    const reco = kindSpecificReco('category', 'control', true, false);
    expect(reco?.status).toBe('keep');
    expect(reco?.label).toMatch(/контроль категории/i);
    expect(reco?.tone).toBe('ok');
  });
  it('category + role=excluded → keep (тоже позитив, не excluded-neutral)', () => {
    const reco = kindSpecificReco('category', 'excluded', true, true);
    expect(reco?.status).toBe('keep');
  });
  it('category + role=media → null (media-блок обрабатывается отдельно)', () => {
    expect(kindSpecificReco('category', 'media', true, false)).toBeNull();
  });
  it('category + role=kpi → null (kpi-блок отдельно)', () => {
    expect(kindSpecificReco('category', 'kpi', true, false)).toBeNull();
  });
});

describe('kindSpecificReco: signed_competitor в роли control', () => {
  it('F-A1-3: signed_competitor + role=control → keep «Оставить: конкурентный контроль»', () => {
    const reco = kindSpecificReco('signed_competitor', 'control', true, false);
    expect(reco?.status).toBe('keep');
    expect(reco?.label).toMatch(/конкурентный контроль/i);
    expect(reco?.tone).toBe('ok');
  });
  it('signed_competitor + role=excluded → keep', () => {
    expect(kindSpecificReco('signed_competitor', 'excluded', true, true)?.status).toBe('keep');
  });
});

describe('kindSpecificReco: target_* → Альтернативная цель', () => {
  it('target_monetary + role=control + hasActiveKpi → review «Альтернативная цель»', () => {
    const reco = kindSpecificReco('target_monetary', 'control', true, true);
    expect(reco?.status).toBe('review');
    expect(reco?.label).toMatch(/альтернативная цель/i);
    expect(reco?.tone).toBe('warn');
  });
  it('target_count + role=control + hasActiveKpi → review', () => {
    expect(kindSpecificReco('target_count', 'control', true, true)?.status).toBe('review');
  });
  it('target_monetary + role=control + НЕТ KPI → null (условие не срабатывает)', () => {
    expect(kindSpecificReco('target_monetary', 'control', true, false)).toBeNull();
  });
  it('target_monetary + role=kpi → null (уже kpi, не переключаем)', () => {
    expect(kindSpecificReco('target_monetary', 'kpi', true, true)).toBeNull();
  });
  it('target_monetary + role=media → null', () => {
    expect(kindSpecificReco('target_monetary', 'media', true, true)).toBeNull();
  });
  it('target_monetary + role=excluded → null', () => {
    expect(kindSpecificReco('target_monetary', 'excluded', true, true)).toBeNull();
  });
});

describe('kindSpecificReco: не-специальные kinds → null', () => {
  it('monetary + role=media → null', () => {
    expect(kindSpecificReco('monetary', 'media', true, false)).toBeNull();
  });
  it('signed_price + role=control → null (не категория, не конкурент)', () => {
    expect(kindSpecificReco('signed_price', 'control', true, false)).toBeNull();
  });
  it('unknown + role=control → null', () => {
    expect(kindSpecificReco('unknown', 'control', true, false)).toBeNull();
  });
  it('пустой kind → null', () => {
    expect(kindSpecificReco('', 'control', true, false)).toBeNull();
  });
});

describe('атомарные хелперы', () => {
  it('recoCategoryControl: status=keep, tone=ok', () => {
    const r = recoCategoryControl();
    expect(r.status).toBe('keep');
    expect(r.tone).toBe('ok');
    expect(r.label).toBeTruthy();
    expect(r.reason).toBeTruthy();
  });
  it('recoCompetitorControl: status=keep, tone=ok', () => {
    const r = recoCompetitorControl();
    expect(r.status).toBe('keep');
    expect(r.tone).toBe('ok');
  });
  it('recoAlternativeTarget: status=review, tone=warn', () => {
    const r = recoAlternativeTarget();
    expect(r.status).toBe('review');
    expect(r.tone).toBe('warn');
  });
});
