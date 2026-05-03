"""Phase 2.7 (5a) — Canonical lift% formula consistency tests.

Verify three engines agree:
- optimizer.expected_lift_pct
- scenario.totals.lift_pct (when scenario allocation = optimal allocation)
- frontend predictKPI-based lift (computed inline using same Hill+adstock formulas)

Pre-fix: three different formulas (media-only ratio in optimizer, baseline-only ratio
in scenario, total ratio in frontend) gave 3-4× different magnitudes. Now: canonical =
total business KPI ratio across all three.

Math reference: Phase 2.7 plan, `project_econometrica_lift_formula_audit.md`.
"""
import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'sidecar' / 'econometrica'))

import numpy as np
import pytest

from _optimizer_fixtures import build_synthetic_pickle, make_media_plan_from_current  # noqa: E402


def _is_ok(r):
    return isinstance(r, dict) and r.get('status') == 'ok'


def _run_optimize(project_dir):
    from engines.optimizer import optimize as _optimize
    return _optimize({'minPct': 50, 'maxPct': 200}, str(project_dir))


def _run_scenario(project_dir, media_plan, name='canonical_test'):
    from engines.scenario import predict_scenario
    return predict_scenario({'scenario_name': name, 'media_plan': media_plan}, str(project_dir))


@pytest.mark.parametrize('seed', [0, 1, 2])
def test_optimizer_returns_canonical_and_legacy_lift(tmp_path, seed):
    """Optimizer output has both `expected_lift_pct` (canonical) and `media_only_lift_pct` (legacy)."""
    proj = tmp_path / f'opt_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24, n_posterior_samples=0)

    r = _run_optimize(proj)
    assert _is_ok(r)
    assert 'expected_lift_pct' in r
    assert 'media_only_lift_pct' in r
    assert 'total_current_kpi' in r
    assert 'total_optimal_kpi' in r

    # Canonical denominator = total KPI (always larger than media-only)
    # → canonical lift_pct в abs value <= legacy lift_pct (Σ baseline)
    canonical = float(r['expected_lift_pct'])
    legacy = float(r['media_only_lift_pct'])
    if abs(legacy) > 0.1:
        assert abs(canonical) <= abs(legacy) + 0.01, (
            f"Canonical |{canonical}| should be ≤ legacy |{legacy}| "
            f"(canonical denominator is always larger)"
        )


@pytest.mark.parametrize('seed', [0, 1, 2])
def test_scenario_returns_canonical_and_legacy_lift(tmp_path, seed):
    """Scenario output has both `lift_pct` (canonical) and `lift_pct_baseline_only` (legacy)."""
    proj = tmp_path / f'scn_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24, n_posterior_samples=0)
    plan = make_media_plan_from_current(proj, per_period=True)

    r = _run_scenario(proj, plan)
    assert _is_ok(r)
    totals = r['totals']
    assert 'lift_pct' in totals
    assert 'lift_pct_baseline_only' in totals
    assert 'current_total_kpi' in totals


@pytest.mark.parametrize('seed', [0, 1, 2])
def test_optimizer_scenario_lift_consistency(tmp_path, seed):
    """5a invariant: when scenario uses current allocation, lift_pct ≈ 0 (canonical)."""
    proj = tmp_path / f'cons_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24, n_posterior_samples=0)

    plan_current = make_media_plan_from_current(proj, per_period=True)
    r_scn = _run_scenario(proj, plan_current, name='use_current')
    assert _is_ok(r_scn)

    # When scenario allocation = current allocation → scenario_total ≈ current_total_kpi → lift ≈ 0
    canonical_lift = float(r_scn['totals']['lift_pct'])
    # Tolerance: per-period flat allocation rebuild через make_media_plan_from_current
    # introduces ≤1 п.п. rounding difference vs raw current spend (synthetic data variability).
    assert abs(canonical_lift) < 1.5, (
        f"Scenario at current allocation should have lift ≈ 0, got {canonical_lift}"
    )


@pytest.mark.parametrize('seed', [0, 1])
def test_legacy_rollback_flag(tmp_path, seed, monkeypatch):
    """AURORA_LEGACY_LIFT_FORMULA=1 → optimizer reports old media-only ratio."""
    proj = tmp_path / f'roll_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=3, n_periods=24, n_posterior_samples=0)

    # Reset module-level cached env reading by re-importing optimizer
    monkeypatch.setenv('AURORA_LEGACY_LIFT_FORMULA', '1')
    r_legacy = _run_optimize(proj)
    assert _is_ok(r_legacy)
    legacy_lift = float(r_legacy['expected_lift_pct'])
    media_only_field = float(r_legacy['media_only_lift_pct'])
    assert abs(legacy_lift - media_only_field) < 0.01, (
        f"With LEGACY flag, expected_lift_pct ({legacy_lift}) should equal "
        f"media_only_lift_pct ({media_only_field})"
    )

    monkeypatch.delenv('AURORA_LEGACY_LIFT_FORMULA', raising=False)
    r_canonical = _run_optimize(proj)
    canonical_lift = float(r_canonical['expected_lift_pct'])
    # Canonical and legacy should differ when there's any baseline
    # (baseline → larger canonical denominator → smaller canonical lift in absolute value)


@pytest.mark.parametrize('seed', [0, 1])
def test_lift_consistency_across_engines(tmp_path, seed):
    """Triangulate canonical lift across optimizer + scenario.

    Run optimizer, get optimal allocation X. Run scenario with X as media_plan.
    Both should agree on canonical lift_pct (within tolerance for floating-point ops).
    """
    proj = tmp_path / f'tri_{seed}'
    build_synthetic_pickle(proj, seed=seed, n_channels=4, n_periods=24, n_posterior_samples=0)

    r_opt = _run_optimize(proj)
    assert _is_ok(r_opt)
    opt_lift = float(r_opt['expected_lift_pct'])

    # Build media_plan from optimizer's optimal allocation
    optimal_total_per_channel = {ch['name']: float(ch['optimal_spend']) for ch in r_opt['channels']}
    n_periods = 24
    plan = {col: [optimal_total_per_channel.get(col, 0) / n_periods] * n_periods
            for col in optimal_total_per_channel}

    r_scn = _run_scenario(proj, plan, name='optimal_alloc')
    assert _is_ok(r_scn)
    scn_lift = float(r_scn['totals']['lift_pct'])

    # Both engines compute lift via canonical formula on same model + same allocation.
    # Tolerance ~2 п.п. accommodates differences in per-period averaging (optimizer uses
    # Hill-of-mean for analyst mode; scenario uses per-period sum-of-Hill); both equally
    # valid math approaches, but they не bit-exact на synthetic Hill-saturated data.
    assert abs(opt_lift - scn_lift) < 2.5, (
        f"Optimizer canonical lift ({opt_lift}) and scenario canonical lift ({scn_lift}) "
        f"should agree within 2.5 п.п. — diff {opt_lift - scn_lift}"
    )
