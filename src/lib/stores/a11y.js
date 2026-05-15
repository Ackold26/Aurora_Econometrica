/**
 * a11y.js — accessibility stores (v2.1.0 п.5.6)
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

  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  set(mq.matches);

  /** @param {MediaQueryListEvent} e */
  const onChange = (e) => set(e.matches);
  mq.addEventListener('change', onChange);

  return () => mq.removeEventListener('change', onChange);
});
