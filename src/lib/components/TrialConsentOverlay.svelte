<script>
  import { invoke } from '@tauri-apps/api/core';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { trialConsentPromptOpen } from '$lib/store.js';
  import { SHOW_CLOUD_PROCESSING_PARAGRAPH } from '$lib/trial-terms-config.js';

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
  // 🔴 Дата в тексте отметки ниже ОБЯЗАНА совпадать с TRIAL_TERMS_REVISION в
  // src-tauri/src/commands/user_config.rs - сторож расхождения:
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

  const visible = $derived($trialConsentPromptOpen);

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
        <span>Я принимаю Условия ознакомительного использования (редакция от 14.09.2026)</span>
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
