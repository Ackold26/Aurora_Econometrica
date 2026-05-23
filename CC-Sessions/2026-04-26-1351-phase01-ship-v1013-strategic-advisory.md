---
tags: [session, compressed, phase01, ship-v1013, strategic-advisory, sprint3-prep]
type: session
updated: 2026-04-26
---

# Quick Reference

Полная multi-day сессия: live-test Kagocel v1.0.13 → 3 hotfix'а (#17/#18/#19 money mode + per-channel sync + multi-start SLSQP) → ship v1.0.13 (full P1-P7 pipeline) → стратегическое обсуждение модулей A/B → 3 промта для следующих сессий → read Sprint 1+2 backend от parallel session → critical review (10 findings) → D→MIN-LIVE→B sequence для Sprint 3 Pharma Causal Premium.

**Topic:** Phase 0.1 fix-session live-test + ship v1.0.13 + Sprint 3 prep
**Key files:** `engines/optimizer.py`, `engines/narrative_adapter.py`, `aurora_html/sections.py`, `aurora_pptx/builder.py`, `OptimizeStep.svelte`, `tools/test_math_correctness.py`, `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`, `RELEASE_NOTES_v1.0.13.md`, `PASHE_IT.MD`, `latest.json`
**Status:** v1.0.13 SHIPPED (commits e567a37+56984ec+a3662a0+75872db+f9e6953+f4da62d). 19 findings closed. GH Release published. Auto-update LIVE. Sprint 1+2 backend done в parallel session (другая Маша). Sprint 3 запланирован: D→MIN-LIVE→B sequence.

---

## Learnings

### Math chain rule canonical (single source of truth)

**Formula** (docs/MATH_AUDIT_v1_3_PHASE_0_1.md):
```
mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost
```

Pre-fix bugs (Phase 0.1):
- **#11** missing adstock_factor → mROAS off 2-15× depending on θ
- **#12** missing /unit_cost → TRPs (uc=250000) показывал 1780×

**Geometric adstock_factor analytical (exact):**
```
factor = (n - θ·(1-θ^n)/(1-θ)) / (n·(1-θ))
```

Constant in x for linear adstock. Для θ=0.5, n=31 → factor ≈ 1.935.

**Weibull:** numerical central difference (eps = max(x·1e-4, 1e-9)).

**Edge cases:** zero spend / mean / beta / unit_cost → return 0.

### Multi-start SLSQP для local-optimum trap

При money_target = current_money_sum, SLSQP стартует с current allocation = local minimum для objective + sum constraint → не двигается → lift=0% даже когда clear redistribution beneficial.

**Solution:** 3 starting points (current + 2 random within bounds, scaled to constraint), pick best converged. Fixed seed=42 для determinism.

**Verification:** Kagocel money×1.0 wide bounds [10,300] → lift +6.0%, Статьи +200% (mROAS 52×), TRPs -0.1% (mROAS 0.014×).

### Money mode constraint для mixed-units

UI runOptimize must pass `totalBudgetMoney = currentTotalBudget` always. Native sum constraint на mixed-units (TRP+рубли) арифметически бессмыслен — optimizer не находит redistribution.

Money mode → `Σ x_native × unit_cost = const` → physically meaningful constraint → SLSQP redistributes.

### Per-channel constraints sync с global slider

`$effect` auto-инициализирует `channelMinPct[ch] = minPct` на first render. Когда user сдвигает global slider — per-channel **остаются stale** и **переопределяют** новое global. Backend получает stale bounds.

**Fix:** в `runOptimize` передавать per-channel ТОЛЬКО если value differs от current global — иначе backend применяет new global автоматически.

### Conditional precision _fmt_pct (никаких «0% бюджета»)

```python
def _fmt_pct(v):
    if f == 0: return "0%"
    if 0 < |f| < 0.1: return "<0.1%" / ">-0.1%"
    if 0 < |f| < 1: return f"{f:.1f}%"
    return f"{round(f)}%"
```

Pre-fix bug: `{:.0f}%` rounded 0.4% to 0% → narrative «Performance — 26% продаж при 0% бюджета» (повторялось 4 раза).

### narrative_adapter typo `miroas` (один i) — silent fall through

