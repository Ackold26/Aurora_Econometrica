# Gap Analysis: Aurora MMM Optimizer vs Industry Standards

**Дата:** 2026-05-14
**Author:** Маша маленькая
**Reference set:** Meta Robyn, Google LightweightMMM, PyMC-Marketing, Nielsen BASES, Kantar MMM tools

---

## TL;DR

Aurora покрывает **~70%** того, что есть в industry standards. **Серьёзные gaps:**

1. **Signed factors** (конкуренты / цена / макро) — добавляем в v2.0.0 (только что согласовали).
2. **Out-of-sample validation** (backtest) — критично для доверия, скорее всего отсутствует визуально.
3. **MCMC convergence диагностика** (R-hat, ESS, trace plots) — Bayesian must-have.
4. **Time-varying coefficients** — эконометристы знают что ROI каналов меняется со временем.
5. **Synergy / interaction effects** (TV × Digital) — большая тема в современном MMM.
6. **Posterior predictive checks** (actual vs predicted distribution diagnostic plots).
7. **Holiday / event dummies** (Новый Год / 8 марта / Чёрная Пятница) — РФ-специфика.
8. **Sensitivity tornado** — какие параметры больше всего влияют на ROI.
9. **Multi-scenario сравнение side-by-side**.
10. **Save/Load обученной модели** без переобучения.

---

## §1 Comparative analysis (8 категорий)

### 1. Mathematical / Modeling features

| Feature | Aurora | Robyn | LightweightMMM | PyMC-Marketing | Nielsen BASES | Gap для Aurora |
|---|---|---|---|---|---|---|
| **Bayesian framework** | ✅ PyMC + JAX | ⚠️ Ridge + multi-objective | ✅ NumPyro | ✅ PyMC | ⚪ Proprietary | OK |
| **Adstock (Geometric)** | ✅ | ✅ | ✅ | ✅ | ✅ | OK |
| **Adstock (Weibull)** | ✅ | ✅ | ✅ | ✅ | ⚪ | OK |
| **Hill saturation** | ✅ | ✅ | ✅ | ✅ | ✅ | OK |
| **Hierarchical priors** | ✅ (Trust 3) | ✅ | ✅ | ✅ | ✅ | OK |
| **Time-varying coefficients** | ❌ time-invariant | ⚠️ refresh trick | ❌ | ✅ stochastic | ⚠️ rolling | **GAP**: эффективность TV в 2021 vs 2025 разная — нужны TVP-priors |
| **Synergy / interaction effects** | ❌ | ⚠️ paired channels | ❌ | ✅ explicit interactions | ✅ | **GAP**: TV × Digital interaction — фундаментальная тема |
| **Multi-region hierarchical** | ❌ single TS | ❌ | ✅ geo-level | ⚠️ extensible | ✅ markets | **GAP** (отложим в v2.x): multi-market support |
| **Lagged variables (non-media)** | ⚠️ только media | ⚠️ ad-hoc | ⚠️ | ✅ | ✅ | **GAP**: distribution lag, price lag |
| **Long-term brand effect** | ❌ только adstock | ⚠️ trend layer | ❌ | ⚠️ | ✅ brand equity | **GAP**: brand effect beyond adstock (~Brand Tracker scope, но cross-pollination нужно) |
| **Holiday / event dummies** | ⚠️ residual shock dummies (manual) | ✅ prophet auto | ⚠️ | ⚠️ | ✅ | **GAP**: автоматический detector РФ-праздников |
| **Macroeconomic factors** | ⚠️ CPI deflation only | ⚠️ exogenous regressors | ⚠️ | ⚠️ | ✅ | **GAP**: CPI / GDP / FX как drivers, не только дефляция |
| **Out-of-stock handling** | ❌ | ⚠️ via distribution proxy | ❌ | ⚠️ | ✅ | **GAP** (отложим): availability как explicit factor |
| **Signed control factors** | ❌ (текущий gap) | ✅ | ✅ | ✅ | ✅ | **GAP v2.0.0** (согласовано) |

**Aurora score:** 6/14 strong, 6/14 weak/missing. **Главный gap:** signed factors (закрываем v2.0.0), time-varying coefficients (v2.1.0+), synergy effects (v2.1.0+).

### 2. Variable / Data handling

