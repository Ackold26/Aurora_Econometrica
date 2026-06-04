/**
 * NAV-2 / 3A-FOOTER-BYPASS regression guard (2026-06-04).
 *
 * Баг: после авто-валидации ValidateStepV13.autoRunValidate() вызывал
 * completeStep(1) → Модель (stepMeta[2]) становилась 'ready' СРАЗУ, до прохождения
 * подшагов конфигурации. Футерная «Далее» (pipeline/+layout goNext) проверяет лишь
 * stepMeta[next] !== 'locked' → перескакивала подшаг «Метрики каналов» и 3A CPP-гейт
 * (physical+ROI канал без unit_cost → ROI-артефакт класса TRPs 12186×).
 *
 * Фикс (Вариант B): completeStep(1) убран из ТРЁХ преждевременных источников
 * (autoRunValidate + InsightsPanel syncStepLockAfterValidate $effect) и оставлен ЕДИНСТВЕННЫМ
 * в ValidateStepV13.handlePerChannelConfirm — после прохождения CPP-гейта, на единственной
 * точке перехода на подшаг 3 «Подтверждение» (контентная кнопка handleContinue убрана —
 * ModeDerivedExplanation стал инфо-строкой, переход подшаг 3 → Модель делает футер goNext).
 * Инвариант, который охраняет этот тест:
 *   - завершение Импорта (completeStep(0)) НЕ разлочивает Модель — только Валидацию;
 *   - Модель (stepMeta[2]) разлочивается ИСКЛЮЧИТЕЛЬНО явным completeStep(1)
 *     (который теперь живёт только в handlePerChannelConfirm, за CPP-гейтом).
 *
 * Это lightweight guard на pipeline-state контракт (не render E2E — проект их избегает,
 * см. save-kpi-persistence.test.js). Полное wiring (3 источника НЕ зовут completeStep(1);
 * handlePerChannelConfirm зовёт после CPP-гейта; Модель locked на подшагах -2/-1/2, ready
 * на 3, футер disabled/enabled соответственно) верифицировано live e2e через MCP-мост 9223.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
  pipelineStepMeta, completeStep, lockStep,
  // NAV-2/3A Minimal-plus (2026-06-05): чистые предикаты + gate-сторы.
  cppSatisfied, shouldRelockModel,
  validateData, perChannelInput, unitCosts, analysisMode,
} from '$lib/project-state.js';

beforeEach(() => {
  // defaultStepMeta: [ready, locked, locked, locked, locked, locked]
  pipelineStepMeta.set([
    { status: 'ready', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
    { status: 'locked', errorMessage: null },
  ]);
  // NAV-2/3A Minimal-plus: сбросить gate-сторы. Без этого (1) chokepoint-guard в
  // completeStep(1) видел бы stale physical-канал без cost из guard-теста и
  // блокировал бы latch-тесты; (2) пустые каналы → cppSatisfied=true → guard
  // инертен, latch-тесты сохраняют прежнее поведение.
  validateData.set({ result: null, correlationMatrix: null, columnHistograms: null });
  perChannelInput.set({});
  unitCosts.set({});
  analysisMode.set('roi');
});

describe('NAV-2/3A-FOOTER-BYPASS: Модель не разлочивается до подшага «Подтверждение»', () => {
  it('completeStep(0) (Импорт) разлочивает Валидацию, но НЕ Модель', () => {
    completeStep(0);
    const meta = get(pipelineStepMeta).map((s) => s.status);
    expect(meta[0]).toBe('complete'); // Импорт завершён
    expect(meta[1]).toBe('ready');    // Валидация разлочена
    expect(meta[2]).toBe('locked');   // Модель ОСТАЁТСЯ locked (ключевой инвариант)
  });

  it('Модель остаётся locked после ТОЛЬКО валидации (без completeStep(1))', () => {
    // Авто-валидация показывает результаты, но НЕ должна разлочивать Модель.
    // Эмулируем состояние после autoRunValidate (фикс убрал оттуда completeStep(1)):
    // только Импорт complete + Валидация ready, Модель ещё locked.
    completeStep(0);
    // ВАЖНО: никакого completeStep(1) — как в autoRunValidate после фикса.
    expect(get(pipelineStepMeta)[2].status).toBe('locked');
  });

  it('completeStep(1) (handlePerChannelConfirm, за CPP-гейтом) разлочивает Модель', () => {
    completeStep(0);
    completeStep(1); // вызывается из handlePerChannelConfirm после прохождения CPP-гейта
    const meta = get(pipelineStepMeta).map((s) => s.status);
    expect(meta[1]).toBe('complete'); // Валидация завершена
    expect(meta[2]).toBe('ready');    // Модель теперь разлочена — легитимный путь
  });
});

/**
 * HOLE-1 (goBack/reload) guard: completeStep(1) — one-way latch; футер «Далее» проверяет
 * только !locked (не allChannelsConfigured). Если пользователь вернулся на подшаг <3 или
 * убрал CPP (goBack 3→2) / reload посреди валидации — Модель остаётся 'ready' и футер
 * перескакивает CPP-гейт. ValidateStepV13 $effect зовёт lockStep(2) для ре-лока. Вскрыто
 * адверсариальным само-аудитом (Agent), невидимо первому e2e-проходу (он шёл только вперёд).
 */
