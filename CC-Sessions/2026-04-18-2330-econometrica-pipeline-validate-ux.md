---
tags: [session, compressed, econometrica, validate, ux, pipeline, objective]
type: session
updated: 2026-04-18
---
# Quick Reference

Длинная live-сессия с Антоном по пайплайну Econometrica на данных Кагоцел (31×34). Закрыли шаги 0 (Импорт) и 1 (Валидация) до состояния success. Реализован новый objective-driven флоу (ROI/Effectiveness/Manual overlay), auto-create project, retry-логика на коллизии имён, home hero logo с 3-кнопочной навигацией, compact ObjectiveSelector без scroll, unified role labels, Russian number formatting (`fmt.js`), 15+ help-icons с econometric объяснениями, stepper по центру через CSS grid, Expert-панели с красной рамкой и labels.

**Topic:** econometrica-pipeline-validate-ux

**Коммиты:** `72c6493` (Session 1 pipeline overhaul) · `539e11f` (home + overlay polish) · `83f28a2` (help icons + formatting + role unification)

**Key files:** `src/routes/+page.svelte`, `src/routes/pipeline/+layout.svelte`, `src/lib/project-state.js`, `src/lib/objective-engine.js`, `src/lib/fmt.js`, `src/lib/insights-rules.js`, `src/lib/components/ProjectSelector.svelte`, `src/lib/components/ConfigPanel.svelte`, `src/lib/components/pipeline/{ImportStep,ValidateStep,ModelTrainingStep,ObjectiveSelector,ColumnMapper,TrafficLight,InsightsPanel,StepWrapper,Expert{Validate,Model,Decompose}Panel}.svelte`, `sidecar/econometrica/engines/validator.py`, `static/logo-hero.png`

**Status:** Шаг 0 ✅ pass / Шаг 1 ✅ pass (ratio 1.72→2.4 после exclude) / Шаг 2 (Модель MCMC) — ready для следующего теста / Шаги 3-5 (Decompose/Optimize/Report) — ожидают

---

## Learnings

### L1 — Objective-driven validation как архитектурный сдвиг
До сессии пайплайн требовал ручной настройки ролей после импорта. Ручная работа на 23 каналах + 31 строке Кагоцел = нежизнеспособно. Решение — спросить **цель анализа** ДО валидации, автоматически применить фильтрацию ролей. Это не косметика, это смена ментальной рамки.
- Цель задаётся как store (`analysisObjective`: roi | effectiveness | manual)
- Overlay ObjectiveSelector с 3 карточками «Когда / Что сделает / К чему приведёт / Типичные кейсы»
- Post-validate applyObjectiveToColumns — auto-exclude, затем recomputeResultAfterObjective пересчитывает ratio/issues/status

### L2 — Tauri WebView2 ломает HTML5 drag-drop
`draggable="true"` + ondragstart/ondrop внутри webview не работает, потому что Tauri native-слой перехватывает drag-events для file-upload. Симптом: drag-indicator отрисовывается, но drop-handler никогда не вызывается.
**Паттерн:** В Tauri-приложениях не полагаться на HTML5 D&D. Использовать click-to-select + click-target-zone.

### L3 — Race между `+layout.onMount` и `Component.onMount`
При `goto('/pipeline?new=1')` layout ставит `activeProjectId.set(null)`, но `ProjectSelector.loadActiveProject()` в своём onMount асинхронно перетирает это через `invoke('project_get_active')`. Результат: пользователь нажал «Новый проект», а попал в старый.
**Паттерн:** Любой компонент, который восстанавливает state из backend, должен респектить query-параметр `?new=1` — skip restore.

### L4 — Persistent state через Rust-backend опасен без escape-hatch
Rust хранит `active_project.json` для бесшовного continuation. Но когда пользователь хочет начать заново — backend силой возвращает старый проект. Нужен явный **override механизм** (у нас: `?new=1` query + `resetForNewAnalysis()` на фронте).

