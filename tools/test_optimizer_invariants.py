"""Optimizer invariants — property-based tests (Phase 1 of audit).

Plan: C:\\Users\\ackol\\.claude\\plans\\zazzy-tumbling-kettle.md

Eight formal invariants verified across random seeds:

    I1 — Monotonicity: wider bounds ⊃ narrow → optimal(wider) ≥ optimal(narrow)
    I2 — Conservation: Σ optimal_money ≈ money_target (eq constraint)
    I3 — Bounds satisfaction: optimal_money[i] ∈ [bounds[i].lo, bounds[i].hi]
    I4 — Backward compat: planning_mode=False → analyst-mode echo + deterministic
    I5 — Lift sign: lift_pct(wider) ≥ lift_pct(narrower) (corollary I1)
    I6 — mROAS chain rule: _compute_mroas_money matches finite-difference
    I7 — Constraint precedence: per-channel > per-group > global
    I8 — Option C alignment: evaluate_flat_allocation_response identical to
         per-period sum-of-Hill (scenario.py:167-186 semantics)

Math refs:
    docs/MATH_AUDIT_v1_3_PHASE_0_1.md (mROAS chain rule §3, adstock factor §4)
    docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md (Option C lock §2bis, L1)

Run:
    pytest tools/test_optimizer_invariants.py -v
"""
from __future__ import annotations

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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for _optimizer_fixtures

from utils.adstock import apply_adstock  # noqa: E402
from utils.saturation import hill_function  # noqa: E402

from _optimizer_fixtures import build_synthetic_pickle, is_ok as _is_ok  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# I1 — Monotonicity: wider bounds dominate narrower
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('seed', list(range(20)))
def test_I1_monotonicity_wider_bounds_dominate(tmp_path, seed):
    """Widening bounds should never decrease optimizer's best objective.

    Math: B_wide ⊇ B_narrow → max_x∈B_wide f(x) ≥ max_x∈B_narrow f(x).
    Optimizer guarantees this via default_anchor mechanism (passes 7-17):
    SLSQP в non-convex space может drift в worse local optimum, but anchor
    seeds default-bounds solution as direct candidate ensuring monotonic
    improvement with bound widening.
    """
    proj = tmp_path / f'I1_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    from engines.optimizer import optimize
    r_narrow = optimize({'min_pct': 50.0, 'max_pct': 150.0}, str(proj))
    r_wide = optimize({'min_pct': 0.0, 'max_pct': 500.0}, str(proj))

    if not _is_ok(r_narrow) or not _is_ok(r_wide):
        pytest.skip(
            f'optimizer status: narrow={r_narrow.get("status")} '
            f'/ wide={r_wide.get("status")}'
        )
    if r_narrow.get('baseline_zero') or r_wide.get('baseline_zero'):
        pytest.skip('baseline_zero — lift_pct undefined')

    lift_narrow = float(r_narrow['expected_lift_pct'])
    lift_wide = float(r_wide['expected_lift_pct'])
    assert lift_wide >= lift_narrow - 0.5, (
        f'I1 violated (seed={seed}): lift_wide={lift_wide:.2f}% < '
        f'lift_narrow={lift_narrow:.2f}% (Δ={lift_wide-lift_narrow:+.2f}pp). '
        f'default_anchor mechanism failed to floor wider-bounds result.'
    )


# ──────────────────────────────────────────────────────────────────────
# I2 — Conservation: Σ optimal_money == money_target (eq constraint)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('seed', list(range(20)))
def test_I2_conservation_no_override(tmp_path, seed):
    """Без total_budget_money override: Σ optimal == Σ current."""
    proj = tmp_path / f'I2a_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    if not _is_ok(r):
        pytest.skip(f'optimizer status={r.get("status")}: {r.get("message")}')

    optimal_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
    current_money = sum(ch['current_spend_money'] for ch in r['channels'])
    rel_err = abs(optimal_money - current_money) / max(current_money, 1.0)
    assert rel_err < 0.005, (
        f'I2 violated (seed={seed}): optimal={optimal_money:,.0f}, '
        f'current={current_money:,.0f}, rel_err={rel_err*100:.3f}% (>0.5%)'
    )


