<script>
  // Таймер сессии (стандарт Aurora Core / SSOT §11, эталон Oracle + Creative Hub):
  // отсчёт с открытия приложения (HH:MM:SS). Не останавливается при навигации,
  // запуске команд, отменах — чистый счётчик времени. Управление кнопкой:
  //   1 клик — стоп · 2-й клик — пуск/продолжение · двойной клик — сброс 00:00:00.
  // Сбрасывается при перезапуске приложения. Стиль/цвет — как у часов (lime).
  import { onMount, onDestroy } from 'svelte';
  import { timerState, timerElapsedMs, toggleTimer, resetTimer } from '$lib/store.js';

  let elapsed = $state('00:00:00');

  /** @param {number} ms */
  function fmt(ms) {
    const t = Math.max(0, Math.floor(ms / 1000));
    const h = String(Math.floor(t / 3600)).padStart(2, '0');
    const m = String(Math.floor((t % 3600) / 60)).padStart(2, '0');
    const s = String(t % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function tick() { elapsed = fmt(timerElapsedMs($timerState)); }

  onMount(() => {
    tick();
    const i = setInterval(tick, 1000);
    return () => clearInterval(i);
  });

  // Мгновенно отразить пуск/стоп/сброс.
  $effect(() => { void $timerState; tick(); });

  // Различение одиночного и двойного клика.
  /** @type {ReturnType<typeof setTimeout>|null} */
  let clickTimer = null;
  function handleClick() {
    if (clickTimer) return; // придёт dblclick
    clickTimer = setTimeout(() => { clickTimer = null; toggleTimer(); }, 250);
  }
  function handleDblClick() {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    resetTimer();
  }

  onDestroy(() => { if (clickTimer) clearTimeout(clickTimer); });
</script>

<div class="session-timer">
  <span class="st-time" class:paused={!$timerState.running} title="Время сессии">{elapsed}</span>
  <button
    class="st-reset"
    onclick={handleClick}
    ondblclick={handleDblClick}
    title={$timerState.running ? 'Клик — стоп · двойной клик — сброс' : 'Клик — продолжить · двойной клик — сброс'}
    aria-label="Управление таймером сессии"
  >
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <line x1="10" x2="14" y1="2" y2="2" /><line x1="12" x2="15" y1="14" y2="11" /><circle cx="12" cy="14" r="8" />
    </svg>
  </button>
</div>

<style>
  .session-timer {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .st-time {
    font-family: var(--font-mono, 'Consolas', monospace);
    font-size: 12px;
    font-weight: 500;
    color: var(--clock-color, var(--accent-secondary, #CCFF00));
    letter-spacing: 0.06em;
    opacity: 0.85;
    user-select: none;
    transition: opacity 150ms ease-out;
  }
  /* На паузе — приглушённо (видно, что отсчёт остановлен). */
  .st-time.paused {
    opacity: 0.4;
  }
  .st-reset {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    padding: 2px;
    cursor: pointer;
    color: var(--text-muted);
    transition: color 150ms ease-out;
  }
  .st-reset:hover {
    color: var(--clock-color, var(--accent-secondary, #CCFF00));
  }
</style>
