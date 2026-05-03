"""Optimizer edge case matrix — Phase 2 of audit.

Plan: C:\\Users\\ackol\\.claude\\plans\\zazzy-tumbling-kettle.md, Phase 2.

Systematic enumeration corner cases — each explicit unit test с pass/fail expectation.

Eleven batches:
    A — Forecast periods validation (9 cases)
    B — Channel count variations (5 cases)
    C — Unit costs / mixed money smell (5 cases)
    D — Money target / What-if extremes (6 cases)
    E — Pass-18 regression lock-in (3 cases)
    F — Anchor monotonicity matrix in planning + inflation (5 cases)
    G — Zero-spend channels (3 cases)
    H — Untrained channels mix (3 cases)
    I — Awareness pickle horizon caps (3 cases)
    J — Conditional-state UnboundLocalError prevention (5 cases)
    K — Inflation edge cases (7 cases)

Total: 54 tests.

Run:
    pytest tools/test_optimizer_edge_cases.py -v
"""
from __future__ import annotations

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

from _optimizer_fixtures import (  # noqa: E402
    build_synthetic_pickle,
    current_total_money,
    is_ok,
)


def _build_multi_year(project_dir: Path, *, seed: int, n_channels: int = 6) -> dict:
    """Build pickle spanning 2 calendar years (для inflation tests).

    Phase 2 audit pass 4: inflation needs spend distributed across multiple
    training years, иначе weighted-average == current_cost (no adjustment).
    """
    md = build_synthetic_pickle(
        project_dir,
        seed=seed,
        n_channels=n_channels,
        n_periods=104,  # 2 years weekly
    )
    # Override dates к 2024-01 .. 2025-12
    import pickle as _p
    df = pd.read_excel(md['config']['data_file'])
    df['date'] = pd.date_range('2024-01-08', periods=104, freq='W-MON')
    df.to_excel(md['config']['data_file'], index=False)
    return md


# ══════════════════════════════════════════════════════════════════════
# Batch A — Forecast periods validation
# ══════════════════════════════════════════════════════════════════════

def test_A1_forecast_periods_none_analyst_mode(tmp_path):
    """forecast_periods=None → planning_mode=False, analyst-mode echo."""
    proj = tmp_path / 'A1'
    build_synthetic_pickle(proj, seed=1, n_periods=31)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r)
    assert r['planning_mode'] is False
    assert r['train_n_periods'] == 31
    assert r['forecast_n_periods'] == 31


def test_A2_forecast_periods_equal_train(tmp_path):
    """forecast_periods=train_n → planning_mode=True, forecast echoed."""
    proj = tmp_path / 'A2'
    build_synthetic_pickle(proj, seed=1, n_periods=31)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 31}, str(proj))
    assert is_ok(r)
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 31


def test_A3_forecast_periods_half_train(tmp_path):
    """forecast_periods=train×0.5 → planning_mode=True (compression OK)."""
    proj = tmp_path / 'A3'
    build_synthetic_pickle(proj, seed=1, n_periods=52)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 26}, str(proj))
    assert is_ok(r)
    assert r['planning_mode'] is True
    assert r['forecast_n_periods'] == 26


def test_A4_forecast_periods_1_5x_train(tmp_path):
    """forecast_periods=train×1.5 → planning_mode=True (warn-zone, NOT reject)."""
    proj = tmp_path / 'A4'
    build_synthetic_pickle(proj, seed=1, n_periods=52)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 78}, str(proj))
    assert is_ok(r), f'1.5× should not reject (warn only): {r.get("error_code")}'
    assert r['planning_mode'] is True


def test_A5_forecast_periods_2x_train_boundary(tmp_path):
    """forecast_periods=train×2.0 (boundary, sales cap) → planning_mode=True."""
    proj = tmp_path / 'A5'
    build_synthetic_pickle(proj, seed=1, n_periods=52)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 104}, str(proj))
    assert is_ok(r), f'2.0× boundary should pass: {r.get("error_code")}'
    assert r['planning_mode'] is True


