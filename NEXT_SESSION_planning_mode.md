# Планирование (прогноз вперёд) — мастер-промпт продолжения (durable)

> **Точка входа при возврате / после компрессии.** Читать ПЕРВЫМ. Продолжать БЕЗ переспроса с раздела «ОСТАЛОСЬ», развилки решать самой (мандат Антона: автономна на исполнении и тактике). Снять режим — по слову Антона «стоп/готово по планированию».

## Что делаем
Разделяем шаг «Оптимизация» на два лица одного движка: **«Оптимизация (ретроспектива)»** → **«Планирование (прогноз вперёд)»**. Модель одна, оптимизатор один. Вход планирования — тот же обучающий Excel, где после истории идут будущие месяцы (даты за концом истории, KPI пуст, инвестиции по каналам заполнены = медиаплан). Движок прогоняет медиаплан через обученную модель → прогноз + варианты. Отдельный прогноз-раздел в отчётности для руководства + ретро-выводы для аналитика.
**Цель:** не повторить Robyn/Meridian, а стать образцом — эконометрика ТОП-уровня силами обычного планера.

**Полный план (после 2 раундов адверс-аудита):** `C:\Users\ackol\.claude\plans\synchronous-stirring-wilkinson.md` (план v3, находки A1-A12, S1-S7, U1-U10).

## Ветка и режим работы
- Ветка **`feat/econ-planning-mode`** от `feat/econ-e1-backtest` (НЕ запушена — пуш по слову Антона). Репо `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`.
- В репо живут чужие незакоммиченные (`installer_hooks.nsh` M, `model_backend.rs` ??) — НЕ трогать, коммитить своим pathspec.
- Кодинг — субагентам на sonnet, я (Opus) — оркестрация + ЛИЧНАЯ верификация (прогон тестов сама, git diff, сырые выводы — урок про фантом-агента [[feedback_agent_report_requires_raw_outputs]]).
- Запуск тестов: из `sidecar/econometrica`: `python -m pytest tests/ -q -m "not requires_real_data"`. Фронт: `CI=1 npx vitest run`, `npm run check`. Rust: `cd src-tauri && CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" cargo check`.

## ✅ СДЕЛАНО (6 коммитов, все гейты зелёные)
Гейты на HEAD: **sidecar pytest 475 passed** (1 правомерный OLS-skip), **vitest 996**, **svelte-check 0**, **cargo check Finished**.
- `424efe8` Фаза 0+1b+1a-i+2 — скелет: детектор хвоста (`engines/planning.py` detect_media_plan_tail/load_frames/compute_source_hash), carry-in математика (`utils/adstock.py` — точечный+batch+диспетчер), 7-й шаг пайплайна `planning` (миграция localStorage 6→7 с ремапом currentStep, сторы mediaPlanDetected/planningManifest, PlanningStep-заглушка).
- `0898ea1` INT-1 — SSOT-разделение история/хвост: notna(kpi)-фильтр у modeler/optimizer/backtest/persistence + детекция в validator (пишет media_plan.json). Регресс-инвариант: файл без хвоста → no-op. Чинит существующий NaN-краш likelihood.
- `e4f2769` INT-2 — carry-in + праздники + horizon-cap + disclaimers в scenario.py (planning-режим); ScenarioRequest +future_dates +carry_in.
- `ef3a461` A3 — carry-in в backtest-витрине (forecast_periods в окна) + доказательство веера A2 (обе границы CI поднимаются, posterior-фикстура) + A9 (holiday∩fourier исключён).
- `9efb490` Фаза 3+4 — баннер медиаплана (ValidateStepV13, подтверждение A6) + полный PlanningStep.svelte (U1-U10) + Rust econ_scenario проброс future_dates/carry_in.
- `af12181` Фаза 6a — прогноз-раздел PPTX (s_forecast_plan) + HTML (render_forecast_plan) + load_saved_forecast + narrative/export проброс.

**Ключевое доказано числами:** carry-in реально поднимает `predictions[0]` (разделяющий зонд на обученной модели), линия и веер согласованы. Backtest наследовал ту же дыру (A3) — теперь carry-in чинит и справедливость вердиктов worse_than_naive.

