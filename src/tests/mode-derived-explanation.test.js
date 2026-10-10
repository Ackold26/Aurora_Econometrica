/**
 * s61 (А1/А3): экран «Подтверждение» (ModeDerivedExplanation) – отрисовка.
 *
 * Живой проход 10.10 на парном демо-файле: экран показывал 8 медиа-каналов при
 * четырёх выключенных физических половинах пар, подписывал показы и клики
 * «спенд в ₽» и складывал их в «ИТОГО медиа» – 3.6 млрд ₽ вместо настоящих
 * 1.1 млрд (в 3,4 раза больше). Здесь – что экран показывает ровно то, что уйдёт
 * в обучение.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import ModeDerivedExplanation from '$lib/components/pipeline/ModeDerivedExplanation.svelte';
import {
  validateData, perChannelInput, unitCosts, analysisMode, kpiType,
  modelChannelEnabled, modelEngine, useHolidays, disabledHolidays,
} from '$lib/project-state.js';

const MONEY = { tv_spend: 400_000_000, digital_spend: 300_000_000, ooh_spend: 200_000_000, performance_spend: 177_800_000 };
const PHYS = { tv_trp: 2514.6, digital_impressions: 1_075_566_682, ooh_contacts: 1_473_341_865, performance_clicks: 811_114 };

/**
 * Результат проверки парного файла: 4 бюджетных + 4 физических (все в роли
 * media, как отдаёт движок) + 3 контроля.
 * @param {{rows?: number, frequency?: string|null, warnings?: any[]}} [o]
 */
function pairedResult(o = {}) {
  const rows = o.rows ?? 48;
  /** @type {Record<string, any>} */
  const detected = { n_rows: rows, n_holidays_auto: 13, n_intercept: 1 };
  if (o.frequency !== null) detected.date_frequency = o.frequency ?? 'monthly';
  return {
    status: 'ok',
    file: { rows },
    warnings: o.warnings ?? [],
    detected,
    columns: [
      { name: 'date', role: 'date' },
      { name: 'sales_rub', role: 'kpi' },
      ...Object.entries(MONEY).map(([name, sum]) => ({ name, role: 'media', stats: { sum, zeros_pct: 0 } })),
      ...Object.entries(PHYS).map(([name, sum]) => ({ name, role: 'media', stats: { sum, zeros_pct: 0 } })),
      { name: 'competitor_trp', role: 'control' },
      { name: 'price_index', role: 'control' },
      { name: 'category_sales', role: 'control' },
    ],
  };
}

/** @param {any} result */
function setResult(result) {
  validateData.set(/** @type {any} */ ({ result, correlationMatrix: null, columnHistograms: null }));
}

/** Экспресс-состояние сторов: бюджетные – деньгами, физические половины выключены. */
function expressState() {
  perChannelInput.set(Object.fromEntries(Object.keys(MONEY).map((name) => [name, 'monetary'])));
  modelChannelEnabled.set(Object.fromEntries(Object.keys(PHYS).map((name) => [name, false])));
}

/** @param {HTMLElement} container */
function tableRowNames(container) {
  return [...container.querySelectorAll('.media-table tbody tr .col-name')].map((el) => el.textContent?.trim());
}

/** @param {HTMLElement} container @param {string} label */
function qualityCard(container, label) {
  const card = [...container.querySelectorAll('.quality-card')]
    .find((el) => el.querySelector('.qc-label')?.textContent?.trim() === label);
  return {
    found: Boolean(card),
    value: card?.querySelector('.qc-value')?.textContent?.trim() ?? null,
    status: card?.querySelector('.qc-status')?.textContent?.trim() ?? null,
  };
}

/** @param {HTMLElement} container */
function totalText(container) {
  return container.querySelector('.media-table tfoot .row-total .col-right')?.textContent?.trim() ?? null;
}

beforeEach(() => {
  analysisMode.set('roi');
  kpiType.set('sales');
  modelEngine.set('bayesian');
  useHolidays.set(true);
  disabledHolidays.set([]);
  unitCosts.set({});
  perChannelInput.set({});
  modelChannelEnabled.set({});
  setResult(pairedResult());
});

