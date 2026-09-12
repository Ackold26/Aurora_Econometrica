// @ts-nocheck
/**
 * Сторож Б-49 (Low, найдено внешним аудитом): признак «уведомление о смене
 * маршрута показано» обязан сниматься ПОСЛЕ того, как человек его увидел
 * (тост закрылся — по таймеру или по клику), а не в момент ВЫЗОВА toast().
 *
 * Дефект: `toast(routeNotice, 'info', 30000); acknowledgeRouteChange();` снимал
 * признак сразу же — если программа закрывалась в первые секунды или тост не
 * успевал отрисоваться, сообщение о смене маршрута данных терялось навсегда,
 * а человеку так и не сказали. Тот же класс дефекта, ради которого весь блок
 * уведомления и делался (см. комментарий в assistant-route.js).
 *
 * Правка: `toast()` принимает необязательный 4-й параметр `onClose`, который
 * `dismiss(id)` вызывает РОВНО ОДИН РАЗ — в момент закрытия, а не показа.
 * Гонка «таймер vs клик закрыть» закрыта тем, что поиск+удаление тоста из
 * массива происходит внутри одного синхронного update(): второй dismiss()
 * с тем же id тост уже не находит и колбэк повторно не зовёт.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { toasts, toast, dismiss } from '$lib/toast.js';

beforeEach(() => {
  toasts.set([]);
});

describe('сторож Б-49: onClose тоста снимает признак только после закрытия', () => {
  it('колбэк НЕ вызван, пока тост показан (признак ещё не снят)', () => {
    let acknowledged = false;
    toast('маршрут сменился', 'info', 30000, () => { acknowledged = true; });

    expect(get(toasts)).toHaveLength(1);
    expect(acknowledged, 'признак не должен сниматься до закрытия тоста').toBe(false);
  });

  it('колбэк вызывается при закрытии (клик/таймер) и тост удаляется из стора', () => {
    let acknowledged = false;
    toast('маршрут сменился', 'info', 30000, () => { acknowledged = true; });
    const [{ id }] = get(toasts);

    dismiss(id);

    expect(acknowledged, 'признак обязан сняться после закрытия').toBe(true);
    expect(get(toasts)).toHaveLength(0);
  });

  it('гонка таймер+клик: повторный dismiss() того же id НЕ зовёт колбэк дважды', () => {
    let calls = 0;
    toast('маршрут сменился', 'info', 30000, () => { calls += 1; });
    const [{ id }] = get(toasts);

    // Имитация гонки: оба пути закрытия (клик по крестику и истёкший таймер)
    // синхронно зовут dismiss() с тем же id.
    dismiss(id);
    dismiss(id);

    expect(calls, 'колбэк обязан сработать ровно один раз, не дважды').toBe(1);
  });

  it('toast() без onClose (обычные уведомления) работает как раньше — без ошибок', () => {
    toast('обычное сообщение');
    const [{ id }] = get(toasts);

    expect(() => dismiss(id)).not.toThrow();
    expect(get(toasts)).toHaveLength(0);
  });
});
