<script>
  // Таймер сессии: отсчёт с открытия приложения (HH:MM:SS). Не останавливается при навигации,
  // запуске команд, отменах, копировании — это чистый счётчик времени. Управление только кнопкой:
  //   1 клик — стоп · 2-й клик — пуск/продолжение · двойной клик — сброс на 00:00:00.
  // Сбрасывается также при перезапуске приложения. Стиль/цвет — как у часов.
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
  // 🔴 Известная граница (приёмка s49, 18.09.2026, проверена настоящим двойным кликом в браузере,
  // а не программным событием). Перехватчик гейта условий (TrialConsentOverlay.svelte) снимает
  // событие 'click' в фазе перехвата, поэтому одиночный клик сюда в окне гонки не доходит. А вот
  // 'dblclick' браузер порождает САМ, отдельным событием: оно не производно от 'click' и его
  // перехватом не гасится - двойной клик по этой кнопке в первые сотни миллисекунд после запуска
  // сбросит таймер, пока ответ ядра о согласии ещё не получен. Оставлено сознательно: сброс
  // таймера сессии не открывает доступ к функциям программы и согласие не обходит. Если сюда
  // когда-нибудь добавится действие ЗНАЧИМОЕ (переход, запуск расчёта, работа с файлом) - эту
  // границу закрывать обязательно, перехватом 'dblclick' там же, где перехватывается 'click'.
  //
  // 🔴 Точность записи (внешний аудит s49, 18.09.2026): это единственный обработчик мыши вне
  // класса 'click' НА ПЕРВОМ ЭКРАНЕ, а не во всём приложении. В других местах есть и 'mousedown',
  // и 'pointerdown', и 'contextmenu', и 'auxclick' (CommandCard, FileList, WorkflowCanvas, экраны
  // кабинета и настроек), а перетаскивание файла в окно вообще не событие разметки
  // (onDragDropEvent). Перехватчик гейта их не закрывает. Обхода сегодня нет по другой причине:
  // все они живут на иных маршрутах, а самопроизвольного перехода при запуске не происходит.
  // То есть граница держится МАРШРУТОМ, а не перехватом, - и если появится автоматический переход
  // с первого экрана, её придётся пересматривать целиком, а не дописывать одно событие.
  function handleDblClick() {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    resetTimer();
  }

  // Не оставлять висящий одиночный-клик setTimeout при размонтировании.
  onDestroy(() => { if (clickTimer) clearTimeout(clickTimer); });
</script>

<div class="session-timer">
  <span class="st-time" class:paused={!$timerState.running} title="Время сессии">{elapsed}</span>
  <button
    class="st-reset"
    onclick={handleClick}
    ondblclick={handleDblClick}
    title={$timerState.running ? 'Клик – стоп · двойной клик – сброс' : 'Клик – продолжить · двойной клик – сброс'}
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
    color: var(--clock-color, #CCFF00);
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
    color: var(--clock-color, #CCFF00);
  }
</style>