def test_A6_forecast_periods_above_2x_rejected(tmp_path):
    """forecast_periods > train×2.0 (sales) → FORECAST_HORIZON_TOO_LONG."""
    proj = tmp_path / 'A6'
    build_synthetic_pickle(proj, seed=1, n_periods=52)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 110}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'FORECAST_HORIZON_TOO_LONG'


def test_A7_forecast_periods_zero_rejected(tmp_path):
    """forecast_periods=0 → INVALID_FORECAST_PERIODS."""
    proj = tmp_path / 'A7'
    build_synthetic_pickle(proj, seed=1)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 0}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INVALID_FORECAST_PERIODS'


def test_A8_forecast_periods_negative_rejected(tmp_path):
    """forecast_periods=-1 → INVALID_FORECAST_PERIODS."""
    proj = tmp_path / 'A8'
    build_synthetic_pickle(proj, seed=1)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': -1}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INVALID_FORECAST_PERIODS'


def test_A9_forecast_periods_garbage_rejected(tmp_path):
    """forecast_periods='abc' → INVALID_FORECAST_PERIODS (type coercion fail)."""
    proj = tmp_path / 'A9'
    build_synthetic_pickle(proj, seed=1)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0, 'forecast_periods': 'abc'}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INVALID_FORECAST_PERIODS'


# ══════════════════════════════════════════════════════════════════════
# Batch B — Channel count variations
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('n_channels', [1, 2, 6, 10, 20])
def test_B_channel_count_works(tmp_path, n_channels):
    """Optimizer handles n_channels ∈ {1, 2, 6, 10, 20}."""
    proj = tmp_path / f'B_{n_channels}'
    build_synthetic_pickle(proj, seed=42, n_channels=n_channels, mixed_units=False)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r), f'n_channels={n_channels}: {r.get("status")} / {r.get("message")}'
    assert len(r['channels']) == n_channels
    # All channels accounted for
    names = {ch['name'] for ch in r['channels']}
    assert len(names) == n_channels


# ══════════════════════════════════════════════════════════════════════
# Batch C — Unit costs / mixed money smell
# ══════════════════════════════════════════════════════════════════════

def test_C1_all_money_units(tmp_path):
    """All channels uc=1 (money) → no UNIT_SMELL, money mode auto."""
    proj = tmp_path / 'C1'
    build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=False)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r)
    # All channels report unit_cost=1.0
    assert all(ch['unit_cost'] == 1.0 for ch in r['channels'])


def test_C2_mixed_units_auto_derive_money_budget(tmp_path):
    """Mixed (1 native + others money), no UNIT_HINTS in money names → auto-derive."""
    proj = tmp_path / 'C2'
    build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=True)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    # Pass-0.1 fix: mixed should auto-derive money budget, not UNIT_SMELL.
    # tv_trps_brand has UNIT hint 'TRP' BUT uc=150_000 ≠ 1 → no smell triggered.
    assert is_ok(r), f'auto-derive should succeed: {r.get("error_code")}'


def test_C3_unit_smell_blocks_native_uc1(tmp_path):
    """UNIT_HINTS in name + uc=1 + no money budget override → UNIT_SMELL."""
    proj = tmp_path / 'C3'
    md = build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=True)
    # Force tv_trps_brand uc к 1.0 (smell trigger) + ensure no money override
    import pickle
    md['config']['unit_costs']['tv_trps_brand'] = 1.0
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'UNIT_SMELL'


def test_C4_unit_smell_bypassed_by_money_budget_override(tmp_path):
    """total_budget_money override → UNIT_SMELL guard skipped."""
    proj = tmp_path / 'C4'
    md = build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=True)
    # Force smell-trigger config
    import pickle
    md['config']['unit_costs']['tv_trps_brand'] = 1.0
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    cur_money = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'total_budget_money': cur_money,
    }, str(proj))
    assert is_ok(r), f'override should bypass smell: {r.get("error_code")}'


def test_C5_native_unit_costs_explicit_no_smell(tmp_path):
    """All-native (uc≠1, no UNIT_HINTS) → ok via auto-derive."""
    proj = tmp_path / 'C5'
    md = build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=False)
    # Override all uc=200_000 + rename channels (no UNIT_HINTS)
    import pickle
    new_uc = {col: 200_000.0 for col in md['config']['media_columns']}
    md['config']['unit_costs'] = new_uc
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    # All uc≠1 → is_all_native=True → goes through native path with auto money budget
    assert is_ok(r), f'all-native with no hints: {r.get("error_code")}: {r.get("message")}'


