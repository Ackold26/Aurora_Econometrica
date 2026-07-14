# Батч 3b — реализация (2026-07-13)

Ветка `feat/econ-v2.3.0` (worktree). НЕ закоммичено — оставлено в рабочем дереве на проверку.

## 3.1 — Психо-фазы: убран ложный процесс

Файл: `content-packs/psy-data.json`, ключ `cabinetPhases.econometrist`.

Было (выдуманный расчётный процесс на ЛЮБОЕ сообщение кабинета, включая 8 консультационных команд):
- 10с: «Строю байесовскую модель…»
- 30с: «MCMC-сэмплирование…»
- 300с: «Рассчитываю ROI и декомпозицию…»

Стало (нейтрально, честно — Аврора работает с готовыми результатами):
- 10с: «Анализирую данные модели…»
- 30с: «Готовлю разбор…»
- 300с: «Формулирую выводы и рекомендации…»

Не тронуты (уже нейтральны): 0с «Загружаю данные…», 120с «Проверяю конвергенцию…», 600с «Оформляю результаты…». Структура/тайминги JSON не менялись.

Механика проверена: `src/lib/components/ChatPanel.svelte` — при получении `pipeline_phase` event (строка ~435-449) выставляется `pipelinePhaseReceived = true`, и timer-based обновление (строка ~752-758, `getCurrentPhase` из `psy.js`) прекращает двигать фазы (`if (cancelled || !startTime || pipelinePhaseReceived) return;`). Значит cabinetPhases-таймер срабатывает только когда движок молчит — то есть в чате/консультациях. Реальный MMM-расчётный пайплайн не задет.

⚠️ **content-pack изменён → нужен re-sign.**

## 3.6 — Онбординг кабинета

### (а) CabinetOnboarding.svelte vs render-ветки

Компонент `src/lib/components/CabinetOnboarding.svelte` (строки 63/81/96) рендерит ТОЛЬКО три ветки: `stepConfig.id === 'upload'`, `'analyze'`, `'result'`. Правку самого компонента решил не делать — вместо этого привёл id в content-pack к уже существующим render-веткам (минимальная хирургичная правка, компонент не трогается).

### (б) content-packs/onboarding-data.json — приведён к активным командам

Было: id `import`/`train`/`analyze` (train/analyze не матчили render-ветки → шаги 1-2 пустые, «Готово» недостижимо), ссылки на скрытые `/mmm-model`, `/mmm-decomposition`, `/mmm-optimize`, `/mmm-report`; noviceCommands — 9 легаси `/mmm-*` + awareness.

Стало:
- Шаг 1: `id: "upload"`, triggerCondition `hasFiles` — загрузка результатов модели.
- Шаг 2: `id: "analyze"`, triggerCondition `hasResponse`, `focusCommand: "/interpret-model"` — задать вопрос по модели.
- Шаг 3: `id: "result"`, triggerCondition `manual`, `nextActions: ["/why-channel", "/data-gaps", "/next-quarter-plan"]`.
- `noviceCommands`: все 8 активных консультационных команд (`/interpret-model`, `/why-channel`, `/explain-ratio`, `/pilot-design`, `/next-quarter-plan`, `/data-gaps`, `/awareness-forecast`, `/awareness-to-sales`).

Тексты шагов переписаны под консультационную модель (не «обучите модель», а «загрузите готовые результаты / задайте вопрос»), т.к. econometrist в проде — кабинет-советник по готовым результатам, а не MMM-расчётный пайплайн.

Проверено: `src/lib/onboarding-state.js::TOUR_STEP_KEYS` (`'import'`, `'validate'`, `'model'`...) — отдельная независимая механика FirstRunTour-коуч-марок, НЕ связана с `onboarding-config.js`/`CabinetOnboarding.svelte`. Тест `onboarding-firstrun-gate.test.js` использует её generic-ключи произвольно ('import', 'optimize', 'validate') — не про econometrist content-pack. Не тронуто.

