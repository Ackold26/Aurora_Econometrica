---
tags: [session, compressed]
type: session
updated: 2026-05-02
---

# Quick Reference

Сессия live-test polish v1.1.0 (Trust 3 + D.1+D.2+D.3+F + audit) — выявлено 14 issues на Kagocel data, все закрыты в commit `6460a24`. Затем — детальное планирование Phase 2 (Forecast Horizon / Planning Mode) с критическим self-audit (M1-M8 math, P1-P5 perf, U1-U11 UX, F1-F4 failure modes), ~13 dev-days estimate. v1.2.0 = combined Trust 3 + Planning Mode (Phase 2 ПЕРЕД customer ship).

**Topic:** live-test-polish-and-phase2-plan
**Key files:**
- Plan: `C:\Users\ackol\.claude\plans\phase-2-dapper-cray.md` (~41KB)
- Plan copy: `C:\Users\ackol\Desktop\PHASE_2_PLAN_forecast_horizon.md`
- Next session prompt: `C:\Users\ackol\Desktop\NEXT_SESSION_PROMPT_phase2_forecast_horizon.md`
- Status: `D:/Docs/Aurora_Ai/Awareness_KPI_track_Weibull_Adstock.md`
- Memory: `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_v1_1_0_live_test_polish.md`
- Memory: `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_forecast_horizon.md`

**Status:**
- ✅ commit `6460a24` SHIPPED (14 файлов, +617/-113), pushed `math-fix-v1.0.13`
- ✅ Phase 2 plan written + reviewed + premium UX additions
- ⏳ Phase 2.0 math audit — блокирующая prerequisite для следующей сессии
- ⏳ v1.2.0 ship gate (Phase 2.8) — все Phase 2 + manual QA + NSIS + GH Release

---

## Learnings

### Architectural insights

1. **Decoupling training horizon от forecast horizon** — fundamental MMM problem. Aurora's `n_periods = len(df)` (optimizer.py:329) hard-pegs обе роли (Hill-mean calibration + forecast scaling). Phase 2 thesis: rename `train_n_periods` (frozen) + add `forecast_n_periods` (config input).

2. **Backend math для per-period averaging уже правильная** в optimizer.py:483-504 (`x_avg_raw = x_native / n_periods` → Hill → `total += beta * sat * n_periods`). Phase 2 lab — substitute `n_periods` для forecast scaling, keep training adstock kernel frozen (Option A locked pending math audit).

3. **scenario.py:117-132 already supports horizon mismatch implicitly** — single-period plans padded к training. Phase 2 reuses + adds metadata.

4. **conformal.py:11, 278 уже знает про seasonality** — exchangeability violated с trend/seasonality. Phase 2 plan должен extend этот acknowledgment в forecast UI.

5. **Existing posterior_propagation.py helpers REUSE**: `compute_ci_hdi` (proven), `compute_train_adstock_mean_samples` (для drift detection extension). Не переписывать.

### Critical bugs found in live-test (commit 6460a24)

1. **modeler.py UnboundLocalError для `hierarchical_priors_summary`** — pre-existing с Trust 3 commit. Переменная использовалась на line 810 (diagnostics dict), определялась только на line 852 (posterior extraction). При use_hierarchical=True крашил весь train. Lesson: synthetic fixtures должны cover **все ветки** use_hierarchical=True/False — не triggered без правильного ≥2/≥2 split.

2. **ImportStep nRows fallback** — `nRows = shape?.rows ?? previewRows.length` (20 — preview limit). При reload проекта shape=null → fallback к 20 → recommendOls=true → OLS вместо Bayesian для 31-row datasets. Fix: убран fallback на preview + restore shape из persisted store.

3. **ColumnMapper Insights ↔ Mapper sync broken** — hash key только из имён, не учитывал role mutations. InsightsPanel меняла role='unused' но mapping не re-init. Fix: hash включает (name, role) + init из columns[i].role priority.

4. **ChannelCategoriesPanel setCategory не обновлял UI** — getCategory() использовал get(channelCategories) (императивный read без подписки). Fix: reactive `$derived.by(resolvedCategories)`.

