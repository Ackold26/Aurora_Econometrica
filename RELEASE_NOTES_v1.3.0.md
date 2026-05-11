# Aurora AI Econometrica MMM Optimizer v1.3.0 — Release Notes

**Release date:** TBD (pending pilot validate Кагоцел + Венарус)
**Type:** minor release (v1.2.0 → v1.3.0)
**Base:** commit `d383636` (v1.2.0)
**Feature branch:** `feat/v1.3.0-next-gen`

## Highlights

Aurora MMM Optimizer становится **продуктом следующего поколения** — доступным не-эконометристам через прогрессивную простоту и встроенную систему обучения. Результат high-end эконометриста теперь достижим обычным маркетологом.

## Ключевые нововведения

### 1. KPI семантика — поддержка любых считаемых метрик

В v1.2.0 единственный KPI = sales_rub (выручка в рублях). v1.3.0 поддерживает **8 KPI types в 2 семантических классах** (ADR-016):

**Monetary KPIs** (target = ₽):
- `sales` — выручка (default)
- `revenue` — доход
- `profit` — прибыль

**Count KPIs** (target = считаемая метрика):
- `sales_packs` — продажи в штуках / упаковках
- `leads` — лиды / заявки
- `registrations` — регистрации / sign-ups
- `loyalty_cards` — выданные карты лояльности
- `subscriptions` — подписки (MRR-based)
- `app_installs` — установки приложений
- `count_custom` — любая считаемая метрика

Для каждого count KPI юзер задаёт **value_per_count_unit** (маржа на упаковку / ценность лида / MRR на подписку / etc.) — это позволяет считать **CPU vs ценность** и давать вердикты «убыточный/окупаемый» в правильной семантике.

### 2. Mode = derived state (Variant C)

В v1.2.0 юзер выбирал mode (ROI / Эффективность / Вручную) explicit toggle. v1.3.0 переводит mode в **derived state** (ADR-015):

1. Юзер выбирает **KPI** на шаге Валидация.
2. Юзер для каждого канала выбирает **input metric** (бюджет ₽ или физический контакт).
3. Mode выводится автоматически:
   - все ₽ → mode = ROI
   - все физ. контакты → mode = Эффективность
   - смешанные → mode = Вручную

Совпадает с industry standard (Robyn, PyMC-Marketing, Lightweight MMM, Jin et al. 2017). Senior эконометристы могут включить Expert Mode override в Settings.

### 3. Goal-Seek optimization (новый режим оптимизации)

В v1.2.0 только **forward** оптимизация: «дан бюджет → max продажи». v1.3.0 добавляет **Goal-Seek** (inverse) (ADR-014):

**Forward:** «куда вложить мой бюджет, чтобы получить максимум?»
**Goal-Seek:** «нужно достичь продаж X — сколько потратить?»

Алгоритм: **бисекция** по бюджету в безопасном коридоре. Performance: < 1s на 7 каналах × 156 наблюдений.

Posterior CI на требуемый бюджет — через **Delta method** (linearization). Phase B расширит до full posterior re-bisection в Expert Mode.

### 4. Safe corridor — math-валидные границы

В v1.2.0 слайдер бюджета можно было сдвинуть на ±500% — модель экстраполировала за пределы observed range. v1.3.0 вводит **safe corridor** (ADR-014):

**MVP формула per канал:**
```
X_i^lo = max(P5_observed, 0.5 · µ_i)
X_i^hi = min(P95_observed, 1.5 · µ_i)
```

Литература: Robyn `0.5x-1.5x` default, Hanssens et al. 2003 (RMSE экстраполяции растёт 2-3×), PyMC-Marketing posterior predictive bounds.

**UX:** Три zones на всех слайдерах:
- 🟢 Зелёная (внутри corridor) — модель валидна
- 🟡 Жёлтая (±10% от границ) — extrapolation warning
- 🔴 Красная (>10% за пределами) — кнопка заблокирована

### 5. KPI-aware вердикты и метрики

Все user-facing тексты теперь KPI-aware (ADR-016):

| KPI=monetary | KPI=count |
|---|---|
| ROI колонка | CPU колонка (₽/единицу) |
| «Глубоко убыточный (ROI < 0.5)» | «Глубоко убыточный (CPU > 2× ценности)» |
| «Лучший ROI: X — 1.8×» | «Самый дешёвый: CPU Y ₽/единицу» |
| Слайдер «бюджет → выручка» | Двойной слайдер «бюджет → штуки» + «бюджет → CPU» |

