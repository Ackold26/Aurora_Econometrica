# АВТОНОМНАЯ РАБОТА: мат-аудит ядра MMM Optimizer

> **SSOT прогресса аудита.** Метод и фазы — в плане `C:\Users\ackol\.claude\plans\rippling-growing-hamming.md`.
> Протокол восстановления после компрессии: прочитать этот файл + план → продолжить с «ОСТАЛОСЬ» БЕЗ переспроса.
> Развилки решать самой; методологические правки — с RAG-атрибуцией (`lib_vec.py search`, двуязычный запрос).

## Шапка
- **Статус:** Фаза 0 (baseline-прогон)
- **Ветка:** `feat/econ-math-audit` (от `feat/design-adopt-hybrid-ds` @ 9054f7f)
- **Safety-тег:** `v-pre-math-reaudit`
- **Среда (0.1 ✅):** глобальный Python 3.12.10 (`C:\Users\ackol\AppData\Local\Programs\Python\Python312`); pymc 5.28.4 / arviz 0.23.4 / numpy 2.4.2 / scipy 1.17.1 / pandas 3.0.1 / jax 0.7.2 + numpyro 0.20.1 / pytest+xdist. g++ НЕТ (pytensor.cxx='') → **режим аудита = Tier-1 NUTS via JAX** (Tier-2 PyTensor-NUTS будет медленный Python-mode). Реальные данные ЕСТЬ: `D:\Docs\Aurora_Ai\TestData\Econometrica` (Kagocel_RF, Venarus, MMX_2021-2025, Planning) → requires_real_data тесты работают.
- **Фикстуры:** conftest.py даёт session-scoped `synthetic_trained_project` (v1.2, 5 каналов, 200 samples, БЕЗ MCMC) + `kagocel_pathology_project` (v1.3 hierarchical, TRP native+money, mROAS-асимметрия) — готовые для зондов decompose/optimize/inverse. NB: pytest collect_ignore: test_math_correctness.py, test_posterior_ci.py, test_roi_verdict.py, test_narrative_adapter.py и causal-m* — standalone-скрипты, гонять `python tools/test_X.py` отдельно.
- **Отчёт:** `docs/MATH_AUDIT_v2_1_CORE_REAUDIT.md` [не создан]
- **Коммиты аудита:** узкий pathspec `sidecar/econometrica/** docs/** tools/** AUTONOMOUS_WORK_STATE_MATH_AUDIT.md`. Чужой untracked `src-tauri/src/commands/model_backend.rs` НЕ трогать.

## Реестр находок (дедуп 4 разведчиков + личное чтение; класс: BUG / METHOD-GAP / TRADEOFF / FALSE / ?)

### P0 — математика/оптимизация
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-01 | optimize/inverse.py:499-509 | goal-seek `budget_hi=5×current` в обход safe-коридора → рекомендация в зоне экстраполяции без пометки [ЭКСТРАПОЛЯЦИЯ] (Chan&Perry) | ? METHOD-GAP | — | — |
| F-02 | optimize/inverse.py:360-416 | Delta-CI на бюджет: `response_spread=|f⁺−f⁻|/2 ≈ grad×δ` → `half_width=1.28×spread/|grad| ≈ 1.28×δ` — алгебраически СХЛОПЫВАЕТСЯ в константу ~±6.4% бюджета, «CI» не отражает posterior-неопределённость вовсе | ? BUG/METHOD | — | — |
| F-03 | optimize/inverse.py:419-440 | `p_hit_target` «crude»: при spread=0 → 0.5; ниже цели → линейная доля. Псевдовероятность в UI | ? METHOD/TRADEOFF (в коде помечен MVP) | — | — |
| F-04 | engines/scenario.py:238-301 | Нет guard экстраполяции: сценарий +30% уходит за историч. максимум канала молча (2 независимых источника) | ? METHOD-GAP | — | — |
| F-05 | engines/optimizer.py | CI на mROI есть (:1297-1357); а на сам оптимальный СПЛИТ долей — нет (канон Jin: «доля 38% [27–46%]») | ? METHOD-GAP | — | — |
| F-06 | engines/sensitivity.py:60-176,626 | Sensitivity = детерминированное ±20% возмущение, НЕ posterior-неопределённость; пользователь читает как неопределённость | ? METHOD | — | — |
| F-07 | utils/adstock.py:73-77 | apply_adstock: неизвестный adstock_type тихо падает в geometric (Weibull-конфиг игнорируется без ошибки) | ? BUG | — | — |
| F-08 | utils/adstock.py:47,214-216 | Weibull weights.sum()<1e-12 → uniform-fallback молча (ломает семантику ядра) | ? BUG | — | — |
| F-09 | utils/saturation.py:8-43 | x^α переполнение при больших α/x; γ-floor 1e-10 неадаптивен; α<0 не отвергается | ? BUG (numerics) | — | — |
| F-10 | optimize/inverse.py | Покрытие тестами inverse в tools/ почти нет (только sidecar/tests/test_inverse_*) | ? GAP-тестов | — | — |