describe('А1: список каналов – только включённые в модель', () => {
  it('экспресс на парном файле: 4 канала вместо 8, физических строк нет', () => {
    expressState();
    const { container } = render(ModeDerivedExplanation);

    expect(tableRowNames(container)).toEqual(Object.keys(MONEY));
    expect(container.querySelector('#media-heading .count-badge')?.textContent?.trim()).toBe('4');
    expect(container.textContent).not.toContain('tv_trp');
    expect(container.textContent).not.toContain('performance_clicks');
    expect(qualityCard(container, 'Каналов').value).toBe('4');
  });

  it('экспресс: «ИТОГО медиа» – 1.1 млрд ₽ по бюджетным, без миллиардов показов', () => {
    expressState();
    const { container } = render(ModeDerivedExplanation);

    expect(totalText(container)).toBe('1.1 млрд ₽');
    expect(container.textContent).not.toContain('3.6 млрд');
    // Все строки рублёвые → оговорки про физические единицы нет.
    expect(container.querySelector('.total-note')).toBeNull();
  });

  it('экспресс: «Переменных» и запас данных – по включённым (4 медиа + 3 контроля)', () => {
    expressState();
    const { container } = render(ModeDerivedExplanation);

    expect(qualityCard(container, 'Переменных').value).toBe('7');
    // 48 / (7 + 13 праздников + свободный член) = 2.29
    expect(qualityCard(container, 'Запас данных (Ratio)').value).toBe('2.3:1');
  });

  it('карта пуста (развязки не было): показаны все 8 – нет ключа = включена', () => {
    perChannelInput.set(Object.fromEntries(Object.keys(MONEY).map((name) => [name, 'monetary'])));
    const { container } = render(ModeDerivedExplanation);

    expect(tableRowNames(container)).toEqual([...Object.keys(MONEY), ...Object.keys(PHYS)]);
    expect(qualityCard(container, 'Каналов').value).toBe('8');
  });

  it('выбрана физическая половина пары: бюджетная половина в списке не появляется', () => {
    perChannelInput.set({ tv_trp: 'physical', digital_spend: 'monetary', ooh_spend: 'monetary', performance_spend: 'monetary' });
    unitCosts.set({ tv_trp: 1500 });
    modelChannelEnabled.set({
      tv_trp: true, tv_spend: false, digital_spend: true, ooh_spend: true, performance_spend: true,
      digital_impressions: false, ooh_contacts: false, performance_clicks: false,
    });
    const { container } = render(ModeDerivedExplanation);

    expect(tableRowNames(container)).toEqual(['digital_spend', 'ooh_spend', 'performance_spend', 'tv_trp']);
    // 300 + 200 + 177.8 млн + 2514.6 × 1500 (3.8 млн) = 681.6 млн – канал ТВ учтён один раз.
    expect(totalText(container)).toBe('681.6 млн ₽');
  });
});

describe('А1: единица по умолчанию – из имени, «ИТОГО» – только рублёвые строки', () => {
  it('колонка без записи о метрике с физическим именем → «физ. контакты», не «спенд в ₽»', () => {
    // Карта пуста, метрики заданы только бюджетным – физические половины показаны,
    // но рублями не подписаны и в итог не сложены.
    perChannelInput.set(Object.fromEntries(Object.keys(MONEY).map((name) => [name, 'monetary'])));
    const { container } = render(ModeDerivedExplanation);

    const rows = [...container.querySelectorAll('.media-table tbody tr')];
    /** @param {string} name */
    const unitOf = (name) => rows
      .find((tr) => tr.querySelector('.col-name')?.textContent?.trim() === name)
      ?.querySelector('.col-unit .unit-label')?.textContent?.trim();
    for (const name of Object.keys(PHYS)) expect(unitOf(name)).toBe('физ. контакты');
    for (const name of Object.keys(MONEY)) expect(unitOf(name)).toBe('спенд в ₽');
  });

  it('физические строки в итог не входят, и подпись говорит об этом', () => {
    perChannelInput.set(Object.fromEntries(Object.keys(MONEY).map((name) => [name, 'monetary'])));
    const { container } = render(ModeDerivedExplanation);

    expect(totalText(container)).toBe('1.1 млрд ₽');
    expect(container.textContent).not.toContain('3.6 млрд');
    const note = container.querySelector('.total-note');
    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('в итог не входят');
    // Сырые суммы физических строк показаны в единицах, а не в рублях.
    const trpRow = [...container.querySelectorAll('.media-table tbody tr')]
      .find((tr) => tr.querySelector('.col-name')?.textContent?.trim() === 'digital_impressions');
    expect(trpRow?.querySelector('.col-sum')?.textContent).toContain('ед');
    expect(trpRow?.querySelector('.col-sum')?.textContent).not.toContain('₽');
  });

  it('оговорка не появляется, когда физический канал пересчитан в рубли ценой единицы', () => {
    perChannelInput.set({ tv_trp: 'physical', digital_spend: 'monetary' });
    unitCosts.set({ tv_trp: 1500 });
    modelChannelEnabled.set({
      tv_spend: false, ooh_spend: false, performance_spend: false,
      digital_impressions: false, ooh_contacts: false, performance_clicks: false,
    });
    const { container } = render(ModeDerivedExplanation);
    expect(tableRowNames(container)).toEqual(['digital_spend', 'tv_trp']);
    expect(container.querySelector('.total-note')).toBeNull();
  });

  it('А3-1: колонка, физическая только для детектора шаблонов (olv_views), не подписывается рублями и не идёт в итог', () => {
    const result = pairedResult();
    result.columns.push({ name: 'olv_views', role: 'media', stats: { sum: 900_000_000, zeros_pct: 0 } });
    setResult(result);
    expressState(); // 4 бюджетных – деньгами, физические половины выключены; у olv_views записи нет
    const { container } = render(ModeDerivedExplanation);

    const row = [...container.querySelectorAll('.media-table tbody tr')]
      .find((tr) => tr.querySelector('.col-name')?.textContent?.trim() === 'olv_views');
    expect(row?.querySelector('.col-unit .unit-label')?.textContent?.trim()).toBe('физ. контакты');
    expect(row?.querySelector('.col-sum')?.textContent).toContain('ед');
    expect(totalText(container)).toBe('1.1 млрд ₽'); // 900 млн просмотров в рубли не сложены
    expect(container.querySelector('.total-note')).not.toBeNull();
  });

  it('явная запись о метрике важнее имени (физическое имя, помеченное как деньги)', () => {
    perChannelInput.set({ tv_trp: 'monetary' });
    modelChannelEnabled.set(Object.fromEntries(
      [...Object.keys(MONEY), ...Object.keys(PHYS)].filter((n) => n !== 'tv_trp').map((n) => [n, false]),
    ));
    const { container } = render(ModeDerivedExplanation);
    expect(tableRowNames(container)).toEqual(['tv_trp']);
    expect(container.querySelector('.col-unit .unit-label')?.textContent?.trim()).toBe('спенд в ₽');
  });
});

