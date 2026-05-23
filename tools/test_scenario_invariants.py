"""Scenario engine invariants - property-based tests (Phase A1 of engine audit extension).

Plan: C:\\Users\\ackol\\Desktop\\optimizer-audit-followup-plan.md, этап 4.

Fourteen formal invariants verified across random seeds:

    S1  - Per-period decomposition: predicted_t == baseline_per_period + Σ contribution_t
    S2  - Total energy: sum(predictions) == baseline_total + Σ_ch sum(contribution_per_period)
    S3  - Sign / scale: predictions > 0; incremental ≥ 0 при positive media plan
    S4  - Money conservation: total_spend_money == Σ_ch native[c] × unit_cost[c]
    S5  - Single-period distribution: plan length=1 + forecast_n distributes evenly
    S6  - Adstock semantics: positive raw → positive adstock; sum_adstock ≥ sum_raw для geometric
    S7  - Hill saturation bounds: 0 ≤ hill(x_norm) < 1 для x_norm ≥ 0
    S8  - Posterior CI ordering: predicted_kpi_ci_low ≤ predicted_kpi ≤ predicted_kpi_ci_high
    S9  - ROAS CI consistency: roas_ci = incremental_kpi_ci / total_spend (constant denom)
    S10 - Determinism: same input → identical output across reruns
    S11 - 3-way alignment с optimizer Option C (covered в I8 of optimizer audit; here
          we verify scenario engine alone gives same result as manual sum-of-Hill)
    S12 - Forecast horizon decoupling: plan_n=1 + forecast_periods=N → predictions length=N
    S13 - Money-mode coverage flag: total_spend_money == None iff not all active channels covered
    S14 - Graceful errors: untrained channel → UNTRAINED_CHANNEL; empty plan → MEDIA_PLAN_EMPTY

Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis (Option C identity),
docs/MATH_AUDIT_v1_3_PHASE_0_1.md (chain rule for mROAS context).

Run:
    pytest tools/test_scenario_invariants.py -v
"""
from __future__ import annotations

import math
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.adstock import apply_adstock  # noqa: E402
from utils.saturation import hill_function  # noqa: E402

from _optimizer_fixtures import (  # noqa: E402
    build_synthetic_pickle,
    is_ok,
    make_media_plan_from_current,
)


# ──────────────────────────────────────────────────────────────────────
# S1 - Per-period decomposition: predicted_t = baseline + Σ contribution_t
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(15)))
def test_S1_per_period_decomposition(tmp_path, seed):
    """Each period's predicted equals baseline_per_period + Σ channel contribution.

    Scenario reports `predictions` per period + `channel_contributions` per channel.
    Per-period identity must hold within rounding tolerance.
    """
    proj = tmp_path / f'S1_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)
    plan = make_media_plan_from_current(proj, multiplier=1.0, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': f'S1_seed_{seed}',
        'media_plan': plan,
    }, str(proj))
    assert is_ok(r)

    n_periods = r['n_periods']
    predictions = r['predictions']
    channel_contributions = r['channel_contributions']

    # Compute baseline_per_period from scenario fields
    totals = r['totals']
    baseline_total = float(totals['baseline_kpi'])
    baseline_per_period = baseline_total / n_periods  # uniform per scenario.py:201-204

    for t in range(n_periods):
        ch_sum_t = sum(
            float(channel_contributions[col][t])
            for col in channel_contributions
        )
        expected = baseline_per_period + ch_sum_t
        actual = float(predictions[t])
        rel_err = abs(actual - expected) / max(abs(actual), 1.0)
        # Tolerance 1.5%: round-1 на channel_contributions + round-0 на predictions + baseline averaging
        assert rel_err < 0.015, (
            f'S1 period {t} (seed={seed}): predicted={actual}, '
            f'expected baseline+ch={expected}, rel_err={rel_err*100:.2f}%'
        )