### L5 — Drop-in функциональность, не меняющая компоненты через новые переменные
Применение objective к validation.result — через **мутацию columns** в локальной функции (applyObjectiveToColumns) + последующий **recompute** агрегатов (recomputeResultAfterObjective). Никаких изменений Python backend, всё на JS.

### L6 — double scroll-container → phantom scroll
`.pipeline-page` + `.pipeline-main` оба имели `overflow: auto` + `.step-wrapper.hidden` с `position: absolute; height: 100%`. Скрытые шаги (Decompose/Optimize/Report) рендерились в том же DOM (visibility-based switching), создавая виртуальную высоту в «невидимом» pipeline-page. Убрали overflow c pipeline-page — scroll owns только pipeline-main.

### L7 — min-height для unified alignment в flex/grid шапках
Разные компоненты с разным content имеют разную intrinsic height. Для выравнивания border-bottom по Y — нужен одинаковый `min-height: 52px` + одинаковый `padding` + `box-sizing: border-box` на обоих.

### L8 — Prefix-matching для русских морфологических пар
«Статьи (прочтения)» vs «Статьи Бюджет», «Спецпроекты» vs «Спецпроект» — разные строковые prefix. Решение: `canonicalPrefix()` — regex `^[А-ЯЁA-Z]+` + truncate до 6 символов (stem). Объединяет множественное/единственное число и варианты со скобками.

### L9 — Python validator + JS — рассинхрон formulas = 3 разных ratio на экране
До фикса:
- Python: `rows / (media + control)` → 1.0
- JS insights-rules: `rows / (media*3 + control + 2)` → 0.4
- JS dashboard chip: `rows / cols` → 1.0
Три разных числа на одном экране у одного пользователя. **Унификация** на `rows / (media + control)` — индустриальный standard, совпадает с Gemini/GCP/Lightweight MMM.

### L10 — UX-правило: не обнулять user work при фоновом действии
Создание проекта вручную (через ProjectSelector dropdown) вызывало `resetPipeline()` → теряла все импорты и валидации. Причина — скопировано из коменты где был «select different project». Fix: убрать resetPipeline() из createProject. Создание — аддитивно, смена — разрушительно.

---

## Decisions

### D1 — 3 кнопки на главной, унифицированный размер, отличие только цветом
Было: 2 кнопки разного размера (primary + skip). Антон: «одинаковый размер, одинаковый шрифт, отличие только цветом».
- padding 7×16, font 12, radius 7, font-weight 600
- Primary: solid accent / Secondary: outline accent / Tertiary: outline muted

### D2 — Полные названия для зон ColumnMapper, короткие для таблиц
Антон: «в 4 зонах полные названия (Медиа и управляемые факторы), в таблицах короткие (Медиа/Внешние/KPI/Дата)».
- Большие зоны нуждаются в контексте для новых пользователей
- Таблицы компактные — длинные лейблы ломают layout

### D3 — Authoring project name по бренду + «ММХ» + дата
Формат: `{brand} ММХ {DDMM-YY}` (пример: «Кагоцел РФ ММХ 1804-26»).
- brand = первое слово файла до разделителя (`+_—`) или ключевых слов («данные», «эконометрика»)
- При коллизии — retry с суффиксом (2), (3), ..., (30)

### D4 — Expert режим не дублирует, а дополняет
До: Expert ValidatePanel содержал копию корреляционной матрицы (с багом — highCorrelations не передавался). После: только **VIF-таблица** + **детальная статистика** (mean/std/missing%/zeros%). Корр.матрица — общедоступный инструмент, в main view. VIF — эконометрический показатель, эксклюзив для эксперта.

### D5 — Hide insights panel когда нечего показать
Insights-панель скрывается когда:
- `isObjectiveOverlay` (step 1 без result) — overlay занимает весь экран
- Импорт без файла (`step===0 && !importData.file`) — нет данных для комментирования
После загрузки файла / валидации — появляется.

