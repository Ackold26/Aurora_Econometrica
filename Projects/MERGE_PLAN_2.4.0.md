# MERGE_PLAN 2.4.0 — объединение линий v2.3.0 + kpi-units (durable-якорь)

> 🔴 **ТОЧКА ВХОДА ПОСЛЕ ОБРЫВА (чекпоинт 2026-07-18 ~02:30):** шаги 0-4 ЗАКРЫТЫ
> (merge `27f11e0` на `origin/feat/econ-2.4.0`, все гейты зелёные, pytest-флак диагностирован).
> **ПРОДОЛЖАТЬ С:** фикс Agg-бэкенда (см. хвост в шаге 4) → шаг 5 (аудит диффа v2.3.1..HEAD,
> 2 аудитора фронт+python, акцент — разрешения 3 конфликтов, перечислены в шаге 2) → шаг 6 (PR→CI)
> → шаги 7-9 → СТОП перед шагом 10 (публикация — отдельная санкция Антона).
> Песочница-worktree: `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_merge` (node_modules стоят).
> Исходные ветки НЕ тронуты (страховка), обе на origin.

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

- [x] **0a.** ✅ 2026-07-18: kpi-units запушена (-u, new branch) + v230 запушена (e79bab3..983e356→d473880).
- [x] **0b.** ✅ План закоммичен `d473880` и запушен.
- [x] **1.** ✅ Песочница создана: worktree `Dev/Aurora_Econometrica_merge`, ветка `feat/econ-2.4.0` от d473880.
- [x] **2.** ✅ MERGE ЗАВЕРШЁН `27f11e0`. Авторазрешились: builder.py, sections.py, весь Rust,
      insights-rules.js. Ручных конфликтов 3, все разрешены лично Машей:
      (а) kpi-aware-formatting.js — обе стороны чинили один дубль cpuPerLabel → HEAD (фикс+комментарий);
      (б) kpi-display.js — оба добавили typedef → HEAD (KpiDisplay, полнее; KpiDisplayPassport отброшен, ссылок 0);
      (в) econometrist/CLAUDE.md — v230 переписал структуру (Батч-5), kpi-units нёс канон-блок
      COPYWRITER_STYLE → новая структура + канон-секция вставлена после нового «Поведения в диалоге»,
      байт-идентичность с kpi-units подтверждена diff, линтер промптов OK 19/19.
      ГЕЙТ ПОЛНОТЫ: `git log feat/econ-kpi-units ^HEAD` ПУСТ и `git log feat/econ-v2.3.0 ^HEAD` ПУСТ —
      обе линии целиком внутри. ⚠️ lefthook в песочнице не установлен (хуки не гонялись) — линтеры в шаге 4/6.
      Старый вариант шага: `git merge feat/econ-kpi-units` (база fecdb84 3-way).
      Правила разрешения: обе ценности сохраняются; версии — сторона v230 (2.3.1, bump позже);
      идентичные правки (maximized/no-window/смоук) — авторазрешение или любая сторона (идентичны);
      builder.py/sections.py — P-2-маппер (реальная схема totals.*, None→«—», интервал суммы,
      TOC-подстрока) ОБЯЗАН выжить ВМЕСТЕ с правками отчётов 2.3.1; CLAUDE.md econometrist —
      стиль-ядро канон + Батч-5 линтер-правки вместе, сверка с `_shared/` каноном;
      содержательные конфликты решает Маша ЛИЧНО, не субагент.
- [x] **3.** ✅ РЕШЕНО архео-следом: сообщение коммита d9c74a0 прямо говорит «Доставка клиентам –
      публикацией vault (отдельный гейт)» ⇒ vault c2 канона НЕ содержит ⇒ **vault c3 В ОБЪЁМЕ РЕЛИЗА**
      по регламенту (lint_prompt_commands ✅ уже OK 19/19 → cabinet_eval --dry → vault-pack c3 →
      строка c3 current в content_versions + vault_versions ЗАПОЛНИТЬ (без него stale-блок не доставит!)).
      Двойная проверка при упаковке: в pack-каталоге канон-блок присутствует.
- [x] **4.** ✅ ГЕЙТЫ ПРОЙДЕНЫ 2026-07-18 (субагент + личная сверка Маши; песочница ЗАПУШЕНА
      `origin/feat/econ-2.4.0` = 27f11e0):
      npm ci чисто (lock не изменился) · svelte-check **0 ERRORS**/177 warn (предсущ.) ·
      vitest **1279/1279 passed (79 файлов)** · npm run build ✅ (2 чанка >500kB — предсущ. warn) ·
      cargo test **197 passed/0 failed** · pytest: у агента 698+2 FAIL (test_forecast_report
      scenarios_comparison_chart ×2, TclError TkAgg), у Маши лично **700 passed/0 fail**, изолированный
      прогон 2 тестов = **passed** ⇒ ФЛАК от распределения xdist, НЕ регрессия слияния.
      **Корень (проверен grep):** НИКТО в sidecar не задаёт headless-backend matplotlib
      (`matplotlib.use('Agg')` отсутствует, conftest пуст, MPLBACKEND не задан; generators.py:6
      импортирует pyplot голым) — на dev-машине сломанный Tcl/Tk → TkAgg иногда взрывается.
      📌 **ОТКРЫТЫЙ ХВОСТ → фикс до сборки:** форсировать Agg — в `charts/generators.py` (и
      соседних chart-модулях, grep pyplot) `import matplotlib; matplotlib.use("Agg")` ДО pyplot
      + в tests/conftest.py `MPLBACKEND=Agg` страховкой; заодно защищает клиентский бандл
      (PyInstaller excludes tkinter НЕ найден в build_sidecar.py — бандл может нести Tk!).
      Затем pytest ×2-3 прогона стабильно зелёный.
- [~] **4b.** ✅ Agg-фикс СДЕЛАН (`ab27ed9`, запушен): `charts/__init__.py` форсирует Agg до pyplot;
      негатив-проба MPLBACKEND=TkAgg проходит (переопределение доказано), pytest ×3 = 700 стабильно.
- [~] **5.** АУДИТ ИДЁТ (2026-07-18): 2 opus-аудитора запущены по готовым диффам
      `Projects/audit_240_front.diff` (756 строк, src/+src-tauri/) и `audit_240_python.diff`
      (574, sidecar/), акцент — сверка разрешений merge с ОБЕИМИ родительскими версиями
      (builder.py/sections.py/build_sidecar.py — авто-слияние = зона риска). Ждём отчёты → триаж.
- [~] **6.** CI ИДЁТ: **PR #4 (draft)** feat/econ-2.4.0 → feat/econ-v2.3.0 создан, Test&Lint
      запущен, фоновый монитор `gh pr checks 4 --watch` активен.
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