# ──────────────────────────────────────────────────────────────────────
# S2 - Total energy conservation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(15)))
def test_S2_total_energy_conservation(tmp_path, seed):
    """sum(predictions) == baseline_total + Σ_ch sum(contribution_per_period)."""
    proj = tmp_path / f'S2_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'S2', 'media_plan': plan}, str(proj))
    assert is_ok(r)

    pred_sum = sum(float(p) for p in r['predictions'])
    baseline_total = float(r['totals']['baseline_kpi'])
    media_sum = sum(
        sum(float(v) for v in ts) for ts in r['channel_contributions'].values()
    )
    expected = baseline_total + media_sum
    rel_err = abs(pred_sum - expected) / max(abs(pred_sum), 1.0)
    assert rel_err < 0.005, (
        f'S2 (seed={seed}): pred_sum={pred_sum:.0f}, '
        f'baseline+media={expected:.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# S3 - Sign / scale invariants
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_S3_predictions_positive_and_incremental_nonneg(tmp_path, seed):
    """Positive media plan → predicted_kpi > 0, incremental_kpi ≥ 0 (media adds)."""
    proj = tmp_path / f'S3_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'S3', 'media_plan': plan}, str(proj))
    assert is_ok(r)

    totals = r['totals']
    assert float(totals['predicted_kpi']) > 0, f'S3: predicted_kpi non-positive (seed={seed})'
    assert float(totals['baseline_kpi']) > 0, f'S3: baseline_kpi non-positive'
    # Media adds value - incremental ≥ 0 для positive media plan
    assert float(totals['incremental_kpi']) >= -1.0, (
        f'S3: incremental_kpi {totals["incremental_kpi"]} highly negative (seed={seed})'
    )


# ──────────────────────────────────────────────────────────────────────
# S4 - Money conservation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_S4_money_conservation(tmp_path, seed):
    """total_spend_money == Σ_ch per_channel_native[c] × unit_cost[c]."""
    proj = tmp_path / f'S4_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=4, mixed_units=True)
    plan = make_media_plan_from_current(proj, per_period=True)
    unit_costs = md['config']['unit_costs']

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S4',
        'media_plan': plan,
        'unit_costs': unit_costs,
    }, str(proj))
    assert is_ok(r)
    if not r['totals'].get('units_fully_covered'):
        pytest.skip(f'S4 (seed={seed}): mixed coverage - total_spend_money is None')

    per_ch_native = r['per_channel_spend']['native']
    expected_money = sum(
        float(per_ch_native[c]) * float(unit_costs.get(c, 1.0))
        for c in per_ch_native
    )
    actual_money = float(r['totals']['total_spend_money'])
    rel_err = abs(actual_money - expected_money) / max(abs(expected_money), 1.0)
    assert rel_err < 0.005, (
        f'S4 (seed={seed}): total_money={actual_money:.0f}, '
        f'Σnative×uc={expected_money:.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# S5 - Single-period plan distributes evenly across forecast_periods
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(5)))
def test_S5_single_period_distribution(tmp_path, seed):
    """Plan length=1 + forecast_periods=N → media_plan output has length N с total preserved.

    NB: scenario engine mutates input media_plan dict (distribution rewrite - known
    side effect, see SCENARIO_INVARIANTS_REGISTRY.md). Capture totals BEFORE call.
    """
    proj = tmp_path / f'S5_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=3, n_periods=52)
    plan = make_media_plan_from_current(proj, per_period=False)  # single-period totals
    # Capture totals BEFORE predict_scenario mutates the dict.
    expected_totals = {col: float(v[0]) for col, v in plan.items()}

    forecast_n = 12
    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S5',
        'media_plan': plan,
        'forecast_periods': forecast_n,
    }, str(proj))
    assert is_ok(r), f'S5 (seed={seed}): {r.get("error_code")}'

    # Predictions length must equal forecast_n
    assert len(r['predictions']) == forecast_n, (
        f'S5: predictions len={len(r["predictions"])}, expected {forecast_n}'
    )

    # Per-channel native spend must match input total (rounded)
    for col, total_input in expected_totals.items():
        if total_input <= 0:
            continue
        native_total = float(r['per_channel_spend']['native'][col])
        rel_err = abs(native_total - total_input) / max(abs(total_input), 1.0)
        assert rel_err < 0.01, (
            f'S5 channel {col} (seed={seed}): native_total={native_total:.2f}, '
            f'input_total={total_input:.2f}'
        )


