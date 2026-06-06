/**
 * LOAD-1 пара (2026-06-07): persist analysisMode + cpp-гейт в trainModel.
 *
 * Тестирует ре-гидрацию analysis_mode из durable project.json (activeProject.subscribe)
 * + `analysisModeIsPersisted()` флаг (D-2 legacy fail-open) + mixed→expertMode (D-5),
 * и композитное решение cpp-гейта обучения (флаг && !cppSatisfied), которое ConfigPanel.
 * trainModel вычисляет перед обучением.
 *
 * Драйвит РЕАЛЬНЫЙ activeProject store (subscribe зарегистрирован на загрузке модуля) —
 * в отличие от save-kpi-persistence.test.js, который симулирует логику. Другие subscribe
 * (unitCosts/channelCategories/count-KPI) толерантны к минимальному ProjectInfo (?? {}).
 *
 * Адверсариальный дизайн-аудит ДО реализации вскрыл 5 дыр; этот файл лочит ключевые:
 *   D-2 (legacy без analysis_mode → гейт fail-open, иначе регрессия на effectiveness-проектах)
 *   D-5 (persisted 'mixed' → expertMode.set(true), иначе INV-30 рассинхрон в Manager-UI)
 *   id-guard (mid-session set того же проекта НЕ клоббит несохранённый выбор режима)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import {
  activeProject, activeProjectId, analysisMode, expertMode, perChannelInput,
  analysisModeIsPersisted, cppSatisfied,
} from '$lib/project-state.js';

/**
 * Композитное решение cpp-гейта обучения — точная копия условия из
 * ConfigPanel.trainModel: блокировать обучение ТОЛЬКО когда режим достоверно
 * ре-гидрирован (флаг) И cpp-гейт не удовлетворён.
 * @param {{channels: string[], perChannelInput?: Record<string,string>, unitCosts?: Record<string,number>}} snap
 * @returns {boolean} true → обучение блокируется
 */
function trainGateBlocks(snap) {
  return analysisModeIsPersisted() && !cppSatisfied({
    channels: snap.channels,
    perChannelInput: snap.perChannelInput ?? {},
    unitCosts: snap.unitCosts ?? {},
    analysisMode: get(analysisMode),
  });
}

beforeEach(() => {
  // Деселект → мой subscribe сбрасывает analysisMode='roi' + флаг=false.
  activeProject.set(null);
  expertMode.set(false);
});

