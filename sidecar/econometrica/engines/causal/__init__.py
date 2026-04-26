"""
Sprint 3 Pharma Causal — causal inference engines.

Sprint 3 EXTENDS Aurora Econometrica architecture per ADR §1 (load-bearing
"EXTEND-not-rewrite" decision). New namespace:

- engines.causal.did            — Difference-in-Differences (Callaway-Santanna 2021, M1)
- engines.causal.scm            — Synthetic Control Method (Abadie 2021, M2)
- engines.causal.causal_forest  — Causal Forest (Wager-Athey 2018, M3)
- engines.causal.common         — Shared utilities (HonestDisclosure, errors, validators)
- engines.causal._panel_data    — Panel format loader + validators

Sprint 3 ADR: docs/SPRINT3_PHARMA_CAUSAL_ADR.md
M-progression: M0 stack scaffolding → M1 DiD → M2 SCM → M3 Forest → M4 integration.

Per Q2(B): NO pysyncon dep, NO cvxpy. Manual scipy SLSQP for SCM weights via
isolated _solve_scm_weights() interface — clean swap path для future Augmented
SCM/BSCM в Sprint 4+.

Per Q4: causal artifacts stored separately в `project_dir/causal/*.json`.
MMM pickle gets optional `causal_artifact_path` hint field (next training write,
backward-compat preserved через .get() fallback).
"""

__version__ = '0.1.0-m0'  # M0 stack scaffolding ship

# Keep imports minimal in __init__ to avoid forcing heavy dep load on every
# `from engines import *`. Endpoints lazy-import от ./<module>.py.

__all__ = ['__version__']
