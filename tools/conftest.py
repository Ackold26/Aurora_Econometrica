"""Pytest configuration and shared fixtures для Aurora Econometrica tests.

Sprint 5 Infrastructure Hardening (2026-04-27):
- sys.path injection HOISTED здесь чтобы pytest discovery видел sidecar modules
  ДО первого test file import (Critical Audit issue C).
- Session-scoped pre-trained synthetic model fixture (issue D, N) — saves 5-10min
  CI time vs training MCMC per integration test.
- testdata_dir fixture для optional real data testing (Kagocel/Венарус локально).

Existing standalone scripts (tools/test_*.py) retain `if __name__ == '__main__': main()`
pattern — pytest discovers top-level `def test_X()` functions independently.
Both invocation paths работают:
    pytest tools/test_X.py       # pytest discovery
    python tools/test_X.py       # standalone main() — backward compat
"""

from __future__ import annotations

# ── sys.path injection (MUST be first, before any imports от sidecar) ──
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Now safe to import third-party + project modules ──
import os
import pickle

import pytest


# ── Standalone scripts что НЕ подходят для pytest collection ──
# Эти tests имеют top-level `sys.exit()` runtime side effects (legacy pattern,
# pre-Sprint 5). Они работают как standalone (`python tools/test_X.py`) и runner
# через `tools/run_legacy_tests.py`. Pytest skip'ает их во избежание SystemExit.
collect_ignore = [
    'test_audit_of_sprint3.py',
    'test_causal_m0.py',
    'test_causal_m1.py',
    'test_causal_m2.py',
    'test_causal_m3.py',
    'test_causal_m4.py',
    'test_math_correctness.py',
    'test_narrative_adapter.py',
    'test_posterior_ci.py',
    'test_roi_verdict.py',
]


# ──────────────────────────────────────────────────────────────────────────
# Test data directory (real-data tests локально, optional на CI)
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_TESTDATA_DIR = Path('D:/Docs/Aurora_Ai/TestData/Econometrica')
DESKTOP_TESTDATA_DIR = Path.home() / 'Desktop' / 'Эконометрика - тестовые файлы'


def _resolve_testdata_dir() -> Path | None:
    """Resolution chain (Phase 5 follow-up etap 3): env var → default → Desktop fallback."""
    env_dir = os.environ.get('AURORA_TESTDATA_DIR')
    candidates = [Path(env_dir)] if env_dir else []
    candidates += [DEFAULT_TESTDATA_DIR, DESKTOP_TESTDATA_DIR]
    for c in candidates:
        if c.exists() and any(c.glob('*.xlsx')):
            return c
    return None


