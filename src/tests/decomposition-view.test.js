/**
 * decomposition-view.test.js — контракт двухуровневой декомпозиции (Т3).
 * Главный инвариант: свёрнутая сумма 4 групп == развёрнутая сумма всех полос
 * == сумма исходных серий (тождество энергосохранения не зависит от раскрытия).
 * Зеркалит форму SSOT decomposer.build_decomposition_series (top_group/pct_of_base).
 */
import { describe, it, expect } from 'vitest';
import {
  TOP_GROUP_ORDER,
  TOP_GROUP_DISPLAY,
  fallbackTopGroup,
  topGroupOf,
  presentTopGroups,
  planViewSeries,
  seasonalityPctOfBase,
  symmetricPctBound,
  seriesIdentity,
} from '../lib/decomposition-view.js';

/** Фикстура ~формы decompose result: 3 периода, 4 группы, знакопеременная сезонность. */
function fixture() {
  return {
    dates: ['2025-01-01', '2025-02-01', '2025-03-01'],
    series: [
      { name: 'Базовый уровень', role: 'baseline', type: 'baseline', group: 'База', top_group: 'БАЗА', side: 'positive', data: [1000, 1000, 1000] },
      { name: 'TV', role: 'media', type: 'media', group: 'Медиа', top_group: 'МЕДИА', side: 'positive', data: [200, 250, 300] },
      { name: 'Digital', role: 'media', type: 'media', group: 'Медиа', top_group: 'МЕДИА', side: 'positive', data: [100, 120, 140] },
      { name: 'Сезонность', role: 'factor', type: 'seasonality', group: 'Сезонность', top_group: 'БАЗА', side: 'positive', data: [-50, 30, 80], pct_of_base: [-5.0, 3.0, 8.0] },
      { name: 'Праздники', role: 'factor', type: 'holiday', group: 'Праздники', top_group: 'БАЗА', side: 'positive', data: [40, 0, 0] },
      { name: 'Цена', role: 'factor', type: 'signed_price', group: 'Цена', top_group: 'ВНЕШНИЕ ФАКТОРЫ', side: 'positive', data: [30, 20, 10] },
      { name: 'Погода', role: 'factor', type: 'signed_weather', group: 'Погода', top_group: 'ВНЕШНИЕ ФАКТОРЫ', side: 'negative', data: [-20, -10, -5] },
      { name: 'Конкуренты', role: 'factor', type: 'signed_competitor', group: 'Конкуренты', top_group: 'КОНКУРЕНТЫ', side: 'negative', data: [-80, -60, -40] },
    ],
  };
}

/** Поэлементная сумма data по набору серий → массив длины n. */
function sumSeries(list, n) {
  const acc = new Array(n).fill(0);
  for (const s of list) for (let t = 0; t < n; t++) acc[t] += (s.data[t] ?? 0);
  return acc;
}