# ══════════════════════════════════════════════════════════════════════
# Batch D — Money target / What-if extremes
# ══════════════════════════════════════════════════════════════════════

def test_D1_money_target_equals_current(tmp_path):
    """total_budget_money = current → ok, lift from redistribution."""
    proj = tmp_path / 'D1'
    build_synthetic_pickle(proj, seed=11, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'total_budget_money': cur,
    }, str(proj))
    assert is_ok(r)
    optimal_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
    assert abs(optimal_money - cur) / cur < 0.005


def test_D2_money_target_half_current(tmp_path):
    """What-if: 0.5× current → ok, lift may be smaller (less budget to optimize)."""
    proj = tmp_path / 'D2'
    build_synthetic_pickle(proj, seed=11, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 300.0,
        'total_budget_money': cur * 0.5,
    }, str(proj))
    assert is_ok(r)
    optimal_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
    assert abs(optimal_money - cur * 0.5) / (cur * 0.5) < 0.005


def test_D3_money_target_1_5x_current(tmp_path):
    """What-if: 1.5× current → positive lift expected."""
    proj = tmp_path / 'D3'
    build_synthetic_pickle(proj, seed=11, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 300.0,
        'total_budget_money': cur * 1.5,
    }, str(proj))
    assert is_ok(r)
    optimal_money = sum(ch['optimal_spend_money'] for ch in r['channels'])
    assert abs(optimal_money - cur * 1.5) / (cur * 1.5) < 0.005


def test_D4_money_target_2x_current(tmp_path):
    """What-if: 2× current with wide bounds → ok."""
    proj = tmp_path / 'D4'
    build_synthetic_pickle(proj, seed=11, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 10.0, 'max_pct': 300.0,  # max=3× supports 2× target
        'total_budget_money': cur * 2.0,
    }, str(proj))
    assert is_ok(r)


