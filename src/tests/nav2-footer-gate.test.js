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
import { pipelineStepMeta, completeStep } from '$lib/project-state.js';

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
