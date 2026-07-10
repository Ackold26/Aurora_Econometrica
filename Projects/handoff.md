# Handoff: режим «Планирование (прогноз вперёд)» — ветка feat/econ-planning-mode

База блока: `a715b3f` (feat/econ-e1-backtest) → HEAD (15 коммитов, 2026-07-10).

## 1. Цель блока

Развести один шаг «Оптимизация» на два лица одного движка: «Оптимизация (ретроспектива)» — как надо было распределить уже потраченный бюджет, и «Планирование (прогноз вперёд)» — что будет с продажами при заданном медиаплане на будущее. Вход планирования — тот же обучающий Excel, где после исторических строк идёт «хвост будущего»: даты за концом истории, KPI пуст, инвестиции по каналам заполнены; загрузчик распознаёт хвост как медиаплан и прогоняет через обученную модель. Дополнительно закрыты три методологические дыры прогноза: adstock-carryover через границу история→будущее (включая CI-веер и backtest-витрину E1), праздники РФ в будущих периодах, обход horizon-cap вектор-планом.

## 2. Ключевые инварианты

- **Разделение история/хвост — SSOT.** Строки с пустым KPI не участвуют в обучении, статистиках, `current_spend`, rolling-окнах backtest и repair. Для файла БЕЗ хвоста фильтр `notna(kpi)` — no-op (нулевая регрессия).
- **Форма carry-in = форма обучения.** `carry_in = alpha * geometric_adstock(история)[-1]` — той же рекуррентной функцией `apply_adstock`, что использует modeler; никакой отдельной нормировки. Untrained-каналы (нулевая история) → carry_in = 0.
- **Carry-in симметричен в точечном и batch-путях** (линия прогноза и ДИ-веер согласованы: линия внутри веера; обе границы поднимаются с carry).
- **Carry-in активен только в planning-режиме** (`forecast_periods` задан) и в backtest-окнах; исторический analyst-сценарий не изменён.
- **Праздники ∩ Фурье = ∅** (колонка, попавшая в fourier_seasonality.columns, исключается из праздничного вклада — нет двойного учёта).
- **INV-50 честность:** planning-результат всегда несёт `disclaimers[]` (неизменные прочие условия); отчётные разделы прогноза не рендерятся без данных (нет wireframe-суррогатов); рекомендация вариантов честна к перекрытию ДИ.
- **Миграция localStorage 6→7 шагов идемпотентна** и ремапит сохранённый `currentStep` 5→6 (кто стоял на Отчёте, остаётся на Отчёте).
- **`media_plan.json` несёт `source_hash`** файла-источника (защита от рассинхрона план↔модель) и `confirmed` (пользователь явно подтвердил, что хвост — медиаплан).
- Атомарная запись артефактов проекта (tmp+replace), как в остальном коде.

## 3. Осознанные компромиссы

- **Weibull carry-in не реализован** (диспетчер даёт fallback на обычный adstock + warning) → Weibull доступен только на JAX-backend, редкий путь; отложено на v2, чтобы не раздувать блок.
- **Будущие значения контролей (цена/дистрибуция/конкуренты) не читаются из файла** → приняты на историческом среднем с явной оговоркой; чтение будущих контролей — осознанно вне v1 (решение владельца).
- **Дубли planning-логики в OptimizeStep не удалены** (toggle, ForecastHorizonPicker, блок прогноза) → expand-contract: старый экран живёт, пока новый PlanningStep не пройдёт релизную проверку; чистка — отдельная фаза 5.
- **`planning.json` — манифест, не дубль данных** → варианты хранятся только в `results/scenarios/*.json` (SSOT, меньше дрейфа); отчёт собирает forecast из манифеста+сценариев.
- **Детекция media-колонок для хвоста — fallback на «числовые кроме date/kpi»**, когда role-детекция имени молчит (кириллица) → шире, чем строгая классификация, но `detect_media_plan_tail` дополнительно проверяет заполненность, и это единственный способ поддержать русские имена каналов без переписывания детектора ролей.
- **`econ_scenario` в backtest-окнах получает `forecast_periods=len(test_df)`** → активирует planning-семантику в окнах; корректно, т.к. test-окно идёт сразу за train-окном.

## 4. Зоны неуверенности

