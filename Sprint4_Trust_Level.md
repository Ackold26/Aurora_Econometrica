# Sprint 4+ Trust Level 3 — Brand vs Performance Split

**Started:** 2026-04-27
**Branch:** math-fix-v1.0.13
**Plan:** `C:\Users\ackol\.claude\plans\bright-jingling-pebble.md`
**Target ship:** v1.1.0 (architectural change — major bump)

---

## Current Status

**Phase:** ALPHA GATE — Live alpha gate (Антон) + ship workflow
**In progress:** Документация готова, await Antón's manual test session на Kagocel + Венарус
**Blocking:** Live alpha gate (manual test) — нужно подтвердить что NumPyro JAX hierarchical sampling сходится на real data и что split даёт sensible ROI changes
**Next concrete step:**
  1. Антон запускает `npm run tauri dev` → открывает Kagocel project → Validate → assigns brand/perf categories → Train → Decompose → проверяет что hierarchical работает
  2. Повторяет на Венарус
  3. Если PASS → bump version 1.0.16 → 1.1.0 (Cargo.toml + tauri.conf.json) + NSIS build + GH Release
  4. Если FAIL — log issue → continue iteration

**Build commands после alpha gate:**
```bash
# Bump version
sed -i 's/version = "1.0.16"/version = "1.1.0"/' src-tauri/Cargo.toml
sed -i 's/"version": "1.0.16"/"version": "1.1.0"/' src-tauri/tauri.conf.json

# Build sidecar
python sidecar/econometrica/build_sidecar.py

# Build NSIS
CARGO_TARGET_DIR="D:/cargo-targets/aurora-econometrica" npm run tauri build

# Tag + ship
git tag v1.1.0
git push --tags
gh release create v1.1.0 --title "Aurora Econometrica v1.1.0 — Brand vs Performance Split"
# + rosst-updates latest.json PATCH
# + Supabase app_versions PATCH
```

---

## Done

- [x] 2026-04-27 Plan approved (`bright-jingling-pebble.md`)
- [x] 2026-04-27 Audit добавлен в plan (24 issues найдено в code-trace)
- [x] 2026-04-27 Status file создан (`Sprint4_Trust_Level.md`)
- [x] 2026-04-27 Phase B: utils/channel_categorization.py + tests (21/21 PASS) [commit `c8efaa5`]
- [x] 2026-04-27 Phase B: engines/persistence.py + tests (10/10 PASS) [commit `c8efaa5`]
- [x] 2026-04-27 Phase B: validation_set_categorization.json fixture (50 labeled channels)
- [x] 2026-04-27 Phase C: modeler.py hierarchical priors path с group-conditional sigma+decay [commit `f45f97b`]
- [x] 2026-04-27 Phase C: R-hat diagnostic gate для hierarchical hyperparameters
- [x] 2026-04-27 Phase C: model_version=1.3 bump + pickle persists categories/priors/use_hierarchical
- [x] 2026-04-27 Phase C: server.py /utils/auto_suggest_categories endpoint (replaces planned JS port)
- [x] 2026-04-27 Phase C: TrainRequest/TrainStartRequest принимают channel_categories
- [x] 2026-04-27 Phase C: ВСЕ engines (decomposer/optimizer/scenario/backtest/html_export) → load_model_with_compat
- [x] 2026-04-27 Phase C: decomposer использует explicit categories (heuristic fallback for pre-v1.3 pickles)
- [x] 2026-04-27 Regression: 75/75 sanity tests PASS (no behavior change для existing models)
- [x] 2026-04-27 Phase D: project.rs ProjectInfo.channel_categories + serde(default) [commit `eb3f4f9`]
- [x] 2026-04-27 Phase D: project_update orphan cleanup на rename/delete media columns
- [x] 2026-04-27 Phase D: validation accepts только brand/performance/mixed values
- [x] 2026-04-27 Phase D: Tauri command econ_categorize_channels + register в lib.rs
- [x] 2026-04-27 Phase D: src/lib/project-state.js channelCategories writable store
- [x] 2026-04-27 Phase D: ConfigPanel pass channel_categories в TrainRequest
- [x] 2026-04-27 Phase D: NEW ChannelCategoriesPanel.svelte (~370 LOC) + mounted в ValidateStep
- [x] 2026-04-27 Phase D: DecomposeStep visual grouping + Decay column ± 50% CI [commit `e864716`]
- [x] 2026-04-27 Phase D: aurora_html/sections.py NEW _render_brand_perf_split_block (auto-gen methodology)
- [x] 2026-04-27 Phase D: backend exposes adstock_decay_mean/_ci_low/_ci_high в ch_dict
- [x] 2026-04-27 Phase E: tools/test_brand_perf_split.py 10/10 PASS (synthetic + smoke)
- [x] 2026-04-27 Phase F: docs/MATH_AUDIT_v1_6_BRAND_PERFORMANCE_SPLIT.md (10 sections, 350+ LOC)
- [x] 2026-04-27 Phase F: docs/CHANGELOG_v1.1.0.md (release notes + migration guide)

