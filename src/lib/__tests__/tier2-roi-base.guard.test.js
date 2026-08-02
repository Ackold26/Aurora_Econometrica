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

import {
  buildTier2Context,
  resolveRoiBase,
  STEP,
  TIER2_SYSTEM_RULES,
} from '../tier2-context.js';

describe('resolveRoiBase — база выводится из выбранной метрики', () => {
  it('режим «Выручка» → оборот', () => {
    expect(resolveRoiBase({ kpiType: 'sales', kpiKind: 'monetary' })).toBe('оборот');
  });

  it('устаревший ключ revenue → тоже оборот', () => {
    // Старые проекты сохраняли kpi_type='revenue' (дубликат убран из выбора
    // в v2.1.0, но в сохранённых проектах остался) — они не должны провалиться
    // в «не определена» и потерять слова про окупаемость.
    expect(resolveRoiBase({ kpiType: 'revenue', kpiKind: 'monetary' })).toBe('оборот');
  });

  it('режим «Прибыль» → прибыль', () => {
    expect(resolveRoiBase({ kpiType: 'profit', kpiKind: 'monetary' })).toBe('прибыль');
  });

  it('счётный режим с маржой на единицу → прибыль', () => {
    expect(
      resolveRoiBase({ kpiType: 'sales_packs', kpiKind: 'count', valuePerCountUnit: 42 }),
    ).toBe('прибыль');
  });

  it('счётный режим без маржи → база не определена (пороги в движке отключены)', () => {
    expect(resolveRoiBase({ kpiType: 'leads', kpiKind: 'count' })).toBe('не определена');
    expect(
      resolveRoiBase({ kpiType: 'leads', kpiKind: 'count', valuePerCountUnit: 0 }),
    ).toBe('не определена');
  });

  it('метрика неизвестна или не выбрана → база не определена, а не «оборот» по умолчанию', () => {
    // Недоказанное не выдаём за доказанное: молчаливый дефолт «оборот» вернул бы
    // ровно ту ошибку, ради которой заведён этот сторож.
    expect(resolveRoiBase({})).toBe('не определена');
    expect(resolveRoiBase({ kpiType: 'share_of_market', kpiKind: 'proportional' })).toBe(
      'не определена',
    );
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
