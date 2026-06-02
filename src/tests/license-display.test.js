/**
 * Lock-in тесты приоритета статуса лицензии (#61, LI-001 fix, 2026-06-02).
 *
 * Защищает 4-уровневый приоритет в Настройках от регрессии. Ключевой кейс —
 * «the LI-001 bug»: валидная офлайн-лицензия должна показываться активной,
 * даже когда онлайн-авторизация недоступна (offline / blocked / exception → null).
 */
import { describe, it, expect } from 'vitest';
import { resolveLicenseTier } from '../lib/license-display.js';

describe('resolveLicenseTier — приоритет источников лицензии', () => {
  it('online ok имеет высший приоритет', () => {
    expect(resolveLicenseTier({ status: 'ok' }, { valid: true })).toBe('online-ok');
    expect(resolveLicenseTier({ status: 'ok' }, null)).toBe('online-ok');
    expect(resolveLicenseTier({ status: 'ok' }, { valid: false })).toBe('online-ok');
  });

  it('LI-001: валидная офлайн-лицензия активна, когда онлайн не ok', () => {
    expect(resolveLicenseTier({ status: 'offline' }, { valid: true })).toBe('offline-valid');
    expect(resolveLicenseTier({ status: 'blocked' }, { valid: true })).toBe('offline-valid');
    expect(resolveLicenseTier(null, { valid: true })).toBe('offline-valid');
    expect(resolveLicenseTier(undefined, { valid: true })).toBe('offline-valid');
  });

  it('офлайн-лицензия важнее устаревшего кэша', () => {
    expect(resolveLicenseTier({ status: 'cached' }, { valid: true })).toBe('offline-valid');
  });

  it('кэш онлайн-авторизации, если нет валидной офлайн-лицензии', () => {
    expect(resolveLicenseTier({ status: 'cached' }, { valid: false })).toBe('cached');
    expect(resolveLicenseTier({ status: 'cached' }, null)).toBe('cached');
  });

  it('«не подтверждена», когда ничего валидного нет', () => {
    expect(resolveLicenseTier(null, null)).toBe('none');
    expect(resolveLicenseTier(undefined, undefined)).toBe('none');
    expect(resolveLicenseTier({ status: 'offline' }, { valid: false })).toBe('none');
    expect(resolveLicenseTier({ status: 'blocked' }, null)).toBe('none');
  });
});
