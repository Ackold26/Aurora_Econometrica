// @ts-nocheck – node-side тест (fs/path/process): svelte-check checkJs не имеет
// @types/node в scope, логика проверяется через vitest, не через типы.
/**
 * К3-1 (s62): запасной набор шаблонов колонок не беднее движка + поведение на нём.
 *
 * Дефект. Детектор получает шаблоны от движка; если движок не ответил при входе в
 * конвейер и кэш старше часа, ВСЁ окно работает на EMBEDDED_FALLBACK. Раньше он был
 * беднее: имена вне разбора пар и вне запасного набора (`TV (GRP)`, `OLV.views`,
 * `reach`, «охват») оставались «денежными» → физическая метрика обучалась как рубли.
 *
 * Сторож двухзвенный (vitest не вызывает Python):
 *   1. здесь – каждый шаблон снимка движка есть в EMBEDDED_FALLBACK;
 *   2. tools/test_classifier_patterns_snapshot.py – снимок == движок сейчас.
 * Поведенческие тесты – в ОБЕ стороны: физические не «денежные» И денежные не
 * стали физическими (два классификатора расходятся в обе стороны).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '@tauri-apps/api/core';
import {
  ensurePatternsLoaded,
  detectChannelUnitType,
  unitLabelFor,
  _resetCache,
} from '$lib/services/classifier-patterns.js';
import { buildExpressPlan } from '$lib/express-validate.js';
import { parseChannelMetric, groupChannelColumns } from '$lib/channel-pairs.js';

const SNAPSHOT_PATH = path.join(
  process.cwd(),
  'src/lib/services/__tests__/fixtures/engine-classifier-patterns.snapshot.json',
);
const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf8'));

/** Категории, которые фронт реально читает из набора (detectChannelUnitType). */
const FRONT_KINDS = ['monetary', 'physical'];
/**
 * Категории движка, которые фронт из шаблонов НЕ использует (классификация ролей
 * семейства target и signed идёт на стороне движка через `econ_validate`). Новая
 * категория движка, которой нет ни здесь, ни в FRONT_KINDS, – красный: решите
 * осознанно, нужна ли она запасному набору.
 */
const ENGINE_ONLY_KINDS = [
  'date', 'seasonality', 'signed_competitor', 'signed_price', 'signed_weather',
  'signed_macro', 'holiday', 'control', 'target_count', 'target_monetary',
];

/** Запасной набор в том виде, в каком его получает окно при недоступном движке. */
async function loadFallback() {
  _resetCache();
  invoke.mockReset();
  invoke.mockRejectedValue(new Error('sidecar unreachable'));
  const payload = await ensurePatternsLoaded();
  expect(payload.embedded_fallback).toBe(true);
  return payload;
}

beforeEach(() => {
  _resetCache();
});

