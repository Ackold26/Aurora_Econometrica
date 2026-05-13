# Aurora MMM Optimizer — v2.1.0+ Roadmap

**Дата:** 2026-05-14
**Author:** Маша маленькая
**Status:** DRAFT — обсуждение приоритизации с Антоном
**Reference:** `V1_4_0_EXPLICIT_MODE_PLAN.md` (deprecated), `GAP_ANALYSIS_v1.md`

---

## Контекст

После ship v2.0.0 (~4 недели: wizard refactor + signed factors UI + forecast по плану + backtest + MCMC + PPC + holidays + sensitivity tornado + reuse существующих наработок) — следующие фазы по 2-3 недели каждая.

**Принцип ранжирования:**
- **Customer value** (HIGH / MEDIUM / LOW) — насколько часто запрашивается
- **Effort** (дней)
- **Industry standard?** — есть ли у Robyn / LightweightMMM / Nielsen / PyMC-Marketing
- **Aurora reuse** — насколько код уже готов

---

## v2.1.0 sprint — Math depth + agency workflow (~2-3 недели)

**Тема:** математическая полнота + повседневный agency workflow.

| # | Feature | Customer value | Effort | Industry | Aurora reuse | Описание |
|---|---|---|---|---|---|---|
| 1 | **Refresh capability** | HIGH | 2-3d | ✅ Robyn `robyn_refresh()` | 70% (Save/Load готов) | Customer добавил 4 новые недели данных → re-fit без полного retrain. Warm-start MCMC: использовать предыдущий posterior как prior. Agency workflow: квартальный refresh клиентской модели |
| 2 | **Synergy / interaction effects** | MEDIUM | 3-5d | ✅ PyMC-Marketing explicit, Robyn paired | 30% (model_spec extension) | TV × Digital interaction term. "TV boosts Digital CTR" — реальная синергия которая в standalone MMM игнорируется |
| 3 | **Pareto frontier (multi-objective)** | MEDIUM | 3d | ✅ Robyn flagship | 50% (optimizer extension) | Trade-off ROI vs reach vs share-of-voice. Sophisticated clients защищают планы перед board как «здесь оптимальная точка между N целями» |
| 4 | **Prior sensitivity analysis** | MEDIUM | 2d | ⚠️ Bayesian standard, рare в UI | 40% | Изменить prior strength на adstock TV ±20%, посмотреть как меняется ROI. Defensibility: «модель не зависит от моих subjective priors» |
| 5 | **Bootstrap coefficient stability** | MEDIUM | 2d | ⚠️ Robyn distribution plots | 30% | Bootstrap N runs → distribution per-channel ROI. Показать «90% бутстрапов даёт ROI TV в диапазоне 2.1-2.8» |
| 6 | **Robustness testing** (alternate spec) | LOW-MED | 2-3d | ⚠️ Robyn DECOMP.RSSD | 50% | Run model with Geometric vs Weibull adstock → сравнить результаты. Если ROI estimates differ >30%, flag instability |

**Subtotal v2.1.0:** ~14-18 дней = 3-3.5 недели.

**Outcome:** Aurora становится equivalent of **Robyn в math depth** + UX preserved.

---

## v2.2.0 sprint — Quality of life & agency productivity (~3 недели)

**Тема:** ежедневный agency workflow + customisation. **Идёт сразу после v2.1.0** — даёт agency analyst daily-use инструмент прежде чем расширять math.

**Перемещено сюда из старого v2.3.0** (Антон 2026-05-14): customer value daily workflow выше чем advanced math extensions.

| # | Feature | Customer value | Effort | Industry | Reuse |
|---|---|---|---|---|---|
| 7 | **Multi-scenario сравнение dashboard** | HIGH (agency) | 3d | ✅ Robyn | 40% (chart overlay есть) | Side-by-side: «План А vs План B vs Aurora-optimized» — table + twin chart + diff analysis |
| 8 | **Project templates / favorites** | MEDIUM | 2d | ⚠️ Robyn templates | 30% | Agency сохраняет «Шаблон Кагоцел-OTC» → applies к похожему клиенту за 30 секунд |
| 9 | **Custom adstock functions** | LOW-MED | 3d | ⚠️ varies | 60% | Beyond Geometric/Weibull: LogNormal, Gamma adstock для специфических каналов |
| 10 | **Categorical KPI customization** | MEDIUM | 2-3d | ❌ | 50% | Customer добавляет свой KPI type с custom auto-suggest формулой value_per_count_unit |
| 11 | **Custom calibration via priors (UI)** | MEDIUM | 3-4d | ⚠️ varies (in code) | 40% | UI для эконометриста/Expert: override prior per channel («я знаю что TV ROI этого бренда исторически 2.0-2.5, поставлю tight prior») |
| 12 | **Posterior comparison across model versions** | MEDIUM (agency) | 2d | ❌ rare | 50% | Версия A vs B side-by-side: «модель чувствительна к priors? насколько?» |

**Subtotal v2.2.0:** ~15-20 дней = 3-4 недели.