def test_D5_money_target_above_max_capacity_rejected(tmp_path):
    """target > sum(max_bounds) → INFEASIBLE_BUDGET_HIGH."""
    proj = tmp_path / 'D5'
    build_synthetic_pickle(proj, seed=11, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 50.0, 'max_pct': 150.0,  # sum_max = 1.5× current
        'total_budget_money': cur * 5.0,    # 5× — way above
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INFEASIBLE_BUDGET_HIGH'


def test_D6_money_target_below_min_floor_rejected(tmp_path):
    """target=0 with min_pct>0 → INFEASIBLE_BUDGET_LOW."""
    proj = tmp_path / 'D6'
    build_synthetic_pickle(proj, seed=11, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 50.0, 'max_pct': 200.0,  # min_lower > 0
        'total_budget_money': 0.0,
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INFEASIBLE_BUDGET_LOW'


# ══════════════════════════════════════════════════════════════════════
# Batch E — Pass-18 regression lock-in
# ══════════════════════════════════════════════════════════════════════

def test_E1_whatif_half_wide_bounds_per_channel_no_unbound(tmp_path):
    """Pass-18 trigger: whatIfMult=0.5, 0/500% widening, per-channel constraints.

    Pre-fix: при user_widened=True + default_anchor infeasibility check failure,
    `_default_anchor_enabled` оставался unbound → UnboundLocalError на post-loop
    check `if _default_anchor_enabled`. Post-fix initializes ВСЕ anchor vars
    ДО if-блока. Test verifies graceful degradation.
    """
    proj = tmp_path / 'E1'
    md = build_synthetic_pickle(proj, seed=7, n_channels=4, mixed_units=False)
    media_cols = md['config']['media_columns']
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    # whatIfMult=0.5 + wide bounds (0/500) + per-channel for all 4 channels
    config = {
        'min_pct': 0.0, 'max_pct': 500.0,
        'min_per_channel': {c: 30.0 for c in media_cols[:4]},
        'max_per_channel': {c: 250.0 for c in media_cols[:4]},
        'total_budget_money': cur * 0.5,
    }
    try:
        r = optimize(config, str(proj))
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'E1 regression: UnboundLocalError surfaced: {type(e).__name__}: {e}')
    # Must return well-formed dict с 'status' field (ok or explicit error)
    assert 'status' in r, f'malformed result: {r}'
    if r.get('status') == 'error':
        # Accept explicit infeasibility — but no Python exception
        assert r.get('error_code'), f'error без error_code: {r}'


def test_E2_whatif_extreme_high_with_tight_bounds_explicit_infeasible(tmp_path):
    """whatIfMult=2.0 + tight bounds → explicit INFEASIBLE_BUDGET_HIGH (not crash)."""
    proj = tmp_path / 'E2'
    build_synthetic_pickle(proj, seed=7, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 80.0, 'max_pct': 120.0,  # tight ±20%
        'total_budget_money': cur * 2.0,    # 2× — infeasible
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INFEASIBLE_BUDGET_HIGH'


def test_E3_whatif_zero_budget_explicit_reject(tmp_path):
    """whatIfMult=0 → INFEASIBLE_BUDGET_LOW (or similar explicit error)."""
    proj = tmp_path / 'E3'
    build_synthetic_pickle(proj, seed=7, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 50.0, 'max_pct': 200.0,
        'total_budget_money': 0.0,
    }, str(proj))
    assert r.get('status') == 'error'
    # Either INFEASIBLE_BUDGET_LOW or zero-target degenerate handling
    assert r.get('error_code') in {'INFEASIBLE_BUDGET_LOW', 'INVALID_BUDGET'}, (
        f'unexpected error_code: {r.get("error_code")}'
    )


# ══════════════════════════════════════════════════════════════════════
# Batch F — Anchor monotonicity matrix (planning + inflation context)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('seed', list(range(5)))
def test_F_anchor_monotonic_planning_with_inflation(tmp_path, seed):
    """Wider bounds in planning mode + inflation → lift_wide ≥ lift_narrow.

    This is the production-realistic version of Phase 1 I1: planning_mode + inflation.
    """
    proj = tmp_path / f'F_{seed}'
    md = _build_multi_year(proj, seed=seed, n_channels=6)
    media_cols = md['config']['media_columns']
    inflation_pct = {c: 25.0 for c in media_cols}

    from engines.optimizer import optimize
    base_cfg = {
        'forecast_periods': 52,
        'unit_cost_inflation_pct': inflation_pct,
        'min_per_channel': {media_cols[1]: 50.0, media_cols[2]: 80.0},
        'max_per_channel': {media_cols[1]: 200.0, media_cols[2]: 150.0},
    }

    r_n = optimize({**base_cfg, 'min_pct': 50.0, 'max_pct': 150.0}, str(proj))
    r_w = optimize({**base_cfg, 'min_pct': 0.0, 'max_pct': 500.0}, str(proj))

    if not is_ok(r_n) or not is_ok(r_w):
        pytest.skip(f'narrow={r_n.get("status")} wide={r_w.get("status")}')
    if r_n.get('baseline_zero') or r_w.get('baseline_zero'):
        pytest.skip()

    lift_n = float(r_n['expected_lift_pct'])
    lift_w = float(r_w['expected_lift_pct'])
    assert lift_w >= lift_n - 0.5, (
        f'F monotonicity violated (seed={seed}): wide={lift_w:.2f}% < narrow={lift_n:.2f}%'
    )


# ══════════════════════════════════════════════════════════════════════
# Batch G — Zero-spend channels
# ══════════════════════════════════════════════════════════════════════

def test_G1_one_zero_spend_channel_doesnt_poison(tmp_path):
    """One channel current_spend=0, others positive → solve OK, zero ch bounds=(0, fallback)."""
    proj = tmp_path / 'G1'
    md = build_synthetic_pickle(proj, seed=13, n_channels=4, zero_spend_channels=['ch_2'])

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r), f'{r.get("status")}: {r.get("message")}'

    zero_ch = next((ch for ch in r['channels'] if ch['name'] == 'ch_2'), None)
    assert zero_ch is not None
    assert zero_ch['current_spend_money'] == 0.0
    # Optimal must be ≥ 0 (no negative spend)
    assert zero_ch['optimal_spend_money'] >= 0.0