### D6 — Hero logo на главной, Pipeline-карточка опускается
Антон: «добавь логотип по центру выше блока Visual Pipeline». Сделано: `static/logo-hero.png` (180px) + `.pipeline-stage` wrapper с gap: 32px.

### D7 — Stepper строго по центру viewport через CSS grid
Было: `display: flex` — stepper сдвигался вправо когда справа нет content. Стало: `grid-template-columns: 1fr auto 1fr` + `:global(*:nth-child(n))` justify-self. Центр гарантирован.

### D8 — ProjectSelector виден только на Import, read-only chip на других
Чтобы пользователь не мог случайно переключить проект в середине валидации/обучения. На шагах 1-5 — статический «📊 Имя» chip.

### D9 — switchObjective через re-validate, не in-place
In-place applyObjectiveToColumns не работает после первого выбора (в columns нет volume/cost пар — там уже только бюджеты). Fix: `analysisObjective.set(obj); runValidate();` — Python отдаёт fresh columns. Медленнее на 1 sidecar call, но детерминированно.

### D10 — Help-icons на параметрах таблиц — pill с accent фоном
Pattern: `<span class="help-icon" title="...">?</span>` — 13×13 circle, accent-20% bg, hover → solid primary. Использовать для всех цифровых параметров в таблицах (особенно для эконометрических: VIF, Ratio, CV, Std).

### D11 — Ratio tooltip с полной образовательной справкой
На Ratio-chip не просто «соотношение rows/cols», а: формула + пороги + рекомендации при низком значении (недельные данные, объединение парных метрик). Маркетолог получает мини-курс при hover.

---

## Solutions & Fixes

### Fix 1 — Ratio = 0.0:1 всегда (showstopper)
**Root cause:** `validateInsights` читал `result.detected?.rows` — у Python такого поля нет. rows хранится в `result.file.rows`. `totalRows = 0` → `currentRatio = 0` → в инсайте «ratio станет 0.0:1».
**Fix:** `result.file?.rows ?? result.detected?.rows ?? 0`.
**File:** `src/lib/insights-rules.js:131`

### Fix 2 — Ratio формула рассинхрон
**Было:** 3 разных значения (Python 1.0, JS detailed 0.4, JS chip 1.0).
**Fix:** унифицировано на `rows / (media + control)` во всех местах (Python validator + JS insights-rules).

### Fix 3 — prefix-matching для pair-grouping
**Bug:** «Статьи (прочтения)» → prefix `"СТАТЬИ ("`, «Статьи Бюджет» → `"СТАТЬИ"` — разные → не группируется → auto-apply ROI не исключил прочтения.
**Fix:** `canonicalPrefix()` — letters-only regex + 6-char stem.

### Fix 4 — switchObjective не переключает роли
**Bug:** после первого выбора ROI columns имеют только media=бюджеты. applyObjectiveToColumns при переключении на Effectiveness не видит volume, не может перестроить.
**Fix:** switchObjective вызывает runValidate() — fresh columns → apply new objective с нуля.

### Fix 5 — Auto-create project fails on name collision
**Bug:** Rust `project_create` возвращает error при existing name. Silent catch → activeProjectId=null → trainModel молча return.
**Fix:** retry-loop в ImportStep — `{baseName}`, `{baseName} (2)`, ..., `(30)`.

### Fix 6 — Backend перетирает активный проект после "Новый проект"
**Bug:** `ProjectSelector.loadActiveProject()` асинхронно после `goto('/pipeline?new=1')` восстанавливает старый activeProjectId.
**Fix:** skip restore если `?new=1` в URL. Дублируется в `pipeline/+layout.svelte.onMount`.

### Fix 7 — createProject() сбрасывал текущий прогресс
**Bug:** `ProjectSelector.createProject()` вызывала `resetPipeline()` — теряла импорт и валидацию при создании нового проекта вручную.
**Fix:** убрать resetPipeline() — создание теперь аддитивное.

### Fix 8 — Project name не помещался в ProjectSelector
**Fix:** `.project-area { min-width: 260px; max-width: 360px }` + dropdown `width: max-content` до 520px.

