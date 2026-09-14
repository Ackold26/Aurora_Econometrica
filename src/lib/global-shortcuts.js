/**
 * Единый источник правды для правила «пока окно условий ознакомительного использования
 * открыто — НИ ОДИН обработчик клавиш в приложении не исполняет действие» (s48,
 * 2026-09-14). Три носителя window-level `keydown` в продукте — `+layout.svelte`
 * (шапка, этот модуль изначально), `routes/+page.svelte` (главная страница — ровно та,
 * где TrialConsentOverlay появляется первым) и `routes/cabinet/+page.svelte` (кабинет,
 * достижим сразу после обхода с главной) — обязаны звать свою функцию отсюда и НЕ
 * дублировать проверку `trialConsentOpen` инлайн у себя: находка внешнего аудита s48
 * закрыла только шапку (`handleGlobalShortcut`), два других носителя вообще не смотрели
 * на состояние окна условий.
 *
 * 🔴 НАХОДКА (внешняя проверка s48, 2026-09-14, первая волна): раньше `handleGlobalShortcut`
 * была локальной функцией внутри onMount `+layout.svelte`, не проверявшей состояние
 * TrialConsentOverlay вовсе. `CommandPalette.svelte` при открытии программно ставит фокус
 * в своё поле ввода (`$effect` → `inputEl?.focus()`) — фокус - это DOM-состояние, а не
 * z-index, и более высокий слой блокирующего оверлея НИКАК не мешал печатать команду и
 * выполнить её (открыть кабинет, перейти в Настройки), пока условия стояли непринятыми.
 *
 * Каждая функция этого модуля принимает `trialConsentOpen` явным параметром (DI, не
 * читает store сама) — так тест подделывает `KeyboardEvent` и булево значение напрямую,
 * без монтирования тяжёлого layout/страницы и без мока svelte-стора (см.
 * src/tests/global-shortcuts.test.js). Правило одно и то же во всех трёх: пока
 * `trialConsentOpen` истинно — функция не делает ничего, первой строкой `return`.
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

/**
 * Обработчик клавиш главной страницы (`routes/+page.svelte`) — Ctrl+, → Настройки,
 * цифры 1-9 → открыть кабинет по индексу. Найдено внешним аудитом s48 (вторая волна):
 * это ровно та страница, на которой TrialConsentOverlay появляется первым, а обработчик
 * не смотрел на его состояние вовсе — цифра 1-9 открывала кабинет мимо непринятых условий.
 *
 * @param {object} params
 * @param {boolean} params.trialConsentOpen - открыто ли блокирующее окно условий.
 * @param {KeyboardEvent} params.event
 * @param {Array<unknown>} params.layoutCabinets - текущий список кабинетов ($layoutCabinets).
 * @param {() => void} params.gotoSettings
 * @param {(index: number) => void} params.openCabinetByIndex
 */
export function handleHomeShortcut({ trialConsentOpen, event, layoutCabinets, gotoSettings, openCabinetByIndex }) {
  if (trialConsentOpen) return;

  if (event.ctrlKey && event.key === ',') {
    event.preventDefault();
    gotoSettings();
    return;
  }

  const targetTag = /** @type {HTMLElement} */ (event.target)?.tagName;
  if (!event.ctrlKey && !event.altKey && !event.metaKey && /^[1-9]$/.test(event.key) && !['INPUT', 'TEXTAREA'].includes(targetTag)) {
    const idx = parseInt(event.key, 10) - 1;
    if (layoutCabinets[idx]) {
      openCabinetByIndex(idx);
    }
  }
}

