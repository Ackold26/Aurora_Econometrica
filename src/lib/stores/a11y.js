/**
 * a11y.js - accessibility stores (v2.1.0 п.5.6)
 *
 * prefersReducedMotion: reactive readable store that mirrors the
 * CSS media query `(prefers-reduced-motion: reduce)`.
 *
 * Usage in Svelte components with programmatic transitions:
 *
 *   import { prefersReducedMotion } from '$lib/stores/a11y.js';
 *   import { fade } from 'svelte/transition';
 *
 *   <div transition:fade={{ duration: $prefersReducedMotion ? 0 : 300 }}>
 *
 * SSR-safe: returns false during server-side render (no window).
 */

import { readable } from 'svelte/store';

/**
 * @type {import('svelte/store').Readable<boolean>}
 */
export const prefersReducedMotion = readable(false, (set) => {
  if (typeof window === 'undefined') return;
  // jsdom (vitest) не реализует matchMedia; fallback к false без подписки.
  if (typeof window.matchMedia !== 'function') return;

  let mq;
  try {
    mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  } catch {
    // Некоторые headless среды могут бросать TypeError; деградируем тихо.
    return;
  }
  set(mq.matches);

  /** @param {MediaQueryListEvent} e */
  const onChange = (e) => set(e.matches);
  // addEventListener поддерживается современными браузерами; старые имели addListener.
  if (typeof mq.addEventListener === 'function') {
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }
  if (typeof mq.addListener === 'function') {
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }
});
