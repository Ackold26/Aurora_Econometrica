/**
 * SEV-1 (2026-06-02): методологический порог по степеням свободы.
 * «Ошибка/невозможно» (красный) только при df ≤ 0 (ratio < 1, параметров ≥
 * наблюдений - модель не определяется). При 1 ≤ ratio < 2 модель идентифицируема
 * и реально обучается (Кагоцел 1.7) - это высокий warning (оранжевый), не error.
 */
import { describe, it, expect } from 'vitest';
import { classifyRatio, RATIO_THRESHOLDS, severityTo3Tier } from '../ratio-classifier.js';

describe('SEV-1 ratio-classifier — порог по степеням свободы', () => {
  it('ratio < 1 (df ≤ 0) → error «Модель не определяется» (красный)', () => {
    const c = classifyRatio(0.8);
    expect(c.severity).toBe('error');
    expect(c.tone).toBe('danger');
    expect(c.label).toMatch(/не определяется/i);
  });

  it('Кагоцел 1.7 → НЕ error: высокий warning (оранжевый), не красный', () => {
    const c = classifyRatio(1.7);
    expect(c.severity).not.toBe('error');
    expect(c.severity).toBe('warning-high');
    expect(c.tone).toBe('warn-strong');
    expect(c.label).toMatch(/критически мало/i);
    expect(c.description).toMatch(/направлени/i); // «только направление, не абсолют»
  });

  it('граница ratio = 1.0 → уже идентифицируема (warning, не error)', () => {
    const c = classifyRatio(1.0);
    expect(c.severity).toBe('warning-high');
  });

  it('ratio чуть ниже 1 → error', () => {
    expect(classifyRatio(0.99).severity).toBe('error');
  });

  it('верхние коридоры не тронуты: 2.5 ниже минимума, 5 рекомендуемый, 7 идеально', () => {
    expect(classifyRatio(2.5).severity).toBe('warning-high');
    expect(classifyRatio(5).severity).toBe('info');
    expect(classifyRatio(7).severity).toBe('success');
  });

  it('DEGENERATE порог добавлен, ERROR/IDEAL сохранены (RatioInfoCard не сломан)', () => {
    expect(RATIO_THRESHOLDS.DEGENERATE).toBe(1);
    expect(RATIO_THRESHOLDS.ERROR).toBe(2);
    expect(RATIO_THRESHOLDS.IDEAL).toBe(6);
  });

  it('3-tier: и вырождение, и критически-мало → bad (для sticky header)', () => {
    expect(severityTo3Tier(classifyRatio(0.8).severity)).toBe('bad');
    expect(severityTo3Tier(classifyRatio(1.7).severity)).toBe('bad');
  });
});