/**
 * Обработчик клавиш кабинета (`routes/cabinet/+page.svelte`) — Ctrl+Shift+Z → дзен-режим,
 * Escape → выход (бриф → режим выполнения → дзен → назад на главную). Достижим сразу после
 * обхода блокирующего экрана с главной страницы (тот же аудит s48, вторая волна) — обработчик
 * тоже не смотрел на состояние окна условий.
 *
 * @param {object} params
 * @param {boolean} params.trialConsentOpen - открыто ли блокирующее окно условий.
 * @param {KeyboardEvent} params.event
 * @param {boolean} params.zenMode
 * @param {(value: boolean) => void} params.setZenMode
 * @param {unknown} params.pendingBriefCommand
 * @param {() => void} params.cancelBrief
 * @param {'selection' | 'execution'} params.workspaceMode
 * @param {(value: 'selection' | 'execution') => void} params.setWorkspaceMode
 * @param {() => void} params.goBack
 */
export function handleCabinetShortcut({ trialConsentOpen, event, zenMode, setZenMode, pendingBriefCommand, cancelBrief, workspaceMode, setWorkspaceMode, goBack }) {
  if (trialConsentOpen) return;

  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'z') {
    event.preventDefault();
    setZenMode(!zenMode);
    return;
  }

  const targetTag = /** @type {HTMLElement} */ (event.target)?.tagName;
  if (event.key === 'Escape' && !['INPUT', 'TEXTAREA'].includes(targetTag)) {
    if (pendingBriefCommand) { cancelBrief(); return; }
    if (workspaceMode === 'execution') { setWorkspaceMode('selection'); return; }
    if (zenMode) { setZenMode(false); return; }
    goBack();
  }
}

/**
 * Второй, независимый от проверок в конкретных обработчиках слой защиты (s48, аудит
 * второй волны, 2026-09-14). `handleHomeShortcut`/`handleCabinetShortcut`/
 * `handleGlobalShortcut` выше проверяют `trialConsentOpen` каждый у себя — работает для
 * известных на сегодня носителей, но каждый НОВЫЙ обработчик клавиш, который кто-то допишет
 * позже, рискует забыть эту проверку (класс регрессии, который уже случался дважды).
 *
 * Разбор аудита, почему обход вообще был возможен: `.overlay` гасит по Tab только СВОЙ
 * focus-trap, всплытие остальных клавиш не останавливает; маршрут главной страницы
 * рендерится ПОД оверлеем (Svelte не размонтирует фон) и продолжает слушать `window`; фокус
 * при появлении оверлея НЕ переносится внутрь него (в оверлее нет текстового поля для
 * автофокуса) — значит клавиатурный фокус мог остаться на фоновом элементе, и keydown уходил
 * прямиком в фоновый обработчик, если тот не проверял состояние сам.
 *
 * Эта функция — чистый предикат для страховки на уровне САМОГО гейта (`TrialConsentOverlay.
 * svelte`): пока окно условий открыто, компонент вешает СВОЙ слушатель `keydown` на `window`
 * в ФАЗЕ ПЕРЕХВАТА (`capture: true`) — первый узел на пути события, до цели и до всплытия. Для
 * каждого нажатия он спрашивает эту функцию: цель события лежит ВНУТРИ дерева оверлея (тогда
 * ничего не делает — Tab-trap, чекбокс, кнопки должны работать как обычно) или СНАРУЖИ (тогда
 * `stopPropagation()` останавливает весь дальнейший путь события целиком — ни один обработчик
 * продукта, старый или ещё не написанный, физически не получит это нажатие, проверяет он
 * `trialConsentOpen` сам или нет).
 *
 * @param {Node | null | undefined} overlayEl - корневой DOM-узел оверлея (`bind:this`).
 * @param {EventTarget | null} eventTarget - `event.target` нажатия клавиши.
 * @returns {boolean} true, если нажатие пришло СНАРУЖИ оверлея и должно быть погашено.
 */
export function isKeydownOutsideBlockingOverlay(overlayEl, eventTarget) {
  if (!overlayEl) return true; // оверлей ещё не смонтирован - блокируем на всякий случай
  if (!(eventTarget instanceof Node)) return true;
  return !overlayEl.contains(eventTarget);
}
