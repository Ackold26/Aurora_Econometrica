/**
 * s61 К2-6: признак ошибки шага «Валидация» (`syncStepLockAfterValidate` в панели
 * подсказок) считает медиа по включённым колонкам И реагирует на смену карты
 * включённости без смены результата проверки.
 *
 * Проверка поведением (панель отрисована), а не сторожем по тексту исходника:
 * при чтении карты через `get()` эффект на её смену не подписан – ложная ошибка
 * «Модель не определяется» повисает, пока не изменится результат проверки.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  pipelineCurrentStep,
  pipelineStepMeta,
  importData,
  validateData,
  modelChannelEnabled,
  setStepError,
} from '$lib/project-state.js';
import InsightsPanel from '$lib/components/pipeline/InsightsPanel.svelte';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));

// Развязка «карта из подписки» и «карта из стора»: в работе приложения они равны всегда, поэтому
// различить, какую из них использует функция проверки шага, можно только подменив чтение стора.
// Подмена включается на один тест и касается только стора включённости; остальное читается как обычно.
const probe = vi.hoisted(() => ({ on: false, store: /** @type {any} */ (null), map: /** @type {any} */ (null) }));
vi.mock('svelte/store', async (importOriginal) => {
  const orig = /** @type {any} */ (await importOriginal());
  return { ...orig, get: (/** @type {any} */ s) => (probe.on && s === probe.store ? probe.map : orig.get(s)) };
});

const MEDIA = Array.from({ length: 10 }, (_, i) => `ch${i}_spend`);

beforeEach(() => {
  probe.on = false;
  probe.store = modelChannelEnabled;
  vi.clearAllMocks();
  vi.mocked(invoke).mockResolvedValue(null);
  modelChannelEnabled.set({});
  importData.set({ file: { name: 'tiny.xlsx' }, columns: [], rows: 9 });
  // 9 наблюдений, 10 медиа-колонок: по ролям параметров больше, чем точек (ошибка шага);
  // при четырёх выключенных – 6 + свободный член < 9 (ошибки нет).
  validateData.set({
    result: {
      status: 'ok',
      file: { rows: 9 },
      detected: {},
      columns: [{ name: 'sales', role: 'kpi' }, ...MEDIA.map((name) => ({ name, role: 'media' }))],
    },
    correlationMatrix: null,
    columnHistograms: null,
  });
  pipelineCurrentStep.set(1);
});

const stepStatus = () => get(pipelineStepMeta)[1]?.status;

describe('К2-6: признак ошибки шага реагирует на карту включённости', () => {
  it('без карты: 10 медиа на 9 наблюдений – ошибка шага', async () => {
    render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });
    await waitFor(() => expect(stepStatus()).toBe('error'));
  });

  it('карту сменили БЕЗ смены результата проверки – ошибка снимается', async () => {
    render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });
    await waitFor(() => expect(stepStatus()).toBe('error'));
    modelChannelEnabled.set(Object.fromEntries(MEDIA.slice(0, 4).map((n) => [n, false])));
    await waitFor(() => expect(stepStatus(), 'карта изменилась, а ошибка шага осталась – эффект не подписан на карту').not.toBe('error'));
  });

  it('и в обратную сторону: настоящая ошибка появляется после включения колонок обратно', async () => {
    modelChannelEnabled.set(Object.fromEntries(MEDIA.slice(0, 4).map((n) => [n, false])));
    render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });
    await waitFor(() => expect(stepStatus()).not.toBe('error'));
    modelChannelEnabled.set({});
    await waitFor(() => expect(stepStatus(), 'все колонки включены обратно, а ошибки нет').toBe('error'));
  });
});

describe('Б3-1c: проверка шага берёт карту включённости из переданного аргумента, а не из стора', () => {
  const FOUR_OFF = Object.fromEntries(MEDIA.slice(0, 4).map((n) => [n, false]));

  it('в подписке все колонки включены (ошибка), а чтение стора вернуло бы четыре выключенных – ошибка остаётся', async () => {
    setStepError(1, null); // старое состояние не должно подменять результат: ошибки нет до проверки
    probe.map = FOUR_OFF;
    probe.on = true;
    render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });
    await waitFor(() => expect(stepStatus(), 'функция проверки шага взяла карту не из переданного аргумента').toBe('error'));
  });

  it('в подписке четыре выключены (ошибки нет), а чтение стора вернуло бы пустую карту – ошибки нет', async () => {
    setStepError(1, 'старая ошибка'); // старое состояние обратное: ошибка должна именно сняться проверкой
    modelChannelEnabled.set(FOUR_OFF);
    probe.map = {};
    probe.on = true;
    render(InsightsPanel, { props: { collapsed: false, onToggle: () => {} } });
    await waitFor(() => expect(stepStatus()).not.toBe('error'));
    // и позже, после перерисовки, статус не переключается на результат по подменённому чтению
    await new Promise((r) => setTimeout(r, 50));
    expect(stepStatus(), 'функция проверки шага взяла карту не из переданного аргумента').not.toBe('error');
  });
});
