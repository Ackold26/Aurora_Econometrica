---
tags: [session, advisory, strategic, sprint3-prep]
type: session
updated: 2026-04-27
---

# Quick Reference

Strategic advisory session — Маша помогла Антону скорректировать post-Sprint-1 sequence через критический review недостатков и обсуждение вариантов развилок. Финальная sequence: **D Independent review → MIN-LIVE headless verification → B Sprint 3 Pharma Causal Premium**. 3 промта подготовлены для следующих сессий. Этот session — без code changes; production code был написан в parallel Sprint 1+2 sessions.

**Topic:** strategic advisory + Sprint 3 preparation
**Predecessor:** v1.0.13 SHIPPED + Sprint 1+2 backend done
**Next:** D review + MIN-LIVE + Sprint 3 launch

## Что сделано в session

1. **3 промта подготовлены** для следующих Claude Code sessions:
   - Sprint 1 Foundation (math evolution: Phase 1.9 + 1.1 + A4) — был использован
   - Sprint 2 Small-data path (OLS + horseshoe + reliability)
   - Sprint 3 Premium (pivoted на Pharma Causal через Аватар B)

2. **Critical review результатов Sprint 1+2 backend**:
   - 5 critical 🔴 findings (SBC gate skipped, pilot recovery 4/5, C1 bias initial commit, UI отсутствует, live-test не сделан)
   - 4 medium 🟡 findings (multi-sprint branch, schema 4 layers, Pathfinder defer, A4 incomplete)
   - 1 low 🟢 (B7 backtest skeleton)

3. **«Нет клиентов» insight** изменил risk calculus:
   - Schema cleanup стал feasible
   - Backward compat не нужна
   - Multi-sprint branch risk снижен
   - SBC можно перенести в Sprint 3 Pre-Ship gate

4. **5 вариантов развилок проанализированы**:
   - A. Stabilize before extend (28-37h, conservative)
   - B. Sprint 3 Pharma Causal straight (25-40h, aggressive)
   - C. Hybrid parallel (25-35h, context-switch heavy)
   - D. Independent review first → decide (3-5h gate)
   - E. Wait Платформа 31 May (zero new work)

5. **Final recommendation: D → MIN-LIVE → B**:
   - D: Independent code review (3-5h)
   - MIN-LIVE: Headless verification через FastAPI (2-3h)
   - B: Sprint 3 Pharma Causal Premium (25-40h)
   - UI integration: parallel track к Sprint 3 backend
   - SBC + Full A4: Sprint 3 Pre-Ship gate (не сейчас)

## Persistent state pattern

**SPRINT*_PROGRESS.md в корне проекта** — protocol для autonomous mode + auto-compaction recovery. Reusable для других продуктов Aurora AI.

Auto-commit policy hybrid:
- Routine work / bug fixes → auto-commit local
- Architecture / schema / new files → show-then-commit
- Push → always show-then-push

## Pharma Causal Premium scope (Sprint 3)

После gates clean — Аватар B implementation:

- B5 Difference-in-Differences (Callaway-Sant'Anna 2021) — staggered adoption, heterogeneous effects
- Synthetic Control Method (Abadie + Augmented SCM Ben-Michael 2021)
- Causal Forest (Wager-Athey) — heterogeneous treatment effects
- Bayesian MMM priors калибруются через geo-experiment lift studies (Robyn-style)
- UI pipeline-step «Causal Validate» внутри MMM-кабинета (не отдельный кабинет)
- Стек: `linearmodels` + `econml` + `pysyncon` + `statsmodels` (~30 MB к sidecar)
- ETA 25-40h backend + ~10-15h UI

**Validate client:** Materia Medica (Кагоцел уже клиент). Geo-data в фарме у всех — pre-launch блокеры закрыты.

**Compliance value:** ФЗ-38 / ОРД / ФАС reporting требуют honest CI на лифт — Causal layer + Phase 1.9 posterior CI = production-ready compliance narrative.

## Эта session — advisory only

Никаких production code commits в этой сессии. Code velocity Sprint 1+2 — это была parallel autonomous Маша. Здесь — strategic советник, аналитик, prompt writer.

Patterns которые остаются:
- D→MIN-LIVE→B sequence
- 3 промта для следующих фаз
- Memory updated с decision log
- Findings tabulated (10 defects)

Антон prepared для Sprint 3 launch.