/**
 * А3: карточка истории – подпись, единица и порог из частоты данных. Живой проход:
 * «Недель истории 48 нед / < 52 нед» на 48 месячных наблюдениях, где норма
 * (24 месяца) выполнена вдвое. Движок отдаёт частоту словом (`monthly`).
 */
describe('А3: карточка истории – из частоты данных', () => {
  /** @param {number} rows @param {string|null} frequency */
  function renderWith(rows, frequency) {
    setResult(pairedResult({ rows, frequency }));
    expressState();
    return render(ModeDerivedExplanation).container;
  }

  /** @param {HTMLElement} container */
  function historyCard(container) {
    // Карточка истории – вторая в сетке «Контроль качества».
    const card = container.querySelectorAll('.quality-card')[1];
    return {
      label: card?.querySelector('.qc-label')?.textContent?.trim(),
      value: card?.querySelector('.qc-value')?.textContent?.trim(),
      status: card?.querySelector('.qc-status')?.textContent?.trim(),
      warn: card?.classList.contains('tone-warn'),
      aria: card?.getAttribute('aria-label'),
      text: card?.textContent ?? '',
    };
  }

  it('48 месячных наблюдений: «Месяцев истории 48 мес», без «нед» и без «< 52»', () => {
    const container = renderWith(48, 'monthly');
    const card = historyCard(container);
    expect(card.label).toBe('Месяцев истории');
    expect(card.value).toBe('48 мес');
    expect(card.status).toBe('Отлично'); // 48 ≥ 2 × 24
    expect(card.warn).toBe(false);
    expect(card.aria).toBe('Месяцев истории для обучения');
    expect(card.text).not.toContain('нед');
    expect(card.text).not.toContain('52');
    // Шапка: бейджа «меньше нормы» нет.
    expect(container.querySelector('.summary-header .badge-warn')).toBeNull();
  });

  it('20 месячных наблюдений: «< 24 мес» и предупреждающий тон', () => {
    const container = renderWith(20, 'monthly');
    const card = historyCard(container);
    expect(card.value).toBe('20 мес');
    expect(card.status).toBe('< 24 мес');
    expect(card.warn).toBe(true);
    expect(container.querySelector('.summary-header .badge-warn')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('<24 мес');
  });

  it('30 месячных наблюдений: порог выполнен, но не вдвое → «Достаточно»', () => {
    const card = historyCard(renderWith(30, 'monthly'));
    expect(card.status).toBe('Достаточно');
    expect(card.warn).toBe(false);
  });

  it('40 недельных наблюдений: «Недель истории 40 нед / < 52 нед»', () => {
    const card = historyCard(renderWith(40, 'weekly'));
    expect(card.label).toBe('Недель истории');
    expect(card.value).toBe('40 нед');
    expect(card.status).toBe('< 52 нед');
    expect(card.warn).toBe(true);
  });

  it('недельные: 60 → «Достаточно», 104 → «Отлично» (прежние границы)', () => {
    expect(historyCard(renderWith(60, 'weekly')).status).toBe('Достаточно');
    expect(historyCard(renderWith(103, 'weekly')).status).toBe('Достаточно');
    expect(historyCard(renderWith(104, 'weekly')).status).toBe('Отлично');
  });

  it('6 квартальных наблюдений: «Кварталов истории 6 кв / < 8 кв»', () => {
    const card = historyCard(renderWith(6, 'quarterly'));
    expect(card.label).toBe('Кварталов истории');
    expect(card.value).toBe('6 кв');
    expect(card.status).toBe('< 8 кв');
  });

  it('дневные данные: «Наблюдений истории», единица «пер»', () => {
    const card = historyCard(renderWith(400, 'daily'));
    expect(card.label).toBe('Наблюдений истории');
    expect(card.value).toBe('400 пер');
    expect(card.text).not.toContain('нед');
  });

  it('неизвестная частота: «Наблюдений истории», «пер», порог 52 – не «недели»', () => {
    const card = historyCard(renderWith(40, 'unknown'));
    expect(card.label).toBe('Наблюдений истории');
    expect(card.value).toBe('40 пер');
    expect(card.status).toBe('< 52 пер');
    expect(card.text).not.toContain('нед');
  });

  it('А-6: частоты в результате нет вовсе → «Наблюдений истории», не «Недель истории»', () => {
    // Сохранённый результат старого формата без date_frequency: частота неизвестна.
    const card = historyCard(renderWith(40, null));
    expect(card.label).toBe('Наблюдений истории');
    expect(card.value).toBe('40 пер');
    expect(card.status).toBe('< 52 пер');
    expect(card.text).not.toContain('нед');
  });
});

/**
 * А-5 (круг 2): зелёный статус карточки истории не спорит с движком. Движок судит
 * по календарному сроку и кладёт в `result.warnings` элемент
 * `{ type: 'short_period', message, severity }` – 60 дневных строк это два месяца,
 * 16 квартальных – мало точек; по числу строк карточка писала «Достаточно» / «Отлично».
 */
describe('А-5: статус карточки истории учитывает вердикт движка short_period', () => {
  const SHORT = { type: 'short_period', message: 'Период данных ~60 дн. (< 1 года)', severity: 'warning' };

  /** @param {number} rows @param {string} frequency @param {any[]} warnings */
  function card(rows, frequency, warnings) {
    setResult(pairedResult({ rows, frequency, warnings }));
    expressState();
    const el = render(ModeDerivedExplanation).container.querySelectorAll('.quality-card')[1];
    return {
      status: el?.querySelector('.qc-status')?.textContent?.trim(),
      warn: el?.classList.contains('tone-warn'),
      ok: el?.classList.contains('tone-ok'),
    };
  }

  it('16 квартальных с short_period → не «Отлично», тон предупреждения', () => {
    const c = card(16, 'quarterly', [SHORT]);
    expect(c.status).toBe('мало для надёжной оценки');
    expect(c.status).not.toBe('Отлично');
    expect(c.warn).toBe(true);
    expect(c.ok).toBe(false);
  });

  it('60 дневных с short_period → не «Достаточно», тон предупреждения', () => {
    const c = card(60, 'daily', [SHORT]);
    expect(c.status).toBe('мало для надёжной оценки');
    expect(c.status).not.toBe('Достаточно');
    expect(c.warn).toBe(true);
  });

  it('без предупреждения движка – прежние статусы', () => {
    expect(card(16, 'quarterly', [])).toEqual({ status: 'Отлично', warn: false, ok: true });
    expect(card(60, 'daily', [])).toEqual({ status: 'Достаточно', warn: false, ok: true });
  });

  it('предупреждение другого типа статус не меняет', () => {
    const c = card(16, 'quarterly', [{ type: 'high_zeros', column: 'tv_spend', severity: 'warning' }]);
    expect(c.status).toBe('Отлично');
    expect(c.warn).toBe(false);
  });

  it('порог по числу наблюдений важнее: 20 месячных с short_period → «< 24 мес»', () => {
    const c = card(20, 'monthly', [SHORT]);
    expect(c.status).toBe('< 24 мес');
    expect(c.warn).toBe(true);
  });
});
