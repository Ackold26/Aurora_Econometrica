"""Tests для utils/optimizer_constraints.py — Phase A3.1.

Pure logic tests (no MCMC) covering 3-level constraint precedence + feasibility +
lock-group action.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sidecar'))

from econometrica.utils.optimizer_constraints import (
    ConstraintBundle,
    FeasibilityError,
    lock_group_to_current,
    resolve_channel_bounds,
    validate_feasibility,
)


# ─── 3-level precedence tests ────────────────────────────────────────────────

def test_precedence_per_channel_overrides_per_group():
    """per-channel constraint overrides brand-group setting."""
    bundle = ConstraintBundle(
        global_min_pct=0.2, global_max_pct=2.0,
        brand_min_pct=0.5, brand_max_pct=1.5,
        channel_min_pct={'TV': 0.8}, channel_max_pct={'TV': 1.2},
    )
    cats = {'TV': 'brand'}
    bounds = resolve_channel_bounds('TV', current_money=1000, channel_categories=cats, bundle=bundle)
    # Per-channel 0.8/1.2 wins over brand-group 0.5/1.5
    assert bounds == (800.0, 1200.0)


def test_precedence_per_group_overrides_global():
    """brand-group setting overrides global для brand channels."""
    bundle = ConstraintBundle(
        global_min_pct=0.2, global_max_pct=2.0,
        brand_min_pct=0.5, brand_max_pct=1.5,
    )
    cats = {'TV': 'brand'}
    bounds = resolve_channel_bounds('TV', current_money=1000, channel_categories=cats, bundle=bundle)
    # Brand 0.5/1.5 wins
    assert bounds == (500.0, 1500.0)


def test_mixed_channel_falls_back_to_global(_=None):
    """Mixed category → global (H3 fix — no separate slider для mixed)."""
    bundle = ConstraintBundle(
        global_min_pct=0.2, global_max_pct=2.0,
        brand_min_pct=0.5, brand_max_pct=1.5,
        perf_min_pct=0.1, perf_max_pct=1.2,
    )
    cats = {'OLV': 'mixed'}
    bounds = resolve_channel_bounds('OLV', current_money=1000, channel_categories=cats, bundle=bundle)
    # Mixed = global 0.2/2.0
    assert bounds == (200.0, 2000.0)


def test_unknown_category_channel_uses_global():
    """Channel without category mapping → global."""
    bundle = ConstraintBundle(global_min_pct=0.3, global_max_pct=1.5)
    cats = {}  # no mapping
    bounds = resolve_channel_bounds('UnknownChannel', current_money=1000, channel_categories=cats, bundle=bundle)
    assert bounds == (300.0, 1500.0)


def test_perf_group_separate_from_brand():
    """Perf group constraint applies только к perf channels."""
    bundle = ConstraintBundle(
        global_min_pct=0.2, global_max_pct=2.0,
        brand_min_pct=0.8, brand_max_pct=1.2,
        perf_min_pct=0.4, perf_max_pct=1.8,
    )
    cats = {'TV': 'brand', 'Search': 'performance'}

    tv_bounds = resolve_channel_bounds('TV', 1000, cats, bundle)
    search_bounds = resolve_channel_bounds('Search', 1000, cats, bundle)

    assert tv_bounds == (800.0, 1200.0)
    assert search_bounds == (400.0, 1800.0)


def test_no_group_constraints_set_uses_global():
    """Если brand_min/max == None, brand channel still uses global."""
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    # No brand_min_pct set → falls back к global
    bounds = resolve_channel_bounds('TV', 1000, {'TV': 'brand'}, bundle)
    assert bounds == (500.0, 1500.0)


# ─── Feasibility tests (H4 fix) ──────────────────────────────────────────────

def test_feasibility_brand_max_gt_global_max_raises():
    bundle = ConstraintBundle(
        global_min_pct=0.5, global_max_pct=1.5,
        brand_max_pct=2.0,  # > global_max
    )
    with pytest.raises(FeasibilityError, match='Brand max'):
        validate_feasibility({'TV': 1000}, {'TV': 'brand'}, bundle, budget=1500)


def test_feasibility_perf_max_gt_global_max_raises():
    bundle = ConstraintBundle(
        global_min_pct=0.5, global_max_pct=1.5,
        perf_max_pct=2.5,
    )
    with pytest.raises(FeasibilityError, match='Performance max'):
        validate_feasibility({'Search': 1000}, {'Search': 'performance'}, bundle, budget=1500)


def test_feasibility_budget_below_total_min_raises():
    """Budget too small для constraint sum minimums."""
    bundle = ConstraintBundle(global_min_pct=1.0, global_max_pct=2.0)
    cats = {'TV': 'mixed', 'OOH': 'mixed'}
    money = {'TV': 1000, 'OOH': 1000}
    # Sum min = 2000, but budget = 1500
    with pytest.raises(FeasibilityError, match='меньше суммы минимумов'):
        validate_feasibility(money, cats, bundle, budget=1500)


def test_feasibility_budget_above_total_max_raises():
    """Budget too large для constraint sum maximums."""
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    money = {'TV': 1000, 'OOH': 1000}
    # Sum max = 3000, but budget = 5000
    with pytest.raises(FeasibilityError, match='больше суммы максимумов'):
        validate_feasibility(money, {}, bundle, budget=5000)


def test_feasibility_passes_for_well_formed_constraints():
    """Sane setup → no error."""
    bundle = ConstraintBundle(
        global_min_pct=0.5, global_max_pct=1.5,
        brand_min_pct=0.8, brand_max_pct=1.2,
    )
    money = {'TV': 1000, 'OOH': 1000, 'Search': 500}
    cats = {'TV': 'brand', 'OOH': 'brand', 'Search': 'performance'}
    # Sum min = 800+800+250 = 1850, sum max = 1200+1200+750 = 3150
    validate_feasibility(money, cats, bundle, budget=2500)  # no error


# ─── Lock-group action tests (H5 fix) ────────────────────────────────────────

def test_lock_brand_sets_min_max_to_100_percent():
    bundle = ConstraintBundle(
        global_min_pct=0.5, global_max_pct=1.5,
        brand_min_pct=0.8, brand_max_pct=1.2,
        perf_min_pct=0.4, perf_max_pct=1.6,
    )
    locked = lock_group_to_current(bundle, 'brand')
    assert locked.brand_min_pct == 1.0
    assert locked.brand_max_pct == 1.0
    # Perf untouched
    assert locked.perf_min_pct == 0.4
    assert locked.perf_max_pct == 1.6


def test_lock_performance_sets_min_max_to_100_percent():
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    locked = lock_group_to_current(bundle, 'performance')
    assert locked.perf_min_pct == 1.0
    assert locked.perf_max_pct == 1.0


def test_lock_unknown_group_raises():
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    with pytest.raises(ValueError, match='Unknown group'):
        lock_group_to_current(bundle, 'mixed')


def test_lock_brand_then_resolve_returns_current_money():
    """После lock brand → resolve_channel_bounds возвращает current_money / current_money."""
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    locked = lock_group_to_current(bundle, 'brand')
    bounds = resolve_channel_bounds('TV', current_money=1000, channel_categories={'TV': 'brand'}, bundle=locked)
    assert bounds == (1000.0, 1000.0)


# ─── Integration scenarios ───────────────────────────────────────────────────

def test_realistic_brand_lock_perf_flexible_scenario():
    """Common scenario: brand contractual (locked), perf flexible."""
    bundle = ConstraintBundle(
        global_min_pct=0.3, global_max_pct=1.8,
        perf_min_pct=0.5, perf_max_pct=1.5,
    )
    locked = lock_group_to_current(bundle, 'brand')

    money = {'TV': 5000, 'OOH': 2000, 'Search': 1000, 'Social': 500}
    cats = {'TV': 'brand', 'OOH': 'brand', 'Search': 'performance', 'Social': 'performance'}

    # Brand sum = 7000 (locked at current). Perf sum range = 750..2250.
    # Budget = 7000 + 1500 = 8500 — feasible
    validate_feasibility(money, cats, locked, budget=8500)

    # Brand bounds = current money exactly
    assert resolve_channel_bounds('TV', 5000, cats, locked) == (5000, 5000)
    assert resolve_channel_bounds('OOH', 2000, cats, locked) == (2000, 2000)
    # Perf bounds = group constraints
    assert resolve_channel_bounds('Search', 1000, cats, locked) == (500, 1500)
    assert resolve_channel_bounds('Social', 500, cats, locked) == (250, 750)


def test_constraint_bundle_is_frozen():
    """Bundle immutable (defensive use)."""
    bundle = ConstraintBundle(global_min_pct=0.5, global_max_pct=1.5)
    with pytest.raises(Exception):  # FrozenInstanceError
        bundle.global_min_pct = 0.9