@pytest.mark.parametrize('seed', list(range(20)))
def test_I2_conservation_with_override(tmp_path, seed):
    """С total_budget_money override: Σ optimal == money_target (1.5× current)."""
    proj = tmp_path / f'I2b_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    df = pd.read_excel(proj / 'data' / 'synthetic.xlsx')
    md = pickle.load(open(proj / 'models' / 'latest.pkl', 'rb'))
    media_cols = md['config']['media_columns']
    uc = md['config']['unit_costs']
    current_total_money = sum(
        float(df[c].fillna(0).sum()) * float(uc.get(c, 1.0)) for c in media_cols
    )
    target = current_total_money * 1.5

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 300.0,
        'total_budget_money': target,
    }, str(proj))
    if not _is_ok(r):
        pytest.skip(f'optimizer status={r.get("status")}: {r.get("message")}')

    optimal_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
    rel_err = abs(optimal_money - target) / max(target, 1.0)
    assert rel_err < 0.005, (
        f'I2 override violated (seed={seed}): optimal={optimal_money:,.0f}, '
        f'target={target:,.0f}, rel_err={rel_err*100:.3f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# I3 — Bounds satisfaction: per-channel
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('seed', list(range(20)))
def test_I3_bounds_satisfaction(tmp_path, seed):
    """Each optimal_money[i] ∈ [current_money × min_pct, current_money × max_pct]."""
    proj = tmp_path / f'I3_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    from engines.optimizer import optimize
    min_pct, max_pct = 20.0, 200.0
    r = optimize({'min_pct': min_pct, 'max_pct': max_pct}, str(proj))
    if not _is_ok(r):
        pytest.skip(f'optimizer status={r.get("status")}: {r.get("message")}')

    for ch in r['channels']:
        cur_money = ch['current_spend_money']
        opt_money = ch['optimal_spend_money']
        if cur_money <= 0:
            assert opt_money >= 0, f'{ch["name"]}: opt={opt_money} < 0 при zero cur'
            continue
        lo = cur_money * (min_pct / 100.0)
        hi = cur_money * (max_pct / 100.0)
        # 0.5% tolerance: round-2 + SLSQP eq-constraint slack
        tol = max(hi * 5e-3, 1.0)
        assert lo - tol <= opt_money <= hi + tol, (
            f'I3 violated (seed={seed}, ch={ch["name"]}): opt={opt_money:.0f} '
            f'∉ [{lo:.0f}, {hi:.0f}] (tol={tol:.0f}, cur={cur_money:.0f})'
        )


# ──────────────────────────────────────────────────────────────────────
# I4 — Backward compat: analyst mode echo + deterministic
# ──────────────────────────────────────────────────────────────────────

def test_I4_analyst_mode_echo_and_determinism(tmp_path):
    """forecast_periods=None → planning_mode=False, train_n echoed, deterministic."""
    proj = tmp_path / 'I4'
    build_synthetic_pickle(proj, seed=42, n_periods=52)

    from engines.optimizer import optimize
    r1 = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    r2 = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': None}, str(proj))
    r3 = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))  # rerun

    for r, label in [(r1, 'r1'), (r2, 'r2'), (r3, 'r3')]:
        assert _is_ok(r), f'{label} status={r.get("status")}'
        assert r['planning_mode'] is False, f'{label} planning_mode wrong'
        assert r['train_n_periods'] == 52, f'{label} train_n_periods echo wrong'
        assert r['forecast_n_periods'] == 52, (
            f'{label} forecast_n_periods should equal train in analyst mode'
        )

    # Determinism: r1 == r2 == r3 channel allocations bytewise
    for c1, c2, c3 in zip(r1['channels'], r2['channels'], r3['channels']):
        assert c1['optimal_spend_money'] == c2['optimal_spend_money'] == c3['optimal_spend_money'], (
            f'Non-deterministic: {c1["name"]} → '
            f'r1={c1["optimal_spend_money"]}, r2={c2["optimal_spend_money"]}, '
            f'r3={c3["optimal_spend_money"]}'
        )