## ⏳ ОСТАЛОСЬ (продолжать отсюда, порядок по приоритету)
1. **Фаза 5 — чистка OptimizeStep (expand-contract contract-шаг).** Удалить planning-блоки из `OptimizeStep.svelte` (4269 строк): planning-mode-toggle, ForecastHorizonPicker, planning-banner, hierarchicalWarning, блок «Прогноз с медиаинфляцией», fixForecastPromise/PromisesCard, econ_forecast_context $effect, planning-ветку effectiveBaseBudget/runOptimize. `planningMode` стор — удалить (grep читателей) или зафиксировать 'analyst'. ПЕРЕД удалением — характеризующий тест OptimizeStep. Гейт: svelte 0, vitest, analyst-оптимизация не сломана. (Делается ПОСЛЕ того как PlanningStep доказан живым — сейчас PlanningStep готов, но живьём не прогнан → аккуратно.)
2. **Фаза 6b — частично СДЕЛАНО (не закоммичено на момент записи — коммитить после cargo зелёного):** XLSX-лист «Прогноз» в `report.rs` (`read_forecast`, между «Оптимизация» и «Сценарии», TOC-строка) ✅ + `scenarios_comparison_chart` в charts/generators.py ✅ (pytest 479, cargo check шёл). **ОСТАЛОСЬ по 6b:** (а) подключить `scenarios_comparison_chart` в отчёт — субагент создал функцию, но НЕ вставил в PPTX-слайд (побоялся layout) и HTML → график пока мёртвый; вставить в `render_forecast_plan` (HTML base64 проще) или вторым PPTX-слайдом «Сравнение вариантов»; (б) ретро-выводы «что улучшить» отдельным блоком (реструктуризация s11_sources + render_retro_insights из готовых diagnostics — honesty_verdict/preflight/thinness).
3. **TODO backend-команды (для полноты UX, фронт сейчас graceful):**
   - `econ_confirm_media_plan(project_dir, confirmed)` — персист подтверждения в media_plan.json (confirmed=true). Rust econometrica.rs + Python /compute endpoint.
   - `econ_download_media_plan_template(project_dir)` — U5: генерация Excel = история клиента + N будущих строк (правильные даты/каналы/пустой KPI). Дёшево (openpyxl). Ценно — «превращает контракт в кнопку».
4. **optimizer planning carryover (остаток Фазы 1, вторично):** carry-in в `evaluate_flat_allocation_response` (utils/forecasting.py) + optimizer planning-mode. Основной путь (scenario) carry-in уже имеет; это для «оптимизировать будущий бюджет».
5. **Фаза 7 — живой прогон + пересборка + релиз.** 🔴 Пересобрать sidecar `build_sidecar.py` (fat-client — `npm run tauri build` sidecar НЕ пересобирает, V39). Живой GUI-прогон полного пути через tauri-мост (AVT-метод, `npm run tauri:dev` для моста :9223): создать тестовый Excel с хвостом → Импорт → Валидация (баннер) → Модель → Декомпозиция → Оптимизация → **Планирование** (варианты, сравнение, disclaimers, фиксация) → Отчёт (прогноз-раздел). Durable TEST_FINDINGS. Разделяющий зонд carry-in первым ходом (с/без — числа отличаются). CI-веер carry-in (A2) на живой bayesian-модели проверить (в CI скипался на OLS). Финальный гейт: pytest+vitest+svelte 0+cargo+verify. Installer по `aurora-fix`; публикация — по слову Антона (канал `aurora-econometrica-gui`; V52; локальная M1 отдельным манифестом).

## Контракт данных (якорь)
- `results/media_plan.json`: `{n_future_periods, period_labels[], granularity, channels:{col:[float]}, future_dates[], detected_at, source_file, source_hash, confirmed:bool, warnings[]}`.
- `results/planning.json` (манифест): `{variant_ids[], accepted_variant, disclaimers[]}`; данные вариантов — в `results/scenarios/*.json`.
- Результат сценария (planning): `predictions[]`, `predictions_ci_low/high[]`, `total_kpi`, `total_spend_money`, `roas_money`, `carry_in_applied`, `disclaimers[]`, `future_dates[]`.

## Грабли / уроки сессии
- carry-in форма ОБЯЗАНА совпасть с обучением (рекуррентный geometric, posterior-decay, нормировка adstock_mean_posterior) — иначе перенос в неверном масштабе (A5). Weibull carry-in — фаза 2 (только JAX-backend).
- horizon-cap раньше жил под `plan_n==1` — обходился медиапланом-вектором (A4, закрыто).
- backtest carry-in гейтится по forecast_periods — надо ПЕРЕДАВАТЬ явно (A3, закрыто).
- Субагенты параллельно на пересекающихся файлах → коллизия в дереве (resumed INT-2 + мои backtest-правки). Разруливать зондом git status/diff, не доверять отчёту агента об атрибуции.
- Rust econ_scenario конвертит camelCase (futureDates→future_dates) авто.
