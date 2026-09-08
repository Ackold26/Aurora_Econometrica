/**
 * Живой прогон 08.09.2026: создание нового проекта показывало результаты ПРЕДЫДУЩЕГО.
 * На диске у нового проекта `models/` и `results/` пусты, а шаг «Модель» рапортовал
 * «Модель обучена! MQS = 70, R² = 0,825» — числа чужого набора данных.
 *
 * Сторож держит два свойства сразу, потому что лечение одного легко ломает второе:
 *   1) чужие РЕЗУЛЬТАТЫ не переносятся в новый проект;
 *   2) незавершённый ИМПОРТ пользователя переживает создание проекта — ради этого
 *      сброс когда-то и не звали вовсе (заметка в `ProjectSelector.svelte`).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
  importData,
  validateData,
  modelData,
  decomposeData,
  optimizeData,
  pipelineStepMeta,
  resetResultsKeepImport,
} from '$lib/project-state.js';

describe('создание нового проекта', () => {
  beforeEach(() => {
    importData.set({ file: { name: 'клиентский.xlsx' }, columns: ['date', 'sales_rub'], rows: 48 });
    validateData.set({ result: { ok: true }, correlationMatrix: [[1]], columnHistograms: {} });
    modelData.set({
      diagnostics: { mqs: 70, r2: 0.825 },
      channelParams: { tv_spend: {} },
      picklePath: 'C:/чужой/проект/models/latest.pkl',
      normalization: {},
    });
    decomposeData.set({ waterfall: { labels: ['Baseline'], values: [1], types: ['total'] } });
    optimizeData.set({ expected_lift_pct: 3.4 });
    pipelineStepMeta.set([
      { status: 'complete', errorMessage: null },
      { status: 'complete', errorMessage: null },
      { status: 'complete', errorMessage: null },
      { status: 'complete', errorMessage: null },
      { status: 'complete', errorMessage: null },
      { status: 'locked', errorMessage: null },
      { status: 'ready', errorMessage: null },
    ]);
  });

  it('не переносит в новый проект результаты предыдущего', () => {
    resetResultsKeepImport();
    expect(get(modelData).channelParams, 'модель чужого проекта обязана исчезнуть').toBeNull();
    expect(get(modelData).diagnostics, 'диагностика чужой модели обязана исчезнуть').toBeNull();
    expect(get(decomposeData), 'декомпозиция чужого проекта обязана исчезнуть').toBeNull();
    expect(get(optimizeData), 'оптимизация чужого проекта обязана исчезнуть').toBeNull();
    expect(get(validateData).result, 'валидация чужого проекта обязана исчезнуть').toBeNull();
  });

  it('снимает зелёные отметки шагов, кроме «Импорта»', () => {
    resetResultsKeepImport();
    const meta = get(pipelineStepMeta);
    expect(meta[0].status, 'отметка шага «Импорт» сохраняется').toBe('complete');
    expect(meta[2].status, 'шаг «Модель» не может остаться завершённым в пустом проекте').not.toBe('complete');
    expect(meta[3].status, 'шаг «Декомпозиция» тоже').not.toBe('complete');
  });

  it('сохраняет незавершённый импорт пользователя', () => {
    resetResultsKeepImport();
    const imp = get(importData);
    expect(imp.file, 'файл, уже перетащенный пользователем, обязан пережить создание проекта').not.toBeNull();
    expect(imp.rows).toBe(48);
  });
});
