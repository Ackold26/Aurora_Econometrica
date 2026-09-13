/**
 * Сторож подсказок шага «Планирование» (живой прогон владельца 14.09: панель на
 * этом шаге писала «Для этого шага подсказок нет» – единственный шаг мастера,
 * где она молчала).
 *
 * 🔴 ГЛАВНОЕ, ЧТО СТЕРЕЖЁТ ЭТОТ ФАЙЛ (INV-50, честность метрик). Каждая подсказка
 * шага обязана быть УСЛОВНОЙ от проверяемого порога. Поэтому у каждого правила
 * здесь ДВА случая: данные выше порога – подсказка есть; данные ниже порога –
 * подсказки НЕТ. Второй случай важнее первого: он не даёт вернуть безусловный
 * шаблон, который печатается всегда и лишь выглядит выводом из данных.
 */
import { describe, it, expect } from 'vitest';
import { planningInsights } from '$lib/insights-rules.js';

/** Слить тексты подсказок в одну строку для поиска. @param {any[]} ins */
const asText = (ins) => ins.map((i) => i.text).join('\n');

/** План на будущее, найденный в файле. @param {any} [over] */
const planFound = (over = {}) => ({
  n_future_periods: 12,
  channels: { ТВ: [100, 100], Диджитал: [50, 50] },
  warnings: [],
  granularity: 'month',
  confirmed: true,
  ...over,
});

/** Диагностика обученной модели. @param {number} score @param {string} label */
const diagnostics = (score, label) => ({
  mqs: { score, tier_label: label },
  metrics: { ratio: 5.2, n_observations: 60 },
});

