/**
 * Обработчик глобальных сочетаний клавиш шапки приложения (Ctrl+K/Cmd+K — командная
 * палитра, Ctrl+G/Cmd+G — глоссарий). Вынесен из `+layout.svelte::onMount` в отдельный
 * модуль (s48, 2026-09-14), чтобы ПРАВИЛО «пока окно условий ознакомительного использования
 * открыто — сочетания клавиш не работают вовсе» проверялось прямым вызовом функции, а не
 * монтированием всего layout (тяжёлые зависимости — ни один существующий тест в продукте
 * так не делает).
 *
 * 🔴 НАХОДКА (внешняя проверка s48, 2026-09-14): раньше это была локальная функция внутри
 * onMount, которая не проверяла состояние TrialConsentOverlay вовсе. `CommandPalette.svelte`
 * при открытии программно ставит фокус в своё поле ввода (`$effect` → `inputEl?.focus()`) —
 * фокус - это DOM-состояние, а не z-index, и более высокий слой блокирующего оверлея НИКАК
 * не мешал печатать команду и выполнить её (открыть кабинет, перейти в Настройки), пока
 * условия стояли непринятыми. Ровно в точке, где по правовой конструкции фиксируется
 * согласие («начало использования Программы означает согласие»), проверки не было.
 * Правило теперь: пока `trialConsentOpen` истинно — обработчик не делает ничего.
 *
 * @param {object} params
 * @param {boolean} params.trialConsentOpen - открыто ли блокирующее окно условий.
 * @param {boolean} params.paletteOpen - текущее состояние командной палитры.
 * @param {(open: boolean) => void} params.setPaletteOpen
 * @param {() => void} params.toggleGlossary
 * @param {KeyboardEvent} params.event
 */
export function handleGlobalShortcut({ trialConsentOpen, paletteOpen, setPaletteOpen, toggleGlossary, event }) {
  if (trialConsentOpen) return;

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    setPaletteOpen(!paletteOpen);
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'g') {
    // Audit fix v1.3.0: guard против modal stacking - не показывать
    // glossary если CommandPalette открыт (избегаем z-index overlap).
    if (paletteOpen) return;
    event.preventDefault();
    toggleGlossary();
  }
}