describe('К3-1 сторож: запасной набор не беднее движка', () => {
  it('снимок не пуст (страховка от тихого нуля)', () => {
    expect(snapshot.version).toBe('v1');
    expect(snapshot.kinds.monetary.length).toBeGreaterThanOrEqual(15);
    expect(snapshot.kinds.physical.length).toBeGreaterThanOrEqual(26);
    expect(snapshot.unit_label_rules.length).toBeGreaterThanOrEqual(8);
  });

  it('у каждой категории движка есть решение: фронтовая или осознанно «только движок»', () => {
    const known = new Set([...FRONT_KINDS, ...ENGINE_ONLY_KINDS]);
    const unknown = Object.keys(snapshot.kinds).filter((k) => !known.has(k));
    expect(unknown, `новая категория движка без решения: ${unknown.join(', ')}`).toEqual([]);
  });

  for (const kind of FRONT_KINDS) {
    it(`каждый шаблон движка категории «${kind}» есть в EMBEDDED_FALLBACK`, async () => {
      const fallback = await loadFallback();
      const have = new Set(fallback.kinds[kind] ?? []);
      const missing = snapshot.kinds[kind].filter((/** @type {string} */ p) => !have.has(p));
      expect(missing, `в запасном наборе нет шаблонов движка (${kind})`).toEqual([]);
    });
  }

  // s63 №13: для ДЕНЕЖНЫХ вложения мало. Лишний денежный шаблон в запасном наборе – опасная
  // сторона: физическая колонка уходит в обучение как рубли. Поэтому запасной денежный набор
  // обязан РАВНЯТЬСЯ белому списку движка, кроме перечисленных ниже прежних узких шаблонов
  // (класс разделителей `_\s-`): они строго уже шаблонов движка (то же слово, класс уже),
  // потому лишних имён не добавляют – это проверяется поведением на пробном наборе имён.
  const LEGACY_NARROW_MONETARY = [
    '(?:^|(?<=[_\\s\\-]))spend(?:s|ing)?(?=[_\\s\\-]|$)',
    '(?:^|(?<=[_\\s\\-]))budget(?=[_\\s\\-]|$)',
    '(?:^|(?<=[_\\s\\-]))cost(?:s)?(?=[_\\s\\-]|$)',
    '(?:^|(?<=[_\\s\\-]))бюджет(?:ы|а|ов)?(?=[_\\s\\-]|$)',
    '(?:^|(?<=[_\\s\\-]))расход(?:ы|ов|а)?(?=[_\\s\\-]|$)',
    '(?:^|(?<=[_\\s\\-]))rub(?=[_\\s\\-]|$)',
  ];
  const MONETARY_PROBE_NAMES = [
    'tv_spend', 'TV spend', 'tv-budget', 'cost_tv', 'бюджет_тв', 'Расходы ТВ', 'tv_rub', 'rub',
    'TV (spend)', 'OLV.cost', 'tv/spend', "TV'budget", 'TV [rub]', 'TV–spend', 'Бюджет/GRP',
    'TV (GRP)', 'tv_grp', 'ТВ/GRP', 'Контекст (клик)', 'olv_views', 'spends', 'costly', 'budgeting',
    'tv_расходы', 'расходная', 'Прочее',
  ];

  it('№13: запасной ДЕНЕЖНЫЙ набор равен белому списку движка (лишний денежный шаблон – красный)', async () => {
    const fallback = await loadFallback();
    const engine = new Set(snapshot.kinds.monetary);
    const legacy = new Set(LEGACY_NARROW_MONETARY);
    const extra = [...new Set(fallback.kinds.monetary)].filter((p) => !engine.has(p) && !legacy.has(p));
    expect(extra, `в запасном наборе лишние денежные шаблоны, которых нет у движка`).toEqual([]);
  });

  it('№13: прежние узкие денежные шаблоны запасного набора не шире движка (поведением)', async () => {
    const fallback = await loadFallback();
    const engineRx = snapshot.kinds.monetary.map((/** @type {string} */ p) => new RegExp(p, 'i'));
    const legacyInFallback = LEGACY_NARROW_MONETARY.filter((p) => fallback.kinds.monetary.includes(p));
    for (const p of legacyInFallback) {
      const rx = new RegExp(p, 'i');
      for (const name of MONETARY_PROBE_NAMES) {
        if (rx.test(name)) {
          expect(
            engineRx.some((e) => e.test(name)),
            `«${name}»: узкий шаблон ${p} денежный, а движок – нет`,
          ).toBe(true);
        }
      }
    }
  });

  it('правила ярлыков единиц движка есть в EMBEDDED_FALLBACK', async () => {
    const fallback = await loadFallback();
    const have = new Set(fallback.unit_label_rules.map((r) => `${r.pattern}\u0000${r.label}`));
    const missing = snapshot.unit_label_rules
      .filter((/** @type {{pattern: string, label: string}} */ r) => !have.has(`${r.pattern}\u0000${r.label}`))
      .map((/** @type {{pattern: string}} */ r) => r.pattern);
    expect(missing).toEqual([]);
  });
});

describe('К3-1: классификация на ЗАПАСНОМ наборе – физические не «денежные»', () => {
  beforeEach(async () => {
    await loadFallback();
  });

  it.each([
    // из постановки: разделители скобки/точка есть только у движка
    ['TV (GRP)'],
    ['OLV.views'],
    ['tv_reach'],
    ['sessions'],
    ['охват_тв'],
    // слова только из набора движка
    ['ТВ (ГРП)'],
    ['Digital: показы'],
    ['search.impr'],
    ['email_open'],
    ['sms_delivery'],
    ['OOH контакты'],
    ['tv_contact'],
    ['аудитория_радио'],
    ['трафик_сайта'],
    ['выдача_поиска'],
    ['youtube_shown'],
    ['Radio (TRP)'],
    // прежние имена запасного набора – не потеряны
    ['TRPs бренд (W 25-54)'],
    ['Banners Показы'],
    ['Social Клики'],
    ['tv_visits'],
    ['Просмотры'],
  ])('«%s» → physical', (name) => {
    expect(detectChannelUnitType(name)).toBe('physical');
  });
});

