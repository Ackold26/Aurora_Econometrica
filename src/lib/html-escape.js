/**
 * html-escape.js — экранирование HTML для вставки текста в innerHTML.
 *
 * Zero-deps (намеренно отдельно от echarts-setup.js, который статически тянет весь
 * echarts-бандл — pure-модули и их тесты не должны его подтягивать). Используется
 * во всех chart-tooltip'ах: имена серий/каналов/сценариев и даты приходят из данных
 * пользователя (загруженные колонки, имена сценариев) → без экранирования это XSS.
 *
 * @param {unknown} s
 * @returns {string} экранированная строка (no-op для строк без спецсимволов)
 */
export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (/** @type {string} */ c) =>
    /** @type {Record<string, string>} */ ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c] ?? c);
}