describe('LOAD-1: ре-гидрация analysis_mode (activeProject.subscribe)', () => {
  it('persisted analysis_mode → стор выставлен + флаг true', () => {
    activeProject.set(/** @type {any} */ ({ id: 'p1', analysis_mode: 'effectiveness' }));
    expect(get(analysisMode)).toBe('effectiveness');
    expect(analysisModeIsPersisted()).toBe(true);
  });

  it('D-2 legacy: НЕТ analysis_mode → стор НЕ клоббится + флаг false', () => {
    // Симулируем mode-defaults/импорт, выставивший режим до загрузки проекта.
    analysisMode.set('effectiveness');
    // Legacy-проект (создан до фикса) без поля analysis_mode.
    activeProject.set(/** @type {any} */ ({ id: 'p-legacy', kpi_column: 'sales' }));
    expect(get(analysisMode)).toBe('effectiveness'); // НЕ сброшен в 'roi'
    expect(analysisModeIsPersisted()).toBe(false);   // → гейт fail-open
  });

  it('D-5 mixed: persisted "mixed" → expertMode форсится true (INV-30 sync)', () => {
    expect(get(expertMode)).toBe(false);
    activeProject.set(/** @type {any} */ ({ id: 'p-mixed', analysis_mode: 'mixed' }));
    expect(get(analysisMode)).toBe('mixed');
    expect(get(expertMode)).toBe(true); // mixed-карточка видна только в Expert
  });

  it('id-guard: mid-session set ТОГО ЖЕ проекта НЕ клоббит несохранённый выбор', () => {
    activeProject.set(/** @type {any} */ ({ id: 'p2', analysis_mode: 'roi' }));
    expect(get(analysisMode)).toBe('roi');
    // Юзер сменил режим в селекторе (стор), но НЕ обучил → disk остаётся 'roi'.
    analysisMode.set('effectiveness');
    // Mid-session activeProject.set (напр. UnitCostsPanel.save) с тем же id и stale disk.
    activeProject.set(/** @type {any} */ ({ id: 'p2', analysis_mode: 'roi' }));
    expect(get(analysisMode)).toBe('effectiveness'); // НЕ затёрт обратно в 'roi'
  });

  it('смена проекта (новый id) ре-гидрирует с диска', () => {
    activeProject.set(/** @type {any} */ ({ id: 'pA', analysis_mode: 'roi' }));
    expect(get(analysisMode)).toBe('roi');
    activeProject.set(/** @type {any} */ ({ id: 'pB', analysis_mode: 'effectiveness' }));
    expect(get(analysisMode)).toBe('effectiveness'); // id сменился → ре-гидрация
  });

  it('транзиция persisted→legacy→persisted: флаг и режим восстанавливаются при возврате', () => {
    // Защита от рефактора id-guard (gap из адверс. верификации реализации).
    activeProject.set(/** @type {any} */ ({ id: 'A', analysis_mode: 'effectiveness' }));
    expect(get(analysisMode)).toBe('effectiveness');
    expect(analysisModeIsPersisted()).toBe(true);
    // Switch на legacy B (нет analysis_mode) → флаг false, режим НЕ клоббится.
    activeProject.set(/** @type {any} */ ({ id: 'B', kpi_column: 'sales' }));
    expect(analysisModeIsPersisted()).toBe(false);
    // Возврат к A (id сменился B→A) → ре-гидрация + флаг снова true.
    activeProject.set(/** @type {any} */ ({ id: 'A', analysis_mode: 'effectiveness' }));
    expect(get(analysisMode)).toBe('effectiveness');
    expect(analysisModeIsPersisted()).toBe(true);
  });

  it('деселект (!p) → сброс в "roi" + флаг false', () => {
    activeProject.set(/** @type {any} */ ({ id: 'p4', analysis_mode: 'effectiveness' }));
    expect(analysisModeIsPersisted()).toBe(true);
    activeProject.set(null);
    expect(get(analysisMode)).toBe('roi');
    expect(analysisModeIsPersisted()).toBe(false);
  });
});

describe('LOAD-1: cpp-гейт обучения (флаг && !cppSatisfied) — truth-table', () => {
  it('D-2 legacy (флаг false) + physical+roi+no-cost → НЕ блокирует (fail-open)', () => {
    // Ключевая защита от регрессии: гейт молчит для legacy-проектов без analysis_mode.
    analysisMode.set('roi');
    activeProject.set(/** @type {any} */ ({ id: 'leg', kpi_column: 'sales' })); // legacy → флаг false
    expect(analysisModeIsPersisted()).toBe(false);
    expect(trainGateBlocks({ channels: ['tv_trp'], unitCosts: {} })).toBe(false);
  });

  it('persisted roi + physical+no-cost → БЛОКИРУЕТ (ROI-артефакт)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'r1', analysis_mode: 'roi' }));
    expect(trainGateBlocks({ channels: ['tv_trp'], unitCosts: {} })).toBe(true);
  });

  it('persisted roi + physical + unit_cost>0 → НЕ блокирует', () => {
    activeProject.set(/** @type {any} */ ({ id: 'r2', analysis_mode: 'roi' }));
    expect(trainGateBlocks({ channels: ['tv_trp'], unitCosts: { tv_trp: 1500 } })).toBe(false);
  });

  it('persisted effectiveness + physical+no-cost → НЕ блокирует (физ.метрики валидны)', () => {
    // Главный кейс пары: effectiveness-проект после reload НЕ блокируется ложно.
    activeProject.set(/** @type {any} */ ({ id: 'e1', analysis_mode: 'effectiveness' }));
    expect(trainGateBlocks({ channels: ['tv_trp'], unitCosts: {} })).toBe(false);
  });

  it('persisted roi + monetary канал → НЕ блокирует (бюджет в ₽)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'r3', analysis_mode: 'roi' }));
    expect(trainGateBlocks({ channels: ['digital_spend'], unitCosts: {} })).toBe(false);
  });

  it('гейт по ENABLED-каналам: отключённый physical не блокирует (только monetary в наборе)', () => {
    // Снимок гейта строится из enabledChannels (не все media) → отключённый physical-канал
    // без unit_cost не обучается → не блокирует. Передаём только включённый monetary.
    activeProject.set(/** @type {any} */ ({ id: 'r4', analysis_mode: 'roi' }));
    expect(trainGateBlocks({ channels: ['digital_spend'], unitCosts: {} })).toBe(false);
  });
});

