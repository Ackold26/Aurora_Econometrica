"""Phase 2 audit pass 4 - per-channel unit cost inflation tests.

Customer enters current_cost (latest training year) + annual_inflation_pct.
Backend computes weighted-average over training period via inflation rollback.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'sidecar' / 'econometrica'))

from utils.unit_cost_inflation import (  # noqa: E402
    apply_inflation_to_unit_costs,
    compute_inflation_weighted_avg_cost,
)


class TestComputeInflationWeightedAvgCost:
    def test_zero_inflation_returns_current(self):
        dates = pd.date_range('2023-01-01', periods=104, freq='W')
        spend = np.full(104, 1000.0)
        result = compute_inflation_weighted_avg_cost(150_000, 0, dates, spend)
        assert result == 150_000

    def test_none_inflation_returns_current(self):
        dates = pd.date_range('2023-01-01', periods=104, freq='W')
        spend = np.full(104, 1000.0)
        result = compute_inflation_weighted_avg_cost(150_000, None, dates, spend)
        assert result == 150_000

    def test_single_year_returns_current(self):
        # Single year training → no rollback applies → current cost.
        dates = pd.date_range('2025-01-01', periods=52, freq='W')
        spend = np.full(52, 1000.0)
        result = compute_inflation_weighted_avg_cost(150_000, 25, dates, spend)
        assert abs(result - 150_000) < 1e-6

    def test_two_year_uniform_spend(self):
        """2-year training, uniform spend distribution, 25% inflation.

        2024 cost = 150k / 1.25 = 120k.
        2025 cost = 150k.
        Weighted average (50/50) = (120k + 150k) / 2 = 135k.
        """
        dates = pd.concat([
            pd.Series(pd.date_range('2024-01-01', periods=52, freq='W')),
            pd.Series(pd.date_range('2025-01-01', periods=52, freq='W')),
        ], ignore_index=True)
        spend = np.full(104, 1000.0)
        result = compute_inflation_weighted_avg_cost(150_000, 25, dates, spend)
        expected = (120_000 + 150_000) / 2
        assert abs(result - expected) < 1.0

    def test_three_year_proportional(self):
        """3-year training с разной spend distribution. 30% inflation.

        2023 cost = 150k / 1.3² ≈ 88_757.
        2024 cost = 150k / 1.3 ≈ 115_385.
        2025 cost = 150k.
        Spend: 50% in 2023, 30% in 2024, 20% in 2025.
        Weighted = 0.5×88757 + 0.3×115385 + 0.2×150000 ≈ 109_000.
        """
        dates_a = pd.date_range('2023-01-01', periods=52, freq='W')
        dates_b = pd.date_range('2024-01-01', periods=52, freq='W')
        dates_c = pd.date_range('2025-01-01', periods=52, freq='W')
        dates = pd.concat([pd.Series(dates_a), pd.Series(dates_b), pd.Series(dates_c)], ignore_index=True)
        spend = np.concatenate([
            np.full(52, 5000.0),  # 2023 (10× weight per period)
            np.full(52, 3000.0),  # 2024 (6×)
            np.full(52, 2000.0),  # 2025 (4×)
        ])
        result = compute_inflation_weighted_avg_cost(150_000, 30, dates, spend)
        # Expected ~ 0.5×88757 + 0.3×115385 + 0.2×150000
        expected = 0.5 * (150_000 / 1.3 ** 2) + 0.3 * (150_000 / 1.3) + 0.2 * 150_000
        assert abs(result - expected) < 100  # ₽1 accuracy

    def test_inflation_lower_than_current(self):
        """Verify training cost is BELOW current cost (inflation rolls back)."""
        dates = pd.concat([
            pd.Series(pd.date_range('2023-01-01', periods=52, freq='W')),
            pd.Series(pd.date_range('2024-01-01', periods=52, freq='W')),
            pd.Series(pd.date_range('2025-01-01', periods=52, freq='W')),
        ], ignore_index=True)
        spend = np.full(156, 1000.0)
        result = compute_inflation_weighted_avg_cost(200_000, 25, dates, spend)
        assert result < 200_000  # weighted average is LESS than latest year cost
        assert result > 100_000  # but not absurdly low

    def test_invalid_dates_returns_current(self):
        result = compute_inflation_weighted_avg_cost(150_000, 25, [None, None], [100, 200])
        assert result == 150_000

    def test_zero_spend_returns_current(self):
        dates = pd.date_range('2023-01-01', periods=104, freq='W')
        spend = np.zeros(104)
        result = compute_inflation_weighted_avg_cost(150_000, 25, dates, spend)
        assert result == 150_000


class TestApplyInflationToUnitCosts:
    def _make_df(self, years_periods: list[tuple[int, int]]):
        """Build df with date column spanning given years."""
        dfs = []
        for year, n in years_periods:
            start = f'{year}-01-01'
            d = pd.date_range(start, periods=n, freq='W')
            dfs.append(pd.DataFrame({
                'date': d,
                'TV': [1000.0] * n,
                'OLV': [500.0] * n,
                'sales': [100.0] * n,
            }))
        return pd.concat(dfs, ignore_index=True)

    def test_no_inflation_passthrough(self):
        df = self._make_df([(2024, 52), (2025, 52)])
        unit_costs = {'TV': 150_000, 'OLV': 200}
        result = apply_inflation_to_unit_costs(unit_costs, None, df, 'date')
        assert result == unit_costs

    def test_empty_inflation_dict_passthrough(self):
        df = self._make_df([(2024, 52), (2025, 52)])
        unit_costs = {'TV': 150_000, 'OLV': 200}
        result = apply_inflation_to_unit_costs(unit_costs, {}, df, 'date')
        # Empty dict → current branch returns dict(unit_costs) unchanged
        assert result == unit_costs

    def test_partial_inflation_only_specified_channels(self):
        df = self._make_df([(2024, 52), (2025, 52)])
        unit_costs = {'TV': 150_000, 'OLV': 200}
        infl = {'TV': 25}  # only TV has inflation
        result = apply_inflation_to_unit_costs(unit_costs, infl, df, 'date')
        assert result['TV'] < 150_000  # adjusted
        assert result['OLV'] == 200    # unchanged

    def test_money_channel_uc_1_unchanged(self):
        """Money channels (uc=1.0) are not inflation-adjusted."""
        df = self._make_df([(2024, 52), (2025, 52)])
        unit_costs = {'TV': 150_000, 'Search': 1.0}  # Search в рублях
        infl = {'TV': 25, 'Search': 25}  # even с inflation specified
        result = apply_inflation_to_unit_costs(unit_costs, infl, df, 'date')
        assert result['TV'] < 150_000     # adjusted
        assert result['Search'] == 1.0    # money channel unchanged

    def test_missing_date_column_returns_unchanged(self):
        df = pd.DataFrame({'TV': [1000.0] * 52, 'sales': [100.0] * 52})
        result = apply_inflation_to_unit_costs(
            {'TV': 150_000}, {'TV': 25}, df, 'date',
        )
        assert result == {'TV': 150_000}

    def test_zero_inflation_in_dict_returns_current(self):
        df = self._make_df([(2024, 52), (2025, 52)])
        unit_costs = {'TV': 150_000}
        result = apply_inflation_to_unit_costs(unit_costs, {'TV': 0}, df, 'date')
        assert result['TV'] == 150_000
