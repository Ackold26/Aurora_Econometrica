# G — Соответствие UI ↔ промпты (кабинет econometrist)

Аудитор G, 2026-07-13. Read-only. Периметр: cabinet.rs ↔ cabinets.json ↔ New_AI_Agency/econometrist/.claude/commands/*.md ↔ command-meta (loader src/lib/command-meta.js + данные content-packs/command-meta-data.json).

## Измерение 1 — четверное совпадение списков — зрелость 4 / эффективность 4

### Как UI реально берёт описания/tooltips (проверено по коду)

- `src/lib/command-meta.js` — НЕ данные, а загрузчик: `_commands = {}` до инициализации (стр. 41), `initCommandMeta(data)` (стр. 54) вызывается один раз из `src/routes/+layout.svelte:163-171`: `invoke('get_content_pack', { packName: 'command-meta-data.json' })` → `initCommandMeta(JSON.parse(...))`.
- Rust `get_content_pack` (`src-tauri/src/lib.rs:1712`): сначала пак из `app_local_data_dir/content-packs/` (`content_pack::load_pack_file`, lib.rs:1719), при отсутствии — fallback на bundled resources инсталлятора (lib.rs:1721-1722). Оба канала несут ОДИН файл `command-meta-data.json`.
- Если оба канала пусты → `catch(() => null)` (+layout.svelte:163) → `initCommandMeta` не вызывается → `getCommandMeta()` возвращает `null` → карточки без описаний/tooltip, `getFileCommands()` пуст (подсветка file-aware отключена). Деградация мягкая, не падение. By-design.
- **Премисса ТЗ «в command-meta-data.json команд econometrist НЕТ» — НЕ подтвердилась** на текущем состоянии репо: `commands` — плоская карта по имени команды (не по кабинету), и все 8 активных команд econometrist там ЕСТЬ (`/interpret-model`, `/why-channel`, `/explain-ratio`, `/pilot-design`, `/next-quarter-plan`, `/data-gaps`, `/awareness-forecast`, `/awareness-to-sales`) с description/category/needsFile. Ключа `commands.econometrist` нет — но его нет ни для одного кабинета: структура плоская. Пустоты нет, дефекта нет.
- Команды грида: `get_commands_dynamic` (cabinet.rs:344-353): cabinets.json из пака → fallback hardcoded `get_commands_for_cabinet` (cabinet.rs:269-278). Двухслойный SSOT — требует ручной синхронизации rust↔json (см. находку ниже — сейчас синхронны).

### Таблица четверного совпадения — 8 активных

| команда | (1) cabinet.rs:269-278 label/group | (2) cabinets.json label/group | (3) файл .md | (4) meta description/needsFile |
|---|---|---|---|---|
| /interpret-model | Объяснить результаты / Смысл | идентично | есть | «Объяснить результаты модели простым языком для руководства» / false |
| /why-channel | Почему у канала такой ROI / Смысл | идентично | есть | «Разобрать ROI и saturation конкретного канала» / false |
| /explain-ratio | Разбор Ratio данных / Смысл | идентично | есть | «Что значит Ratio данных, как его улучшить» / false |
| /pilot-design | План пилота 4–6 недель / Стратегия | идентично | есть | «План пилота 4–6 недель для валидации MMM-рекомендаций» / false |
| /next-quarter-plan | План следующего квартала / Стратегия | идентично | есть | «План медиа-активности на следующий квартал» / false |
| /data-gaps | Чего не хватает в данных / Стратегия | идентично | есть | «Что собрать или улучшить в данных к следующей сборке модели» / false |
| /awareness-forecast | Прогноз awareness / Awareness | идентично | есть | «Прогноз awareness по медиаплану» / true |
| /awareness-to-sales | Awareness → Продажи / Awareness | идентично | есть | «Моделирование связи awareness → продажи» / true |

Расхождений labels/groups между (1) и (2) — ноль (сверено дословно, включая «–» U+2013 и «→»). Все 8 файлов промптов существуют.

### Легенда 9 скрытых (файлы есть, в гриде нет — by-design, комментарий cabinet.rs:262-268)

/mmm-prepare, /mmm-model, /mmm-decomposition, /mmm-optimize, /mmm-scenarios, /mmm-report, /mmm-full, /mmm-to-doc, /mmm-to-slides — все 9 файлов на месте; в cabinet.rs и cabinets.json отсутствуют (корректно скрыты).

**Несимметрия меты легаси:** в command-meta-data.json есть мета для 7 из 9 скрытых (/mmm-full с example «Загрузите xlsx…», /mmm-prepare, /mmm-model, /mmm-decomposition, /mmm-optimize, /mmm-scenarios, /mmm-report — все needsFile:true), но НЕТ для /mmm-to-doc и /mmm-to-slides. Т.к. грид рендерит только команды из cabinets.json, мета скрытых не всплывает в карточках — мёртвые записи. Опасность одна: `getFileCommands()` (command-meta.js:127-131) возвращает needsFile-команды БЕЗ фильтра по кабинету — CommandGrid пересекает со своим списком (CommandGrid.svelte:191), лишние записи безвредны (проверено в изм. 3).

Находки изм. 1:
- [low] content-packs/command-meta-data.json — мета 7 скрытых /mmm-* команд осталась в паке, а /mmm-to-doc и /mmm-to-slides меты не имеют: несогласованный остаток; при ручном вводе скрытой команды 2 из 9 не получат needsFile-подсветку/описание, 7 получат — непредсказуемо для поддержки.
- [info] Двойной SSOT команд (cabinet.rs hardcoded ↔ cabinets.json pack) сейчас синхронен байт-в-байт; расхождение при будущих правках даст разные гриды у клиентов с паком и без. Тест `assert_eq!(get_commands_for_cabinet("econometrist").len(), 8)` (cabinet.rs:431) прикрывает только hardcoded-слой.

## Измерение 2 — overclaim витрины — зрелость 4 / эффективность 4

Сравнение label (cabinet.rs/cabinets.json) + description (command-meta-data.json, рендер CommandCard.svelte:32-35,60-64: description видна на карточке и в tooltip) с телом промпта:

| команда | label/описание vs промпт | вердикт |
|---|---|---|
| /interpret-model | «Объяснить результаты» / «…простым языком для руководства» ↔ промпт: осмысление готовой модели, 5-блочная структура, антисикофантия | совпадает |
| /why-channel | «Почему у канала такой ROI» / «Разобрать ROI и saturation конкретного канала» ↔ промпт: карточка канала, ROI/saturation/adstock, 1 уточняющий вопрос | совпадает |
| /explain-ratio | «Разбор Ratio данных» / «Что значит Ratio…, как его улучшить» ↔ промпт: вердикт, объяснение, влияние, что добавить | совпадает |
| /pilot-design | «План пилота 4–6 недель» / «…для валидации MMM-рекомендаций» ↔ промпт (pilot-design.md:3,26): именно 4–6-недельный пилот: длительность/бюджет 20–30%/гео-сплит/метрики/чек-лист/красные флаги | совпадает точно |
| /next-quarter-plan | «План следующего квартала» / «План медиа-активности на следующий квартал» ↔ промпт: сплит-таблица, таймлайн, точки пересмотра | совпадает |
| /data-gaps | «Чего не хватает в данных» / «Что собрать или улучшить…» ↔ промпт: сводка, пробелы Что/Почему/Где, рекомендация | совпадает |
| /awareness-forecast | label ок; description «Прогноз awareness **по медиаплану**» ↔ промпт (awareness-forecast.md:5): вход = ИСТОРИЧЕСКИЙ трекинг `date`+`awareness_%` + медиазатраты; медиаплан (будущий план) промпт не принимает, прогноз строит «при текущих бюджетах» (стр. 20) | **РАСХОЖДЕНИЕ** — описание задаёт неверное ожидание входа: клиент положит медиаплан без awareness_% → отказ |
| /awareness-to-sales | «Awareness → Продажи» / «Моделирование связи…» ↔ промпт: эластичность, S-кривая, лаг | совпадает |

**Отдельный overclaim runtime-витрины (легаси-театр):** content-packs/psy-data.json `cabinetPhases.econometrist` = «Загружаю данные… Строю байесовскую модель… MCMC-сэмплирование… Проверяю конвергенцию… Рассчитываю ROI и декомпозицию…» — эти статусы показываются клиенту при КАЖДОЙ консультационной команде (ChatPanel.svelte:748-758, getCurrentPhase → psy.js:147-148), хотя консультант ничего не считает (CLAUDE.md кабинета: «Не обучаю модели и не пересчитываю числа движка»; interpret-model.md:3 «Никаких расчётов»). Клиент видит ложный процесс — противоречит самой конструкции «советник поверх pipeline» и дезинформирует о том, где считается модель.

Находки изм. 2:
- [high] content-packs/psy-data.json (cabinetPhases.econometrist) + src/lib/components/ChatPanel.svelte:748-758 — статусы «Строю байесовскую модель…/MCMC-сэмплирование…/Рассчитываю ROI и декомпозицию…» при консультационных командах, которые по контракту НЕ считают — ложный процесс на клиентской витрине.
- [medium] content-packs/command-meta-data.json (/awareness-forecast) — «Прогноз awareness по медиаплану» ≠ вход промпта (исторический трекинг awareness_%, прогноз при текущих бюджетах, awareness-forecast.md:5,20).

## Измерение 3 — needsFile и файловые подсказки — зрелость 4 / эффективность 5

- **Механика UI:** needsFile из command-meta-data.json → (а) блокирующий toast при пустом inbox (cabinet/+page.svelte:88-95 «Загрузите файл во "Входящие"…»), (б) подсветка карточек при наличии файлов (CommandGrid.svelte:43,191 через getFileCommands).
- **6 консультационных** (interpret-model, why-channel, explain-ratio, pilot-design, next-quarter-plan, data-gaps): needsFile:false ✓ — промпты читают НЕ inbox, а блок «=== Данные проекта ===», который фронт инжектит в сообщение (ChatPanel.svelte:697-708) ровно для этих 6 команд (econ-project-context.js:16-23 ECON_DATA_COMMANDS — список 1:1). Доставка через $ARGUMENTS покрыта тестами (lib.rs:3547-3563, регресс-детектор 3584+). Полная согласованность UI ↔ промпт ↔ инжект.
- **2 awareness** (awareness-forecast, awareness-to-sales): needsFile:true ✓ — промпты читают xlsx из inbox (awareness-forecast.md:5, awareness-to-sales.md:5); в ECON_DATA_COMMANDS их нет ✓ (блок пайплайна им не нужен).
- getFileCommands без фильтра по кабинету (command-meta.js:127-131) — включает legacy needsFile-команды, но грид пересекает со своим списком → не всплывают. Побочно: ручной ввод легаси /mmm-* тоже получает toast-блокировку пустого inbox — согласуется с их контрактом (читают inbox).
- **Дыра контракта данных:** next-quarter-plan.md:11 обещает источник «scenarios — сохранённые пользователем сценарии (если есть)», но buildProjectDataBlock (econ-project-context.js:142-161) секцию [scenarios] НЕ строит никогда, и контракт CLAUDE.md кабинета её не содержит. Сценарии пользователя физически не доезжают до советника — мёртвое обещание промпта.

Находки изм. 3:
- [medium] New_AI_Agency/econometrist/.claude/commands/next-quarter-plan.md:11 — источник «scenarios» не существует в инжекте (econ-project-context.js:142-161 без [scenarios]; CLAUDE.md-контракт тоже без него) — промпт ссылается на данные, которые приложение никогда не прикладывает.

## Измерение 4 — скрытые команды в UI-слоях — зрелость 3 / эффективность 3

Проверка всех слоёв на упоминание 9 скрытых legacy-команд:

| Слой | Результат |
|---|---|
| content-packs/cabinets.json | чисто — только 8 активных |
| content-packs/command-meta-data.json | 7 легаси-мет (/mmm-full…/mmm-report) — инертны (грид не рендерит), см. изм. 1 |
| content-packs/classifier-data.json | чисто — только regex-паттерны small talk (9 категорий), команд нет |
| src/lib/chat-classifier.js | чисто — topCommands = top-3 label из активного грида (ChatPanel.svelte:414-427) |
| **content-packs/onboarding-data.json** | **ГРЯЗНО**: configs.econometrist — focusCommand «/mmm-model» (шаг train), nextActions [/mmm-decomposition, /mmm-optimize, /mmm-report] (шаг analyze), noviceCommands = все 9 легаси; активных 8 команд в онбординге НЕТ вообще |
| src/lib/program-help.js | чисто — карта программы без слэш-команд, только пайплайн/пороги |
| content-packs/psy-data.json | команд нет, но cabinetPhases — легаси-расчётный театр (см. изм. 2); nextSteps.econometrist предлагает кабинеты не из продукта (communication-strategist, media-analyst), НО чипы отключены `{#if false}` (ChatPanel.svelte:1160-1162) |
| CommandPalette.svelte (Ctrl+K) | чисто — команды из get_cabinet_commands (8 активных), HELP_PAGES все существуют в help-econometrica/ |
| src-tauri/help/econometrist.html:130-154, help/user-guide.html:1995-2002 | легаси-справка документирует 9 скрытых как ОСНОВНОЙ workflow («нажмите /mmm-prepare»…), группы «Основные/Анализ/Отчёты» ≠ гриду; в ЭТОЙ сборке НЕ бандлится (tauri.conf.json:34 — только help-econometrica/*) → residue |
| ChatPanel AUTO_CONTINUE_COMMANDS:96-105 | содержит 7 легаси — внутренний список, клиенту не виден, поведенчески безвреден |

**Почему onboarding-грязь сегодня не всплывает (двойная случайность, не защита):** (а) render-ветки CabinetOnboarding.svelte:63-113 матчат id 'upload'/'analyze'/'result', а у econometrist шаги 'import'/'train'/'analyze' → focusCommand «/mmm-model» (в шаге 'train') и nextActions (в шаге 'analyze', а рендер только в 'result') НЕ отображаются; (б) noviceCommands вычисляется (cabinet/+page.svelte:149-157), но НЕ передаётся в CommandGrid (строка 417 без visibleCommands) — мёртвый код. Цена: свежий пользователь Optimizer видит онбординг с ПУСТЫМИ шагами 1-2 (только точки прогресса и «Далее») и без кнопки «Готово» на последнем шаге (complete-btn только в ветке 'result') — выйти можно только «Пропустить». Любая правка (подключение visibleCommands / приведение id) вскрывает 9 скрытых команд в онбординге: noviceCommands отфильтрует грид до 2 карточек из 8.

**Справка кабинета мертва в проде:** кнопки «Инструкция» (cabinet/+page.svelte:354) и «Открыть справку» (FileList.svelte:445) зовут open_help('econometrist') → lib.rs:1641-1679 ищет econometrist.html в content-pack → help-econometrica/ (файла НЕТ — листинг проверен) → help/ (не бандлится) → dev-путь → в проде Err, UI глотает ошибку в console.error без toast — клиент жмёт кнопку, ничего не происходит.

Находки изм. 4:
- [medium] content-packs/onboarding-data.json (configs.econometrist) — онбординг живёт в легаси-эпохе: focusCommand/nextActions/noviceCommands ссылаются ТОЛЬКО на скрытые команды, 8 активных отсутствуют.
- [medium] src/lib/components/CabinetOnboarding.svelte:63-113 ↔ onboarding-data step ids — шаги 'import'/'train' рендерятся пустыми, «Готово» недостижимо (только «Пропустить») — сломанный первый экран единственного кабинета.
- [medium] src-tauri/src/lib.rs:1641-1679 + tauri.conf.json:34 — open_help('econometrist') в проде не находит файл (help-econometrica/econometrist.html нет) → кнопки справки кабинета молча мертвы (cabinet/+page.svelte:354, FileList.svelte:445).
- [low] src-tauri/help/econometrist.html:130-154 + help/user-guide.html:1995-2002 — легаси-справка с 9 скрытыми командами как основным workflow; не бандлится в Optimizer, но остаётся в репо (риск других вариантов/будущего бандла).
- [low] src/routes/cabinet/+page.svelte:149-157 — noviceCommands вычисляется, но не подключён к CommandGrid; при подключении легаси-список сократит грид econometrist до 2 команд из 8.
- [info-crossref] explain-ratio.md:24 «Ratio ≥ 4 — норма, cap снят» ↔ CLAUDE.md кабинета «MQS-кэп: ≥ 6 — cap снят, 2–4 — cap 70» — зона 4–6 противоречива (передаю аудитору промпт-контента).

## Итог G

| Измерение | Оценка |
|---|---|
| 1. Четверное совпадение списков | 4 |
| 2. Overclaim витрины | 4 |
| 3. needsFile / файловые подсказки | 4 |
| 4. Скрытые команды в UI-слоях | 3 |

Среднее 3.75. Ядро (грид ↔ промпты ↔ мета ↔ инжект данных) выровнено образцово для 8 активных команд; главный риск — UI-слои второй линии (onboarding, психо-статусы, справка кабинета), застрявшие в легаси-эпохе расчётного эконометриста: клиент видит ложные фазы «MCMC-сэмплирование», пустой онбординг и мёртвую кнопку справки.
