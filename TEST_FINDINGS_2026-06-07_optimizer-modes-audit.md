# TEST FINDINGS — аудит корректности режимов оптимизатора (#4/#8, 2026-06-07)

**Задача:** глубокий сенситивный аудит корректности математики режимов оптимизатора.
**Метод:** probe-first на реальном Кагоцел pickle (`models/latest.pkl`) — прогон движков
`engines.optimizer.optimize` (forward «От бюджета») и `optimize.inverse.optimize_inverse`
(goal-seek «От цели») детерминированно, без GUI. («От задачи»/planner-analyst = чат-слой
кабинета econometrist, не отдельная математика — вне этого math-аудита.)

## ✅ ВЕРДИКТ: математика обоих движков — ЗДОРОВА

**Forward `optimize()` («От бюджета»):**
- Монотонность total_optimal_kpi по бюджету: 0.5×→11.54B, 1×→11.74B, 2×→11.90B ✓
- 5× → корректный `INFEASIBLE_BUDGET_HIGH` (при max_pct=200 нельзя потратить 5× — правильное
  поведение ограничений, НЕ баг)
- lift ≥ 0 (оптимум ≥ текущего): optimal 11.742B ≥ current 11.105B ✓
- Границы min20/max200 соблюдены (все delta_pct ∈ [-80,+100]) ✓
- Воспроизведён optimization.json ТОЧНО (с override CPP 94238): current 2 342 802 669,
  optimal 11 735 141 568, lift 5.7% ✓

**Goal-seek `optimize_inverse()` («От цели»):**
- round-trip ошибка **0.02%** (target = S(1.5×) → найденный budget ≈ 1.5×) ✓
- потолок достижимости (fallback_max_sales/budget) корректен ✓
- bisection монотонна (proportional forward монотонен по построению — GS-1 фикс держится) ✓

**Семантика reallocate vs proportional:** forward(reallocate) ≥ goal-seek(proportional) при
одном бюджете/CPP (11.896B ≥ 11.894B @2×) ✓ — реаллокация никогда не хуже фикс. микса.

## 🟡 НАХОДКА (cross-mode, INV-50-класс): нет единого источника CPP → forward и goal-seek расходятся по «текущему бюджету»

**Симптом (live-подтверждён):** на вкладке «От бюджета» текущий бюджет = **2.34 млрд** ₽;
goal-seek «От цели» строит коридор/потолок на текущем = **2.91 млрд** (потолок «бюджет 14.6 млрд»
= 5×2.91). Расхождение ~24% на одном экране оптимизации.

**Корень — три расходящихся источника unit_costs (CPP для TRPs):**
| Источник | TRPs CPP | Текущий бюджет | Кто читает |
|---|---|---|---|
| pickle `cfg.unit_costs` (заморожено при обучении) | 120000 | 2.91 млрд | **goal-seek** (`build_proportional_forward` → `cfg`) |
| `project.json.unit_costs` | **{}** (пусто!) | — | фронт-store при загрузке проекта |
| runtime `optimization.json` (последний прогон) | 94238 | 2.34 млрд | **forward** (получил override из рантайм-store) |

- Forward `optimize()` получает `unitCosts` из рантайм-store (94238) — это на экране «От бюджета».
- Goal-seek `optimize_inverse` НЕ принимает unit_costs (ни JS-invoke, ни Rust `econ_optimize_inverse`,
  ни `InverseOptimizeRequest`, ни функция) → `build_proportional_forward` читает pickle `cfg` (120000).
- project.json пуст → CPP нигде не персистится консистентно; forward'ский 94238 — сессионный.

**Почему не фиксил сразу (не over-build):** «пробросить unit_costs в goal-seek» (5 слоёв:
JS→Rust→endpoint→optimize_inverse→build_proportional_forward, аддитивно) сделает их согласованными
В РАНТАЙМЕ, но НЕ устранит корень — отсутствие персистентного SSOT для CPP (project.json={}, pickle≠runtime).
Какой источник канонический — **архитектурное решение Антона** (одна из 3 тем для вопроса).

**Опции фикса (для решения):**
- (A) Рантайм-консистентность: пробросить тот же `unitCosts` store в goal-seek (5 слоёв, аддитивно).
  Быстро согласует две вкладки, но CPP по-прежнему не персистится.
- (B) Персистентный SSOT: optimize-time derivation пишет CPP в project.json; оба движка + декомпозиция
  читают один источник. Правильный фикс, больше объёма (тот же приём, что MQS/ratio/decomposition_series).
- (C) Оба читают training-snapshot (pickle) — но это игнорирует «текущие цены ≠ тренировочные».

**Severity:** 🟡 (не краш; математика верна). Влияет на budget-числа goal-seek (потолок, рекомендация
бюджета) — завышены на ~CPP-ratio. Не критично, но это displayed-number-консистентность (тема rc10).

## Сопутствующее наблюдение (не дефект)
При бюджете ≥2× forward вынужден лить +100% даже в убыточный TRPs (mROI 0.11×) — потому что
профитные каналы упёрты в max_pct=200, а Σ=бюджет. Математически корректно (constraint-driven),
но контринтуитивно. Кандидат на UX-подсказку, не на math-фикс.

## ✅ ФИКС РЕАЛИЗОВАН (опция B — персистентный SSOT для current CPP)
Решение Антона: B (правильный). Реализовано в 2 этапа:
- **B-core** (`4be3290`, tag `v-fix-cpp-ssot-goalseek-core`): `_resolve_current_unit_costs` —
  единый SSOT (override > project.json.unit_costs > pickle cfg fallback); goal-seek
  `build_proportional_forward` берёт current CPP отсюда (uc_snap остаётся для Hill).
  Probe: project.json CPP=94238 → goal-seek current 2.34B (= forward); пустой → cfg 120000. +6 pytest (361).
- **B-persist** (`f1d9ed0`, tag `v-fix-cpp-ssot-persist`): `OptimizeStep.runOptimize` после optimize
  персистит current CPP в project.json через `project_update` (пересчитывает `_jcs_sha256`). project.json
  = SSOT; авто-бэкфилл любого проекта при optimize. svelte 0E, vitest 696.
- **B3 consumer audit:** forward/decompose/report → store(=project.json); goal-seek → project.json. Консистентно, код-правок нет.

**Остаток (гейт Антона):** bulk-backfill 116 проектов с пустым project.json (hash-aware через
project_update, не сырой Python — иначе ломается JCS-хеш) + **live-верификация при сборке rc10**
(B-core в sidecar, B-persist в JS — войдут в билд). Edge: goal-seek ДО первого optimize на
свеже-выведенном (не сохранённом) CPP читает project.json/cfg, не свежий store — `optimize_inverse`
уже принимает `unit_costs` (override готов к 3-слойному пробросу JS→Rust→endpoint, если понадобится).

## Гейты
probe-аудит на реальном pickle (system Python scipy 1.17.1). Фикс B: pytest 361, svelte 0E, vitest 696.
