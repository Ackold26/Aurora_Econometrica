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
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
  activeProject, analysisMode, expertMode,
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
