"""Forecast horizon math helpers for Planning Mode (Phase 2).

Single source of truth для per-period Hill summation matching scenario engine.
Used by optimizer.py total_response_money_planning (planning mode objective).

Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis (M9 finding —
Hill-of-mean vs sum-of-Hills, Option C lock).

3-way alignment в planning mode:
- scenario.py:167-186 — per-period sum-of-Hill (existing)
- decomposer.py:289-292 — per-period sum-of-Hill (existing)
- optimizer.py planning mode → calls evaluate_flat_allocation_response() — joins alignment
- optimizer.py analyst mode → preserves Hill-of-mean approximation для backward compat
"""
from __future__ import annotations

import numpy as np

from utils.adstock import apply_adstock
from utils.saturation import hill_function


def flat_alloc_adstock_series(
    x_avg: float,
    n_periods: int,
    a_type: str,
    decay: float | None = None,
) -> np.ndarray:
    """Adstock series under flat allocation x_t = x_avg for n_periods.

    Closed-form fast path for geometric adstock (avoids Python for-loop in
    apply_adstock). Falls back к generic apply_adstock for non-geometric types.

    For geometric с decay θ ∈ [0, 1):
        adstock_t = x_avg × (1 - θ^(t+1)) / (1 - θ)

    Args:
        x_avg: per-period spend (constant over n_periods)
        n_periods: forecast horizon length
        a_type: 'geometric', 'weibull', 'noop'
        decay: posterior mean decay — None falls back to library default

    Returns:
        np.ndarray shape (n_periods,) of adstocked values.
    """
    if n_periods < 1:
        return np.array([], dtype=np.float64)
    if x_avg <= 0:
        return np.zeros(n_periods, dtype=np.float64)

    if a_type == 'geometric' and decay is not None:
        d = float(decay)
        if d < 1e-9:
            return np.full(n_periods, float(x_avg))
        if 0 < d < 1:
            t = np.arange(n_periods)
            return float(x_avg) * (1.0 - d ** (t + 1)) / (1.0 - d)
        # decay ≥ 1 — clamp via apply_adstock fallback (it handles edge cases)

    # Fallback: numerical via apply_adstock
    flat = np.full(n_periods, float(x_avg))
    params = {'alpha': float(decay)} if decay is not None else None
    return apply_adstock(flat, a_type, params)


def _adstock_type_for(adstock_config: dict, col: str) -> str:
    """Resolve adstock type from per-channel config (matches optimizer.py:337-343)."""
    raw = (adstock_config or {}).get(col)
    if isinstance(raw, dict):
        return raw.get('type', 'geometric')
    if isinstance(raw, str):
        return raw
    return 'geometric'


def evaluate_flat_allocation_response(
    *,
    media_cols: list[str],
    channel_params: dict[str, dict],
    allocation_money,  # array-like shape (n_channels,) money axis
    unit_costs: list[float] | np.ndarray,
    media_means: dict[str, float],
    adstock_config: dict | None = None,
    n_periods: int,
) -> float:
    """Total media response под flat allocation (Option C — sum-of-Hills).

    Per-period summation matching `scenario.py:167-186` semantics. Restores
    3-way alignment optimizer ↔ scenario ↔ decomposer в planning mode.

    Math:
        for each channel i:
            x_avg = (allocation_money[i] / unit_cost[i]) / n_periods
            adstock_t = adstock_kernel(x_avg, t)        # per-period
            x_norm_t = adstock_t / mean_train_posterior
            sat_t = hill(x_norm_t, alpha, gamma)        # per-period
            total += beta_i × sum(sat_t)                # sum, not Hill(mean)×n

    Args:
        media_cols: ordered channel names aligned к allocation_money + unit_costs
        channel_params: per-channel dict {'alpha', 'gamma', 'beta', 'decay',
                       optionally 'adstock_mean_posterior'}
        allocation_money: per-channel total spend (₽) — money axis
        unit_costs: per-channel unit cost (₽/native unit) aligned to media_cols
        media_means: per-channel training adstock mean (fallback когда нет
                    posterior — pre-v1.2 pickles)
        adstock_config: per-channel adstock type config ({col: 'geometric'|...})
        n_periods: forecast horizon length

    Returns:
        Total media response (y_norm scale). Caller multiplies by y_std для KPI scale.
        Always non-negative (zero when allocation_money is all zeros).
    """
    if n_periods < 1:
        return 0.0

    alloc = np.asarray(allocation_money, dtype=np.float64)
    uc_arr = np.asarray(unit_costs, dtype=np.float64)
    cfg = adstock_config or {}

    total = 0.0
    for i, col in enumerate(media_cols):
        p = channel_params.get(col)
        if p is None:
            continue

        mean_posterior = p.get('adstock_mean_posterior')
        if mean_posterior is not None:
            mean = float(mean_posterior)
        else:
            mean = float(media_means.get(col, 1) or 1)
        if mean <= 0:
            continue  # zero-mean channel — cannot normalize

        uc = float(uc_arr[i]) if i < len(uc_arr) else 1.0
        if uc <= 0:
            uc = 1e-10

        x_native_total = float(alloc[i]) / uc
        x_avg_raw = x_native_total / n_periods
        if x_avg_raw <= 0:
            continue

        a_type = _adstock_type_for(cfg, col)
        decay = p.get('decay')

        adstock_series = flat_alloc_adstock_series(x_avg_raw, n_periods, a_type, decay)
        x_norm_series = adstock_series / mean
        sat_series = hill_function(
            np.maximum(x_norm_series, 0.0),
            alpha=float(p['alpha']),
            gamma=max(float(p['gamma']), 1e-6),
        )
        total += float(p['beta']) * float(sat_series.sum())

    return total
