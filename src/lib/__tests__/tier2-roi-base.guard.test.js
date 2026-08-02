/**
 * Сторож базы окупаемости в словах советника.
 *
 * ЗАЧЕМ. Расчёт продукта корректен в обоих режимах: «Выручка» и «Прибыль» —
 * полноценные метрики (`utils/kpi_registry.py`), а когда экономика не задана,
 * абсолютные пороги окупаемости честно отключаются
 * (`engines/channel_action.py`, ветка `money_roi_unavailable`). Неточной была
 * РЕЧЬ: правило 7 советника до 2026-08-02 говорило «прибылен канал или
 * убыточен» безотносительно выбранной метрики. В режиме выручки ROI=1 — это
 * окупаемость по обороту, из которой прибыльность не следует: себестоимость в
 * выручке не вычтена. Клиент читал вывод о прибыли там, где модель считала
 * оборот.
 *
 * Тест держит границу поведением: база выводится единственной функцией, доезжает
 * в факты и названа в правилах. Возврат к безусловной формулировке красит тест.
 */
import { describe, expect, it } from 'vitest';

import { roiBase, roiBaseNote } from '../kpi-aware-formatting.js';
import { buildTier2Context, STEP, TIER2_SYSTEM_RULES } from '../tier2-context.js';

describe('roiBase — база выводится из выбранной метрики', () => {
  it('режим «Выручка» → оборот', () => {
    expect(roiBase({ kpiType: 'sales', kpiKind: 'monetary' })).toBe('оборот');
  });

  it('устаревший ключ revenue → тоже оборот', () => {
    // Старые проекты сохраняли kpi_type='revenue' (дубликат убран из выбора
    // в v2.1.0, но в сохранённых проектах остался) — они не должны провалиться
    // в «не определена» и потерять слова про окупаемость.
    expect(roiBase({ kpiType: 'revenue', kpiKind: 'monetary' })).toBe('оборот');
  });

  it('денежный проект без паспорта KPI (legacy) → оборот, а не «не определена»', () => {
    // У старых проектов kpiType нет вовсе, а ROI исторически считался от продаж
    // в рублях. Уронить их в «не определена» значило бы отобрать слова про
    // окупаемость без причины — регресс там, где ошибки не было.
    expect(roiBase({ kpiKind: 'monetary', kpiType: null })).toBe('оборот');
  });

  it('режим «Прибыль» → прибыль', () => {
    expect(roiBase({ kpiType: 'profit', kpiKind: 'monetary' })).toBe('прибыль');
  });

  it('счётный режим с маржой на единицу → прибыль', () => {
    expect(roiBase({ kpiType: 'sales_packs', kpiKind: 'count', vpcu: 42 })).toBe('прибыль');
  });

  it('счётный режим без маржи → база не определена (пороги в движке отключены)', () => {
    expect(roiBase({ kpiType: 'leads', kpiKind: 'count' })).toBe('не определена');
    expect(roiBase({ kpiType: 'leads', kpiKind: 'count', vpcu: 0 })).toBe('не определена');
  });

  it('режим эффективности считает доли, а не деньги → базы нет', () => {
    expect(roiBase({ kpiKind: 'monetary', kpiType: 'sales', mode: 'effectiveness' })).toBe(
      'не определена',
    );
  });

  it('ничего не известно → база не определена', () => {
    expect(roiBase({})).toBe('не определена');
    expect(roiBase(null)).toBe('не определена');
    expect(roiBase({ kpiType: 'share_of_market', kpiKind: 'proportional' })).toBe(
      'не определена',
    );
  });
});

describe('roiBaseNote — пояснение соответствует базе', () => {
  it('при обороте прямо предупреждает, что прибыльность не следует', () => {
    const note = roiBaseNote({ kpiType: 'sales', kpiKind: 'monetary' });
    expect(note).toContain('по обороту');
    expect(note).toContain('не следует');
  });

  it('при прибыли говорит о прибыли и не путает базы', () => {
    const note = roiBaseNote({ kpiType: 'profit', kpiKind: 'monetary' });
    expect(note).toContain('по прибыли');
    expect(note).not.toContain('по обороту');
  });

  it('без экономики честно называет пороги отключёнными', () => {
    const note = roiBaseNote({ kpiType: 'leads', kpiKind: 'count' });
    expect(note).toContain('отключены');
  });
});

describe('база доезжает в факты советника', () => {
  /** @param {Record<string, any>} [extra] */
  const call = (extra) =>
    buildTier2Context({
      step: STEP.DECOMPOSE,
      question: 'Какие каналы окупаются?',
      dec: { channels: [] },
      ...extra,
    });

  it('поле roi_base есть в фактах при режиме выручки', () => {
    expect(call({ kpiType: 'sales', kpiKind: 'monetary' }).facts.roi_base).toBe('оборот');
  });

  it('поле roi_base есть в фактах при режиме прибыли', () => {
    expect(call({ kpiType: 'profit', kpiKind: 'monetary' }).facts.roi_base).toBe('прибыль');
  });

  it('без переданной метрики поле присутствует и честно говорит «не определена»', () => {
    // Поле обязано быть всегда: отсутствие ключа советник трактовал бы как
    // «спрашивать не о чем» и вернулся бы к вольной формулировке.
    expect(call({}).facts.roi_base).toBe('не определена');
  });
});

describe('правило 7 называет базу, а не судит о прибыли безусловно', () => {
  // TIER2_SYSTEM_RULES экспортируется уже склеенной строкой, не массивом.
  const rules = TIER2_SYSTEM_RULES;

  it('правила ссылаются на поле roi_base', () => {
    expect(rules).toContain('roi_base');
  });

  it('безусловной формулировки «прибылен канал или убыточен» больше нет', () => {
    expect(rules).not.toContain('прибылен канал или убыточен');
  });

  it('при базе «оборот» слова о прибыли прямо запрещены', () => {
    expect(rules).toMatch(/оборот[\s\S]{0,400}НЕЛЬЗЯ/);
  });

  it('при неопределённой базе запрещено и слово «окупается»', () => {
    expect(rules).toMatch(/не определена[\s\S]{0,400}не используй/);
  });
});
