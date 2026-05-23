# ADR-019: Aurora MMM Optimizer v2.0.0 — Explicit Mode + ScenarioWizard Architecture

**Status:** Accepted
**Date:** 2026-05-14
**Owner:** Маша маленькая (review Антон)
**Supersedes:** ADR-015 (Mode as Derived State)
**Preserves:** ADR-014 (Safe Corridor Bounds), ADR-016 (KPI Kinds Binary Semantics), ADR-017 (Bundle Schema v13 Additive), ADR-018 (Migration Safety Protocol)
**Related:** INV-25 (Dual-mode UX), INV-30 (MMM single-unit preference)
**Reference docs:** `docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md`, `GAP_ANALYSIS_v1.md`, `V2_1_0_PLUS_ROADMAP.md`, `INTERVIEW_NOTES.md`

---

## Context

Aurora MMM Optimizer v1.3.x использует **derived-mode UX**: пользователь выбирает per-channel input metric (`monetary` / `physical`) для каждого канала, а mode (`'roi'` / `'effectiveness'` / `'manual'`) автоматически выводится из per-channel выборов. Это решение зафиксировано в **ADR-015**.

### Проблемы текущей архитектуры (root cause analysis 2026-05-13)

1. **Mixed-mode trap.** Юзер делает per-channel выбор без понимания что любое несовпадение единиц = `mode='manual'` (смешанный). Этот режим требует `unit_cost` ставок (250 000 ₽/TRP и т.д.), которые сам пользователь вводит как догадку — это **измерение с ошибкой 10-25%**. Получается, юзер случайно попадает в самый сложный режим, не понимая ответственности.

2. **Двух-панельная UX-путаница.** `PerChannelInputSelector` (v1.3, per-channel выбор) и `UnitCostsPanel` (v1.2 legacy, ставки конверсии) живут параллельно. Оба решают разные части одной проблемы. Customer не понимает зачем обе.

3. **Mismatched ICP в ADR-015 rationale.** ADR-015 §3 цитировал PyMC-Marketing, Meta Robyn, Lightweight MMM, Jin et al. (2017) как «industry standard mode-free». Но эти library — **analyst-driven tools** для эконометристов PhD. Aurora ICP — **агентский аналитик-маркетолог** (90% use case) и брeнд-менеджер (10%). Argument-from-authority применён без проверки context match (зафиксировано в `feedback_authority_argument_context_check.md` + `feedback_technical_vs_product_question_disambiguation.md`).

4. **Methodological gap — signed factors.** Текущая Aurora не различает «signed control factors» (competitor activity → negative coefficient, price → unconstrained, weather/macro → signed) от «media channels» (positivity-constrained). Decomposer не возвращает negative contributions. UI WaterfallChart не рендерит negative bars. Эконометрист агентства сразу заметит наивность по сравнению с Robyn / Nielsen / Kantar.

5. **Cascade bug evidence.** B4 finding в v1.3.2 audit pass (raw vs derived metric, fix `a776060`) — прямое следствие двух-панельной архитектуры. Цена ошибки: 4-layer cascade fix.

6. **Missing forecast по плану пользователя.** Aurora имеет 4 task profiles (`budget_optimization` / `what_if` / `inverse_optimization` / coverage check), но **не имеет** task для «загрузить план активностей, получить прогноз». Антон 2026-05-14: «это ключевая цель моделирования».

### Текущий customer base context

- **1 реальный агентский customer** работает с Aurora несистемно, преимущественно для фарма-клиентов
- **Aurora positioning:** «результат high-end эконометриста доступен маркетологу» (ADR-013, Антон 2026-05-12)
- **B2B2C модель:** Aurora → агентство → бренд-клиент. Primary user — агентский аналитик, не бренд-менеджер
- **TOP-5 приоритеты (Антон 2026-05-13):** Фарма OTC / FMCG / Ретейл / Недвижимость / Агентства
- **MMM granularity РФ-стандарт = monthly**, не weekly как в US/EU industry libraries

---

## Decision

### 1. Mode становится Explicit Manager Choice

`analysisMode` store с тремя значениями: `'roi'` / `'effectiveness'` / `'mixed'`.