describe('fallbackTopGroup / topGroupOf', () => {
  it('раскладывает legacy-имена по 4 группам', () => {
    expect(fallbackTopGroup('Базовый уровень')).toBe('БАЗА');
    expect(fallbackTopGroup('Сезонность: Q1')).toBe('БАЗА');
    expect(fallbackTopGroup('Праздники: НГ')).toBe('БАЗА');
    expect(fallbackTopGroup('Цена: CPI')).toBe('ВНЕШНИЕ ФАКТОРЫ');
    expect(fallbackTopGroup('Категория: рынок')).toBe('ВНЕШНИЕ ФАКТОРЫ');
    expect(fallbackTopGroup('Конкуренты: X')).toBe('КОНКУРЕНТЫ');
    expect(fallbackTopGroup('TV федеральное')).toBe('МЕДИА');
  });

  it('точные имена без префикса (А-3): агрегированные факторы SSOT и display-имена групп', () => {
    // Фурье агрегируется под ключом 'Сезонность' — имя серии БЕЗ префикса
    expect(fallbackTopGroup('Сезонность')).toBe('БАЗА');
    expect(fallbackTopGroup('Праздники')).toBe('БАЗА');
    expect(fallbackTopGroup('База')).toBe('БАЗА');
    expect(fallbackTopGroup('Конкуренты')).toBe('КОНКУРЕНТЫ');
    expect(fallbackTopGroup('Категория')).toBe('ВНЕШНИЕ ФАКТОРЫ');
    expect(fallbackTopGroup('Цена')).toBe('ВНЕШНИЕ ФАКТОРЫ');
    expect(fallbackTopGroup('Внешние факторы')).toBe('ВНЕШНИЕ ФАКТОРЫ');
    // «Медиа» и произвольные каналы — дефолт МЕДИА
    expect(fallbackTopGroup('Медиа')).toBe('МЕДИА');
  });

  it('topGroupOf предпочитает поле top_group полю имени', () => {
    // имя выглядит как медиа, но SSOT говорит КОНКУРЕНТЫ — верим SSOT
    expect(topGroupOf({ name: 'TV', top_group: 'КОНКУРЕНТЫ', data: [] })).toBe('КОНКУРЕНТЫ');
    // нет поля → fallback по имени
    expect(topGroupOf({ name: 'Сезонность: Q1', data: [] })).toBe('БАЗА');
    // мусорное поле игнорируется
    expect(topGroupOf({ name: 'Цена: CPI', top_group: 'ЧУШЬ', data: [] })).toBe('ВНЕШНИЕ ФАКТОРЫ');
  });
});

describe('presentTopGroups', () => {
  it('возвращает непустые группы в каноническом порядке', () => {
    expect(presentTopGroups(fixture())).toEqual(['БАЗА', 'МЕДИА', 'ВНЕШНИЕ ФАКТОРЫ', 'КОНКУРЕНТЫ']);
  });
  it('пропускает отсутствующие группы', () => {
    const ds = { series: [{ name: 'TV', top_group: 'МЕДИА', data: [1] }] };
    expect(presentTopGroups(ds)).toEqual(['МЕДИА']);
  });
  it('пустой вход → []', () => {
    expect(presentTopGroups({})).toEqual([]);
    expect(presentTopGroups(null)).toEqual([]);
  });
});

describe('planViewSeries — свёрнутый режим (по умолчанию)', () => {
  const ds = fixture();
  const { plan, groups, n } = planViewSeries(ds, new Set());

  it('n = длина ряда', () => expect(n).toBe(3));

  it('4 агрегированные полосы (по одной на группу)', () => {
    expect(plan).toHaveLength(4);
    expect(plan.every((p) => p.kind === 'group')).toBe(true);
    expect(plan.map((p) => p.topGroup)).toEqual(TOP_GROUP_ORDER);
    expect(plan.map((p) => p.name)).toEqual(['База', 'Медиа', 'Внешние факторы', 'Конкуренты']);
  });

  it('БАЗА = baseline + сезонность + праздники (поэлементно)', () => {
    const baza = plan.find((p) => p.topGroup === 'БАЗА');
    // t0: 1000 + (-50) + 40 = 990;  t1: 1000+30+0=1030;  t2: 1000+80+0=1080
    expect(baza.data).toEqual([990, 1030, 1080]);
    expect(baza.memberCount).toBe(3);
  });

  it('side агрегата по знаку суммарного вклада: БАЗА/МЕДИА +, КОНКУРЕНТЫ −', () => {
    expect(plan.find((p) => p.topGroup === 'БАЗА').side).toBe('positive');
    expect(plan.find((p) => p.topGroup === 'МЕДИА').side).toBe('positive');
    expect(plan.find((p) => p.topGroup === 'КОНКУРЕНТЫ').side).toBe('negative');
    // ВНЕШНИЕ: Σ = (30-20)+(20-10)+(10-5) = 35 > 0 → positive
    expect(plan.find((p) => p.topGroup === 'ВНЕШНИЕ ФАКТОРЫ').side).toBe('positive');
  });

  it('groups отражают memberCount и expanded=false', () => {
    expect(groups.map((g) => g.expanded)).toEqual([false, false, false, false]);
    expect(groups.find((g) => g.topGroup === 'МЕДИА').memberCount).toBe(2);
  });
});