| Feature | Aurora | Industry standard | Gap |
|---|---|---|---|
| **Variable type detection** | ⚠️ ограниченный column_detection | ✅ Robyn semi-auto, manual override | **GAP**: расширяем classifier в v2.0.0 (согласовано) |
| **Signed factor handling** | ❌ | ✅ | **GAP v2.0.0** (согласовано) |
| **Multi-currency** | ⚠️ ₽ only | ✅ Robyn / Nielsen | **GAP** (отложим): USD / EUR / экспортные продукты |
| **Mixed-frequency data** | ✅ Chow-Lin / Denton (per task profile) | ⚠️ varies | OK |
| **Holidays / events library** | ❌ | ✅ Robyn (prophet) | **GAP**: РФ-календарь holiday dummies автоматом |
| **Sample weighting** | ❌ | ⚠️ Robyn manual, Bayesian via prior | **GAP** (низкий приоритет) |
| **Categorical channels** | ⚠️ implicit | ✅ | OK |
| **Cross-product / portfolio** | ❌ | ⚠️ varies | (Aurora Portfolio = функция платформы, отдельно) |

### 3. Output / Visualization

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **ROI per channel + CI** | ✅ | ✅ | OK |
| **Decomposition stack** | ✅ | ✅ | OK (расширяем до signed) |
| **Response curves** | ✅ ResponseCurves.svelte | ✅ | OK |
| **Forecast continuation chart** | ⚠️ ScenarioPlayground only | ✅ | **GAP**: добавляем v2.0.0 (согласовано из последнего скрина) |
| **Negative bars (signed)** | ❌ | ✅ | **GAP**: согласовано |
| **Sensitivity tornado chart** | ❌ | ✅ Robyn output | **GAP**: какие parameters больше всего влияют на ROI — must для defensibility |
| **Posterior predictive checks (PPC)** | ❌ | ✅ standard Bayesian | **GAP**: actual vs predicted scatter + residuals — must для Bayesian trust |
| **Convergence diagnostics (R-hat / ESS / trace plots)** | ⚠️ есть в backend, в UI скрыто | ✅ standard | **GAP**: surface в UI хотя бы в Expert mode |
| **Cost curves (для count KPI)** | ⚠️ CPU есть | ✅ | OK |
| **Saturation point indicator** | ✅ светофор | ⚠️ varies | OK |
| **Multi-scenario side-by-side** | ❌ | ✅ Robyn `robyn_response()` | **GAP**: загрузил 3 плана → сравнить таблицей + графиком |
| **Channel contribution waterfall** | ❌ | ✅ | **GAP**: waterfall summary в отчёте |
| **Validation plots (actual vs predicted)** | ⚠️ residual diagnostics в backend | ✅ | **GAP**: surface в UI |

### 4. Workflow / UX

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **Wizard / guided setup** | ❌ (текущий gap) | ⚠️ Robyn template | **GAP**: ScenarioWizard в v2.0.0 (согласовано) |
| **Auto data detection** | ⚠️ partial | ⚠️ varies | **GAP**: расширяем classifier (согласовано) |
| **Save/Load trained model** | ❓ unclear (Phase B persistence) | ✅ Robyn `robyn_save()` | **GAP**: критично для agency workflow (обучил один раз, применяет к разным планам) |
| **Model versioning** | ❌ | ⚠️ Robyn version tags | **GAP**: track какая модель чем отличается (для repeat customers) |
| **Refresh capability** | ❌ (full retrain) | ✅ Robyn `robyn_refresh()` | **GAP**: добавить новые недели данных без полного reMatch — экономия времени |
| **Multi-scenario / compare runs** | ❌ | ✅ | **GAP**: сравнить 2-3 модели (different priors / different period) |
| **Project templates / favorites** | ❌ | ⚠️ Robyn template files | **GAP** (опционально): для agency повторяемости |
| **Collaboration / multi-user** | ❌ | ⚠️ varies | **GAP** (отложим): команды агентств |

### 5. Reporting / Certification

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **HTML report** | ✅ | ✅ | OK |
| **PPTX report** | ✅ | ⚠️ rarely | OK (наше преимущество) |
| **Methodology Certificate + verifier** | ✅ | ❌ unique | OK (наше преимущество) |
| **Executive summary auto-generation** | ⚠️ SCQAR section | ✅ Nielsen one-pager | **GAP**: 1-pager 5-bullet summary для C-level |
| **Confidence levels per insight** | ⚠️ Bayesian CI exists | ✅ | **GAP**: «90% уверены ROI TV > 2.0» textual flagging |
| **Audit log** | ❌ | ⚠️ varies | **GAP** (compliance) |
| **White-label / branding** | ❌ | ⚠️ Nielsen branded | **GAP** (Антон сказал 10% use case — отложим) |
| **Export model parameters** | ❌ | ✅ Robyn JSON | **GAP**: для external validation / second opinion |