**Manager mode (default 80%+ use cases):** AnalysisModeSelector с **двумя кнопками**:
- 💰 **Денежный (ROI)** — все медиа-каналы подаются в ₽. Модель считает ROI / CPU
- 📦 **Штучный (Эффективность/CPU)** — все медиа-каналы в физических метриках. Модель считает доли вклада

**Expert mode (opt-in через `$expertMode` toggle):** добавляется третья кнопка:
- 🔧 **Смешанный (Expert)** — per-channel выбор + `UnitCostsPanel` доступна

При выборе Manager mode — `perChannelInput` автоматически заполняется однородно (все `'monetary'` или все `'physical'`). `UnitCostsPanel` HIDDEN. `PerChannelInputSelector` replaced by `AppliedModeSummary` (read-only сводка с CTA «Управлять вручную → Expert mode»).

Backward-compat: `analysisObjective` остаётся как `derived` alias (`'mixed' → 'manual'`). Legacy ValidateStep / InsightsPanel / UnitCostsPanel работают через alias без правок.

### 2. ScenarioWizard как entry point

Новый компонент `ScenarioWizard.svelte` ведёт Manager через 3-7 шагов до запуска train:

| Шаг | Что | Условный skip |
|---|---|---|
| 1 | Task intent (5 options) | always shown |
| 2 | Target metric confirm + value_per_count_unit для count KPI | silent если 1 candidate с confidence ≥0.95 |
| 3 | Media inputs confirm + best-practice warnings | silent если все каналы в одной единице |
| 4 | Plan inputs (task-specific) | always shown для tasks 1-4 |
| 5 | Context (non-media factors confirm) | silent если nothing ambiguous |
| 6 | Summary + Diagnostics + Run | always shown |

Auto-detect делает 60-80% работы через расширенный variable classifier. Wizard спрашивает только F4 (task intent) и disambiguation там где auto-detect не уверен.

### 3. Variable Classifier extended

Расширяем `column_detection.py` до полной типизации:

- **13 target metric types** (sales_rub / sales_packs / revenue / profit / leads / registrations / subscriptions / applications / bookings / transactions / traffic / loyalty_cards / app_installs / custom + 1 fallback)
- **15 media format categories** (TV / Digital / OLV / Performance / Social / OOH / Print / Radio / Cinema / Аптечный OOH / Retail Media / Influencer / Email-CRM / Programmatic / Affiliates)
- **Signed control factors** (NEW category): competitor (negative-leaning), price/weather/macro (signed unconstrained)
- **Best-practice rules library** (warn-level): Performance→clicks, OLV→views, Display→impressions, TV TRP→приведённые, OOH→OTS, Mixed+monetary KPI→single mode recommended

Existing positive controls (distribution, trade_activity, promo_indicator) — preserved.

### 4. Signed factor support (math + UI)

**Backend:**
- `validator.py::CONTROL_PATTERNS` extended с signed categories
- Bayesian model — отдельные prior namespaces:
  - Media channels: LogNormal (positivity-constrained) — existing
  - Positive controls: HalfNormal — existing
  - Competitor: Normal с negative-leaning mean (μ=-0.5σ)
  - Signed (price/weather/macro): Normal zero-centered
- `decomposer.py` returns separate `signed_factor_contributions` field

**UI:**
- `WaterfallChart.svelte` extended для рендера negative bars (extension существующего production component)
- Insights текст: «Активность конкурентов забрала 11%, ваша Performance дала +31%, чистый эффект рекламы +20% сверх базы»

### 5. РФ Holiday Calendar Auto-Injection

**Silent auto-injection** 12 hardcoded РФ-events как control factor dummies — не спрашивается у user, происходит в Studio bundle stage:

- `holiday_newyear_preshop` (15-31 декабря)
- `holiday_newyear_postsale` (25 декабря - 8 января)
- `holiday_valentine` (1-14 февраля)
- `holiday_defender_day` (15-23 февраля)
- `holiday_march8` (1-8 марта)
- `holiday_may_holidays` (28 апреля - 9 мая)
- `holiday_russia_day` (11-12 июня)
- `holiday_back_to_school` (15 августа - 1 сентября)
- `holiday_unity_day` (3-4 ноября)
- `holiday_black_friday` (last Friday of November + weekend)
- `holiday_cyber_monday` (понедельник после Чёрной пятницы)
- `holiday_school_breaks` (4 окна школьных каникул / год)

