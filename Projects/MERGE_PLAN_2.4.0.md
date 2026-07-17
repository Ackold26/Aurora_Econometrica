# MERGE_PLAN 2.4.0 — объединение линий v2.3.0 + kpi-units (durable-якорь)

> Санкция Антона 2026-07-18: пуш веток ✅ · версия **2.4.0** ✅ · старт исполнения ✅.
> Публикация (шаг 10) — ОТДЕЛЬНАЯ санкция по предъявленным результатам.
> При обрыве сессии: продолжать отсюда, сверив чекбоксы. Ничего не переделывать.
> Оркестратор — Маша (main), механика — durable-субагенты sonnet, содержательные
> конфликты и гейты — личная верификация Маши.

## Проверенные факты (не перепроверять, зонды 2026-07-18)

- Общий git: `Dev/Aurora_Econometrica/.git`; worktree v230 = `Dev/Aurora_Econometrica_v230`.
- `master` = застывшая точка `7fbfd96`, 0 уникальных коммитов; НЕ прод.
- Прод-линия = `feat/econ-v2.3.0` (тег `v2.3.1` = `34b9aa2`); на ветке 14 коммитов ПОСЛЕ тега.
- Расхождение веток от `fecdb84`: v2.3.0 +88 уникальных, kpi-units +8.
- Из 8 kpi-units: `479ef2c`+`821420f` патч-эквивалентны v230 (git cherry «-»);
  реально уникальны: `85df196` (P-2 PPTX), `8e0f8cc` (дизайн Планирования),
  `d9c74a0` (стиль-ядро промптов), `cc42940` (хвосты P-3/svelte/jsdom), `553c0e3` (docs),
  `47c57f0` (порт maximized/no-window — содержимое в v230 есть, patch-id разный из-за контекста).
- **P-1 и прогноз-раздел (af12181) В ОПУБЛИКОВАННОМ теге v2.3.1** ⇒ P-2-баг (ложные нули
  в прогноз-разделе PPTX) СЕЙЧАС У КЛИЕНТОВ — релиз 2.4.0 = прод-фикс INV-50, срочный.
- Манифесты версий kpi-units после fecdb84 НЕ менялись ⇒ конфликта версий при merge нет.
- Ожидаемые содержательные конфликты (обе стороны меняли после fecdb84, 13 файлов-кандидатов;
  реально содержательные ~2-4): `sidecar/econometrica/aurora_pptx/builder.py`,
  `aurora_html/sections.py` (P-2 vs правки отчётов 2.3.1), `New_AI_Agency/econometrist/CLAUDE.md`
  (стиль-ядро vs Батч-5 аудит промптов), возможно `src/lib/{insights-rules,kpi-aware-formatting,kpi/kpi-display}.js`.

## Шаги (чекбоксы вести по факту)

- [ ] **0a.** Пуш `feat/econ-kpi-units` (с `-u`, upstream нет) + `feat/econ-v2.3.0` (ahead) на origin.
      Сеть флачит (TLS 10054/curl 35) → retry ×3-5; после обрыва — проверка `git status -sb`.
- [ ] **0b.** Этот план закоммичен в v230 (docs, свой pathspec).
- [ ] **1.** Песочница: `git worktree add -b feat/econ-2.4.0 D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_merge feat/econ-v2.3.0`
      (третье дерево; существующие НЕ трогать — в обоих чужие незакоммиченные файлы).
- [ ] **2.** В песочнице: `git merge feat/econ-kpi-units` (база fecdb84 3-way).
      Правила разрешения: обе ценности сохраняются; версии — сторона v230 (2.3.1, bump позже);
      идентичные правки (maximized/no-window/смоук) — авторазрешение или любая сторона (идентичны);
      builder.py/sections.py — P-2-маппер (реальная схема totals.*, None→«—», интервал суммы,
      TOC-подстрока) ОБЯЗАН выжить ВМЕСТЕ с правками отчётов 2.3.1; CLAUDE.md econometrist —
      стиль-ядро канон + Батч-5 линтер-правки вместе, сверка с `_shared/` каноном;
      содержательные конфликты решает Маша ЛИЧНО, не субагент.
- [ ] **3.** Vault-развилка: вошло ли стиль-ядро (d9c74a0) в опубликованный vault c2?
      (распаковать/сравнить CLAUDE.md кабинета). НЕТ → vault c3 в объём релиза по регламенту
      (lint_prompt_commands 0 FAIL → cabinet_eval --dry → sign_content_pack --bump →
      check_content_pack_sync OK). ДА → конфликт в пользу раскатанного текста.
- [ ] **4.** Гейты на песочнице (node_modules: npm ci; python — окружением v230):
      pytest `-m "not requires_real_data"` · vitest · svelte-check 0 · cargo test ·
      `npm run build` (прод-сборка!) · линтеры промптов/контента/help-consistency.
- [ ] **5.** Аудит: handoff по диффу `v2.3.1..HEAD(песочницы)` → 2 независимых аудитора
      (фронт + python, subagent sonnet/opus) с явным заданием: сверить КАЖДОЕ разрешение
      конфликта против обеих родительских версий → триаж → фикс-коммит.
- [ ] **6.** CI начисто: пуш `feat/econ-2.4.0` → PR draft → Test&Lint зелёные.
- [ ] **7.** ff-слияние песочницы → `feat/econ-v2.3.0` + bump **2.4.0**
      (Cargo.toml, tauri.conf.json, package.json; tauri.local.conf.json — version там НЕТ,
      наследуется; сверить по факту + Cargo.lock/package-lock).
- [ ] **8.** Сборка в v230-дереве: `python build_sidecar.py` (смоук INV-96 + freshness) →
      `CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri build` → живой смоук
      установленного exe: сквозной сценарий Планирования до PPTX.
- [ ] **9.** Гейт «ничего не потерять» (методы, не «собралось»):
      P-2 — python-pptx-инспекция слайда прогноза (числа ≠ нули, интервал суммы);
      дизайн — DOM-замер full-width Планирования == соседям; стиль-ядро — grep канона в
      CLAUDE.md кабинета (+vault если c3); P-3 — grep «выше на этом шаге»; svelte-check 0;
      полнота — `git log feat/econ-kpi-units ^HEAD` ПУСТ (валиден при merge) +
      выборочно 5 прод-фич 2.3.1 (vault-механика, security path-traversal, демо, drill, avrora).
- [ ] **10.** ПУБЛИКАЦИЯ — санкция Антона по результатам: тег `v2.4.0` → GH release →
      rosst-updates latest.json → Supabase app_versions (sha256) → content-pack sync-проверка.
      Здесь же решение Антона по тестовым компам (мягко / форс app_min_version).
- [ ] **11.** После: предложить `v2.3.0`→`master` (вернуть master правду); ветку kpi-units
      НЕ удалять; durable-память и роутеры актуализировать; worktree-песочницу убрать
      (`git worktree remove`) после слияния.

## Грабли сессии (наследие)

- Чужие незакоммиченные в обоих деревьях — коммитить ТОЛЬКО своим pathspec.
- Сеть Supabase/GitHub рвёт TLS → retry; POST после обрыва — GET-проверка.
- JSON с кириллицей — json.dumps в файл + --data-binary @file.
- `npm run tauri build` НЕ пересобирает sidecar (V39) — только `build_sidecar.py`.
- Правки промптов/контента → линтеры + re-sign ОБЯЗАТЕЛЬНЫ (CLAUDE.md §18).