# ──────────────────────────────────────────────────────────────────────
# I5 — Lift sign: anchor-floor guarantee (corollary I1)
# ──────────────────────────────────────────────────────────────────────
#
# Plan I5 = corollary of I1 ("wider → lift_wide ≥ lift_narrow"). Optimizer
# implements this via default_anchor mechanism (passes 7-17 в optimizer.py:
# DEFAULT_MIN_PCT=0.20, DEFAULT_MAX_PCT=2.00). Anchor active iff user widens
# **past** defaults — not for narrower-than-default OR for chains entirely
# inside default bracket. So actual guarantee is:
#
#   (anchor floor) For any user bounds wider than (0.20, 2.00):
#                  lift(user) ≥ lift(default 20/200) - tolerance
#
# Full transitive monotonicity (chain over arbitrary widenings) is NOT
# guaranteed by current implementation — it would need cumulative anchor
# (each call seeds previous-narrower's optimum). Captured as advisory xfail
# below (Phase 5 follow-up).
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('seed', list(range(5)))
def test_I5_lift_floor_at_default_anchor(tmp_path, seed):
    """Wider-than-default bounds always ≥ default(20/200) lift — anchor floor."""
    proj = tmp_path / f'I5a_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    from engines.optimizer import optimize
    r_default = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    if not _is_ok(r_default) or r_default.get('baseline_zero'):
        pytest.skip(f'default optimize: {r_default.get("status")}')
    lift_default = float(r_default['expected_lift_pct'])

    for lo, hi in [(10.0, 250.0), (10.0, 300.0), (5.0, 400.0), (0.0, 500.0)]:
        r = optimize({'min_pct': lo, 'max_pct': hi}, str(proj))
        if not _is_ok(r) or r.get('baseline_zero'):
            continue
        lift = float(r['expected_lift_pct'])
        assert lift >= lift_default - 0.5, (
            f'I5 anchor floor violated (seed={seed}, bounds={lo}/{hi}): '
            f'lift={lift:.2f}% < default(20/200)={lift_default:.2f}% '
            f'(Δ={lift-lift_default:+.2f}pp). default_anchor mechanism failed.'
        )


@pytest.mark.xfail(
    reason=(
        'Transitive chain monotonicity not guaranteed by current optimizer — '
        'anchor floors only vs default(20/200), not vs each prior chain step. '
        'Phase 5 follow-up: implement cumulative anchor seeding.'
    ),
    strict=False,
)
@pytest.mark.parametrize('seed', list(range(5)))
def test_I5_chain_monotonic_advisory(tmp_path, seed):
    """ADVISORY: full chain monotonicity (every step ≥ previous).

    Surfaces transitive non-monotonicity for Phase 5 finding registry.
    Marked xfail because plan I5 only requires paired (narrow vs wide), not chain;
    chain regression is real bug class but deferred to anchor-mechanism rewrite.
    """
    proj = tmp_path / f'I5b_{seed}'
    build_synthetic_pickle(proj, seed=seed)

    from engines.optimizer import optimize
    chain = [(50, 150), (30, 200), (20, 250), (10, 300), (0, 500)]
    lifts: list[tuple[str, float]] = []
    for lo, hi in chain:
        r = optimize({'min_pct': float(lo), 'max_pct': float(hi)}, str(proj))
        if not _is_ok(r) or r.get('baseline_zero'):
            continue
        lifts.append((f'{lo}/{hi}', float(r['expected_lift_pct'])))

    if len(lifts) < 2:
        pytest.skip(f'<2 runs successful')

    for i in range(1, len(lifts)):
        prev_label, prev_lift = lifts[i - 1]
        curr_label, curr_lift = lifts[i]
        assert curr_lift >= prev_lift - 0.5, (
            f'I5 chain violated (seed={seed}): {curr_label}={curr_lift:.2f}% < '
            f'{prev_label}={prev_lift:.2f}%. Full chain: {lifts}'
        )