describe('К3-1: классификация на ЗАПАСНОМ наборе – денежные не стали физическими', () => {
  beforeEach(async () => {
    await loadFallback();
  });

  it.each([
    ['tv_spend'],
    ['budget_tv'],
    ['затраты_тв'],
    ['impressions_usd'], // денежный суффикс при физическом слове → деньги
    ['TV (spend)'],
    ['TV (бюджет)'],
    ['OLV.cost'],
    ['Бюджет, руб.'],
    ['ТВ, ₽'],
    ['Social: расходы'],
    ['tv_rub'],
    ['clicks_eur'],
    ['TRP бюджет'],
    ['investment_tv'],
    ['стоимость_радио'],
    ['OLV Бюджет до НДС до АК'],
    ['Прочее'],
  ])('«%s» → monetary', (name) => {
    expect(detectChannelUnitType(name)).toBe('monetary');
  });

  it('ярлыки единиц не изменились: TRP и показы', () => {
    expect(unitLabelFor('TRPs бренд')).toBe('₽ за 1 TRP');
    expect(unitLabelFor('Banners Показы')).toBe('₽ за 1000 показов (CPM)');
  });
});

describe('К3-1: экспресс-путь на запасном наборе не отдаёт физическую колонку в обучение как рубли', () => {
  /** @param {string[]} media */
  function expressPlan(media) {
    return buildExpressPlan({
      validateResult: {
        status: 'ok',
        columns: [
          { name: 'date', role: 'date' },
          { name: 'sales_rub', role: 'kpi' },
          ...media.map((name) => ({ name, role: 'media' })),
        ],
      },
      currentKPI: 'sales',
      kpiUnavailable: false,
      kpiKind: 'monetary',
      // ровно то, что передаёт ValidateStepV13 (expressIsPhysical)
      isPhysicalChannel: (/** @type {string} */ name) => detectChannelUnitType(name) === 'physical',
    });
  }

  beforeEach(async () => {
    await loadFallback();
  });

  it('tv_spend + radio_spend + «TV (GRP)» → экспресс НЕ предлагается, колонка не в рублях', () => {
    const p = expressPlan(['tv_spend', 'radio_spend', 'TV (GRP)']);
    expect(p.eligible).toBe(false);
    expect(p.reason).toContain('TV (GRP)');
    expect(p.uniform['TV (GRP)']).toBeUndefined();
  });

  it('tv_spend + radio_spend + «OLV.views» → экспресс НЕ предлагается', () => {
    const p = expressPlan(['tv_spend', 'radio_spend', 'OLV.views']);
    expect(p.eligible).toBe(false);
    expect(p.reason).toContain('OLV.views');
    expect(p.uniform['OLV.views']).toBeUndefined();
  });

  it('обычный файл только с *_spend → экспресс по-прежнему предлагается (деньги не стали физическими)', () => {
    const p = expressPlan(['tv_spend', 'radio_spend', 'olv_spend']);
    expect(p.eligible).toBe(true);
    expect(p.mediaChannels).toEqual(['tv_spend', 'radio_spend', 'olv_spend']);
    expect(p.uniform).toEqual({
      tv_spend: 'monetary',
      radio_spend: 'monetary',
      olv_spend: 'monetary',
    });
  });

  it('рублёвые имена со скобками и точкой → экспресс предлагается', () => {
    const p = expressPlan(['TV (spend)', 'Radio (бюджет)', 'OLV.cost']);
    expect(p.eligible).toBe(true);
    expect(Object.keys(p.uniform)).toHaveLength(3);
  });
});