def test_G2_two_zero_spend_channels(tmp_path):
    """Two zero-spend channels among 4 → solve OK на остальных 2 active."""
    proj = tmp_path / 'G2'
    build_synthetic_pickle(
        proj, seed=13, n_channels=4,
        zero_spend_channels=['ch_2', 'ch_3'],
    )

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r)
    zero_chs = [ch for ch in r['channels'] if ch['name'] in {'ch_2', 'ch_3'}]
    assert all(ch['current_spend_money'] == 0.0 for ch in zero_chs)


def test_G3_all_zero_spend_rejected(tmp_path):
    """All channels current_spend=0 → INFEASIBLE_BUDGET_LOW (degenerate)."""
    proj = tmp_path / 'G3'
    md = build_synthetic_pickle(proj, seed=13, n_channels=4, mixed_units=False)
    # Zero out all media в данных
    df = pd.read_excel(md['config']['data_file'])
    for col in md['config']['media_columns']:
        df[col] = 0.0
    df.to_excel(md['config']['data_file'], index=False)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    # All zero current → money_target=0 (auto), bounds (0, fallback) → INFEASIBLE
    # OR success with zero everywhere. Both acceptable, no crash.
    assert r.get('status') in {'ok', 'error'}, f'malformed: {r}'
    if r.get('status') == 'error':
        # Accept any explicit error_code
        assert r.get('error_code'), f'error без error_code: {r}'


# ══════════════════════════════════════════════════════════════════════
# Batch H — Untrained channels mix
# ══════════════════════════════════════════════════════════════════════

def test_H1_partial_untrained_excluded_cleanly(tmp_path):
    """6 channels, 2 marked untrained → optimizer scope = 4 active."""
    proj = tmp_path / 'H1'
    md = build_synthetic_pickle(
        proj, seed=17, n_channels=6,
        untrained_channels=['ch_4', 'ch_5'],
    )

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r), f'{r.get("status")}: {r.get("message")}'
    names = {ch['name'] for ch in r['channels']}
    # Untrained excluded from optimization scope
    assert 'ch_4' not in names
    assert 'ch_5' not in names
    assert len(r['channels']) == 4


def test_H2_all_untrained_rejected(tmp_path):
    """All channels untrained → NO_TRAINED_CHANNELS error."""
    proj = tmp_path / 'H2'
    md = build_synthetic_pickle(
        proj, seed=17, n_channels=4,
        untrained_channels=['tv_trps_brand', 'ch_1', 'ch_2', 'ch_3'],
    )

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'NO_TRAINED_CHANNELS'


def test_H3_one_untrained_mid_list(tmp_path):
    """Single untrained channel mid-list → exclusion preserves order of others."""
    proj = tmp_path / 'H3'
    build_synthetic_pickle(
        proj, seed=17, n_channels=5,
        untrained_channels=['ch_2'],
    )

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r)
    names = [ch['name'] for ch in r['channels']]
    assert 'ch_2' not in names
    assert len(names) == 4


# ══════════════════════════════════════════════════════════════════════
# Batch I — Awareness pickle horizon caps
# ══════════════════════════════════════════════════════════════════════

def test_I1_awareness_below_cap_ok(tmp_path):
    """Awareness + forecast_periods = train×1.4 → ok (within 1.5× cap)."""
    proj = tmp_path / 'I1aw'
    build_synthetic_pickle(proj, seed=23, n_channels=3, n_periods=52, awareness=True)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': int(52 * 1.4),
    }, str(proj))
    assert is_ok(r), f'{r.get("error_code")}: {r.get("message")}'
    assert r['planning_mode'] is True


def test_I2_awareness_at_cap_ok(tmp_path):
    """Awareness + forecast=train×1.5 boundary → ok."""
    proj = tmp_path / 'I2aw'
    build_synthetic_pickle(proj, seed=23, n_channels=3, n_periods=52, awareness=True)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': int(52 * 1.5),  # = 78, exactly cap
    }, str(proj))
    assert is_ok(r), f'awareness 1.5× boundary: {r.get("error_code")}'