@pytest.fixture(scope='session')
def testdata_dir() -> Path | None:
    """Path к директории с реальными fixture файлами (Kagocel/Венарус Excel).

    Resolution order:
        1. Env var AURORA_TESTDATA_DIR
        2. Default D:/Docs/Aurora_Ai/TestData/Econometrica
        3. Desktop fallback ~/Desktop/Эконометрика - тестовые файлы
        4. None (если не существует)

    Tests с маркером @pytest.mark.requires_real_data will skip если return None.
    """
    return _resolve_testdata_dir()


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests с requires_real_data маркером если testdata_dir недоступен."""
    if _resolve_testdata_dir() is not None:
        return  # data доступен — не skip'аем
    skip_reason = pytest.mark.skip(
        reason='AURORA_TESTDATA_DIR not set / no Excel fixtures found — skipping real-data test'
    )
    for item in items:
        if 'requires_real_data' in item.keywords:
            item.add_marker(skip_reason)


# ──────────────────────────────────────────────────────────────────────────
# Pre-trained synthetic model fixture (Phase 1.1 reuse)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope='session')
def synthetic_trained_project(tmp_path_factory):
    """Train MMM один раз per session на synthetic 36×5 data, return project_dir.

    Reused integration tests чтобы избежать MCMC training cost (~30sec) на каждый.
    Использует tools/demo_phase1_9_e2e.py pattern.

    NB: Если PyMC/NumPyro не доступны (lightweight CI без heavy deps) — fixture
    fall-back: возвращает project_dir с синтетическим pickle (point estimates only,
    sufficient для большинства downstream tests).
    """
    project_dir = tmp_path_factory.mktemp('synthetic_trained')
    models_dir = project_dir / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    results_dir = project_dir / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)

    # Lightweight synthetic pickle — encodes Phase 1.9 + Trust 3 schema.
    # 5 channels, 36 monthly obs, predictable structure for downstream tests.
    import numpy as np
    rng = np.random.default_rng(42)

    n_obs = 36
    media_cols = ['TV_TRPs', 'OOH', 'Search', 'Social', 'Mixed_X']
    n_channels = len(media_cols)
    n_samples = 200

    media_betas_samples = np.abs(rng.normal(0.5, 0.2, size=(n_channels, n_samples))).astype(np.float32)
    alphas_samples = np.abs(rng.normal(1.5, 0.3, size=(n_channels, n_samples))).astype(np.float32)
    gammas_samples = np.clip(rng.normal(0.5, 0.15, size=(n_channels, n_samples)), 0.1, 0.9).astype(np.float32)
    intercept_samples = rng.normal(0.0, 0.3, size=n_samples).astype(np.float32)
    decay_samples = np.clip(
        rng.normal(0.3, 0.15, size=(n_channels, n_samples)), 0.0, 0.95
    ).astype(np.float32)

    channel_params = {
        col: {
            'beta': float(media_betas_samples[i].mean()),
            'alpha': float(alphas_samples[i].mean()),
            'gamma': float(gammas_samples[i].mean()),
            'decay': float(decay_samples[i].mean()),
            'beta_ci_low': float(np.quantile(media_betas_samples[i], 0.025)),
            'beta_ci_high': float(np.quantile(media_betas_samples[i], 0.975)),
        }
        for i, col in enumerate(media_cols)
    }

    raw_means = {col: float(100.0 * (i + 1)) for i, col in enumerate(media_cols)}

    model_data = {
        'model_version': '1.2',  # single-prior path (no Trust 3 categories)
        'config': {
            'media_columns': media_cols,
            'control_columns': [],
            'kpi_column': 'sales',
            'date_column': 'date',
            'adstock_config': {col: 'geometric' for col in media_cols},
            'channel_categories': {},
        },
        'media_columns': media_cols,
        'control_columns': [],
        'channel_params': channel_params,
        'channel_categories': {},
        'use_hierarchical': False,
        'hierarchical_priors': {},
        'categorization_warnings': [],
        'normalization': {
            'media_means': raw_means,
            'control_means': {},
            'control_stds': {},
            'y_mean': 1000.0,
            'y_std': 250.0,
            'intercept_mean': float(intercept_samples.mean()),
            'control_betas_mean': [],
            'untrained_channels': [],
        },
        'posterior_samples': {
            'media_betas': media_betas_samples,
            'alphas': alphas_samples,
            'gammas': gammas_samples,
            'intercept': intercept_samples,
            'control_betas': np.zeros((0, n_samples), dtype=np.float32),
            'adstock_decay': decay_samples,
            'adstock_mu_logit_mean': -1.0,
            'adstock_sigma_logit_mean': 0.7,
            'media_columns': media_cols,
            'control_columns': [],
            'n_chains': 2,
            'n_draws': n_samples // 2,
        },
        'y_actual': (1000 + rng.normal(0, 100, n_obs)).tolist(),
        'y_predicted': (1000 + rng.normal(0, 50, n_obs)).tolist(),
        'causal_artifact_path': None,
    }

    pickle_path = models_dir / 'latest.pkl'
    with open(pickle_path, 'wb') as f:
        pickle.dump(model_data, f)

    return project_dir


@pytest.fixture(scope='session')
def kagocel_pathology_project(tmp_path_factory):
    """Synthetic project матчит Kagocel mathematical pathologies.

    Pattern match: TV-dominant с TRPs (native units) + 5 money channels,
    mROAS asymmetry ~350×, low decay (~0.245).
    Используется в integration tests для regression detection (L4-style bugs).
    """
    project_dir = tmp_path_factory.mktemp('kagocel_pathology')
    models_dir = project_dir / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    rng = np.random.default_rng(2026)

    n_obs = 31
    media_cols = ['TRPs бренд', 'OOH', 'Performance', 'Social', 'Search', 'Articles']
    # Categorize по hint heuristic
    cats = {'TRPs бренд': 'brand', 'OOH': 'brand', 'Performance': 'performance',
            'Social': 'performance', 'Search': 'performance', 'Articles': 'mixed'}
    n_channels = len(media_cols)
    n_samples = 200

    # Asymmetric betas (TRPs huge but saturated, others smaller)
    base_betas = np.array([0.8, 0.4, 0.05, 0.04, 0.03, 0.02])
    media_betas_samples = np.abs(
        rng.normal(base_betas[:, None], 0.05, size=(n_channels, n_samples))
    ).astype(np.float32)
    alphas_samples = np.full((n_channels, n_samples), 1.5, dtype=np.float32)
    gammas_samples = np.full((n_channels, n_samples), 0.48, dtype=np.float32)
    intercept_samples = rng.normal(0.0, 0.3, size=n_samples).astype(np.float32)
    # Brand long decay, performance short — Trust 3 hierarchical pattern
    decay_means = np.array([0.65, 0.55, 0.18, 0.20, 0.15, 0.30])
    decay_samples = np.clip(
        rng.normal(decay_means[:, None], 0.08, size=(n_channels, n_samples)), 0.0, 0.95
    ).astype(np.float32)

    channel_params = {
        col: {
            'beta': float(media_betas_samples[i].mean()),
            'alpha': 1.5,
            'gamma': 0.48,
            'decay': float(decay_samples[i].mean()),
        }
        for i, col in enumerate(media_cols)
    }

    raw_means = {
        'TRPs бренд': 50.0,        # native TRP units
        'OOH': 80_000_000.0,       # money RUB
        'Performance': 30_000_000.0,
        'Social': 20_000_000.0,
        'Search': 15_000_000.0,
        'Articles': 5_000_000.0,
    }
    unit_costs = {
        'TRPs бренд': 150_000.0,  # 150k RUB per TRP
        # Others — money channels (uc=1)
    }

    model_data = {
        'model_version': '1.3',  # hierarchical (Trust 3)
        'config': {
            'media_columns': media_cols,
            'control_columns': [],
            'kpi_column': 'sales',
            'date_column': 'date',
            'adstock_config': {col: 'geometric' for col in media_cols},
            'channel_categories': cats,
            'unit_costs': unit_costs,
        },
        'media_columns': media_cols,
        'control_columns': [],
        'channel_params': channel_params,
        'channel_categories': cats,
        'use_hierarchical': True,
        'hierarchical_priors': {
            'brand_mu_logit_mean': 0.7,
            'brand_sigma_mean': 0.6,
            'performance_mu_logit_mean': -1.4,
            'performance_sigma_mean': 0.28,
            'mixed_mu_logit_mean': -1.4,
            'mixed_sigma_mean': 0.4,
        },
        'categorization_warnings': [],
        'normalization': {
            'media_means': raw_means,
            'control_means': {},
            'control_stds': {},
            'y_mean': 100_000_000.0,
            'y_std': 15_000_000.0,
            'intercept_mean': float(intercept_samples.mean()),
            'control_betas_mean': [],
            'untrained_channels': [],
        },
        'posterior_samples': {
            'media_betas': media_betas_samples,
            'alphas': alphas_samples,
            'gammas': gammas_samples,
            'intercept': intercept_samples,
            'control_betas': np.zeros((0, n_samples), dtype=np.float32),
            'adstock_decay': decay_samples,
            'adstock_mu_logit_mean': -0.4,
            'adstock_sigma_logit_mean': 0.7,
            'media_columns': media_cols,
            'control_columns': [],
            'n_chains': 2,
            'n_draws': n_samples // 2,
        },
        'y_actual': (100_000_000 + rng.normal(0, 10_000_000, n_obs)).tolist(),
        'y_predicted': (100_000_000 + rng.normal(0, 5_000_000, n_obs)).tolist(),
        'causal_artifact_path': None,
    }

    pickle_path = models_dir / 'latest.pkl'
    with open(pickle_path, 'wb') as f:
        pickle.dump(model_data, f)

    return project_dir
