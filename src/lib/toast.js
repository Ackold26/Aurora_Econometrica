import { writable } from 'svelte/store';

/** @type {import('svelte/store').Writable<Array<{id: number, message: string, type: 'success'|'error'|'warning'|'info', duration: number, onClose: (() => void) | null}>>} */
export const toasts = writable([]);

let nextId = 0;

/**
 * Show a toast notification.
 * @param {string} message
 * @param {'success'|'error'|'warning'|'info'} [type='info']
 * @param {number} [duration=3000]
 * @param {(() => void) | null} [onClose=null] Вызывается РОВНО ОДИН РАЗ в момент
 *   закрытия тоста (по таймеру или по клику человека) — не в момент показа.
 *   Нужно для признаков вида «человек это увидел»: снимать их сразу при вызове
 *   toast() значит терять сообщение навсегда, если программа закроется раньше,
 *   чем истечёт таймер показа.
 */
export function toast(message, type = 'info', duration = 3000, onClose = null) {
  const id = nextId++;
  toasts.update(t => [...t, { id, message, type, duration, onClose }]);
  // Auto-dismiss handled by Toast.svelte onMount timer → calls onClose(prop) → dismiss()
}

/**
 * Закрыть тост по id. Вызывает его собственный onClose (если задан) РОВНО ОДИН РАЗ:
 * поиск и удаление из массива происходят внутри одного синхронного update() —
 * повторный вызов dismiss() с тем же id (гонка таймер vs клик «закрыть») уже не
 * находит тост в массиве и колбэк не срабатывает повторно.
 * @param {number} id
 */
export function dismiss(id) {
  toasts.update(t => {
    const found = t.find(x => x.id === id);
    if (found?.onClose) found.onClose();
    return t.filter(x => x.id !== id);
  });
}
