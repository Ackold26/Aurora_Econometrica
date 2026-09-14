<script>
  import { invoke } from '@tauri-apps/api/core';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { trialConsentPromptOpen, trialConsentBlocking } from '$lib/store.js';
  import { SHOW_CLOUD_PROCESSING_PARAGRAPH } from '$lib/trial-terms-config.js';
  import { isKeydownOutsideBlockingOverlay } from '$lib/global-shortcuts.js';

  // Экран «Условия ознакомительного использования» (s48, 2026-09-14). Пробный период выведен
  // правовым блоком из лицензионного договора в отдельный документ, единый для всей линейки
  // Aurora AI (опора - п.5 ст.1286 ГК РФ, договор присоединения). Роль этого окна - краткая
  // суть + ссылка на полный документ + подтверждение согласия; ПОЛНОГО текста условий здесь
  // быть не должно.
  //
  // В отличие от CloudConsentOverlay (граcefully-skippable «Позже») это окно НЕ пропускаемо:
  // «Отказаться» закрывает программу целиком, «Принимаю» доступно только с поставленной
  // отметкой. Текст ниже согласован правовым блоком дословно - не редактировать формулировки.
  //
  // 🔴 Номер И дата в тексте отметки ниже ОБЯЗАНЫ совпадать с TRIAL_TERMS_REVISION в
  // src-tauri/src/commands/user_config.rs (формат ГГГГ-ММ-ДД.НН) - сторож расхождения:
  // trial_terms_revision_matches_frontend_checkbox_text (там же).
  //
  // Средний абзац - условный (см. $lib/trial-terms-config.js): зависит от отдельной проверки,
  // уходит ли из Econometrica содержание материалов клиента наружу. Прокидывается пропом с
  // дефолтом из константы - чтобы тесты могли проверить оба состояния без мока модуля, а
  // реальный рендер (`+layout.svelte`) всегда брал значение из ЕДИНСТВЕННОГО места.

  /** @type {{ showCloudProcessingParagraph?: boolean }} */
  let { showCloudProcessingParagraph = SHOW_CLOUD_PROCESSING_PARAGRAPH } = $props();

  let agreed = $state(false); // отметка «Я принимаю…» - НЕ предустановлена
  let busy = $state(false);
  let declining = $state(false);
  let errorMsg = $state('');
  let openError = $state('');
  /** @type {HTMLElement | null} */
  let overlayEl = $state(null);

  // `visible` управляет ТОЛЬКО разметкой ({#if} ниже) - модаль не обязана мигать у
  // человека, который уже согласился давно, пока Rust ещё не ответил. Для решения
  // «активен ли перехватчик» это значение НЕПРИГОДНО - см. `blockingActive` ниже.
  const visible = $derived($trialConsentPromptOpen);

  // Второй, независимый от проверок в отдельных обработчиках слой защиты - см. докстринг
  // isKeydownOutsideBlockingOverlay в $lib/global-shortcuts.js (s48, аудит второй волны,
  // 2026-09-14). Пока условия не подтверждены - слушатель в ФАЗЕ ПЕРЕХВАТА на `window`
  // гасит ЛЮБОЕ нажатие клавиши вне дерева этого оверлея ДО того, как оно дойдёт до цели
  // и всплывёт до какого-либо обработчика продукта - не важно, проверяет тот
  // `trialConsentOpen` сам или ещё не написан.
  //
  // 🔴 s48 (2026-09-14, третья волна аудита - находка front-gate-s48): раньше этот
  // `$effect` был завязан на `visible` (то есть на сыром `trialConsentPromptOpen`) - той
  // же величине, что и починенные обработчики клавиш ИЗБЕГАЮТ читать напрямую. В первые
  // миллисекунды после запуска, пока Rust ещё не ответил, `trialConsentPromptOpen` = false,
  // разметка ({#if visible}) не смонтирована - и этот, второй, слой защиты вообще не
  // слушал, хотя именно на этот случай (обработчик, который забудет проверить гейт сам)
  // его и заводили. Теперь монтирование листенера читает `trialConsentBlocking` -
  // производную, которая по умолчанию блокирует (истинна), пока ответа нет.
  const blockingActive = $derived($trialConsentBlocking);

  $effect(() => {
    if (!blockingActive) return;

    /** @param {KeyboardEvent} e */
    function blockKeydownOutsideOverlay(e) {
      // `overlayEl` здесь может быть `null` - в окне гонки (блокировка уже активна,
      // а `{#if visible}` ещё не смонтировал разметку, т.к. Rust не ответил и решение
      // «показывать ли модаль» ещё не принято) `isKeydownOutsideBlockingOverlay(null, ...)`
      // возвращает `true` («цель снаружи») - и гасит нажатие. Это ПРАВИЛЬНОЕ поведение,
      // а не недосмотр: раз окна ещё нет, внутри него быть не может ничто, значит гасить
      // надо всё - см. тест "второй слой активен ДО монтирования разметки окна" в
      // src/tests/trial-consent-overlay.test.js.
      if (!isKeydownOutsideBlockingOverlay(overlayEl, e.target)) return;
      e.preventDefault();
      e.stopPropagation();
    }

    window.addEventListener('keydown', blockKeydownOutsideOverlay, true);
    return () => window.removeEventListener('keydown', blockKeydownOutsideOverlay, true);
  });

  // 🔴 s48 (четвёртая находка внешнего аудита, 2026-09-14): клавиатура закрыта блоком выше,
  // но на главной странице девять обработчиков нажатия МЫШЬЮ (карточки кабинетов, шестерёнка
  // настроек, кнопки «Продолжить/Новый проект» и др.) читали `trialConsentBlocking` только
  // через сочетания клавиш - ни один из них гейт не проверял, и в окне гонки (blockingActive
  // истинно, а {#if visible} ещё не смонтирован - Rust не ответил) клик мышью или касание
  // проходили. Чиним класс, а не девять обработчиков по отдельности: тот же приём, что и
  // выше - capture-listener на `window`, но для 'click' (событие, которым браузер выражает
  // и клик мышью, и синтетический клик касания, и активацию клавиатурой Enter/Space на
  // фокусе - двойное покрытие с блоком выше не мешает). Новый, ещё не написанный десятый
  // обработчик заведомо попадает под тот же перехватчик - его не нужно чинить отдельно.
  //
  // Чего этот приём НЕ закрывает (названо прямо, по требованию): (1) навигацию, запущенную
  // НЕ через событие 'click' - drag-and-drop, программный вызов без события пользователя;
  // такого в кодовой базе сегодня нет. (2) он не заменяет физическое перекрытие экрана
  // (invisible full-viewport shield с pointer-events) - та альтернатива тоже устраняла бы
  // находку, но полагалась бы на корректность z-index/stacking context, а её нельзя
  // подтвердить в jsdom (в нём нет layout-движка, click, отправленный программно на элемент,
  // достигает цели независимо от того, что должно визуально его перекрывать) - то есть
  // регресс CSS (соседний элемент со случайно более высоким z-index) не поймал бы ни один
  // тест. Capture-listener на событии, наоборот, проверяем тем же приёмом, что и клавиатуру
  // выше, и доказательно, а не «похоже на то же самое визуально».
  $effect(() => {
    if (!blockingActive) return;

    /** @param {MouseEvent} e */
    function blockClickOutsideOverlay(e) {
      if (!isKeydownOutsideBlockingOverlay(overlayEl, e.target)) return;
      e.preventDefault();
      e.stopPropagation();
    }

    window.addEventListener('click', blockClickOutsideOverlay, true);
    return () => window.removeEventListener('click', blockClickOutsideOverlay, true);
  });

  async function openTerms() {
    openError = '';
    try {
      await invoke('open_trial_terms');
    } catch (e) {
      // Понятное сообщение человеку, а не молчаливый отказ и не пустое окно (файл условий
      // поставляется правовым блоком отдельно от кода - до его прихода команда честно
      // отвечает ошибкой).
      openError = String(e);
    }
  }

  async function accept() {
    if (!agreed || busy) return;
    busy = true;
    errorMsg = '';
    try {
      await invoke('accept_trial_consent');
      trialConsentPromptOpen.set(false);
    } catch (e) {
      errorMsg = String(e);
    } finally {
      busy = false;
    }
  }

  async function decline() {
    if (declining) return;
    declining = true;
    try {
      // Единственное окно приложения, CloseRequested нигде не перехватывается (см.
      // src-tauri/src/lib.rs on_window_event) - закрытие окна завершает процесс.
      await getCurrentWindow().close();
    } catch {
      /* окно недоступно (тесты) - обработчик сам по себе доказывает намерение закрыть */
      declining = false;
    }
  }

  /** Focus-trap внутри модали, без закрытия по Escape - выбор должен быть явным.
   * @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Tab') {
      const focusable = /** @type {NodeListOf<HTMLElement>} */ (
        /** @type {HTMLElement} */ (e.currentTarget)?.querySelectorAll(
          'button:not([disabled]), input, [href], [tabindex]:not([tabindex="-1"])'
        )
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
</script>

{#if visible}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="trial-consent-title"
    tabindex="-1"
    onkeydown={handleKeydown}
    bind:this={overlayEl}
  >
    <div class="card">
      <div class="gradient-line"></div>

      <h2 id="trial-consent-title" class="title">Условия работы с программой</h2>

      <p class="body-text">
        Программа передана вам для ознакомления. До приобретения лицензии она используется на
        условиях ознакомительного использования: право на срок ознакомления, без платы,
        «как есть».
      </p>

      {#if showCloudProcessingParagraph}
        <p class="body-text">
          Часть функций отправляет содержание переданных в работу материалов на серверы
          Платформы Аврора и далее привлекаемым поставщикам вычислительных ресурсов, в том
          числе за пределами России.
        </p>
      {/if}

      <p class="body-text">
        Персональные данные в программу вводить нельзя.
      </p>

      <button type="button" class="open-terms-btn" onclick={openTerms}>
        Открыть условия
      </button>
      {#if openError}
        <p class="error-text">{openError}</p>
      {/if}

      <label class="consent-check">
        <input type="checkbox" bind:checked={agreed} />
        <span>Я принимаю Условия ознакомительного использования (редакция 2 от 14.09.2026)</span>
      </label>

      {#if errorMsg}
        <p class="error-text">{errorMsg}</p>
      {/if}

      <div class="actions">
        <button type="button" class="decline-btn" onclick={decline} disabled={declining}>
          {declining ? 'Закрытие…' : 'Отказаться'}
        </button>
        <button type="button" class="accept-btn" onclick={accept} disabled={!agreed || busy}>
          {busy ? 'Сохранение…' : 'Принимаю'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 10001;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: var(--overlay-bg);
    backdrop-filter: var(--blur-focus);
    -webkit-backdrop-filter: var(--blur-focus);
    animation: fadeIn 0.3s ease;
  }

  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 34px 34px 24px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow), var(--shadow-glow);
    max-width: 480px;
    width: 92%;
    max-height: 88vh;
    overflow-y: auto;
    animation: slideUp 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .card > * {
    flex-shrink: 0;
  }

  .gradient-line {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--gradient-accent-line);
  }

  .title {
    font-size: 19px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }

  .body-text {
    font-size: 13.5px;
    line-height: 1.6;
    color: var(--text-secondary);
    margin: 0;
  }

  .open-terms-btn {
    align-self: flex-start;
    padding: 9px 16px;
    background: transparent;
    color: var(--accent-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition);
  }

  .open-terms-btn:hover {
    background: var(--hover-bg);
  }

  .consent-check {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 14px;
    background: var(--hover-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }

  .consent-check input {
    margin-top: 2px;
    flex-shrink: 0;
    accent-color: var(--accent-primary);
    cursor: pointer;
  }

  .consent-check span {
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 2px;
  }

  .decline-btn {
    padding: 10px 18px;
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 13px;
    cursor: pointer;
    transition: all var(--transition);
  }

  .decline-btn:hover:not(:disabled) {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
  }

  .accept-btn {
    padding: 11px 26px;
    background: var(--gradient-primary);
    color: var(--text-on-accent, #fff);
    border: none;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition);
    box-shadow: var(--shadow-glow);
  }

  .accept-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    filter: brightness(1.08);
  }

  .accept-btn:disabled,
  .decline-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error-text {
    font-size: 12.5px;
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--danger) 15%, transparent);
    word-break: break-word;
    margin: 0;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes slideUp {
    from { transform: translateY(20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .overlay,
    .card {
      animation: none;
    }
  }
</style>
