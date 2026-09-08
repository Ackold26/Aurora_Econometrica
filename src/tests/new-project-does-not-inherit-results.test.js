/**
 * Живой прогон 08.09.2026: создание нового проекта показывало результаты ПРЕДЫДУЩЕГО.
 * На диске у нового проекта `models/` и `results/` пусты, а шаг «Модель» рапортовал
 * «Модель обучена! MQS = 70, R² = 0,825» — числа чужого набора данных.
 *
 * Внешний аудит того же дня показал, что компромисс «сохранить импорт» был неверен:
 * обещание не выполнялось (асинхронное восстановление с диска перезаписывало отметки
 * ПОСЛЕ синхронного сброса), а сохранённый импорт принадлежал прошлому проекту — путь,
 * на котором доступна «Валидация», посчитал бы данные проекта А в каталог проекта Б.
 * Поэтому снимается ВСЁ. Сторож держит это свойство целиком, включая три хранилища,
 * которые переживали смену проекта молча.
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
  optimizeLiveState,
  forecastContext,
  lastTrainedConfig,
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
    optimizeLiveState.set({
      channelBudgets: { tv_spend: 100 },
      channelMinPct: { tv_spend: 20 },
      channelMaxPct: { tv_spend: 200 },
      globalMinPct: 20,
      globalMaxPct: 200,
    });
    forecastContext.set({ granularity: 'weekly', seasonalityDetected: true });
    lastTrainedConfig.set({ media: ['tv_spend'], kpi: 'sales_rub' });
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

  it('снимает зелёные отметки со ВСЕХ шагов, включая «Импорт»', () => {
    resetResultsKeepImport();
    const meta = get(pipelineStepMeta);
    expect(meta[0].status, 'отметка шага «Импорт» относится к файлу прошлого проекта').not.toBe('complete');
    expect(meta[2].status, 'шаг «Модель» не может остаться завершённым в пустом проекте').not.toBe('complete');
    expect(meta[3].status, 'шаг «Декомпозиция» тоже').not.toBe('complete');
  });

  it('снимает импорт прошлого проекта', () => {
    resetResultsKeepImport();
    const imp = get(importData);
    expect(imp.file, 'файл принадлежит прошлому проекту — его нельзя оставлять новому').toBeNull();
    expect(imp.rows, 'число строк прошлого файла тоже').toBeNull();
  });

  it('снимает три хранилища, переживавшие смену проекта молча', () => {
    resetResultsKeepImport();
    expect(get(optimizeLiveState).channelBudgets, 'коридоры и бюджеты прошлого проекта').toEqual({});
    expect(get(forecastContext), 'гранулярность и «сезонность обнаружена» от чужой модели').toBeNull();
    expect(get(lastTrainedConfig), 'конфигурация, по которой судится «модель устарела»').toBeNull();
  });
});
