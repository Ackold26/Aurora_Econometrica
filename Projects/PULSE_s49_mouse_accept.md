# PULSE s49 — приёмка гейта мыши

Задача: проверить починку 5ee6c875 в TrialConsentOverlay.svelte — перехватчик click в capture-фазе на window,
призванный закрыть окно гонки, где клик мышью проходил мимо непринятых условий (обработчики клавиш величину
blockingActive знали, обработчики мыши на главной странице — нет). Нужно доказать фактом (не чтением кода)
пять пунктов: 1) зелёные тесты, 2) красное при отключённом перехватчике (тест ловит именно этот дефект),
3) окно условий по-прежнему кликабельно изнутри, 4) снятие перехватчика после принятия, 5) честная граница —
что приём НЕ закрывает (mousedown/pointerdown/touchstart/programmatic goto).

## План
1. Найти файлы тестов (ls src/tests | grep -i trial), прочитать компонент.
2. Прогнать целевые тесты — зафиксировать числа.
3. Временно отключить регистрацию click-перехватчика → прогнать тесты → зафиксировать красное → вернуть файл, проверить git status пусто.
4. Проверить/дописать тест на клики внутри окна условий.
5. Проверить/дописать тест на снятие слушателя после blockingActive=false.
6. Грепнуть +page.svelte и соседние маршруты на mousedown/pointerdown/touchstart/dblclick/goto по таймеру.
7. Записать ACCEPT_s49_mouse_gate.md с вердиктом.

Старт: 2026-09-18 (время не синхронизировано с системными часами сессии, отмечаю по факту хода работы).

- Прочитан компонент TrialConsentOverlay.svelte и оба тестовых файла. Пункты 3 (клики внутри
  оверлея не гасятся, строки 292-313) и 4 (снятие перехватчика после принятия, строки 315-333)
  УЖЕ покрыты готовыми тестами в trial-consent-overlay.test.js - дописывать не требуется,
  достаточно прогнать и подтвердить фактом.

- 11:01 Пункт 1 (зелёное) — npx vitest run src/tests/trial-consent-overlay.test.js
  src/tests/trial-consent-gate-race.test.js → Test Files 2 passed (2), Tests 24 passed (24).
- 11:01 Начинаю пункт 2 (красное на нынешнем коде): временно нейтрализую регистрацию click-
  перехватчика в TrialConsentOverlay.svelte.

- 11:02 Пункт 2 (красное) подтверждён: закомментирована строка window.addEventListener('click', ...)
  в $effect (строка 112). Прогон дал Test Files 1 failed | 1 passed (2), Tests 2 failed | 22 passed (24).
  Упали РОВНО два теста мышиного блока: "клик МЫШЬЮ на фоновом элементе... не доходит до обработчика
  продукта" и "перехватчик активен ДО монтирования разметки окна" — AssertionError: expected vi.fn()
  to not be called at all, but actually been called 1 times (клик дошёл до фонового обработчика).
  Остальные 22 теста, включая клики внутри оверлея и снятие перехватчика, остались зелёными
  (ожидаемо — они не зависят от снятой регистрации). Тест ловит именно починенный дефект.
  Файл возвращён git checkout --, git status --short пуст.
- 11:03 Пункты 3 и 4 уже покрыты готовыми тестами (строки 292-313, 315-333 trial-consent-overlay.test.js),
  подтверждены тем же зелёным прогоном 24/24 в пункте 1 — доп. тесты не нужны.
- 11:03 Начинаю пункт 5 (граница честности): грепаю routes на mousedown/pointerdown/touchstart/dblclick/goto по таймеру.

- 11:05 Грепы в src/routes: on:mousedown/onmousedown/on:pointerdown/onpointerdown/on:touchstart/
  ontouchstart/on:dblclick/ondblclick — 0 совпадений. goto() по таймеру — 0 (все setTimeout в routes
  сбрасывают текстовые сообщения, не навигация). Программные goto() при монтировании (guard-редиректы
  brand/[id], brands на !$isCreativeHub) есть, но недостижимы в окне гонки (сами требуют клика для
  захода на маршрут).
- 11:06 Грепы шире, по src/lib/components: найдены onmousedown (FileList.svelte:308, InsightsPanel.svelte:703,
  SlidePanel.svelte:91 — resize-handle), onpointerdown (WorkflowCanvas.svelte:267,309,325 — drag узлов),
  ondblclick (ColumnMapper.svelte:377, WorkflowCanvas.svelte:310, SessionTimer.svelte:52). Проверил импорты
  +layout.svelte и +page.svelte (первый экран, где идёт окно гонки) — из всех шести файлов ТОЛЬКО
  SessionTimer.svelte смонтирован на первом экране (+layout.svelte:21, +page.svelte:47); остальные пять —
  внутри /pipeline и /workflow, недостижимы до прохода через гейт.
- 11:08 Пробник в реальном браузере (Playwright, page.locator('#btn').dblclick() — настоящий двойной клик,
  не dispatchEvent): capture-слушатель click с preventDefault()+stopPropagation() гасит оба click-события
  (clickCount=2), но браузер ВСЁ РАВНО генерирует нативный dblclick (dblClickCount=1). ФАКТ подтверждён:
  перехватчик click НЕ гасит dblclick — это отдельное браузерное событие.
  НАХОДКА: SessionTimer.svelte:52 (ondblclick={handleDblClick} → resetTimer()) смонтирован на главном
  экране (+layout.svelte и +page.svelte) и переживает окно гонки — двойной клик по кнопке таймера в первые
  миллисекунды после запуска (пока blockingActive=true, окно условий ещё не смонтировано) сбросит таймер
  сессии в обход перехватчика. Навигацию/обход согласия это НЕ даёт (resetTimer не открывает доступ к
  программе), поэтому это не дыра в правовом гейте, а узкая функциональная утечка класса «клик» -
  докладываю отдельно, не блокирует приёмку.
- 11:09 Пишу ACCEPT_s49_mouse_gate.md.

- 11:12 ACCEPT_s49_mouse_gate.md записан. Вердикт: ПРИНЯТО, с находкой SessionTimer.svelte:52
  (ondblclick пережил окно гонки — не блокирует приёмку). Задача завершена, отчёт передаю в
  сообщении team-lead.
