<script>
  /**
   * Карточка-обёртка: открывает своё содержимое в отдельном крупном окне поверх
   * страницы. Оборачивает любой контент (график, таблицу) и даёт кнопку
   * развернуть/свернуть.
   *
   * Props:
   *   title - заголовок карточки (то что раньше было .card-title)
   *   children - содержимое (Svelte 5 snippet), принимает параметром текущее
   *     состояние expanded. Пример:
   *       {#snippet children(expanded)}
   *         <EChartBase height={expanded ? '100%' : '240px'} .../>
   *       {/snippet}
   *     🔴 Для графиков на EChartBase значение в развороте роли не играет: высоту
   *     контейнера снимает и раздаёт сама карточка (правило по метке data-echart
   *     в блоке стилей ниже). Не копируйте сюда пиксели или vh в надежде на рост -
   *     живое измерение 12.09 показало, что '70vh' давало графику 24% высоты окна:
   *     значение доезжало до параметра, но цепочка родителей его не пропускала.
   *
   * Поведение:
   *   - Клик по кнопке в углу → окно поверх страницы (fixed, размытый фон,
   *     по центру, размер меняется вручную за нижний правый угол)
   *   - Escape или клик по фону → свернуть обратно
   *   - body overflow:hidden пока открыт, чтобы страница не скроллилась позади
   *
   * @component ExpandableCard
   */
  import { onDestroy } from 'svelte';

  /**
   * @type {{ title?: string, tourKey?: string, children: import('svelte').Snippet<[boolean]> }}
   */
  let { title = '', tourKey = '', children } = $props();

  let expanded = $state(false);

  function toggle() {
    expanded = !expanded;
  }

  /** @param {KeyboardEvent} e */
  function onKey(e) {
    if (e.key === 'Escape' && expanded) expanded = false;
  }

  $effect(() => {
    if (expanded) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', onKey);
    } else {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', onKey);
    }
  });

  onDestroy(() => {
    document.body.style.overflow = '';
    window.removeEventListener('keydown', onKey);
  });
</script>

