"""Shared synthetic-pickle fixture builder для optimizer tests (Phase 1+2 audit).

Used by:
    tools/test_optimizer_invariants.py   (Phase 1)
    tools/test_optimizer_edge_cases.py   (Phase 2)
    tools/test_optimizer_smoke_matrix.py (Phase 4)

Filename starts with `_` so pytest doesn't collect it as a test module.

Pattern mirrors test_optimizer_kagocel_redistribution.py - geometric adstock +
Hill saturation + posterior samples produce a v1.2 pickle compatible with
optimizer.optimize().
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
if str(SIDECAR) not in sys.path:
    sys.path.insert(0, str(SIDECAR))
if str(SIDECAR / 'econometrica') not in sys.path:
    sys.path.insert(0, str(SIDECAR / 'econometrica'))

from utils.adstock import apply_adstock  # noqa: E402
from utils.saturation import hill_function  # noqa: E402


def build_synthetic_pickle(
    project_dir: Path,
    *,
    seed: int,
    n_channels: int = 6,
    n_periods: int = 31,
    mixed_units: bool = True,
    n_posterior_samples: int = 200,
    awareness: bool = False,
    zero_spend_channels: list[str] | None = None,
    untrained_channels: list[str] | None = None,
) -> dict:
    """Build synthetic pickle compatible with optimizer.optimize().

    Args:
        project_dir: created on disk
        seed: numpy seed
        n_channels: 1..20 supported
        n_periods: training horizon
        mixed_units: True → 1 native (TRPs uc=150_000), rest money
        n_posterior_samples: 0 → no posterior_samples (legacy v1.0/1.1 path)
        awareness: True → KPI tagged как awareness (1.5× horizon cap)
        zero_spend_channels: names → set spend≡0 in raw data (degenerate fixture)
        untrained_channels: names → register в normalization.untrained_channels

    Returns:
        model_data dict (pickle saved at project_dir/models/latest.pkl).
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    data_path = project_dir / 'data' / 'synthetic.xlsx'
    data_path.parent.mkdir(exist_ok=True)

    rng = np.random.default_rng(seed)
    zero_set = set(zero_spend_channels or [])

    media_cols: list[str] = []
    unit_costs: dict[str, float] = {}
    for i in range(n_channels):
        if mixed_units and i == 0:
            name = 'tv_trps_brand'
            unit_costs[name] = 150_000.0
        else:
            name = f'ch_{i}'
            unit_costs[name] = 1.0
        media_cols.append(name)

    raw_data: dict = {
        'date': pd.date_range('2025-01-06', periods=n_periods, freq='W-MON'),
    }
    for col in media_cols:
        if col in zero_set:
            raw_data[col] = np.zeros(n_periods)
        elif col == 'tv_trps_brand':
            raw_data[col] = rng.uniform(200, 1500, n_periods)
        else:
            raw_data[col] = rng.uniform(500_000, 5_000_000, n_periods)

    decays = {col: float(rng.uniform(0.2, 0.7)) for col in media_cols}
    alphas = {col: float(rng.uniform(1.5, 2.8)) for col in media_cols}
    gammas = {col: float(rng.uniform(0.4, 0.7)) for col in media_cols}
    betas = {col: float(rng.uniform(0.04, 0.12)) for col in media_cols}

    if awareness:
        y_std, y_mean = 0.10, 0.50
    else:
        y_std, y_mean = 180_000_000.0, 360_000_000.0

    df = pd.DataFrame(raw_data)

    adstock_mean_posterior: dict[str, float] = {}
    media_means: dict[str, float] = {}
    kpi_signal = np.full(n_periods, y_mean / y_std)
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        adstock_mean_posterior[col] = float(adstocked.mean())
        media_means[col] = float(df[col].mean())
        denom = max(adstock_mean_posterior[col], 1e-10)
        x_norm = adstocked / denom
        sat = hill_function(x_norm, alpha=alphas[col], gamma=gammas[col])
        kpi_signal += betas[col] * sat
    kpi_signal += rng.normal(0, 0.03, n_periods)
    df['kpi'] = kpi_signal * y_std + y_mean
    df.to_excel(data_path, index=False)

    if n_posterior_samples > 0:
        n_samples = n_posterior_samples
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
            'intercept': np.full(n_samples, 0.0, dtype=np.float32),
            'control_betas': np.zeros((0, n_samples), dtype=np.float32),
            'adstock_decay': np.array([
                [decays[col] + rng.normal(0, 0.003) for _ in range(n_samples)]
                for col in media_cols
            ], dtype=np.float32),
            'media_columns': media_cols,
            'control_columns': [],
            'n_chains': 4,
            'n_draws': n_samples // 4,
        }
    else:
        posterior_samples = None

    channel_params = {
        col: {
            'beta': round(betas[col], 6),
            'alpha': round(alphas[col], 6),
            'gamma': round(gammas[col], 6),
            'adstock': {'type': 'geometric'},
            'tail_ess_ok': True,
            'decay': round(decays[col], 6),
            'adstock_mean_posterior': round(adstock_mean_posterior[col], 6),
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
            'kpi_type': 'awareness' if awareness else 'sales',
        },
        'channel_params': channel_params,
        'normalization': {
            'media_means': media_means,
            'control_means': {},
            'control_stds': {},
            'y_mean': y_mean,
            'y_std': y_std,
            'intercept_mean': 0.0,
            'control_betas_mean': [],
            'untrained_channels': list(untrained_channels or []),
        },
        'posterior_samples': posterior_samples,
        'model_version': '1.2',
        'y_actual': df['kpi'].tolist(),
        'y_predicted': df['kpi'].tolist(),
        'causal_artifact_path': None,
    }
    if awareness:
        model_data['kpi_type'] = 'awareness'

    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(model_data, f)

    return model_data


