# GH Release Draft — Aurora AI Econometrica v1.0.14

**Status:** DRAFT (не публиковать пока Pre-Ship gate items #2 + #3 не done в next session)

**Repo:** github.com/Ackold26/aurora-releases (public release channel per memory)
**Tag:** `v1.0.14`
**Branch source:** `math-fix-v1.0.13` (в Aurora_Econometrica private)

---

## Release notes (copy-paste для GitHub)

# Aurora AI Econometrica v1.0.14 — Pharma Causal Module

## 🎯 Headline

Sprint 3 ship: новый causal-inference модуль поверх MMM. Три метода для оценки причинных эффектов маркетинговых кампаний:

- **DiD (Difference-in-Differences)** — для geo-holdout tests
- **SCM (Synthetic Control Method)** — для post-hoc оценки holdout markets
- **Causal Forest** — heterogeneous treatment effects по сегментам

Plus: 5 high-severity math fixes from Phase 1.1 audit (F1-F5) и audit-of-Sprint3 hardening (B1-B10).

## ⚠️ Honest disclosures

### Synthetic-only validation для v1.0.14
Causal endpoints validated на synthetic data + DGP-controlled ground truth recovery (508 tests + 100-sim SBC harness):
- **SCM**: coverage 0.92 ✅ at nominal
- **Forest**: coverage 1.00 (conservative)
- **DiD**: coverage 0.72 — small-sample cluster SE limitation under n_clusters < 10

Real-customer validation запланирован v1.0.15 после получения Materia Medica regional data.

### DiD small-sample caveat
API возвращает `honest_disclosure.caveats` с предупреждением когда n_clusters < 10. Recommend triangulate с SCM/Forest или wider confidence (0.95+). Wild-cluster bootstrap fix deferred к v1.0.15.

### Coverage assumptions
Все causal endpoints возвращают `honest_disclosure` с явными method assumptions: parallel-trends, convex-hull, positivity/overlap, SUTVA. Time-series exchangeability ослаблена — vanilla conformal coverage не guaranteed.

## 📦 New endpoints

```
POST /compute/causal/preflight     — applicable methods + recommendation
POST /compute/causal/list          — artifacts history
POST /compute/causal/consistency   — cross-method ATT triangulation
POST /compute/causal/did           — TWFE с staggered detection
POST /compute/causal/scm           — Abadie classic
POST /compute/causal/forest        — Wager-Athey HTE
```

## 🔄 Backwards compatibility

- ✅ All existing endpoints + pickle schemas IDENTICAL
- ✅ Existing v1.2/v1.1.5/v1.1/v1.0-ols pickles forward-compat (no re-train)
- ✅ Existing scenarios + decompose results unchanged
- ⚠ MMM pickle получает optional `causal_artifact_path: null` field (forward-compat hint, no functional impact)

## 📥 Installation

Скачать: `Aurora_AI_Econometrica_1.0.14_x64-setup.exe`

Auto-update from v1.0.13 supported. Или manual install — keeps existing projects/data intact.

**SHA256:** `<TO_BE_FILLED_AFTER_BUILD>`
**Bundle size:** ~210MB (was ~180MB в v1.0.13 — +30MB Sprint 3 deps: linearmodels, econml)

## 📚 Documentation

- `docs/CHANGELOG_v1.0.14.md` — полный список changes (headline + honest disclosures + migration)
- `docs/SPRINT3_PHARMA_CAUSAL_ADR.md` — architectural decisions (12 sections + ADR §1 EXTEND-not-rewrite)
- `docs/SBC_RESULTS_v1.0.14.md` — Simulation-Based Calibration coverage report
- `docs/MATERIA_MEDICA_GEO_DATA_REQUEST.md` — template для real-data v1.0.15 case-study

## 🔮 Coming в v1.0.15

- Real-customer Materia Medica/Кагоцел/Афала regional data validation (case-study)
- DiD wild-cluster bootstrap для small n_clusters fix
- UI polish: file picker через Tauri dialog, column auto-detect from xlsx
- Synergy refactors: F2/F3 caveats consolidation в HonestDisclosure
- True bootstrap для Causal Forest (currently `cate_mean_se_fallback`)

---

## 📋 Pre-Ship gate checklist (для оператора при публикации)

Before clicking "Publish release":

- [x] Sprint 3 backend M0-M4 complete + 488 tests PASS
- [x] Audit-of-Sprint3 fixes (B1-B10) shipped + 20 lock-in tests PASS
- [x] UI track shipped (route + 3 components + 6 Rust pass-throughs)
- [x] SBC 100 sims на all 3 methods + coverage report
- [x] DiD small-sample caveat в honest_disclosure
- [x] CHANGELOG_v1.0.14.md
- [x] Version bumps (Cargo.toml + tauri.conf.json + package.json)
- [x] PyInstaller sidecar bundle с new deps (linearmodels, econml)
- [ ] **NSIS installer build** (TODO this session, в parallel с release prep)
- [ ] **Independent fresh-context audit pass** (next session, mandatory per ADR §5 #3)
- [ ] **MIN-LIVE gates 6-9 production scenario** (next session)
- [ ] SHA256 checksum в release notes
- [ ] aurora-releases GH repo: upload .exe + Release notes
- [ ] aurora-releases `latest.json` update для auto-updater
- [ ] Supabase `app_versions` table SQL update
- [ ] PASHE_IT.MD client documentation update
- [ ] Tag `v1.0.14` в Aurora_Econometrica + push
