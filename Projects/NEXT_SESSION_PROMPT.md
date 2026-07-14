# Econometrica — роутер следующей сессии (2.3.1: аудит+сборка ГОТОВЫ, осталась ПУБЛИКАЦИЯ)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_v230`
> (worktree релизной ветки `feat/econ-v2.3.0`). Обновлён 2026-07-14 (wrap-up после сборки installer 2.3.1).

## Контекст — что сделано (НЕ переделывать)

**Адверсариальный аудит перед сборкой + count-KPI фикс + installer 2.3.1 СОБРАН и СМОУКНУТ.**
Коммиты на `feat/econ-v2.3.0`: `dc01a9c` (count-фикс + bump) + `1255db4` (revert productName).
HEAD = `1255db4`. Дерево чистое, всё локально (НЕ запушено — push в следующей сессии перед мержем).

**Что закрыто этой сессией:**
1. **CI PR #3 зелёный** (Test&Lint + Python Tests + Help Sync на `e63176b`/`c637c06`/`aa32040`).
2. **Живой прогон D1** (dev-мост): 4 проводки доказаны (страж INV-50 ловит выдуманное число ·
   доставка Батч 0 = send_heartbeat→content_version · next-quarter в 8 командах · PIPELINE_STEPS[6]=report,
   completeStep(6)). Онбординг чистый, Отчёт рендерится. Смоук установленного .exe — Антон подтвердил
   «установилась, запустилась, без ошибок».
3. **Адверсариальный аудит (2 независимых аудитора + верификация):** внешний аудит e270353..HEAD (0 находок,
   2 реальных багфикса y_actual/resolver подтверждены) · release-consistency (2 HIGH: нейминг+грязное дерево) ·
   hidden-defects (**1 HIGH: занижение вклада count-KPI в 1e6, 6 мест одного корня, INV-50**).
4. **HIGH count-KPI УСТРАНЁН** (`dc01a9c`): честный форматтер `_contrib_scale`/`_fmt_contrib` (адаптивный
   масштаб млн/тыс/полное + единица из паспорта) в 6 местах (HTML таблица/итог/drill/график, PPTX таблица/итог,
   JS-инсайт). Анти-регресс тест на ЗНАЧЕНИЕ + паритет HTML↔PPTX (поймал mirror-drift разделителя). 27/27 тестов.
5. **HIGH нейминг → решение Антона: productName ОСТАВЛЕН «Optimizer MMM»** (V52 upgrade-continuity — 2.1.0
   выдана клиентам с этим именем; смена ломала бы обновление). Заголовок окна/firewall — «Aurora AI Econometrica».