def test_I3_awareness_above_cap_rejected(tmp_path):
    """Awareness + forecast=train×1.6 → FORECAST_HORIZON_TOO_LONG (1.5× cap)."""
    proj = tmp_path / 'I3aw'
    build_synthetic_pickle(proj, seed=23, n_channels=3, n_periods=52, awareness=True)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'forecast_periods': int(52 * 1.6),  # > 1.5× awareness cap
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'FORECAST_HORIZON_TOO_LONG'


# ══════════════════════════════════════════════════════════════════════
# Batch J — Conditional-state UnboundLocalError prevention
# ══════════════════════════════════════════════════════════════════════

def test_J1_anchor_infeasible_no_unbound(tmp_path):
    """User widened (0/500) + default_anchor infeasible (target=0.1×) → no crash.

    Trigger: money_target = 0.1 × current_total → user pre-flight passes (0% min,
    500% max), but default_anchor sum_def_lo = 0.20 × current_total > 0.1 × total
    → infeasibility check fails → if-block skipped. Pass-18 fix: vars init'd.
    """
    proj = tmp_path / 'J1'
    build_synthetic_pickle(proj, seed=29, n_channels=4)
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    try:
        r = optimize({
            'min_pct': 0.0, 'max_pct': 500.0,
            'total_budget_money': cur * 0.1,
        }, str(proj))
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'J1: UnboundLocalError surfaced: {type(e).__name__}: {e}')
    assert 'status' in r


def test_J2_planning_forecast_n_eq_1_boundary(tmp_path):
    """forecast_periods=1 (minimal valid) → no crash, planning mode active."""
    proj = tmp_path / 'J2'
    build_synthetic_pickle(proj, seed=29, n_channels=3, n_periods=20)

    from engines.optimizer import optimize
    try:
        r = optimize({
            'min_pct': 20.0, 'max_pct': 200.0,
            'forecast_periods': 1,
        }, str(proj))
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'J2: forecast_n=1 boundary crash: {type(e).__name__}: {e}')
    assert is_ok(r) or r.get('error_code'), f'malformed: {r}'


def test_J3_per_group_on_flat_model_explicit_error(tmp_path):
    """Per-group constraints on non-hierarchical model → PER_GROUP_REQUIRES_HIERARCHICAL_MODEL."""
    proj = tmp_path / 'J3'
    build_synthetic_pickle(proj, seed=29, n_channels=4)  # default flat model_version=1.2

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'brand_min_pct': 50.0, 'brand_max_pct': 150.0,
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'PER_GROUP_REQUIRES_HIERARCHICAL_MODEL'


def test_J4_brand_max_above_global_max_explicit_error(tmp_path):
    """brand_max > global_max → INFEASIBLE_GROUP_HIERARCHY (FeasibilityError caught)."""
    proj = tmp_path / 'J4'
    md = build_synthetic_pickle(proj, seed=29, n_channels=4)
    # Promote model к hierarchical so per-group not pre-rejected
    import pickle
    md['model_version'] = '1.3'
    md['use_hierarchical'] = True
    md['channel_categories'] = {
        'tv_trps_brand': 'brand',
        'ch_1': 'brand',
        'ch_2': 'performance',
        'ch_3': 'performance',
    }
    with open(proj / 'models' / 'latest.pkl', 'wb') as f:
        pickle.dump(md, f)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 150.0,
        'brand_max_pct': 200.0,  # > global_max=150 → hierarchy violation
    }, str(proj))
    assert r.get('status') == 'error'
    assert r.get('error_code') == 'INFEASIBLE_GROUP_HIERARCHY'


def test_J5_combined_planning_perchannel_inflation_whatif(tmp_path):
    """Combined: planning + per-channel + inflation + What-if — all 4 features at once."""
    proj = tmp_path / 'J5'
    md = _build_multi_year(proj, seed=29, n_channels=4)
    media_cols = md['config']['media_columns']
    cur = current_total_money(proj)

    from engines.optimizer import optimize
    try:
        r = optimize({
            'min_pct': 10.0, 'max_pct': 300.0,
            'min_per_channel': {media_cols[1]: 30.0},
            'max_per_channel': {media_cols[2]: 250.0},
            'forecast_periods': 52,
            'unit_cost_inflation_pct': {media_cols[0]: 25.0},
            'total_budget_money': cur * 1.2,
        }, str(proj))
    except (NameError, AttributeError, UnboundLocalError) as e:
        pytest.fail(f'J5: combined-features crash: {type(e).__name__}: {e}')
    assert 'status' in r
    if is_ok(r):
        assert r['planning_mode'] is True