# ──────────────────────────────────────────────────────────────────────
# S6 - Adstock semantics: positive raw → positive adstock + carryover increase
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(20)))
def test_S6_adstock_positive_and_carryover(seed):
    """For positive flat input + decay ∈ (0, 1): adstock sum ≥ raw sum (carryover boost).

    Pure math invariant - independent от scenario engine. Confirms adstock
    foundation matches Aurora's convention used в scenario.py:194-195.
    """
    rng = np.random.default_rng(seed)
    n = int(rng.integers(10, 60))
    raw_x = rng.uniform(100, 1000, n)
    decay = float(rng.uniform(0.05, 0.95))

    adstock = apply_adstock(raw_x, 'geometric', {'alpha': decay})
    assert (adstock >= 0).all(), f'S6: negative adstock value (seed={seed})'
    assert adstock.sum() >= raw_x.sum() - 1e-6, (
        f'S6 (seed={seed}, decay={decay:.3f}): '
        f'sum_adstock={adstock.sum():.2f} < sum_raw={raw_x.sum():.2f}'
    )


# ──────────────────────────────────────────────────────────────────────
# S7 - Hill saturation bounds: 0 ≤ hill < 1
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(20)))
def test_S7_hill_bounds(seed):
    """Hill saturation strictly в [0, 1) для finite x_norm ≥ 0."""
    rng = np.random.default_rng(seed)
    alpha = float(rng.uniform(0.5, 4.0))
    gamma = float(rng.uniform(0.1, 1.0))
    x = rng.uniform(0, 100, 200)

    sat = hill_function(x, alpha=alpha, gamma=max(gamma, 1e-6))
    assert (sat >= 0).all(), f'S7: hill < 0 (seed={seed})'
    assert (sat < 1.0 + 1e-9).all(), f'S7: hill ≥ 1 (seed={seed}, max={sat.max()})'
    assert np.isfinite(sat).all(), f'S7: non-finite hill output (seed={seed})'


# ──────────────────────────────────────────────────────────────────────
# S8 - Posterior CI ordering: low ≤ point ≤ high
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_S8_posterior_ci_ordering(tmp_path, seed):
    """When posterior_samples available: ci_low ≤ point ≤ ci_high для all CI fields."""
    proj = tmp_path / f'S8_{seed}'
    build_synthetic_pickle(
        proj, seed=seed, n_channels=4, n_periods=24,
        n_posterior_samples=200,
    )
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'S8', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    totals = r['totals']

    if totals.get('predicted_kpi_ci_low') is None:
        pytest.skip(f'S8 (seed={seed}): no posterior CI')

    pairs = [
        ('predicted_kpi', 'predicted_kpi_ci_low', 'predicted_kpi_ci_high'),
        ('incremental_kpi', 'incremental_kpi_ci_low', 'incremental_kpi_ci_high'),
        ('lift_pct', 'lift_pct_ci_low', 'lift_pct_ci_high'),
    ]
    for point_key, lo_key, hi_key in pairs:
        if totals.get(lo_key) is None:
            continue
        point = float(totals[point_key])
        lo = float(totals[lo_key])
        hi = float(totals[hi_key])
        assert lo <= hi, f'S8 {point_key}: ci_low {lo} > ci_high {hi} (seed={seed})'
        # Point может быть outside HDI by small margin in extreme cases (HDI != percentile);
        # use 5% relative tolerance относительно (hi-lo) или absolute tolerance.
        margin = max(abs(hi - lo) * 0.05, abs(point) * 0.01, 1.0)
        assert lo - margin <= point <= hi + margin, (
            f'S8 {point_key} (seed={seed}): point={point} not в [{lo}, {hi}]'
        )


