"""
Optimizer Kagocel-redistribution lock-in test (math-fix v1.0.14.1, A1 fix-session 2026-04-28).

Reproduces the 0% lift bug reported on real Kagocel data via a SYNTHETIC
fixture с такими же mathematical pathologies:
  - 6 channels, 1 in native units (TRPs, uc=150_000 ₽/TRP), 5 in money (uc=1)
  - mROAS asymmetry ~350× between channels (TRPs saturated, small channels efficient)
  - Hill α ≈ 1.5, γ ≈ 0.48, decay ≈ 0.245 (uniform — Phase 1.1 hierarchical pulled tight)
  - n_periods = 31 weeks
  - Bounds spread 10⁵× (TRPs native ~10⁴ vs money channels ~10⁸)
  - Money budget constraint (sum x · uc = target)

Pre-fix evidence (scipy direct repro):
  start = current  → SLSQP success=True, iter=1, lift=+0.00%   ← BUG
  start = extreme  → lift=+28.30%                              ← real optimum

Acceptance gates:
  G1: lift_pct ≥ 5%                                  (proved 28% achievable)
  G2: Performance/Social/RetailMedia delta ≥ +5%     (high mROAS → grow)
  G3: TRPs delta ≤ -3%                                (low mROAS → shrink)
  G4: optimization_converged = True
  G5: status == 'ok'
  G6: insight string mentions actual reallocation (not vacuous "сохранить")

Run:
    cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
    python tools/test_optimizer_kagocel_redistribution.py

Exit 0 on success, 1 on failure. Plain stdlib + numpy + pandas — no pytest.
"""
from __future__ import annotations

import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))

import numpy as np
import pandas as pd

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, hint: str = '') -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f'[OK]   {label}')
    else:
        FAILED += 1
        print(f'[FAIL] {label}' + (f' — {hint}' if hint else ''))


# ──────────────────────────────────────────────────────────────────────
# Synthetic Kagocel fixture builder
# ──────────────────────────────────────────────────────────────────────