Model подхватывает их как control factors (CONTROL_PATTERNS уже включают `holiday`). Customer customization (opt-out specific holidays, custom events) — откладывается в **v2.2.0 Quality of Life sprint**.

### 6. Diagnostics Panel (math validation surface)

Новый раздел в pipeline между Train и Decompose. Manager видит **traffic-light summary**, Expert разворачивает **full plots**.

- **Backtest (auto-runs in training):** default 4 months holdout (РФ-monthly стандарт) или 16 weeks для weekly grain. Auto-extend до 6-8 months если history ≥48 months. Reports MAPE, RMSE, R².
- **MCMC convergence (auto-runs):** R-hat / ESS traffic light:
  - 🟢 max R-hat < 1.05 AND min ESS > 400
  - 🟡 R-hat 1.05-1.10 OR ESS 200-400
  - 🔴 R-hat > 1.10 OR ESS < 200
- **Posterior predictive checks (PPC):** R² scatter + residual time series:
  - 🟢 R² > 0.85
  - 🟡 0.70-0.85
  - 🔴 < 0.70
- **Sensitivity tornado:** adaptive top-7 параметров (varied ±20%, ranked by |ΔROI|)

Expert mode разворачивает trace plots, ESS per parameter, posterior pairs, prior sensitivity table.

### 7. Multi-Scenario Comparison Page

Новая страница после Optimize, visible если в проекте ≥2 scenarios:
- **Multi-line continuation chart** с overlaid scenarios (лимит 5 на chart)
- **Comparison table:** Scenario × {Budget, Predicted KPI, CI 90%, % Uplift, Per-channel breakdown} (unlimited в таблице)
- **Diff analyzer auto-narrative:** «План B даёт +27.3% KPI при +40% budget vs Базовый»
- **Export:** CSV / Excel / PPTX

Component: `MultiScenarioPage.svelte` + `MultiScenarioChart.svelte` (extension `ContinuationChart`).

### 8. Forecast Continuation Chart (main visualization)

Reference visualization — Антон 2026-05-14 ("ПРОГНОЗ НА ОСНОВЕ МОДЕЛИ"):
- Historical actuals (solid)
- Model fit (solid)
- Forecast scenarios (solid / dotted) с endpoint labels
- **CI ribbons 90%** (Aurora Bayesian)
- Vertical divider на cutoff
- Clickable legend, hover tooltip

Component: `ContinuationChart.svelte` (NEW).

### 9. 5-th Task Profile: `forecast_planned_activities`

Customer задаёт собственный план активностей (Excel или manual entry), модель прогнозирует:
- Adstock continuation от исторического tail
- Hill saturation applied
- Per-period KPI projection с CI

Task profile YAML: `04_Task_Profiles/aurora_optimize/forecast_planned_activities.yaml` (NEW).

Output: таблица + continuation chart + optional comparison «мой план vs Aurora-optimized».

### 10. Reuse существующих наработок

Audit 2026-05-14 показал что **5 features уже в коде, 3 partially готовы**:
- **Save/Load обученной модели** — ✅ 100% reuse (`engines/persistence.py`)
- **Executive summary SCQAR** — ✅ 100% reuse (`aurora_html/sections.py:363-490`)
- **10 KPI types полностью** — ✅ 100% reuse (`utils/kpi_registry.py` + KPISelector)
- **Waterfall chart** — ✅ 95% reuse, +UI extension для negative bars
- **Signed factor backend partially** — ⚠️ 85% (control patterns есть, нужна priors specialization)
- **Export model JSON** — ⚠️ 60% (pickle ready, нужна JSON serialization layer, ~0.5-1d)

### 11. Granularity Default = Monthly (РФ-стандарт)

РФ MMM работает преимущественно с monthly grain. Default UX:
- Wizard plan inputs default unit = «месяц»
- Backtest holdout default 4 months
- Forecast horizon default 12 months
- Weekly grain — auto-adapt если data signature weekly

Saved as feedback memory: `feedback_rf_mmm_monthly_default.md`. Кандидат для INV-31 в `aurora-meta/ENGINEERING_INVARIANTS.md`.

---

## Rationale

### Почему мы отменяем ADR-015

