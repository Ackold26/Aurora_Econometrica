# NEXT SESSION — Econometrica: КОММЕРЧЕСКАЯ ГОТОВНОСТЬ (grill-me → PRD → honesty-аудит/stable/онбординг)

Скопируй этот промт в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`, ветка master.
**origin синхронизирован** (HEAD==origin/master, ahead 0 / behind 0; rc11 выпущен+пересобран+доставлен). Точный HEAD — `git log --oneline -1`.

## Контекст (сделано 2026-06-13)

### rc11 ВЫПУЩЕН клиентам (forecast + NSIS-окна + кофе + палитры)
- Forecast-модуль (CI-веер) + NSIS чёрные окна фикс + тёплые палитры (light беж `#EDEAE3` / fun песок `#E7D8B2`) + кофе-иконка вместо радуги (4 места).
- Опубликовано: GitHub Release **`v2.1.0-rc11`** (публичный `Ackold26/aurora-releases`) + `app_versions` ОБА ключа (`aurora-econometrica-gui`+`econometrica`) + content-pack **v4** в Supabase Storage (`content-packs/econometrica/v4/`, `content_versions.content_pack_version=4`, INV-64) + `latest.json` в rosst-updates. Edge оба ключа = rc11. Supabase project_id `quzhkfvglqmppxcrindh`.