describe('s63 №12 и №14: голое «клик» и знаки `/ | [ ] – \'` на ЗАПАСНОМ наборе', () => {
  beforeEach(async () => {
    await loadFallback();
  });

  it.each([
    ['клик'],
    ['Клик'],
    ['клики'],
    ['кликов'],
    ['Контекст (клик)'],
    ['Контекст_клик'],
    ['Контекст [клик]'],
    ['Контекст/клик'],
    ['ТВ/GRP'],
    ['ТВ/ГРП'],
    ['TV–GRP'], // U+2013
    ['TV | GRP'],
    ['TV [GRP]'],
    ["TV'GRP"],
    ['OLV/views'],
    ['OLV [views]'],
  ])('«%s» → physical', (name) => {
    expect(detectChannelUnitType(name)).toBe('physical');
  });

  // каждый новый знак отдельно с каждой стороны слова: слева лежит `(?<=[...])`, справа `(?=[...])`
  it.each(['/', '|', '[', ']', '–', "'"])('знак «%s» – разделитель слева и справа от слова', (sep) => {
    expect(detectChannelUnitType(`TV${sep}GRP`)).toBe('physical');
    expect(detectChannelUnitType(`GRP${sep}TV`)).toBe('physical');
  });

  it.each([
    ['Бюджет ТВ / Москва'],
    ['TV | spend'],
    ['ТВ|бюджет'],
    ['tv/spend'],
    ['tv/rub'],
    ['TV–spend'],
    ["TV'spend"],
    ['Бюджет/GRP'], // «бюджет на GRP» – деньги: денежный маркер сильнее физического
    ['Cost/GRP'],
    ['Spend [GRP]'],
    ['Клик-бюджет'],
    ['Бюджет, клик'],
    ['Затраты на клики'],
    ['Контекст (клик), ₽'],
    ['ТВ [руб]'], // «руб» – не маркер ни у движка, ни здесь: деньги по умолчанию
    ['TV/OLV'],
  ])('«%s» → monetary', (name) => {
    expect(detectChannelUnitType(name)).toBe('monetary');
  });

  it.each([
    ['TV/GRPX'],
    ['TV/grpmax'],
    ['ТВ/ГРПэ'],
    ['TV|reacher'],
    ['TV/reachable'],
    ["TV'impressionist"],
    ['OLV [viewport]'],
    ['Контекст/кликабельность'],
    ['кликер'],
  ])('слово внутри длинного слова не срабатывает: «%s» → monetary', (name) => {
    expect(detectChannelUnitType(name)).toBe('monetary');
  });

  it('длинное тире U+2014 разделителем не стало', () => {
    expect(detectChannelUnitType('TV—GRP')).toBe('monetary');
  });

  it('экспресс-путь: «ТВ/GRP» и «Контекст (клик)» не уходят в обучение как рубли', () => {
    const plan = buildExpressPlan({
      validateResult: {
        status: 'ok',
        columns: [
          { name: 'date', role: 'date' },
          { name: 'sales_rub', role: 'kpi' },
          { name: 'tv_spend', role: 'media' },
          { name: 'ТВ/GRP', role: 'media' },
          { name: 'Контекст (клик)', role: 'media' },
        ],
      },
      currentKPI: 'sales',
      kpiUnavailable: false,
      kpiKind: 'monetary',
      isPhysicalChannel: (/** @type {string} */ name) => detectChannelUnitType(name) === 'physical',
    });
    expect(plan.eligible).toBe(false);
    expect(plan.uniform['ТВ/GRP']).toBeUndefined();
    expect(plan.uniform['Контекст (клик)']).toBeUndefined();
  });
});

describe('s63: парность двух классификаторов – разбор пар (channel-pairs.js) и детектор шаблонов', () => {
  // Разбор пар видит суффикс только после `_`, пробела или `-`; детектор знает больше разделителей.
  // Допустимое расхождение: разбор пар молчит (metric: null), вердикт даёт детектор через
  // isPhysicalName в groupChannelColumns. НЕДОПУСТИМО: противоположные вердикты.
  const PHYSICAL_NEW = [
    'ТВ/GRP', 'TV–GRP', 'TV [GRP]', "TV'GRP", 'ТВ|ГРП', 'TV | GRP',
    'Контекст (клик)', 'Контекст/клик', 'Контекст_клик', 'OLV [views]', 'OLV/views',
  ];
  const MONETARY_NEW = [
    'Бюджет ТВ / Москва', 'TV | spend', 'ТВ|бюджет', 'tv/spend', "TV'spend", 'TV–spend',
    'Бюджет/GRP', 'Cost/GRP', 'Spend [GRP]', 'ТВ [руб]', 'Клик-бюджет',
  ];

  beforeEach(async () => {
    await loadFallback();
  });

  it('физические имена: разбор пар не говорит «денежная» (метрика physical или молчание)', () => {
    for (const name of PHYSICAL_NEW) {
      expect(detectChannelUnitType(name), name).toBe('physical');
      expect(parseChannelMetric(name).metric, name).not.toBe('monetary');
    }
  });

  it('денежные имена: разбор пар не говорит «физическая» (метрика monetary или молчание)', () => {
    for (const name of MONETARY_NEW) {
      expect(detectChannelUnitType(name), name).toBe('monetary');
      expect(parseChannelMetric(name).metric, name).not.toBe('physical');
    }
  });

  // Известное расхождение ДО s63, не от новых знаков: запятая и скобки разделяют слова у детектора, но не
  // у разбора пар (класс `[_\s-]`): «Бюджет, клик» – детектор «деньги», разбор пар «физическая».
  // Чинится расширением трёх регулярных выражений channel-pairs.js (решение владельца), не здесь.
  it.todo('«Бюджет, клик»: разбор пар и детектор расходятся в противоположные стороны (запятая)');

  it('группировка с детектором кладёт новые физические имена в physical, денежные – в monetary', () => {
    const isPhysical = (/** @type {string} */ n) => detectChannelUnitType(n) === 'physical';
    const { byChannel } = groupChannelColumns([...PHYSICAL_NEW, ...MONETARY_NEW], isPhysical);
    const physical = Object.values(byChannel).flatMap((c) => c.physical);
    const monetary = Object.values(byChannel).flatMap((c) => c.monetary);
    for (const name of PHYSICAL_NEW) expect(physical, name).toContain(name);
    for (const name of MONETARY_NEW) expect(monetary, name).toContain(name);
    for (const name of PHYSICAL_NEW) expect(monetary, name).not.toContain(name);
  });
});