1. **CI-batch ветка carry-in в scenario.py** (`compute_geometric_carry_in_batch` → `geometric_adstock_batch(..., carry_in=)`): согласованность линия/веер доказана живьём на bayesian-модели, но краевые случаи — канал без `decay_samples`, проект со смешанными adstock-типами (geometric+weibull), пустая история у части каналов — построчно не проверялись.
2. **Horizon-cap для вектор-плана при недоступном `data_file`:** для `plan_n > 1` training_n дочитывается из файла; если файл не резолвится, cap может тихо не сработать (fallback-ветка) — вектор длиннее 2× обучения пройдёт без ошибки.
3. **Пороги ретро-блока** (`render_retro_insights`: ratio < 3.0, R² < 0.6, MAPE > 20%) выбраны реализатором, с каноном коридоров INV-50/ratio-classifier не сверены — тексты рекомендаций могут расходиться с плашками честности в других местах продукта.
4. **Backtest с carry-in: механика доказана (spy-тест передачи forecast_periods), но полный rolling-прогон на реальной bayesian-модели до/после carry-in (сдвиг MAPE и вердиктов) не выполнялся** — эффект на реальные вердикты worse_than_naive не измерен.
5. **Миграция localStorage проверена vitest'ом, но не на живом клиенте** со старым 6-элементным состоянием в реальном приложении (обе комбинации ключей: глобальный и per-project).
6. **`_page_shift`/нумерация PPTX при всех 3 вставных слайдах одновременно** (backtest + gen_compare + forecast) покрыта юнит-тестом, но живой деки со всеми тремя разделами сразу не собиралось.

## 5. Затронутые файлы

**Python-движок (sidecar/econometrica/):**
- `engines/planning.py` — новый SSOT: детекция хвоста, `load_frames`, `source_hash`, `load_saved_forecast`, генератор шаблона медиаплана.
- `utils/adstock.py` — carry-in: точечный, batch, диспетчер `apply_adstock_with_carryin`.
- `engines/scenario.py` — интеграция carry-in (оба пути), праздники будущего, horizon-cap на общий путь, disclaimers.
- `engines/validator.py` — детекция хвоста при валидации (+кириллический fallback), статистики по истории, запись `media_plan.json`.
- `engines/modeler.py` / `engines/optimizer.py` / `engines/backtest.py` / `engines/persistence.py` — notna-фильтр истории (modeler лечит NaN-краш; optimizer чинит current_spend; backtest — окна + `forecast_periods` в predict_scenario; persistence — repair).
- `server.py` — `ScenarioRequest` +future_dates/carry_in; endpoints `/compute/media-plan-template`, `/compute/confirm-media-plan`; forecast в `/export/*`.
- `aurora_pptx/builder.py` — слайд `s_forecast_plan` (+график сравнения), `_page_shift` 3 слагаемых.
- `aurora_html/sections.py` — `render_forecast_plan` (+график), `render_retro_insights`.
- `charts/generators.py` — `scenarios_comparison_chart`.
- `engines/narrative_adapter.py`, `engines/pptx_export.py`, `engines/html_export.py` — проброс forecast.

**Rust (src-tauri/):**
- `src/commands/econometrica.rs` — `econ_scenario` +future_dates/carry_in; новые `econ_download_media_plan_template`, `econ_confirm_media_plan`.
- `src/commands/report.rs` — `read_forecast`, XLSX-лист «Прогноз».
- `src/commands/project.rs` — `project_load_results` +planning.json/media_plan.json.
- `src/lib.rs` — регистрация новых команд.

**Фронт (src/):**
- `lib/project-state.js` — 7 шагов, миграция localStorage, сторы mediaPlanDetected/planningManifest, reconcile.
- `lib/components/pipeline/PlanningStep.svelte` — новый экран Планирования.
- `lib/components/pipeline/ValidateStepV13.svelte` — баннер медиаплана с подтверждением.
- `routes/pipeline/+layout.svelte`, `+page.svelte`, `lib/step-icons.js` — вставка шага.
- `lib/pipeline-migration.test.js` — тесты миграции.

**Тесты (sidecar/econometrica/tests/):** `test_adstock_carryin.py`, `test_planning_detect.py`, `test_planning_history_split.py`, `test_planning_carryin_e2e.py`, `test_backtest_carryin.py`, `test_forecast_report.py`, `test_planning_cyrillic_channels.py`, `test_planning_template.py`.

**Документация:** `NEXT_SESSION_planning_mode.md` (durable-статус), `TEST_FINDINGS_planning_AVT_2026_07_10.md` (находки живого прогона).
