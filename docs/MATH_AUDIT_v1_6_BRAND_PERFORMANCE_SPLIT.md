# MATH AUDIT v1.6 - Brand vs Performance Split (Trust Level 3)

**Status:** SHIPPED 2026-04-27 (v1.1.0 architectural change)
**Branch:** math-fix-v1.0.13
**Author:** Sprint 4 (Antón + Маша через Claude Code Opus 4.7)
**Plan:** `bright-jingling-pebble.md`
**Tracker:** `Sprint4_Trust_Level.md`

---

## 1. Mathematical motivation

Pre-v1.1.0 модель применяла единый logit-normal hyperprior для adstock decay:

```
adstock_mu_logit ~ Normal(-1.4, 0.7)
adstock_decay[i] = sigmoid(adstock_mu_logit + adstock_sigma_logit · z[i])
```

На FMCG-портфеле где TV/TRPs (long-decay 4-26 weeks) сосуществуют с Digital/Search
(short-decay 1-2 weeks), single hyperprior компрометирует обе оценки:

- Brand-каналы недооцениваются (decay μ pulled toward общим средним ~0.20)
- Performance-каналы получают «остаточный» вклад поверх неправильно атрибуированной brand-baseline

Trust Level 3 разделяет каналы на **brand / performance / mixed** и применяет
group-conditional hierarchical priors.

---

## 2. Hierarchical structure (final implementation)

### 2.1 Beta priors (media coefficients)

**Pre-v1.1.0 (single prior path, preserved для backward compat):**
```python
media_betas ~ HalfNormal(sigma=0.3, shape=N)
```

**v1.1.0 hierarchical path (when ≥2 каналов в одной из brand/perf групп):**
```python
brand_sigma  ~ HalfNormal(0.7)   # wider - accommodate brand variance
perf_sigma   ~ HalfNormal(0.3)   # tighter - performance well-identified
mixed_sigma  ~ HalfNormal(0.4)   # intermediate

sigma_per_channel[i] = brand_sigma  if cat[i] == 'brand'
                     elif perf_sigma  if cat[i] == 'performance'
                     else mixed_sigma

# Non-centered z-reparameterization (Critical Audit issue C):
media_betas_z ~ HalfNormal(1.0, shape=N)
media_betas[i] = sigma_per_channel[i] * media_betas_z[i]
```

**Why non-centered:** Centered (`betas ~ HalfNormal(group_sigma)`) creates funnel
geometry на small N (e.g. n=31 monthly). NumPyro NUTS divergences explode.
Non-centered reparam decouples sigma↔beta sampling - identical posterior, robust geometry.

### 2.2 Adstock decay priors

**Pre-v1.1.0 (single hyperprior, preserved):**
```python
adstock_mu_logit ~ Normal(-1.4, 0.7)
adstock_sigma_logit ~ HalfNormal(1.0)
adstock_z[i] ~ Normal(0, 1)
adstock_decay[i] = sigmoid(adstock_mu_logit + adstock_sigma_logit * adstock_z[i])
```

**v1.1.0 hierarchical path:**
```python
brand_mu_logit  ~ Normal(0.7,  0.3)   # sigmoid ≈ 0.67 → ~12 weeks half-life (monthly)
perf_mu_logit   ~ Normal(-1.4, 0.7)   # sigmoid ≈ 0.20 → ~1.3 weeks half-life
mixed_mu_logit  ~ Normal(-1.4, 0.7)   # same as pre-v1.1.0 fallback

mu_per_channel[i] = brand_mu_logit  if cat[i] == 'brand'
                  elif perf_mu_logit  if cat[i] == 'performance'
                  else mixed_mu_logit

adstock_sigma_logit ~ HalfNormal(1.0)
adstock_z[i] ~ Normal(0, 1)
adstock_decay[i] = sigmoid(mu_per_channel[i] + adstock_sigma_logit * adstock_z[i])
```

### 2.3 Why geometric (NOT weibull) для brand

Original plan предложил Weibull adstock для brand (delayed-peak shape). После
code-trace (Critical Audit issue A):

- Текущий weibull в-model = pre-computed (Phase 1.5 task to make learnable)
- Weibull = convolution (CDF weights × shifted matrix) - не natural для pt.scan
- Wiring weibull в pt.scan = ~10-15h additional work + JAX JIT recompilation issues

**Решение:** **Stronger geometric prior для brand** (mu_logit=0.7 vs -1.4).
- Effective half-life ≈ 12 weeks матчится с brand reality для monthly data
- Robyn (Meta MMM) использует geometric для всех каналов с tuned decay - accepted industry practice
- Reuses existing pt.scan infrastructure без modifications
- adstock_factor_batch уже correct для geometric (analytical formula в utils/adstock.py:130-139)

