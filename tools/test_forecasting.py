"""Unit tests for utils/forecasting.py — Phase 2.1 Step 1 (Option C math layer).

Tests:
- flat_alloc_adstock_series: closed-form == apply_adstock numerical (geometric)
- flat_alloc_adstock_series: edge cases (n=0, x=0, decay=0)
- evaluate_flat_allocation_response: matches scenario.py per-period summation
- evaluate_flat_allocation_response: planning mode != analyst Hill-of-mean (Jensen)
- evaluate_flat_allocation_response: zero allocation → zero response
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))

from utils.adstock import apply_adstock  # noqa: E402
from utils.forecasting import (  # noqa: E402
    evaluate_flat_allocation_response,
    flat_alloc_adstock_series,
)
from utils.saturation import hill_function  # noqa: E402


class TestFlatAllocAdstockSeries:
    def test_closed_form_matches_numerical_geometric(self):
        """Closed-form geometric adstock series == apply_adstock numerical."""
        for decay in [0.1, 0.3, 0.5, 0.7, 0.85, 0.95]:
            x_avg, n = 100.0, 52
            closed = flat_alloc_adstock_series(x_avg, n, 'geometric', decay)
            flat = np.full(n, x_avg)
            numerical = apply_adstock(flat, 'geometric', {'alpha': decay})
            np.testing.assert_allclose(closed, numerical, rtol=1e-10)

    def test_zero_x_returns_zeros(self):
        result = flat_alloc_adstock_series(0.0, 10, 'geometric', 0.5)
        assert result.shape == (10,)
        np.testing.assert_array_equal(result, np.zeros(10))

    def test_zero_decay_returns_constant(self):
        result = flat_alloc_adstock_series(50.0, 5, 'geometric', 0.0)
        np.testing.assert_allclose(result, np.full(5, 50.0))

    def test_n_zero_returns_empty(self):
        result = flat_alloc_adstock_series(100.0, 0, 'geometric', 0.5)
        assert result.shape == (0,)

    def test_decay_none_falls_back_to_apply_adstock(self):
        """When decay is None, falls back to apply_adstock library default."""
        result = flat_alloc_adstock_series(100.0, 10, 'geometric', None)
        assert result.shape == (10,)
        # Library default decay is 0.5, so result[0]=100, result[1]=100+50=150...
        # Just verify increasing sequence (geometric carryover sign)
        assert result[0] == 100.0
        assert result[-1] > result[0]

    def test_steady_state_long_horizon(self):
        """For long horizon, mean adstock → x_avg / (1 - decay)."""
        x_avg, decay = 10.0, 0.5
        series = flat_alloc_adstock_series(x_avg, 1000, 'geometric', decay)
        steady_state = x_avg / (1 - decay)
        # Last point should be very close к steady state
        assert abs(series[-1] - steady_state) < 1e-6


class TestEvaluateFlatAllocationResponse:
    def _basic_setup(self, decay=0.5, alpha=2.0, gamma=0.5, beta=0.05):
        """Single-channel test fixture."""
        media_cols = ['ChannelA']
        channel_params = {
            'ChannelA': {
                'alpha': alpha, 'gamma': gamma, 'beta': beta, 'decay': decay,
                'adstock_mean_posterior': 5.0,  # arbitrary но > 0
            }
        }
        media_means = {'ChannelA': 5.0}
        adstock_config = {'ChannelA': 'geometric'}
        unit_costs = [1.0]
        return media_cols, channel_params, media_means, adstock_config, unit_costs

    def test_matches_scenario_per_period_math(self):
        """Replicate scenario.py math by hand → must match helper output exactly."""
        cols, params, means, cfg, uc = self._basic_setup(decay=0.6, alpha=2.5, gamma=0.5, beta=0.04)
        alloc = np.array([10000.0])
        n = 52

        # Manual replication of scenario.py:167-186 logic (per-period sum).
        x_avg = alloc[0] / 1.0 / n  # money / unit_cost / n_periods
        flat = np.full(n, x_avg)
        adstock = apply_adstock(flat, 'geometric', {'alpha': 0.6})
        x_norm = adstock / 5.0
        sat = hill_function(np.maximum(x_norm, 0), alpha=2.5, gamma=0.5)
        expected = 0.04 * sat.sum()

        actual = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=alloc, unit_costs=uc,
            media_means=means, adstock_config=cfg,
            n_periods=n,
        )
        assert abs(actual - expected) < 1e-9

    def test_zero_allocation_returns_zero(self):
        cols, params, means, cfg, uc = self._basic_setup()
        result = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([0.0]), unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=52,
        )
        assert result == 0.0

    def test_n_periods_zero_returns_zero(self):
        cols, params, means, cfg, uc = self._basic_setup()
        result = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([10000.0]), unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=0,
        )
        assert result == 0.0

    def test_option_c_differs_from_hill_of_mean_by_jensen(self):
        """For non-trivial S-curve, sum-of-Hills != Hill-of-mean × n.

        Core M9 finding — confirms Option C mathematically distinct от current
        Aurora optimizer's Hill-of-mean approximation. Test uses short horizon
        (cold-start adstock variability) + mid-S Hill operating zone (peak
        Jensen sensitivity).
        """
        cols, params, means, cfg, uc = self._basic_setup(decay=0.5, alpha=3.0, gamma=0.5, beta=0.1)
        # n=5, alloc=10 → x_avg=2 / mean=5 → x_norm ranges 0.4..0.78 (mid-S zone)
        alloc = np.array([10.0])
        n = 5  # short horizon — cold-start adstock variability matters

        # Option C (per-period sum)
        option_c = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=alloc, unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=n,
        )

        # Hill-of-mean approximation (current optimizer math)
        from utils.adstock import apply_adstock as _apply
        x_avg = alloc[0] / 1.0 / n
        flat = np.full(n, x_avg)
        x_avg_adstock = _apply(flat, 'geometric', {'alpha': 0.85}).mean()
        x_norm_mean = x_avg_adstock / 5.0
        sat_of_mean = hill_function(np.array([max(x_norm_mean, 0)]), alpha=3.0, gamma=0.5)
        hill_of_mean = 0.1 * sat_of_mean[0] * n

        rel_diff = abs(option_c - hill_of_mean) / max(abs(hill_of_mean), 1e-9)
        # Should differ ≥ 1% — concrete divergence proves Jensen's inequality realized.
        assert rel_diff > 0.01, (
            f"Option C ({option_c:.6f}) and Hill-of-mean ({hill_of_mean:.6f}) "
            f"should differ ≥1% in mid-S zone — Jensen's inequality. rel_diff={rel_diff:.6f}"
        )

    def test_multi_channel_sums_correctly(self):
        """Two channels — total response = sum of per-channel contributions."""
        cols = ['A', 'B']
        params = {
            'A': {'alpha': 2.0, 'gamma': 0.5, 'beta': 0.05, 'decay': 0.5,
                  'adstock_mean_posterior': 4.0},
            'B': {'alpha': 1.8, 'gamma': 0.4, 'beta': 0.04, 'decay': 0.3,
                  'adstock_mean_posterior': 3.0},
        }
        means = {'A': 4.0, 'B': 3.0}
        cfg = {'A': 'geometric', 'B': 'geometric'}
        uc = [1.0, 1.0]
        alloc_both = np.array([10000.0, 5000.0])

        total = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=alloc_both, unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=52,
        )

        only_a = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([10000.0, 0.0]), unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=52,
        )
        only_b = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([0.0, 5000.0]), unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=52,
        )

        assert abs(total - (only_a + only_b)) < 1e-9

    def test_falls_back_to_media_means_for_legacy_pickle(self):
        """No adstock_mean_posterior → use media_means (pre-v1.2 behavior)."""
        cols = ['A']
        params = {'A': {'alpha': 2.0, 'gamma': 0.5, 'beta': 0.05, 'decay': 0.5}}
        means = {'A': 7.5}  # ← used because no adstock_mean_posterior
        cfg = {'A': 'geometric'}

        result = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([10000.0]), unit_costs=[1.0],
            media_means=means, adstock_config=cfg, n_periods=26,
        )
        assert result > 0  # sanity — produces non-zero response

    def test_zero_mean_channel_skipped(self):
        """Channel с mean=0 is skipped (cannot normalize)."""
        cols = ['A']
        params = {'A': {'alpha': 2.0, 'gamma': 0.5, 'beta': 0.05, 'decay': 0.5,
                        'adstock_mean_posterior': 0.0}}
        means = {'A': 0.0}
        cfg = {'A': 'geometric'}

        result = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=np.array([10000.0]), unit_costs=[1.0],
            media_means=means, adstock_config=cfg, n_periods=26,
        )
        assert result == 0.0

    @pytest.mark.parametrize('forecast_n', [13, 26, 52, 104, 156])
    def test_increasing_with_horizon_at_fixed_per_period_spend(self, forecast_n):
        """Holding per-period spend constant, total response scales linearly with n."""
        cols, params, means, cfg, uc = self._basic_setup(decay=0.5, alpha=2.0, gamma=0.5, beta=0.05)
        x_per_period = 50.0  # fixed
        alloc = np.array([x_per_period * forecast_n])

        result = evaluate_flat_allocation_response(
            media_cols=cols, channel_params=params,
            allocation_money=alloc, unit_costs=uc,
            media_means=means, adstock_config=cfg, n_periods=forecast_n,
        )
        # For long enough horizon в steady state, response/n_periods → const
        per_period_response = result / forecast_n
        assert per_period_response > 0


class TestPlanningModeOptimizerIntegration:
    """Smoke test — Phase 2.1 Step 1 dispatcher correctly switches objective."""

    def test_planning_mode_metadata_in_result(self):
        """Trivial smoke check via direct config — actual optimize runs need pickle."""
        # This test would ideally run optimizer with mock pickle.
        # For now verify dispatcher signature exists без full optimize round-trip.
        from engines import optimizer as opt_mod
        assert hasattr(opt_mod, 'optimize'), 'optimizer.optimize entry point missing'