6. **LOW почищены:** tooltip «Вклад» KPI-нейтрально · U+2014 в комментариях installer → «–».
7. **Гейты все зелёные:** svelte-check 0 · vitest 1279 · cargo 191 · sidecar pytest 694 · V29 sidecar collect ✅.
8. **installer 2.3.1 СОБРАН:** `Optimizer MMM_2.3.1_x64-setup.exe` = **244.7 MiB**, SHA256
   `6299e82e597b52e4e94591ae5ea72db20d987c0969233a2d429d8764e6d77315`, путь
   `D:\cargo-targets\ai-agency\release\bundle\nsis\`. Sidecar 970MB (freshness ✅ count-фиксы внутри).
9. **VAULT собран локально:** `econometrist.vault` (plain gzip-tar, 33.7KB, 19 файлов) в scratchpad — греп
   next-quarter строки прошёл. НЕ загружен на прод.

**⚠️ Грабля сборки (записана в память):** worktree v230 не содержал generated-токены (`aurora_tokens.py` +
`aurora_html/templates/*.css/js`) — gitignored, остались в родителе `Aurora_Econometrica/`. Первая сборка
sidecar FAILED. Скопировала из родителя → пересборка ОК. [[feedback_worktree_missing_generated_tokens_sidecar_build]]

## Файлы для контекста (порядок чтения)
1. Этот файл + `Projects/handoff.md` (детали count-фикса + зоны неуверенности).
2. `Projects/audit_findings_live.md` + отчёт аудитора wrap-up (если завершился — проверить триаж).
3. Память: [[INDEX_econometrica]] · [[feedback_worktree_missing_generated_tokens_sidecar_build]] ·
   [[feedback_count_kpi_unit_scale_together]] (если создан).
4. Регламенты: `aurora-release-update` скилл (публикация) + `aurora-fix` скилл (V52/P8/P9).

## Задачи продолжения (приоритет)

### 0. 🔴🔴 ПЕРЕСОБРАТЬ installer (drill-fix после сборки) — ПЕРЕД публикацией
⚠️ Installer `Optimizer MMM_2.3.1_x64-setup.exe` (244.7 MiB) собран ДО fix-коммита drill-масштаба
(HIGH из wrap-up аудита). Sidecar в текущем .exe НЕ содержит drill-fix. **Пересобрать перед публикацией:**
скопировать generated-токены из родителя (см. грабля выше) → `python build_sidecar.py` → `npm run tauri build`
→ НОВЫЙ SHA256 (старый `6299e82e...` устарел). Смоук заново (или доверять — fix локализован в drill CHART_DATA).

### 1. 🔴 ПУБЛИКАЦИЯ 2.3.1 (ВМЕСТЕ с Антоном, НЕОБРАТИМО) — главная задача
Installer пересобрать (шаг 0!) → публикация по `aurora-release-update` (Econometrica = fat-client, GH Releases):
- **P3/5b:** залить `.exe` на **GitHub Releases `Ackold26/aurora-releases`** (>50MB → не Storage). `cp` в /tmp
  с точным именем, `gh release create`, потом `gh release view --json assets` + `curl -sI` 200.
- **P5:** `app_versions` UPDATE (product `aurora-econometrica-gui`): version=2.3.1 + download_url(GH) +
  checksum `sha256:6299e82e597b52e4e94591ae5ea72db20d987c0969233a2d429d8764e6d77315` + release_notes. 4 поля вместе.
- **P4:** `rosst-updates/aurora-econometrica-gui/latest.json` — та же версия/url/checksum (оба канала одним батчем).
- **P8 VAULT:** залить `econometrist.vault` в Storage `vaults/econometrica/c2/econometrist.vault` (plain tar.gz,
  из scratchpad или пересобрать `tar czf econometrist.vault -C New_AI_Agency/econometrist .`) + SHA-256 +
  content_versions: INSERT c2 is_current=true (checksums {econometrist.vault: sha}) + прежний c1 is_current=false.
  Текущий серверный content_version = **c1**. B2 «серверная vault_versions отложена» — глобальный content_version путь.
- **P9 smoke:** после публикации — fresh install (снести %APPDATA%\com.aurora.econometrica) → auth → открыть
  кабинет econometrist (vault докачается) → нет VT-*.
- **P2/9b verify:** Edge `app-update {product:"aurora-econometrica-gui"}` = 2.3.1 + fallback latest.json совпадает.
- ⚠️ Supabase MCP в этой сессии был **Unauthorized** — публиковать через `aurora-secrets.env` + curl/PowerShell
  (SUPABASE_SERVICE_ROLE_KEY), НЕ через MCP. Сеть github → `dangerouslyDisableSandbox: true`.
- Без code-signing (сертификата нет → SmartScreen предупредит, пометка в release notes).

### 2. Тег + мерж (после публикации)
`git push origin feat/econ-v2.3.0` → тег `v2.3.1` → мерж PR #3 в master (master `7fbfd96` +247 позади).

### 3. Демо-данные (замечание Антона 2026-07-14) — очевидный прирост при оптимизации
Демо-фикстура «демо_медиаплан_с_хвостом» даёт ПРИРОСТ ОТ ОПТИМИЗАЦИИ **+0.0%** (R² 0.396, слабые данные) —
нулевой прирост подрывает доверие к продукту. Пересобрать демо-данные так, чтобы прогон через оптимизацию
давал заметный, очевидно-положительный прирост (демонстрация реальной эффективности). Пост-релизная.

### 4. Отложенное (эскалация/после выката)
- G9 geo-иерархия (продуктовое, эскалация) · G7 SBC (движковое) · справка econometrist (8 команд+бандл, к сборке) ·
  2d frontend BUNDLED_FRONTEND_VERSION (build-time) · 2c серверная vault_versions.
- Триаж находок wrap-up аудита (если аудитор что-то нашёл — см. audit_findings_live.md).

## Инварианты/правила
- INV-50 честность метрик (count-KPI: единица ↔ масштаб ВМЕСТЕ; `insights-grounding.js` НЕ трогать).
- JS+JSDoc не TS. Клиентский текст: короткое тире «–», без англицизмов, без slash-команд.
- Релиз по СВОЕМУ каналу; vault=plain gzip-tar (НЕ vault-packer AES); Econometrica hosting=GH Releases.
- productName «Optimizer MMM» — НЕ менять (upgrade-контракт клиентов 2.1.0).
- Shared-репо: зонд HEAD/origin ДО коммита/push; узкий pathspec. Сеть → `dangerouslyDisableSandbox`.

## 🔴 Руководство по стилю действий (прочитать ПЕРВЫМ)
1. **Публикацию через `aurora-secrets.env` + curl/PowerShell, НЕ Supabase MCP** — MCP в этой сессии вернул
   Unauthorized (нет access token). Секреты: `C:\Users\ackol\.claude\aurora-secrets.env`.
2. **Сборка из worktree: сначала проверить generated-артефакты.** Grep `aurora_tokens.py`/`*.generated.*` — нет
   генератора (`Standards/tokens/build.py`) в worktree → скопировать готовые из родителя (`git worktree list`).
   НЕ гонять build_sidecar вслепую (первая сборка этой сессии FAILED на отсутствии aurora_tokens.py).
3. **Фоновая команда: exit 0 от `| tail` МАСКИРУЕТ провал.** build_sidecar FAILED, но фон вернул exit 0 (от tail).
   Читать реальный итог в output-файле («Build SUCCESS/FAILED»), не доверять exit-коду фоновой pipe.
4. **Аудит перед сборкой окупился — HIGH дефект (count-KPI) прошёл 3 прошлых аудита** (тест проверял ШАПКУ, не
   ЗНАЧЕНИЕ ячейки — «тест проверяет что заявил агент»). Перед выкатом гонять адверсариальный аудит + верифицировать
   находки лично. Новый тест ДОЛЖЕН проверять значение/поведение, не только присутствие метки.
5. **Смоук установленного .exe — БЕЗ моста** (`#[cfg(debug_assertions)]` — только dev). Программная проверка на
   проде — через ВЫХОДНОЙ артефакт (греп HTML/PPTX отчёта на честный масштаб), не webview. Визуальное — Антон.
6. **Публикация — ВМЕСТЕ, необратимо.** Не заливать на прод в одиночку. Сверить checksum во ВСЕХ читателях
   (app_versions + latest.json) синхронно с заливкой .exe (иначе verify_checksum у клиента падает).
