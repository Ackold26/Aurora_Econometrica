# Handoff — Econometrica 2.4.0: объединение линий + релиз (2026-07-18)

> ✅ Внешний diff-аудит ВЫПОЛНЕН по ходу операции (2026-07-18, 2×Opus в чистом контексте,
> дифф `v2.3.1..HEAD` = вся операция 2.4.0, шире base-SHA окна): вердикт **«ГОТОВ К РЕЛИЗУ»**,
> **0 High / 0 Medium**, 2 Low (мёртвая ветка guard build_sidecar.py:157; предсущ. em-dash
> PromisesCard.svelte:112) → в бэклог, не чинились (хирургичность). Ключевое утверждение
> (реверс-патчи обеих родительских сторон чисты, вклады целы) перепроверено лично. 2.4.0
> опубликован. Прошлый handoff (сессия 2026-07-16/17) → git-история файла.

## Цель блока
Слить разошедшиеся ветки Optimizer MMM — прод `feat/econ-v2.3.0` (2.3.1) и planning/KPI
`feat/econ-kpi-units` (2.2.0) — в релиз 2.4.0 без потери функциональности ни одной стороны,
довести доводку Планирования (прежде всего P-2: честные числа в прогноз-разделе PPTX вместо
ложных нулей, которые были у клиентов в 2.3.1) и опубликовать по всем каналам.

## Ключевые инварианты
- **Полнота слияния:** обе родительские ветки — предки объединённого HEAD
  (`git log <ветка> ^HEAD` == пусто для обеих). Достигается merge'ом, не cherry-pick.
- **P-2 / INV-50:** прогноз читает реальную схему `totals.predicted_kpi`; None → «—», не 0.0;
  интервал PPTX/HTML = СУММА за горизонт (SSOT с GUI-карточкой), не CI последнего периода.
- **no-window (Rust):** каждый консольный спавн под Windows несёт `creation_flags(0x08000000)`
  через `#[cfg(windows)]` (не ломает не-Windows); UAC установщика НЕ подавляется.
- **Headless-графики:** `matplotlib.use("Agg")` в `charts/__init__.py` до импорта pyplot.
- **Доставка:** app_versions (id `aurora-econometrica-gui` + short `econometrica`) и fallback
  `latest.json` — одним батчем; правки промптов доставляет vault_versions bump.

## Осознанные компромиссы
- **F2 (лейбл «Дата отсечки») НЕ в релизе** — минор, требует живого рендера, конец сессии +
  экран занят другой сессией. Перенесён с точным кодом и гипотезой (коллизия с rotate:35).
- **Build Release job отключён `if: false`, не удалён** — собирал exe без sidecar (битый
  артефакт); канал — локальная сборка + aurora-releases. Логика сохранена для возврата.
- **2 Low аудита не чинились** (хирургичность) → бэклог.
- **Cargo.toml оставлен с EOL-шумом** (LF→CRLF, содержимое идентично 2.4.0) — без коммита.

## Зоны неуверенности
1. **Авто-merge `builder.py`/`sections.py`** (P-2 vs отчёты 2.3.1). Верифицировано реверс-
   патчами обеих сторон + 32 регресс-теста + живой PPTX. НО живой прогон — на ОДНОЙ фикстуре
   (физметрика); прогноз-раздел с money-KPI/money-каналами (roas_money не None) живьём не наблюдался.
2. **Клиентская докачка vault c2→c3** (stale-блок): канон в c3 подтверждён артефактом из
   Storage, но путь докачки на СВЕЖЕЙ установке в этой сессии не прогонялся (только при публикации c3 16.07).
3. **Доставка 2.4.0 на PC443/PC583** (на 2.1.0): Edge отдаёт 2.4.0, баннер исправен по коду,
   но живого обновления на этих машинах не наблюдали; ранее баннер там игнорировали.
4. **F2** — визуально не верифицирован; `position:'insideEndTop'` не доказан как источник/не-источник наложения.

## Затронутые файлы (роль)
- `sidecar/econometrica/aurora_pptx/builder.py`, `aurora_html/sections.py` — P-2 + отчёты 2.3.1 (авто-merge).
- `sidecar/econometrica/engines/planning.py` — `load_saved_forecast` реальная схема, None-маппинг.
- `sidecar/econometrica/charts/__init__.py` — NEW: headless Agg.
- `sidecar/econometrica/build_sidecar.py` — смоук-гейт бандла INV-96 (авто-merge).
- `src/lib/kpi-aware-formatting.js`, `src/lib/kpi/kpi-display.js`, `src/lib/insights-rules.js` — svelte-check (ручной merge).
- `src/lib/components/pipeline/PromisesCard.svelte` — P-3 текст; `PlanningStep.svelte` — дизайн/тема.
- `src/tests/scenario-export.test.js` — jsdom fake-timers.
- `src-tauri/src/{lib.rs,commands/{updater,claude,diagnostics,pptx_processor}.rs,session/manager.rs}` — no-window + maximized.
- `New_AI_Agency/econometrist/CLAUDE.md` + `_shared/COPYWRITER_STYLE.md` — стиль-ядро (ручной merge).
- `src-tauri/{Cargo.toml,tauri.conf.json}`, `package.json`, `Cargo.lock`, `package-lock.json` — bump 2.4.0.