В режиме Эффективность ROI / CPU columns **полностью убраны** — главная метрика **sales share %** (единственная безразмерная, сравнимая между каналами с разными физ. единицами).

### 6. Educational system — обучение встроено

Новая система обучения для не-эконометристов (Stage 4):

- **Глоссарий 20 терминов** — Hill, adstock, mROI, ROI, CPU, MCMC, R-hat, Bayesian, posterior, safe corridor, и т.д. С cross-links между терминами.
- **«Зачем этот шаг?» панель** на каждом из 6 шагов pipeline. Раскрывающаяся секция с 4 блоками: что мы делаем / зачем нужно / на что обратить внимание / что будет дальше.
- **Inline tooltips** на ключевые поля с linkом в глоссарий.
- **Intro Tutorial** — 5-минутный walkthrough «Что такое MMM» перед первым проектом (8 slides). Skippable.
- **Glossary Panel** — раскрывающаяся боковая панель с поиском (Ctrl+K shortcut).

### 7. Bundle schema v1.3 — additive, no migration

Per ADR-017, schema bump НЕ делается. v1.2 bundles читаются с **defaults injected in memory**. Новые поля (`kpi_kind`, `per_channel_input`, `derived_mode`, `value_per_count_unit`) сохраняются при следующем save.

Migration tool НЕ нужен. Старые проекты Кагоцел / Венарус открываются без UI изменений. Default treatment: `kpi_kind='monetary'` + per-channel input all `monetary` → derived mode = ROI (соответствует прежнему явному выбору).

## Backend changes

### New modules

- `sidecar/econometrica/utils/kpi_registry.py` — расширен с `kpi_kind` field + 7 count KPIs + helpers.
- `sidecar/econometrica/utils/mode_inference.py` — NEW. `derive_mode`, `derive_mode_with_explanation`.
- `sidecar/econometrica/utils/column_detection.py` — NEW. Auto-classify RU/EN columns (separator-aware regex).
- `sidecar/econometrica/optimize/` — NEW package:
  - `bounds.py` — `compute_safe_corridor` (MVP formula).
  - `inverse.py` — `optimize_inverse` (bisection-based).
  - `auto_price.py` — `detect_value_per_count_unit`.
- `sidecar/econometrica/engines/verdicts.py` — NEW. `compute_verdict_kpi_aware` unified dispatch.

### New endpoints

- `POST /optimize/corridor` — safe corridor compute
- `POST /optimize/inverse` — Goal-Seek
- `POST /project/auto_price` — auto-detect value_per_count_unit
- `POST /project/save_kpi_settings` — persist KPI metadata + derived mode

### Updated

- `sidecar/econometrica/engines/persistence.py` — `_inject_v13_defaults()` для backward compat.
- `src-tauri/src/commands/econometrica.rs` — 4 new Tauri commands (econ_safe_corridor, econ_optimize_inverse, econ_auto_detect_price, econ_save_kpi_settings).

## Frontend changes

### New components

- `src/lib/components/pipeline/KPISelector.svelte` — 10 KPI cards (grouped).
- `src/lib/components/pipeline/ValuePerCountUnitInput.svelte` — для count KPIs.
- `src/lib/components/pipeline/PerChannelInputSelector.svelte` — radio table.
- `src/lib/components/pipeline/ModeDerivedExplanation.svelte` — plain-text объяснение.
- `src/lib/components/pipeline/ValidateStepV13.svelte` — orchestrator 4-substep flow.
- `src/lib/components/pipeline/CorridorSlider.svelte` — reusable slider with safe zones.
- `src/lib/components/pipeline/OptimizeGoalSeek.svelte` — Goal-Seek UI.
- `src/lib/components/pipeline/GoalSeekResultCard.svelte` — result display.
- `src/lib/components/pipeline/WhyThisStep.svelte` — раскрывающаяся секция.
- `src/lib/components/pipeline/InlineHelpIcon.svelte` — (i) tooltip.
- `src/lib/components/IntroTutorial.svelte` — 8-slide MMM intro.
- `src/lib/components/GlossaryPanel.svelte` — раскрывающаяся боковая панель.

### Updated

