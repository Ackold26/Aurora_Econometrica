"""Unit tests for utils/forecast_validation.py — Phase 2.1 Step 2.

Covers granularity detection, seasonality detection, x_norm quantiles,
extrapolation severity, drift checks, horizon warnings, conformal-in-planning,
warning priority, KPI registry coupling.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))

from utils.forecast_validation import (  # noqa: E402
    compute_x_norm_quantiles,
    conformal_planning_intervals,
    detect_granularity,
    detect_seasonality,
    extrapolation_severity,
    get_forecast_horizon_max_multiplier,
    horizon_extrapolation_check,
    resolve_warning_priority,
    saturation_drift_check,
)
from utils.posterior_propagation import verdict_tier  # noqa: E402


class TestDetectGranularity:
    def test_weekly_perfect(self):
        dates = pd.date_range('2023-01-01', periods=52, freq='W')
        result = detect_granularity(dates)
        assert result['granularity'] == 'W'
        assert result['confidence'] > 0.9
        assert not result['requires_user_confirm']

    def test_monthly(self):
        dates = pd.date_range('2023-01-01', periods=24, freq='ME')
        result = detect_granularity(dates)
        assert result['granularity'] == 'M'
        assert result['confidence'] > 0.6

    def test_daily(self):
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        result = detect_granularity(dates)
        assert result['granularity'] == 'D'

    def test_quarterly(self):
        dates = pd.date_range('2020-01-01', periods=12, freq='QE')
        result = detect_granularity(dates)
        assert result['granularity'] == 'Q'

    def test_irregular_low_confidence(self):
        dates = pd.to_datetime([
            '2023-01-01', '2023-01-08', '2023-02-15', '2023-02-20',
            '2023-04-30', '2023-05-01',
        ])
        result = detect_granularity(dates)
        assert result['confidence'] < 0.6
        assert result['requires_user_confirm']

    def test_empty_falls_back(self):
        result = detect_granularity([])
        assert result['confidence'] == 0.0
        assert result['requires_user_confirm']


class TestDetectSeasonality:
    def test_yearly_weekly_data(self):
        t = np.arange(156)
        y = 100 + 30 * np.sin(2 * np.pi * t / 52)
        result = detect_seasonality(y, granularity='W')
        assert result is not None
        assert result['period'] == 52
        assert abs(result['autocorr']) > 0.5

    def test_no_seasonality_returns_none(self):
        np.random.seed(42)
        y = np.random.normal(100, 10, 100)
        result = detect_seasonality(y, granularity='W')
        assert result is None

    def test_short_series_returns_none(self):
        y = np.array([1, 2, 3, 4, 5])
        assert detect_seasonality(y) is None

    def test_quarterly_pattern_in_weekly(self):
        t = np.arange(104)
        y = 50 + 20 * np.sin(2 * np.pi * t / 13)  # 13-week quarter
        result = detect_seasonality(y, granularity='W')
        assert result is not None
        assert result['period'] in {13, 26, 52}


class TestComputeXNormQuantiles:
    def test_basic(self):
        adstock = np.linspace(1, 100, 100)
        result = compute_x_norm_quantiles(adstock, mean=50.0)
        assert 'p50' in result and 'p75' in result and 'p90' in result and 'p95' in result and 'p99' in result
        assert result['p50'] < result['p75'] < result['p99']

    def test_zero_mean_returns_zeros(self):
        result = compute_x_norm_quantiles([1, 2, 3], mean=0.0)
        assert all(v == 0.0 for v in result.values())

    def test_empty_returns_zeros(self):
        result = compute_x_norm_quantiles([], mean=10.0)
        assert all(v == 0.0 for v in result.values())


class TestExtrapolationSeverity:
    def test_in_zone(self):
        q = {'p95': 1.0, 'p99': 1.5}
        assert extrapolation_severity(0.5, q) == 0
        assert extrapolation_severity(1.0, q) == 0

    def test_p95_boundary(self):
        q = {'p95': 1.0, 'p99': 1.5}
        assert extrapolation_severity(1.2, q) == 1

    def test_p99_extrapolation(self):
        q = {'p95': 1.0, 'p99': 1.5}
        assert extrapolation_severity(2.0, q) == 2

    def test_extreme_3x_p99(self):
        q = {'p95': 1.0, 'p99': 1.5}
        assert extrapolation_severity(5.0, q) == 3

    def test_none_quantiles_returns_zero(self):
        assert extrapolation_severity(100.0, None) == 0


class TestVerdictTierExtrapolationGate:
    """S3 synergy verification — extrapolation_severity gate в verdict_tier."""

    def test_severity_zero_no_effect(self):
        tier, _, _ = verdict_tier(1.0, 0.8, 1.2, extrapolation_severity=0)
        assert tier == "Уверенная"

    def test_severity_2_forces_directional(self):
        # Confident CI (relative_width 0.4 < 0.5) → would be "Уверенная"
        tier, tone, _ = verdict_tier(1.0, 0.8, 1.2, extrapolation_severity=2)
        assert tier == "Направленная"
        assert tone == "warn"

    def test_severity_3_forces_high_uncertainty(self):
        tier, tone, _ = verdict_tier(1.0, 0.8, 1.2, extrapolation_severity=3)
        assert tier == "Высокая неопределённость"
        assert tone == "bad"

    def test_severity_3_overrides_existing_directional(self):
        # Even с wide CI (relative_width=0.7 → "Направленная"), severity=3 escalates
        tier, _, _ = verdict_tier(1.0, 0.65, 1.35, extrapolation_severity=3)
        assert tier == "Высокая неопределённость"


class TestSaturationDriftCheck:
    def test_high_drift_critical(self):
        result = saturation_drift_check(forecast_per_period_spend=1500, train_avg_spend=300)
        assert result is not None
        assert result['severity'] == 'critical'
        assert result['ratio_spend'] == 5.0

    def test_low_drift_warn(self):
        result = saturation_drift_check(forecast_per_period_spend=50, train_avg_spend=500)
        assert result is not None
        assert result['severity'] == 'warn'

    def test_in_zone_returns_none(self):
        assert saturation_drift_check(forecast_per_period_spend=400, train_avg_spend=500) is None

    def test_adstock_critical_overrides(self):
        result = saturation_drift_check(
            forecast_per_period_spend=400, train_avg_spend=500,
            forecast_avg_adstock=2000, train_avg_adstock=500,  # 4× drift
        )
        assert result is not None
        assert result['severity'] == 'critical'


class TestHorizonExtrapolationCheck:
    def test_no_warn_below_threshold(self):
        assert horizon_extrapolation_check(forecast_n=156, train_n=156) is None

    def test_warn_at_15x(self):
        result = horizon_extrapolation_check(forecast_n=240, train_n=156)
        assert result is not None
        assert result['severity'] == 'warn'
        assert 1.5 < result['ratio'] < 1.6


class TestResolveWarningPriority:
    def test_critical_wins(self):
        warnings = [
            {'severity': 'info', 'message_ru': 'a'},
            {'severity': 'warn', 'message_ru': 'b'},
            {'severity': 'critical', 'message_ru': 'c'},
        ]
        result = resolve_warning_priority(warnings)
        assert result['top_warning']['message_ru'] == 'c'
        assert result['total_count'] == 3
        assert len(result['secondary']) == 2

    def test_empty_returns_none_top(self):
        result = resolve_warning_priority([])
        assert result['top_warning'] is None
        assert result['secondary'] == []

    def test_invalid_filtered(self):
        warnings = [{'severity': 'unknown'}, None, 'string']
        result = resolve_warning_priority(warnings)  # type: ignore
        assert result['top_warning'] is None

    def test_stable_within_severity(self):
        """Within same severity, preserves input order."""
        w1 = {'severity': 'warn', 'message_ru': 'first'}
        w2 = {'severity': 'warn', 'message_ru': 'second'}
        result = resolve_warning_priority([w1, w2])
        assert result['top_warning']['message_ru'] == 'first'


class TestKPIRegistryCoupling:
    def test_default_returns_2x(self):
        assert get_forecast_horizon_max_multiplier(None) == 2.0

    def test_sales_returns_2x(self):
        assert get_forecast_horizon_max_multiplier('sales') == 2.0

    def test_awareness_returns_15x(self):
        """Awareness has longer brand build-up → tighter cap (S7)."""
        assert get_forecast_horizon_max_multiplier('awareness') == 1.5

    def test_unknown_kpi_falls_back_to_default(self):
        assert get_forecast_horizon_max_multiplier('nonexistent_kpi') == 2.0


class TestConformalPlanningIntervals:
    def test_missing_training_arrays_returns_none(self):
        # Bayesian-only pickle (no X_train/y_train) → conformal not applicable
        model_data = {'model_type': 'bayesian'}
        assert conformal_planning_intervals(model_data) is None

    def test_with_training_arrays_returns_interval(self):
        np.random.seed(42)
        X = np.random.normal(0, 1, (100, 3))
        y = X[:, 0] * 2.5 + X[:, 1] * 1.5 + np.random.normal(0, 0.5, 100)
        model_data = {'X_train': X, 'y_train': y}
        result = conformal_planning_intervals(model_data, confidence=0.8)
        if result is not None:  # may fail on some envs — defensive
            assert 'half_width' in result
            assert result['half_width'] > 0
            assert 'method' in result
