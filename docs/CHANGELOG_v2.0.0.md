# Aurora MMM Optimizer v2.0.0 — Release Notes

**Release date:** 2026-XX-XX (target: середина июня — начало июля 2026)
**Branch:** `feat/v2.0.0-explicit-mode-wizard`
**ADR:** ADR-019 (supersedes ADR-015)

---

## 🎯 Главное

Aurora MMM Optimizer v2.0.0 — крупный UX-рефакторинг с focus на **«эконометрист доступен маркетологу»**. Mode (ROI / Эффективность) становится явным выбором Manager-режима одним кликом. Смешанный режим единиц убран из default flow → Expert mode opt-in.

**5 крупных нововведений:**

1. **ScenarioWizard** — диагностический мастер вместо catalog шаблонов. Auto-detect делает 60-80% работы, wizard спрашивает 3-7 шагов до запуска модели.

2. **Signed factor support** — модель явно учитывает negative factors (активность конкурентов, цена, погода, макроэкономика). Декомпозиция показывает «−15% от конкурентов» как отдельный bar в WaterfallChart.

3. **РФ holiday auto-injection** — 12 hardcoded событий (Новый Год / 23 февраля / 8 марта / 9 мая / Чёрная Пятница / Cyber Monday / школьные каникулы) автоматически инжектируются как control factors. Декомпозиция в декабре больше не врёт.

4. **Diagnostics panel** — traffic-light статус модели (MCMC сходимость / Backtest / PPC / Sensitivity tornado). Manager видит «✅ модель сходится», Expert раскрывает full plots.

5. **Multi-scenario comparison** — отдельная страница для сравнения N планов: continuation chart с overlay, сортируемая таблица, автогенерируемые narrative diffs, экспорт CSV/Excel/PPTX.

---

## ⚙️ Архитектурные изменения

### Mode выбор стал explicit (ADR-019 supersedes ADR-015)

**Было (v1.3.x):** mode (ROI / Эффективность / Manual) выводился автоматически из per-channel выборов. Юзер случайно попадал в Manual (смешанный) режим с unit_cost ставками — точность ROI ±10-25%.

**Стало (v2.0.0):**
- **Manager mode (default):** один клик ROI / Эффективность. Все каналы выровнены в одну единицу. `UnitCostsPanel` скрыт.
- **Expert mode (opt-in):** третья опция «Смешанный» + per-channel control + UnitCostsPanel доступны.

**Backward compat:**
- Pure monetary projects → Manager ROI silent
- Pure physical projects → Manager Эффективность silent
- Mixed projects → auto-Expert + toast notification

### Variable classifier расширен

**Было:** 4 категории (monetary / physical / target / unknown).

**Стало:** 13 target types (sales / leads / subscriptions / applications / bookings / transactions / traffic / loyalty / installs / ...), 15 media formats (TV / Digital / OLV / Performance / Social / OOH / Print / Radio / Cinema / Аптечный OOH / Retail Media / Influencer / Email-CRM / Programmatic / Affiliates), 4 signed control types (competitor / price / weather / macro), holiday markers.

**420 pytest tests** покрывают classifier.

### РФ-monthly default granularity

Aurora теперь default'ит monthly grain (РФ-стандарт MMM). Weekly grain — auto-adapt опция для customers с подходящими данными.

---

## 🆕 Новые фичи

### ScenarioWizard (6 шагов, 3-7 active в типовом случае)

1. **Task intent** — что хочешь получить?
   - Распределить плановый бюджет (`budget_optimization`)
   - Достичь цели — сколько потратить? (`inverse_optimization`)
   - Найти оптимальный размер бюджета (`what_if`)
   - **NEW:** Прогноз по моему плану активностей (`forecast_planned_activities`)
   - Просто декомпозировать прошлый период (`decompose-only`)

2. **Target metric confirm** — auto-detect 1 candidate с confidence ≥0.95 → silent. Иначе disambiguation list. Для count KPI — поле «Ценность единицы».

3. **Media inputs confirm** — auto-detect per-channel, best-practice warnings (Performance→клики, OLV→просмотры, TV TRP→приведённые), bulk mode selector.

4. **Plan inputs** (task-specific):
   - budget_optimization → бюджет + период + constraints
   - inverse_optimization → target absolute / +%
   - what_if → range бюджетов (±20% / ±50% / custom)
   - **NEW:** forecast → upload Excel с плановыми активностями
   - decompose-only → skip

5. **Context confirm** (optional) — auto-detected non-media factors (trade_activity / distribution / 11 РФ-праздников / competitors / prices).

6. **Summary + Diagnostics** — model summary + traffic-light diagnostics + Run.

### 5-й task profile: `forecast_planned_activities`

