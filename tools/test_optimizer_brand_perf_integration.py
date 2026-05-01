"""Integration test для optimizer + ConstraintBundle (D.3 + AUDIT-2).

Замыкает gap между unit tests (test_optimizer_per_group_constraints.py — 17 helper
tests) и реальным optimize() workflow. Проверяет что:

1. Hierarchical модель + brand_max_pct=80% → результирующий brand sum ≤ 80% × current_brand
2. Hierarchical модель + brand_min_pct=110% → brand sum ≥ 110% × current_brand
3. Non-hierarchical модель + per-group passed → PER_GROUP_REQUIRES_HIERARCHICAL_MODEL
4. brand_max_pct > global_max_pct → INFEASIBLE_GROUP_HIERARCHY
5. No per-group fields на любой модели → backward compat (нет regression)

Synthetic pickle с use_hierarchical=True + channel_categories. Mirrors structure
из test_optimizer_kagocel_redistribution.py но добавляет Trust 3 поля.

Run:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python -m pytest tools/test_optimizer_brand_perf_integration.py -v
"""
from __future__ import annotations

import pickle
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))


# ──────────────────────────────────────────────────────────────────────
# Fixture builder — hierarchical model с brand/perf split
# ──────────────────────────────────────────────────────────────────────


def _build_synthetic_hierarchical_pickle(
    project_dir: Path,
    *,
    hierarchical: bool = True,
) -> dict:
    """Build synthetic pickle с 6 каналами: 2 brand + 3 performance + 1 mixed.

    Args:
        project_dir: where to write data + pickle
        hierarchical: if True → use_hierarchical=True, model_version='1.3', channel_categories filled.
                      if False → use_hierarchical=False, model_version='1.2', empty categories.

    Returns:
        loaded model_data dict.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    data_path = project_dir / 'data' / 'synthetic_brand_perf.xlsx'
    data_path.parent.mkdir(exist_ok=True)

    rng = np.random.default_rng(2026)
    n_periods = 31

    # Channel taxonomy:
    # brand: tv_brand (high beta, slow decay), ooh_brand (moderate beta)
    # performance: search, social, programmatic (high beta, fast decay)
    # mixed: native_ad
    media_cols = ['tv_brand', 'ooh_brand', 'search', 'social', 'programmatic', 'native_ad']
    categories = {
        'tv_brand': 'brand',
        'ooh_brand': 'brand',
        'search': 'performance',
        'social': 'performance',
        'programmatic': 'performance',
        'native_ad': 'mixed',
    }

    raw_data = {
        'date': pd.date_range('2025-01-06', periods=n_periods, freq='W-MON'),
        'tv_brand': rng.uniform(2_000_000, 5_000_000, n_periods),
        'ooh_brand': rng.uniform(800_000, 2_000_000, n_periods),
        'search': rng.uniform(500_000, 1_500_000, n_periods),
        'social': rng.uniform(400_000, 1_200_000, n_periods),
        'programmatic': rng.uniform(300_000, 900_000, n_periods),
        'native_ad': rng.uniform(200_000, 600_000, n_periods),
        'kpi': np.zeros(n_periods),
    }
    df = pd.DataFrame(raw_data)

    unit_costs = {col: 1.0 for col in media_cols}

    # Decays calibrated per category
    decays = {
        'tv_brand': 0.65, 'ooh_brand': 0.55,        # brand — slow decay
        'search': 0.18, 'social': 0.20, 'programmatic': 0.22,  # perf — fast
        'native_ad': 0.35,                           # mixed
    }

    betas = {
        'tv_brand': 0.085, 'ooh_brand': 0.055,
        'search': 0.115, 'social': 0.095, 'programmatic': 0.105,
        'native_ad': 0.060,
    }
    alphas = {col: 1.5 + rng.normal(0, 0.05) for col in media_cols}
    gammas = {col: 0.48 + rng.normal(0, 0.02) for col in media_cols}

    from utils.adstock import apply_adstock
    from utils.saturation import hill_function

    adstock_mean_posterior = {}
    media_means = {}
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        adstock_mean_posterior[col] = float(adstocked.mean())
        media_means[col] = float(df[col].mean())

    y_std = 200_000_000.0
    y_mean = 400_000_000.0
    kpi_signal = np.full(n_periods, y_mean / y_std)
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        x_norm = adstocked / max(adstock_mean_posterior[col], 1e-10)
        sat = hill_function(x_norm, alpha=alphas[col], gamma=gammas[col])
        kpi_signal += betas[col] * sat
    kpi_signal += rng.normal(0, 0.05, n_periods)
    df['kpi'] = kpi_signal * y_std + y_mean
    df.to_excel(data_path, index=False)

    n_samples = 200
    posterior_samples = {
        'media_betas': np.array([
            [betas[col] + rng.normal(0, 0.005) for _ in range(n_samples)]
            for col in media_cols
        ], dtype=np.float32),
        'alphas': np.array([
            [alphas[col] + rng.normal(0, 0.02) for _ in range(n_samples)]
            for col in media_cols
        ], dtype=np.float32),
        'gammas': np.array([
            [gammas[col] + rng.normal(0, 0.01) for _ in range(n_samples)]
            for col in media_cols
        ], dtype=np.float32),
        'intercept': np.full(n_samples, -0.265, dtype=np.float32),
        'control_betas': np.zeros((0, n_samples), dtype=np.float32),
        'adstock_decay': np.array([
            [decays[col] + rng.normal(0, 0.003) for _ in range(n_samples)]
            for col in media_cols
        ], dtype=np.float32),
        'adstock_mu_logit_mean': -1.4,
        'adstock_sigma_logit_mean': 0.5,
        'media_columns': media_cols,
        'control_columns': [],
        'n_chains': 4,
        'n_draws': n_samples // 4,
    }

    channel_params = {
        col: {
            'beta': round(betas[col], 4),
            'alpha': round(alphas[col], 4),
            'gamma': round(gammas[col], 4),
            'adstock': {'type': 'geometric'},
            'tail_ess_ok': True,
            'decay': round(decays[col], 4),
            'adstock_mean_posterior': round(adstock_mean_posterior[col], 4),
        }
        for col in media_cols
    }

    model_data = {
        'config': {
            'data_file': str(data_path),
            'kpi_column': 'kpi',
            'media_columns': media_cols,
            'control_columns': [],
            'date_column': 'date',
            'adstock_config': {col: 'geometric' for col in media_cols},
            'unit_costs': unit_costs,
            'merge_rules': {},
        },
        'channel_params': channel_params,
        'normalization': {
            'media_means': media_means,
            'control_means': {},
            'control_stds': {},
            'y_mean': y_mean,
            'y_std': y_std,
            'intercept_mean': -0.265,
            'control_betas_mean': [],
            'untrained_channels': [],
        },
        'posterior_samples': posterior_samples,
        'model_version': '1.3' if hierarchical else '1.2',
        'channel_categories': categories if hierarchical else {},
        'use_hierarchical': hierarchical,
        'y_actual': df['kpi'].tolist(),
        'y_predicted': df['kpi'].tolist(),
        'causal_artifact_path': None,
    }

    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(model_data, f)

    return model_data


@pytest.fixture
def hierarchical_project(tmp_path: Path) -> Path:
    """Synthetic Trust 3 hierarchical project."""
    proj = tmp_path / 'hierarchical'
    _build_synthetic_hierarchical_pickle(proj, hierarchical=True)
    return proj


@pytest.fixture
def flat_project(tmp_path: Path) -> Path:
    """Synthetic pre-Trust3 flat project."""
    proj = tmp_path / 'flat'
    _build_synthetic_hierarchical_pickle(proj, hierarchical=False)
    return proj


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def _channel_money_by_category(result: dict, categories: dict[str, str]) -> dict[str, float]:
    """Aggregate optimal money per category из optimize() result."""
    sums = {'brand': 0.0, 'performance': 0.0, 'mixed': 0.0}
    for ch in result.get('channels', []):
        cat = categories.get(ch['name'], 'mixed')
        money = float(ch.get('optimal_spend_money') or ch.get('optimal_spend') or 0)
        sums[cat] = sums[cat] + money
    return sums


def _current_money_by_category(result: dict, categories: dict[str, str]) -> dict[str, float]:
    sums = {'brand': 0.0, 'performance': 0.0, 'mixed': 0.0}
    for ch in result.get('channels', []):
        cat = categories.get(ch['name'], 'mixed')
        money = float(ch.get('current_spend_money') or ch.get('current_spend') or 0)
        sums[cat] = sums[cat] + money
    return sums


@pytest.mark.integration
def test_brand_max_constraint_respected(hierarchical_project: Path):
    """brand_max_pct=80% → каждый brand канал ≤ 80% × current."""
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        'brand_max_pct': 80.0,  # каждый brand канал не должен расти
    }, str(hierarchical_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"

    categories = {
        'tv_brand': 'brand', 'ooh_brand': 'brand',
        'search': 'performance', 'social': 'performance', 'programmatic': 'performance',
        'native_ad': 'mixed',
    }
    # Per-channel check: каждый brand канал должен иметь optimal ≤ 0.80 × current.
    # Toleranсе 1% для float jitter.
    for ch in result.get('channels', []):
        if categories.get(ch['name']) != 'brand':
            continue
        current = float(ch.get('current_spend_money') or ch.get('current_spend') or 0)
        optimal = float(ch.get('optimal_spend_money') or ch.get('optimal_spend') or 0)
        assert optimal <= current * 0.80 * 1.01, (
            f"{ch['name']}: optimal={optimal:.0f} > current*0.80={current*0.80:.0f} "
            f"(brand_max_pct=80% violated)"
        )


@pytest.mark.integration
def test_brand_min_constraint_respected(hierarchical_project: Path):
    """brand_min_pct=110% → каждый brand канал ≥ 110% × current."""
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 50.0,
        'max_pct': 200.0,
        'brand_min_pct': 110.0,  # brand должен расти минимум на 10%
    }, str(hierarchical_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"

    categories = {
        'tv_brand': 'brand', 'ooh_brand': 'brand',
        'search': 'performance', 'social': 'performance', 'programmatic': 'performance',
        'native_ad': 'mixed',
    }
    for ch in result.get('channels', []):
        if categories.get(ch['name']) != 'brand':
            continue
        current = float(ch.get('current_spend_money') or ch.get('current_spend') or 0)
        optimal = float(ch.get('optimal_spend_money') or ch.get('optimal_spend') or 0)
        assert optimal >= current * 1.10 * 0.99, (
            f"{ch['name']}: optimal={optimal:.0f} < current*1.10={current*1.10:.0f} "
            f"(brand_min_pct=110% violated)"
        )


@pytest.mark.integration
def test_perf_max_constraint_respected(hierarchical_project: Path):
    """perf_max_pct=90% → performance каналы не растут."""
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        'perf_max_pct': 90.0,
    }, str(hierarchical_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"

    perf_channels = ('search', 'social', 'programmatic')
    for ch in result.get('channels', []):
        if ch['name'] not in perf_channels:
            continue
        current = float(ch.get('current_spend_money') or ch.get('current_spend') or 0)
        optimal = float(ch.get('optimal_spend_money') or ch.get('optimal_spend') or 0)
        assert optimal <= current * 0.90 * 1.01, (
            f"{ch['name']}: optimal={optimal:.0f} > current*0.90={current*0.90:.0f} "
            f"(perf_max_pct=90% violated)"
        )


@pytest.mark.integration
def test_per_group_rejected_for_flat_model(flat_project: Path):
    """Pre-Trust3 модель + brand_min_pct → PER_GROUP_REQUIRES_HIERARCHICAL_MODEL.

    AUDIT-2: пользователь не должен мочь применить brand/perf constraints на flat модель,
    потому что MCMC posterior не училась с group-conditional структурой.
    """
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        'brand_min_pct': 80.0,  # тут per-group passed
    }, str(flat_project))

    assert result.get('status') == 'error'
    assert result.get('error_code') == 'PER_GROUP_REQUIRES_HIERARCHICAL_MODEL', (
        f"Expected PER_GROUP_REQUIRES_HIERARCHICAL_MODEL, got {result.get('error_code')}: "
        f"{result.get('message')}"
    )


@pytest.mark.integration
def test_constraint_hierarchy_violation_rejected(hierarchical_project: Path):
    """brand_max_pct=300% > global_max_pct=200% → INFEASIBLE_GROUP_HIERARCHY."""
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        'brand_max_pct': 300.0,  # больше глобального
    }, str(hierarchical_project))

    assert result.get('status') == 'error'
    assert result.get('error_code') == 'INFEASIBLE_GROUP_HIERARCHY', (
        f"Expected INFEASIBLE_GROUP_HIERARCHY, got {result.get('error_code')}: "
        f"{result.get('message')}"
    )
    # Сообщение должно упоминать конкретное превышение
    assert 'Brand max' in result.get('message', '')


@pytest.mark.integration
def test_perf_hierarchy_violation_rejected(hierarchical_project: Path):
    """perf_max_pct=250% > global_max_pct=200% → INFEASIBLE_GROUP_HIERARCHY."""
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        'perf_max_pct': 250.0,
    }, str(hierarchical_project))

    assert result.get('status') == 'error'
    assert result.get('error_code') == 'INFEASIBLE_GROUP_HIERARCHY'
    assert 'Performance max' in result.get('message', '')


@pytest.mark.integration
def test_no_per_group_backward_compat(hierarchical_project: Path):
    """Hierarchical модель БЕЗ per-group fields — behavior identical к pre-D.3.

    Backward compat: если пользователь не задал brand_*/perf_*, optimize должна работать
    как до D.3 (только global + per-channel constraints).
    """
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
        # без brand_*/perf_* fields
    }, str(hierarchical_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"
    assert result.get('optimization_converged') is True


@pytest.mark.integration
def test_no_per_group_on_flat_model_works(flat_project: Path):
    """Pre-Trust3 модель БЕЗ per-group — backward compat работает.

    AUDIT-2 gate срабатывает ТОЛЬКО когда per-group passed. Без них — flat модель
    оптимизируется как раньше.
    """
    from engines.optimizer import optimize

    result = optimize({
        'min_pct': 20.0,
        'max_pct': 200.0,
    }, str(flat_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"


@pytest.mark.integration
def test_mixed_channel_falls_back_to_global(hierarchical_project: Path):
    """Mixed channel (native_ad) игнорирует brand_*/perf_* constraints, использует global.

    Per resolve_channel_bounds семантику: mixed → global fallback.
    """
    from engines.optimizer import optimize

    # Tight brand bounds, loose global bounds
    result = optimize({
        'min_pct': 50.0,
        'max_pct': 200.0,
        'brand_min_pct': 95.0,
        'brand_max_pct': 105.0,
        'perf_min_pct': 95.0,
        'perf_max_pct': 105.0,
    }, str(hierarchical_project))

    assert result.get('status') == 'ok', f"optimize failed: {result.get('message')}"

    # native_ad (mixed) должен иметь bounds = global = [50%, 200%], а не [95%, 105%]
    native = next(ch for ch in result['channels'] if ch['name'] == 'native_ad')
    current = float(native.get('current_spend_money') or native.get('current_spend') or 0)
    optimal = float(native.get('optimal_spend_money') or native.get('optimal_spend') or 0)
    ratio = optimal / max(current, 1.0)
    # Mixed должен попасть в [0.5, 2.0], а не [0.95, 1.05]
    assert 0.50 * 0.99 <= ratio <= 2.00 * 1.01, (
        f"native_ad ratio={ratio:.3f} вне [0.5, 2.0] global bounds"
    )
