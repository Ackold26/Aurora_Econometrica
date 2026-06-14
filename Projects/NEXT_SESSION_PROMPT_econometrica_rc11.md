# NEXT SESSION — Econometrica: финализация rc11-rebuild + карта (stable 2.1.0, кросс-продукт is_newer)

Скопируй этот промт в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`, ветка master.
HEAD = `7e1bb27`, **origin синхронизирован** (ahead 0 / behind 0).

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

## Задачи продолжения (приоритет)
1. **[ПЕРВЫЙ] Финализировать rc11-rebuild** — дождаться clobber-upload, обновить checksum (оба app_versions + latest.json) на `ab4822d8…`, verify (см. хвост выше).
2. **Кросс-продукт is_newer** — баг `is_newer` (отбрасывает `-rcN`) почти наверняка во ВСЕХ Aurora-продуктах (общий updater). Пропатчить Oracle/Agency/Legal/Creative/Insights Hub/Smart Analytica/DocMaster по образцу `updater.rs::is_newer` (Econometrica `8dfc631`) + регрешн-тест на rcN.
3. **Кросс-продукт палитры+кофе+контраст** — раскатать тёплые палитры + кофе-иконку на остальные продукты (`project_aurora_coffee_icon_and_color_rollout` — параллельная сессия уже раскатала 6 продуктов на уровне рабочих файлов, НЕ задеплоено), И при этом грепнуть класс «хардкод светлый текст» (`feedback_palette_rollout_reveals_hardcoded_light_text`) — он будет в каждом.
   - **Econometrica consumption-gap (follow-up):** у Econometrica палитра-фон есть, но `--cab-accent` НЕ подключён (themes.json без токена; 0 обёрток `var(--cab-accent, …)` в CommandCard/NavRail) → акценты кабинета в light/fun остаются ХОЛОДНЫМИ. Дораскатать consumption по образцу Oracle (`--cab-color`→`var(--cab-accent, var(--cab-color))`), но ОСТОРОЖНО (только что вышел rc11) — отдельным релизом. Эталон палитр = Oracle (`06_Aurora_Design_system/07_Theme_Lab/rollout_themes.py`, WCAG-гейт).
4. **rc→stable 2.1.0** — критерии готовности; code signing (Unsigned → SmartScreen-трения). NB: rc11→stable-2.1.0 авто-баннер сработает даже со старым is_newer (`[2,1,0]>[2,1]`); rc11→rc12 — нет (нужен фикс на клиенте, он forward-only).
5. **Опционально (Ratio):** RatioInfoCard tooltip (`«K переменных в модели»`) уточнить «параметры после обучения / признаки до». Спиннер `ValidateStep:571 border-top #93c5fd` (не подпись, низкий приоритет).
6. **Инфра:** бандл 969MB→243MB (collect-all build_sidecar); `.bak`/`tmp/` артефакты в рабочем дереве можно удалить.

## Инварианты/правила
- **aurora-fix перед сборкой** (V39 sidecar freshness, V49/V50 NSIS — **V50 теперь BLOCKER**: 0 ExecWait, всё nsExec, чёрных окон нет). **aurora-release-update** для публикации (P5 оба ключа, Шаг 6.5 пак).
- **JS+JSDoc** (НЕ TS). Дуальный источник тем/контента: рантайм грузит из УСТАНОВЛЕННОГО пака `%LOCALAPPDATA%\com.aurora.econometrica\content-packs\`, не из рабочей папки (INV-64 / dual-source memory).
- **Тема-токены, не хардкод цвета:** `var(--success)`/`--color-info`/`--accent`; проверять токен во всех 3 темах.
- **INV-50 честность:** отображаемые производные через единый селектор (`mqsView`/`ratioView`).
- Каждый фикс = коммит+тег; push/release по команде; HEAD-дрейф проверять (shared master).

## С чего начать
Прочитать этот промт + `feedback_aurora_updater_isnewer_drops_prerelease` → **проверить, завершилась ли clobber-загрузка (`gh release view v2.1.0-rc11`), и если да — закрыть checksum (Задача 1).** Затем уточнить у Антона: кросс-продукт is_newer/палитры (Задача 2-3) или rc→stable (Задача 4)?
