<script>
  /**
   * Кнопка «Сообщить о проблеме» для мест, где человек видит сбой (окно ошибки шага
   * пайплайна). Экран и текст ошибки берутся из места вызова САМИ — это и есть главный
   * смысл задачи: из настроек их взять неоткуда, а тут они уже известны.
   */
  import { openFeedbackForm, feedbackErrorText } from '$lib/feedback.js';

  /** @type {{ekran: string, oshibka?: string}} */
  const { ekran, oshibka = '' } = $props();

  let opening = $state(false);
  let error = $state('');
  /**
   * Форма только что успешно открылась в браузере.
   *
   * 🔴 CPD-178, тот же дефект в шести окнах ошибки пайплайна (Импорт/Валидация/Модель/
   * Декомпозиция/Оптимизация/Отчёт): после успешного открытия `opening` возвращался в `false`,
   * кнопка выглядела так же, как до нажатия — человек в момент сбоя не получал вообще ничего.
   * Подтверждение стоит РЯДОМ с кнопкой, не на ней, и не гаснет по таймеру (см. то же решение
   * в `settings/+page.svelte`); текст короче — окно ошибки тесное.
   */
  let justOpened = $state(false);

  async function report() {
    opening = true;
    justOpened = false;
    error = '';
    try {
      await openFeedbackForm(ekran, oshibka);
      justOpened = true;
    } catch (err) {
      // Отказ обратной связи не мешает работе программы: это не её основная обязанность.
      error = feedbackErrorText(err);
    } finally {
      opening = false;
    }
  }
</script>

<button type="button" class="feedback-report-btn" onclick={report} disabled={opening}>
  {opening ? 'Открываю форму…' : 'Сообщить о проблеме'}
</button>
{#if justOpened}
  <p class="feedback-report-success" role="status">Форма открылась в браузере.</p>
{/if}
{#if error}
  <p class="feedback-report-error" role="status">{error}</p>
{/if}

<style>
  .feedback-report-btn {
    /* Внутри окна ошибки шага «Импорт» кнопка стоит в строке с растущим текстом
       ошибки (.error-banner{display:flex} без переноса). Без этих двух свойств
       на длинном тексте её сжимает до ширины самого длинного слова, и надпись
       ломается посреди обращения к нам. Находка внешнего аудита 14.09. */
    flex-shrink: 0;
    white-space: nowrap;
    margin-top: 6px;
    padding: 5px 12px;
    background: transparent;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.16));
    border-radius: 6px;
    color: var(--text-secondary, #b6b6c5);
    font-size: 11.5px;
    cursor: pointer;
  }
  .feedback-report-btn:disabled {
    opacity: 0.6;
    cursor: default;
  }
  @media (prefers-reduced-motion: no-preference) {
    .feedback-report-btn {
      transition: background 0.15s, border-color 0.15s;
    }
    .feedback-report-btn:hover:not(:disabled) {
      background: color-mix(in srgb, var(--text-primary) 6%, transparent);
      border-color: color-mix(in srgb, var(--text-primary) 24%, transparent);
    }
  }
  .feedback-report-error {
    margin: 4px 0 0;
    font-size: 11px;
    color: var(--danger, #ef4444);
  }
  .feedback-report-success {
    margin: 4px 0 0;
    font-size: 11px;
    color: var(--success, #10b981);
  }
</style>