ADR-015 §3 «UX argument: Progressive Simplicity — юзер должен думать в терминах данных» — справедливо в принципе, но **не реализовано**. Per-channel selector требует мышления «бюджет или показы для канала X» — это **больше** решений (N штук), чем «ROI или Эффективность для проекта» (одно).

ADR-015 §A. Alternatives Considered отвергло вариант «B. Убрать Вручную, оставить 2 explicit toggle» с обоснованием «теряем гибкость mixed-units». Это **верно технически, неверно продуктово**: mixed-units нужен <15% случаев и не имеет place в Manager mode. Plus текущий approach даёт хуже UX в 85% случаев ради 15% case.

ADR-015 §3 «Industry standard» — все цитированные libraries (PyMC-Marketing, Robyn, Lightweight MMM, Jin 2017) — analyst-driven tools. Operating context: $500k Nielsen engagement с командой эконометристов калибрующих unit_cost через rate-cards. Aurora ICP — self-service для агентского аналитика без эконометрической экспертизы PhD-уровня.

ADR-015 не учитывал что **unit_cost conversion error** (10-25%) добавляется к ROI uncertainty. Это методологический недостаток derived-mode подхода для self-service.

### Почему именно эта архитектура

1. **Wizard-driven flow** match'ит positioning «эконометрист доступен маркетологу» лучше чем catalog templates. Programma «задаёт правильные вопросы», menedger не «выбирает карточку».

2. **Auto-detect делает 60-80%** — Manager делает minimal cognitive work.

3. **Signed factors** закрывают methodological gap который senior эконометрист агентства first thing замечает (Антон 2026-05-13 пример: «у нас такого ещё не видел, почему?»).

4. **Cross-product escape в Expert mode** (не redirect) — pragmatic для раннего customer base где Launch / Brand / Trade & Pricing не all installed.

5. **РФ-monthly default** — match'ит local media planning convention. US/EU weekly default — wrong для нашего рынка.

6. **Reuse existing 60%+ кодовой базы** — сжимает scope с 7-9 недель до ~4.5-5 недель.

---

## Alternatives Considered

| # | Альтернатива | Отвергнуто потому что |
|---|---|---|
| **A** | Keep ADR-015 derived mode, добавить prominent warning при mixed detection | Косметика, root cause не решается. UnitCostsPanel остаётся в default flow, B4-type bugs продолжают быть возможны |
| **B** | 2 explicit modes без wizard (мой первый draft v1.3.3) | Полу-шаг: упрощает mode selection, но KPI selector с 10 опциями + плановые inputs всё ещё громоздкие. Не решает «эконометрист рядом» positioning |
| **C** | Smart default из data analysis (auto-derive mode на основе типов колонок без user input) | Магия для customer = trust issue («почему так?»). Edge cases (50/50 spend mix?). False confidence при auto-detection ошибках. Plus все равно нужен explicit override → возврат к 2 кнопкам |
| **D** | TemplateGallery (catalog шаблонов «Фарма OTC / FMCG / Ретейл» на старте) — мой второй draft | Категория вторична, задача первична (Антон 2026-05-14: БАДы / OTC / FMCG / косметика имеют одинаковую бизнес-логику, разделение их шаблонами создаёт redundancy + ICP confusion) |
| **E** | Ship только ROI mode | Антон явно требует оба режима. ~15-20% customers (бренды с агентскими скидками / бартером) теряют ability работать с продуктом |
| **F** | Mode в Project Settings (не в Validate) | Mode концептуально связан с KPI selection, естественное место = Validate. Settings location создаёт discoverability issue («где менять режим») |

**ВЫБРАНО:** ScenarioWizard + Explicit 2 modes Manager + Expert mixed opt-in + signed factors + diagnostics + multi-scenario page + monthly default.

---

## Consequences

### Positive

- **Cognitive load на Manager minimized** — auto-detect делает 60-80%, wizard 3-7 шагов
- **Methodological completeness** — signed factors, backtest, MCMC, PPC, sensitivity tornado закрывают gap vs Robyn / PyMC-Marketing
- **Cross-product UX consistency** — wizard pattern переносится на Launch Planner / Brand Tracker / Trade & Pricing
- **Backward compat preserved** — existing projects with mixed perChannelInput auto-migrate в Expert mode + toast notification
- **Sales pitch усиливается** — от «дешевле Nielsen» к «полнофункциональный Bayesian MMM с agency-grade workflow + Methodology Certificate verifier»
- **РФ-первый positioning** через monthly default + 12 hardcoded РФ holidays + соответствие local media planning convention
- **Соответствие positioning slogan** «high-end эконометрист доступен маркетологу»

