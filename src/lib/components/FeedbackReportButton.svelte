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

  async function report() {
    opening = true;
    error = '';
    try {
      await openFeedbackForm(ekran, oshibka);
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
{#if error}
  <p class="feedback-report-error">{error}</p>
{/if}

<style>
  .feedback-report-btn {
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
</style>