`oc.get("miroas") or oc.get("mroas") or dc.get("roi")` — поле в optimizer.json называется `mroi_current`, не `miroas`. Silent fall through на average ROI (contribution/spend) из decomposer. HTML/PPTX отчёты годами показывали average ROI в полях помеченных «mROAS».

**Fix:** `oc.get("mroi_current") or 0.0` + `avg_roi` отдельным полем.

**Side effect:** 4 test/verify файла использовали `miroas` в sample data → тесты не ловили реальный bug. После typo fix — sample data updated, tests testify правильный contract.

### Pre-flight feasibility check

Перед SLSQP проверить (в money units):
- `sum_upper_money >= money_target` иначе INFEASIBLE_BUDGET_HIGH
- `sum_lower_money <= money_target` иначе INFEASIBLE_BUDGET_LOW
- Tolerance 0.1%

Pre-fix: infeasible bounds → SLSQP iterating fruitlessly до 60s Tauri timeout → sidecar crash + watchdog respawn (90s downtime). Post-fix: 0.05s instant rejection с explicit error message.

### Binding constraints diagnostic flag

После SLSQP проверить:
```python
def _is_binding(x_val, bound_val, scale):
    rel = abs(x_val - bound_val) / max(abs(bound_val), scale*1e-3, 1.0)
    return rel < 1e-3
```

Surface `binding_constraints`, `n_channels_at_max/min`, `min_pct_used`, `max_pct_used` в JSON. Frontend → narrative показывает «Оптимизатор упёрся в границы» вместо vacuous «перебалансировать 0 млн».

### V40 XSS защита для {@html}

Channel names из xlsx user-controlled → если пройдут через `{@html text.replace(...)}` без escape → XSS vector. Все user-sourced strings обязательно через `escapeHtml()` helper.

### Sidecar build freshness check

`build_sidecar.py` exit 1 если `.py` newer чем `econometrica-sidecar.exe`. Защита от stale exe в installer.

### auto-update pipeline LIVE

`updater.rs:70-86`:
1. Tries Supabase `/app-update` first
2. Fallback на GitHub Pages `https://ackold26.github.io/rosst-updates/{product}/latest.json`
3. `is_newer(remote, current)` → frontend показывает баннер
4. Download + auto-install + restart

**3 places sync обязательно:**
- GH Release `aurora-releases` repo (public!)
- Supabase `app_versions` row (4 поля атомарно)
- `rosst-updates/{product}/latest.json`

### SPRINT*_PROGRESS.md persistent state pattern

Reusable protocol для autonomous mode + auto-compaction recovery:
- Persistent file в корне проекта
- Маша обновляет после каждого commit
- При compress restoration из файла
- Auto-commit local OK
- Architecture decisions / schema migration / push — confirmation required
- Пример Antонов AUTO-RESUME PROTOCOL block в стартовом промте

### Defense in depth gates

**Independent code review** ≠ **MIN-LIVE headless verification** — complementary, не overlapping:
- Review ловит logical bugs (off-by-one, wrong formula, missing edge case)
- MIN-LIVE ловит integration bugs (schema mismatch, pickle persistence, JSON shape regressions)

Без обоих — single point of failure.

---

## Decisions

### Ship decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-26 | v1.0.13 ship через GH Releases в Ackold26/aurora-releases (public) | Supabase 413 на .exe >117MB; private repo даёт 404 для clients без auth |
| 2026-04-26 | Auto-update mandatory=false | Клиент может отложить, не принудительно |
| 2026-04-26 | min_version: 1.0.0 | Все клиенты v1.0.10+ получат update |

### Sprint 1 Foundation decisions (Phase 1.9 + 1.1 + A4)

| # | Decision | Detail |
|---|---|---|
| 1 | Adstock priors: hierarchical (b) | μ ~ Beta(2,5), κ ~ Gamma(3,1), decay_i ~ Beta(μ·κ, (1-μ)·κ). SBC recovery >85% milestone gate |
| 2 | Calendar: implementation после 31 May | Research до 31 May в окнах. Ship 15-30 июня |
| 3 | A4 audience: hybrid (c) | Marketing summary + analyst expandable details |
| 4 | Validation: Kagocel + Venarus + MMX 2021-2025 | Real-data + 5 synthetic scenarios |
| 5 | Sequence: 1.9 → 1.1 → A4 (3 separate ships) | 1.9 immediate value, 1.1 расширяет quality, A4 как Sprint 1.5 |

