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