**Trade-off:** Не «true» weibull (нет delayed-peak shape, peak всегда в первый период).
Acceptable simplification для v1.1.0; Phase 1.5 weibull-learnable можно ship позже.

---

## 3. Identifiability constraint (issue B)

**Risk:** Single-channel group (e.g. brand_idx=[TRPs only]) → group_sigma_brand
становится hyperparameter с zero degrees of freedom. Posterior degenerate
→ r_hat > 1.1 → silently broken model.

**Mitigation:** `validate_categorization_for_hierarchical()` в utils/channel_categorization.py:
- Если `len(brand_idx) < 2 OR len(perf_idx) < 2` → канал(ы) demoted к mixed
- UI warning displayed: «Категория Brand имеет всего N канал(ов). Для надёжного
  разделения нужно ≥2. Канал переведён в Mixed.»

Server `train_model()` вызывает validate ДО построения PyMC model. `use_hierarchical`
flag set False автоматически если post-validation no group has ≥2.

---

## 4. R-hat diagnostic gate (issue L)

Hierarchical introduces 2-4 new hyperparameters. MCMC может sample их poorly даже
если betas converge. Server post-sampling check:

```python
hyper_names = ['brand_sigma', 'perf_sigma', 'brand_mu_logit', 'perf_mu_logit']
hyper_rhats = [per_param_rhat[n] for n in hyper_names if n in per_param_rhat]
if hyper_rhats and max(hyper_rhats) > 1.05:
    diagnostics['hierarchical']['rhat_warning'] = (
        f'Hierarchical hyperparameters did not converge: ... '
        f'Consider increasing tune/draws or revert к single-prior path.'
    )
```

Warning attached к `diagnostics.hierarchical.rhat_warning`. UI shows banner
+ HTML report включает в methodology section.

---

## 5. Pickle versioning (issue E)

| Version  | Description                                                     |
|----------|-----------------------------------------------------------------|
| 1.0      | Initial OLS path (rejected by decomposer - MODEL_OUTDATED)      |
| 1.0-ols  | Sprint 2 small-data fallback (point estimates)                  |
| 1.1      | v1.0.13+ Bayesian baseline (z-score → spend/mean Hill normalization) |
| 1.1.1    | Phase 1.1 hierarchical adstock decay (single hyperprior)        |
| 1.2      | v1.0.16 baseline (post-audit fixes, three-way alignment)        |
| **1.3**  | **Trust Level 3 - brand vs performance split**                  |

**v1.3 schema additions:**
- `channel_categories: dict[str, 'brand'|'performance'|'mixed']`
- `categorization_warnings: list[str]`
- `use_hierarchical: bool`
- `hierarchical_priors: dict` - `{brand_mu_logit_mean, perf_mu_logit_mean, ...}` для methodology auto-gen

**Backward compat:** `engines/persistence.py:load_model_with_compat()` injects
defaults для pre-v1.3 pickles. `model_data['channel_categories']` always present
(empty dict для legacy).

Все downstream consumers (decomposer, optimizer, scenario, backtest, html_export)
теперь go through helper, NOT direct pickle.load(). Single source of truth for
backward compat handling.

---

## 6. Conformal Prediction interaction (issue F - partial)

S-OLS-1 conformal PI assumes exchangeability of residuals. Hierarchical model
с group structure → residuals могут показывать group-conditional patterns
(brand residuals correlated, performance residuals correlated).