### Negative

- **ADR-015 supersede** требует UX migration logic для existing v1.3.x customers (auto-Expert + toast)
- **Существенный refactor** ValidateStepV13 (~600 LOC) + новые компоненты (~12 NEW files)
- **Variable classifier расширение** — нужны тесты на все 13 target types + edge cases
- **Signed factor priors** — math review нужен (negative-leaning vs unconstrained calibration)
- **РФ holiday hardcoded** — каждая категория клиента может иметь свою чувствительность; до v2.2.0 нет customization

### Neutral

- **Sidecar API contract** unchanged — все request fields те же, Manager mode заполняет согласованно
- **Bundle schema** additive (per ADR-017) — `analysisMode` field optional, default `'roi'`
- **Customer pricing** unchanged

---

## Implementation

### Backend (sidecar)

| File | Change |
|---|---|
| `sidecar/econometrica/utils/column_detection.py` | EXTEND — 13 target types + 15 media formats + signed controls |
| `sidecar/econometrica/utils/holiday_calendar_ru.py` | NEW — 12 РФ holidays generator |
| `sidecar/econometrica/utils/best_practice_rules.py` | NEW — soft-recommendation library |
| `sidecar/econometrica/engines/validator.py` | EXTEND `CONTROL_PATTERNS` для signed controls |
| `sidecar/econometrica/engines/modeler.py` | EXTEND — auto-inject holidays + signed factor prior namespaces |
| `sidecar/econometrica/engines/decomposer.py` | EXTEND — separate `signed_factor_contributions` output |
| `sidecar/econometrica/engines/json_export.py` | NEW — JSON model params export layer |
| `04_Task_Profiles/aurora_optimize/forecast_planned_activities.yaml` | NEW — 5-й task profile |
| `sidecar/econometrica/engines/backtest.py` | NEW — holdout validation (4 months РФ default) |
| `sidecar/econometrica/engines/sensitivity.py` | NEW — adaptive top-7 sensitivity tornado |

### Frontend (src/lib)

| File | Change |
|---|---|
| `src/lib/project-state.js` | + `analysisMode` store (default `'roi'`), `analysisObjective` alias for backward compat |
| `src/lib/wizard-state.js` | NEW — wizard state management + auto-detect orchestration |
| `src/lib/mode-defaults.js` | NEW — `detectExistingMode()`, `defaultPerChannelInput()`, `migratePreExpert()` |
| `src/lib/components/pipeline/ScenarioWizard.svelte` | NEW — main wizard orchestrator |
| `src/lib/components/pipeline/wizard/Step*.svelte` | NEW — 6 step components |
| `src/lib/components/pipeline/AnalysisModeSelector.svelte` | NEW — 2 кнопки + Expert 3-я |
| `src/lib/components/pipeline/AppliedModeSummary.svelte` | NEW — replaces PerChannelInputSelector в Manager |
| `src/lib/components/pipeline/DiagnosticsPanel.svelte` | NEW — traffic-light + Expert expand |
| `src/lib/components/pipeline/ContinuationChart.svelte` | NEW — main forecast viz |
| `src/lib/components/pipeline/MultiScenarioPage.svelte` | NEW — comparison page |
| `src/lib/components/pipeline/MultiScenarioChart.svelte` | NEW — extension continuation chart |
| `src/lib/components/pipeline/SensitivityTornado.svelte` | NEW — adaptive tornado |
| `src/lib/components/pipeline/PPCScatter.svelte` | NEW — actual vs predicted |
| `src/lib/components/pipeline/ValidateStepV13.svelte` | REFACTOR — wizard как entry, AppliedModeSummary, conditional UnitCostsPanel |
| `src/lib/components/pipeline/WaterfallChart.svelte` | EXTEND — negative bars для signed factor contributions |
| `src/lib/components/pipeline/UnitCostsPanel.svelte` | UPDATE — conditional render (only Expert + mixed + physical) |
| `src/lib/components/pipeline/PerChannelInputSelector.svelte` | UPDATE — hidden в Manager mode |
| `src/lib/components/IntroTutorial.svelte` | UPDATE — slide 8 переписан под new mode logic |