### 6. Integration / Data Sources

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **Source adapters** | ✅ 5 (DSM, Mediascope, AdEx, TV Index, Excel) | ✅ varies | OK |
| **Wordstat integration** | ⚠️ optional field, no auto | ❌ | OK |
| **Public macro data** | ❌ | ⚠️ Nielsen, varies | **GAP** (отложим): Rosstat / ЦБ API |
| **Programmatic API access** | ❌ | ⚠️ varies | **GAP** (v2.x): agency hooks |
| **Industry benchmarks library** | ❌ | ✅ Nielsen, BASES | **GAP**: «ваш TV ROI 2.5 — это в норме для категории» — для калибровки |

### 7. Scenario / Planning

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **Forward budget optimization** | ✅ | ✅ | OK |
| **Goal-seek (inverse)** | ✅ | ⚠️ rare | OK (наше преимущество) |
| **What-if bracketing / sensitivity curve** | ✅ | ✅ | OK |
| **Forecast по плану пользователя** | ⚠️ только через ScenarioPlayground | ✅ Robyn `robyn_response` | **GAP v2.0.0**: согласовано (5-й task profile) |
| **Multi-scenario comparison** | ❌ | ✅ Robyn Pareto frontier | **GAP**: сравнить 3 плана таблицей + chart |
| **Constraints library / preset** | ❌ | ⚠️ Robyn manual | **GAP** (минор): preset «TV ≥ 30%», «Performance ≥ 20%» |
| **Pareto frontier (multi-objective)** | ❌ | ✅ Robyn | **GAP**: Trade-off ROI vs reach vs share — отложим v2.1+ |

### 8. Audit / Trust / Diagnostics

| Feature | Aurora | Industry | Gap |
|---|---|---|---|
| **Trust Level 1 (smell flags)** | ✅ | ⚠️ varies | OK (наше преимущество) |
| **Trust Level 2 (unit cost calibration)** | ✅ | ⚠️ rare | OK (наше преимущество) |
| **Trust Level 3 (Bayesian + hierarchical)** | ✅ | ✅ standard | OK |
| **Out-of-sample validation (backtest)** | ❓ unclear surfaced | ✅ Robyn DECOMP.RSSD на holdout | **GAP CRITICAL**: 4-8 недель holdout, сравнить prediction vs actual — must для доверия |
| **Cross-validation (k-fold)** | ❌ | ⚠️ Robyn ridge CV | **GAP** (опционально для time-series) |
| **Prior sensitivity analysis** | ❌ | ⚠️ Bayesian standard | **GAP**: «если adstock_TV prior был 0.3 вместо 0.5 — ROI меняется на X» |
| **Bootstrap coefficient stability** | ❌ | ⚠️ Robyn distribution plots | **GAP** (опционально) |
| **MCMC convergence (R-hat / ESS)** | ⚠️ есть в backend, не в UI | ✅ standard | **GAP**: surface для Expert mode минимум |

---

## §2 Prioritized gaps

### Tier 1 — Critical для v2.0.0 (must-add)

| # | Feature | Why critical | Estimated effort |
|---|---|---|---|
| 1 | **Signed factor support** (math + UI) | Industry standard, агентский аналитик ожидает | 3-5 дней (согласовано) |
| 2 | **Forecast по плану пользователя** (5-й task profile) | Ключевая цель моделирования (Антон) | 2-3 дня (согласовано) |
| 3 | **Out-of-sample validation (backtest)** | Без неё ROI estimate непроверяем — это критично для **доверия** customer. Agency analyst первым делом спросит | 2-3 дня |
| 4 | **MCMC convergence в UI** (R-hat, ESS, basic trace plots) — хотя бы Expert mode | Bayesian модель без convergence checks = «может работать, может не работать». Эконометрист агентства это увидит | 1 день |
| 5 | **Posterior predictive checks (PPC)** — actual vs predicted scatter, residuals over time | Стандарт Bayesian diagnostics. Дополняет out-of-sample validation | 1-2 дня |
| 6 | **Holiday / event dummies** (РФ-календарь автоматом) | TV-driven продажи в дек/янв смещены — без этого decomposition врёт | 1-2 дня |
| 7 | **Sensitivity tornado chart** | Defensibility: «если adstock_TV ±20%, ROI меняется на ±X» — без этого менеджер не может защищать решения перед CFO | 1-2 дня |
| 8 | **Forecast continuation chart** (как на скрине) | Согласовано — main visualization | 2 дня |

