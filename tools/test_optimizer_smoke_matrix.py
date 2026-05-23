"""Optimizer end-to-end smoke matrix - Phase 4 of audit.

Plan: C:\\Users\\ackol\\.claude\\plans\\zazzy-tumbling-kettle.md, Phase 4.

Twelve representative configurations (C1-C12) covering production combinations:

| ID  | Mode    | KPI       | Units | Inflation | Per-channel             | Forecast | Source         |
|-----|---------|-----------|-------|-----------|-------------------------|----------|----------------|
| C1  | analyst | sales     | money | None      | None                    | None     | synthetic      |
| C2  | analyst | sales     | mixed | None      | partial                 | None     | synthetic      |
| C3  | analyst | sales     | mixed | 25%/yr    | None                    | None     | synthetic 2yr  |
| C4  | planner | sales     | mixed | None      | None                    | 12       | synthetic      |
| C5  | planner | sales     | mixed | 25%/yr    | partial 4ch             | 12       | Kagocel-shape  |
| C6  | planner | sales     | mixed | None      | per-group brand+perf    | 12       | hierarchical   |
| C7  | planner | sales     | mixed | 25%/yr    | per-group               | 26       | hierarchical 2yr |
| C8  | analyst | awareness | money | None      | None                    | None     | synthetic      |
| C9  | planner | awareness | money | None      | None                    | 8        | synthetic      |
| C10 | planner | sales     | mixed | 25%/yr    | per-channel + per-group | 12       | hierarchical 2yr |
| C11 | planner | sales     | money | None      | infeasible-narrow       | 12       | edge case      |
| C12 | What-if | sales     | mixed | 25%/yr    | partial                 | 12       | Kagocel + 0.5× |

Each config asserts:
1. status='ok' OR explicit error_code
2. lift > -10% (no catastrophic regression)
3. bounds satisfied (optimal_money ≥ 0, finite)
4. result dict has all expected schema keys
5. mROAS values consistent с decompose ROI (sample C5 cross-check)
6. C5 + C12: scenario save round-trip (sanity workflow)

Run:
    pytest tools/test_optimizer_smoke_matrix.py -v
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _optimizer_fixtures import (  # noqa: E402
    build_kagocel_shape,
    build_multi_year_pickle,
    build_synthetic_pickle,
    current_total_money,
    promote_to_hierarchical,
)


REQUIRED_KEYS_OK = (
    'status', 'expected_lift_pct', 'channels', 'response_curves',
    'planning_mode', 'train_n_periods', 'forecast_n_periods',
    'optimization_converged', 'binding_constraints',
    'total_budget_money', 'total_current_money',
    'min_pct_used', 'max_pct_used',
    'slsqp_diagnostics',
)


def _validate_smoke_ok(r: dict, label: str) -> None:
    """Generic acceptance checks for status='ok' configs."""
    assert r.get('status') == 'ok', (
        f'{label}: expected ok, got {r.get("status")} / {r.get("error_code")} / {r.get("message")}'
    )
    for key in REQUIRED_KEYS_OK:
        assert key in r, f'{label}: missing required key `{key}`'
    if not r.get('baseline_zero'):
        lift = float(r['expected_lift_pct'])
        assert lift > -10.0, f'{label}: catastrophic lift={lift:.1f}%'
    for ch in r['channels']:
        assert ch['optimal_spend_money'] >= 0, (
            f'{label}: negative optimal {ch["name"]}={ch["optimal_spend_money"]}'
        )
        assert math.isfinite(ch['optimal_spend_money']), (
            f'{label}: non-finite optimal_spend_money {ch["name"]}'
        )
        assert math.isfinite(ch.get('mroi_current', 0)), (
            f'{label}: non-finite mroi_current {ch["name"]}'
        )
        assert math.isfinite(ch.get('mroi_optimal', 0)), (
            f'{label}: non-finite mroi_optimal {ch["name"]}'
        )
        # Channel schema sanity
        for k in ('name', 'current_spend', 'optimal_spend',
                  'current_spend_money', 'optimal_spend_money',
                  'unit_cost', 'delta_pct', 'mroi_current', 'mroi_optimal',
                  'action', 'action_label'):
            assert k in ch, f'{label}: channel `{ch.get("name")}` missing `{k}`'


def _validate_smoke_error(r: dict, label: str, expected_codes: set[str]) -> None:
    """Acceptance for explicit-error configs."""
    assert r.get('status') == 'error', f'{label}: expected error, got {r.get("status")}'
    assert r.get('error_code') in expected_codes, (
        f'{label}: error_code={r.get("error_code")!r} not in {expected_codes}'
    )


# ══════════════════════════════════════════════════════════════════════
# C1 - analyst / sales / money / no extras
# ══════════════════════════════════════════════════════════════════════

def test_C1_analyst_sales_money_baseline(tmp_path):
    proj = tmp_path / 'C1'
    build_synthetic_pickle(proj, seed=101, n_channels=4, mixed_units=False)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    _validate_smoke_ok(r, 'C1')
    assert r['planning_mode'] is False


# ══════════════════════════════════════════════════════════════════════
# C2 - analyst / sales / mixed units / partial per-channel
# ══════════════════════════════════════════════════════════════════════

def test_C2_analyst_sales_mixed_partial_perch(tmp_path):
    proj = tmp_path / 'C2'
    md = build_synthetic_pickle(proj, seed=102, n_channels=6, mixed_units=True)
    cols = md['config']['media_columns']

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'min_per_channel': {cols[1]: 50.0},
        'max_per_channel': {cols[2]: 180.0},
    }, str(proj))
    _validate_smoke_ok(r, 'C2')


# ══════════════════════════════════════════════════════════════════════
# C3 - analyst / sales / mixed / 25% inflation
# ══════════════════════════════════════════════════════════════════════

def test_C3_analyst_sales_with_inflation(tmp_path):
    proj = tmp_path / 'C3'
    md = build_multi_year_pickle(proj, seed=103, n_channels=4)
    cols = md['config']['media_columns']

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {c: 25.0 for c in cols},
    }, str(proj))
    _validate_smoke_ok(r, 'C3')
    # TRPs unit_cost reflects 2-year weighted avg < 150_000
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert trps is not None
    assert trps['unit_cost'] < 150_000.0, 'C3: inflation should reduce TRPs effective cost'


# ══════════════════════════════════════════════════════════════════════
# C4 - planner / sales / mixed / forecast=12
# ══════════════════════════════════════════════════════════════════════

def test_C4_planner_sales_forecast_12(tmp_path):
    proj = tmp_path / 'C4'
    build_synthetic_pickle(proj, seed=104, n_channels=4, n_periods=52, mixed_units=True)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': 12,
    }, str(proj))
    _validate_smoke_ok(r, 'C4')
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 12
    assert r['train_n_periods'] == 52


# ══════════════════════════════════════════════════════════════════════
# C5 - planner / Kagocel-shape / 25% inflation / partial 4ch / forecast=12
# Includes mROAS↔decompose alignment cross-check + scenario round-trip
# ══════════════════════════════════════════════════════════════════════

def test_C5_planner_kagocel_inflation_perch_forecast(tmp_path):
    proj = tmp_path / 'C5'
    md = build_kagocel_shape(proj, seed=2026)
    cols = md['config']['media_columns']

    from engines.optimizer import optimize
    from engines.decomposer import decompose

    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {'tv_trps_brand': 25.0},
        'min_per_channel': {cols[0]: 50.0, cols[2]: 80.0},
        'max_per_channel': {cols[1]: 180.0, cols[4]: 150.0},
        'forecast_periods': 12,
    }, str(proj))
    _validate_smoke_ok(r, 'C5')
    assert r['planning_mode'] is True

    # Cross-check: decompose produces compatible mroi_current
    dec = decompose(str(proj))
    assert dec.get('status') == 'ok', f'C5 decompose: {dec.get("error_code")}'
    opt_mroi = {ch['name']: float(ch.get('mroi_current') or 0) for ch in r['channels']}
    dec_mroi = {ch['name']: float(ch.get('mroi_current') or 0) for ch in dec['channels']}
    common = set(opt_mroi) & set(dec_mroi)
    assert common, 'C5: no common channels between optimize и decompose'
    # Both engines call _compute_mroas_money с current_spend; analyst-mode optimize
    # uses train_n, planning-mode uses forecast_n → mROAS scales differ. Decomposer
    # always uses train_n. Sanity check: both signs consistent (same channel doesn't
    # show pos в decompose + neg в optimize).
    for name in common:
        assert (opt_mroi[name] >= 0) == (dec_mroi[name] >= 0), (
            f'C5: {name} mROAS sign mismatch - opt={opt_mroi[name]:.4f} '
            f'dec={dec_mroi[name]:.4f}'
        )


# ══════════════════════════════════════════════════════════════════════
# C6 - planner / hierarchical / per-group brand+perf / forecast=12
# ══════════════════════════════════════════════════════════════════════

def test_C6_planner_hierarchical_per_group(tmp_path):
    proj = tmp_path / 'C6'
    build_synthetic_pickle(proj, seed=106, n_channels=6, n_periods=52, mixed_units=True)
    promote_to_hierarchical(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'brand_min_pct': 50.0, 'brand_max_pct': 150.0,
        'perf_min_pct': 60.0, 'perf_max_pct': 180.0,
        'forecast_periods': 12,
    }, str(proj))
    _validate_smoke_ok(r, 'C6')
    assert r['planning_mode'] is True


# ══════════════════════════════════════════════════════════════════════
# C7 - planner / hierarchical 2-yr / inflation / per-group / forecast=26
# ══════════════════════════════════════════════════════════════════════

def test_C7_planner_hierarchical_inflation_pergroup_26(tmp_path):
    proj = tmp_path / 'C7'
    md = build_multi_year_pickle(proj, seed=107, n_channels=6)
    cols = md['config']['media_columns']
    promote_to_hierarchical(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'brand_min_pct': 50.0, 'brand_max_pct': 150.0,
        'perf_min_pct': 60.0, 'perf_max_pct': 180.0,
        'unit_cost_inflation_pct': {c: 25.0 for c in cols},
        'forecast_periods': 26,
    }, str(proj))
    _validate_smoke_ok(r, 'C7')
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 26


# ══════════════════════════════════════════════════════════════════════
# C8 - analyst / awareness / money
# ══════════════════════════════════════════════════════════════════════

def test_C8_analyst_awareness_money(tmp_path):
    proj = tmp_path / 'C8'
    build_synthetic_pickle(
        proj, seed=108, n_channels=3,
        mixed_units=False, awareness=True,
    )

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    _validate_smoke_ok(r, 'C8')
    assert r['planning_mode'] is False


# ══════════════════════════════════════════════════════════════════════
# C9 - planner / awareness / forecast=8
# ══════════════════════════════════════════════════════════════════════

def test_C9_planner_awareness_forecast_8(tmp_path):
    proj = tmp_path / 'C9'
    build_synthetic_pickle(
        proj, seed=109, n_channels=3, n_periods=26,
        mixed_units=False, awareness=True,
    )

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': 8,
    }, str(proj))
    _validate_smoke_ok(r, 'C9')
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 8


# ══════════════════════════════════════════════════════════════════════
# C10 - planner / hierarchical 2-yr / inflation / per-channel + per-group / forecast=12
# Hardest production combo - every feature exercised
# ══════════════════════════════════════════════════════════════════════

def test_C10_planner_all_features_combined(tmp_path):
    proj = tmp_path / 'C10'
    md = build_multi_year_pickle(proj, seed=110, n_channels=6)
    cols = md['config']['media_columns']
    promote_to_hierarchical(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 250.0,
        'brand_min_pct': 50.0, 'brand_max_pct': 200.0,
        'perf_min_pct': 60.0, 'perf_max_pct': 180.0,
        'min_per_channel': {cols[1]: 70.0},  # tighter than brand_min
        'max_per_channel': {cols[4]: 140.0},  # tighter than perf_max
        'unit_cost_inflation_pct': {cols[0]: 25.0, cols[3]: 15.0},
        'forecast_periods': 12,
    }, str(proj))
    _validate_smoke_ok(r, 'C10')
    assert r['planning_mode'] is True


# ══════════════════════════════════════════════════════════════════════
# C11 - infeasible-narrow per-channel (sum_lo > target) → INFEASIBLE
# ══════════════════════════════════════════════════════════════════════

def test_C11_infeasible_narrow_per_channel(tmp_path):
    proj = tmp_path / 'C11'
    md = build_synthetic_pickle(
        proj, seed=111, n_channels=4, n_periods=52,
        mixed_units=False,
    )
    cols = md['config']['media_columns']
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    # All per-channel min=200% → sum_min = 2× current. Total target = 1× current.
    # Should reject INFEASIBLE_BUDGET_LOW (target < sum_min).
    r = optimize({
        'min_pct': 20.0, 'max_pct': 300.0,
        'min_per_channel': {c: 200.0 for c in cols},
        'max_per_channel': {c: 250.0 for c in cols},
        'total_budget_money': cur,
        'forecast_periods': 12,
    }, str(proj))
    _validate_smoke_error(r, 'C11', {'INFEASIBLE_BUDGET_LOW'})


# ══════════════════════════════════════════════════════════════════════
# C12 - What-if 0.5× / Kagocel / inflation / partial / forecast=12 (pass-18)
# Direct regression lock-in для pass-18 UnboundLocalError trigger
# ══════════════════════════════════════════════════════════════════════

def test_C12_whatif_kagocel_pass18_regression(tmp_path):
    proj = tmp_path / 'C12'
    md = build_kagocel_shape(proj, seed=2027)
    cols = md['config']['media_columns']
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    config = {
        'min_pct': 0.0, 'max_pct': 500.0,  # widening (anchor active)
        'min_per_channel': {cols[0]: 30.0, cols[2]: 40.0},
        'max_per_channel': {cols[1]: 250.0, cols[4]: 200.0},
        'unit_cost_inflation_pct': {'tv_trps_brand': 25.0},
        'total_budget_money': cur * 0.5,  # whatIfMult = 0.5 - pass-18 trigger
        'forecast_periods': 12,
    }
    try:
        r = optimize(config, str(proj))
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'C12 pass-18 regression: {type(e).__name__}: {e}')

    # Must return well-formed dict с status. Either ok OR explicit error_code.
    assert 'status' in r
    if r.get('status') == 'ok':
        _validate_smoke_ok(r, 'C12')
        assert r['planning_mode'] is True
        # Conservation of 0.5× target
        opt_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
        target = cur * 0.5
        assert abs(opt_money - target) / target < 0.01, (
            f'C12: conservation violated, opt={opt_money:,.0f}, target={target:,.0f}'
        )
    else:
        assert r.get('error_code'), f'C12: error без error_code: {r}'


# ══════════════════════════════════════════════════════════════════════
# C5 + C12 scenario round-trip - sanity workflow check (plan §6)
# ══════════════════════════════════════════════════════════════════════

def test_C5_scenario_save_round_trip(tmp_path):
    """C5 sanity: optimal allocation replays через scenario.predict_scenario."""
    proj = tmp_path / 'C5_round'
    build_kagocel_shape(proj, seed=2028)

    from engines.optimizer import optimize
    from engines.scenario import predict_scenario, compare_scenarios

    r_opt = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': 12,
    }, str(proj))
    assert r_opt.get('status') == 'ok'

    media_plan = {ch['name']: [float(ch['optimal_spend'])] for ch in r_opt['channels']}
    unit_costs = {ch['name']: ch['unit_cost'] for ch in r_opt['channels']}

    r_scen = predict_scenario({
        'scenario_name': 'C5_optimal_round_trip',
        'media_plan': media_plan,
        'unit_costs': unit_costs,
        'forecast_periods': 12,
    }, str(proj))
    assert r_scen.get('status') == 'ok', f'scenario: {r_scen.get("error_code")}: {r_scen.get("message")}'

    # compare_scenarios должен загрузить сохранённый scenario
    cmp = compare_scenarios(str(proj), unit_costs=unit_costs)
    assert cmp.get('status') == 'ok'
    assert 'C5_optimal_round_trip' in {s['scenario_name'] for s in cmp['scenarios']}


# ══════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