### Audit B-list decisions

| # | Decision | Status |
|---|---|---|
| B1 ArviZ.hdi() | ✅ Accept | Technical lib choice, fix H2 |
| B2 Pathfinder init | ✅ Accept | Free win, deferred to Phase 1.1 |
| B3 Quick proxy A4.3 | ✅ Accept | UX improvement |
| B4 Unified Confidence Score | ❌ Reject | Сохраняем 3-tier (MQS уже 0-100, второе число = confusion) |
| B7 Backtest framework | ⏸ Defer | Sprint 1.5 (v1.0.17) |

### Critical findings → no clients pivot

«Нет клиентов и моделей в production» меняет risk profile:
- Schema cleanup feasible (~2-3h, drop v1.0/v1.1/v1.1.5 fallbacks)
- Backward compat не нужна
- Multi-sprint в одном branch — снижено
- 3 staged ships → combined ship лучше
- SBC defer до Sprint 3 Pre-Ship gate (Pharma compliance тогда требует)

### Sprint 3 final sequence: D → MIN-LIVE → B

- **D Independent math review** (3-5h) — fresh-context skeptic, code-only без docs
- **MIN-LIVE headless verification** (2-3h) — через FastAPI endpoint (тот же путь что Rust), не direct Python
- **B Sprint 3 Pharma Causal Premium** (25-40h):
  - B5 DiD (Callaway-Sant'Anna 2021)
  - Synthetic Control + Augmented (Abadie + Ben-Michael 2021)
  - Causal Forest (Wager-Athey)
  - Bayesian MMM priors калибровка через geo-experiment lift studies (Robyn-style)
  - UI pipeline-step «Causal Validate» внутри MMM-кабинета
  - Стек: linearmodels + econml + pysyncon + statsmodels (~30 MB к sidecar)
- UI integration параллельно с Sprint 3 backend
- SBC + Full A4 — Sprint 3 Pre-Ship gate

**Уверенность Маши: 85%** (90% если MIN-LIVE через FastAPI endpoint == production path).

### Aurora-fix skill usage

Должен запускаться pre/post-build для всех Aurora продуктов. Skill актуализирован с V40-V47 (security audit findings), V28-V30 (cabinet.rs↔cabinets.json sync, GH Release public repo), V34-V39 (FastAPI sidecar layers).

---

## Pending

### Sprint 3 launch sequence (Антон)

1. ⏳ **D Independent math review** (3-5h, fresh Claude session)
   - Read engines/modeler.py Phase 1.1 hierarchical priors
   - Read utils/posterior_propagation.py HDI computation, joint correlation
   - Read utils/adstock.py geometric_adstock_batch при θ→1 numerical stability
   - Read _compute_mroas_money_samples chain rule
   - Surface ≥3 hidden bugs/inconsistencies → discuss

2. ⏳ **MIN-LIVE headless** (2-3h, через FastAPI):
   ```bash
   cd sidecar/econometrica && python server.py &
   curl -X POST http://127.0.0.1:7529/compute/decompose -d @kagocel_payload.json
   curl -X POST http://127.0.0.1:7529/compute/optimize -d @optimize_payload.json
   curl -X POST http://127.0.0.1:7529/compute/scenario -d @scenario_payload.json
   ```
   Verify: pickle v1.2 loadable, CI fields populate, math values reasonable, joint correlation preserved

3. ⏳ **Sprint 3 Pharma Causal launch** после gates clean

### Параллельные tracks

- **UI integration** (10-15h SvelteKit) — Mode toggle, Banner, Reliability tier viz, Backtest button, CI brackets rendering
- **Sales validate B3** (Materia Medica + 4 FMCG) — отложено
- **Em dash cleanup sweep** (10 продуктов) — отложено
- **Schema cleanup до v1.2 only** (2-3h) — feasible без клиентов

### Sprint 3 Pre-Ship gate

- SBC test recovery >85% (overnight 16h)
- Full A4 implementation (Yang's test + identifiability simulation)
- UI integration + live-test на 3 dataset
- Compliance docs (ФЗ-38 / ОРД / ФАС) для Pharma

---

## Errors & Workarounds

### Live-test environment

| Error | Workaround |
|---|---|
| Vite cache stale (показывал 50/150 после моих 20/200) | `rm -rf node_modules/.vite .svelte-kit build` + WebView2 EBWebView clear |
| Port 5173 conflict (stale node process) | `Stop-Process -Id <pid>` после `Get-NetTCPConnection -LocalPort 5173` |
| Sidecar 90s crash на первом optimize | try/except SLSQP + maxiter=200 + pre-flight feasibility |
| Watchdog flapping (1/3 → recovered) | Independent health checks, не блокер если recovery < 60s |
| `taskkill /F` flag parsing fail | `cmd //c "taskkill /F /IM ..."` wrapper |
| Bash cd failed на относительный путь | Absolute path: `python "D:/Docs/.../build_sidecar.py"` |

### Math discoveries

- **typo `miroas`** (один i) silent fall through на avg_roi — main cause «5 разных mROAS источников» из live-test
- **C1 mean-normalization drift 5-15% bias** в первой Phase 1.1 имплементации — поймано аудитом ПОСЛЕ commit (single-session blind spot)
- **Pilot recovery 4/5** logit-normal записан как «production-ready» — самообман, ch1 true=0.40 НЕ внутри HDI

### UI flow surprises

- Optimizer dirty-state не sync per-channel с global slider — finding #18 из live-test
- Money mode UI runOptimize передавал `totalBudgetMoney: null` → native sum constraint на mixed-units = арифметический мусор — finding #17

---

## Files modified (этот session)

### Production code (Phase 0.1 fixes)
- `sidecar/econometrica/engines/narrative_adapter.py` — typo fix `miroas` → `mroi_current`, avg_roi field, binding-aware narrative facts, _derive_narrative_facts propagates optimization state
- `sidecar/econometrica/engines/optimizer.py` — `_adstock_factor()`, `_compute_mroas_money()` helpers, multi-start SLSQP (3 starts seed=42), pre-flight feasibility, try/except, binding flag, JSON output extended
- `sidecar/econometrica/utils/adstock.py` — `'noop'`/`'none'` mode для tests
- `sidecar/econometrica/aurora_html/sections.py` — `_fmt_pct` conditional precision, binding-aware f3/SCQAR/Recommendation, data-driven Action 02/03 (replace Burst/Targeted)
- `sidecar/econometrica/aurora_html/strings_ru.json` — templates pre-formatted strings
- `sidecar/econometrica/aurora_pptx/builder.py` — `_fmt_pct`, всех callers updated
- `src/lib/components/pipeline/OptimizeStep.svelte` — defaults 50/150 → 20/200, money mode totalBudgetMoney=currentTotalBudget, per-channel sync с global, dirty-state badge, miROASMap reads backend authoritative
- `src-tauri/src/commands/econometrica.rs` — Rust fallback defaults 20/200

### Tests + verify
- `tools/test_math_correctness.py` — analytical synthetic test (mROAS=500), unit cost invariance, zero spend edge cases, geometric adstock_factor analytical formula match, narrative regression, _fmt_pct 18 cases (138 → 156 assertions)
- `tools/test_narrative_adapter.py` — sample data `miroas` → `mroi_current` (4 places)
- `tools/verify_aurora_pptx_brand.py` — same
- `tools/verify_aurora_pptx_narrative.py` — same
- `tools/verify_aurora_html_narrative.py` — same

### Docs + memory
- `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — single source of truth math reference (NEW)
- `RELEASE_NOTES_v1.0.13.md` — release notes (NEW)
- `src-tauri/help/econometrica.html` — Step 5 Optimize section actualized (defaults 20/200, multi-start, money-mode, mROAS formula, Avg ROI vs mROAS, диагностика)

### Version bumps (v1.0.10 → v1.0.13)
- `package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`

### Ship artifacts
- `D:\cargo-targets\econometrica\release\bundle\nsis\Aurora AI Econometrica_1.0.13_x64-setup.exe` (178.78 MB, SHA256 `bf3e873dbaad3a80123569eb61d806e3063e4d890c10b8e2e9998a3b00870beb`)
- GH Release: https://github.com/Ackold26/aurora-releases/releases/tag/v1.0.13
- `D:/Docs/Aurora_Ai/Infrastructure/rosst-updates/aurora-econometrica-gui/latest.json` — v1.0.13 manifest (commit `806131d` pushed)
- Supabase `app_versions` row aurora-econometrica-gui — PATCHED v1.0.13 (4 поля атомарно)
- `C:/Users/ackol/Desktop/PASHE_IT.MD` — IT docs обновлены

### Memory updates
- `MEMORY.md` — Econometrica entries → SHIPPED status
- `project_econometrica_phase01_livetest_findings.md` — COMPLETE 19/19 findings
- `project_econometrica_strategic_advisory_2026_04_27.md` (NEW) — D→MIN-LIVE→B sequence

### Session logs
- `CC-Sessions/2026-04-26-0100-phase01-fix-session-ship-v1013.md`
- `CC-Sessions/2026-04-27-strategic-advisory-d-min-b-sequence.md`
- `CC-Sessions/2026-04-26-1351-phase01-ship-v1013-strategic-advisory.md` (this file)

### Plans + progress trackers
- `C:/Users/ackol/.claude/plans/joyful-strolling-fiddle.md` — Phase 0.1 fix plan v3
- `C:/Users/ackol/Desktop/Phase0.1_FixSession_Progress.md` — completed tracker

---

## Setup & config changes

### GH CLI
- Authorized as Ackold26 (`gh auth status` confirmed)
- Releases pushed to public `Ackold26/aurora-releases` (V30 compliance)

### Supabase secrets
- `C:/Users/ackol/.claude/aurora-secrets.env` — SUPABASE_SERVICE_ROLE_KEY validated, REST API PATCH работает

### Tauri dev defaults
- Port 1420 → 5173 (Vite default, escape Hyper-V/HNS dynamic claim)
- IPv4 explicit `127.0.0.1` (WebView2 на Windows резолвит localhost в IPv6)

### Sidecar build
- PyInstaller bundle 637 MB (--collect-all для arviz/pymc/pytensor/pymc_marketing)
- Freshness check: exit 1 если .py newer чем exe

---

## Commits (this session contribution)

```
e567a37  fix(F0): mROAS canonical chain rule + typo + JS deprecate (#5/#11/#12/#13/#14/#16)
56984ec  fix(N+O): narrative format + recommendations + bounds + sidecar hardening (#1-#9, #15)
a3662a0  fix(hotfix): live-test Phase 0.1 — money mode + per-channel sync + multi-start (#17/#18/#19)
75872db  release: bump v1.0.10 → v1.0.13 + help system actualization
f9e6953  docs: release notes v1.0.13
f4da62d  docs(session): Phase 0.1 fix-session + v1.0.13 ship complete
e660034  docs(session): strategic advisory 2026-04-27 — D→MIN-LIVE→B sequence
```

Plus tag: `v1.0.13` + `v1.0.13-rc-phase0.1-fixes`.

---

## Full Session Notes — narrative timeline

### Day 1 — Phase 0.1 fix-session

Session начался после v1.0.12 ship (sessions 2+3 report quality). Антон попросил план для Phase 0.1 fix-session — закрытие ship-blockers перед v1.0.13 commercial release.

Plan v3 написан с глубоким аудитом (`joyful-strolling-fiddle.md`). Найдена **главная находка** — typo `miroas` (с одной i) в `narrative_adapter.py:196` → silent fall through на average ROI вместо marginal. Это объясняло «5 разных mROAS источников» из live-test.

F0 фундамент closed 7 findings:
- F0.1 typo fix (5 мин, 4 test files updated)
- F0.2 math chain rule с adstock_factor + /unit_cost (analytical mROAS=500 verified)
- F0.3 JS marginalROI deprecation (backend authoritative)
- F0.4 adstock params audit (invariant держится)
- F0.5 14 new analytical tests

Track N+O closed 7 more:
- N1 _fmt_pct conditional precision (никаких «0% бюджета»)
- N3 binding-aware narrative
- N4 generic советы → data-driven
- O1.1 defaults 20/200
- O1.2 dirty-state hint
- O1.3 binding flag + pre-flight feasibility
- O2 SLSQP try/except + maxiter cap

Standalone test PASS на Kagocel pickle: tight bounds → binding=True (correctly detected), wide bounds → +13% lift, infeasible → 0.05s rejection.

333/333 tests PASS.

### Day 1 — Live-test + 3 hotfix'а

Live-test показал что mROAS правильные, recommendations data-driven, narrative честный. **Но** Optimize daм lift=0%. Investigation:

**#17 money mode UI bug:** runOptimize передавал `totalBudgetMoney: null` → backend native sum constraint на mixed-units → SLSQP не находит redistribution. Fix: всегда передавать money budget.

**#18 per-channel sync с global:** $effect auto-init `channelMinPct[ch] = minPct` на first render. После смены global slider per-channel остаются stale → backend получает stale bounds. Fix: передавать per-channel ТОЛЬКО если differs от current global.

**#19 SLSQP local optimum:** при money_target = current, SLSQP starts at current = local minimum → не двигается. Fix: multi-start (3 points, seed=42) → выбрать best.

Standalone после fix: lift +6.0%, Статьи +200%, TRPs -0.1% (correct redistribution).

UI verified: Статьи 52.92× verdict Scale ✅, TRPs 0.014× Cut ✅, narrative никаких «0% бюджета» ✅, recommendations data-driven ✅.

### Day 1 — Ship v1.0.13 (P1-P7 pipeline)

После live-test PASS — full ship pipeline:
- P1 .exe valid (178.78 MB) ✅
- P2 SHA256 `bf3e873d...0beb` ✅
- P3 GH Release published в Ackold26/aurora-releases (V30 compliance) ✅
- P4 rosst-updates `latest.json` updated, pushed ✅
- P5 Supabase `app_versions` PATCH 4 поля атомарно ✅
- P6 Tag `v1.0.13` pushed ✅
- P7 Branch + session log pushed ✅

Auto-update verified: GH Pages отдаёт v1.0.13 manifest, curl 302→200 download URL. Клиенты v1.0.10+ получат баннер в течение часа (Supabase primary + GitHub Pages fallback).

### Day 2 — Strategic advisory

Антон запросил 3 промта для следующих сессий:
1. **Sprint 1 Foundation** — Phase 1.9 + 1.1 + A4 (math evolution, ~30-40h)
2. **Sprint 2 Small-data** — OLS + horseshoe + reliability для n<20
3. **Sprint 3 Premium** — для больших клиентов (later pivot на Pharma Causal)

Memory обновлено: показала что Sprint 1+2+1.5 backend сделаны parallel session (другая Маша) — **329 tests PASS, 30+ commits**. Phase 1.9 + 1.1 + A4 quick proxy + Sprint 2 OLS + B7 backtest skeleton + 9 audit fixes за один autonomous-mode день.

Critical review:
- 5 🔴 findings: SBC gate skipped, pilot recovery 4/5, C1 5-15% bias initial commit, UI отсутствует, live-test не сделан
- 4 🟡 findings: multi-sprint branch, schema 4 layers, Pathfinder defer, A4 incomplete
- 1 🟢 finding: B7 backtest skeleton

«Нет клиентов» insight Антона изменил risk calculus — backward compat не критична, schema cleanup feasible, multi-sprint branch снижено.

### Day 2 — D → MIN-LIVE → B sequence

5 вариантов развилок проанализированы. Final recommendation:

1. **D Independent math review** (3-5h)
2. **MIN-LIVE headless** (2-3h) через FastAPI endpoint
3. **B Sprint 3 Pharma Causal Premium** (25-40h):
   - B5 DiD (Callaway-Sant'Anna 2021)
   - Synthetic Control + Augmented (Abadie + Ben-Michael 2021)
   - Causal Forest (Wager-Athey)
   - Bayesian MMM priors калибровка через geo-experiment lift studies
   - UI pipeline-step «Causal Validate»
   - Стек: linearmodels + econml + pysyncon + statsmodels

UI integration параллельно. SBC + Full A4 → Sprint 3 Pre-Ship gate.

Уверенность Маши: 85% (90% если MIN-LIVE через FastAPI endpoint).

### Day 2 — Wrap

Антон закрыл сессию тёплыми словами. Финальный commit `e660034` (advisory session log). Все обновления memory + 3 промта готовы для следующих сессий. v1.0.13 LIVE для клиентов через auto-update.

Эта сессия = strategic + Phase 0.1 critical math work. Code velocity Sprint 1+2 = parallel autonomous Маша. Здесь — анализ, варианты, decisions, prompts.