def is_ok(result: dict) -> bool:
    return result.get('status') == 'ok'


def make_media_plan_from_current(
    project_dir: Path,
    *,
    multiplier: float = 1.0,
    per_period: bool = False,
) -> dict[str, list[float]]:
    """Build media_plan dict from current spend в pickle.

    Args:
        project_dir: project с models/latest.pkl + data file.
        multiplier: scale factor (1.0 = current allocation).
        per_period: True → per-period list of len n_periods (each = period_spend × multiplier).
                    False → single-period total list (length 1) - scenario distributes evenly
                    across forecast_periods OR training_n_periods.

    Returns:
        {channel_name: [...] }
    """
    md = pickle.load(open(project_dir / 'models' / 'latest.pkl', 'rb'))
    df = pd.read_excel(md['config']['data_file'])
    media_cols = md['config']['media_columns']
    out: dict[str, list[float]] = {}
    if per_period:
        for c in media_cols:
            out[c] = [float(v) * multiplier for v in df[c].fillna(0).tolist()]
    else:
        for c in media_cols:
            total = float(df[c].fillna(0).sum())
            out[c] = [total * multiplier]
    return out


def current_total_money(project_dir: Path) -> float:
    """Sum of df[col].sum() × unit_cost for all media_cols (matches optimizer)."""
    md = pickle.load(open(project_dir / 'models' / 'latest.pkl', 'rb'))
    df = pd.read_excel(md['config']['data_file'])
    media_cols = md['config']['media_columns']
    uc = md['config']['unit_costs']
    return sum(
        float(df[c].fillna(0).sum()) * float(uc.get(c, 1.0))
        for c in media_cols
    )


def build_multi_year_pickle(
    project_dir: Path,
    *,
    seed: int,
    n_channels: int = 6,
    awareness: bool = False,
) -> dict:
    """Pickle с 104-week training horizon spanning calendar years 2024-2025.

    Used for inflation tests (single-year fixture → weighted-avg == current_cost).
    """
    md = build_synthetic_pickle(
        project_dir,
        seed=seed,
        n_channels=n_channels,
        n_periods=104,
        awareness=awareness,
    )
    df = pd.read_excel(md['config']['data_file'])
    df['date'] = pd.date_range('2024-01-08', periods=104, freq='W-MON')
    df.to_excel(md['config']['data_file'], index=False)
    return md