⚠️ **content-pack изменён → нужен re-sign.**

## 3.7 — Мёртвые кнопки «Инструкция»/«Справка»

### Исследование

1. `src-tauri/help/econometrist.html` существует (734 строки) — детальный, качественный, но **полностью легаси**: документирует 9 скрытых команд (`/mmm-prepare`, `/mmm-model`, `/mmm-decomposition`, `/mmm-optimize`, `/mmm-scenarios`, `/mmm-report`, `/awareness-forecast`, `/awareness-to-sales`, causal-раздел DiD/SCM/Causal Forest) — не упоминает НИ ОДНУ из 8 активных консультационных команд (`interpret-model`, `why-channel`, `explain-ratio`, `pilot-design`, `next-quarter-plan`, `data-gaps` и т.д. по смыслу консультаций).
2. `src-tauri/tauri.conf.json` (строка 34) бандлит в ресурсы **только** `help-econometrica/*` — общая папка `help-econometrica/` не содержит `econometrist.html` (там `econometrica.html`, `pipeline.html`, `faq.html` и др. product-level страницы). `econometrist.html` физически лежит в `src-tauri/help/` — папке для полной Agency-сборки (13 кабинетов), которая НЕ бандлится в Optimizer MMM.
3. `open_help()` в `src-tauri/src/lib.rs` (строка 1663+): (1) content-pack help, (2) bundled `help-econometrica/` или `help/` в `resource_dir()`, (3) dev-fallback из `CARGO_MANIFEST_DIR/help-econometrica/`. Ни один путь в проде Optimizer MMM не находит `econometrist.html`, т.к. он не входит в бандл этой сборки — подтверждён дефект.

### Решение: Вариант Б

Контент **устарел** (документирует 9 скрытых legacy-команд, не документирует ни одной активной) → переписывать в этом батче нельзя (задача явно запрещает трогать контент справки — отдельная задача). Минимальный безопасный фикс — **скрыть кнопки «Инструкция»/«Справка» для econometrist**, чтобы не показывать битую кнопку.

Правки:
- `src/routes/cabinet/+page.svelte` (~354-361): кнопка «Инструкция» обёрнута в `{#if $activeCabinet.id !== 'econometrist'}`.
- `src/lib/components/FileList.svelte` (~444-453): кнопка «Инструкция» в bottom-actions обёрнута в `{#if $activeCabinet?.id !== 'econometrist'}`.

Обе кнопки вызывают одну и ту же `openHelp()` → `invoke('open_help', { cabinetId })` — других мест вызова не найдено.

**Флаг на будущее: справку `econometrist.html` нужно переписать под 8 активных консультационных команд — отдельная задача (контент справки НЕ входит в батч 3b).**

content-pack (`help-econometrica/`) не менялся в рамках 3.7 — re-sign по этому пункту не требуется (правки только в Svelte-компонентах).

## Гейт

- `npm run check` (svelte-check): см. результат ниже.
- `npm test` (vitest): см. результат ниже.
- lib.rs НЕ менялся в этом батче (только исследован) → cargo test не запускался.
- JSON валидность: `psy-data.json` и `onboarding-data.json` проверены через `python -c "json.load(...)"` — оба валидны (см. вывод выше по ходу правок).

### Результаты

- `npm run check` (svelte-check): **0 ERRORS**, 177 WARNINGS (все pre-existing — unused CSS/a11y в файлах, не связанных с правками этого батча; мои правки не добавили новых warning'ов).
- `npm test` (vitest): **78 test files passed, 1263 tests passed**, 0 failed.
- `src-tauri/src/lib.rs` только исследован (open_help), не изменён → cargo test не запускался (правило гейта: только если тронул lib.rs).
- JSON валидность: `psy-data.json` и `onboarding-data.json` — оба успешно проходят `python -c "json.load(...)"`, структура сохранена.
- Проверка короткого тире: найден и исправлен один em-dash «—» в новом тексте onboarding-data.json (шаг upload) → заменён на «–».
