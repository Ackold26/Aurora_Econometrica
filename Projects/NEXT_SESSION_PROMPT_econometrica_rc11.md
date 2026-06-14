# NEXT SESSION — Econometrica: rc11 релиз (forecast + NSIS-окна) → stable 2.1.0 + карта развития

Скопируй этот промт в начало следующей сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`, ветка master.
Всё ЗАПУШЕНО (origin HEAD `baefe0b`, HEAD==origin/master).

## Контекст (сделано 2026-06-13)
**Forecast-модуль «График прогноза продаж по сценариям» ВЫПОЛНЕН и ЗАПУШЕН** (4 коммита + 4 тега):
- `fe4c5f0` `v2.1.0-rc11-forecast-ci-band` — движок per-period CI-веер (`predictions_ci_low/high` из `predicted_per_period_samples`, scenario.py) + probe `tools/probe_forecast_scenarios_kagocel.py` + тест S8b.
- `beca616` `v2.1.0-rc11-forecast-compare-wired` — Phase E wiring: `src/lib/forecast-timeline.js` (сборка «история-fit + N хвостов + веер») + `src/routes/pipeline/compare/+page.svelte` подключён к движку (`econ_compare` + `modelData.diagnostics.actual_vs_predicted.predicted` + `econ_scenario_delete`).
- `83d5bc3` `v2.1.0-rc11-forecast-adversarial-fixes` — A1 honesty (единицы money/native ГЛОБАЛЬНО по флагам compare, не per-field) + C1 (даты от len(predictions), band-guard) + B1 (forecast_periods).
- `1462f7d` `v2.1.0-rc11-forecast-chart-ux` — fullscreen (`ExpandableCard`) + богатый тултип + endpoint-легенда (`src/lib/forecast-chart-format.js`, юнит-тестирован).
- **Детальный аудит + hardening (2 коммита):** `6fae792` `security(charts)` — устранён СИСТЕМНЫЙ XSS в ECharts tooltip'ах (корень `chartTooltipDark` + 4 кастомных чарта + forecast; общий `src/lib/html-escape.js`); `baefe0b` `v2.1.0-rc11-forecast-audit-hardening` — [CRITICAL] гонка `modelData.diagnostics`→реактивная `$derived`, NaN-safe scenario.py save, nextMonths день≠01, band-mismatch warn, legend perf. 2 adversarial-агента + личная верификация.
- **Live-подтверждено** мост 9223: baseline-fit 2023-2025 + 4 хвоста + CI-веер + cutoff «Прогноз→»; fullscreen 706px; легенда endpoint. (Аудит-фиксы live НЕ перепроверены — dev был погашен; покрыты тестами, happy-path визуал не менялся.)
- Гейты: vitest **749** · svelte **0E** · python scenario **152**. cargo не трогал (Rust без изменений).

**Из rc10 (опубликован клиентам ранее):** GitHub Release v2.1.0-rc10, app_versions оба ключа, latest.json. Фича #6 (Tier-3/OVB).

## КРИТИЧНЫЕ БЛОКЕРЫ перед rc11-релизом (не переоткрывать)
1. **Sidecar СТАЛ STALE** — `scenario.py` изменён (per-period band) → bundled exe НЕ содержит band. `aurora-fix` V39 должен поймать. Compare-страница читает СОХРАНЁННЫЕ scenario.json (band там есть для уже сохранённых), но НОВЫЕ предсказания в проде дадут band только после пересборки sidecar. **Пересобрать sidecar перед rc11.**
2. **NSIS чёрные окна (`33a572a`) ВСЁ ЕЩЁ ждут пересборки** — фикс вкомпилен, нужна только Rust+NSIS пересборка (rc10 у клиентов окна сохраняет). Соединить с forecast в ОДИН rc11, не плодить rc.

## Файлы для контекста (порядок чтения)
1. Память: `project_econometrica_forecast_compare_phase_e_2026_06_13.md` (полный handoff forecast + аудит-секция), `feedback_anchor_session_to_one_real_artifact.md` (probe→фикстура→оракул→adversarial), `feedback_match_verification_to_phase_failure_mode.md` (матчи проверку к риску фазы: data→диск, form→скриншот, logic→тест), `feedback_fix_at_shared_root_not_leaf_by_leaf.md` (N находок→руби по стволу), `feedback_echarts_tooltip_innerhtml_xss.md` (XSS-класс, кросс-продукт, INV-кандидат), `feedback_verify_existing_impl_before_building_planned_feature.md` (инвентаризация ДО оценки), `feedback_default_rhythm_probe_background_adversarial.md` (рабочий ритм), `feedback_autonomous_visual_testing_standard.md` (live-test грабли SvelteKit+ECharts §новая секция), `feedback_sidecar_rebuild_required.md`.
2. Код forecast: `src/lib/forecast-timeline.js`, `src/lib/forecast-chart-format.js`, `src/routes/pipeline/compare/+page.svelte`, `src/lib/components/pipeline/MultiScenarioChart.svelte`, `sidecar/econometrica/engines/scenario.py:558` (band).

## Задачи продолжения (приоритет — уточнить у Антона)
1. **[ПЕРВЫЙ ШАГ] rc11 релиз** — собрать накопленное (forecast + NSIS-окна) в один rc11:
   - `aurora-fix` (pre-build, V39 sidecar freshness ОБЯЗАТЕЛЬНО пересоберёт, V1 bump rc10→rc11, V18 kill dev) → `CARGO_TARGET_DIR="D:/cargo-targets/ai-agency" npm run tauri build` → `aurora-release-update` (GH Release · app_versions ОБА ключа `aurora-econometrica-gui`+`econometrica` · latest.json · Edge verify). ~15 мин (sidecar 969MB долго).
   - **При живом приложении (rc11 smoke) — перепроверить аудит-фиксы** через мост 9223 (dev был погашен на момент аудита): (а) compare-страница рисует baseline+4 хвоста после реактивного рефактора `$derived`; (б) tooltip/легенда не сломаны escapeHtml (имена рендерятся нормально); (в) гонка: открыть compare СРАЗУ после смены проекта — baseline появляется (не остаётся пустым). Грабли live-теста — в `feedback_autonomous_visual_testing_standard`.
   - Forecast UX-косметика (опц., низкий приоритет): y-axis label «Прогноз продаж» обрезается; cutoff-метка «Прогноз» вертикально тесная — в MultiScenarioChart.
2. **Выход rc→stable 2.1.0** — критерии готовности; **code signing** (installer Unsigned → SmartScreen/антивирус-трения, бюджетное решение); hierarchical-проекты (27 шт) — per_control_contraction на hierarchical-путь ИЛИ явный «badges недоступны».
3. **Честность движка (INV-50)** — #4/#8 глубокий аудит оптимизатора (probe-стенд→adversarial, отдельная сессия); MCMC-divergences при удалении контролей (показывать warning в UI?); Tier-3 контроли-колонки actionable.
4. **Продукт** — sample-data Фаза 2 (`pharma_rx` shipped-broken 3/5 колонок мисроль); ΔROI-вердикт если спрос.
5. **Инфра** — бандл 969MB→243MB (ревизия collect-all build_sidecar); `Standards/` под git; версионная схема rcN vs APP_VERSION 1.2.0 задокументировать.

## Инварианты/правила
- **INV-50 честность** (единый источник+селектор+гард для отображаемых производных; оговорка доходит до клиента). Forecast CI-веер = ИЗ движка (единый HDI), не пересчёт на фронте.
- **JS+JSDoc** (НЕ TS); `.map` callbacks типизировать (`/** @type {any} */`) иначе svelte-check ERROR.
- **aurora-fix перед сборкой** (V39 sidecar freshness, V49 PREUNINSTALL kill, V50 nsExec). **aurora-release-update** для публикации (ОБА app_versions ключа Econometrica).
- **Рабочий ритм:** инвентаризуй движок (grep `def`/`engines/`/что возвращает) ДО оценки → probe-first на pickle Кагоцела (БЕЗ GUI) → фоновый агент на независимый трек → adversarial Explore на свой свежак (особо на «безопасное») → live-взгляд мост 9223 перед «готово». Каждый фикс = коммит+тег; push/release по команде; HEAD-дрейф проверять (shared master).

## С чего начать
Прочитать `project_econometrica_forecast_compare_phase_e_2026_06_13.md` + этот промт → **уточнить у Антона: делаем rc11 релиз сейчас (Задача 1) или другой пункт карты?** Затем по выбранному треку.