# ══════════════════════════════════════════════════════════════════════
# Batch K — Inflation edge cases
# ══════════════════════════════════════════════════════════════════════

def test_K1_inflation_none_no_change(tmp_path):
    """inflation_pct=None → unit_costs unchanged."""
    proj = tmp_path / 'K1'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({'min_pct': 20.0, 'max_pct': 200.0}, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert trps is not None
    assert abs(trps['unit_cost'] - 150_000.0) < 1.0


def test_K2_inflation_empty_dict_no_change(tmp_path):
    """inflation_pct={} → falsy → no adjustment."""
    proj = tmp_path / 'K2'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {},
    }, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert abs(trps['unit_cost'] - 150_000.0) < 1.0


def test_K3_inflation_partial_only_target_adjusted(tmp_path):
    """inflation_pct = {tv_trps: 25%} → only TRPs adjusted (other channels unchanged)."""
    proj = tmp_path / 'K3'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {'tv_trps_brand': 25.0},
    }, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    # Multi-year fixture (2024-2025) + 25% inflation → weighted avg < 150_000
    assert trps['unit_cost'] < 150_000.0
    # Other channels (uc=1) skipped — inflation irrelevant for money channels
    other = next((ch for ch in r['channels'] if ch['name'] == 'ch_1'), None)
    assert abs(other['unit_cost'] - 1.0) < 1e-9


def test_K4_inflation_zero_pct_no_op(tmp_path):
    """inflation_pct = {tv_trps: 0.0} → effective_avg == current_cost."""
    proj = tmp_path / 'K4'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {'tv_trps_brand': 0.0},
    }, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert abs(trps['unit_cost'] - 150_000.0) < 1.0


def test_K5_inflation_uniform_30pct_all_native_adjusted(tmp_path):
    """inflation_pct=30% applied uniformly → only native (uc≠1) channels adjusted."""
    proj = tmp_path / 'K5'
    md = _build_multi_year(proj, seed=31, n_channels=4)
    media_cols = md['config']['media_columns']

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {c: 30.0 for c in media_cols},
    }, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    assert trps['unit_cost'] < 150_000.0
    # uc=1 channels — skipped по logic в apply_inflation_to_unit_costs
    others = [ch for ch in r['channels'] if ch['name'] != 'tv_trps_brand']
    for ch in others:
        assert abs(ch['unit_cost'] - 1.0) < 1e-9


def test_K6_inflation_unknown_channel_silent_skip(tmp_path):
    """inflation_pct contains unknown channel → silent skip (no error, no crash)."""
    proj = tmp_path / 'K6'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    try:
        r = optimize({
            'min_pct': 20.0, 'max_pct': 200.0,
            'unit_cost_inflation_pct': {
                'tv_trps_brand': 25.0,
                'unknown_channel_xyz': 50.0,  # not in media_cols
            },
        }, str(proj))
    except (KeyError, ValueError) as e:
        pytest.fail(f'K6: unknown channel должен silent skip, got: {e}')
    assert is_ok(r)


def test_K7_inflation_negative_deflation(tmp_path):
    """inflation_pct=-10% (deflation) → effective_avg > current_cost (older years more expensive)."""
    proj = tmp_path / 'K7'
    md = _build_multi_year(proj, seed=31, n_channels=4)

    from engines.optimizer import optimize
    r = optimize({
        'min_pct': 20.0, 'max_pct': 200.0,
        'unit_cost_inflation_pct': {'tv_trps_brand': -10.0},
    }, str(proj))
    assert is_ok(r)
    trps = next((ch for ch in r['channels'] if ch['name'] == 'tv_trps_brand'), None)
    # Negative inflation → current_cost / (1 + (-0.1))^offset for older years
    # = current_cost × 1.111 for 1-year-back → weighted avg > 150_000
    assert trps['unit_cost'] > 150_000.0


# ══════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