describe('planViewSeries — тождество не зависит от раскрытия', () => {
  const ds = fixture();
  const n = 3;
  const truth = sumSeries(ds.series, n); // Σ исходных серий

  const cases = [
    ['свёрнуто всё', new Set()],
    ['раскрыта БАЗА', new Set(['БАЗА'])],
    ['раскрыты БАЗА+МЕДИА', new Set(['БАЗА', 'МЕДИА'])],
    ['раскрыто всё', new Set(TOP_GROUP_ORDER)],
    ['раскрыты ВНЕШНИЕ (смешанный знак)', new Set(['ВНЕШНИЕ ФАКТОРЫ'])],
  ];

  for (const [label, expanded] of cases) {
    it(`Σ plan == Σ исходных (${label})`, () => {
      const { plan } = planViewSeries(ds, expanded);
      const got = sumSeries(plan, n);
      expect(got).toEqual(truth);
    });
  }

  it('раскрытая группа даёт её члены отдельными полосами', () => {
    const { plan } = planViewSeries(ds, new Set(['МЕДИА']));
    const media = plan.filter((p) => p.topGroup === 'МЕДИА');
    expect(media).toHaveLength(2);
    expect(media.every((p) => p.kind === 'member')).toBe(true);
    expect(media.map((p) => p.name)).toEqual(['TV', 'Digital']);
    // остальные группы остаются свёрнутыми
    expect(plan.filter((p) => p.topGroup === 'БАЗА')).toHaveLength(1);
  });

  it('полное раскрытие == исходные 8 серий', () => {
    const { plan } = planViewSeries(ds, new Set(TOP_GROUP_ORDER));
    expect(plan).toHaveLength(8);
    expect(plan.every((p) => p.kind === 'member')).toBe(true);
  });
});

describe('planViewSeries — edge cases', () => {
  it('пустой вход → пустой план', () => {
    expect(planViewSeries({}, new Set()).plan).toEqual([]);
    expect(planViewSeries(null, new Set()).plan).toEqual([]);
  });

  it('ряды разной длины добиваются нулями до max', () => {
    const ds = {
      series: [
        { name: 'A', top_group: 'МЕДИА', data: [1, 2, 3] },
        { name: 'B', top_group: 'МЕДИА', data: [10] },
      ],
    };
    const { plan, n } = planViewSeries(ds, new Set());
    expect(n).toBe(3);
    expect(plan[0].data).toEqual([11, 2, 3]);
  });

  it('невалидные значения (null/NaN) → 0', () => {
    const ds = { series: [{ name: 'A', top_group: 'МЕДИА', data: [1, null, NaN, 4] }] };
    const { plan } = planViewSeries(ds, new Set());
    expect(plan[0].data).toEqual([1, 0, 0, 4]);
  });

  it('expanded принимает и массив, и Set', () => {
    const ds = fixture();
    const a = planViewSeries(ds, ['МЕДИА']);
    const b = planViewSeries(ds, new Set(['МЕДИА']));
    expect(a.plan.filter((p) => p.topGroup === 'МЕДИА')).toHaveLength(2);
    expect(b.plan.filter((p) => p.topGroup === 'МЕДИА')).toHaveLength(2);
  });
});