### 7 пост-rc11 фиксов (закоммичены + запушены, НЕ были в первом rc11-бинаре)
1. `8dfc631` **is_newer prerelease** — `updater.rs::is_newer` отбрасывал `-rcN` → rc→rc авто-апдейт НИКОГДА не показывал баннер. Фикс: база+pre_rank раздельно (stable=u32::MAX, числовой хвост rc11>rc10), +9 тестов. **Forward-only** (rc10-клиенты ставят rc11 ВРУЧНУЮ).
2. `8a14cdb` контраст success-бейджей (#4ade80→var(--success)) — «Выбрано»/«рекомендуется»/chip/excluded.
3. `41ea426` развести **«Ratio данных»** (pre-train, obs÷колонки ≈4.4) и **«Эффективный Ratio»** (post-train, obs÷effective_params ≈2.9) по `ratioView.source` + мостик в tip.
4. `e3927b5` оговорка: отключение незначимых праздников НЕ двигает Эффективный Ratio (они вносят ≈0 эфф. параметров — `effective_params=Σ(1−Var_post/Var_prior)`).
5. `1d5941a` бейджи панели «Авто-праздники РФ» (лайм/голубой → var(--success)/var(--color-info)).
6. `3f9ad4e` добить светлый текст: dropdown-selected + mode-toggle (#93c5fd→var(--accent)), счётчики brand/performance/code (→var(--color-info)/var(--success)).
7. `7e1bb27` Cargo.lock rc11.

### rc11 ПЕРЕСОБРАН со всеми 7 фиксами (по команде Антона)
- Новый installer: `D:\cargo-targets\ai-agency\release\bundle\nsis\Aurora AI Econometrica_2.1.0-rc11_x64-setup.exe` — 243.8 MB, собран 19:35.
- **Новый SHA256: `ab4822d8ac9827609ccc6ec49d20d0924d1c22e12b45b35f5bf427f3626dc2c5`** (старый rc11 был `574c3b28…`).
- Версия осталась `2.1.0-rc11` (та же) → авто-баннера на пересборку НЕ будет (та же версия), ставить вручную.
- Sidecar НЕ пересобирался (свежий, band внутри); content-pack v4 НЕ менялся (фиксы были frontend+updater.rs).

## ✅ rc11-rebuild ДОСТАВЛЕН (хвост закрыт в этой сессии)
Пересборка rc11 (`ab4822d8`) полностью доставлена, сервер консистентен:
- GH Release `v2.1.0-rc11` asset = новый бинарь, download_url HTTP 200.
- app_versions ОБА ключа + latest.json (`2b1cb39`) + Edge оба ключа = rc11 + checksum `sha256:ab4822d8ac9827609ccc6ec49d20d0924d1c22e12b45b35f5bf427f3626dc2c5`.
- (История: первый clobber упал на сети с EOF, `--clobber` успел удалить старый asset → был 404; ретрай при восстановленной сети залил новый бинарь и checksum обновлён. Урок: `gh release upload --clobber` удаляет старый asset ДО заливки → провал заливки = пустой релиз/404; на флапающей сети безопаснее заливать новое имя или проверять asset после.)
- NB: версия та же rc11 → авто-баннера на пересборку нет; обновлённые клиенты ставят вручную (`D:\cargo-targets\ai-agency\release\bundle\nsis\Aurora AI Econometrica_2.1.0-rc11_x64-setup.exe`). GH Pages latest.json кэш ≤10 мин (Supabase Edge уже отдаёт новое — это первичный канал апдейтера).

## Файлы для контекста (порядок чтения)
1. Память (feedback этой сессии): `feedback_palette_rollout_reveals_hardcoded_light_text.md` (класс «хардкод светлый текст», грепать по всем компонентам), `feedback_aurora_updater_isnewer_drops_prerelease.md` (is_newer, кросс-продукт INV-кандидат), `project_aurora_coffee_icon_and_color_rollout.md` (Econometrica done, ждут Agency/Legal/Creative/Insights Hub/Creative Hub/Smart Analytica), `feedback_aurora_contentpack_dualsource_runtime.md`, `feedback_fix_at_shared_root_not_leaf_by_leaf.md`.
2. Скиллы: `aurora-fix` (V50 теперь BLOCKER — чёрные окна), `aurora-release-update` (P5 оба ключа, Шаг 6.5 пак).
3. Код: `src-tauri/src/commands/updater.rs::is_newer` (фикс-образец для кросс-продукт), `src/lib/insights-rules.js` (Ratio-инсайты), `src/lib/ratio-classifier.js` + `metric-views.js::ratioView` (source effective/fallback), `src/lib/components/pipeline/HolidayControlsPanel.svelte`.

## НАПРАВЛЕНИЕ СЛЕДУЮЩЕЙ СЕССИИ — коммерческая готовность Econometrica (выбрал Антон 2026-06-13)
rc11 готов и пилотируется; цель — довести до коммерчески готового (продаётся по лицензии). Нумерация пунктов — из readiness-оценки 2026-06-13.

**Старт сессии (строго по порядку):**
1. **Пояснить Антону** пункты ниже из блока «ПОЯСНИТЬ» (технические п7/п8/п11 + бизнес: биллинг/юр/SLA/ценообразование) — это питает дорожную карту.
2. **`grill-me`** — 5-7 вопросов, чтобы ДОПОЛНИТЬ дорожную карту коммерческой доработки. Главный вопрос: «коммерчески готов ДЛЯ КОГО» — якорный фарма-клиент (Кагоцел) vs широкий self-serve (резко меняет приоритеты) + критерии «готов» + объём первого платного релиза.
3. **`write-a-prd`** — оформить результат в PRD / чек-лист коммерческой готовности (критерии приёмки по пунктам).

### СДЕЛАТЬ (в работу после PRD)
- **п2 — Честность движка-оптимизатора (INV-50, аудит #4/#8) [ГЛАВНЫЙ КОММЕРЧЕСКИЙ РИСК].** Ядро ценности = ROI-рекомендации по переброске бюджета; неверный совет хуже отсутствия совета. Probe-стенд на реальном Кагоцеле (БЕЗ GUI) → adversarial-аудит decision-логики оптимизатора (переобучение на тонких данных, mixed units TRP+₽, MCMC-divergences) → честные UI-предупреждения. Отдельная сессия (probe-first + adversarial).
- **п3 — Stable 2.1.0.** Критерии готовности + чистый stable-релиз (без rc) + задокументировать версионную схему `rcN` (tauri/Cargo) vs `APP_VERSION 1.2.0` (content-compat чек, `+layout.svelte:78`). NB: is_newer пофикшен (`8dfc631`) → rc11→stable авто-баннер заработает.
- **п10 — Онбординг/доки для self-serve.** FirstRunTour + `help-econometrica/` есть; проверить покрытие пути «первый запуск → импорт → модель → отчёт» без поддержки, закрыть gaps.

### ОБСУДИТЬ (с Антоном, до реализации)
- **п4 — ПДн / 152-ФЗ / data-flow (INV-38).** MMM-компьют ЛОКАЛЬНО в sidecar (плюс); но кабинеты-советники используют Claude (облако) — определить+задокументировать, какие данные туда уходят + residency (Anthropic/pseudonym tier-1/2 vs YandexGPT-residency tier-3 по INV-38). Для фарма-тендера критично.
- **п5 — Лицензирование → биллинг (техчасть).** Ed25519 + online_auth есть, выдача ручная (`gen_license.py`). Обсудить: нужен ли self-serve provisioning / продление / отзыв / seat-management, или ручная выдача достаточна на этапе якорных клиентов.
- **п6 — Sample-data демо/триал.** `pharma_rx` shipped-broken (3/5 колонок мисроль). Нужен чистый демо-датасет («попробовать без своих данных»). Обсудить: синтетика vs обезличенный реальный, KPI/каналы.

### ПОЯСНИТЬ АНТОНУ (в начале сессии — питает grill-me)
Технические:
- **п7 — Hierarchical-проекты** (что это, ~27 проектов, per_control_contraction на hierarchical-пути ИЛИ явное «badges недоступны»).
- **п8 — Consumption-gap `--cab-accent`** (почему акценты кабинета холодные в light/fun, что значит «подключить consumption» `--cab-color`→`var(--cab-accent, var(--cab-color))`, цена/риск; эталон = Oracle).
- **п11 — MCMC-divergences warning + Tier-3 контроли actionable** (что такое divergences, когда при удалении контролей, что показывать в UI; смысл «Tier-3 контроли actionable»).
Бизнес (подготовить обзор опций/соображений, НЕ решения):
- **Биллинг / процесс продажи** (purchase → provisioning → renewal; варианты).
- **Юр-обвязка** (EULA / оферта / договор — минимум для платной выдачи в РФ).
- **SLA / поддержка** (каналы, время реакции, кто держит).
- **Ценообразование / упаковка** (подписка vs perpetual; per-seat vs per-product; tiers).

### ⚠ НЕ категоризовано Антоном — уточнить в grill-me
- **п1 — Code signing** (Unsigned → SmartScreen «защитила ваш компьютер» + AV-карантин = «выглядит как вирус» для платящего). Это **Tier-1 коммерческий блокер**, но Антон не отнёс его в этот раунд — вероятно «сделать»/часть первого платного релиза, отдельный трек (получить OV/EV-сертификат + подпись .exe в пайплайне).

### Технический бэклог (параллельно/позже, НЕ в коммерческом критическом пути)
- **Кросс-продукт is_newer** — баг во ВСЕХ продуктах (общий updater), пропатчить по образцу `8dfc631` (Oracle/Agency/Legal/Creative/Insights Hub/Smart Analytica/DocMaster) + тест на rcN.
- **Кросс-продукт палитры+кофе+контраст** — параллельная сессия раскатала 6 продуктов на уровне файлов (НЕ задеплоено); грепать класс хардкод-текста (`feedback_palette_rollout_reveals_hardcoded_light_text`); Econometrica consumption-gap = п8.
- Инфра: бандл 969MB (installer 243MB ок); `.bak`/`tmp/` артефакты; RatioInfoCard tooltip + спиннер `ValidateStep:571 #93c5fd` (косметика).

## Инварианты/правила
- **aurora-fix перед сборкой** (V39 sidecar freshness, V49/V50 NSIS — **V50 теперь BLOCKER**: 0 ExecWait, всё nsExec, чёрных окон нет). **aurora-release-update** для публикации (P5 оба ключа, Шаг 6.5 пак).
- **JS+JSDoc** (НЕ TS). Дуальный источник тем/контента: рантайм грузит из УСТАНОВЛЕННОГО пака `%LOCALAPPDATA%\com.aurora.econometrica\content-packs\`, не из рабочей папки (INV-64 / dual-source memory).
- **Тема-токены, не хардкод цвета:** `var(--success)`/`--color-info`/`--accent`; проверять токен во всех 3 темах.
- **INV-50 честность:** отображаемые производные через единый селектор (`mqsView`/`ratioView`).
- Каждый фикс = коммит+тег; push/release по команде; HEAD-дрейф проверять (shared master).

## С чего начать
rc11 ВЫПУЩЕН+ПЕРЕСОБРАН+ДОСТАВЛЕН (хвост закрыт, см. секцию «✅ rc11-rebuild ДОСТАВЛЕН»). Направление — **коммерческая готовность**.
Прочитать этот промт → **(1)** пояснить Антону блок «ПОЯСНИТЬ» (п7/п8/п11 + биллинг/юр/SLA/ценообразование) → **(2)** прогнать **`grill-me`** (дополнить дорожную карту; ключевой вопрос «готов ДЛЯ КОГО») → **(3)** оформить в **`write-a-prd`** (чек-лист коммерческой готовности). Затем «СДЕЛАТЬ» (п2 honesty-аудит — главный риск, п3 stable, п10 онбординг). Технический бэклог (кросс-продукт is_newer/палитры) — параллельно.