### Fix 9 — Scroll в пустоту на шаге Модель
**Bug:** `.pipeline-page` + `.pipeline-main` оба с `overflow: auto`. Скрытые step-wrappers (visibility-based) создавали виртуальную высоту.
**Fix:** убрать overflow с `.pipeline-page` — scroll owns pipeline-main. `.model-training-step` — без `height: 100%`/`overflow-y`, чтобы не создавать nested scroll.

### Fix 10 — Header bottom-borders на разных уровнях (Импорт vs ИНСАЙТЫ)
**Fix:** `.step-header` и `.panel-header` — общий `min-height: 52px` + `padding: 14px X 12px` + `box-sizing: border-box`.

### Fix 11 — Stepper не по центру (сдвигался вправо)
**Fix:** `.pipeline-header` → `grid-template-columns: 1fr auto 1fr` + justify-self для детей. Stepper всегда строго по центру.

### Fix 12 — isComputing залипал в true
**Bug:** после applyAction/switchObjective trainModel проверял `$isComputing`, а он остался true от прежнего запуска.
**Fix:** `ModelTrainingStep.onMount` — если savedTaskId is null, сбрасывать isComputing = false.

### Fix 13 — Кнопка «Запустить» не активна без feedback
**Bug:** silent return в trainModel при отсутствии `projectId` / `selectedKpi` / `enabledChannels`.
**Fix:** computeStatus.set(error message) + `setTimeout(clear, 5000)` — пользователь видит причину.

### Fix 14 — Корр.матрица дубликат в Expert с багом «не обнаружена»
**Bug:** `ExpertValidatePanel` передавал только `correlationMatrix` без `highCorrelations` → compound говорил «не обнаружена», а tooltip показывал есть.
**Fix:** убрать дубль компонента. Матрица одна, в main view. Expert добавляет VIF.

### Fix 15 — Duplicate empty-state «🔍 Запустите валидацию»
**Bug:** idle-state рендерился одновременно с ObjectiveSelector overlay.
**Fix:** удалить idle-state block — overlay полностью заменяет.

### Fix 16 — Expert toggle / insights видны на overlay
**Fix:** условие `!isObjectiveOverlay` на обоих элементах.

### Fix 17 — Расширенные настройки видны маркетологу
**Fix:** `{#if $expertMode}` вокруг advanced-section. Плюс `$effect(() => { if ($expertMode) showAdvanced = true })` — автораскрытие при переключении.

### Fix 18 — completeStep(1) не срабатывал при recompute
**Bug:** если status меняется с error → warning после apply/revert, `pipelineStepMeta[2].status` остаётся 'locked'.
**Fix:** `syncStepLockAfterValidate(result)` после каждого recompute — вызывает completeStep(1) или setStepError(1).

### Fix 19 — Filename на drop-zone в 2 строки
**Fix:** `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: min(85vw, 1100px)`.

### Fix 20 — Цвет кнопок действий в инсайтах — выглядели как текст
**Fix:** solid background (var(--success) для warning, var(--danger) для error) + white text + box-shadow. `.fix-btn` и `.action-btn` — полноцветные, не outline-только.

---

## Files Modified

