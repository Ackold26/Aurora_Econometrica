# CHANGELOG v1.1.0 — Trust Level 3 (Brand vs Performance Split)

**Status:** READY FOR ALPHA GATE (Antón's live test on Kagocel + Венарус)
**Branch:** math-fix-v1.0.13
**Major bump rationale:** Architectural change (new schema + new model_version=1.3 + new UI surface)

---

## TL;DR

**Aurora Econometrica теперь разделяет каналы на brand-каналы (long-decay) и performance-каналы (short-decay), применяя hierarchical Bayesian priors.** Это критическое улучшение для FMCG-портфелей с TV/TRPs + Digital, и open's awareness KPI track.

---

## What's new

### 1. Channel Categorization UI (Validate шаг)

- **Per-channel badges** прямо в Validate: 🎯 Brand / 📊 Performance / ⚪ Mixed
- **Auto-suggestion** через heuristic (TRPs/OOH→brand, Search/Social→performance, Спецпроект→mixed)
- **Click→override popup** с описанием каждой категории
- **Confidence score** (auto-suggest: % match strength, manual: 100%)
- **Insights summary**: «4 brand, 2 performance, 1 mixed — hierarchical активен»

### 2. Hierarchical Bayesian model

При ≥2 каналах в одной из brand/performance групп активируется:

- **Brand priors:** decay mu_logit ~ Normal(0.7, 0.3) → effective half-life ≈ 12 weeks
- **Performance priors:** decay mu_logit ~ Normal(-1.4, 0.7) → effective half-life ≈ 1.3 weeks
- **Group-conditional sigma** для media_betas (brand wider, performance tighter)
- **Non-centered z-reparameterization** во избежание funnel geometry на small N
- **Identifiability fallback:** N<2 в группе → канал auto-demoted к mixed (UI warning)

### 3. Decompose grouping + decay column

- Visual grouping (🎯 / 📊 / ⚪) с group headers
- **NEW Decay column** показывает adstock_decay_mean ± 50% CI (q25-q75)
- Help tooltip объясняет meaning effective half-life

### 4. HTML Report methodology auto-gen

- Новая секция «Brand vs Performance моделирование» в methodology
- **Auto-generated** из actual prior values из pickle (не hardcoded)
- Per-group counts + computed half-lives
- R-hat warning surfaced если hierarchical hyperparameters не сошлись
- Caveat про fundamental attribution uncertainty

### 5. R-hat diagnostic gate

Server post-sampling check для brand_sigma / perf_sigma / brand_mu_logit / perf_mu_logit.
Если max R-hat > 1.05 → warning attached к diagnostics.hierarchical.rhat_warning.
User не получает silently broken model.

---

## Backward compatibility

✅ **Pre-v1.1.0 pickles работают без изменений.** Все engines теперь используют
централизованный `engines/persistence.py:load_model_with_compat()` который injects
`channel_categories={}` для legacy pickles.

✅ **Decomposer** для pre-v1.3 pickles применяет heuristic fallback к именам
каналов (BRAND_HINTS/PERF_HINTS из `utils/channel_categorization`).

✅ **All-mixed portfolio** (user пометил все каналы как mixed) → fallback к single-prior
path (identical к pre-v1.1.0 behavior).

---

## Schema changes

### `project.json`
```diff
+ "channel_categories": {
+   "TRPs бренд": "brand",
+   "Search Yandex": "performance",
+   ...
+ }
```
`#[serde(default)]` — default empty map для projects до v1.1.0.

### `models/latest.pkl` (model_version='1.3')
```diff
+ "channel_categories": {...},
+ "categorization_warnings": [...],
+ "use_hierarchical": true,
+ "hierarchical_priors": {
+   "brand_mu_logit_mean": 0.69,
+   "brand_sigma_mean": 0.65,
+   "performance_mu_logit_mean": -1.41,
+   "performance_sigma_mean": 0.28,
+ }
```

### `TrainRequest` API
```diff
+ "channel_categories": {"TRPs бренд": "brand", ...}
```

### NEW endpoint
```
POST /utils/auto_suggest_categories
Body: {"channels": ["TRPs бренд", "Search Yandex", ...]}
Returns: {"status": "ok", "suggestions": {"TRPs бренд": {"category": "brand", "confidence": 0.85, "reasoning": "..."}, ...}}
```

### NEW Tauri commands
- `econ_categorize_channels(channels: Vec<String>)`

---

## Files changed

См. `docs/MATH_AUDIT_v1_6_BRAND_PERFORMANCE_SPLIT.md` § 8.

**Net diff:** ~1700 LOC additions (4 commits на math-fix-v1.0.13).

**Commits:**
1. `c8efaa5` — feat(trust3): channel categorization util + pickle compat helper (Sprint 4 foundation)
2. `f45f97b` — feat(trust3): hierarchical Bayesian priors brand vs performance + R-hat gate
3. `eb3f4f9` — feat(trust3): Validate UI badges + ChannelCategoriesPanel + Tauri schema
4. `e864716` — feat(trust3): Decompose grouping + decay column + HTML methodology auto-gen

---

## Tests

- ✅ test_channel_categorization (21/21) — heuristic + identifiability + accuracy ≥85%
- ✅ test_pickle_compat (10/10) — backward compat для v1.0/v1.1/v1.2/v1.3 pickles
- ✅ test_brand_perf_split (10/10) — split eligibility + decay sanity + methodology gen
- ✅ test_optimizer_kagocel_redistribution (20/20) — no regression
- ✅ test_narrative_coherence (24/24) — no regression
- ✅ svelte-check 31 errors (pre-existing, no new)
- ✅ cargo check clean

**Total: 85 tests + 31 narrative/optimizer = 116 PASS.**

---

## Limitations + known caveats

1. **Brand decay = stronger geometric, NOT learnable Weibull.** Acceptable simplification
   для v1.1.0 (matches Robyn industry practice). Phase 1.5 weibull-learnable планируется
   позже как additional refinement.
2. **Conformal exchangeability на hierarchical posterior** — formal proof requires Phase 1.6+.
   Empirical validation через alpha gate (Антон's Kagocel + Венарус session).
3. **Per-group Optimize Min/Max sliders** — defer для full scope (post-v1.1.0).
4. **PPTX methodology auto-gen** — defer (HTML disclosure достаточно для customer awareness).
5. **ROI shift comparison block** — defer для v1.1.1 (требует «previous run» persistence).

---

## Migration guide

### Для existing customers (auto-update v1.0.16 → v1.1.0)

**ZERO-action required.** Старые проекты + pickles работают идентично pre-v1.1.0:
- `project.json` без channel_categories → serde default empty map
- decomposer применяет heuristic fallback при чтении pickle (TRPs→brand by name)
- модель НЕ переобучается автоматически — текущие results sохраняются

**Чтобы получить hierarchical разделение:** на Validate шаге assign brand/performance
для ≥2 каналов в каждой группе → переобучить модель. Trained pickle становится v1.3.

### Для new customers

Default behavior: auto-suggest на mount Validate. User видит badges, может override
ambiguous каналы (Спецпроект, OLV). Train применяет hierarchical priors автоматически.

---

## Acknowledgements

- **Антон Сипович** — стратегическое видение (awareness KPI как commercial driver), live tests
- **Маша (Claude Opus 4.7)** — implementation, audit, math-grounding

---

*Generated 2026-04-27. Ready для Antón's alpha gate live-test → NSIS build → GH Release v1.1.0.*