Customer загружает Excel с плановыми активностями → модель прогнозирует period-by-period KPI с CI 90%. Output — continuation chart с history + model fit + forecast.

### Multi-scenario comparison page

`/pipeline/compare` — сравнение N планов:
- **Continuation chart** с overlay (до 5 scenarios visible, остальные через legend toggle)
- **Comparison table** (Budget / Predicted KPI / CI 90% / Uplift % / Per-channel breakdown)
- **Auto-generated narratives** («План B даёт +27.3% KPI при +40% budget — высокая marginal стоимость роста»)
- **Export** CSV / Excel / PPTX (XLSX/PPTX requires backend implementation post-ship)

### DiagnosticsPanel (traffic-light)

Manager view: 4 traffic-light rows
- 🟢/🟡/🔴 **Сходимость MCMC** — R-hat / ESS
- 🟢/🟡/🔴 **Backtest** — MAPE / R²
- 🟢/🟡/🔴 **Posterior predictive** — R² / Durbin-Watson
- 🟢/🟡/🔴 **Sensitivity** — adaptive top-7 parameters

Expert expand: trace plots, ESS per parameter table, full PPC scatter + residuals.

### Sensitivity Tornado

`engines/sensitivity.py` (новый модуль) — adaptive top-7 параметров varied ±20%, ranked by |ΔROI|. UI horizontal bar chart с diverging directions.

### Signed factor support в WaterfallChart

Negative bars для signed factors (competitor / price / weather / macro):
- `signed_competitor` → red
- `signed_price` → purple
- `signed_weather` → sky-blue
- `signed_macro` → amber
- `holiday` → violet
- `positive_control` → teal

### JSON model export

`engines/json_export.py` — экспорт всех ключевых параметров модели (channels, signed_factors, controls, holidays_injected, normalization, priors_used, mcmc_diagnostics, backtest_results, ppc_results) в structured JSON для external validation.

---

## 🐛 Bug fixes (audit-driven)

### Critical
- **Frontend C5:** ScenarioWizard теперь корректно рендерит Steps 4-6 (был placeholder stub после parallel sub-agent work)
- **Frontend C2:** Svelte 5 `$state` from props anti-pattern исправлен в StepMediaConfirm + RecommendationCard + StepTargetConfirm
- **Backend C1:** division-by-zero guard в `signed_factor_contributions` pct calculation

### High
- **Backend C5:** `control_prior_mus` fallback логика clarified (positive control vs unknown)
- **Backend H3:** zero-variance control columns flagged как `untrained_controls`
- **Backend H4:** sensitivity tornado guard для near-zero baseline ROI (`_BASELINE_ROI_ACTIONABLE_GUARD = 1e-3`)
- **Arch H3:** holiday collinearity severity granular (`warn_expected` / `merge_recommended`)

---

## 🏗️ Технические детали

### Новые backend модули
- `sidecar/econometrica/utils/holiday_calendar_ru.py` — 12 РФ events + collinearity check
- `sidecar/econometrica/utils/best_practice_rules.py` — soft-recommendation library
- `sidecar/econometrica/engines/json_export.py` — model params JSON export
- `sidecar/econometrica/engines/sensitivity.py` — adaptive top-7 sensitivity tornado

### Новые frontend компоненты
- `AnalysisModeSelector.svelte` (463 LOC)
- `AppliedModeSummary.svelte` (331 LOC)
- `ScenarioWizard.svelte` (811 LOC) + 6 step components (1773 LOC)
- `DiagnosticsPanel.svelte` (569 LOC)
- `ContinuationChart.svelte` (351 LOC)
- `SensitivityTornado.svelte` (308 LOC)
- `PPCScatter.svelte` (382 LOC)
- `MultiScenarioPage.svelte` (1211 LOC)
- `MultiScenarioChart.svelte` (383 LOC)
- `wizard-state.js` + `mode-defaults.js` (state machine + migration)
- `scenario-diff-analyzer.js` + `scenario-export.js`

### Расширенные backend модули
- `column_detection.py` — 13 target types + 15 media formats + signed controls + holidays
- `validator.py` — CONTROL_PATTERNS extended с signed factors
- `modeler.py` — holiday auto-inject + signed factor priors + untrained_controls
- `decomposer.py` — `signed_factor_contributions` output
- `persistence.py` — v2.0.0 diagnostics cache (mcmc_diagnostics, backtest_results, ppc_results, sensitivity_tornado_cache)

### Тесты
- **420 pytest** tests (`tools/test_column_detection_v2.py`)
- **136 Vitest** tests для wizard components (5 files)
- **Total 556 tests passing**

### Quality gates
- svelte-check: 0 errors, 164 warnings (preserved baseline)
- pytest backend: passing
- vitest frontend: passing
- ECharts integration consistent (no Chart.js dep added)

