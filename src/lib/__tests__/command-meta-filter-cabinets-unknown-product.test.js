/**
 * CPD-84 (JS-класс дыры, зеркалит правку Rust 44961d01 в `cabinet.rs::filter_by_product`).
 *
 * До правки `filterCabinetsByProduct` для незнакомого/неопознанного ключа продукта
 * (`_products[productType]` — `undefined`) отдавал `!allowed === true` → ВСЕ кабинеты —
 * то же расширение прав, что было в Rust `_ => None` до записи 44961d01. Теперь
 * умолчание — пустой список; «все кабинеты» — только для явно перечисленных
 * unrestricted-ключей (agency/creative-hub/media, зеркалит `None` в Rust).
 *
 * Продукты и составы кабинетов — те же значения, что в `content-packs/command-meta-data.json`
 * (проверено вручную 27.09.2026): agency/creative-hub → cabinets:null (без ограничения),
 * media → cabinets:[...] в content-pack, но Rust и JS трактуют его как unrestricted
 * (ловушка B — чужая линия ROSST_AI_Media/Insights Hub, см. PULSE_s51_phaseC.md),
 * econometrica → cabinets:["econometrist"].
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { initCommandMeta, filterCabinetsByProduct } from '../command-meta.js';

const ALL_CABINETS = [
  { id: 'econometrist', name: 'Эконометрист' },
  { id: 'lawyer-contracts', name: 'Юрист по договорам' },
  { id: 'lawyer-claims', name: 'Юрист по претензиям' },
  { id: 'creative-director', name: 'Креативный директор' },
  { id: 'media-analyst', name: 'Медиааналитик' },
];

/** Фикстура products — состав как в content-packs/command-meta-data.json (27.09.2026). */
function productsFixture() {
  return {
    agency: { name: 'Aurora AI - Agency', cabinets: null },
    'creative-hub': { name: 'Aurora AI - Creative Hub', cabinets: null },
    media: { name: 'Aurora AI - Insights Hub', cabinets: ['media-analyst', 'econometrist'] },
    legal: { name: 'Aurora AI - Legal', cabinets: ['lawyer-contracts', 'lawyer-claims'] },
    econometrica: { name: 'Aurora AI Econometrica', cabinets: ['econometrist'] },
  };
}

beforeEach(() => {
  initCommandMeta({ commands: {}, categories: [], products: productsFixture() });
});

describe('filterCabinetsByProduct — CPD-84 незнакомый продукт закрыт по умолчанию', () => {
  it('"unknown" (значение по умолчанию до ответа get_product_type) → пустой список', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'unknown')).toEqual([]);
  });

  it('выдуманный ключ, которого нет в content-pack → пустой список', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'no-such-product-xyz')).toEqual([]);
  });

  it('"agency" — без ограничения, все кабинеты', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'agency')).toEqual(ALL_CABINETS);
  });

  it('"creative-hub" — без ограничения, все кабинеты', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'creative-hub')).toEqual(ALL_CABINETS);
  });

  it('"media" — ограничен своим списком из content-pack, как и до правки (не «все»)', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'media')).toEqual([
      { id: 'econometrist', name: 'Эконометрист' },
      { id: 'media-analyst', name: 'Медиааналитик' },
    ]);
  });

  it('"econometrica" — ровно её состав (["econometrist"])', () => {
    expect(filterCabinetsByProduct(ALL_CABINETS, 'econometrica')).toEqual([
      { id: 'econometrist', name: 'Эконометрист' },
    ]);
  });
});