describe('NAV-2/3A guard: lockStep ре-локает преждевременный ready (HOLE-1 goBack/reload)', () => {
  it('lockStep: ready → locked (вернулся на подшаг <3 / убрал CPP)', () => {
    completeStep(0);
    completeStep(1); // Модель 'ready' (one-way latch)
    expect(get(pipelineStepMeta)[2].status).toBe('ready');
    lockStep(2);     // guard-условие: subStep<3 ИЛИ !allChannelsConfigured
    expect(get(pipelineStepMeta)[2].status).toBe('locked');
  });

  it('lockStep НЕ трогает complete (обученная модель = retrain-flow, не HOLE-1)', () => {
    completeStep(0);
    completeStep(1);
    completeStep(2); // Модель обучена → 'complete'
    lockStep(2);
    expect(get(pipelineStepMeta)[2].status).toBe('complete'); // сохраняется
  });

  it('lockStep идемпотентен на locked (не плодит мутаций)', () => {
    completeStep(0); // [complete, ready, locked, ...]
    lockStep(2);     // уже locked
    expect(get(pipelineStepMeta)[2].status).toBe('locked');
  });
});

/**
 * NAV-2/3A Minimal-plus (2026-06-05): чистый CPP-предикат cppSatisfied — SSOT-порт
 * allChannelsConfigured (ValidateStepV13:786). physical+ROI канал без unit_cost → false
 * (защита от ROI-артефакта 12186×). Покрывает forward/effectiveness/empty + reload-путь
 * (perChannelInput пуст → падение на detectChannelUnitType). channels-prop и columns-вывод
 * тождественны (+page.svelte:39-45 = тот же media-фильтр).
 */
describe('cppSatisfied — CPP-гейт (SSOT-предикат)', () => {
  const kpiCol = { name: 'sales_rub', role: 'kpi' };
  const physCol = { name: 'tv_trp', role: 'media' };     // детектор → physical (паттерн trp)
  const moneyCol = { name: 'digital_spend', role: 'media' }; // детектор → monetary (spend)

  it('пустой список каналов → true (нечего проверять)', () => {
    expect(cppSatisfied({ columns: [kpiCol], analysisMode: 'roi' })).toBe(true);
    expect(cppSatisfied({ channels: [], analysisMode: 'roi' })).toBe(true);
    expect(cppSatisfied({ analysisMode: 'roi' })).toBe(true); // ни channels, ни columns
  });

  it('physical+ROI без unit_cost → false (ROI-артефакт)', () => {
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: { tv_trp: 'physical' }, unitCosts: {}, analysisMode: 'roi',
    })).toBe(false);
  });

  it('physical+ROI с unit_cost>0 → true', () => {
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: { tv_trp: 'physical' }, unitCosts: { tv_trp: 1500 }, analysisMode: 'roi',
    })).toBe(true);
  });

  it('monetary канал → true (бюджет в ₽ уже есть, cost не нужен)', () => {
    expect(cppSatisfied({
      channels: ['digital_spend'], perChannelInput: { digital_spend: 'monetary' }, unitCosts: {}, analysisMode: 'roi',
    })).toBe(true);
  });

  it('physical в effectiveness mode → true (физ.единицы валидны без конверсии)', () => {
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: { tv_trp: 'physical' }, unitCosts: {}, analysisMode: 'effectiveness',
    })).toBe(true);
  });

  it('physical в mixed mode → true (физ.ветка кусает ТОЛЬКО roi — лочим инвариант)', () => {
    // Защита от рефактора `=== "roi"` → `!== "effectiveness"`, который молча
    // начал бы блокировать mixed-mode physical-каналы.
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: { tv_trp: 'physical' }, unitCosts: {}, analysisMode: 'mixed',
    })).toBe(true);
  });

  it('columns вместо channels: выводит media-каналы тождественно prop', () => {
    expect(cppSatisfied({
      columns: [kpiCol, physCol], perChannelInput: { tv_trp: 'physical' }, unitCosts: {}, analysisMode: 'roi',
    })).toBe(false); // tv_trp physical+roi без cost
    expect(cppSatisfied({
      columns: [kpiCol, moneyCol], perChannelInput: {}, unitCosts: {}, analysisMode: 'roi',
    })).toBe(true); // digital_spend → monetary
  });

  it('reload: perChannelInput пуст → тип берётся из детектора (TRP→physical нужен cost)', () => {
    // После reload perChannelInput НЕ ре-гидрируется (writable({})) → fallback на detectChannelUnitType.
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: {}, unitCosts: {}, analysisMode: 'roi',
    })).toBe(false);
    expect(cppSatisfied({
      channels: ['tv_trp'], perChannelInput: {}, unitCosts: { tv_trp: 1500 }, analysisMode: 'roi',
    })).toBe(true);
  });
});