### Migration logic

- Existing project pure-monetary → Manager ROI mode (silent)
- Existing project pure-physical → Manager Effectiveness mode (silent)
- Existing project mixed → auto-Expert mode + toast «Включён Expert mode. Проект использует смешанный режим единиц.»
- New project → Manager ROI default

### Phase plan (revised после audit, 2026-05-14)

| Phase | Duration | Deliverable |
|---|---|---|
| Pre-flight | ~1.5 дня | Address 2 BLOCKER + 17 HIGH findings из `AUDIT_RESULTS_v1.md`. См. `PRE_FLIGHT_FIXES.md` |
| A — Backend foundation | ~1.5 недели | Variable classifier extended, holiday calendar, signed factors backend, store changes, forecast profile, JSON export, backtest, sensitivity, persistence diagnostics cache |
| B — Wizard + ValidateStep refactor | ~1.5 недели | ScenarioWizard + AnalysisModeSelector + AppliedModeSummary + wizard state lifecycle + analysisObjective alias migration |
| C — Diagnostics & visualizations | ~1 неделя | DiagnosticsPanel + ContinuationChart + MultiScenarioChart + SensitivityTornado + PPCScatter + WaterfallChart extension |
| D — Multi-scenario page + integration | ~0.75 недели | MultiScenarioPage + DiffAnalyzer + ScenarioExport + edge cases (palette, accessibility, label overlap) |
| E — Audit + ship | ~1.25 недели | Re-audit pass + math review priors + Methodology Certificate update + verifier coord + 3 pilot scenarios + NSIS build + tag v2.0.0 |

**Total: ~5.75-6.5 недель** (с 0.5-1 week buffer = реалистично 6-7 недель).

Original 4.5-5 недель оценка была under-estimated (audit B1, L2). Pre-flight cycle добавляет +1.5 дня но предотвращает 3-5 дней rollback / rework в середине execution.

---

## Update protocol для ADR-015

ADR-015 header обновляется:
```
Status: Superseded by ADR-019
Date: 2026-05-12 (original) / 2026-05-14 (superseded)
```

Body ADR-015 preserved для historical reference (учим на ошибках).

---

## Pre-flight Checklist (per ENGINEERING_INVARIANTS §6)

- ✅ INV-04 — ADR supersession with explicit user re-confirmation (Антон 2026-05-13, multiple подтверждения)
- ✅ INV-15 — Adapter wiring path completeness (wizard state через `wizardState` store без breaks)
- ✅ INV-17 — Single source of truth (`analysisMode` как SSOT для mode)
- ✅ INV-25 — Dual-mode UX (Manager 2 кнопки + Expert 3-я)
- ✅ INV-30 — MMM single-unit preference (Manager 2 clean modes)
- ⏳ INV-08 — Run pytest before declaring done (Phase E)
- ⏳ INV-01 — Schema migration full propagate (Phase A → Phase B одна волна)

---

## References

- `docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md` — детальная implementation спецификация
- `docs/v2_0_0_design/GAP_ANALYSIS_v1.md` — comparative analysis vs Robyn / LightweightMMM / PyMC-Marketing / Nielsen
- `docs/v2_0_0_design/V2_1_0_PLUS_ROADMAP.md` — что после v2.0.0
- `docs/v2_0_0_design/INTERVIEW_NOTES.md` — interview материал
- `aurora-meta/ENGINEERING_INVARIANTS.md` — cross-product invariants INV-04, 15, 17, 25, 30
- `aurora-meta/PORTFOLIO.md` — product line context
- `aurora-meta/DECISIONS/ADR-013` — Aurora Econometrica positioning slogan
- ADR-015 (superseded) — Mode as Derived State
- ADR-016 (preserved) — KPI Kinds Binary Semantics
- `feedback_authority_argument_context_check.md` — почему «лидеры рынка делают X» был misapplied
- `feedback_technical_vs_product_question_disambiguation.md` — technical vs product question
- `feedback_rf_mmm_monthly_default.md` — РФ-monthly default cross-product convention
