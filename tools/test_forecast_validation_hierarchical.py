"""Tests for hierarchical_extrapolation_warning() helper (Phase 2.0 Part 2 / Этап 5).

Plan: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §6 + §7 L5.

Verifies:
    - Returns None для non-hierarchical models
    - Returns None below 3× threshold
    - Returns warning above threshold с brand_channels list + ratio
    - Threshold parametric (custom drift_threshold)
    - Edge cases: empty categories, no brand channels, zero training budget

Run:
    pytest tools/test_forecast_validation_hierarchical.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / 'econometrica'))

from utils.forecast_validation import hierarchical_extrapolation_warning  # noqa: E402


def _md(use_hier: bool, categories: dict | None = None) -> dict:
    return {
        'use_hierarchical': use_hier,
        'channel_categories': categories or {},
    }


def test_non_hierarchical_returns_none():
    """Flat model (use_hierarchical=False) → no warning."""
    md = _md(False, {'tv': 'brand'})
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=1_000_000
    ) is None


def test_below_threshold_returns_none():
    """Hierarchical но ratio < 3× → no warning."""
    md = _md(True, {'tv': 'brand'})
    # ratio = 2.5 < 3.0 default
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=2_500_000, train_total_money=1_000_000
    ) is None


def test_at_threshold_returns_none():
    """ratio == threshold → strictly below check fires AT 3.0+ε; exactly 3.0 → None."""
    md = _md(True, {'tv': 'brand'})
    # ratio = 3.0 — boundary, test strict > check
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=3_000_000, train_total_money=1_000_000
    ) is None


def test_above_threshold_returns_warning():
    """ratio > 3× + hierarchical + brand channels → warning emitted."""
    md = _md(True, {'tv': 'brand', 'ooh': 'brand', 'search': 'performance'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=4_000_000, train_total_money=1_000_000
    )
    assert w is not None
    assert w['severity'] == 'warn'
    assert w['forecast_ratio'] == 4.0
    assert sorted(w['brand_channels']) == ['ooh', 'tv']
    assert w['threshold'] == 3.0
    assert 'brand-каналы' in w['message_ru'].lower()


def test_no_brand_channels_returns_none():
    """Hierarchical model но без brand-categorized channels → no warning."""
    md = _md(True, {'search': 'performance', 'social': 'performance'})
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=1_000_000
    ) is None


def test_empty_categories_returns_none():
    """Hierarchical=True но channel_categories empty → no warning."""
    md = _md(True, {})
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=1_000_000
    ) is None


def test_missing_categories_key_returns_none():
    """No channel_categories key at all → graceful None."""
    md = {'use_hierarchical': True}
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=1_000_000
    ) is None


def test_zero_train_budget_returns_none():
    """train_total_money=0 → division-by-zero guard, returns None."""
    md = _md(True, {'tv': 'brand'})
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=0.0
    ) is None


def test_negative_train_budget_returns_none():
    """Negative train budget — degenerate, returns None."""
    md = _md(True, {'tv': 'brand'})
    assert hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=-1_000_000
    ) is None


def test_custom_threshold():
    """Threshold parametrizable — pass 5.0 → 4× ratio passes (no warning)."""
    md = _md(True, {'tv': 'brand'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=4_000_000, train_total_money=1_000_000,
        brand_drift_threshold=5.0,
    )
    assert w is None


def test_custom_threshold_triggers():
    """Custom threshold 1.5 → 2× ratio triggers warning."""
    md = _md(True, {'tv': 'brand'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=2_000_000, train_total_money=1_000_000,
        brand_drift_threshold=1.5,
    )
    assert w is not None
    assert w['threshold'] == 1.5
    assert w['forecast_ratio'] == 2.0


def test_warning_message_ru_format():
    """Russian message contains key terms + brand channel names + ratio."""
    md = _md(True, {'tv_brand': 'brand', 'olv_brand': 'brand'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=5_000_000, train_total_money=1_000_000
    )
    assert w is not None
    msg = w['message_ru']
    assert '5.0×' in msg or '5.0x' in msg.replace('×', 'x')
    assert 'tv_brand' in msg or 'olv_brand' in msg
    assert 'pooling' in msg.lower() or 'pooling' in msg
    assert 'cross-check' in msg.lower() or 'flat' in msg.lower()


def test_warning_includes_actionable_guidance():
    """Message recommends cross-check + horizon reduction."""
    md = _md(True, {'tv': 'brand'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=10_000_000, train_total_money=1_000_000
    )
    assert w is not None
    msg = w['message_ru'].lower()
    assert 'flat' in msg  # recommends flat-model cross-check
    assert ('сократите' in msg or 'горизонт' in msg)


# Integration test: high-volume parametric verification
@pytest.mark.parametrize('ratio,should_warn', [
    (1.0, False),
    (2.0, False),
    (2.99, False),
    (3.0, False),     # boundary — not strictly above
    (3.01, True),
    (5.0, True),
    (10.0, True),
    (100.0, True),
])
def test_threshold_boundary_ratio_sweep(ratio, should_warn):
    """Sweep ratios around 3× boundary."""
    md = _md(True, {'tv': 'brand'})
    w = hierarchical_extrapolation_warning(
        md, forecast_budget_money=ratio * 1_000_000,
        train_total_money=1_000_000,
    )
    assert (w is not None) == should_warn, f'ratio={ratio}: warn={w is not None}, expected={should_warn}'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
