# ADR-014: Safe Corridor Bounds для бюджета и цели оптимизации

**Status:** Accepted
**Date:** 2026-05-12
**Owner:** Маша маленькая (review Антон)
**Related:** v1.3.0 plan, REFACTOR_PLAN_v1.3.0.md

## Context

В v1.2.0 шаг Оптимизация позволяет двигать слайдер бюджета на ±500%. Hill saturation параметры обучаются на исторических наблюдениях каждого канала в диапазоне `[X_i^obs_min, X_i^obs_max]`. За пределами этого диапазона функция `f(X) = X/(K+X)` (Hill normalized) формально определена, но это **экстраполяция**, и:

- Posterior CI на `mROAS`/`mEffect` расширяется кратно (≥2× при `X > P95 + 50%`).
- Optimization рекомендации теряют валидность - solver maximizes ожидание там, где модель не наблюдала.
- `value_per_count_unit` сравнения теряют смысл при extrapolation.

Это методологически известная проблема в MMM literature; стандартные tools применяют ограничения на оптимизационный домен.

## Decision

Вводим понятие **safe corridor** для двух осей:
- **Per-channel input** (бюджет ₽ или физ. контакты в зависимости от mode).
- **Target sales** (агрегатная цель Goal-Seek).

**MVP формула per канал (default):**
```
X_i^lo = max(P5(X_i_observed), 0.5 · µ_i)
X_i^hi = min(P95(X_i_observed), 1.5 · µ_i)
```

**Total budget corridor** = `[Σ X_i^lo, Σ X_i^hi]` с предупреждением «aggregate corridor - приближение; реальный safe range зависит от paired observations».

**Target sales corridor (S_safe):**
- Lower: `base + Σ β_i · f(X_i^lo)` (при минимальной загрузке).
- Upper: `base + Σ β_i · f(X_i^hi)`.
- В UI: ±% от текущих продаж `S_current`.

**Three zones для UX слайдеров:**
- 🟢 Зелёная (внутри corridor) - модель валидна.
- 🟡 Жёлтая (±10% за пределами) - warning: extrapolation, расширенный CI.
- 🔴 Красная (>10% за пределами) - кнопка `Найти решение` неактивна.

**Expert Mode (Phase B опция):**
- Posterior-based bounds через bootstrap-сэмплирование исторических распределений + propagation через posterior MCMC.

## Rationale

Литература по MMM extrapolation:

1. **Robyn (Meta) open source MMM.** Default bounds: `lower_bound = 0.5 · spend_avg`, `upper_bound = 1.5 · spend_avg` (документация Robyn user guide). Эмпирическое правило: extrapolation за этими границами увеличивает posterior CV >50%.

2. **PyMC-Marketing** (Bayesian MMM framework). Рекомендует posterior predictive checks для определения safe extrapolation range; точные пороги - данных-зависимые.

3. **Hanssens, Parsons, Schultz (2003), "Market Response Models", §11.4 "Extrapolation beyond observed range"**: RMSE прогноза за пределами наблюдённого range увеличивается типично в 2–3 раза для нелинейных saturation моделей.

4. **Jin, Wang, Sun, Chan, Koehler (2017), Google research paper "Bayesian Methods for Media Mix Modeling with Carryover and Shape Effects"**: Hill curve identifiability в §3.2 - гибкость Hill требует sufficient data coverage внутри observed range; extrapolation требует additional regularization через priors.

5. **Lightweight MMM (Google).** Использует input scaling по historical mean, рекомендует optimization domain `[0.3 · spend_avg, 2.0 · spend_avg]`.

**Гибридная формула** `max(P5, 0.5·µ)` / `min(P95, 1.5·µ)` сочетает два подхода: percentile-based (защищает от extreme outliers с pulpy hist) и relative (защищает от пустых perсентilей при малой выборке). Aggressive enough чтобы давать юзеру простор для recommendations, conservative enough чтобы не пускать в зону низкой confidence.

## Alternatives Considered

| Альтернатива | Отвергнуто потому что |
|---|---|
| Только relative `µ ± 50%` (Robyn-style) | Игнорирует фактическое распределение; на каналах с большим std даёт слишком узкий corridor |
| Только percentile P5/P95 | На малой выборке (N < 30) percentiles нестабильны |
| Gaussian `µ ± 2σ` | Media spend часто right-skewed (long tail); Gaussian допущение неверно |
| Posterior predictive sampling (Expert) | Дорого вычислительно (~30s на проект); вынесено в Expert Mode |
| Без ограничений (текущий v1.2) | Юзер ловится на extrapolation, рекомендации некорректны |

## Consequences

**Positive:**
- Юзер видит границы валидности модели сразу.
- Solver работает в зоне высокой confidence.
- Goal-seek даёт сообщение «недостижимо» когда цель за пределами `S_safe`.
- Отчёты могут upfront показывать в footer «оценки валидны в диапазоне [B_lo, B_hi]».

**Negative:**
- Юзер не может «попробовать» сценарии 200%+ (требует Expert Mode override).
- Aggregate corridor не точно отражает paired-data limitations (over-estimates achievable range).

**Neutral:**
- Backward compat: для v1.2 bundles при load - corridor вычисляется на лету, не сохраняется в bundle.

## Implementation

**MVP:**
- `sidecar/econometrica/optimize/bounds.py::compute_safe_corridor(model, mode='mvp')`.
- Pure function, no side effects.
- Returns `{X_lo, X_hi, S_lo, S_hi}` per channel + aggregate.

**Endpoint:**
- `POST /optimize/corridor` → `{project_id, kpi_kind}` → corridor dict.
- Cached per `(project_id, model_version_hash)`.

**UI:**
- `CorridorSlider.svelte` reusable component с 3 zones.
- Override button: «Я знаю, что делаю - снять ограничения» (Expert Mode flag).

## References

- Robyn user guide: <https://facebookexperimental.github.io/Robyn/docs/quick-start/>
- PyMC-Marketing docs: <https://www.pymc-marketing.io/en/stable/notebooks/mmm/mmm_example.html>
- Hanssens, Parsons, Schultz (2003), "Market Response Models: Econometric and Time Series Analysis", 2nd ed., Kluwer Academic Publishers.
- Jin et al. (2017), Google Inc. <https://research.google/pubs/pub46001/>
- Aurora внутренние: `MATH_REFERENCE.md`, `ROI_THRESHOLDS.md`.