{#if expanded}
  <!-- Fullscreen overlay. При свёртке content перерисовывается в inline-режиме
       ниже - чарты на основе canvas/svg пересоздадутся с правильными размерами. -->
  <div
    class="overlay"
    role="dialog"
    aria-modal="true"
    aria-label={title || 'Развёрнутая карточка'}
    onclick={toggle}
  >
    <div
      class="overlay-card"
      role="document"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <div class="overlay-header">
        {#if title}<div class="overlay-title">{title}</div>{/if}
        <button
          type="button"
          class="btn-toggle"
          onclick={toggle}
          title="Свернуть (Esc)"
          aria-label="Свернуть"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 3V5H3M11 3V5H13M3 11H5V13M11 13V11H13" />
          </svg>
        </button>
      </div>
      <div class="overlay-body">
        <div class="overlay-content">
          {@render children(true)}
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Inline-рендер карточки. Когда expanded=true, сам chart отрисован в окне поверх,
     а здесь показываем placeholder чтобы не рендерить один и тот же canvas дважды
     (это ломает chart.js / matplotlib и даёт пустые графики). -->
<div class="card" data-tour={tourKey || undefined}>
  <div class="card-header">
    {#if title}<div class="card-title">{title}</div>{/if}
    <button
      type="button"
      class="btn-toggle card-toggle"
      onclick={toggle}
      title={expanded ? 'Свернуть (Esc)' : 'Развернуть'}
      aria-label={expanded ? 'Свернуть' : 'Развернуть'}
    >
      {#if expanded}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 3V5H3M11 3V5H13M3 11H5V13M11 13V11H13" />
        </svg>
      {:else}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 5V3H5M11 3H13V5M13 11V13H11M5 13H3V11" />
        </svg>
      {/if}
    </button>
  </div>
  {#if !expanded}
    <div class="card-body">
      {@render children(false)}
    </div>
  {:else}
    <!-- Placeholder чтобы не схлопнулась высота карточки на странице -->
    <div class="card-placeholder">
      <span>График открыт в отдельном окне</span>
      <button type="button" class="placeholder-collapse" onclick={toggle}>Свернуть</button>
    </div>
  {/if}
</div>

<style>
  .card {
    background: var(--bg-surface-quiet, rgba(30,33,44,0.92));
    border: 1px solid var(--border-subtle, rgba(255,255,255,0.08));
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0; /* чтобы внутри grid-cell flex/canvas ужимались нормально */
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 0; /* gap: 12px у .card сам даёт отступ */
  }

  .card-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1.3;
  }

  .card-body {
    flex: 1;
    min-height: 0;
  }

  .card-placeholder {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 24px 16px;
    color: var(--text-muted);
    font-size: 13px;
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 6%, transparent);
    border: 1px dashed color-mix(in srgb, var(--accent-primary, #3b82f6) 25%, transparent);
    border-radius: 8px;
  }

  .placeholder-collapse {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .placeholder-collapse:hover {
    border-color: var(--accent-primary);
    color: var(--accent-primary);
  }

  .btn-toggle {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-muted);
    padding: 4px 6px;
    border-radius: 6px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
  }
  .btn-toggle:hover {
    color: var(--text-primary);
    background: color-mix(in srgb, var(--accent-primary, #3b82f6) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent-primary, #3b82f6) 30%, transparent);
  }

  /* ── Fullscreen overlay ───────────────────────────────────────────────── */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: color-mix(in srgb, #000 58%, transparent);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    display: flex;
    /* Владелец 12.09: окно разворота обязано быть изменяемого размера вручную,
       а не всегда занимать весь экран. center вместо stretch - иначе flex
       растянул бы .overlay-card назад до полного размера при каждом ре-рендере,
       обнуляя ручное изменение (resize на .overlay-card ниже). */
    align-items: center;
    justify-content: center;
    padding: 24px;
    animation: fadeIn 0.12s ease-out;
  }

  .overlay-card {
    /* Стартовый размер - крупный, дальше меняет владелец, таща за нижний правый
       угол (нативный CSS resize - без лишнего JS и рисков).
       Почему 86vh, а не 70vh: на служебное место (шапка 40px, отступы карточки
       и тела, легенда графика) уходит ~130-170px. Живое измерение 13.09 при 70vh
       давало холсту 59-61.5% высоты окна - ниже требования владельца (не ниже 60%
       с запасом). При 86vh то же измерение даёт 74-77%. Окно по-прежнему НЕ во весь
       экран и меняется вручную.
       min - чтобы не схлопнулось до нечитаемого; max - чтобы не вылезло за
       границы окна приложения. */
    width: 86vw;
    height: 86vh;
    max-width: calc(100vw - 48px);
    max-height: calc(100vh - 48px);
    min-width: 420px;
    min-height: 320px;
    resize: both;
    display: flex;
    flex-direction: column;
    gap: 16px;
    background: var(--bg-surface-quiet, #0f1115);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: 14px;
    padding: 20px 24px;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,0.45);
  }

  .overlay-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-shrink: 0;
  }

  .overlay-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .overlay-body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    /* Фикс F-A1-13: align-items:stretch (было center) — чтобы .overlay-content
       занял всю высоту и EChartBase-контейнеры внутри могли растянуться через flex.
       Прежний center сжимал .overlay-content до min-content → график не мог вырасти. */
    display: flex;
    align-items: stretch;
    justify-content: stretch;
    padding: 16px;
  }

  .overlay-content {
    width: 100%;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  /* Fullscreen: прямой потомок .overlay-content занимает всё доступное пространство
     (flex: 1 + min-height: 0 для flex-shrink), высота — 70vh ограничение убрано чтобы
     дать внутренним flex-детям (EChartBase-контейнер) корректно растянуться.
     Фикс F-A1-13 (2026-07-06): прежний height:70vh !important на > * обрезал overlay
     до высоты родителя (.timeline-wrap = 70vh), но EChartBase-контейнер (div с inline
     style="height:280px") внутри .timeline-wrap не получал пространство → график ½
     высоты. Теперь: flex: 1 + min-height: 0 на > *, и EChartBase-контейнеры (все div
     с inline height) переопределяем через height: 100% чтобы ResizeObserver подхватил.
     SVG waterfall — viewBox, растягивается сам. */
  .overlay-content :global(> *) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  /* ── Цепочка высоты до графика: ОДИН приём на все графики echarts ─────────
     Раньше расти умел только график, лежащий прямо в корне компонента: правило
     выше достаёт лишь прямого потомка .overlay-content. Любая промежуточная
     обёртка (.chart-cell у PPCScatter, .timeline-wrap у ChannelTimeline и т.д.)
     рвала цепочку, и каждый такой компонент вынужден был дублировать flex-вёрстку
     у себя в <style>. Вместо копии в каждом файле: :has() делает растягивающейся
     flex-колонкой ЛЮБОГО предка графика на любой глубине. Метку data-echart
     ставит EChartBase (и ResponseCurves со своим инстансом echarts).
     Соседи графика (легенда, подпись, метрики) остаются по содержимому и не
     сжимаются - им free space не достаётся, весь остаток уходит графику. */
  .overlay-content :global(*:has([data-echart])) {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  .overlay-content :global(*:has([data-echart]) > *:not(:has([data-echart])):not([data-echart])) {
    flex-shrink: 0;
  }

  /* Контейнер echarts в развороте: снимаем пиксельную высоту, заданную компонентом
     для свёрнутого вида, и отдаём весь остаток родителя. ResizeObserver внутри
     EChartBase подхватит изменение → chart.resize(), поэтому холст следует и за
     ручным изменением размера .overlay-card (проверено измерением 13.09). */
  .overlay-content :global([data-echart]) {
    flex: 1 !important;
    height: auto !important;
    min-height: 200px;
  }

  /* Страховка на случай, если :has() не поддержан (WebView2 старее Chrome 105):
     правило выше по цепочке предков тогда не применится, предки не станут
     flex-колонками, flex:1 работать не на чем - и контейнер сел бы на пол
     200px, то есть дефект вернулся бы к покупателю молча: ни тесты в jsdom,
     ни измерение на нашей машине его не увидят. В этом случае даём графику
     долю окна - ровно тот минимум, которого требует владелец.
     Почему под @supports, а не просто min-height: max(200px, 60vh) - такой
     безусловный пол сломал бы ручное уменьшение окна разворота: при карточке
     760px измерение 13.09 даёт холсту 642px, а пол 60vh (821px) выдавил бы
     содержимое в прокрутку. Гейт @supports включает страховку ровно там, где
     она нужна, и не мешает там, где приём работает.
     Проверено измерением 13.09: с принудительно удалённым правилом :has()
     (имитация старого WebView2) холст садится на 200px = 14.6% окна, а с этой
     страховкой - 821px = 60.0%. */
  @supports not selector(:has(*)) {
    .overlay-content :global([data-echart]) {
      min-height: 60vh;
    }
  }

  /* Внутри overlay даём canvas/img растянуться по ширине */
  .overlay-body :global(canvas),
  .overlay-body :global(img) {
    max-width: 100%;
  }

  /* SVG (waterfall и др.) — viewBox, растягивается по ширине, высота естественная */
  .overlay-body :global(svg) {
    max-width: 100%;
    height: auto;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }
</style>
