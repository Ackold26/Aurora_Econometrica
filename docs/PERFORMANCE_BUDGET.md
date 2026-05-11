# Performance Budget v1.3.0

**Date:** 2026-05-12
**Owner:** Маша маленькая
**Status:** Live (CI-enforced в Stage 5)

Эталонная тестовая конфигурация: **Кагоцел РФ ММХ 1105-26** baseline проект (7 каналов × 156 наблюдений недельных данных). Этого достаточно для realistic regression. Для absolute benchmarks использовать synthetic dataset (`tests/integration/test_performance_synthetic.py`) с параметризацией 3×10 / 7×156 / 12×260.

## Бюджет по операциям

| Операция | Target | Hard fail | Notes |
|---|---|---|---|
| **Bundle load (без миграции)** | < 1.5s | > 3s | На SSD/NVMe. HDD не поддерживаем. |
| **Bundle load (с in-memory v1.3.0 default injection)** | < 2.0s | > 4s | Default injection per ADR-017. |
| **Bundle save** | < 2s | > 5s | Включая auto-backup history rotation. |
| **Sidecar cold start (до handshake healthy)** | < 15s | > 25s | Текущее v1.2: ~22s. Цель v1.3: ≤15s. |
| **Auto-detect columns (Excel parse + classify)** | < 1s | > 3s | На 7 каналов × 156 строк. |
| **Validate columns + KPI** | < 0.5s | > 2s | Plus mode_inference на per-channel inputs. |
| **Train model (Bayesian, NUTS)** | < 60s | > 180s | На 7×156. 4 chains × 1000 samples. |
| **Decompose (post-train)** | < 2s | > 5s | KPI/mode-aware verdicts + CPU + sales share. |
| **Insights generation** | < 0.5s | > 2s | 8 rules × 4 mode matrix. |
| **Optimize forward (SLSQP)** | < 3s | > 8s | 7 каналов, 100 iterations max. |
| **Optimize goal-seek (MVP bisection)** | < 1s | > 3s | < 30 iterations bisection convergence. |
| **Optimize goal-seek (Expert posterior)** | < 60s | > 120s | Phase B. 10 multi-start × 1000 posterior draws. |
| **Compute safe corridor (MVP)** | < 0.3s | > 1s | Pure computation per канал. |
| **Auto-detect price per pack** | < 0.5s | > 2s | sales_rub / sales_packs trimmed mean + CV. |
| **Sensitivity preview (UI slider)** | < 200ms | > 500ms | Real-time slider response. |
| **Report HTML generate** | < 5s | > 12s | 14 секций + charts (ECharts JS embedded). |
| **Report PPTX generate** | < 5s | > 12s | 13 slides + embedded charts. |
| **Report XLSX generate** | < 3s | > 8s | Rust rust_xlsxwriter, ~5 sheets. |
| **Report DOCX generate (MVP)** | < 2s | > 6s | Executive summary only в MVP. |
| **Full pipeline (Import → Report)** | < 90s | > 240s | Includes training. |
| **Full pipeline без training (open + decompose + optimize + report)** | < 15s | > 40s | На existing model. |

## Memory budget

| Component | Target | Hard fail | Notes |
|---|---|---|---|
| **Bundle размер** (после v1.3.0 defaults) | +5% vs v1.2 | +15% | Защита против раздувания. |
| **Sidecar RSS idle** | < 250 MB | > 400 MB | После cold start. |
| **Sidecar RSS during training** | < 1.5 GB | > 3 GB | На 7×156. |
| **Frontend RAM (Tauri WebView)** | < 300 MB | > 600 MB | Из памяти Tauri allocation. |
| **Goal-seek posterior CI cache** | < 50 MB | > 200 MB | Per project. |

## Cold start (sidecar startup)

| Этап | Текущее v1.2 | Target v1.3 | Notes |
|---|---|---|---|
| FastAPI startup | ~1s | < 1s | Не должно ухудшиться. |
| KPI registry load | ~0.1s | < 0.2s | Расширение до 8 типов. |
| Content pack load | ~0.5s | < 0.7s | Если добавляются count KPI strings. |
| First-request warmup (model loaders, optimizers) | lazy | lazy | `optimize/inverse.py` lazy import per ADR. |
| **Total до handshake healthy** | ~22s (8 attempts) | **≤ 15s** | Reduce attempts threshold + faster init. |

## UI Responsiveness

| Interaction | Target | Hard fail |
|---|---|---|
| Click button → visible response | < 100ms | > 300ms |
| Slider drag → result update | < 200ms | > 500ms |
| Page transition | 200ms (animated) | > 500ms |
| Modal open | < 150ms | > 400ms |
| Tooltip show | < 50ms | > 200ms |
| Glossary panel open (Ctrl+K) | < 100ms | > 300ms |
| Form validation feedback | < 100ms | > 300ms |

## CI gates

В Stage 5 добавляется `tests/integration/test_performance_budget.py`:
- Запускает каждую операцию из таблицы на синтетике 7×156.
- Сравнивает с Target / Hard fail.
- `assert duration <= TARGET` — soft fail (warning в CI summary).
- `assert duration <= HARD_FAIL` — fail build.

Также `tests/integration/test_memory_budget.py`:
- Запускает full pipeline + measures peak RSS.

## Regression baseline

После каждого commit на `feat/v1.3.0-next-gen` — performance suite запускается. Baseline зашит в `tests/integration/performance_baseline.json` (commit-controlled). Если duration новее baseline на > 20% — warning. На > 50% — fail.

## Принципы оптимизации

1. **Lazy imports.** Тяжёлые модули (PyMC, scipy.optimize, posterior CI compute) — lazy import при первом use, не на startup.
2. **Caching.** Safe corridor, decompose results, posterior samples — cached per `(project_id, model_version_hash)`. Invalidate on retrain.
3. **Profiling first.** Перед optimization — `cProfile` + flamegraph. Не угадывать bottlenecks.
4. **Batching.** UI updates через debounce / requestAnimationFrame, не один-к-одному с backend events.
5. **Web workers** для heavy frontend ops (chart re-renders) — Phase B.

## Performance regression policy

Если operation breaks soft target (Target):
1. Notice в CI summary.
2. Owner reviews — accepts ((tradeoff for feature) или fixes.

Если operation breaks hard fail:
1. Build red. Owner fixes before merge.
2. Если cannot fix — escalate to architect.

## Related

- ADR-014 Safe corridor (Phase B Expert mode = full posterior — отложен из-за perf budget).
- ENGINEERING_INVARIANTS.md INV-02 (runtime smoke tests).
- Aurora общая performance policy (cross-product Aurora Platform).