---

## ⚠️ Breaking changes

**Нет breaking changes для customer.** Bundle schema additive (per ADR-017 + ADR-018). Migration logic:

| v1.3.x project | v2.0.0 behavior |
|---|---|
| Pure monetary perChannelInput | Manager ROI mode (silent) |
| Pure physical perChannelInput | Manager Effectiveness mode (silent) |
| Mixed perChannelInput | Auto-Expert mode + toast notification |
| Empty/new project | Manager ROI default |

`analysisObjective` store deprecated, но preserved как derived alias от `analysisMode` для backward compat legacy code (ValidateStep / InsightsPanel / UnitCostsPanel).

---

## 🚧 Known limitations

1. **Excel / PPTX export** для multi-scenario page — UI готов, но требует Rust backend commands (`econ_export_scenarios_xlsx`, `export_scenarios_pptx`). CSV export работает полностью. Excel/PPTX → post-ship (v2.0.1).

2. **Signed factor priors** — текущие значения (μ=-0.3 для competitor, μ=0 для signed unconstrained, μ=+0.2 для positive controls) — placeholder. Math review на pilot data (pilot pharma dataset / pilot pharma dataset 2) scheduled в Phase E.

3. **Methodology Certificate verifier** (verify.auroraai.pro) — требует update schema для new fields (signed_factor_contributions, holidays). Cross-product coordination с aurora-platform-core.

4. **Phase D Vitest** — MultiScenarioPage + MultiScenarioChart unit tests pending. Pure JS modules (scenario-diff-analyzer.js + scenario-export.js) тесты — async work в progress.

5. **Sentry / telemetry** — wizard error states yet не integrated. Production observability — v2.0.1.

---

## 📈 Methodology validation

**Industry parity** (per `docs/v2_0_0_design/GAP_ANALYSIS_v1.md`):

| Feature | v1.3.x | v2.0.0 | Robyn | PyMC-Marketing | Nielsen BASES |
|---|---|---|---|---|---|
| Signed factors | ❌ | ✅ | ✅ | ✅ | ✅ |
| Holiday auto-inject | ❌ | ✅ (РФ) | ✅ (US/global) | ⚠️ | ✅ |
| MCMC convergence UI | ⚠️ backend | ✅ | ✅ | ✅ | ⚠️ |
| Backtest validation | ⚠️ existing | ✅ surfaced | ✅ | ✅ | ✅ |
| Sensitivity tornado | ❌ | ✅ | ✅ | ⚠️ | ⚠️ |
| Multi-scenario comparison | ❌ | ✅ | ✅ | ❌ | ✅ |
| Forecast по плану | ❌ | ✅ | ✅ | ❌ | ✅ |
| Methodology Certificate | ✅ unique | ✅ enhanced | ❌ | ❌ | ❌ |

Aurora v2.0.0 — **competitive parity с Robyn в math depth, премиум UX поверх**.

---

## 🛠️ Migration guide

Для существующих v1.3.x проектов → автоматическая migration logic. Пользователю достаточно открыть проект в v2.0.0 — система:

1. Загружает bundle с `perChannelInput` field
2. Determines mode по migrateV13ToV20 algorithm (5 cases)
3. Sets `analysisMode` + `expertMode` stores
4. Shows toast если mixed → auto-Expert

См. полный migration spec: `docs/v2_0_0_design/PRE_FLIGHT_FIXES.md` §B3.

---

## 📚 Reference docs

- **ADR-019** Aurora MMM Optimizer v2.0.0 Architecture (`docs/adrs/ADR-019_explicit_mode_wizard_v2.md`)
- **WIZARD_FLOW_v2_FINAL** Implementation spec (`docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md`)
- **GAP_ANALYSIS_v1** Comparative analysis vs industry (`docs/v2_0_0_design/GAP_ANALYSIS_v1.md`)
- **V2_1_0_PLUS_ROADMAP** Post-v2.0.0 sprint sequence (`docs/v2_0_0_design/V2_1_0_PLUS_ROADMAP.md`)
- **AUDIT_RESULTS_v1** Red-team audit findings (`docs/v2_0_0_design/AUDIT_RESULTS_v1.md`)
- **MIGRATION_v1.3_to_v2.0** Customer migration guide (`docs/MIGRATION_v1.3_to_v2.0.md`)

---

## 🙏 Credits

Sprint лидировала Маша маленькая (Claude Opus 4.7 в Aurora_Econometrica session 2026-05-14). Parallel sub-agent работа на Sonnet 4.6 для implementation. Antоn — product strategy + architectural reviews + audit findings approvals.

10+ commits на branch, ~12000 LOC + 556 tests + 0 svelte-check errors.