### P0 — статистика
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-11 | utils/diagnostics.py | bulk/tail-ESS≥400 НЕ является gate (только R-hat); канон T3.10/Vehtari: при ESS<400 R̂ ненадёжен | ? METHOD-GAP | — | — |
| F-12 | utils/diagnostics.py | E-BFMI (Betancourt, NUTS-only) не реализован | ? METHOD-GAP | — | — |
| F-13 | engines/modeler.py + server.py:903-917 | prior predictive check (reliability_a4) вызывается только в preflight опционально, НЕ в train_model | ? METHOD/verify | — | — |
| F-14 | engines/modeler.py:484-509 | Контрольные priors μ через classify_column-эвристику; fallback μ=0 молча | ? verify | — | — |
| F-15 | engines/decomposer.py:854-855 | Реконструкция контролей: std=0 → деление на ноль без guard | ? BUG | — | — |
| F-16 | engines/decomposer.py:658 + optimizer | Нормировка mean: adstock_mean_posterior (Phase 1.1) vs media_means (legacy) — рассинхрон train↔decompose для старых pickle | ? verify (I8/D4 могут покрывать) | — | — |
| F-17 | utils/ols_bootstrap.py:142-147 | Bootstrap LinAlgError → continue: presence_mask/индекс off-by-one | ? BUG | — | — |
| F-18 | utils/conformal.py | split-conformal exchangeability + plain jackknife (не jackknife+): caveat в коде есть — виден ли пользователю (INV-50)? где потребляется conformal_pi | ? TRADEOFF/honesty | — | — |
| F-19 | engines/decomposer.py:679-684 | count-KPI: kpi_unit_cost предполагается константой во времени, не валидируется | ? METHOD (low) | — | — |
| F-20 | engines/modeler.py:909-942 | posterior extraction fail → y_pred=zeros: маскирует причину, R² аномально низкий без объяснения | ? BUG (obs) | — | — |

### P1-P2 — общая логика
| ID | Где | Гипотеза | Класс | Verify | Fix |
|---|---|---|---|---|---|
| F-21 | server.py:~999 | `consumed_at` нигде не ставится → stale-cleanup мёртв → утечка `_training_tasks` | ? BUG | — | — |
| F-22 | server.py:1041-1091 | result задачи только в памяти (перезагрузка страницы → потеря); cancel не прерывает MCMC-поток | ? verify (может быть by-design: result читается decompose из pickle) | — | — |
| F-23 | engines/validator.py:402-442 | ratio<4:1 и <52 недель — только warning, не gate; канон: 4:1 минимум | ? METHOD/TRADEOFF (optimizer_honesty уже гейтит uncertain) | — | — |
| F-24 | utils/canonical_hash.py:40 | payload с datetime/Decimal → исключение rfc8785 без graceful | ? BUG (low) | — | — |
| F-25 | utils/file_lock.py:67 | re-entrancy по процессу vs потокам — deadlock train+cancel? | ? verify | — | — |
| F-26 | engines/awareness.py | Методология: ESOV Binet&Field, natural decay, лаг, S-кривая — соответствие канону | ? audit | — | — |
| F-27 | граница сайдкар↔Rust | sanitize_nonfinite NaN→null: не искажает ли корректный мат-выход | ? verify | — | — |

### Реестр возможностей (OPP — поручение Антона 2026-07-02: эффективнее/надёжнее/стабильнее/удобнее; НЕ дефекты — рекомендации, вернуться к Антону по итогам)
| ID | Область | Идея | Эффект |
|---|---|---|---|
| OPP-01 | UX | [пример-слот: наполнять по ходу фаз] | — |

### Закрыто в ходе аудита
| ID | Где | Что | Класс | Статус |
|---|---|---|---|---|
| F-29 | tools/test_priors_calibration.py | Дрейф тест-инфраструктуры: файл написан под СТАРУЮ схему synthetic_pilot_data (GROUND_TRUTH_RETAIL→RETAIL_ECOM, generate_retail_chain→retail_ecom, holiday_newyear_preshop→holiday_newyear, apteka_ooh_ots→_contacts, real_estate q1/q4-колонки→baked+дамми из дат) → ImportError → **весь набор калибровки priors молча не гонялся**. Плюс 3 стухших абсолютных допуска (scale-фактор y-нормализации ~2-3× документирован в самом файле; ratio-проверка: comp −0.4533≈2.06×GT, weather 0.3015≈2.5×GT — recovery верный с точностью до масштаба) → приведены к паттерну «знак+bounded+R²» как у FMCG-competitor. | BUG (test-infra) | ✅ FIX, 11/11 passed |
| F-30 | pytest -n auto | 24 xdist-воркера на Windows → гонка загрузки jaxlib-DLL (OSError у части воркеров, «different tests collected») → флаки-развал прогона. Мит: `-n 4`. | ИНЖ (CI-грабля) | ✅ workaround, кандидат в OPP (зафиксировать -n в pytest.ini addopts) |

