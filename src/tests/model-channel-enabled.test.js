/**
 * LOAD-1 (2026-06-07): persist modelChannelEnabled (toggle ВКЛ/ВЫКЛ каналов).
 *
 * Баг: на reload ConfigPanel $effect ре-init channelEnabled из `zeros_pct>80` default →
 * ручной disabled low-zeros канал РЕ-ВКЛЮЧАЛСЯ → re-train с иным media-набором = иная
 * модель. Фикс: persist toggle в project.json (model_channel_enabled) + seed
 * `resolveChannelEnabled` где persisted имеет приоритет над zeros-default.
 *
 * Тестирует чистую `resolveChannelEnabled` (логика seed-а $effect-а, вынесенная для
 * тестируемости без рендера ConfigPanel). Wiring в ConfigPanel ($effect зовёт её с
 * get(activeProject)?.model_channel_enabled) + persist в trainModel верифицированы чтением.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { resolveChannelEnabled, activeProject } from '$lib/project-state.js';

const lowZeros = { name: 'digital_spend', stats: { zeros_pct: 10 } };
const highZeros = { name: 'rare_promo', stats: { zeros_pct: 95 } };

describe('resolveChannelEnabled — seed toggle каналов (LOAD-1)', () => {
  it('persisted пуст → zeros-default (low<80 вкл, high>80 выкл)', () => {
    const r = resolveChannelEnabled([lowZeros, highZeros], {});
    expect(r).toEqual({ digital_spend: true, rare_promo: false });
  });

  it('persisted=null/undefined → zeros-default (legacy/fresh проект)', () => {
    expect(resolveChannelEnabled([lowZeros], null)).toEqual({ digital_spend: true });
    expect(resolveChannelEnabled([lowZeros], undefined)).toEqual({ digital_spend: true });
  });

  it('БАГ-ФИКС: persisted false на low-zeros канале → остаётся ВЫКЛ (не ре-включается)', () => {
    const r = resolveChannelEnabled([lowZeros], { digital_spend: false });
    expect(r.digital_spend).toBe(false); // persisted приоритет над zeros-default (true)
  });

  it('persisted true на high-zeros канале → остаётся ВКЛ (override default)', () => {
    const r = resolveChannelEnabled([highZeros], { rare_promo: true });
    expect(r.rare_promo).toBe(true); // persisted приоритет над zeros-default (false)
  });

  it('новый канал (нет в persisted) → zeros-default; известный → persisted', () => {
    const newCh = { name: 'new_tv', stats: { zeros_pct: 5 } };
    const r = resolveChannelEnabled([lowZeros, newCh], { digital_spend: false });
    expect(r).toEqual({ digital_spend: false, new_tv: true });
  });

  it('канал без zeros-статы → ВКЛ по умолчанию (0 нулей)', () => {
    const r = resolveChannelEnabled([{ name: 'no_stats' }], {});
    expect(r.no_stats).toBe(true);
  });

  it('пустой/невалидный media-список → {} (нет падения)', () => {
    expect(resolveChannelEnabled([], {})).toEqual({});
    expect(resolveChannelEnabled(null, {})).toEqual({});
    expect(resolveChannelEnabled([{ stats: {} }], {})).toEqual({}); // нет name → пропуск
  });
});

describe('LOAD-1: контракт seed-source (activeProject.model_channel_enabled)', () => {
  // Закрывает LOW-gap адверс. верификации: пинит, что seed-источник ConfigPanel $effect-а =
  // activeProject.model_channel_enabled. Регрессия порядка load (validateData до activeProject)
  // или смена поля молча переоткрыла бы баг при зелёных pure-тестах. Здесь — как $effect:
  // resolveChannelEnabled(media, get(activeProject)?.model_channel_enabled).
  beforeEach(() => activeProject.set(null));

  it('round-trip: persisted disabled канал на reload остаётся ВЫКЛ', () => {
    activeProject.set(/** @type {any} */ ({
      id: 'p1', model_channel_enabled: { digital_spend: false, rare_promo: false },
    }));
    const seeded = resolveChannelEnabled([lowZeros, highZeros], get(activeProject)?.model_channel_enabled);
    expect(seeded.digital_spend).toBe(false); // ручной disable пережил reload (баг закрыт)
    expect(seeded.rare_promo).toBe(false);
  });

  it('legacy/fresh проект (нет model_channel_enabled) → zeros-default', () => {
    activeProject.set(/** @type {any} */ ({ id: 'legacy', kpi_column: 'sales' }));
    const seeded = resolveChannelEnabled([lowZeros, highZeros], get(activeProject)?.model_channel_enabled);
    expect(seeded).toEqual({ digital_spend: true, rare_promo: false }); // pre-fix поведение
  });
});