def build_synthetic_kagocel_fixture(project_dir: Path) -> dict:
    """Build a Kagocel-like synthetic project (data + pickle).

    Returns the model_data dict for inspection в тесте.

    Channel taxonomy (mirrors real Kagocel structure):
      tv_trps_brand    : native (TRPs), uc=150_000, low β·gamma → low mROAS
      olv              : money,         uc=1,       moderate β
      banners          : money,         uc=1,       moderate β
      social           : money,         uc=1,       high β → high mROAS
      retail_media     : money,         uc=1,       moderate-high β
      performance      : money,         uc=1,       high β → high mROAS

    Shaped so total_money ≈ 3.6B ₽, TRPs ≈ 92% of budget. Same ratio
    as real Kagocel, ensuring optimizer must redistribute small money
    channels к 200% bound while TRPs absorbs balance.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    models_dir = project_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    data_path = project_dir / 'data' / 'synthetic_kagocel.xlsx'
    data_path.parent.mkdir(exist_ok=True)

    rng = np.random.default_rng(2026)
    n_periods = 31

    # Realistic spend patterns (bursty TRPs, smoother digital)
    raw_data = {
        'date': pd.date_range('2025-01-06', periods=n_periods, freq='W-MON'),
        # Money channels — varied weekly spend, scale similar to real Kagocel
        'olv': rng.uniform(2_000_000, 5_000_000, n_periods),
        'banners': rng.uniform(2_500_000, 5_500_000, n_periods),
        'social': rng.uniform(300_000, 800_000, n_periods),
        'retail_media': rng.uniform(300_000, 800_000, n_periods),
        'performance': rng.uniform(500_000, 1_300_000, n_periods),
        # TRPs — bursty (some weeks 1500, others 200)
        'tv_trps_brand': np.concatenate([
            rng.uniform(800, 1500, 18),  # active campaign
            rng.uniform(100, 400, 13),   # quiet period
        ])[:n_periods],
        # Synthetic KPI — sum of media contributions + baseline + noise
        # We compute exact KPI below (depends on channel_params)
        'kpi': np.zeros(n_periods),
    }
    df = pd.DataFrame(raw_data)

    media_cols = ['olv', 'banners', 'social', 'retail_media', 'performance', 'tv_trps_brand']
    unit_costs = {
        'olv': 1.0, 'banners': 1.0, 'social': 1.0, 'retail_media': 1.0,
        'performance': 1.0, 'tv_trps_brand': 150_000.0,
    }

    # Channel parameters: similar shape (Phase 1.1 hierarchical pooling),
    # different βs reflecting effectiveness asymmetry.
    # Critical: mean of adstocked spend computed from actual training raw → realistic.
    from utils.adstock import apply_adstock

    # Use Phase 1.1 hierarchical-pulled decay ≈ 0.245 across channels
    decays = {col: 0.245 for col in media_cols}

    # β values calibrated so mROAS_money asymmetry ≈ 350× (matches real Kagocel)
    # mROAS_money ∝ β / (mean × unit_cost) approximately (full chain rule below)
    betas = {
        'olv': 0.0567,
        'banners': 0.0631,
        'social': 0.0821,         # high → high mROAS
        'retail_media': 0.0527,
        'performance': 0.1169,    # highest → highest mROAS
        'tv_trps_brand': 0.0475,  # moderate β BUT TRPs scale 1422 makes mROAS_money tiny
    }
    alphas = {col: 1.5 + rng.normal(0, 0.05) for col in media_cols}
    gammas = {col: 0.48 + rng.normal(0, 0.02) for col in media_cols}

    # Compute adstock_mean_posterior = mean of training adstocked spend per channel
    adstock_mean_posterior = {}
    media_means = {}
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        adstock_mean_posterior[col] = float(adstocked.mean())
        media_means[col] = float(df[col].mean())

    # Build synthetic KPI = β × hill(adstock(x)/mean) × y_std + baseline + noise
    from utils.saturation import hill_function
    y_std = 180_000_000.0
    y_mean = 360_000_000.0

    kpi_signal = np.full(n_periods, y_mean / y_std)  # normalized baseline ≈ 2.0
    for col in media_cols:
        adstocked = apply_adstock(df[col].values, 'geometric', {'alpha': decays[col]})
        x_norm = adstocked / max(adstock_mean_posterior[col], 1e-10)
        sat = hill_function(x_norm, alpha=alphas[col], gamma=gammas[col])
        kpi_signal += betas[col] * sat

    # Add small noise + denormalize
    kpi_signal += rng.normal(0, 0.05, n_periods)
    df['kpi'] = kpi_signal * y_std + y_mean
    df.to_excel(data_path, index=False)

    # Posterior samples (small — 200 draws, just enough for CI computation)
    n_samples = 200
    n_ch = len(media_cols)
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
        'model_version': '1.2',
        'y_actual': df['kpi'].tolist(),
        'y_predicted': df['kpi'].tolist(),  # synthetic — match perfectly
        'causal_artifact_path': None,
    }

    with open(models_dir / 'latest.pkl', 'wb') as f:
        pickle.dump(model_data, f)

    return model_data


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print('── Optimizer Kagocel-redistribution lock-in ──')

    tmp_root = Path(tempfile.mkdtemp(prefix='aurora-optimizer-test-'))
    try:
        proj = tmp_root / 'synthetic_kagocel'
        model_data = build_synthetic_kagocel_fixture(proj)
        check('Synthetic fixture built', (proj / 'models' / 'latest.pkl').exists())

        from engines.optimizer import optimize
        result = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))

        # G5 — status ok
        check('G5: status == "ok"', result.get('status') == 'ok',
              hint=f'got {result.get("status")} / {result.get("error_code")} / {result.get("message")}')
        if result.get('status') != 'ok':
            return 1  # cannot continue without ok

        # G4 — converged
        check('G4: optimization_converged == True',
              result.get('optimization_converged') is True,
              hint=str(result.get('optimization_converged')))

        # G1 — lift ≥ 5%
        lift = float(result.get('expected_lift_pct') or 0)
        check(f'G1: lift_pct ≥ 5.0 (got {lift:.2f})', lift >= 5.0,
              hint='Multi-start failed to escape current allocation local trap')

        # G2 — Performance/Social/RetailMedia grow
        deltas = {ch['name']: float(ch.get('delta_pct') or 0) for ch in result.get('channels', [])}
        check(f'G2a: performance delta ≥ +5% (got {deltas.get("performance", 0):+.2f}%)',
              deltas.get('performance', 0) >= 5.0)
        check(f'G2b: social delta ≥ +5% (got {deltas.get("social", 0):+.2f}%)',
              deltas.get('social', 0) >= 5.0)
        check(f'G2c: retail_media delta ≥ +5% (got {deltas.get("retail_media", 0):+.2f}%)',
              deltas.get('retail_media', 0) >= 5.0)

        # G3 — TRPs shrinks
        check(f'G3: tv_trps_brand delta ≤ -3% (got {deltas.get("tv_trps_brand", 0):+.2f}%)',
              deltas.get('tv_trps_brand', 0) <= -3.0)

        # G6 — narrative non-vacuous
        insight = result.get('insight') or ''
        check('G6: insight mentions reallocation',
              ('Увеличить' in insight) or ('Сократить' in insight),
              hint=f'insight="{insight[:120]}"')

        # ──────────────────────────────────────────────────────────────
        # L10 — math-fix v1.0.16 lock-in: lift_pct correct когда
        # money_target ≠ current_total_money (What-if scenarios).
        # Pre-fix regression: x0_money projected to money_target inflated
        # baseline → lift_pct artifacts (-50% budget → +124% «lift»).
        # ──────────────────────────────────────────────────────────────
        print('── L10: What-if budget regression lock-in ──')
        from engines.optimizer import optimize as _optimize

        # Compute current money total через config + xlsx (matches optimizer.py logic)
        import pandas as pd
        with open(proj / 'models' / 'latest.pkl', 'rb') as f:
            md = pickle.load(f)
        df_m = pd.read_excel(md['config']['data_file'])
        media_cols_m = md['config']['media_columns']
        uc_m = md['config']['unit_costs']
        current_total_money = sum(
            float(df_m[c].fillna(0).sum()) * float(uc_m.get(c, 1.0))
            for c in media_cols_m
        )

        # L10a — half budget should give SMALL or NEGATIVE lift_pct
        # (Hill saturation monotonic — less spend = less media response,
        # max possible: optimizer redistributes within smaller budget).
        result_half = _optimize({
            'min_pct': 10.0,
            'max_pct': 300.0,
            'total_budget_money': current_total_money * 0.5,
        }, str(proj))
        lift_half = float(result_half.get('expected_lift_pct') or 0)
        # Pre-fix этот test failed с lift_half ≈ +124%.
        # Post-fix expected: lift_half < 50% (если позитив, то скромный
        # redistribution gain в смягчающем budget).
        check(
            f'L10a: half budget lift_pct < +50 (got {lift_half:+.2f}%)',
            lift_half < 50.0,
            hint='lift_pct inflated when money_target < current_total — L10 regression',
        )

        # L10b — double budget should give POSITIVE lift bigger than default
        # (more money → more media potential, but diminishing returns)
        result_default = _optimize({
            'min_pct': 10.0,
            'max_pct': 300.0,
            'total_budget_money': current_total_money,
        }, str(proj))
        lift_default = float(result_default.get('expected_lift_pct') or 0)

        result_double = _optimize({
            'min_pct': 10.0,
            'max_pct': 300.0,
            'total_budget_money': current_total_money * 2.0,
        }, str(proj))
        lift_double = float(result_double.get('expected_lift_pct') or 0)
        # Pre-fix этот test failed с lift_double ≈ +10% (меньше default 30%).
        # Post-fix expected: lift_double > lift_default (more budget → more lift).
        check(
            f'L10b: 2× budget lift > default (got {lift_double:.2f}% vs default {lift_default:.2f}%)',
            lift_double > lift_default,
            hint='2× budget should give more lift, not less — L10 inverted relationship',
        )

        # L10c — property-based monotonicity test (SA18)
        # Lift_pct должно strictly не-decreasing с money_target ratio.
        # Hill saturation монотонна — больше spend → больше effect.
        targets = [0.5, 0.75, 1.0, 1.5, 2.0]
        lifts = []
        for ratio in targets:
            r = _optimize({
                'min_pct': 10.0, 'max_pct': 300.0,
                'total_budget_money': current_total_money * ratio,
            }, str(proj))
            lifts.append(float(r.get('expected_lift_pct') or 0))
        monotonic = all(
            lifts[i + 1] >= lifts[i] - 0.5  # 0.5pp tolerance for numerical jitter
            for i in range(len(lifts) - 1)
        )
        check(
            f'L10c: lift_pct monotonic in budget — {dict(zip(targets, [round(l, 1) for l in lifts]))}',
            monotonic,
            hint='Hill saturation монотонна — больше budget должен давать больше lift',
        )

    finally:
        # Cleanup
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass

    print(f'\n{PASSED} passed, {FAILED} failed.')
    return 0 if FAILED == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