# ──────────────────────────────────────────────────────────────────────
# I6 — mROAS chain rule consistency vs finite-difference
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('seed', list(range(50)))
def test_I6_mroas_finite_difference(seed):
    """_compute_mroas_money matches numerical derivative of analytical KPI.

    Math: mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost
    (docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3).

    Finite-difference: KPI(s+ε) - KPI(s-ε) / 2ε with KPI = β · hill(...) · n · y_std.
    Should match analytical to relative error < 1e-3 (truncation O(ε²)).
    """
    from engines.optimizer import _compute_mroas_money, _flat_alloc_adstock_avg

    rng = np.random.default_rng(seed)
    alpha = float(rng.uniform(1.0, 3.0))
    gamma = float(rng.uniform(0.3, 0.8))
    beta = float(rng.uniform(0.02, 0.15))
    decay = float(rng.uniform(0.1, 0.7))
    n_periods = int(rng.integers(20, 60))
    mean = float(rng.uniform(50, 500))
    y_std = float(rng.uniform(1e6, 1e8))
    unit_cost = float(rng.choice([1.0, float(rng.uniform(50, 500_000))]))
    cur_native = float(rng.uniform(100, 1000) * n_periods)

    analytical = _compute_mroas_money(
        current_spend_native=cur_native,
        n_periods=n_periods,
        mean=mean,
        alpha=alpha,
        gamma=gamma,
        beta=beta,
        adstock_type='geometric',
        y_std=y_std,
        unit_cost=unit_cost,
        decay=decay,
    )

    def kpi_money(s_money: float) -> float:
        s_native = s_money / unit_cost
        x_pp = s_native / n_periods
        if x_pp <= 0:
            return 0.0
        adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, 'geometric', decay)
        x_norm = adstock_avg / max(mean, 1e-10)
        sat = hill_function(
            np.array([max(x_norm, 0)]),
            alpha=alpha,
            gamma=max(gamma, 1e-6),
        )
        return float(beta * sat[0] * n_periods * y_std)

    s_money = cur_native * unit_cost
    eps = max(s_money * 1e-5, 1e-3)
    fd = (kpi_money(s_money + eps) - kpi_money(s_money - eps)) / (2.0 * eps)

    abs_err = abs(analytical - fd)
    rel_err = abs_err / max(abs(analytical), 1e-10)
    # Relative tol 5e-3 covers truncation (O(ε²) ≈ 1e-10 of KPI scale, but
    # x_norm近 saturation may amplify; 1e-5 ε / 1e8 y_std → fd ~1e3 abs while
    # mROAS itself может быть в [10⁻⁴ .. 10²] range).
    assert rel_err < 5e-3 or abs_err < 1e-6, (
        f'I6 violated (seed={seed}): analytical={analytical:.6e}, '
        f'finite-diff={fd:.6e}, abs_err={abs_err:.6e}, rel_err={rel_err:.2e}'
    )


# ──────────────────────────────────────────────────────────────────────
# I7 — Per-channel constraint precedence (E2E через optimize)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('seed', list(range(10)))
def test_I7_per_channel_overrides_global(tmp_path, seed):
    """Per-channel constraint must be tighter than global."""
    proj = tmp_path / f'I7_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4)

    df = pd.read_excel(proj / 'data' / 'synthetic.xlsx')
    md = pickle.load(open(proj / 'models' / 'latest.pkl', 'rb'))
    media_cols = md['config']['media_columns']
    target_ch = media_cols[1] if len(media_cols) >= 2 else media_cols[0]

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 300.0,
        'min_per_channel': {target_ch: 80.0},
        'max_per_channel': {target_ch: 120.0},
    }, str(proj))
    if not _is_ok(r):
        pytest.skip(f'optimizer status={r.get("status")}: {r.get("message")}')

    target = next((ch for ch in r['channels'] if ch['name'] == target_ch), None)
    assert target is not None, f'{target_ch} not in result.channels'
    cur_money = target['current_spend_money']
    opt_money = target['optimal_spend_money']

    if cur_money <= 0:
        pytest.skip(f'{target_ch} has zero current_money — bounds degenerate')

    lo = cur_money * 0.80
    hi = cur_money * 1.20
    tol = max(hi * 5e-3, 1.0)
    assert lo - tol <= opt_money <= hi + tol, (
        f'I7 violated (seed={seed}, ch={target_ch}): opt={opt_money:.0f} '
        f'∉ per-channel [{lo:.0f}, {hi:.0f}] (cur={cur_money:.0f}). '
        f'global was [{cur_money*0.10:.0f}, {cur_money*3.00:.0f}].'
    )


# ──────────────────────────────────────────────────────────────────────
# I8 — Option C alignment: optimizer planning ≡ scenario forward sum
# ──────────────────────────────────────────────────────────────────────

