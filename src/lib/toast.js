import { writable } from 'svelte/store';

/** @type {import('svelte/store').Writable<Array<{id: number, message: string, type: 'success'|'error'|'warning'|'info', duration: number}>>} */
export const toasts = writable([]);

let nextId = 0;

/**
 * Show a toast notification.
 * @param {string} message
 * @param {'success'|'error'|'warning'|'info'} [type='info']
 * @param {number} [duration=3000]
 */
export function toast(message, type = 'info', duration = 3000) {
  const id = nextId++;
  toasts.update(t => [...t, { id, message, type, duration }]);
  // Auto-dismiss handled by Toast.svelte onMount timer → calls onClose → dismiss()
}

/** @param {number} id */
export function dismiss(id) {
  toasts.update(t => t.filter(x => x.id !== id));
}
