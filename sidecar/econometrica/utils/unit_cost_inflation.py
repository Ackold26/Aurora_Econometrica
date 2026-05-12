"""Per-channel inflation-aware unit cost helpers (Phase 2 audit pass 4 cont).

Customer requirement (Антон 2026-05-02): при денежной оценке медиа за training
period длиной несколько лет, годовая инфляция CPP/CPM (25-30% по РФ) меняет
"настоящую" стоимость единицы существенно. Single scalar unit_cost для всего
training horizon усредняет неправильно (geometric mean assumed, не accounting
для spend distribution).

Approach (option C per Антон): customer enters
  - current_cost: ₽ за единицу в latest training year (последняя точка данных)
  - annual_inflation_pct: годовой темп роста CPP/CPM (e.g. 25)

Aurora computes training-period weighted average:
  per_year_cost[y] = current_cost / (1 + rate)^(latest_year - y)
  weight[y]        = raw_spend_in_year[y] / total_raw_spend
  effective_avg    = Σ per_year_cost[y] × weight[y]

Decomposer / Scenario / Optimizer use effective_avg как единый scalar unit_cost
(API-compatible). Math correctness improvement: ROI/mROAS отражает реальные
training prices, не market price today extrapolated к past.

Forecast (planning mode): customer applies forecast inflation в Block D
(separate from training inflation). Уже существующая logic.

Backward compat:
- annual_inflation_pct = 0 OR None → effective_avg = current_cost (identical
  к pre-Phase-2-audit-pass-4 behavior)
- Legacy projects без inflation_pct field → treated as 0 → no math change
"""
from __future__ import annotations

import logging

logger = logging.getLogger('econometrica')


def compute_inflation_weighted_avg_cost(
    current_cost: float,
    inflation_pct: float | None,
    training_dates,  # array-like of datetime-ish
    raw_spend_per_period,  # array-like of floats
) -> float:
    """Effective training-period unit cost, weighted by spend share per year.

    Args:
        current_cost: ₽ за юнит в latest training year (or current market).
        inflation_pct: годовой темп роста (e.g. 25.0 for 25%/year). None / 0 →
            no adjustment, returns current_cost.
        training_dates: per-period date column от training data.
        raw_spend_per_period: per-period raw spend (native units), aligned к dates.

    Returns:
        Effective unit_cost (scalar) representing weighted average training
        period cost. Falls back к current_cost on any error or degenerate input.
    """
    if current_cost is None or current_cost <= 0:
        return float(current_cost or 0.0)
    if inflation_pct is None or abs(float(inflation_pct)) < 1e-9:
        return float(current_cost)

    try:
        import numpy as np
        import pandas as pd
        rate = float(inflation_pct) / 100.0
        dates = pd.to_datetime(pd.Series(training_dates), errors='coerce')
        spend = np.asarray(raw_spend_per_period, dtype=float)
        if len(dates) == 0 or len(spend) == 0:
            return float(current_cost)
        if len(dates) != len(spend):
            # Defensive - date/spend misalignment → fallback
            return float(current_cost)
        # pd.Series → .dt accessor; pd.DatetimeIndex → no .dt needed.
        years = dates.dt.year if hasattr(dates, 'dt') else pd.Series(dates).dt.year
        valid = years.notna() & np.isfinite(spend) & (spend >= 0)
        if not valid.any():
            return float(current_cost)
        years = years[valid].astype(int)
        spend = spend[valid.values]
        latest_year = int(years.max())
        df = pd.DataFrame({'year': years.values, 'spend': spend})
        by_year = df.groupby('year')['spend'].sum()
        total = float(by_year.sum())
        if total <= 1e-9:
            return float(current_cost)
        weighted = 0.0
        for year, year_spend in by_year.items():
            year_offset = latest_year - int(year)
            year_cost = float(current_cost) / ((1.0 + rate) ** year_offset)
            weight = float(year_spend) / total
            weighted += year_cost * weight
        return float(weighted)
    except Exception as exc:
        logger.warning(
            f"compute_inflation_weighted_avg_cost failed: {exc}. "
            f"Fallback к current_cost={current_cost} (no inflation adjustment)."
        )
        return float(current_cost)


def apply_inflation_to_unit_costs(
    unit_costs: dict[str, float],
    inflation_pct_per_channel: dict[str, float] | None,
    df,  # pandas DataFrame с date column + media columns
    date_column: str,
) -> dict[str, float]:
    """Apply per-channel inflation к unit_costs map → returns adjusted map.

    Customer entered current_cost; result is training-weighted-average suitable
    для decomposer/optimizer/scenario money conversion.

    Args:
        unit_costs: {channel: current_cost_₽}
        inflation_pct_per_channel: {channel: annual_pct} or None for no adjustment.
        df: training DataFrame (already loaded, with merge_rules applied).
        date_column: name of date column in df.

    Returns:
        Adjusted unit_costs map. Channels без inflation_pct → unchanged.
        Channels с unit_cost = 1.0 (money channels) → unchanged.
    """
    if not inflation_pct_per_channel:
        return dict(unit_costs)
    if date_column not in df.columns:
        return dict(unit_costs)
    out = {}
    dates = df[date_column]
    for channel, cost in unit_costs.items():
        if cost is None or cost <= 0 or cost == 1.0:
            # Money channels (uc=1.0) - inflation irrelevant. Skip adjustment.
            out[channel] = cost
            continue
        rate = inflation_pct_per_channel.get(channel)
        if rate is None or abs(float(rate)) < 1e-9:
            out[channel] = cost
            continue
        if channel not in df.columns:
            out[channel] = cost
            continue
        raw_spend = df[channel].fillna(0).values.astype(float)
        out[channel] = compute_inflation_weighted_avg_cost(
            current_cost=cost,
            inflation_pct=rate,
            training_dates=dates,
            raw_spend_per_period=raw_spend,
        )
    return out
