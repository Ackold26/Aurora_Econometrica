"""Tests для optimize/bounds.py - safe corridor MVP formula (ADR-014)."""
from __future__ import annotations

import numpy as np
import pytest

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from optimize.bounds import compute_per_channel_bounds, is_in_safe_corridor


# ─── compute_per_channel_bounds - basic ─────────────────────────────────────

def test_uniform_history_gives_tight_corridor():
    """Если все значения равны - P5=P95=mu, lo=hi=mu (или near-mu)."""
    spend = np.full(20, 100.0)
    bounds = compute_per_channel_bounds(spend)
    assert bounds['mu'] == 100.0
    assert bounds['p5'] == 100.0
    assert bounds['p95'] == 100.0
    # MVP: lo = max(P5, 0.5*mu) = max(100, 50) = 100
    assert bounds['lo'] == 100.0
    # hi = min(P95, 1.5*mu) = min(100, 150) = 100
    assert bounds['hi'] == 100.0


def test_normal_distribution_bounds():
    """На normal distribution lo ≈ 0.5*mu, hi ≈ 1.5*mu (relative dominate)."""
    np.random.seed(42)
    spend = np.random.normal(100, 20, 1000).clip(min=10)
    bounds = compute_per_channel_bounds(spend)
    # mu ≈ 100, P5 ≈ 67, P95 ≈ 133
    assert 95 < bounds['mu'] < 105
    # MVP: lo = max(P5≈67, 50) = 67. hi = min(P95≈133, 150) = 133.
    assert 60 < bounds['lo'] < 75
    assert 125 < bounds['hi'] < 140


def test_skewed_distribution_relative_caps():
    """Highly skewed history - relative factors clip extreme percentiles."""
    np.random.seed(42)
    # Lognormal: long right tail.
    spend = np.random.lognormal(mean=4.5, sigma=1.5, size=1000)
    bounds = compute_per_channel_bounds(spend)

    # P95 на lognormal может быть очень большим - relative factor 1.5x clipping protects.
    assert bounds['hi'] <= bounds['mu'] * 1.5 + 1e-6  # numerical tolerance


def test_zero_history_returns_zero_corridor():
    spend = np.zeros(20)
    bounds = compute_per_channel_bounds(spend)
    assert bounds['lo'] == 0.0
    assert bounds['hi'] == 0.0
    assert bounds['mu'] == 0.0


def test_mostly_zeros_uses_only_positive():
    """Channel with mostly zeros (sparse spend) - corridor based on positive entries only."""
    spend = np.array([0, 0, 0, 100, 0, 200, 0, 0, 150, 0])
    bounds = compute_per_channel_bounds(spend)
    # mu = (100 + 200 + 150) / 3 = 150
    assert bounds['mu'] == 150.0


# ─── compute_per_channel_bounds - custom factors ────────────────────────────

def test_custom_factors():
    """Phase B Expert mode parameters override defaults."""
    spend = np.full(20, 100.0)
    bounds = compute_per_channel_bounds(spend, relative_lo_factor=0.3, relative_hi_factor=2.0)
    # Constant data: P5=P95=100. lo=max(100, 30)=100. hi=min(100, 200)=100.
    assert bounds['lo'] == 100.0
    assert bounds['hi'] == 100.0


# ─── is_in_safe_corridor ────────────────────────────────────────────────────

def test_value_inside_corridor_is_green():
    bounds = {'lo': 50.0, 'hi': 150.0}
    assert is_in_safe_corridor(75, bounds) == 'green'
    assert is_in_safe_corridor(100, bounds) == 'green'
    assert is_in_safe_corridor(150, bounds) == 'green'
    assert is_in_safe_corridor(50, bounds) == 'green'


def test_value_just_outside_is_yellow():
    """В пределах ±10% от bounds - yellow."""
    bounds = {'lo': 100.0, 'hi': 200.0}
    # 5% выше hi → 210 → yellow.
    assert is_in_safe_corridor(210, bounds) == 'yellow'
    # 8% ниже lo → 92 → yellow.
    assert is_in_safe_corridor(92, bounds) == 'yellow'


def test_value_far_outside_is_red():
    bounds = {'lo': 100.0, 'hi': 200.0}
    # 50% выше hi → 300 → red.
    assert is_in_safe_corridor(300, bounds) == 'red'
    # 50% ниже lo → 50 → red.
    assert is_in_safe_corridor(50, bounds) == 'red'


def test_corridor_at_zero_handles_gracefully():
    """Edge case: corridor [0, 0] (e.g. inactive channel)."""
    bounds = {'lo': 0.0, 'hi': 0.0}
    assert is_in_safe_corridor(0, bounds) == 'green'
    # Любое > 0 → red (delta_relative = inf).
    assert is_in_safe_corridor(1, bounds) == 'red'
