/**
 * Sanity test для i18n infrastructure (foundation v2.0.1-rc2).
 *
 * Не покрывает translation completeness — только asserts что framework
 * initialized, locale store работает, translate() helper returns string.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { get } from 'svelte/store';
import { _, init, addMessages } from 'svelte-i18n';


// Setup minimal locale fixtures для test (без полной dictionary).
beforeAll(() => {
  addMessages('ru', {
    common: { save: 'Сохранить', cancel: 'Отмена' },
    test: { greeting: 'Привет, {name}!' },
  });
  addMessages('en', {
    common: { save: 'Save', cancel: 'Cancel' },
    test: { greeting: 'Hello, {name}!' },
  });
  init({ fallbackLocale: 'ru', initialLocale: 'ru' });
});


describe('i18n infrastructure (foundation)', () => {
  it('svelte-i18n _ store resolves nested keys', () => {
    const t = get(_);
    expect(t('common.save')).toBe('Сохранить');
    expect(t('common.cancel')).toBe('Отмена');
  });

  it('interpolation параметров работает', () => {
    const t = get(_);
    expect(t('test.greeting', { values: { name: 'Антон' } })).toBe('Привет, Антон!');
  });

  it('missing key returns key (no crash)', () => {
    const t = get(_);
    const result = t('common.nonexistent');
    expect(typeof result).toBe('string');
    // svelte-i18n returns key path для missing entries, что safer чем crash.
    expect(result).toContain('nonexistent');
  });
});


describe('locale switching', () => {
  it('switches between ru и en', async () => {
    const { locale: i18nLocale } = await import('svelte-i18n');
    i18nLocale.set('en');
    const t = get(_);
    expect(t('common.save')).toBe('Save');
    i18nLocale.set('ru');
    const t2 = get(_);
    expect(t2('common.save')).toBe('Сохранить');
  });
});