**Outcome:** Aurora становится **daily-use инструментом** для agency analyst — обучить, refresh, сравнить версии, кастомизировать под клиента, использовать templates для повторяемости.

---

## v2.3.0 sprint — Extension to multi-context (~4 недели)

**Тема:** масштабирование на multi-region / multi-SKU / time-varying. **Перемещено сюда из старого v2.2.0** (Антон 2026-05-14): advanced math extensions — после daily workflow.

| # | Feature | Customer value | Effort | Industry | Aurora reuse |
|---|---|---|---|---|---|
| 13 | **Time-varying coefficients (TVP)** | HIGH | 5-7d | ✅ PyMC-Marketing | 40% (math additions) | Effectiveness каналов меняется со временем (TV ROI в 2021 vs 2025 — разный). Stochastic / random-walk priors на β. **Эконометристы заметят отсутствие у Aurora** |
| 14 | **Multi-region hierarchical** | HIGH (для крупных FMCG) | 5-7d | ✅ LightweightMMM сильнейшее | 20% (требует data structure change) | Cross-market hierarchy: shared priors на категорию + per-region delta. Большая FMCG которая работает в нескольких странах / регионах |
| 15 | **Cross-validation (k-fold time series CV)** | MEDIUM | 3d | ⚠️ Robyn ridge CV | 50% | Time-series CV (rolling origin), не только single holdout. Дополнительная защита против overfitting |
| 16 | **Drift detection** | MEDIUM | 2-3d | ❌ rare | 30% | Customer добавил новые данные — Aurora детектирует если distribution drift >threshold |
| 17 | **Custom likelihood (Poisson / Negative Binomial для low-count)** | MEDIUM | 2-3d | ⚠️ PyMC-Marketing | 60% (modeler extension) | Если weekly count <50 (B2B лиды) — Gaussian неточный. Poisson / NB более подходят |
| 18 | **Coverage forecast (reach / frequency)** | MEDIUM | 3d | ⚠️ Nielsen | 0% | Не только sales forecast, но reach/frequency forecast для брендовых задач |

**Subtotal v2.3.0:** ~20-26 дней = 4-5 недель.

**Outcome:** Aurora обходит PyMC-Marketing в полноте math features + добавляет multi-context (region/SKU).

---

## v3.0.0+ — Strategic investments (требует commitment)

**Тема:** market positioning / partnerships / infrastructure.

| # | Feature | Customer value | Effort | Industry | Описание |
|---|---|---|---|---|---|
| 19 | **Industry benchmarks library** | HIGH | partnership + 5d code | ✅ Nielsen, BASES | Partner с Nielsen / Mediascope / Kantar для category-level benchmarks. «Ваш TV ROI 2.5 — в норме для OTC категории (медиана 2.3, IQR 1.8-3.0)». Это **major positioning shift**: Aurora не только инструмент, но и authoritative reference. **Требует commercial partnership** |
| 20 | **Programmatic REST API** | LOW сейчас, HIGH after scale | 5-7d | ✅ enterprise tools | Aurora API для customer integration. Сейчас 1 agency customer — нет demand. После 10+ — критично |
| 21 | **Collaboration / multi-user / team workspace** | MEDIUM-HIGH (large agencies) | 7-10d | ⚠️ varies | Несколько analysts одного агентства на одном проекте + permissions + change history |
| 22 | **Multi-currency** | LOW (РФ-focus) | 2-3d | ✅ global tools | USD / EUR / экспортные продукты. Не блокирует, но при выходе на CIS / Балканы — нужно |
| 23 | **White-label / agency branding** | MEDIUM (Антон сказал 10% use case) | 3-4d | ⚠️ enterprise | Logo agency в reports, custom color scheme, branded landing pages. Для агентств которые продают output клиенту как their deliverable |
| 24 | **Wordstat / Yandex Direct integration** | MEDIUM | 4-5d | ❌ unique to РФ | Auto-fetch Wordstat brand metrics, не требовать customer уlozjit'ed вручную |
| 25 | **Public data sources** (Rosstat / ЦБ макро) | LOW-MED | 3d | ⚠️ Nielsen | Auto-fetch CPI / GDP / FX для использования как macroeconomic factor |

---

## v3.x+ — Aspirational / cross-product

**Тема:** Aurora Econometrica platform features.

| # | Feature | Описание |
|---|---|---|
| 26 | **Cross-product portfolio view** | После Brand Tracker + Trade & Pricing live: combined dashboard «общий ROI медиа + ценовой elastic + brand equity» — Portfolio как функция Platform Core (per ADR-012) |
| 27 | **Causal inference modules** | Beyond MMM correlation: difference-in-differences, synthetic control, RCT integration. Critical для proving causality в litigated cases |
| 28 | **Marketing attribution integration** | Aurora MMM + multi-touch attribution (touch-level conversion data) → unified view. Большая методологическая работа |
| 29 | **Predictive customer segmentation** | LTV-based segmentation + per-segment ROI. Cross-pollination с Aurora Brand Tracker |
| 30 | **Auto-ML hyperparameter tuning** | Современный AutoML для prior selection / model spec selection |