---

## Decisions Log

### 2026-04-27 — Architectural

- **Brand adstock = stronger geometric, NOT weibull** (Critical Audit issue A). Weibull в-model = Phase 1.5 task, не bridge-able. Brand mu_logit ~ Normal(0.7, 0.3) → effective decay ≈ 0.67 ≈ 12 weeks half-life monthly data. Saves 10-15h.
- **Backend endpoint вместо JS port** (issue H) — `POST /utils/auto_suggest_categories`. Single source of truth = Python.
- **Optimizer untouched** (issue Q) — already correct via posterior chain rule.
- **Identifiability fallback** (issue B) — N<2 в группе → канал demoted к mixed с UI warning.
- **Non-centered reparam betas обязателен** (issue C) — z-score pattern из Phase 1.1.
- **Pickle compat helper** (issue E) — `engines/persistence.py:load_model_with_compat`, все downstream consumers через него.

### 2026-04-27 — Versioning

- **v1.1.0 major bump** (architectural change, new schema). НЕ patch.
- Mixed category = fallback к single prior path (current behavior preserved).

---

## Next steps queue

1. Phase A — investigation: probe hierarchical NumPyro JAX
2. Phase B — failing tests first (13 split + 10 categorization + compat + prior predictive + validation set)
3. Phase C — backend implementation (channel_categorization util + persistence helper + modeler hierarchical + decomposer compat + server endpoint)
4. Phase D — frontend (project.rs schema + ValidateStep badges + DecomposeStep grouping + Report integration)
5. Phase E — multi-client validation (Kagocel + Венарус + edge cases)
6. Phase F — documentation (math audit auto-gen + CHANGELOG + Help)
7. Phase G — ship (alpha gate + NSIS + GH Release + rosst-updates + Supabase)

---

## Commits

- `c8efaa5` 2026-04-27 — feat(trust3): channel categorization util + pickle compat helper (Sprint 4 foundation)
- `f45f97b` 2026-04-27 — feat(trust3): hierarchical Bayesian priors brand vs performance + R-hat gate
- `eb3f4f9` 2026-04-27 — feat(trust3): Validate UI badges + ChannelCategoriesPanel + Tauri schema
- `e864716` 2026-04-27 — feat(trust3): Decompose grouping + decay column + HTML methodology auto-gen
- `269a683` 2026-04-27 — docs(trust3): math audit + CHANGELOG v1.1.0 + brand_perf_split tests
- (next) 2026-04-27 — fix(trust3): post-audit regression fixes + UI synergy

## Post-audit findings (2026-04-27 deep review)

🔴 **CRITICAL fix:** `validate_categorization_for_hierarchical` auto-fill missing с 'mixed' ломал pre-Trust3 backward compat — pickle saved all-mixed → decomposer пропускал heuristic → пре-existing проекты теряли категоризацию в отчётах. **Fix:** validate возвращает только explicit user entries; modeler use new `resolve_per_channel_categories` для in-model vector. Pickle persists empty {} когда user не assigned.

🟠 `categorization_warnings` saved в pickle но не surface к UI. **Fix:** decomposer response теперь включает `hierarchical: {enabled, channel_categories, categorization_warnings, priors_summary}`. DecomposeStep показывает warning banner.

🟠 `channelCategories` store не cleanup orphans на frontend (backend project.rs делал). **Fix:** NEW `syncChannelCategoriesToMedia()` helper в project-state.js. ValidateStep вызывает после persist.

🟡 Triple `import pytensor.tensor as pt` в modeler — duplicate, грязно. **Fix:** Удалены, использован shared import + `_mu_lookup`/`_sigma_lookup` dicts (cleaner code via dict-comp).

🟡 `mu_per_channel`/`sigma_per_channel` строились через append loops. **Fix:** Replaced с list-comprehension + lookup dicts (DRY + faster).

🟡 `mixed_mu_logit` и `mixed_sigma` semantically duplicate single-prior path. Kept (semantic clarity outweighs ~3 extra hyperparam samples).