/** Вариант плана. @param {string} name @param {any} over */
const variant = (name, over = {}) => ({
  name,
  budget: 1_000_000,
  predictedKpi: 100,
  ...over,
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P1 – плана на будущее в данных нет', () => {
  it('появляется, когда строк на будущее ноль', () => {
    const t = asText(planningInsights({ mediaPlan: null, probeStatus: 'absent' }));
    expect(t).toMatch(/нет ни одной строки на будущее/);
  });

  it('НЕ появляется, как только план в файле найден (12 периодов)', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), probeStatus: 'found' }));
    expect(t).not.toMatch(/нет ни одной строки на будущее/);
  });

  it('различает «плана нет» и «определить не удалось»', () => {
    const t = asText(planningInsights({ mediaPlan: null, probeStatus: 'unavailable' }));
    expect(t).toMatch(/Определить план на будущее в этих данных не удалось/);
    expect(t).not.toMatch(/нет ни одной строки на будущее/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P2 – замечания к плану из файла', () => {
  it('появляется и называет их число и первое замечание', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound({ warnings: ['канал «Радио» не участвовал в обучении', 'пропуск в периоде 4'] }),
    }));
    expect(t).toMatch(/К плану из файла 2 замечания/);
    expect(t).toMatch(/канал «Радио» не участвовал в обучении/);
    expect(t).toMatch(/И ещё 1\./);
  });

  it('НЕ появляется при пустом списке замечаний', () => {
    const t = asText(planningInsights({ mediaPlan: planFound({ warnings: [] }) }));
    expect(t).not.toMatch(/К плану из файла/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P3 – горизонт против длины истории (порог: больше половины)', () => {
  it('появляется при 24 периодах прогноза на 36 периодах истории (67%)', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound({ n_future_periods: 24 }),
      horizonPeriods: 24,
      historyPeriods: 36,
    }));
    expect(t).toMatch(/Горизонт прогноза 24 периода против 36 периодов истории/);
    expect(t).toMatch(/67% её длины/);
    expect(t).toMatch(/Сократите горизонт до 18/);
  });

  it('НЕ появляется при 12 периодах прогноза на 36 периодах истории (33%)', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound({ n_future_periods: 12 }),
      horizonPeriods: 12,
      historyPeriods: 36,
    }));
    expect(t).not.toMatch(/Горизонт прогноза/);
  });

  it('НЕ появляется, когда длина истории неизвестна', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound({ n_future_periods: 24 }),
      horizonPeriods: 24,
      historyPeriods: 0,
    }));
    expect(t).not.toMatch(/Горизонт прогноза/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P4 – ширина правдоподобного диапазона базового прогноза', () => {
  const base = (lo, hi, mid = 100) => ({
    totalKpi: mid, totalSpend: 1_000_000, ciLowTotal: lo, ciHighTotal: hi,
  });

  it('предупреждает при ширине 80% от центра и велит брать нижнюю границу', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), baseline: base(60, 140) }));
    expect(t).toMatch(/ширина 80% от прогноза/);
    expect(t).toMatch(/по нижней границе/);
  });

  it('хвалит узкий диапазон при ширине 10%', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), baseline: base(95, 105) }));
    expect(t).toMatch(/ширина 10% от центра/);
    expect(t).toMatch(/узкий/);
  });

  it('МОЛЧИТ в середине (ширина 20%) – ни «широко», ни «узко»', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), baseline: base(90, 110) }));
    expect(t).not.toMatch(/Правдоподобный диапазон базового прогноза/);
  });

  it('НЕ появляется, когда диапазона у прогноза нет', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      baseline: { totalKpi: 100, totalSpend: 1_000_000, ciLowTotal: null, ciHighTotal: null },
    }));
    expect(t).not.toMatch(/Правдоподобный диапазон базового прогноза/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P5 – качество модели, на которой строится прогноз', () => {
  it('предупреждает при MQS 55 («приемлемое») и называет балл', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), diagnostics: diagnostics(55, 'Приемлемое') }));
    expect(t).toMatch(/Качество модели 55 из 100 \(приемлемое\)/);
    expect(t).toMatch(/ниже уровня «Хорошее» \(70\)/);
  });

  it('НЕ появляется при MQS 70 – это уже уровень «Хорошее»', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), diagnostics: diagnostics(70, 'Хорошее') }));
    expect(t).not.toMatch(/Качество модели/);
  });

  it('НЕ появляется, когда балла нет вовсе – недоказанное не выдаём за низкое', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), diagnostics: { metrics: {} } }));
    expect(t).not.toMatch(/Качество модели/);
  });

  it('при несошедшемся расчёте говорит об отказе даже при высоком балле', () => {
    const d = diagnostics(88, 'Отличное');
    d.model_reliability = { refused: true };
    const t = asText(planningInsights({ mediaPlan: planFound(), diagnostics: d }));
    expect(t).toMatch(/Качество модели 88 из 100/);
    expect(t).toMatch(/опираться на них при распределении бюджета рано/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P6 – вариант один, сравнивать не с чем', () => {
  it('появляется при ровно одном варианте и без базового прогноза', () => {
    const t = asText(planningInsights({ mediaPlan: planFound(), variants: [variant('Вариант 1')] }));
    expect(t).toMatch(/Создан один вариант «Вариант 1»/);
  });

  it('НЕ появляется, когда посчитан базовый план – сравнивать уже есть с чем', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [variant('Вариант 1')],
      baseline: { totalKpi: 100, totalSpend: 1_000_000, ciLowTotal: 90, ciHighTotal: 110 },
    }));
    expect(t).not.toMatch(/Создан один вариант/);
  });

  it('НЕ появляется при двух вариантах', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [variant('Вариант 1'), variant('Вариант 2', { budget: 2_000_000 })],
    }));
    expect(t).not.toMatch(/Создан один вариант/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P7 – бюджеты вариантов почти совпадают (порог: разброс меньше 5%)', () => {
  it('появляется при разбросе 2,0% и называет его', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [variant('A', { budget: 1_000_000 }), variant('Б', { budget: 1_020_000 })],
    }));
    expect(t).toMatch(/различаются на 2\.0%/);
  });

  it('НЕ появляется при разбросе 16,7%', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [variant('A', { budget: 1_000_000 }), variant('Б', { budget: 1_200_000 })],
    }));
    expect(t).not.toMatch(/Бюджеты вариантов различаются/);
  });

  it('НЕ появляется, когда бюджет варианта не посчитан (ноль)', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [variant('A', { budget: 0 }), variant('Б', { budget: 0 })],
    }));
    expect(t).not.toMatch(/Бюджеты вариантов различаются/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('P8 / P9 – различимы ли варианты между собой', () => {
  it('при перекрытии диапазонов отказывается называть лидера лучшим', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [
        variant('A', { predictedKpi: 110, ciLow: 90, ciHigh: 130, budget: 1_000_000 }),
        variant('Б', { predictedKpi: 100, ciLow: 80, ciHigh: 120, budget: 1_500_000 }),
      ],
    }));
    expect(t).toMatch(/преимущество лидера «A».*данными не доказано/s);
    expect(t).not.toMatch(/устойчиво лучше/);
  });

  it('при непересекающихся диапазонах называет лидера и обе границы', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [
        variant('A', { predictedKpi: 200, ciLow: 180, ciHigh: 220, budget: 1_000_000 }),
        variant('Б', { predictedKpi: 100, ciLow: 80, ciHigh: 120, budget: 1_500_000 }),
      ],
    }));
    expect(t).toMatch(/«A» устойчиво лучше «Б»/);
    expect(t).not.toMatch(/данными не доказано/);
  });

  it('базовый план участвует в сравнении наравне с вариантами', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      baseline: { totalKpi: 300, totalSpend: 1_000_000, ciLowTotal: 280, ciHighTotal: 320 },
      variants: [variant('A', { predictedKpi: 100, ciLow: 80, ciHigh: 120, budget: 1_500_000 })],
    }));
    expect(t).toMatch(/«Базовый план» устойчиво лучше «A»/);
  });

  it('НЕ сравнивает, когда диапазона нет ни у одной линии', () => {
    const t = asText(planningInsights({
      mediaPlan: planFound(),
      variants: [
        variant('A', { predictedKpi: 200, budget: 1_000_000 }),
        variant('Б', { predictedKpi: 100, budget: 1_500_000 }),
      ],
    }));
    expect(t).not.toMatch(/устойчиво лучше/);
    expect(t).not.toMatch(/данными не доказано/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('общее свойство: пустой ход не печатает ничего лишнего', () => {
  it('на чистом плане без прогноза и вариантов подсказок про сравнение нет', () => {
    const ins = planningInsights({
      mediaPlan: planFound(),
      horizonPeriods: 12,
      historyPeriods: 60,
      diagnostics: diagnostics(80, 'Хорошее'),
    });
    expect(asText(ins)).not.toMatch(/устойчиво лучше|не доказано|Создан один вариант|Бюджеты вариантов/);
    expect(ins).toHaveLength(0);
  });

  it('ни одна подсказка не печатается при ЛЮБОМ входе – пустой контекст даёт ровно одну, про отсутствие плана', () => {
    const ins = planningInsights({});
    expect(ins).toHaveLength(1);
    expect(ins[0].text).toMatch(/нет ни одной строки на будущее/);
  });
});
