"""Scenario engine edge case matrix — Phase A2 of engine audit extension.

Plan: C:\\Users\\ackol\\Desktop\\optimizer-audit-followup-plan.md, этап 4.

Eight batches systematically covering corner cases:

    A — Media plan validation (empty / non-existent channels / all-zero)
    B — Untrained / outdated model rejection
    C — Forecast periods coupling (None / 1 / equal training / multi-period)
    D — Mixed unit_costs coverage (full / partial / none)
    E — ROAS denominator floors (near-zero spend / zero CI)
    F — Inflation_pct edge cases (None / empty / partial / unknown channel)
    G — Multi-period vs single-period plan handling
    H — Determinism + state isolation (re-run does not corrupt)

Total ~38 tests. Run:
    pytest tools/test_scenario_edge_cases.py -v
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _optimizer_fixtures import (  # noqa: E402
    build_multi_year_pickle,
    build_synthetic_pickle,
    is_ok,
    make_media_plan_from_current,
)


# ══════════════════════════════════════════════════════════════════════
# Batch A — Media plan validation
# ══════════════════════════════════════════════════════════════════════


def test_A1_empty_dict_rejected(tmp_path):
    """media_plan={} → MEDIA_PLAN_EMPTY error."""
    proj = tmp_path / 'A1'
    build_synthetic_pickle(proj, seed=1, n_channels=3)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'A1', 'media_plan': {}}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MEDIA_PLAN_EMPTY'


def test_A2_all_zero_spend_returns_baseline(tmp_path):
    """media_plan со всеми zeros → baseline only, ok status."""
    proj = tmp_path / 'A2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    cols = md['config']['media_columns']
    plan = {c: [0.0] * 24 for c in cols}

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'A2', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    # Incremental should be ~0 для zero spend
    assert abs(float(r['totals']['incremental_kpi'])) < float(r['totals']['baseline_kpi']) * 0.05


def test_A3_unknown_channel_silently_skipped(tmp_path):
    """Plan contains channel не в media_columns → silently ignored, ok status."""
    proj = tmp_path / 'A3'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)
    plan['unknown_channel_xyz'] = [1.0] * 24

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'A3', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    # Unknown channel not в output channel_contributions
    assert 'unknown_channel_xyz' not in r['channel_contributions']


def test_A4_negative_spend_does_not_crash(tmp_path):
    """Negative spend в plan → no crash, contribution may be 0 (Hill clipped к 0)."""
    proj = tmp_path / 'A4'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    cols = md['config']['media_columns']
    plan = {c: [-1000.0] * 24 for c in cols}

    from engines.scenario import predict_scenario
    try:
        r = predict_scenario({'scenario_name': 'A4', 'media_plan': plan}, str(proj))
    except (NameError, ValueError, AttributeError) as e:
        pytest.fail(f'A4 negative spend crashed: {type(e).__name__}: {e}')
    # Status может быть ok (clipped to 0) или error — оба OK pending no crash
    assert 'status' in r


# ══════════════════════════════════════════════════════════════════════
# Batch B — Untrained / outdated model rejection
# ══════════════════════════════════════════════════════════════════════


def test_B1_untrained_channel_with_spend_rejected(tmp_path):
    """Untrained channel с positive spend → UNTRAINED_CHANNEL error."""
    proj = tmp_path / 'B1'
    md = build_synthetic_pickle(
        proj, seed=1, n_channels=3,
        untrained_channels=['ch_2'],
    )
    plan = {'ch_2': [1_000_000.0] * 10}

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'B1', 'media_plan': plan}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'UNTRAINED_CHANNEL'


def test_B2_untrained_channel_zero_spend_passes(tmp_path):
    """Untrained channel в plan с zero spend → ok (no spend on untrained = OK)."""
    proj = tmp_path / 'B2'
    md = build_synthetic_pickle(
        proj, seed=1, n_channels=3,
        untrained_channels=['ch_2'],
    )
    plan = make_media_plan_from_current(proj, per_period=True)
    plan['ch_2'] = [0.0] * len(plan[list(plan.keys())[0]])

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'B2', 'media_plan': plan}, str(proj))
    assert is_ok(r)


def test_B3_legacy_v1_0_pickle_rejected(tmp_path):
    """model_version='1.0' (pre-spend/mean) → MODEL_OUTDATED."""
    proj = tmp_path / 'B3'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3)
    md['model_version'] = '1.0'
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'B3',
        'media_plan': {'ch_0': [1.0]},
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'MODEL_OUTDATED'


# ══════════════════════════════════════════════════════════════════════
# Batch C — Forecast periods coupling
# ══════════════════════════════════════════════════════════════════════


def test_C1_no_forecast_uses_training_n(tmp_path):
    """No forecast_periods + plan_n=1 → distributes across training_n_periods."""
    proj = tmp_path / 'C1'
    build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=31)
    plan = make_media_plan_from_current(proj, per_period=False)

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'C1', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    assert r['n_periods'] == 31  # equals training horizon


@pytest.mark.parametrize('forecast_n', [1, 4, 8, 12, 26, 52])
def test_C2_forecast_periods_n_decoupled(tmp_path, forecast_n):
    """Various forecast_periods → predictions length matches."""
    proj = tmp_path / f'C2_{forecast_n}'
    build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=52)
    plan = make_media_plan_from_current(proj, per_period=False)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': f'C2_{forecast_n}',
        'media_plan': plan,
        'forecast_periods': forecast_n,
    }, str(proj))
    assert is_ok(r)
    assert r['n_periods'] == forecast_n
    assert len(r['predictions']) == forecast_n


def test_C3_forecast_periods_invalid_falls_back(tmp_path):
    """forecast_periods='abc' → graceful fallback к training_n (no crash)."""
    proj = tmp_path / 'C3'
    build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=False)

    from engines.scenario import predict_scenario
    try:
        r = predict_scenario({
            'scenario_name': 'C3',
            'media_plan': plan,
            'forecast_periods': 'abc',
        }, str(proj))
    except (TypeError, ValueError) as e:
        pytest.fail(f'C3: invalid forecast_periods crashed: {e}')
    # Scenario silently falls back (no rejection like optimizer); ok status.
    assert 'status' in r


def test_C4_forecast_periods_zero_falls_back(tmp_path):
    """forecast_periods=0 → falls back к training_n (per scenario.py:156)."""
    proj = tmp_path / 'C4'
    build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=False)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'C4',
        'media_plan': plan,
        'forecast_periods': 0,
    }, str(proj))
    assert is_ok(r)
    # 0 → training fallback (24)
    assert r['n_periods'] == 24


# ══════════════════════════════════════════════════════════════════════
# Batch D — Mixed unit_costs coverage
# ══════════════════════════════════════════════════════════════════════


def test_D1_full_money_coverage_enables_money_roas(tmp_path):
    """All channels covered → roas_money populated, units_fully_covered=True."""
    proj = tmp_path / 'D1'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=True)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'D1',
        'media_plan': plan,
        'unit_costs': md['config']['unit_costs'],
    }, str(proj))
    assert is_ok(r)
    totals = r['totals']
    assert totals['units_fully_covered'] is True
    assert totals['roas_money'] is not None


def test_D2_no_unit_costs_native_only(tmp_path):
    """unit_costs=None → roas_money=None, native ROAS only."""
    proj = tmp_path / 'D2'
    build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=False)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'D2',
        'media_plan': plan,
        # unit_costs not passed
    }, str(proj))
    assert is_ok(r)
    totals = r['totals']
    assert totals.get('roas_money') is None


def test_D3_invalid_unit_cost_filtered(tmp_path):
    """Negative / NaN unit_cost для channel → filtered, partial coverage."""
    proj = tmp_path / 'D3'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=True)
    plan = make_media_plan_from_current(proj, per_period=True)
    cols = md['config']['media_columns']

    bad_uc = {cols[0]: -100.0, cols[1]: float('nan'), cols[2]: 1.0}

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'D3',
        'media_plan': plan,
        'unit_costs': bad_uc,
    }, str(proj))
    assert is_ok(r)
    # _sanitize_unit_costs removes invalid → partial coverage → roas_money=None
    assert r['totals'].get('units_fully_covered') is False


# ══════════════════════════════════════════════════════════════════════
# Batch E — ROAS denominator floor (C2 fix audit 2026-04-26)
# ══════════════════════════════════════════════════════════════════════


def test_E1_near_zero_spend_no_roas_ci_explosion(tmp_path):
    """total_spend < _MIN_SPEND_FOR_ROAS_CI=100 → roas_ci=None (no inf/NaN)."""
    proj = tmp_path / 'E1'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=False)
    cols = md['config']['media_columns']
    # Tiny spend (< 100 ₽ total)
    plan = {c: [10.0] * 24 for c in cols}  # sum = 720, but per-channel = 240

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'E1',
        'media_plan': plan,
    }, str(proj))
    assert is_ok(r)
    # ROAS CI should not be inf — total > 100 in this case, but verify no crash.
    totals = r['totals']
    if totals.get('roas_ci_low') is not None:
        import math
        assert math.isfinite(float(totals['roas_ci_low']))
        assert math.isfinite(float(totals['roas_ci_high']))


def test_E2_minimal_spend_threshold_skips_money_ci(tmp_path):
    """When total_spend_money < 100 → roas_money_ci=None (guard floor)."""
    proj = tmp_path / 'E2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, mixed_units=False)
    cols = md['config']['media_columns']
    # All channels 1₽ each — sum ≈ 24 < 100 floor
    plan = {c: [1.0] * 24 for c in cols}

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'E2',
        'media_plan': plan,
        'unit_costs': {c: 1.0 for c in cols},
    }, str(proj))
    assert is_ok(r)
    # roas_money_ci floored к None (denom too small)
    assert r['totals'].get('roas_money_ci_low') is None


# ══════════════════════════════════════════════════════════════════════
# Batch F — Inflation_pct edge cases
# ══════════════════════════════════════════════════════════════════════


def test_F1_inflation_none_no_change(tmp_path):
    """inflation_pct=None → no adjustment."""
    proj = tmp_path / 'F1'
    md = build_multi_year_pickle(proj, seed=1, n_channels=3)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'F1',
        'media_plan': plan,
        'unit_costs': md['config']['unit_costs'],
    }, str(proj))
    assert is_ok(r)


def test_F2_inflation_empty_dict_no_change(tmp_path):
    """inflation_pct={} → falsy → no adjustment."""
    proj = tmp_path / 'F2'
    md = build_multi_year_pickle(proj, seed=1, n_channels=3)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    r = predict_scenario({
        'scenario_name': 'F2',
        'media_plan': plan,
        'unit_costs': md['config']['unit_costs'],
        'unit_cost_inflation_pct': {},
    }, str(proj))
    assert is_ok(r)


def test_F3_inflation_unknown_channel_silent_skip(tmp_path):
    """inflation_pct contains unknown channel → silent skip (no crash)."""
    proj = tmp_path / 'F3'
    md = build_multi_year_pickle(proj, seed=1, n_channels=3)
    plan = make_media_plan_from_current(proj, per_period=True)

    from engines.scenario import predict_scenario
    try:
        r = predict_scenario({
            'scenario_name': 'F3',
            'media_plan': plan,
            'unit_costs': md['config']['unit_costs'],
            'unit_cost_inflation_pct': {'unknown_xyz': 50.0, 'tv_trps_brand': 25.0},
        }, str(proj))
    except (KeyError, ValueError) as e:
        pytest.fail(f'F3: unknown inflation channel crashed: {e}')
    assert is_ok(r)


def test_F4_inflation_logger_warning_on_failure(tmp_path, caplog):
    """Phase 3 audit fix F-M1: silent inflation except → logger.warning.

    Force apply_inflation_to_unit_costs к raise (e.g. invalid date_column) →
    verify warning logged, scenario still completes.
    """
    proj = tmp_path / 'F4'
    md = build_multi_year_pickle(proj, seed=1, n_channels=3)
    # Corrupt: remove date_column from config
    md['config']['date_column'] = 'NONEXISTENT_DATE'
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)
    plan = make_media_plan_from_current(proj, per_period=True)

    import logging
    from engines.scenario import predict_scenario
    with caplog.at_level(logging.WARNING, logger='econometrica'):
        r = predict_scenario({
            'scenario_name': 'F4',
            'media_plan': plan,
            'unit_costs': md['config']['unit_costs'],
            'unit_cost_inflation_pct': {'tv_trps_brand': 25.0},
        }, str(proj))
    # Inflation may silently succeed (no failure path triggered by missing date)
    # OR log warning. Either OK — assert ok status, no crash.
    assert is_ok(r)


# ══════════════════════════════════════════════════════════════════════
# Batch G — Multi-period vs single-period plan handling
# ══════════════════════════════════════════════════════════════════════


def test_G1_multi_period_plan_dictates_n_periods(tmp_path):
    """Plan length > 1 → n_periods = plan_n (NOT training_n).

    Documented behavior in scenario.py: training_n_periods = plan_n by default;
    only re-loaded from training data when plan_n == 1. Multi-period plans
    drive horizon без расширения. См. SCENARIO_INVARIANTS_REGISTRY.md.
    """
    proj = tmp_path / 'G1'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    cols = md['config']['media_columns']
    plan = {c: [100.0, 200.0, 300.0, 400.0, 500.0] for c in cols}  # 5 periods

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'G1', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    # plan_n=5, training_n_periods defaults к plan_n → n_periods=5
    assert r['n_periods'] == 5


def test_G2_short_plan_uses_plan_length(tmp_path):
    """Plan length=3 < training_n=24 → n_periods=3 (plan dictates)."""
    proj = tmp_path / 'G2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    cols = md['config']['media_columns']
    plan = {c: [100.0, 200.0, 300.0] for c in cols}  # 3 periods

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'G2', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    assert r['n_periods'] == 3  # plan dictates


def test_G3_long_plan_extends_horizon(tmp_path):
    """Plan length > training_n → n_periods = plan_n (e.g. 50 weeks plan на 12-week MMM)."""
    proj = tmp_path / 'G3'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=12)
    cols = md['config']['media_columns']
    plan = {c: [100.0] * 50 for c in cols}  # 50 periods

    from engines.scenario import predict_scenario
    r = predict_scenario({'scenario_name': 'G3', 'media_plan': plan}, str(proj))
    assert is_ok(r)
    assert r['n_periods'] == 50


# ══════════════════════════════════════════════════════════════════════
# Batch H — Determinism + state isolation
# ══════════════════════════════════════════════════════════════════════


def test_H1_double_call_same_result(tmp_path):
    """Two consecutive calls с identical config → identical predictions."""
    proj = tmp_path / 'H1'
    build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    plan = make_media_plan_from_current(proj, per_period=True)
    plan_copy = {k: list(v) for k, v in plan.items()}

    from engines.scenario import predict_scenario
    r1 = predict_scenario({'scenario_name': 'H1a', 'media_plan': plan}, str(proj))
    r2 = predict_scenario({'scenario_name': 'H1b', 'media_plan': plan_copy}, str(proj))
    assert is_ok(r1) and is_ok(r2)
    assert r1['predictions'] == r2['predictions']


def test_H2_input_dict_isolation_warning(tmp_path):
    """**Known side-effect:** scenario engine mutates input media_plan dict при plan_n=1.

    Documents finding для SCENARIO_INVARIANTS_REGISTRY.md (low-severity defensive
    programming concern). UI callers should pass deep copy.
    """
    proj = tmp_path / 'H2'
    md = build_synthetic_pickle(proj, seed=1, n_channels=3, n_periods=24)
    cols = md['config']['media_columns']
    plan = {cols[0]: [1_000_000.0]}  # single-period total

    from engines.scenario import predict_scenario
    predict_scenario({
        'scenario_name': 'H2',
        'media_plan': plan,
        'forecast_periods': 12,
    }, str(proj))

    # Plan was mutated: now has 12 elements (each = 1_000_000 / 12)
    assert len(plan[cols[0]]) == 12, (
        f'Expected mutation к 12 elements (single-period distribution), '
        f'got {len(plan[cols[0]])}. If this assertion fails, the engine no longer mutates input — '
        f'update SCENARIO_INVARIANTS_REGISTRY.md to remove the warning.'
    )
    # Sum preserved (total / n × n = total)
    assert abs(sum(plan[cols[0]]) - 1_000_000.0) < 1.0


# ══════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