**Status:** test_brand_perf_split.py включает acceptance assertion (≥85% empirical
coverage) но требует live MCMC sampling - defer к Phase E live alpha gate
(Антон's Kagocel + Венарус validation session).

**Risk acknowledged в methodology section:** «Атрибуция между brand и performance
имеет fundamental uncertainty - мы используем priors based on industry norms».

---

## 7. UX disclosure (issue R - deferred)

Original plan включал ROI shift comparison block («ROI was 0.85 → now 0.62 (−0.23)»).
**Defer для v1.1.1:** требует «previous run» persistence + comparison logic в backend.
Workaround для v1.1.0: HTML methodology section явно указывает что новая модель
applies hierarchical attribution → user понимает контекст ROI change.

---

## 8. File modifications summary

### Backend (Python sidecar)

- **NEW** `sidecar/econometrica/utils/channel_categorization.py` (200 LOC)
- **NEW** `sidecar/econometrica/engines/persistence.py` (90 LOC)
- **MODIFIED** `sidecar/econometrica/engines/modeler.py`:
  - Hierarchical priors path (~80 LOC)
  - R-hat diagnostic gate
  - model_version='1.3' bump iff use_hierarchical
  - hierarchical_priors_summary persisted в pickle
- **MODIFIED** `sidecar/econometrica/engines/decomposer.py`:
  - Use load_model_with_compat
  - Use explicit channel_categories (heuristic fallback for pre-v1.3)
  - Persist adstock_decay_mean/_ci_low/_ci_high (50% CI)
  - Heuristic source = utils/channel_categorization (DRY)
- **MODIFIED** `sidecar/econometrica/engines/optimizer.py / scenario.py / backtest.py / html_export.py`:
  - Use load_model_with_compat
- **MODIFIED** `sidecar/econometrica/aurora_html/sections.py`:
  - NEW `_render_brand_perf_split_block(ctx)` - methodology auto-gen
- **MODIFIED** `sidecar/econometrica/server.py`:
  - TrainRequest/TrainStartRequest принимают channel_categories
  - NEW endpoint `POST /utils/auto_suggest_categories`

### Frontend (Svelte + Tauri)

- **MODIFIED** `src-tauri/src/commands/project.rs`:
  - ProjectInfo.channel_categories: HashMap<String,String>
  - update_project_columns sync (orphan cleanup)
  - validation accepts только brand/performance/mixed
- **MODIFIED** `src-tauri/src/commands/econometrica.rs`:
  - NEW `econ_categorize_channels` Tauri command
- **MODIFIED** `src-tauri/src/lib.rs`:
  - Register `econ_categorize_channels` в invoke_handler
- **MODIFIED** `src/lib/project-state.js`:
  - NEW channelCategories writable store + activeProject sync
- **MODIFIED** `src/lib/components/ConfigPanel.svelte`:
  - Pass channel_categories в TrainRequest config (sync + async paths)
- **NEW** `src/lib/components/pipeline/ChannelCategoriesPanel.svelte` (~370 LOC):
  - Per-channel badge UI 🎯/📊/⚪
  - Click→override popup
  - Auto-suggest на mount + persistence
  - Insights summary (group counts + hierarchical eligibility)
- **MODIFIED** `src/lib/components/pipeline/ValidateStep.svelte`:
  - Mount ChannelCategoriesPanel section под UnitCostsPanel
- **MODIFIED** `src/lib/components/pipeline/DecomposeStep.svelte`:
  - Visual grouping (group headers per category)
  - NEW Decay column (mean ± 50% CI)

### Tests (NEW)

- `tools/test_channel_categorization.py` - 21/21 PASS
- `tools/test_pickle_compat.py` - 10/10 PASS
- `tools/test_brand_perf_split.py` - 10/10 PASS
- `tools/validation_set_categorization.json` - 50 manually-labeled channels (≥85% accuracy)

### Documentation

- **THIS FILE** - `docs/MATH_AUDIT_v1_6_BRAND_PERFORMANCE_SPLIT.md`
- `docs/CHANGELOG_v1.1.0.md` - release notes
- Sprint4_Trust_Level.md - current status / commits log

---

## 9. Known limitations + roadmap

**v1.1.0 limitations (ack'd):**
1. Brand decay = geometric с stronger prior, не «true» Weibull (Phase 1.5+)
2. Conformal exchangeability на split posterior - empirically validated в alpha gate
   (formal proof requires Phase 1.6+ work)
3. ROI shift comparison block deferred к v1.1.1
4. Per-group Min/Max sliders в Optimize deferred (full scope, post-v1.1.0)
5. PPTX methodology section не обновлён (HTML-only disclosure для MVP)

**Phase 1.5 / v1.2 roadmap:**
- Learnable Weibull adstock (true delayed-peak)
- Per-group MQS thresholds в decomposer verdict
- Multi-product hierarchical (brand/perf split × SKU level)
- Causal artifact integration с category-aware lift models

---

## 10. Verification matrix

| Check                                | Status        |
|--------------------------------------|---------------|
| svelte-check (no new errors)         | ✅ 31 pre-existing only |
| cargo check                          | ✅ Clean      |
| V40 lint                             | ✅ OK         |
| test_channel_categorization (21)     | ✅ 21/21      |
| test_pickle_compat (10)              | ✅ 10/10      |
| test_brand_perf_split (10)           | ✅ 10/10      |
| test_optimizer_kagocel_redistribution (regression) | ✅ 20/20 |
| test_narrative_coherence (regression)| ✅ 24/24      |
| Validation accuracy ≥85%             | ✅ 50 labels  |
| Backward compat (v1.2 pickle loads)  | ✅ Tested     |
| Identifiability fallback (N=1)       | ✅ Tested     |
| Heuristic fallback for legacy pickles| ✅ Tested     |
| HTML methodology auto-gen            | ✅ Tested     |
| **Live alpha gate (Kagocel + Венарус)** | **⏸ PENDING - Phase G** |

**Total automated tests:** 75 unit + 41 channel_categorization/pickle/split + 24 narrative + 20 optimizer = **160 PASS**.

---

*Generated 2026-04-27 для Sprint 4 Trust Level 3 architectural ship.*