### Коммит `72c6493` (Session 1 — objective + pre-training + fixes) — 17 файлов
- `sidecar/econometrica/engines/validator.py` — MEDIA_PATTERNS (OOH/OTS/TV)
- `src/lib/components/ConfigPanel.svelte` — Expert UI (red border, help icons, auto-expand)
- `src/lib/components/ProjectSelector.svelte` — no resetPipeline, ?new=1 skip
- `src/lib/components/pipeline/{ExpertDecompose,ExpertModel,ExpertValidate}Panel.svelte` — red border + label
- `src/lib/components/pipeline/ImportStep.svelte` — auto-create, buildProjectName
- `src/lib/components/pipeline/InsightsPanel.svelte` — apply/revert, recompute, step unlock, objective param
- `src/lib/components/pipeline/ModelTrainingStep.svelte` — isComputing reset, scroll fix
- `src/lib/components/pipeline/ObjectiveSelector.svelte` (NEW) — 3 cards overlay
- `src/lib/components/pipeline/StepWrapper.svelte` — min-height
- `src/lib/components/pipeline/ValidateStep.svelte` — segmented control, switchObjective
- `src/lib/insights-rules.js` — canonicalPrefix, modelPreTrainingInsights, objective recs, ratio fix, bulk-apply
- `src/lib/objective-engine.js` (NEW) — applyObjectiveToColumns, recomputeResultAfterObjective
- `src/lib/project-state.js` — analysisObjective store
- `src/routes/pipeline/+layout.svelte` — project chip conditional
- `src/routes/pipeline/+page.svelte` — убран overflow

### Коммит `539e11f` (home + overlay polish) — 10 файлов
- `static/logo-hero.png` (NEW, 56KB)
- `src/lib/components/ProjectSelector.svelte` — delete button, width, ?new=1 skip
- `src/lib/components/pipeline/ImportStep.svelte` — retry-30, nowrap filename
- `src/lib/components/pipeline/InsightsPanel.svelte` — min-height 52px
- `src/lib/components/pipeline/ObjectiveSelector.svelte` — compact no-scroll, badge "80% моделей"
- `src/lib/components/pipeline/StepWrapper.svelte` — min-height 52px
- `src/lib/components/pipeline/ValidateStep.svelte` — idle-state removed
- `src/lib/project-state.js` — resetForNewAnalysis()
- `src/routes/+page.svelte` — hero logo, 3 buttons, pipeline-stage
- `src/routes/pipeline/+layout.svelte` — grid header, ?new=1, hideInsightsPanel

### Коммит `83f28a2` (help icons + formatting + role unification) — 5 файлов
- `src/lib/fmt.js` (NEW) — fmtNum, fmtPct
- `src/lib/components/pipeline/ColumnMapper.svelte` — heading, short→full role labels, click-only, tooltip on conf-badge
- `src/lib/components/pipeline/ExpertValidatePanel.svelte` — fmtNum, help-icons ×8, no corr heatmap dup
- `src/lib/components/pipeline/TrafficLight.svelte` — fmtNum, help-icons ×6, Ratio tooltip
- `src/lib/components/pipeline/ValidateStep.svelte` — switchObjective via runValidate

---

## Setup & Config Changes

- Нет изменений в tauri.conf.json, Cargo.toml, package.json.
- Все изменения — на уровне фронтенда (Svelte/JS) + один Python-паттерн в validator.py.
- Memory: новый файл `project_econometrica_pipeline_ux.md` в `C:/Users/ackol/.claude/projects/D--Docs-Aurora-Ai/memory/` + ссылка в MEMORY.md.

---

## Pending Tasks

### Live-test (приоритет 1)
- [ ] TEST 5 — Запуск Модели (MCMC обучение) на 6-8 каналах Кагоцел
- [ ] TEST 6 — Декомпозиция (waterfall chart, base sales)
- [ ] TEST 7 — Оптимизация (budget optimizer, response curves)
- [ ] TEST 8 — Отчёт (XLSX/PPTX export)

### Tech debt (приоритет 2)
- [ ] Auto-watcher на `result.status` для мгновенной разблокировки «Далее» без клика
- [ ] Скрывать bulk-карточку «Оставить бюджеты (N канала)» если `result.objective_applied` уже применён (дубль)
- [ ] Диалог «Создать проект» — починить размер если потребуется (сейчас обходится auto-create)

### Phase 3 идеи (отложено)
- [ ] Fun per-card accents для KPI/Insight карточек — переменные готовы, компоненты ещё не используют
- [ ] Condition number + eigenvalues в Expert панели (дополнительный уровень мультиколлинеарной диагностики)
- [ ] Durbin-Watson для residuals (после модели)
- [ ] Синхронизация design-system фиксов в 9 других Aurora продуктов (только Econometrica + Parser получили)