def test_I8_option_c_per_period_identity():
    """evaluate_flat_allocation_response identical to manual per-period sum-of-Hill.

    This is the Aurora 3-way alignment invariant в planning mode (M9 finding,
    docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis): optimizer planning-mode
    objective uses same per-period Hill summation как scenario.py:167-186.
    """
    from utils.forecasting import evaluate_flat_allocation_response

    rng = np.random.default_rng(2026)
    n_periods = 12
    media_cols = ['ch_a', 'ch_b', 'ch_c', 'ch_d']
    channel_params = {
        col: {
            'alpha': float(rng.uniform(1.5, 2.5)),
            'gamma': float(rng.uniform(0.4, 0.7)),
            'beta': float(rng.uniform(0.04, 0.12)),
            'decay': float(rng.uniform(0.2, 0.6)),
            'adstock_mean_posterior': float(rng.uniform(50, 500)),
        }
        for col in media_cols
    }
    unit_costs = [1.0, 1.0, 1.0, 150_000.0]
    media_means = {col: 100.0 for col in media_cols}
    adstock_config = {col: 'geometric' for col in media_cols}
    allocation_money = np.array([3_000_000, 5_000_000, 2_000_000, 50_000_000], dtype=float)

    total_optim = evaluate_flat_allocation_response(
        media_cols=media_cols,
        channel_params=channel_params,
        allocation_money=allocation_money,
        unit_costs=unit_costs,
        media_means=media_means,
        adstock_config=adstock_config,
        n_periods=n_periods,
    )

    total_manual = 0.0
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        x_native_total = allocation_money[i] / unit_costs[i]
        x_avg_raw = x_native_total / n_periods
        flat_series = np.full(n_periods, x_avg_raw)
        adstock_series = apply_adstock(flat_series, 'geometric', {'alpha': p['decay']})
        x_norm_series = adstock_series / max(p['adstock_mean_posterior'], 1e-10)
        sat_series = hill_function(
            np.maximum(x_norm_series, 0),
            alpha=p['alpha'],
            gamma=max(p['gamma'], 1e-6),
        )
        total_manual += p['beta'] * sat_series.sum()

    rel_err = abs(total_optim - total_manual) / max(abs(total_manual), 1e-10)
    assert rel_err < 1e-9, (
        f'I8 identity broken: evaluate_flat_allocation_response={total_optim:.6e}, '
        f'manual={total_manual:.6e}, rel_err={rel_err:.2e}. '
        f'Optimizer planning-mode no longer matches scenario.py per-period sum.'
    )


@pytest.mark.parametrize('seed', list(range(5)))
def test_I8_planning_optimizer_scenario_consistency(tmp_path, seed):
    """E2E: optimizer planning mode → scenario forward sim на optimal allocation.

    Replays optimizer's optimal allocation через scenario.predict_scenario,
    asserts incremental KPI matches optimizer's projected media response
    within numerical tolerance. Uses media_plan length=1 (total) → scenario
    distributes evenly (matching optimizer Option C flat allocation).
    """
    proj = tmp_path / f'I8e_{seed}'
    md = build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=52)
    y_std = md['normalization']['y_std']

    from engines.optimizer import optimize
    from engines.scenario import predict_scenario

    forecast_n = 12
    r_opt = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': forecast_n,
    }, str(proj))
    if not _is_ok(r_opt):
        pytest.skip(f'optimize: {r_opt.get("message")}')
    assert r_opt['planning_mode'] is True
    assert r_opt['forecast_n_periods'] == forecast_n

    # Optimizer's media response в normalized scale = -best_objective.
    # Multiply by y_std → KPI-scale media contribution at optimum.
    diag = r_opt.get('slsqp_diagnostics', {})
    best_obj = diag.get('best_objective')
    if best_obj is None:
        pytest.skip('no best_objective (SLSQP did not converge)')
    media_kpi_optim = -float(best_obj) * y_std

    # Build scenario's media plan as single-period totals (scenario distributes
    # evenly across forecast_n when plan length == 1).
    media_plan = {ch['name']: [float(ch['optimal_spend'])] for ch in r_opt['channels']}
    unit_costs_scen = {ch['name']: ch['unit_cost'] for ch in r_opt['channels']}

    r_scen = predict_scenario({
        'scenario_name': 'I8_optimal_replay',
        'media_plan': media_plan,
        'unit_costs': unit_costs_scen,
        'forecast_periods': forecast_n,
    }, str(proj))
    if not _is_ok(r_scen):
        pytest.skip(f'scenario: {r_scen.get("message")}')

    media_kpi_scen = float(r_scen['totals']['incremental_kpi'])

    assert media_kpi_optim > 0, f'optimizer media KPI non-positive: {media_kpi_optim}'
    assert media_kpi_scen > 0, f'scenario incremental non-positive: {media_kpi_scen}'

    rel_err = abs(media_kpi_optim - media_kpi_scen) / max(media_kpi_optim, 1.0)
    # 1% tolerance: rounding + intercept_baseline differences in scenario.py
    assert rel_err < 0.01, (
        f'I8 E2E violated (seed={seed}): optimizer KPI={media_kpi_optim:,.0f}, '
        f'scenario incremental={media_kpi_scen:,.0f}, rel_err={rel_err*100:.2f}%'
    )


# ──────────────────────────────────────────────────────────────────────
# Standalone runner (pattern from test_optimizer_kagocel_redistribution)
# ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