def promote_to_hierarchical(
    project_dir: Path,
    *,
    categories: dict[str, str] | None = None,
) -> dict:
    """In-place pickle promotion к Trust 3 hierarchical (model_version=1.3).

    Sets channel_categories с brand/performance split. По умолчанию: первая
    половина каналов = brand, вторая = performance.

    Returns updated model_data (also persisted к pickle).
    """
    pkl = project_dir / 'models' / 'latest.pkl'
    md = pickle.load(open(pkl, 'rb'))
    media_cols = md['config']['media_columns']
    n = len(media_cols)
    if categories is None:
        half = n // 2
        categories = {col: ('brand' if i < half else 'performance')
                      for i, col in enumerate(media_cols)}
    md['model_version'] = '1.3'
    md['use_hierarchical'] = True
    md['channel_categories'] = categories
    md['hierarchical_priors'] = {
        'brand_mean': 0.075,
        'brand_sigma': 0.02,
        'performance_mean': 0.085,
        'performance_sigma': 0.02,
    }
    with open(pkl, 'wb') as f:
        pickle.dump(md, f)
    return md


def build_kagocel_shape(project_dir: Path, *, seed: int = 2026) -> dict:
    """Synthetic Kagocel-shape pickle: 6 channels, 1 native (TRPs uc=150_000),
    5 money. Multi-year (2024-2025). β asymmetry mimics realistic Russian FMCG.

    Used by Phase 4 smoke matrix C5 + C12 (pass-18 What-if regression).
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    data_path = project_dir / 'data' / 'synthetic_kagocel.xlsx'
    data_path.parent.mkdir(exist_ok=True)

    rng = np.random.default_rng(seed)
    n_periods = 104  # 2 years weekly

    media_cols = ['olv', 'banners', 'social', 'retail_media', 'performance', 'tv_trps_brand']
    unit_costs = {col: 1.0 for col in media_cols if col != 'tv_trps_brand'}
    unit_costs['tv_trps_brand'] = 150_000.0

    raw_data: dict = {
        'date': pd.date_range('2024-01-08', periods=n_periods, freq='W-MON'),
        'olv': rng.uniform(2_000_000, 5_000_000, n_periods),
        'banners': rng.uniform(2_500_000, 5_500_000, n_periods),
        'social': rng.uniform(300_000, 800_000, n_periods),
        'retail_media': rng.uniform(300_000, 800_000, n_periods),
        'performance': rng.uniform(500_000, 1_300_000, n_periods),
        'tv_trps_brand': np.concatenate([
            rng.uniform(800, 1500, 60),
            rng.uniform(100, 400, n_periods - 60),
        ]),
    }
    df = pd.DataFrame(raw_data)

    decays = {col: 0.245 for col in media_cols}
    betas = {
        'olv': 0.0567, 'banners': 0.0631, 'social': 0.0821,
        'retail_media': 0.0527, 'performance': 0.1169, 'tv_trps_brand': 0.0475,
    }
    alphas = {col: 1.5 + float(rng.normal(0, 0.05)) for col in media_cols}
    gammas = {col: 0.48 + float(rng.normal(0, 0.02)) for col in media_cols}

    y_std, y_mean = 180_000_000.0, 360_000_000.0

    adstock_mean_posterior: dict[str, float] = {}
    media_means: dict[str, float] = {}
    kpi_signal = np.full(n_periods, y_mean / y_std)
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        adstock_mean_posterior[col] = float(adstocked.mean())
        media_means[col] = float(df[col].mean())
        denom = max(adstock_mean_posterior[col], 1e-10)
        x_norm = adstocked / denom
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
            'kpi_type': 'sales',
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
        'model_version': '1.2',
        'y_actual': df['kpi'].tolist(),
        'y_predicted': df['kpi'].tolist(),
        'causal_artifact_path': None,
    }
    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(model_data, f)
    return model_data
