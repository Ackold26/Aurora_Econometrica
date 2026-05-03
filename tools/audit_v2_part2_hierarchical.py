"""Audit v2.0 Part 2 — Hierarchical extrapolation experiment (Этап 5 / L5).

Plan: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §6 + §7 L5.

Goal: validate that quantitative threshold (3× training budget) для hierarchical
warning corresponds к meaningful allocation divergence between flat и hierarchical
model на same data.

Synthetic experiment:
    1. Build flat pickle (model_version=1.2) с heterogeneous brand βs (top-performer asymmetry).
    2. Build hierarchical pickle (model_version=1.3) — same data, но брand βs
       pulled toward group mean (simulates posterior shrinkage в Trust 3 path).
    3. Optimize at budgets {1×, 2×, 3×, 5×} for each model.
    4. Compare allocations: cosine similarity + L1 divergence.
    5. Compare top-performer brand channel allocation specifically.
    6. Report at which ratio divergence > 10% (calibration check).

Output: stdout report + JSON snapshot для memory.

Run:
    python tools/audit_v2_part2_hierarchical.py
"""
from __future__ import annotations

import json
import pickle
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.adstock import apply_adstock  # noqa: E402
from utils.saturation import hill_function  # noqa: E402
from _optimizer_fixtures import build_synthetic_pickle, promote_to_hierarchical  # noqa: E402