- `src/lib/project-state.js` — 7 new v1.3 stores (kpiKind, kpiType, perChannelInput, derivedMode, valuePerCountUnit, valuePerCountUnitSource, useDerivedModeUX).
- `src/lib/components/pipeline/DecomposeStep.svelte` — KPI-aware metric column.
- `src/lib/components/pipeline/OptimizeStep.svelte` — Forward / Goal-Seek toggle.
- `src/routes/pipeline/+page.svelte` — feature flag для ValidateStepV13.
- `src/lib/components/OnboardingOverlay.svelte` — step 1 обновлён.

### New JS modules

- `src/lib/glossary.js` — 20 critical terms data.
- `src/lib/mode-derivation.js` — frontend mirror of backend.
- `src/lib/contextual-help.json` — content для 6 шагов.

## Documentation

- `docs/adrs/ADR-014_safe_corridor_bounds.md`
- `docs/adrs/ADR-015_mode_as_derived_state.md`
- `docs/adrs/ADR-016_kpi_kinds_binary_semantics.md`
- `docs/adrs/ADR-017_bundle_schema_v13_additive.md`
- `docs/adrs/ADR-018_migration_safety_protocol.md`
- `docs/audits/KPI_TEXT_AUDIT.md`
- `docs/audits/REPORT_KPI_AUDIT.md`
- `docs/audits/EDUCATIONAL_TEXTS_AUDIT.md`
- `docs/GLOSSARY_TERMS.md`
- `docs/PERFORMANCE_BUDGET.md`
- `REFACTOR_PLAN_v1.3.0.md`

## Test coverage

- **950 unit tests pass** (929 v1.2 baseline + 21 new v1.3-specific) + 5 known skips
- **0 regressions** на pickle compat (26 tests), decomposer invariants, ROI verdict
- **0 svelte-check errors** на frontend (151 pre-existing warnings unchanged)
- **Cargo check OK** для Rust IPC

### New v1.3 tests
- `tools/test_kpi_registry_v13.py` (29 tests) — kpi_kind + count KPIs + helpers
- `tools/test_mode_inference.py` (19 tests)
- `tools/test_column_detection.py` (24 tests) — RU/EN regex
- `tools/test_safe_corridor.py` (10 tests)
- `tools/test_auto_price.py` (11 tests)
- `tools/test_verdicts_kpi_aware.py` (19 tests)

## Migration guide

### От v1.2 к v1.3 (юзеры)

Никаких действий не требуется. Старые `.aurora` bundles открываются с default treatments:
- KPI = `sales` (monetary)
- Все каналы как `monetary` input
- Derived mode = ROI (соответствует прежнему явному выбору)

### От v1.2 к v1.3 (разработчики)

- `analysisObjective` store deprecated → use `derivedMode` + `kpiKind` + `perChannelInput`
- `objective-engine.js::applyObjectiveToColumns` → use `mode-derivation.js::deriveMode`
- `compute_roi_verdict` старая работает для monetary; для count — `compute_verdict_kpi_aware`

## Pending integration (Stage 5 final)

- IntroTutorial — invoke на первом запуске свежей установки
- GlossaryPanel — global trigger в header + Ctrl+K shortcut
- WhyThisStep — embedded в каждом из 6 шагов с content из contextual-help.json
- Mastery toggle в Settings (скрыть подсказки)
- 4 формата отчётов KPI/mode-aware (Reports Stage 3 Phase B)

Эти задачи планируются как hotfixes v1.3.1 после ship v1.3.0.

## Известные ограничения

1. **Goal-Seek MVP** — линейная Delta method posterior CI. Полная re-bisection на posterior samples — Phase B.
2. **Reports не полностью KPI-aware** — HTML/PPTX/XLSX используют ROI labels even for count KPI. Stage 3 Phase B исправит.
3. **Awareness KPI** — помечен `out_of_scope_v13` в registry. v1.3 enhancements не применяются. Phase B Aurora Brand Tracker.
4. **value_per_count_unit auto-detect** — только для пары `sales_rub / sales_packs`. Для leads / registrations нужен manual input.

## Pilot validate plan

- **Кагоцел РФ ММХ 1105-26** — KPI=monetary, full pipeline Forward + Goal-Seek.
- **Венарус** — KPI=monetary, regression на live data.
- После 2 pilots sign-off — tag `v1.3.0` + ship NSIS installer.

## Acknowledgments

- Антон (product direction, методологические решения).
- Маша маленькая (implementation, testing, ADRs).
- Маша небесная (cross-product coordination, Brand Tracker scope).
- Bayesian MMM community: Robyn (Meta), PyMC-Marketing, Jin et al. (2017) Google paper.
