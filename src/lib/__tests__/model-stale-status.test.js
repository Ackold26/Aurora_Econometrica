/**
 * STATE-1 (2026-06-02): ложный рассинхрон «было 7 стало 10» сразу после обучения.
 * Корень: lastTrainedConfig.media = обученное подмножество (enabled, напр. 7), а
 * modelStaleStatus сравнивал со ВСЕМИ media-ролями (10). Фикс: сравнивать с текущим
 * включённым подмножеством (modelChannelEnabled).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
  modelData,
  validateData,
  lastTrainedConfig,
  modelChannelEnabled,
  modelStaleStatus,
} from '../project-state.js';

/** @param {string[]} media @param {string[]} control @param {string} kpi */
function setValidation(media, control, kpi) {
  const columns = [
    ...media.map((name) => ({ name, role: 'media' })),
    ...control.map((name) => ({ name, role: 'control' })),
    { name: kpi, role: 'kpi' },
  ];
  validateData.set(/** @type {any} */ ({ result: { columns } }));
}

beforeEach(() => {
  modelData.set(/** @type {any} */ ({ diagnostics: { r2: 0.9 }, channelParams: {}, picklePath: 'x', normalization: null }));
  lastTrainedConfig.set({ kpi: 'Sales', media: ['A', 'B', 'C'], control: ['X'] });
  modelChannelEnabled.set({});
});

describe('STATE-1 modelStaleStatus сравнивает с обученным подмножеством', () => {
  it('обучение на 3 из 4 каналов → НЕ stale сразу после обучения', () => {
    // 4 media-роли, но обучали на 3 (D выключен) — раньше давало ложный «было 3 стало 4»
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true, D: false });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false);
    expect(st.diff).toEqual([]);
  });

  it('включение ранее выключенного канала → stale', () => {
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({ A: true, B: true, C: true, D: true }); // теперь 4 включено
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Медиа-каналы: было 3, стало 4/);
  });

  it('смена KPI → stale независимо от каналов', () => {
    setValidation(['A', 'B', 'C'], ['X'], 'Revenue'); // KPI сменился
    modelChannelEnabled.set({ A: true, B: true, C: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/KPI/);
  });

  it('guard: пустой enabled-map (после reload) → media-diff пропущен, нет ложного stale', () => {
    setValidation(['A', 'B', 'C', 'D'], ['X'], 'Sales');
    modelChannelEnabled.set({}); // enabled-инфо ещё нет
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(false); // не флагуем media по всем ролям
  });

  it('изменение контрольных переменных → stale', () => {
    setValidation(['A', 'B', 'C'], ['X', 'Y'], 'Sales'); // добавлен контрольный Y
    modelChannelEnabled.set({ A: true, B: true, C: true });
    const st = get(modelStaleStatus);
    expect(st.stale).toBe(true);
    expect(st.diff.join(' ')).toMatch(/Контрольные/);
  });
});