### UX learnings

1. **Honest UX disclosure > emotional language** — «низкая уверенность» воспринималось как «не доверяй модели». «Широкий ROI-интервал» — нейтральное техническое описание + tooltip. Same для divergences (proportion thresholds Stan-standard, не absolute count).

2. **Backend-frontend single source of truth для critical metrics** — frontend approximations OK для real-time preview, но финальные deliverables ВСЕГДА из backend. BudgetOptimizer atOptimum detection: `channelBudgets ≈ optimal_spend` (1% tolerance) → use backend `expected_lift_pct`, иначе frontend approx с бейджем «≈ приблизительно».

3. **Theme-adaptive contrast обязателен** — hardcoded rgba(255,255,255,…) почти невидим в light/fun темах. Use `color-mix(in srgb, var(--text-primary) X%, transparent)` для consistent subtle contrast независимо от theme background.

4. **MMM training horizon ≠ planning horizon** — fundamental. Aurora сейчас Analyst tool, planner нужен Planning Mode. Phase 1 ship — honest disclosure banner, Phase 2 — full architectural feature.

### Phase 2 critical review findings (M/P/U/F)

**M. Math correctness gaps (8):**
- M1 Adstock warmup для sharp-start forecasts (Robyn issue #781): первые ~1/(1-decay) periods underperform без carryover seed
- M2 Seasonality bias по позиции старта (Q1 vs Q3 starts give different per-period saturation)
- M3 unit_costs scaling в forecast (media inflation 8-15%/year)
- M4 Posterior uncertainty underestimated в extrapolated zones (epistemic inflation γ=0.3)
- M5 Hierarchical priors interaction с extreme forecasts (shrinkage может underestimate top performer)
- M6 Stationarity hard cap tightened 5× → 2× (более consistent с MMM literature)
- M7 Hill calibration boundary tiered p95/p99 (not just single threshold)
- M8 `adstock_mean_posterior` stale anchor при extreme budgets (drift detection extends к adstock mean ratio)

**P. Performance (5):**
- P1 CI propagation только AFTER convergence, не in objective function
- P2 REUSE `compute_train_adstock_mean_samples` (existing)
- P3 Single pickle bump 1.3 → 2.0 (batch для known future phases)
- P4 Scenarios в file-system, not localStorage (project portability)
- P5 forecastConfig reset при смене проекта (effect on activeProjectId change)

**U. Premium UX gaps (11):**
- U1 Smart mode default detection (fresh train → Analyst, 7+ days → Planner pulse)
- U2 Plain-language layer (no posterior/horizon jargon)
- U3 Decision support panel (P10 risk-averse, P50 average, P90 bull case)
- U4 Premium loading с progress + cancel + queue recovery
- U5 Quality Stamp Badge (8 quality checks expandable)
- U6 On-demand math view modal (KaTeX lazy-loaded)
- U7 Animation polish (cross-fades, slide-ins, ribbon fades)
- U8 First-time Planner experience (3-step interactive walk-through)
- U9 Result interpretation messaging (sticky summary с decision support)
- U10 Scenario sharing (Phase 2.5: URL encoding)
- U11 Aurora Suite branding alignment

**F. Failure modes (4):**
- F1 Tiered fallback при math audit failure
- F2 «No-absolute mode» когда все каналы в drift critical (proportions only)
- F3 Posterior samples missing → P50 only с note
- F4 Multiple gates compose → один умный summary banner с приоритетом

---

## Decisions

### Live-test session decisions

1. **Engine selector UI** — 2-cards layout (Bayesian | OLS) с подсветкой выбранного, не один блок
2. **ChannelCategoriesPanel** — swap order (имя канала первое), убран % (manual=100% не несёт информации), mixed между brand/perf
3. **Verdict suffix** — «(низкая уверенность)» → «(широкий ROI-интервал)» (нейтральная формулировка)
4. **Divergences thresholds** — proportional (Stan/PyMC standard) вместо absolute count: <0.5% Низкая, 0.5-2% Несколько, 2-5% Заметно, ≥5% Много
5. **Banner показывает % дивергенций** в дополнение к count: «9 (0.06% от 16000 draws)»
6. **ROI/CI на Train этапе** — placeholder «→ После декомпозиции» вместо confusing «—x» / «[?, ?]»
7. **BudgetOptimizer backend lift%** — atOptimum detection (1% tolerance) → use backend authoritative value, иначе frontend approx с visible бейджем «≈ приблизительно»
8. **ResponseCurves fullscreen** — wrap в ExpandableCard как Decompose. Точки draggable строго на линии (curveResponseAt вместо локальной Hill)
9. **Per-group sliders polish** — reset button + информационный блок «Типичные сценарии» (4 примера включая Lock+Lock=0% lift)
10. **Planning horizon disclosure** — honest banner с 4 пунктами guidance (доли валидны / абсолюты делить / ≥ training granularity / KPI % training-scaled)

### Phase 2 design decisions (Антон 2026-05-02)

| Decision | Choice | Rationale |
|---|---|---|
| Order vs v1.1.0 customer ship | **Phase 2 ПЕРЕД v1.1.0 ship** | Combined v1.2.0 release: Trust 3 + Planning Mode together. Customers сразу получают full feature set |
| Scenario library scope | **Minimum viable** (~150 LOC) | Extend ScenarioPlayground, save + 1-on-1 compare. Full library (3+ side-by-side, parallel coords) → Phase 2.5 |
| Variable per-period budgets (Q1/Q2/Q3/Q4) | **Defer к Phase 2.5** | Math complexity high (Hill saturation non-linear in time-varying x), нужен synthetic backtest |
| Adstock kernel math | **Hybrid: investigate further** | Phase 2.0 math audit (1.5 days) с synthetic test cases prior к lock decision. Option A (freeze training) vs Option B (recompute) |

### Premium UX targets (locked in Phase 2 plan)

- Plain-language layer (glossary translation table)
- Smart mode default detection
- 3-step interactive Planner onboarding (first-time only)
- Quality Stamp badge (8 quality checks)
- On-demand math view (KaTeX lazy-loaded ~280KB only on modal open)
- Animation polish: cross-fade Analyst↔Planner, drift slide-in, ribbon fade
- Decision support messaging (P10/P50/P90 → risk-averse/average/bull case)
- Result interpretation sticky panel post-optimize

### Math correctness gates (consolidated)

- forecast_periods ≥ 1 integer (reject 400)
- forecast_periods > train_n × 2 (reject 400 — tightened from 5)
- forecast_periods > train_n × 1.5 (warn proceed)
- Per-channel forecast_avg / train_avg ≥ 3.0 OR ≤ 0.3 (drift warn)
- Per-channel forecast_adstock_avg / train_adstock_mean ≥ 3.0 (critical extrapolation)
- Hill x_norm > p95 (yellow warn) / > p99 (red critical)
- Seasonality detected + start non-aligned (warn + suggest)
- Granularity confidence < 0.6 (force manual confirm)
- All channels in critical drift → NO-ABSOLUTE mode (proportions only)

---

## Pending

### Phase 2.0 — Math audit (1.5 days, BLOCKING)

**MUST complete before Phase 2.1 starts.**

1. Create `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md`
2. Synthetic test matrix 5×5 (forecast_periods × forecast_budget)
3. Compare Option A vs B vs ground truth (analytical Hill+adstock)
4. Test seasonality bias (Q1/Q3/Q4 starts)
5. Test hierarchical interaction
6. Lock decisions:
   - Adstock kernel approach (A or B)
   - Stationarity cap (1.5×/2×/5×)
   - Seasonality strategy (warning vs auto-correction)
   - Epistemic inflation γ factor

### Phase 2.1-2.8 — Implementation (sequential, ~11.5 days)

- 2.1 Backend math + helpers (2.5 days) — optimizer.py, forecast_validation.py, CI propagation
- 2.2 Backend API + Tauri shim (0.5 days) — OptimizeRequest extension + 2 new endpoints
- 2.3 Frontend Planning Mode UI core (3 days) — ForecastHorizonPicker, DriftPanel, mode toggle, P10/P90
- 2.4 Premium UX layer (1.5 days) — onboarding, QualityStamp, MathModal, Interpretation, Progress
- 2.5 Scenario library Min viable (0.5 days) — ScenarioPlayground extension
- 2.6 Reports (1 day) — HTML/PPTX/XLSX forecast sections
- 2.7 Tests (1 day) — unit + integration + pickle compat
- 2.8 QA + docs + release (1.5 days) — manual QA + methodology PDF + v1.2.0 ship

### v1.2.0 ship gate

- All Phase 2 tests PASS (162 baseline + ~60 new = ~222+/222+)
- Manual QA на 3 pickles (Kagocel, Венарус, MMX synthetic)
- Math audit doc finalized
- PLANNING_MODE_METHODOLOGY.md customer-facing PDF
- v1.2.0 NSIS build → GH Release → Supabase → rosst-updates
- Auto-update propagation verified

### Telemetry baseline (post-ship)

Track post-ship для 4 weeks:
- mode_toggle_count per project per session
- planner_mode_completion_rate (% reach «Оптимизировать» в Planner)
- scenario_save_rate
- math_modal_open_rate (engagement signal)
- 4-week review: если planner_completion < 30% → simplify defaults sprint

### Phase 3 (post v1.2.0)

- A1a awareness likelihood (logit-Normal + GaussianRandomWalk) — ~12-15h
- B2.2 PyTensor in-model Weibull adstock — ~10-15h
- A2 dual-posterior cached baseline — ~10-13h

---

## Files modified

### commit `6460a24` (live-test polish session) — 14 файлов, +617/-113

**Backend (Python sidecar):**
- `sidecar/econometrica/engines/modeler.py` — UnboundLocalError fix (early init `hierarchical_priors_summary` line ~701)
- `sidecar/econometrica/engines/decomposer.py` — «низкая уверенность» → «широкий ROI-интервал»

**Frontend (Svelte):**
- `src/lib/components/pipeline/BudgetOptimizer.svelte` — backendLiftPct prop, atOptimum derived, «≈ приблизительно» бейдж
- `src/lib/components/pipeline/ChannelCategoriesPanel.svelte` — swap order, убран %, theme-adaptive contrast, mixed между brand/perf, hint расширен
- `src/lib/components/pipeline/ChannelTimeline.svelte` — highlight active series в tooltip (ECharts mouseover + dispatchAction)
- `src/lib/components/pipeline/ColumnMapper.svelte` — hash key (name, role), init из columns[i].role priority
- `src/lib/components/pipeline/ConvergenceDashboard.svelte` — % дивергенций в banner
- `src/lib/components/pipeline/DecomposeStep.svelte` — verdict tooltip explanation
- `src/lib/components/pipeline/ExpertDecomposePanel.svelte` — verdict tooltip explanation
- `src/lib/components/pipeline/ExpertModelPanel.svelte` — divergences proportion thresholds, ROI inline placeholder, % display
- `src/lib/components/pipeline/ImportStep.svelte` — 2-cards engine selector, nRows fallback fix, shape restore из store
- `src/lib/components/pipeline/OptimizeStep.svelte` — planning horizon banner, per-group reset, сценарии instructions, ResponseCurves fullscreen
- `src/lib/components/pipeline/ReportStep.svelte` — flex-wrap для info-toggle headers
- `src/lib/components/pipeline/ResponseCurves.svelte` — точки на линии (curveResponseAt fix)

### Plan/prompt artifacts (этой сессии)

- `C:\Users\ackol\.claude\plans\phase-2-dapper-cray.md` — Phase 2 plan (~41KB)
- `C:\Users\ackol\Desktop\PHASE_2_PLAN_forecast_horizon.md` — copy на Desktop
- `C:\Users\ackol\Desktop\NEXT_SESSION_PROMPT_phase2_forecast_horizon.md` — следующая сессия prompt (~10KB)

### Memory updates

- `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_v1_1_0_live_test_polish.md` — created
- `~/.claude/projects/D--Docs-Aurora-Ai/memory/project_econometrica_forecast_horizon.md` — created (proposal)
- `~/.claude/projects/D--Docs-Aurora-Ai/memory/MEMORY.md` — index updated с 2 новыми priority entries
- `D:/Docs/Aurora_Ai/Awareness_KPI_track_Weibull_Adstock.md` — status updated

---

## Errors & workarounds

### Pre-existing bugs surfaced by правильные данные

1. **modeler.py UnboundLocalError** — был в коде с момента Trust 3 commit (5 дней до проявления). Без ≥2/≥2 brand/perf split не triggered. **Lesson:** synthetic fixtures должны cover все ветки use_hierarchical=True/False.

2. **ImportStep nRows preview fallback** — был в коде но triggered только при navigate-out + back-in (shape сбрасывается, previewRows persists). User тестировал реальный workflow → triggered.

3. **ColumnMapper hash key** — был sufficient для добавления/удаления каналов, но не для role mutations. Triggered InsightsPanel "Оставить бюджет" actions.

### Tauri dev workflow gotchas

1. **Python sidecar runs from source в dev mode** (`spawn_python_dev` в econ_sidecar.rs). Module reload требует Tauri dev restart (Ctrl+C + npm run tauri dev). HMR подхватывает только frontend changes.

2. **Monitor timeout 5min** — нормально для long-running dev. Tauri dev продолжает работать. Не нужно re-arm если просто длинная сессия.

3. **Tauri dev exit 0** = пользователь закрыл окно намеренно. Сигнал конца работы, не ошибка.

### Math gotchas (для Phase 2 awareness)

1. **conformal.py:11, 278 already documents** — exchangeability violated с trend/seasonality. Aurora's Conformal Prediction уже acknowledges это; Phase 2 forecast horizon должен extend acknowledgment, не contradict.

2. **`adstock_mean_posterior`** (Phase 1.1 C1 fix) — frozen at training. Forecast must use this anchor, не recompute. Иначе re-introduces math drift identified в Phase 1.1 audit.

3. **Robyn issue #781** — adstock carryover в forecast period слабо документировано во всех MMM tools. Phase 2 forecast_warmup_correction() helper закрывает этот gap.

---

## Full Session Notes

### Часть 1 — Live test session (6 hours)

**Начало:** Антон ship'нул integration test (commit 5bbab49, 9 cases optimizer + ConstraintBundle), затем запустил Tauri dev для проверки v1.1.0 на Kagocel data. Я набросала smoke-test чек-лист.

**Engine selector UI improvements:**
- Запрос Антона: показывать оба варианта (Bayesian + OLS) с явной маркировкой выбранного
- Я сделала 2-cards layout с подсветкой active + muted состояния для не выбранного
- **Bug:** «выбрано автоматически по 20 наблюдениям», но Insights говорят «31 месячных» → fallback nRows на previewRows.length вместо shape.rows
- Fix: убран fallback на preview + restore shape из persisted store при mount

**ChannelCategoriesPanel iterations (несколько rounds):**
- Swap порядка: имя → икона → label (естественный read order)
- Дополнительный параграф hint с call-to-action
- Убран confidence % (категорий 3 фиксированных, не несёт UI-info)
- Theme-adaptive contrast: hardcoded rgba → color-mix(text-primary)
- Mixed между Brand и Performance (логика спектра)
- **Bug:** клик option в popup не обновлял UI → reactive `$derived.by(resolvedCategories)` через $channelCategories
- Discussion про continuous slider vs 3 discrete categories: я дала глубокий анализ за/против. Антон передумал — оставляем 3 фиксированных, удалила proposal memory

**ColumnMapper Insights sync:**
- Антон жал «Оставить бюджет» в инсайтах, но каналы оставались в media zone
- Root cause: hash key только из имён → role mutations не triggered re-init
- Fix: hash включает (name, role) пары + init mapping из columns[i].role priority

**FAQ tooltip:**
- Объяснение что значит «Оставить бюджет» (mультиколлинеарность, ROI-фокус)

**Train модель (после переназначения каналов на 2 brand + 2 perf + 2 mixed):**
- Train completed: R²=0.985, MAPE=7.1%, R-hat=1.0, 9 divergences
- Антон критика: «низкая уверенность в вердикте» резко снижает доверие → переименовала в «широкий ROI-интервал»
- Антон критика: divergences тоже воспринимаются эмоционально → перекалибровала пороги к proportion (Stan standard) + добавила % display

**ROI/CI на Train этапе показывали `—x` / `[?, ?]`:**
- By design — ROI вычисляется в Decompose, не Train. Антон выбрал Option 2 — inline-подпись «→ После декомпозиции»

**Optimization step:**
- Антон спросил про «Оптимизация распределения - бренд vs перформанс» — я объяснила F.1-F.3 фичу
- **Bug:** Lock Brand 100% + Lock Perf 100% → 0% lift на любых параметрах. Объяснила что это математически правильно (нет степеней свободы)
- Запрос Антона: добавить reset button + инструкции
- Я добавила «↺ Сбросить per-group» + информационный блок «Типичные сценарии» (4 примера включая Lock+Lock objection)

**ResponseCurves chart:**
- Запрос Антона: fullscreen + точки на линиях
- Wrap в ExpandableCard (как Decompose charts)
- Точки draggable строго на линии — Y координата через curveResponseAt (backend curve interpolation), не локальная Hill

**KPI lift discrepancy:**
- Banner +27.2% vs карточка +1.4% — массовый user confusion
- Root cause: frontend predictKPI упрощённая Hill без adstock, backend optimizer полная MMM
- Quick fix (Option 1): atOptimum detection → backend authoritative когда budgets ≈ optimal, иначе frontend approx с visible бейджем «≈ приблизительно»

**Forecast horizon discussion (start of Phase 2 conversation):**
- Антон: «как смоделировать оптимальный медиа-микс на бюджете будущего периода?»
- Глубокий концептуальный анализ: training horizon vs planning horizon mismatch
- Антон: «не повторить бенчмарки, стать новым образцом»
- Я предложила 3-фазовый подход:
  - Phase 1 (~30 мин) — honest disclosure banner
  - Phase 2 (~6-8h, отдельная сессия) — proper Planning Mode
  - Phase 3 (v1.2.0+) — full Planner mode
- Phase 1 ship'нула: planning warning banner с 4 пунктами guidance
- Phase 2 proposal saved в memory

**Channel Timeline tooltip highlight:**
- Антон: при hover на конкретный слой выделять соответствующую строку в tooltip
- Implementation: closure-based activeSeries variable + chart.on('mouseover') с filter по componentType + dispatchAction для force tooltip refresh
- **Bug 1:** `{ type: 'series' }` query невалидный → handler не fired
- Fix: убран query, filter по componentType inside handler

**ReportStep FAQ heading wrap:**
- Длинный заголовок «Часто задаваемые вопросы по этой модели» обрезался на узких экранах
- Fix: flex-wrap: wrap + row-gap на .info-toggle

**Commit 6460a24** — все 14 fixes + memory updates. Pushed.

### Часть 2 — Phase 2 planning session (4 hours)

**Антон активировал Plan mode:**
- Цель: детальное планирование Phase 2 forecast horizon
- Амбиция: next-generation образец, не повторение Robyn/Meridian

**Phase 1 — Initial Understanding:**
- Запустила 3 parallel Explore agents:
  - Backend `n_periods` + budget audit (rejected by user — не критично, я прочитала сама)
  - Frontend OptimizeStep/ScenarioPlayground/Report mental map
  - Industry research (Robyn/Meridian/LightweightMMM API + gaps)

**Frontend agent findings:**
- Detailed mental map OptimizeStep.svelte (~2940 lines, 5 visible blocks A-E)
- Все 4 invoke('econ_optimize') call sites (main + whatIf + 2× forecast)
- Existing patterns: ExpandableCard, expert disclosure, what-if multiplier, inflation overlay
- Layout opportunities для Planning Mode insertion

**Industry research findings:**
- Robyn `date_range`-ambiguous (best-known but messy)
- Meridian (Google) cleanest API (training/planning split)
- LightweightMMM `n_time_periods` abstract без date semantics
- Gaps Aurora может exploit: explicit period naming + posterior CI propagation + saturation drift detection + non-data-scientist UX + multi-scenario comparison

**Phase 2 — Design (1 Plan agent):**
- Generated detailed implementation plan ~3000 words
- 7 sections: backend math, API, frontend UI, math gates, tests, rollout, files
- Mode toggle (Analyst/Planner) vs always-on block A0 — chosen toggle
- Variable per-period budgets — defer 2.5 (math complexity)
- Adstock kernel decision: Option A (freeze training) recommended; Option B (recompute) higher risk
- "Next-gen UX" 4 specifics: calendar timeline picker, P10/P50/P90 headline, drift panel, scenario library

**Phase 3 — Review:**
- Read backend optimizer.py:478-510 для verification
- Confirmed math hot-path (`total_response_money` line 483-504)
- 4 questions через AskUserQuestion:
  - Order: Phase 2 ПЕРЕД v1.1.0 ship (decided)
  - Scenario library: needs explanation (decided after — Minimum viable)
  - Variable per-period: defer к 2.5 (decided)
  - Adstock math: Hybrid investigate (decided)
- Дополнительный AskUserQuestion для scenario library scope clarification

**Phase 4 — First plan written:**
- `C:\Users\ackol\.claude\plans\phase-2-dapper-cray.md`
- ~9-10 dev-days, 8 phases (2.0-2.7)
- ExitPlanMode call rejected by user

**Critical self-audit (по запросу Антона):**
- Глубокая ревизия плана с фокусом на:
  - Hidden math errors
  - Performance / efficiency gaps
  - UX gaps для premium tier
  - Failure modes
- Проверила existing helpers (`posterior_propagation.py`, `conformal.py`)
- Found 28 issues across M/P/U/F categories

**Plan rewrite (final version, ~41KB):**
- Added M1-M8 critical math gaps (warmup, seasonality, inflation, epistemic, hierarchical, stationarity, calibration, adstock_anchor)
- Added P1-P5 performance optimizations
- Added U1-U11 premium UX additions (smart defaults, plain language, decision support, quality stamp, math modal, animations, onboarding, interpretation, sharing, suite branding)
- Added F1-F4 failure modes & graceful degradation
- Phase 2.4 — Premium UX layer (1.5 days, NEW)
- Effort updated к ~13 dev-days
- Tightened math gates (forecast cap 5× → 2×, Hill p95/p99 tiered)
- Single pickle bump 1.3 → 2.0 (batch для known phases)

**Final actions:**
- Plan copied к `C:\Users\ackol\Desktop\PHASE_2_PLAN_forecast_horizon.md`
- Next session prompt created: `C:\Users\ackol\Desktop\NEXT_SESSION_PROMPT_phase2_forecast_horizon.md`
- Session compress requested

### Доктрина закреплена

1. **Backend-frontend single source of truth для critical metrics** — frontend approximations OK для preview, deliverables ВСЕГДА backend (atOptimum logic в BudgetOptimizer)

2. **Pre-existing bugs проявляются только при правильных данных** — synthetic fixtures должны cover все ветки (use_hierarchical=True/False)

3. **Honest UX disclosure > emotional language** — нейтральные технические термины с tooltip, не «низкая уверенность»

4. **MMM training horizon ≠ planning horizon** — fundamental, требует architectural decoupling

5. **Theme-adaptive contrast обязателен** — color-mix(text-primary) вместо hardcoded rgba

6. **Premium UX = trust signals + decision support + plain language** — никто из MMM competitors не делает; Aurora differentiation point

7. **Math correctness gates non-negotiable** — Phase 2.0 audit BEFORE 2.1, backward compat byte-exact

8. **Plan mode discipline** — Phase 1 understanding (Explore agents) → Phase 2 design (Plan agent) → Phase 3 review → Phase 4 final → Phase 5 ExitPlanMode. AskUserQuestion для clarifications.

9. **Critical self-audit перед ExitPlanMode** — ловит что Plan agent + initial planning пропустили (Антон requested → 28 findings обнаружено)