/**
 * NAV-2/3A Minimal-plus: чистый shouldRelockModel — экстракция guard-условия
 * ValidateStepV13:813 в тестируемую функцию. Покрывает goBack/reload/forward/обучена
 * по построению (схлопывает live-goBack-verify в unit). Скоуп pipelineCurrentStep===1
 * остаётся в вызывающем $effect.
 */
describe('shouldRelockModel — ре-лок Модели (HOLE-1 goBack/reload)', () => {
  it('forward (subStep=3, cpp, ready) → false (легит-путь, не ре-локать)', () => {
    expect(shouldRelockModel({ subStep: 3, cppSatisfied: true, status: 'ready' })).toBe(false);
  });
  it('goBack (subStep=2, ready) → true (вернулся на подшаг <3)', () => {
    expect(shouldRelockModel({ subStep: 2, cppSatisfied: true, status: 'ready' })).toBe(true);
  });
  it('CPP убран (subStep=3, !cpp, ready) → true', () => {
    expect(shouldRelockModel({ subStep: 3, cppSatisfied: false, status: 'ready' })).toBe(true);
  });
  it('reload mid-validate (subStep=-2, ready) → true', () => {
    expect(shouldRelockModel({ subStep: -2, cppSatisfied: true, status: 'ready' })).toBe(true);
  });
  it('обучена (status=complete) → false (не трогаем, любой subStep/cpp)', () => {
    expect(shouldRelockModel({ subStep: -2, cppSatisfied: false, status: 'complete' })).toBe(false);
  });
  it('уже locked (status=locked) → false (идемпотентность)', () => {
    expect(shouldRelockModel({ subStep: 0, cppSatisfied: false, status: 'locked' })).toBe(false);
  });
});

/**
 * NAV-2/3A Minimal-plus: chokepoint-guard внутри completeStep — единственный
 * писатель, разлочивающий Модель. Превращает «4-й преждевременный источник» из
 * policed-by-test в policed-by-mechanism: completeStep(1) при неудовлетворённом
 * CPP-гейте НЕ разлочивает Модель (читает живые сторы через currentGateSnapshot).
 */
describe('chokepoint-guard: completeStep(1) блокирует разлок Модели без CPP', () => {
  it('physical+ROI без unit_cost → Модель остаётся locked (guard сработал)', () => {
    completeStep(0); // Валидация ready
    validateData.set({ result: { columns: [{ name: 'tv_trp', role: 'media' }] }, correlationMatrix: null, columnHistograms: null });
    perChannelInput.set({ tv_trp: 'physical' });
    unitCosts.set({});
    analysisMode.set('roi');
    completeStep(1); // guard блокирует
    expect(get(pipelineStepMeta)[2].status).toBe('locked');
    expect(get(pipelineStepMeta)[1].status).toBe('ready'); // Валидация НЕ помечена complete
  });

  it('physical+ROI с unit_cost>0 → Модель разлочена (легит-путь пропущен)', () => {
    completeStep(0);
    validateData.set({ result: { columns: [{ name: 'tv_trp', role: 'media' }] }, correlationMatrix: null, columnHistograms: null });
    perChannelInput.set({ tv_trp: 'physical' });
    unitCosts.set({ tv_trp: 1500 });
    analysisMode.set('roi');
    completeStep(1);
    expect(get(pipelineStepMeta)[1].status).toBe('complete');
    expect(get(pipelineStepMeta)[2].status).toBe('ready');
  });

  it('reload-домен: perChannelInput пуст + physical-канал → guard блокирует через детектор', () => {
    // Точно reload-сценарий: perChannelInput НЕ ре-гидрируется (пуст), тип берётся
    // из detectChannelUnitType (tv_trp→physical). Guard читает живые сторы через
    // currentGateSnapshot — проверяем detector-fallback на интеграционном уровне.
    completeStep(0);
    validateData.set({ result: { columns: [{ name: 'tv_trp', role: 'media' }] }, correlationMatrix: null, columnHistograms: null });
    perChannelInput.set({});      // ← пусто, как после reload
    unitCosts.set({});
    analysisMode.set('roi');
    completeStep(1);
    expect(get(pipelineStepMeta)[2].status).toBe('locked');
  });

  it('scope step===1: guard НЕ трогает completeStep(2) даже при сломанном CPP', () => {
    // Негативный тест scope: будущий typo `step <= 1` поймается здесь.
    completeStep(0);
    validateData.set({ result: { columns: [{ name: 'tv_trp', role: 'media' }] }, correlationMatrix: null, columnHistograms: null });
    perChannelInput.set({ tv_trp: 'physical' });
    unitCosts.set({ tv_trp: 1500 });
    analysisMode.set('roi');
    completeStep(1);                 // Модель ready (cpp ok)
    unitCosts.set({});               // сломать CPP (как goBack убрал cost)
    completeStep(2);                 // step!==1 → guard не применяется
    const meta = get(pipelineStepMeta).map(s => s.status);
    expect(meta[2]).toBe('complete'); // Модель обучена
    expect(meta[3]).toBe('ready');    // Декомпозиция разлочена
  });
});
