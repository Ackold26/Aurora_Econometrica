/**
 * П5-3: умная обрезка подписей корреляционной матрицы.
 *
 * Критерий приёмки: пары с одинаковым префиксом (performance_spend / performance_clicks)
 * должны давать РАЗЛИЧИМЫЕ метки. Короткие имена не трогаются.
 */
import { describe, it, expect } from 'vitest';
import { abbreviateLabel } from '$lib/correlation-utils.js';

describe('abbreviateLabel — умная обрезка для корреляционной матрицы', () => {
  it('пара performance_spend / performance_clicks — метки РАЗЛИЧАЮТСЯ', () => {
    const spend  = abbreviateLabel('performance_spend');
    const clicks = abbreviateLabel('performance_clicks');
    expect(spend).not.toBe(clicks);
  });

  it('performance_spend → голова + … + хвост', () => {
    const result = abbreviateLabel('performance_spend');
    // Должен начинаться с 'perform' и заканчиваться '_spend'
    expect(result).toMatch(/^perform…/);
    expect(result).toMatch(/_spend$/);
  });

  it('performance_clicks → голова + … + хвост', () => {
    const result = abbreviateLabel('performance_clicks');
    expect(result).toMatch(/^perform…/);
    expect(result).toMatch(/licks$/);
  });

  it('короткое имя (≤ maxLen) — не трогается', () => {
    expect(abbreviateLabel('digital')).toBe('digital');
    expect(abbreviateLabel('tv')).toBe('tv');
    expect(abbreviateLabel('category_sa')).toBe('category_sa');
  });

  it('имя ровно на границе maxLen — не трогается', () => {
    // 14 символов — граница
    expect(abbreviateLabel('digital_spend1')).toBe('digital_spend1');
  });

  it('имя длиннее maxLen — обрезается с голова…хвост', () => {
    // 'digital_spend_x' = 15 символов > 14 → обрезать
    const result = abbreviateLabel('digital_spend_x');
    expect(result).toContain('…');
    expect(result.length).toBeLessThan('digital_spend_x'.length);
  });

  it('competitor_spend / competitor_imp — различаются', () => {
    const a = abbreviateLabel('competitor_spend');
    const b = abbreviateLabel('competitor_imp');
    // competitor_imp = 14 символов ровно → не обрезается
    expect(b).toBe('competitor_imp');
    expect(a).not.toBe(b);
  });

  it('custom maxLen работает', () => {
    // С maxLen=10 — 'digital_spend' (13 символов) должно обрезаться
    const result = abbreviateLabel('digital_spend', 10, 4, 4);
    expect(result).toContain('…');
    expect(result.startsWith('digi')).toBe(true);
    expect(result.endsWith('pend')).toBe(true);
  });

  it('результат содержит ровно одно «…»', () => {
    const result = abbreviateLabel('performance_spend');
    const matches = result.match(/…/g);
    expect(matches).not.toBeNull();
    expect(matches?.length).toBe(1);
  });
});