def build_flat_pickle(project_dir: Path, *, seed: int) -> dict:
    """Heterogeneous brand betas — top performer (TV brand) ~3× others."""
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    data_path = project_dir / 'data' / 'flat.xlsx'
    data_path.parent.mkdir(exist_ok=True)

    rng = np.random.default_rng(seed)
    n_periods = 52
    media_cols = ['tv_brand', 'ooh_brand', 'olv_brand', 'search', 'social', 'programmatic']
    cats = {
        'tv_brand': 'brand', 'ooh_brand': 'brand', 'olv_brand': 'brand',
        'search': 'performance', 'social': 'performance', 'programmatic': 'performance',
    }
    unit_costs = {col: 1.0 for col in media_cols}

    raw_data = {'date': pd.date_range('2024-01-08', periods=n_periods, freq='W-MON')}
    for col in media_cols:
        raw_data[col] = rng.uniform(1_000_000, 5_000_000, n_periods)
    df = pd.DataFrame(raw_data)

    # Heterogeneous betas — top-performer asymmetry в brand pool
    betas_flat = {
        'tv_brand': 0.140,        # ⭐ top performer
        'ooh_brand': 0.060,
        'olv_brand': 0.045,
        'search': 0.080,
        'social': 0.075,
        'programmatic': 0.070,
    }
    decays = {
        'tv_brand': 0.65, 'ooh_brand': 0.55, 'olv_brand': 0.45,
        'search': 0.20, 'social': 0.25, 'programmatic': 0.30,
    }
    alphas = {col: 1.8 for col in media_cols}
    gammas = {col: 0.5 for col in media_cols}
    y_std, y_mean = 200_000_000.0, 400_000_000.0

    adstock_mean_posterior = {}
    media_means = {}
    kpi_signal = np.full(n_periods, y_mean / y_std)
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        adstock_mean_posterior[col] = float(adstocked.mean())
        media_means[col] = float(df[col].mean())
        x_norm = adstocked / max(adstock_mean_posterior[col], 1e-10)
        sat = hill_function(x_norm, alpha=alphas[col], gamma=gammas[col])
        kpi_signal += betas_flat[col] * sat
    kpi_signal += rng.normal(0, 0.03, n_periods)
    df['kpi'] = kpi_signal * y_std + y_mean
    df.to_excel(data_path, index=False)

    # Posterior samples — narrow around point (synthetic flat → no pool variance)
    n_samples = 200
    posterior_samples = {
        'media_betas': np.array([
            [betas_flat[col] + rng.normal(0, 0.005) for _ in range(n_samples)]
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

    channel_params = {
        col: {
            'beta': round(betas_flat[col], 6),
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
            'kpi_type': 'sales',
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
            'untrained_channels': [],
        },
        'posterior_samples': posterior_samples,
        'model_version': '1.2',
        'use_hierarchical': False,
        'channel_categories': cats,  # categorization for cross-check, but flat priors
        'y_actual': df['kpi'].tolist(),
        'y_predicted': df['kpi'].tolist(),
        'causal_artifact_path': None,
    }
    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(model_data, f)
    return model_data


def build_hierarchical_pickle(project_dir: Path, flat_md: dict) -> dict:
    """Same data as flat, но brand βs pulled toward group mean (shrinkage simulation).

    Hierarchical Trust 3 pooling → outliers (top-performer) pulled к pool mean.
    Synthetic shrinkage factor: 0.5 (50% pull toward group mean).
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    # Reuse same xlsx
    data_path = project_dir / 'data' / 'hier.xlsx'
    data_path.parent.mkdir(exist_ok=True)
    pd.read_excel(flat_md['config']['data_file']).to_excel(data_path, index=False)

    md = {**flat_md, 'config': {**flat_md['config'], 'data_file': str(data_path)}}
    md['model_version'] = '1.3'
    md['use_hierarchical'] = True
    cats = md['channel_categories']
    brand_cols = [c for c, cat in cats.items() if cat == 'brand']
    perf_cols = [c for c, cat in cats.items() if cat == 'performance']

    # Compute group means + apply 50% shrinkage to point estimates
    SHRINK = 0.5
    new_params = {}
    for c in cats:
        params = dict(flat_md['channel_params'][c])
        new_params[c] = params

    brand_mean_beta = float(np.mean([flat_md['channel_params'][c]['beta'] for c in brand_cols]))
    perf_mean_beta = float(np.mean([flat_md['channel_params'][c]['beta'] for c in perf_cols]))

    for c in brand_cols:
        b_orig = flat_md['channel_params'][c]['beta']
        new_params[c]['beta'] = round(b_orig * (1 - SHRINK) + brand_mean_beta * SHRINK, 6)
    for c in perf_cols:
        b_orig = flat_md['channel_params'][c]['beta']
        new_params[c]['beta'] = round(b_orig * (1 - SHRINK) + perf_mean_beta * SHRINK, 6)

    md['channel_params'] = new_params

    # Re-shrink posterior samples for media_betas
    rng = np.random.default_rng(2027)
    n_samples = 200
    new_betas_samples = []
    for c in cats:
        b_pooled = new_params[c]['beta']
        new_betas_samples.append(
            [b_pooled + rng.normal(0, 0.003) for _ in range(n_samples)]
        )
    md['posterior_samples'] = {**flat_md['posterior_samples']}
    md['posterior_samples']['media_betas'] = np.array(new_betas_samples, dtype=np.float32)

    md['hierarchical_priors'] = {
        'brand_mu_logit_mean': float(np.mean([d['decay'] for k, d in new_params.items() if cats[k] == 'brand'])),
        'brand_sigma_mean': 0.6,
        'performance_mu_logit_mean': float(np.mean([d['decay'] for k, d in new_params.items() if cats[k] == 'performance'])),
        'performance_sigma_mean': 0.28,
    }

    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)
    return md


def cosine_sim(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    denom = (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)) or 1.0
    return float(np.dot(a_arr, b_arr) / denom)


def l1_divergence(a: list[float], b: list[float]) -> float:
    """Σ |a_i - b_i| / Σ a_i — L1 relative divergence."""
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    return float(np.sum(np.abs(a_arr - b_arr)) / max(np.sum(a_arr), 1.0))


def run_experiment() -> dict:
    """Build pickles, run optimize at multiple ratios, compute divergence."""
    tmp = Path(tempfile.mkdtemp(prefix='aurora-audit-v2-part2-'))
    flat_proj = tmp / 'flat'
    hier_proj = tmp / 'hier'

    flat_md = build_flat_pickle(flat_proj, seed=2026)
    hier_md = build_hierarchical_pickle(hier_proj, flat_md)

    df_flat = pd.read_excel(flat_md['config']['data_file'])
    media_cols = flat_md['config']['media_columns']
    train_total_money = float(sum(df_flat[c].sum() for c in media_cols))

    from engines.optimizer import optimize

    results = []
    for ratio in [1.0, 2.0, 3.0, 5.0]:
        budget = train_total_money * ratio

        cfg_base = {
            'min_pct': 0.0, 'max_pct': 500.0,
            'total_budget_money': budget,
            'forecast_periods': 52,
        }
        r_flat = optimize(cfg_base, str(flat_proj))
        r_hier = optimize(cfg_base, str(hier_proj))

        if r_flat.get('status') != 'ok' or r_hier.get('status') != 'ok':
            results.append({
                'ratio': ratio, 'status': 'one_failed',
                'flat_status': r_flat.get('status'),
                'hier_status': r_hier.get('status'),
            })
            continue

        # Sort channels by name for aligned comparison
        flat_alloc = sorted(
            [(ch['name'], ch['optimal_spend_money']) for ch in r_flat['channels']],
            key=lambda x: x[0],
        )
        hier_alloc = sorted(
            [(ch['name'], ch['optimal_spend_money']) for ch in r_hier['channels']],
            key=lambda x: x[0],
        )
        flat_vals = [v for _, v in flat_alloc]
        hier_vals = [v for _, v in hier_alloc]

        # Top-performer (tv_brand) allocation specifically
        top_flat = next(v for n, v in flat_alloc if n == 'tv_brand')
        top_hier = next(v for n, v in hier_alloc if n == 'tv_brand')
        top_diff_pct = (top_flat - top_hier) / max(top_flat, 1.0) * 100

        results.append({
            'ratio': ratio,
            'budget_money': round(budget, 0),
            'cosine_similarity': round(cosine_sim(flat_vals, hier_vals), 4),
            'l1_divergence_pct': round(l1_divergence(flat_vals, hier_vals) * 100, 2),
            'lift_flat': round(float(r_flat['expected_lift_pct']), 2),
            'lift_hier': round(float(r_hier['expected_lift_pct']), 2),
            'top_performer_flat': round(top_flat, 0),
            'top_performer_hier': round(top_hier, 0),
            'top_performer_underestimate_pct': round(top_diff_pct, 2),
        })

    return {
        'train_total_money': round(train_total_money, 0),
        'shrinkage_factor': 0.5,  # synthetic param
        'experiment_results': results,
    }


def main() -> None:
    print('=== Aurora MATH AUDIT v2.0 Part 2 — Hierarchical extrapolation experiment ===\n')
    out = run_experiment()
    print(f'Training total budget: {out["train_total_money"]:,.0f} ₽')
    print(f'Synthetic shrinkage factor (β pooling 50%): {out["shrinkage_factor"]}\n')

    print(f'{"ratio":>6} | {"L1_div%":>8} | {"cos_sim":>8} | {"lift_flat":>10} | {"lift_hier":>10} | {"top_flat":>14} | {"top_hier":>14} | {"underest%":>10}')
    print('-' * 110)
    for r in out['experiment_results']:
        if r.get('status') == 'one_failed':
            print(f'{r["ratio"]:>6} | FAILED ({r["flat_status"]}/{r["hier_status"]})')
            continue
        print(
            f'{r["ratio"]:>6.1f} | {r["l1_divergence_pct"]:>8.2f} | '
            f'{r["cosine_similarity"]:>8.4f} | {r["lift_flat"]:>10.2f} | '
            f'{r["lift_hier"]:>10.2f} | {r["top_performer_flat"]:>14,.0f} | '
            f'{r["top_performer_hier"]:>14,.0f} | {r["top_performer_underestimate_pct"]:>10.2f}'
        )

    print()
    # Output JSON snapshot
    snapshot = ROOT / 'docs' / 'audit_v2_part2_hierarchical_results.json'
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f'Snapshot saved: {snapshot}')


if __name__ == '__main__':
    main()