describe('seasonalityPctOfBase', () => {
  it('извлекает pct_of_base из полосы сезонности', () => {
    expect(seasonalityPctOfBase(fixture())).toEqual([-5.0, 3.0, 8.0]);
  });
  it('null когда сезонности нет', () => {
    const ds = { series: [{ name: 'TV', type: 'media', top_group: 'МЕДИА', data: [1] }] };
    expect(seasonalityPctOfBase(ds)).toBeNull();
  });
  it('null когда сезонность есть, но без pct_of_base', () => {
    const ds = { series: [{ name: 'Сезонность', type: 'seasonality', top_group: 'БАЗА', data: [1, 2] }] };
    expect(seasonalityPctOfBase(ds)).toBeNull();
  });
  it('чистит невалидные значения до 0', () => {
    const ds = { series: [{ name: 'Сезонность', type: 'seasonality', top_group: 'БАЗА', data: [1], pct_of_base: [10, null, 'x', -5] }] };
    expect(seasonalityPctOfBase(ds)).toEqual([10, 0, 0, -5]);
  });
});

describe('symmetricPctBound (А-4: симметричная %-ось)', () => {
  it('наименьшее кратное 5, покрывающее max|pct| (реальные MMX/Venarus)', () => {
    expect(symmetricPctBound([-31.5, 41.6])).toBe(45); // MMX
    expect(symmetricPctBound([-38.8, 61.4])).toBe(65); // Venarus
  });
  it('точное кратное не раздувается', () => {
    expect(symmetricPctBound([50, -10])).toBe(50);
    expect(symmetricPctBound([-5])).toBe(5);
  });
  it('малые значения → минимум step', () => {
    expect(symmetricPctBound([1.2, -0.4])).toBe(5);
  });
  it('пусто/нули/мусор → step (без деления на 0 и NaN)', () => {
    expect(symmetricPctBound([])).toBe(5);
    expect(symmetricPctBound([0, 0])).toBe(5);
    expect(symmetricPctBound(null)).toBe(5);
    expect(symmetricPctBound([NaN, Infinity, -0])).toBe(5);
  });
  it('кастомный step', () => {
    expect(symmetricPctBound([12], 10)).toBe(20);
  });
});

describe('seriesIdentity (П1 анимация / П3 регрессия)', () => {
  it('groupId == top_group; id стабилен по kind/topGroup/name', () => {
    expect(seriesIdentity({ kind: 'group', topGroup: 'БАЗА', name: 'База' }))
      .toEqual({ id: 'grp:БАЗА', groupId: 'БАЗА' });
    expect(seriesIdentity({ kind: 'member', topGroup: 'БАЗА', name: 'Сезонность' }))
      .toEqual({ id: 'mem:БАЗА:Сезонность', groupId: 'БАЗА' });
  });

  it('агрегат и все его члены несут ОДИН groupId (условие morph свёрнуто↔развёрнуто)', () => {
    const ds = fixture();
    const collapsed = planViewSeries(ds, new Set());
    const expanded = planViewSeries(ds, new Set(TOP_GROUP_ORDER));
    for (const tg of TOP_GROUP_ORDER) {
      const aggId = collapsed.plan.filter((p) => p.topGroup === tg).map(seriesIdentity);
      const memIds = expanded.plan.filter((p) => p.topGroup === tg).map(seriesIdentity);
      // один агрегат на группу в свёрнутом
      expect(aggId).toHaveLength(1);
      // все id этой группы (агрегат + члены) делят groupId == tg
      for (const it of [...aggId, ...memIds]) expect(it.groupId).toBe(tg);
    }
  });

  it('id уникальны в пределах одного option (свёрнуто и развёрнуто)', () => {
    const ds = fixture();
    for (const exp of [new Set(), new Set(TOP_GROUP_ORDER), new Set(['МЕДИА'])]) {
      const ids = planViewSeries(ds, exp).plan.map((p) => seriesIdentity(p).id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });
});

describe('константы стабильны', () => {
  it('TOP_GROUP_DISPLAY покрывает весь порядок', () => {
    for (const g of TOP_GROUP_ORDER) expect(TOP_GROUP_DISPLAY[g]).toBeTruthy();
  });
});