### Отброшено разведчиками ошибочно / уже покрыто (НЕ переоткрывать)
- ~~сумма декомпозиции ≈ продажам не проверяется~~ → **FALSE**: D1 energy conservation (residual absorption) + test_D1 ×15 seeds.
- ~~ROI без CI~~ → **FALSE** для v1.2+: D12 + test_posterior_ci; для v1.0/1.1 — задокументированная compat-таблица.
- ~~нет тестов scenario/sensitivity~~ → **частично FALSE**: tools/test_scenario_invariants.py, test_scenario_edge_cases.py существуют (разведчик смотрел не туда). Sensitivity — проверить.
- ~~mROAS формула~~ → I6 chain rule ×50 combos покрыт.
- ~~Metropolis-fallback опасен~~ → **TRADEOFF задокументирован**: modeler.py:691-695 «Metropolis НЕ используется как Tier-3» — честный fail MMM_SAMPLER_EXHAUSTED. Windows-режим 2×1000×500 (get_mcmc_params:127) — verify, применяется ли вообще.

## СДЕЛАНО
- 2026-07-02: План одобрен (2 раунда самоаудита R1+R2). Ветка `feat/econ-math-audit` + тег `v-pre-math-reaudit`. Реестр находок собран (27 гипотез, дедуп).

## ОСТАЛОСЬ (next actions, по порядку)
1. **0.0-остаток:** флаг 🔴 в MEMORY.md ядро (компактно, не раздувая >180 строк).
2. **0.1 Среда:** python сайдкара, pymc/jax/arviz, check_compiler() → NUTS/Metropolis; зафиксировать в шапке.
3. **0.2 Baseline:** `pytest tools/ -m "not slow and not integration and not requires_real_data" -n auto` (из корня Dev/Aurora_Econometrica); затем целевые property-based. Красное = находка-регрессия в реестр.
4. **0.3 Критерии:** MATH_REFERENCE.md, SCENARIO_INVARIANTS_REGISTRY.md, MATH_AUDIT_v1_3_PHASE_0_1.md, MATH_AUDIT_v2_0_FORECAST_HORIZON.md, ADR-014/020/021 (по мере надобности в verify, не всё подряд).
5. **0.4 Фикстура:** реальные данные (AURORA_TESTDATA_DIR / pin Кагоцел) или синтетика с ground-truth; обучить; **проверить сходимость ДО использования** (R-hat/ESS/div).
6. **Фаза 1 зонд:** inverse на фикстуре с растущей целью → бюджет за историч. максимум без пометки? (F-01). Параллельно F-02 алгеброй+числом.
7. Фаза 1 verify→fix (F-01..F-10, батч P0 → коммит).
8. Фаза 2 зонд (канарейки R²/MAPE/ROI + ESS-gate) → verify→fix (F-11..F-20, батч → коммит).
9. Фаза 3 (F-21..F-27, батч → коммит).
10. Фаза 4: отчёт MATH_AUDIT_v2_1_CORE_REAUDIT.md + реестры инвариантов + полный gate `pytest tools/ -n auto` + smoke на фикстуре в двух режимах + отчёт Антону **вкл. раздел «Рекомендации» из реестра OPP (эффективность/надёжность/стабильность/удобство — поручение 2026-07-02)**.

## Грабли и решения
- pytest гнать из корня `Dev/Aurora_Econometrica` (pytest.ini: testpaths=tools). В tools/ свой conftest — проверить sys.path к sidecar/econometrica.
- Правки БЕЗ слома pickle-compat (1.0/1.0-ols/1.1/1.1.5/1.2/1.3) и детерминизма (I4/D13).
- Guard экстраполяции — мягкий (пометка+CI), не блокирующий.
- pin Кагоцел: если методологическая правка легитимно меняет число — переустановить pin С ОБОСНОВАНИЕМ (правка+первоисточник), не подгонять молча.
- Два режима движка (planning Option C / analyst Hill-of-mean) — правки проверять в обоих.

## Аудит-чеклист финала
- [ ] Все 27 находок реестра имеют класс + verify-статус (нет «?»)
- [ ] Все BUG/METHOD-GAP исправлены ИЛИ осознанно отложены с записью причины
- [ ] Методологические правки — с RAG-атрибуцией (или честный [ASSUMED] fallback)
- [ ] Каждая правка — характеризующий тест в tools/
- [ ] Реестры инвариантов пополнены (формат statement/rationale/test)
- [ ] Полный `pytest tools/ -n auto` зелёный; pin Кагоцел объяснён
- [ ] Smoke пайплайна на фикстуре в двух режимах
- [ ] Отчёт Антону: находки/правки/атрибуции/остаточные риски + раздел «Рекомендации» (OPP)