---

## Summary timeline

| Sprint | Когда | Длительность | Тема |
|---|---|---|---|
| **v2.0.0** | 2026-05 — 2026-06 | ~4 недели | Wizard + foundation + signed factors + forecast + backtest + holidays + sensitivity |
| **v2.1.0** | 2026-06 — 2026-07 | ~3 недели | Refresh + synergy + Pareto + sensitivity analysis + bootstrap (math depth) |
| **v2.2.0** | 2026-07 — 2026-08 | ~3 недели | Multi-scenario + templates + custom adstock + KPI customization + priors UI (**daily workflow**) |
| **v2.3.0** | 2026-08 — 2026-09 | ~4 недели | TVP + multi-region + CV + drift + custom likelihood + coverage (advanced math) |
| **v3.0.0+** | 2026-Q4+ | ongoing | Benchmarks partnership, API, collaboration, multi-currency, white-label |

**Total Optimizer roadmap:** ~4 месяца до feature-complete версии = end Q3 2026.

**Логика sequence (Антон 2026-05-14):** после math depth (v2.1.0) — сразу daily workflow features (v2.2.0) которые делают product daily-useable для agency. Multi-context extensions (TVP, multi-region — v2.3.0) — sophisticated, требуют customers которые этого хотят.

---

## Cross-product implications

После реализации многих фич в Optimizer — **shared library** материал для всей линейки Econometrica:

| Feature | Reuse в Launch Planner | Reuse в Brand Tracker | Reuse в Trade & Pricing |
|---|---|---|---|
| ScenarioWizard | ✅ полностью | ✅ полностью | ✅ полностью |
| Signed factors | ✅ нужен | ✅ нужен | ✅ нужен |
| Forecast continuation chart | ✅ нужен | ✅ нужен | ✅ нужен |
| MCMC diagnostics | ✅ нужен | ✅ нужен | ✅ нужен |
| Holiday dummies | ✅ нужен | ✅ нужен | ✅ нужен |
| Sensitivity tornado | ✅ нужен | ✅ нужен | ✅ нужен |
| Refresh capability | ⚠️ Launch обычно single-shot | ✅ нужен | ✅ нужен |
| TVP | ✅ нужен | ✅ нужен | ⚠️ less |
| Multi-region | ✅ нужен | ✅ нужен | ✅ нужен |
| Industry benchmarks | ✅ нужен | ✅ нужен | ✅ нужен |

**Implication:** многое из v2.0.0 / v2.1.0 features должно строиться **как shared library** (eventually in Aurora Platform Core), а не Optimizer-only код. Это даёт **значительный leverage**: одно implementation работает в 4-х продуктах.

**Trigger миграции в Platform Core** (per ADR-012 decision 3): 1-2 успешных пилота Launch / Brand Tracker на Platform Core с NPS ≥ 7. К моменту v2.2.0+ для Optimizer — Platform Core уже должен быть battle-tested. Тогда v2.2.0+ features можно сразу строить на Platform Core.

---

## Открытые вопросы

**Q1.** v2.1.0 — все 6 пунктов или урезать? Customer value высокий у refresh, synergy, sensitivity analysis. Pareto / bootstrap / robustness — nice-to-have.

**Q2.** v2.2.0 — приоритет TVP vs Multi-region? Оба HIGH value но разный target customer. TVP — для долгих historical periods. Multi-region — для крупных cross-market клиентов.

**Q3.** v3.0.0+ Industry benchmarks — стратегическая партнёрская инвестиция. Кто потенциальные партнёры в РФ (Mediascope? Kantar? Nielsen?) и насколько готовы share data?

**Q4.** Cross-product migration — когда Optimizer переедет на Platform Core? Решение должно быть после v2.1.0 (~3 месяца с момента ship v2.0.0).

**Q5.** Дополнительные items которые я не учла — что Антон хочет добавить?

---

## Что я не включила (намеренно или забыла)

Brain-storm: что ещё может быть в roadmap, что не вошло в список?

- **AI-powered insights** (LLM analyses results, narrative auto-generation) — risky positioning «AI does decisions», но customers любят это
- **Plan optimization on Pareto frontier** (выбрать точку на Pareto curve interactively) — премиум UI
- **What-if simulator with sliders** (already есть basic ScenarioPlayground)
- **Customer success metrics tracking** (NPS, churn, expansion ARR) — для self-monitoring продукта
- **Automatic insight prioritization** (top-N actionable recommendations, не raw stats)
- **Anomaly detection in raw data** (flag unusual spikes / dips перед training)
- **Pre-flight data quality scoring** (single score 0-100 «качество ваших данных») — easier чем серия warnings
- **Channel mix templates** (preset «classic FMCG mix», «modern DTC mix» как starting point)
- **«Recommendation explorer»** — interactive UI где customer может тестировать разные «what-if» предложения от Aurora
- **Audit trail для regulators** (compliance: какие данные, какие модели использованы, версионирование решений)

Это items для discussion. Что resonates с твоим vision?