### Prod release (после live-теста)
- [ ] v1.0.8 build + публикация (GitHub Releases + Supabase + rosst-updates manifest)

---

## Errors & Workarounds

### E1 — Python `project_create` не идемпотентна
`invoke('project_create', { name })` возвращает error при существующем проекте вместо activate.
**Workaround:** retry в ImportStep с суффиксами (2), (3), ..., (30).
**Proper fix (отложено):** добавить Rust команду `project_create_or_activate` или `project_upsert`.

### E2 — HTML5 drag-drop не работает в Tauri WebView2
Native слой перехватывает для file-upload.
**Workaround:** убрали draggable/ondragstart/ondrop из ColumnMapper. Click-to-assign работает детерминированно.
**Proper fix (отложено):** Tauri-specific drag API через плагин или через `dragDropEnabled: false` в tauri.conf (но сломает file-drop в ImportStep).

### E3 — ProjectSelector перетирает layout reset через async race
`loadActiveProject()` async вызывается из onMount ПОСЛЕ того как layout поставил null.
**Workaround:** оба места проверяют `?new=1` и skip restore.
**Proper fix (отложено):** перенести restore-логику целиком в layout, ProjectSelector должен только читать store.

### E4 — Rust backend persist даже при frontend reset
`active_project.json` на диске живёт до следующего project_activate/create.
**Workaround:** query-флаг `?new=1` обрабатывается на фронте.
**Proper fix (отложено):** Rust-команда `project_deactivate` (delete active_project.json) + вызов из resetForNewAnalysis().

### E5 — Sidecar может оставить isComputing=true при крэше
Training task может упасть до `setTimeout(() => isComputing.set(false))`.
**Workaround:** `ModelTrainingStep.onMount` чистит флаг если savedTaskId null.

### E6 — Гемини и наш ratio не совпадали
Gemini считал `31/8 = 3.87` (rows/cols). Наш JS считал `31/(8*3+7+2) = 0.93`. Оба математически правильны но разные.
**Workaround:** унифицировали на Gemini-формулу (rows/(media+control)) — индустриальный stadard.

---

## Full Session Notes

### Хронология

1. **Начало** — продолжение live-теста после Session 1 (72c6493). Антон на главной, активный проект «1test» из предыдущей сессии.

2. **Логотип на главной** — Антон попросил hero-лого над Visual Pipeline карточкой. Скопирован `6_Aurora_Ai_logo/PNG/Logo_PNG_1.png` → `static/logo-hero.png`. Обёртка `.pipeline-stage` с flex-column + gap 32px.

3. **Перенос строки в описании Pipeline** — через `<br>` + `.pipeline-steps-line` nowrap chip.

4. **3 кнопки вместо 2** — новый UX: «Продолжить проект» / «Новый проект» / «Перейти к командам». Унифицированные стили — padding 7×16, font 12, radius 7, отличие только фоном. `resetForNewAnalysis()` функция в project-state.js.

5. **Race condition backend-restore** — `?new=1` флаг обрабатывается в layout + ProjectSelector. Race fix.

6. **Auto-create project retry** — ImportStep в цикле 30 попыток при коллизии Rust error «уже существует».

7. **ProjectSelector widening** — чтобы «Кагоцел РФ ММХ 1804-26 (2)» помещалось. 260-360px area, dropdown до 520px.

8. **Удаление проектов через 🗑** — per-item delete button в dropdown, confirm + Rust `project_delete`.

9. **ObjectiveSelector overlay проверка** — работает, 3 карточки, CTA. Задача: compact для 1080p без scroll.

10. **Compact ObjectiveSelector** — padding 14 (-36%), gap 10 (-28%), heading 18 (-18%), intro gap 16 (-43%). Все 3 карточки без scroll.

11. **Empty-state cleanup** — idle-state с 🔍 удалён из ValidateStep (overlay заменяет).