# ──────────────────────────────────────────────────────────────────────
# S9 - ROAS CI = incremental_kpi_ci / total_spend (constant denominator)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(10)))
def test_S9_roas_ci_consistency(tmp_path, seed):
    """roas_ci_low = incremental_kpi_ci_low / total_spend (denom is scalar)."""
    proj = tmp_path / f'S9_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)
    unit_costs = md['config']['unit_costs']

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S9', 'media_plan': plan, 'unit_costs': unit_costs,
    }, str(proj))
    assert is_ok(r)
    totals = r['totals']

    if (totals.get('incremental_kpi_ci_low') is None
            or totals.get('roas_money_ci_low') is None):
        pytest.skip(f'S9 (seed={seed}): no money CI available')

    inc_lo = float(totals['incremental_kpi_ci_low'])
    inc_hi = float(totals['incremental_kpi_ci_high'])
    money = float(totals['total_spend_money'])

    expected_lo = inc_lo / money
    expected_hi = inc_hi / money
    actual_lo = float(totals['roas_money_ci_low'])
    actual_hi = float(totals['roas_money_ci_high'])

    # Round-2 на ROAS field - tolerance 0.05 absolute
    assert abs(actual_lo - expected_lo) < 0.05, (
        f'S9 lo (seed={seed}): roas_lo={actual_lo}, expected={expected_lo}'
    )
    assert abs(actual_hi - expected_hi) < 0.05, (
        f'S9 hi (seed={seed}): roas_hi={actual_hi}, expected={expected_hi}'
    )


# ──────────────────────────────────────────────────────────────────────
# S10 - Determinism: same input → identical output
# ──────────────────────────────────────────────────────────────────────


def test_S10_determinism(tmp_path):
    """Two calls с identical config produce byte-identical predictions."""
    proj = tmp_path / 'S10'
    build_synthetic_pickle(proj, seed=99, n_channels=4, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r1 = predict_scenario({'scenario_name': 'r1', 'media_plan': plan}, str(proj))
    r2 = predict_scenario({'scenario_name': 'r2', 'media_plan': plan}, str(proj))
    assert is_ok(r1) and is_ok(r2)

    assert r1['predictions'] == r2['predictions'], 'S10: predictions mismatch'
    for col in r1['channel_contributions']:
        assert r1['channel_contributions'][col] == r2['channel_contributions'][col], (
            f'S10: channel_contributions {col} mismatch'
        )
    assert r1['totals']['predicted_kpi'] == r2['totals']['predicted_kpi']
    assert r1['totals']['incremental_kpi'] == r2['totals']['incremental_kpi']


# ──────────────────────────────────────────────────────────────────────
# S11 - Engine identity vs manual sum-of-Hill (extension of optimizer I8)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(5)))
def test_S11_scenario_identity_with_manual_sum_of_hills(tmp_path, seed):
    """Scenario's media_contribution matches manual Σ β·hill(x_norm_t)·y_std summed."""
    proj = tmp_path / f'S11_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=3, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)
    y_std = md['normalization']['y_std']
    channel_params = md['channel_params']

    # Scenario engine output
    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'S11', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    scenario_media_kpi = float(r['totals']['incremental_kpi'])

    # Manual reproduction matching scenario.py:210-228 semantics
    media_total_manual = 0.0
    for col, plan_list in plan.items():
        p = channel_params[col]
        raw = np.array(plan_list, dtype=float)
        adstocked = apply_adstock(raw, 'geometric', {'alpha': p['decay']})
        mean = float(p.get('adstock_mean_posterior', 1.0))
        x_norm = adstocked / max(mean, 1e-10)
        sat = hill_function(np.maximum(x_norm, 0), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
        media_total_manual += float(p['beta']) * float(sat.sum()) * y_std

    rel_err = abs(scenario_media_kpi - media_total_manual) / max(abs(media_total_manual), 1.0)
    assert rel_err < 0.005, (
        f'S11 (seed={seed}): scenario={scenario_media_kpi:.0f}, '
        f'manual={media_total_manual:.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# S12 - Forecast horizon decoupling: plan_n=1 + forecast_periods=N → predictions length=N
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('forecast_n', [4, 8, 12, 24, 52])
def test_S12_forecast_horizon_length(tmp_path, forecast_n):
    """Predictions length matches forecast_periods when plan is single-period."""
    proj = tmp_path / f'S12_{forecast_n}'
    build_synthetic_pickle(proj, seed=2, n_channels=3, n_periods=52)
    plan = make_media_plan_from_current(proj, per_period=False)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S12',
        'media_plan': plan,
        'forecast_periods': forecast_n,
    }, str(proj))
    assert is_ok(r)
    assert r['n_periods'] == forecast_n, (
        f'S12 forecast={forecast_n}: n_periods={r["n_periods"]}'
    )
    assert len(r['predictions']) == forecast_n


# ──────────────────────────────────────────────────────────────────────
# S13 - Money-mode coverage flag
# ──────────────────────────────────────────────────────────────────────


def test_S13_money_mode_flag_when_partial_coverage(tmp_path):
    """unit_costs missing PHYSICAL channel → units_fully_covered=False, total_spend_money=None.

    CI fix 2026-05-24: mixed_units=True fixture puts ONLY channel 0 (tv_trps_brand) as
    physical (uc=150000); ch_1/ch_2/ch_3 are money channels (uc=1.0, classified
    'monetary' by persistence default). F-019 hardening (2026-05-18 pilot) интенционально
    auto-covers money channels (per_channel_input='monetary') когда user provides ANY
    unit_costs — для partial coverage detection нужно drop PHYSICAL channel, который
    не имеет classification='monetary' fallback.
    """
    proj = tmp_path / 'S13'
    md = build_synthetic_pickle(proj, seed=3, n_channels=4, mixed_units=True)
    plan = make_media_plan_from_current(proj, per_period=True)
    media_cols = md['config']['media_columns']

    # CI fix: drop PHYSICAL channel (tv_trps_brand at index 0), not last money channel.
    # Auto-cover для money channels intended per F-019 — physical drop = real partial coverage.
    incomplete_uc = {c: 1.0 for c in media_cols if c != 'tv_trps_brand'}

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S13_partial',
        'media_plan': plan,
        'unit_costs': incomplete_uc,
    }, str(proj))
    assert is_ok(r)
    totals = r['totals']
    assert totals.get('units_fully_covered') is False, (
        f'S13: expected units_fully_covered=False, got {totals.get("units_fully_covered")}'
    )
    assert totals.get('total_spend_money') is None, (
        f'S13: total_spend_money should be None when partial coverage'
    )