describe('LOAD-1 D-1: ре-гидрация perChannelInput закрывает ложный over-block', () => {
  // Гейт читает get(perChannelInput); проверяем что rehydrated override снимает блок.
  function gateBlocksFromStore(channels, unitCosts) {
    return analysisModeIsPersisted() && !cppSatisfied({
      channels, perChannelInput: get(perChannelInput),
      unitCosts: unitCosts ?? {}, analysisMode: get(analysisMode),
    });
  }

  it('persisted pci override physical-имени на monetary → roi+no-cost НЕ блокирует', () => {
    // tv_trp детектится physical; юзер пометил monetary (колонка уже в ₽). До D-1 reload
    // терял override → детектор→physical→roi+no-cost→ложный блок. Теперь pci ре-гидрирован.
    activeProject.set(/** @type {any} */ ({ id: 'd1a', analysis_mode: 'roi', per_channel_input: { tv_trp: 'monetary' } }));
    expect(get(perChannelInput)).toEqual({ tv_trp: 'monetary' });
    expect(gateBlocksFromStore(['tv_trp'], {})).toBe(false); // override снял блок
  });

  it('БЕЗ pci (legacy/пусто) physical-имя + roi + no-cost → детектор→блок (контраст)', () => {
    activeProject.set(/** @type {any} */ ({ id: 'd1b', analysis_mode: 'roi' })); // pci не ре-гидрирован
    expect(get(perChannelInput)).toEqual({}); // сброшен, детектор-fallback
    expect(gateBlocksFromStore(['tv_trp'], {})).toBe(true); // детектор tv_trp→physical→блок
  });

  it('деселект сбрасывает perChannelInput', () => {
    activeProject.set(/** @type {any} */ ({ id: 'd1c', per_channel_input: { x: 'physical' } }));
    activeProject.set(null);
    expect(get(perChannelInput)).toEqual({});
  });
});

describe('LOAD-1 D-3: persist analysisMode on-change', () => {
  const amUpdates = () => /** @type {any} */ (invoke).mock.calls.filter(
    (c) => c[0] === 'project_update' && c[1]?.updates && 'analysis_mode' in c[1].updates);

  beforeEach(() => { activeProject.set(null); activeProjectId.set(null); /** @type {any} */ (invoke).mockClear(); });

  it('explicit смена режима при активном проекте → project_update с analysis_mode', async () => {
    activeProjectId.set('proj-1');
    /** @type {any} */ (invoke).mockClear();
    analysisMode.set('effectiveness');
    await Promise.resolve();
    const calls = amUpdates();
    expect(calls.length).toBeGreaterThanOrEqual(1);
    expect(calls[calls.length - 1][1]).toEqual({ projectId: 'proj-1', updates: { analysis_mode: 'effectiveness' } });
  });

  it('нет активного проекта → НЕ персистит', () => {
    activeProjectId.set(null);
    /** @type {any} */ (invoke).mockClear();
    analysisMode.set('mixed');
    expect(amUpdates().length).toBe(0);
  });

  it('ре-гидрация (disk→disk) НЕ перезаписывает: persisted mode не триггерит project_update', () => {
    activeProjectId.set('proj-2');
    /** @type {any} */ (invoke).mockClear();
    // activeProject с тем же режимом, что прилетает с диска → _amLastWritten синхрон → skip.
    activeProject.set(/** @type {any} */ ({ id: 'proj-2-load', analysis_mode: 'roi' }));
    expect(amUpdates().length).toBe(0); // ре-гидрация roi не пишется обратно
  });
});
