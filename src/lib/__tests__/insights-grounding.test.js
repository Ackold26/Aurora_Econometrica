/**
 * Прокси-гейт Фазы 0 для Tier 2 (INV-50 grounding guard).
 *
 * Гоняется на РЕАЛЬНОЙ фикстуре прогона (Кагоцел — проблемная модель: широкие
 * ROI-интервалы, baseline 80.6%, verdict «ROI завышен»). Фиксирует контракт
 * «LLM не выдумывает числа» ДО постройки Tier 2 и ловит регрессии после.
 */
import { describe, it, expect } from 'vitest';
import {
  extractNumbers,
  collectGroundedNumbers,
  findUngroundedNumbers,
  assertGrounded,
} from '../insights-grounding.js';
import decomposition from './fixtures/kagocel-load1/decomposition.json';

describe('extractNumbers — форматы чисел (рус + лат)', () => {
  it('целые с группировкой тысяч', () => {
    const v = extractNumbers('бюджет 113 701 403 ₽').map((n) => n.value);
    expect(v).toContain(113701403);
  });

  it('десятичные с точкой и запятой', () => {
    expect(extractNumbers('ROI 12186.08').map((n) => n.value)).toContain(12186.08);
    expect(extractNumbers('ratio 2,4:1').map((n) => n.value)).toContain(2.4);
  });

  it('проценты и множители не меняют значение', () => {
    expect(extractNumbers('доля 43,3%').map((n) => n.value)).toContain(43.3);
    expect(extractNumbers('ROI 77.5×').map((n) => n.value)).toContain(77.5);
  });

  it('масштабные суффиксы млн/млрд/тыс', () => {
    expect(extractNumbers('около 6 млн').map((n) => n.value)).toContain(6_000_000);
    expect(extractNumbers('11,2 млрд').map((n) => n.value)).toContain(11_200_000_000);
    expect(extractNumbers('12 тыс').map((n) => n.value)).toContain(12_000);
  });

  it('отрицательные числа', () => {
    expect(extractNumbers('разрыв -28.8 пп').map((n) => n.value)).toContain(-28.8);
  });

  it('пустой/некорректный вход — пустой массив', () => {
    expect(extractNumbers('')).toEqual([]);
    expect(extractNumbers(null)).toEqual([]);
    expect(extractNumbers('без чисел вовсе')).toEqual([]);
  });
});

describe('collectGroundedNumbers — сбор фактов из реальной фикстуры', () => {
  const grounded = collectGroundedNumbers({ jsonFacts: decomposition });

  it('содержит ключевые числовые факты модели', () => {
    expect(grounded.has(77.49)).toBe(true); // ROI Статьи
    expect(grounded.has(2.03)).toBe(true); // ROI OLV
    expect(grounded.has(38.4)).toBe(true); // share_of_spend OLV
    expect(grounded.has(12186.08)).toBe(true); // ROI TRPs (завышен)
    expect(grounded.has(11226057702)).toBe(true); // total_sales
    expect(grounded.has(80.6)).toBe(true); // baseline_pct
  });

  it('содержит числа из строковых полей (имена каналов)', () => {
    // «TRPs бренд (W 25-54)» — цитирование имени канала не должно флагаться.
    expect(grounded.has(25)).toBe(true);
    expect(grounded.has(54)).toBe(true);
  });

  it('толеранс округления: «12 тыс» совпадает с фактом 12186.08', () => {
    expect(grounded.has(12_000)).toBe(true);
  });

  it('толеранс масштаба: «11,2 млрд» совпадает с total_sales', () => {
    expect(grounded.has(11_200_000_000)).toBe(true);
  });
});

describe('findUngroundedNumbers — главный инвариант INV-50', () => {
  const facts = { jsonFacts: decomposition };

  it('честный ответ (числа из фактов) — НЕТ негрунд-чисел', () => {
    // Все числа взяты из фикстуры: ROI 77.5/2.0, доли 38.4%/10%, gap -28.
    const honest =
      'Статьи — самый эффективный канал (ROI 77.5×), а OLV перенасыщен ' +
      '(ROI 2.0×): тратит 38.4% бюджета, но даёт лишь 10% эффекта — ' +
      'разрыв около 28 пунктов. Базовые продажи — 80.6% от общего.';
    expect(findUngroundedNumbers(honest, facts)).toEqual([]);
  });

  it('галлюцинированный ответ — числа помечены', () => {
    // 35% и 450× и 999 млн — таких чисел в фактах нет.
    const halluc =
      'Телевидение приносит 35% всех продаж с рекордным ROI 450×, ' +
      'а общий бюджет составил 999 млн ₽.';
    const bad = findUngroundedNumbers(halluc, facts).map((b) => b.value);
    expect(bad).toContain(35);
    expect(bad).toContain(450);
    expect(bad).toContain(999_000_000);
  });

  it('assertGrounded бросает на галлюцинации, молчит на честном', () => {
    expect(() => assertGrounded('ROI 450× у ТВ', facts)).toThrow(/INV-50/);
    expect(() => assertGrounded('ROI 77.5× у Статей', facts)).not.toThrow();
  });

  it('частичная галлюцинация: честное число пропущено, выдуманное поймано', () => {
    const mixed = 'Статьи дают ROI 77.5×, но я оцениваю потенциал в ROI 300×.';
    const bad = findUngroundedNumbers(mixed, facts).map((b) => b.value);
    expect(bad).toContain(300);
    expect(bad).not.toContain(77.5);
  });
});

describe('grounding учитывает Tier-1 инсайты', () => {
  it('число из текста инсайта считается grounded', () => {
    const facts = {
      jsonFacts: { channels: [] },
      insightTexts: [{ text: 'Прирост от перераспределения +5.7%', tip: 'Бюджет 2,3 млрд ₽' }],
    };
    const grounded = collectGroundedNumbers(facts);
    expect(grounded.has(5.7)).toBe(true);
    expect(grounded.has(2_300_000_000)).toBe(true);
    expect(findUngroundedNumbers('Ожидаемый прирост +5.7%', facts)).toEqual([]);
  });
});