def test_S13b_money_mode_flag_when_full_coverage(tmp_path):
    """All channels covered → units_fully_covered=True + roas_money populated."""
    proj = tmp_path / 'S13b'
    md = build_synthetic_pickle(proj, seed=3, n_channels=4, mixed_units=True)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'S13b_full',
        'media_plan': plan,
        'unit_costs': md['config']['unit_costs'],
    }, str(proj))
    assert is_ok(r)
    totals = r['totals']
    assert totals.get('units_fully_covered') is True
    assert totals.get('total_spend_money') is not None
    assert totals.get('roas_money') is not None


# ──────────────────────────────────────────────────────────────────────
# S14 - Graceful errors
# ──────────────────────────────────────────────────────────────────────


def test_S14_empty_plan_rejected(tmp_path):
    """media_plan={} → MEDIA_PLAN_EMPTY error."""
    proj = tmp_path / 'S14a'
    build_synthetic_pickle(proj, seed=1)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'empty', 'media_plan': {}}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MEDIA_PLAN_EMPTY'


def test_S14_untrained_channel_rejected(tmp_path):
    """Plan с untrained channel + positive spend → UNTRAINED_CHANNEL error."""
    proj = tmp_path / 'S14b'
    md = build_synthetic_pickle(
        proj, seed=1, n_channels=3,
        untrained_channels=['ch_2'],
    )
    plan = {'ch_2': [1_000_000.0]}

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'untrained',
        'media_plan': plan,
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'UNTRAINED_CHANNEL'


def test_S14_model_not_found(tmp_path):
    """No pickle → MODEL_NOT_FOUND error (Phase 3 audit fix)."""
    empty_proj = tmp_path / 'S14c'
    empty_proj.mkdir()
    (empty_proj / 'models').mkdir()

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'missing',
        'media_plan': {'ch_0': [1.0]},
    }, str(empty_proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MODEL_NOT_FOUND'


# ──────────────────────────────────────────────────────────────────────
# Standalone runner
# ──────────────────────────────────────────────────────────────────────


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
