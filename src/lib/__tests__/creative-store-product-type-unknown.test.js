/**
 * CPD-84 (JS-класс дыры, зеркалит правку Rust 44961d01 в `cabinet.rs::filter_by_product`).
 *
 * До правки: (1) начальное значение `productType` ДО ответа `get_product_type` было
 * «agency» (без ограничения — все кабинеты видны, пока backend ещё не ответил);
 * (2) отказ самого вызова `get_product_type` (invoke бросает) в `initCreativeStore()`
 * тоже откатывал на «agency». Оба случая — расширение прав при неопределённости, тот же
 * класс дыры, что был в Rust `_ => None` до записи 44961d01. Теперь и начальное значение,
 * и результат отказа — «unknown» (пустой список кабинетов через `filterCabinetsByProduct`,
 * см. `command-meta-filter-cabinets-unknown-product.test.js`). «agency» — легитимный
 * продукт, не заглушка ошибки.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';

describe('creative-store productType — CPD-84 неопределённость закрыта по умолчанию', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.mocked(invoke).mockReset();
  });

  it('начальное значение стора (до любого invoke) — "unknown", не "agency"', async () => {
    // Модуль импортируется заново (resetModules) — читаем значение writable('unknown')
    // до вызова initCreativeStore().
    const { productType } = await import('../creative-store.js');
    expect(get(productType)).toBe('unknown');
  });

  it('initCreativeStore(): отказ get_product_type → productType становится "unknown"', async () => {
    vi.mocked(invoke).mockImplementation((/** @type {string} */ cmd) => {
      if (cmd === 'get_product_type') return Promise.reject(new Error('backend недоступен'));
      // Прочие вызовы initCreativeStore (refreshBrands→brand_list, brand_get_active,
      // ensure_default_brand) — молча резолвятся, как их собственные catch-ветки ожидают.
      return Promise.resolve(null);
    });
    const { productType, initCreativeStore } = await import('../creative-store.js');
    await initCreativeStore();
    expect(get(productType)).toBe('unknown');
  });

  it('initCreativeStore(): успешный ответ get_product_type — не переопределяется на "unknown"', async () => {
    vi.mocked(invoke).mockImplementation((/** @type {string} */ cmd) => {
      if (cmd === 'get_product_type') return Promise.resolve('econometrica');
      return Promise.resolve(null);
    });
    const { productType, initCreativeStore } = await import('../creative-store.js');
    await initCreativeStore();
    expect(get(productType)).toBe('econometrica');
  });
});
