# Econometrica — роутер следующей сессии (после сессии 2026-07-19 вечер: #6 глоссарий + CPD-15 + сборка/аудит)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_v230`
> (worktree ветки `feat/econ-v2.3.0` = прод-линия 2.4.0). Бэклог → память `project_econometrica_backlog`.

## ✅ Сделано в этой сессии (ЗАПУШЕНО origin/feat/econ-v2.3.0 + aurora-meta, НЕ переделывать)
6 коммитов econ (`6e2e60c..e9eacc9`):
- **#6 SSOT глоссарий ЗАКРЫТ:** `9144488` реконсиляция источника (`docs/GLOSSARY_v2_1_0.md` + `LEGACY_ONLY` в `build_glossary.py`: INV-50, термин OVB, текст 10 терминов, тире + нормализация `_norm_dash` в генераторе, MMM «6→7 шагов») · `eb440c6` CI-линтер синхронности `tools/check_glossary_sync.py` (temp-перегенерация + сверка autocrlf-устойчиво + гейт 0×U+2014 в выходах → `ci.yml` + `lefthook.yml`). Канон: **INV-97** в aurora-meta (`f3abae4`).
- **CPD-15 (изоляция кабинетного claude CLI) ЗАКРЫТ:** `244fccd` helper `isolated_claude_config_dir` вербатим-эталон SA 1.3.10 + `env_remove(CLAUDE_CONFIG_DIR)` + `cmd.env` перед spawn (`claude.rs`). Живой аудит в собранном .exe 2.4.0: scope-отказ + инъекция «ВЗЛОМАНО/license.json»→данные — **оба PASS, приёмка Антона**. Реестр CPD-15 EC ✅ (`a9bd90d` aurora-meta). INV-92 уже корректен (SA закрыл).
- **Мелочи:** `c69b4b2` program-help.js 11×U+2014→«–» · `5d89ce6` линтер INV-50 в help-HTML (`check_help_pdf_consistency.py`).
- **#8 orphans удалены:** `e9eacc9` (`src/lib/help-econometrica/` analysis-mode + signed-factors — сироты 0 ссылок, темы покрыты актуальной справкой).
- **Сборка .exe 2.4.0 для аудита (БЕЗ публикации — решение Антона):** `Optimizer MMM_2.4.0_x64-setup.exe` 246.5МБ, SHA256 `65d9ce62ea1028f74a4d245ada04c02e8ed61b2babfcd0dfc5f26fcdbf06e101`, в `D:\cargo-targets\ai-agency\release\bundle\nsis\`. sidecar переиспользован (Python MMM не менялся).
- Аудит diff блока: `Projects/handoff.md` (этот блок) + findings/триаж в итоге wrap-up.

## 📋 Задачи продолжения (приоритет — определить с Антоном)
1. **ВЫКАТ 2.4.x клиентам** (если Антон санкционирует — необратимо): справка+PDF (прошлая сессия) + глоссарий (#6) + CPD-15 едут ОДНОЙ пересборкой. Аудит-сборка 2.4.0 уже есть. Для публикации: `aurora-fix` полный pre-build (content-pack/vault/**version bump — см. п.2**) → build_sidecar? (нет, sidecar не менялся — переиспользовать) → `npm run tauri build` → смоук → `aurora-release-update` (GH `aurora-releases` fat >50MB + app_versions ×2 `aurora-econometrica-gui`+`econometrica` + latest.json). content-pack re-sign НЕ нужен (справка/PDF/глоссарий не в паке).
2. **🔴 Баг установщика «unableToUninstall»** (диагностирован, НЕ исправлен): при установке 2.4.0 поверх 2.4.0 (same-version) режим «удалить предыдущую» падал (`installer.nsi:355`); реестр Optimizer чист, приложение НЕ было запущено, причина НЕ подтверждена. **При bump-релизе (2.4.1, НЕ same-version) проверить воспроизведение**; если да — снять NSIS-лог `"...setup.exe" /L=log.txt`. Bump версии сам по себе снимает same-version краевой случай. НЕ править NSIS-хук вслепую (проверено: хуки корректны, `installer_hooks.nsh` не менялся).
3. **#9 блок «Какой режим выбрать»** в актуальную справку: компактный decision-guide ROI/Эффективность/Смешанный единым блоком в `src-tauri/help-econometrica/` (pipeline.html или data-preparation.html), navy-стандарт 2.4.0. Идею взять из git-истории удалённого `analysis-mode.html` (до `e9eacc9`) — НЕ воскрешать orphan, свежий раздел.
4. **Тестовые компы PC443/PC583** — баннер 2.4.0 (ждёт решения Антона: мягко/форс min_version).
5. Прочий бэклог → [[project_econometrica_backlog]] (пилот прогноз→факт · юр · code-signing · Аврора Tier2+RAG · петля доверия E1→E4).

## 🌐 Тонкий клиент — ОТДЕЛЬНЫЙ проект (не этот роутер)
Зонд этой сессии: движок `nodeB_engine_async.py` УЖЕ диалоговый (не one-shot), узел Б в бою. Точка входа реализации — `D:\Docs\Aurora_Ai\thin-client\NEXT_SESSION_phase2_carryover.md`, память [[project_thin_clients_2026_07_01]] (🆕 UPDATE 2026-07-19). Остаток: дожать Tauri-клиент `thin-client/app/` + узел А (РФ/ПДн, host-серт ждёт passphrase Антона).

## Инварианты/правила
- Shared-репо: зонд `git rev-parse --abbrev-ref HEAD` + fetch/behind ДО работы; коммит своим pathspec; чужие незакоммиченные в дереве (`Projects/audit.diff`, `audit_findings_live.md`, `Cargo.toml`, `audit_kpiunits.diff`, `audit_session.diff`) — НЕ трогать.
- Глоссарий SSOT: правки ТОЛЬКО в источник (`docs/GLOSSARY_v2_1_0.md` / `LEGACY_ONLY`) + перегенерация `build_glossary.py`; выходы `glossary.json/html/js` — производные (CI-линтер `check_glossary_sync.py` стережёт). INV-97.
- INV-50: клиентский текст «правдоподобный диапазон»; тире «–» (U+2013), не «—». CPD-15: safe-mode НЕ применять; helper вербатим.
- Линтеры справки в CI/lefthook — держать зелёными; новый линтер — «внести-поймать-откатить».

## С чего начать
1. Прочитать `INDEX_econometrica` 📍 (свежая 🆕 сессия сверху) + `project_econometrica_backlog`.
2. Зонд ветки (`git rev-parse --abbrev-ref HEAD` + fetch/behind=0?) + `git log --oneline -8` (6 коммитов сессии на месте).
3. Согласовать с Антоном приоритет: ВЫКАТ 2.4.x (при санкции) vs #9 vs тестовые компы.

## 🔴 Руководство по стилю действий (прочитать ПЕРВЫМ — уроки этой сессии)
1. **Зонд > память, всегда.** Память 16 дней назвала движок thin-client «one-shot» — зонд кода опроверг (диалоговый). Память назвала долг MANUFACTURER-mismatch — оказался ЧУЖОЙ installer.nsi. Первый ход любого блока — 10-сек зонд решающего артефакта НА ОПРОВЕРЖЕНИЕ, не конструкция.
2. **Реконсиляция SSOT: сверяй КАЖДЫЙ выход с прежним, не sample по одному.** Регресс MMM «6→7 шагов» жил ТОЛЬКО в `glossary.html`; сверка перегенерации против `glossary.js` (0 расхождений) его не увидела — поймала личная проверка `git diff` ВСЕХ выходов. Диагностику дрейфа веди безопасным прогоном генератора в песочницу (подмена OUT_* путей), не мутируя рабочее дерево.
3. **Общий `CARGO_TARGET_DIR` — `installer.nsi`/`release/*.exe` НЕ персистентны per-product.** Последняя сборка ЛЮБОГО продукта перезаписывает их. Диагностируя installer.nsi — ПЕРВЫМ делом сверь `!define PRODUCTNAME`/mtime с целевым продуктом. Надёжны: итоговый `*-setup.exe` (per-product по имени) + реестр машины. [[feedback_shared_cargo_target_artifacts_not_per_product]].
4. **Не фабрикуй причину и не чини вслепую.** Баг установщика: несколько технических гипотез опровергнуты фактами (реестр чист, publisher совпадает, ключ не пуст) — честный тупик лучше выдуманного диагноза. Предложенная правка хука (kill node.exe) оказалась опасной (снесёт чужие node) + бесполезной (claude CLI не держит файлы установки) — red-team своей же идеи ДО реализации.
5. **Приёмка субагентов — метрику/находку верифицируй ЛИЧНО** (~40% FP), но диагностику/сборку/аудит выноси в durable-субагентов (щадит контекст). Живой аудит security-фикса в СОБРАННОМ .exe (не dev — там нет MCP-моста в release), тестируй САМ барьер (scope+инъекция), не «как меня зовут».
6. **Собранный релиз .exe: sidecar переиспользуй, если Python не менялся** — только `npm run tauri build` (Rust+фронт+бандлинг готового sidecar), не `build_sidecar.py`. Токены `aurora_tokens.py` в worktree уже сгенерированы (дизайн-систему не трогали) → worktree-грабля не срабатывает.
