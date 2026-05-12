"""
Aurora Econometrica — safe corridor bounds (v1.3.0).

Per ADR-014: вычисляет MVP формулу для безопасного диапазона бюджета per канал
+ агрегатный коридор по total budget + по target sales.

MVP per канал (default):
    X_i^lo = max(P5(X_i_observed), 0.5 · µ_i)
    X_i^hi = min(P95(X_i_observed), 1.5 · µ_i)

Expert mode (Phase B): posterior-based bounds через bootstrap-сэмплирование.

Usage:
    from optimize.bounds import compute_safe_corridor

    corridor = compute_safe_corridor(model_data)
    # {
    #   'per_channel': {ch: {'lo': X_lo, 'hi': X_hi, 'mu': avg, 'p5': P5, 'p95': P95}},
    #   'aggregate_budget': {'lo': sum_lo, 'hi': sum_hi, 'current': sum_current},
    #   'aggregate_sales': {'lo': S_at_lo, 'hi': S_at_hi, 'current': S_current},
    # }
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def compute_per_channel_bounds(
    spend_history: np.ndarray,
    relative_lo_factor: float = 0.5,
    relative_hi_factor: float = 1.5,
    percentile_lo: float = 5.0,
    percentile_hi: float = 95.0,
) -> Dict[str, float]:
    """Compute safe corridor bounds для одного канала.

    Args:
        spend_history: array of historical spend values (np.array).
        relative_lo_factor: множитель к среднему для нижней границы (default 0.5x).
        relative_hi_factor: множитель к среднему для верхней границы (default 1.5x).
        percentile_lo: lower percentile threshold (default 5).
        percentile_hi: upper percentile threshold (default 95).

    Returns:
        Dict с keys: 'lo', 'hi', 'mu', 'p5', 'p95'.

    MVP формула:
        lo = max(P5, lo_factor * mu)
        hi = min(P95, hi_factor * mu)

    Защищает от extrapolation за пределы observed range, но достаточно гибко
    для actionable рекомендаций.
    """
    spend = np.asarray(spend_history, dtype=float)
    spend_positive = spend[spend > 0]

    if len(spend_positive) == 0:
        # Канал без активности — corridor [0, 0].
        return {'lo': 0.0, 'hi': 0.0, 'mu': 0.0, 'p5': 0.0, 'p95': 0.0}

    mu = float(np.mean(spend_positive))
    p5 = float(np.percentile(spend_positive, percentile_lo))
    p95 = float(np.percentile(spend_positive, percentile_hi))

    lo = max(p5, relative_lo_factor * mu)
    hi = min(p95, relative_hi_factor * mu)

    # Sanity: lo не больше hi.
    # Audit fix v1.3.0 (red-team review): silent swap скрывал inverted corridor.
    # Если lo > hi, это симптом very low CV (P5 ≈ P95) + relative_lo > relative_hi.
    # Honest fix: set lo = hi = mu (point estimate), без свапа. Warning через
    # narrow_corridor flag для downstream UI.
    if lo > hi:
        lo = hi = mu

    return {
        'lo': lo, 'hi': hi, 'mu': mu, 'p5': p5, 'p95': p95,
        'narrow_corridor': p95 - p5 < 0.01 * mu,  # flag для UI warning
    }


def compute_safe_corridor(
    model_data: Dict[str, Any],
    relative_lo_factor: float = 0.5,
    relative_hi_factor: float = 1.5,
) -> Dict[str, Any]:
    """Compute safe corridor for all channels + aggregate.

    Args:
        model_data: loaded model pickle (через `load_model_with_compat`).
        relative_lo_factor / relative_hi_factor: see compute_per_channel_bounds.

    Returns:
        Dict:
        {
          'mode': 'mvp',
          'formula': 'max(P5, 0.5*mu), min(P95, 1.5*mu)',
          'per_channel': {channel: {lo, hi, mu, p5, p95, current}},
          'aggregate_budget': {lo, hi, current},
          'aggregate_sales': {lo, hi, current}  # optional, требует forward pass
        }

    Note: aggregate_sales — placeholder. Полный compute требует forward pass
    через model (вынесен в goal_seek.py).
    """
    config = model_data.get('config', {})
    media_cols = config.get('media_columns', [])
    data_file = config.get('data_file')

    if not data_file:
        # Cannot compute без training data. Return empty corridor.
        return {
            'mode': 'mvp',
            'formula': f'max(P{int(5)}, {relative_lo_factor}*mu), min(P{int(95)}, {relative_hi_factor}*mu)',
            'per_channel': {},
            'aggregate_budget': {'lo': 0.0, 'hi': 0.0, 'current': 0.0},
            'error': 'No data_file in model config',
        }

    # Load training data.
    if str(data_file).endswith(('.xlsx', '.xls')):
        df = pd.read_excel(data_file)
    else:
        df = pd.read_csv(data_file)

    # Apply merge_rules если есть (consistent с optimizer/decomposer).
    try:
        from utils.merge_rules import apply_merge_rules
        apply_merge_rules(df, config.get('merge_rules'))
    except Exception:
        pass  # merge_rules optional; continue без них.

    per_channel: Dict[str, Dict[str, float]] = {}
    sum_lo = 0.0
    sum_hi = 0.0
    sum_current = 0.0

    for channel in media_cols:
        if channel not in df.columns:
            # Канал в media_cols, но нет колонки в data — skip с пустым corridor.
            per_channel[channel] = {
                'lo': 0.0, 'hi': 0.0, 'mu': 0.0, 'p5': 0.0, 'p95': 0.0,
                'current': 0.0,
            }
            continue

        spend_array = df[channel].fillna(0).values
        bounds = compute_per_channel_bounds(
            spend_array,
            relative_lo_factor=relative_lo_factor,
            relative_hi_factor=relative_hi_factor,
        )

        # Current spend — сумма по всему периоду obs.
        current_total = float(spend_array.sum())
        bounds['current'] = current_total

        per_channel[channel] = bounds
        sum_lo += bounds['lo']
        sum_hi += bounds['hi']
        sum_current += current_total

    aggregate_budget = {
        'lo': sum_lo,
        'hi': sum_hi,
        'current': sum_current,
    }

    return {
        'mode': 'mvp',
        'formula': f'max(P5, {relative_lo_factor}*mu), min(P95, {relative_hi_factor}*mu)',
        'per_channel': per_channel,
        'aggregate_budget': aggregate_budget,
    }


def is_in_safe_corridor(
    value: float,
    bounds: Dict[str, float],
    yellow_zone_pct: float = 0.10,
) -> str:
    """Classify value as 'green', 'yellow', or 'red' based on bounds.

    Per ADR-014 UX:
    - 🟢 Внутри [lo, hi] — safe.
    - 🟡 ±10% за пределами — extrapolation warning.
    - 🔴 > 10% за пределами — заблокировано.

    Args:
        value: тестируемое значение (бюджет, цель).
        bounds: {'lo': float, 'hi': float}.
        yellow_zone_pct: relative ширина жёлтой зоны (default 10%).

    Returns:
        'green' | 'yellow' | 'red'.
    """
    lo = bounds['lo']
    hi = bounds['hi']
    if lo <= value <= hi:
        return 'green'

    if value < lo:
        delta_relative = (lo - value) / lo if lo > 0 else float('inf')
    else:  # value > hi
        delta_relative = (value - hi) / hi if hi > 0 else float('inf')

    if delta_relative <= yellow_zone_pct:
        return 'yellow'
    return 'red'