**Subtotal Tier 1:** ~13-20 дней

### Tier 2 — Strong nice-to-have для v2.0.0 (если время позволит)

| # | Feature | Why | Effort |
|---|---|---|---|
| 9 | **Save/Load обученной модели** | Agency workflow: обучил один раз, прогоняет много планов | 2-3 дня |
| 10 | **Multi-scenario сравнение** (table + chart) | Twin curves «план vs Aurora optimized» — visible через twin chart, как на втором скрине | 2 дня |
| 11 | **Validation plots в UI** (actual vs predicted, residuals) | Стандарт Bayesian diagnostic, дополняет PPC | 1 день |
| 12 | **Channel contribution waterfall** | Premium-style декомпозиции | 1-2 дня |
| 13 | **Executive summary 1-pager auto** | C-level deliverable | 1-2 дня |
| 14 | **Export model parameters JSON** | External validation, audit | 0.5 дня |

**Subtotal Tier 2:** ~7-11 дней

### Tier 3 — Откладываем в v2.1.0+

- Time-varying coefficients (~5-7 дней, math-heavy)
- Synergy / interaction effects (~3-5 дней)
- Multi-region hierarchical (~5-7 дней, нужно multi-market data)
- Refresh capability (без full retrain, ~3 дня)
- Pareto frontier multi-objective (~3 дня)
- Industry benchmarks library (требует partnership)
- Public macro API (Rosstat / ЦБ интеграции)
- Multi-currency (отложим — фокус на РФ)
- Out-of-stock handling (через distribution proxy)
- White-label / branding (Антон сказал 10% use case)
- Programmatic API
- Collaboration / multi-user
- Project templates / favorites (можно сделать поверх Save/Load)

---

## §3 Strategic recommendation

### Predict scope v2.0.0

**Только Tier 1** (~13-20 дней) — реалистично 3-4 рабочих недели.

Если хотим Tier 2 — ~3-5 недель.

### Что это значит для positioning

Закрытие Tier 1 переводит Aurora из **«базовый MMM с UX-фокусом»** в **«полнофункциональный Bayesian MMM с industry-grade диагностикой + agency-friendly UX»**.

Это **меняет sales pitch:**
- Сейчас: «дешевле Nielsen, удобный UI»
- После v2.0.0: «полный MMM math с диагностикой + wizard UX + Methodology Certificate verifier» → competitive parity с Robyn (open source benchmark) + premium polish

### Что я бы лично выделила как 3 must-do для v2.0.0

Из 8 Tier 1 — **3 наиболее критичных** (если что-то срезать):

1. **Signed factors** — без них Aurora выглядит наивно (Антон сразу заметил)
2. **Out-of-sample backtest** — без него ROI estimate непроверяем
3. **MCMC convergence + PPC** — без них Bayesian = чёрный ящик

Холдинги и senior эконометристы (которые делают decision о покупке для агентств) первым делом смотрят на эти три. Если есть — покупают. Если нет — отказывают.

---

## §4 Open вопросы для Антона

**Q1.** Из Tier 1 (8 пунктов) — все включаем в v2.0.0 или прирезать до 3-4?

**Q2.** Из Tier 2 (6 пунктов) — какие из них critically важны и должны попасть в v2.0.0?

**Q3.** Save/Load модели (Tier 2 #9) — насколько важно для agency workflow? Если агентство обучает 1 раз на клиента и потом много раз прогоняет планы — это **critical**. Если каждый раз обучает заново — nice-to-have.

**Q4.** Multi-scenario comparison (Tier 2 #10) — это просто extension forecast'а (можно сделать поверх forecast continuation chart) или отдельная задача?

**Q5.** Какие конкретно РФ-праздники должны быть в holiday dummy library? Новый Год, 8 Марта, 23 Февраля, 9 Мая, Чёрная Пятница (если есть), Cyber Monday (если есть), Дни рождения брендов в категории. Что ещё?

**Q6.** Time-varying coefficients (Tier 3) — действительно отложить или это критично? Это **значимое улучшение математики**, но сложное в реализации. Эконометристы агентств заметят отсутствие.

**Q7.** Industry benchmarks library (Tier 3) — отложить или важно для positioning? Это требует partnership с Nielsen / Mediascope / похожими data providers.