12. **Hide Expert toggle + Insights panel на overlay** — оба через `isObjectiveOverlay = step===1 && !$validateData?.result`.

13. **Hide Insights panel на пустом Import** — дополнительно `(step===0 && !importData.file)`.

14. **Alignment заголовков** — `.step-header` и `.panel-header` общий `min-height: 52px` + `padding: 14px X 12px`.

15. **Stepper grid-по-центру** — `grid-template-columns: 1fr auto 1fr`.

16. **Filename nowrap** — ellipsis + max-width.

17. **Auto-create project baг** — коллизия имён → retry-loop.

18. **Badge «80% моделей» на ROI card** — pill-форма в правом углу card-head.

19. **Текст "Рекомендую опытным аналитикам" → "Рекомендовано опытным специалистам"** — по требованию.

20. **Перенос строки в intro**: `<br>` перед «Проверьте 3 варианта» — 3 строки → 2.

21. **Expert vs Main режим дублирование**: Антон задал вопрос "чем Expert отличается?". Объяснила + убрала дубль CorrelationHeatmap из ExpertValidatePanel.

22. **«Мультиколлинеарность не обнаружена» при наличии высоких корреляций** — баг: highCorrelations не передавался в Expert-копию heatmap (по умолчанию [] → зелёная надпись, но tooltip проверяет свой threshold). Дубль удалён.

23. **Drag-drop не работает в ColumnMapper** — Tauri WebView2 перехватывает HTML5 D&D. Убрали draggable/handlers, оставили click-to-assign.

24. **Tooltip на conf-badge** (проценты 70/85/90%) — объяснение что это confidence автодетекции.

25. **Switch ROI/Effectiveness/Manual не работал** — in-place apply не мог видеть volume после ROI (только media=budgets). Fix через runValidate().

26. **Role labels unification** — полные в ColumnMapper (4 зоны), короткие в таблицах.

27. **Number formatting (Russian)** — `src/lib/fmt.js` с fmtNum + fmtPct. Применение в TrafficLight stats-table + Expert stats-table + VIF.

28. **Help-icons системно** — 14+ пиктограмм `?` с title-tooltip. TrafficLight (6), Expert VIF (3), Expert stats (5), Ratio chip (1 большой с формулой и порогами).

29. **Финальный коммит + память** — обновлена `project_econometrica_pipeline_ux.md` в .claude memory.

### Ключевые скриншоты тестирования

- Home page с 3 кнопками + hero logo — ✅ идеально
- Import step с auto-created «Кагоцел РФ ММХ 1804-26 (2)» — ✅
- Validate overlay (compact) — все 3 карточки без scroll ✅
- Validate result после ROI — status=success, Мультиколлинеарность не обнаружена ✅
- Expert panel с VIF (без дубля heatmap) — ✅
- Stepper по центру на всех шагах ✅

### Важные технические детали

- **Store архитектура** — все pipeline data в memory-only stores (A4 rule), не persisted. Persisted только step metadata в localStorage.
- **pipelineStepMeta loading** — при `?new=1` сбрасывается на `defaultStepMeta()`, иначе восстанавливается через `loadPipelineForProject(projectId)` из localStorage.
- **Python sidecar сохранит backward compat** — validator.py обновлён только для новых MEDIA_PATTERNS, остальное не трогалось.
- **Svelte 5 runes** — все компоненты используют `$state`, `$derived`, `$effect`, `$props`. Обратная совместимость не важна.

### Commits

```
83f28a2 feat(validate): help icons, number formatting, role unification, ColumnMapper fixes
539e11f feat(ux): home hero logo, 3-button nav, project lifecycle, overlay polish
72c6493 feat(pipeline): objective-driven validation + pre-training insights + UX fixes
```

3 коммита, ~32 файла, ~1900 insertions / ~280 deletions.

### Memory

- `project_econometrica_pipeline_ux.md` — three sections: Session 1 / Session 2 / Session 3
- Обновлен `MEMORY.md` с ссылкой
