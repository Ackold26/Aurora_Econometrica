/**
 * s48 (2026-09-14, четвёртое уточнение аудитора — переписан с нуля). Прежняя версия
 * воспроизводила гонку, СОБИРАЯ входной объект вручную внутри себя
 * (`{ trialConsentOpen: get(trialConsentPromptOpen) }`) и передавая его в чистую функцию
 * `handleHomeShortcut` — то есть проверяла свою же копию старого выражения, а не код
 * продукта: мутация настоящего потребителя (`src/routes/+page.svelte`) не меняла её
 * результат ни на бит (доказано делом, отчёт front-gate-s48). Здесь — две проверки другой
 * природы, обе действительно читают код продукта.
 *
 * (а) Поведенческая — вызывает `resolveTrialConsentGate` напрямую, с поддельным `invoke`,
 * и проверяет саму производную `trialConsentBlocking`: блокирует, пока ответа нет, и
 * снимает/держит блокировку по содержанию ответа (fail-closed на отказе IPC). Красная
 * мутация: убрать проверку `resolved` из формулы в `$lib/store.js`
 * (`([resolved, open]) => open` вместо `!resolved || open`) — тогда в состоянии «ответа ещё
 * нет» (`open === false` по умолчанию) первый тест ожидает `true`, а формула даёт `false`.
 *
 * (б) Текстовая — читает исходники всех известных потребителей гейта и требует, чтобы
 * решение о блокировке было завязано на `trialConsentBlocking`, а не на сыром
 * `trialConsentPromptOpen`. Ловит именно то, что случилось: второй слой защиты в
 * `TrialConsentOverlay.svelte` монтировал перехватчик по видимости модали (то есть по
 * `trialConsentPromptOpen` напрямую) в обход починки трёх обработчиков клавиш. Красная
 * мутация: вернуть в любом из четырёх файлов чтение `trialConsentPromptOpen` вместо
 * `trialConsentBlocking` для решения о блокировке.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { get } from 'svelte/store';
import { trialConsentPromptOpen, trialConsentResolved, trialConsentBlocking } from '$lib/store.js';
import { resolveTrialConsentGate } from '$lib/trial-consent-gate.js';

beforeEach(() => {
  trialConsentPromptOpen.set(false);
  trialConsentResolved.set(false);
});

describe('гейт условий - поведение производной trialConsentBlocking', () => {
  it('пока ответ Rust не пришёл (промис подвешен) - блокировка включена', () => {
    const neverResolves = vi.fn(() => new Promise(() => {})); // подвешенный промис - "Rust ещё не ответил"
    resolveTrialConsentGate(neverResolves); // без await - смотрим на состояние ДО разрешения

    expect(get(trialConsentResolved)).toBe(false);
    expect(get(trialConsentBlocking)).toBe(true);
  });

  it('согласие уже дано (required: false) - блокировка снимается после ответа', async () => {
    const invoke = vi.fn().mockResolvedValue({ required: false });
    await resolveTrialConsentGate(invoke);

    expect(get(trialConsentResolved)).toBe(true);
    expect(get(trialConsentPromptOpen)).toBe(false);
    expect(get(trialConsentBlocking)).toBe(false);
  });

  it('согласие требуется (required: true) - блокировка остаётся после ответа', async () => {
    const invoke = vi.fn().mockResolvedValue({ required: true });
    await resolveTrialConsentGate(invoke);

    expect(get(trialConsentResolved)).toBe(true);
    expect(get(trialConsentBlocking)).toBe(true);
  });

  it('отказ проверки (IPC упал) - fail-closed, блокировка остаётся', async () => {
    const invoke = vi.fn().mockRejectedValue(new Error('IPC недоступен'));
    await resolveTrialConsentGate(invoke);

    expect(get(trialConsentResolved)).toBe(true);
    expect(get(trialConsentPromptOpen)).toBe(true);
    expect(get(trialConsentBlocking)).toBe(true);
  });
});

describe('гейт условий - все известные потребители читают trialConsentBlocking, не сырой trialConsentPromptOpen', () => {
  /** Три обработчика клавиш, передающие `trialConsentOpen` в `$lib/global-shortcuts.js`. */
  const HANDLER_CONSUMERS = [
    'src/routes/+layout.svelte',
    'src/routes/+page.svelte',
    'src/routes/cabinet/+page.svelte',
  ];

  it('обработчики клавиш решают вопрос блокировки через get(trialConsentBlocking)', () => {
    for (const path of HANDLER_CONSUMERS) {
      const src = readFileSync(path, 'utf-8');
      expect(src, `${path}: не найдено get(trialConsentBlocking) - решение о блокировке потеряно`).toMatch(/get\(trialConsentBlocking\)/);
      expect(src, `${path}: найдено прямое get(trialConsentPromptOpen) - вернулась гонка`).not.toMatch(/get\(trialConsentPromptOpen\)/);
    }
  });

  it('второй слой защиты (TrialConsentOverlay) монтирует перехватчик по trialConsentBlocking, а не по видимости модали', () => {
    const src = readFileSync('src/lib/components/TrialConsentOverlay.svelte', 'utf-8');
    expect(src, 'не найден derived, читающий $trialConsentBlocking для гейта перехвата').toMatch(/\$derived\(\$trialConsentBlocking\)/);
    // `visible` (= $trialConsentPromptOpen) допустим ТОЛЬКО для {#if} разметки - не для
    // решения, слушать ли window.keydown.
    expect(src, '$effect всё ещё гасит слушатель по видимости модали (визуальный признак, не гейтующий)').not.toMatch(/\$effect\(\(\) => \{\s*\n\s*if \(!visible\) return;/);
  });
});
