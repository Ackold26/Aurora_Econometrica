"""
Aurora Econometrica — auto-detection price/value-per-count-unit (v1.3.0).

Per ADR-016 + REFACTOR_PLAN_v1.3.0.md P0.3:
- Если в данных есть и `sales_rub` (или KPI=monetary колонка) И count колонка
  (sales_packs / leads / etc.) — auto-suggest value_per_count_unit = monetary / count.
- Trimmed mean ± CV>20% warning (instability).

Usage:
    from optimize.auto_price import detect_value_per_count_unit

    result = detect_value_per_count_unit(
        df,
        monetary_col='sales_rub',
        count_col='sales_packs',
    )
    # {
    #   'value': 120.5,        # ₽ за упаковку
    #   'cv': 0.08,            # coefficient of variation (8% — stable)
    #   'method': 'trimmed_mean',
    #   'n_periods': 156,
    #   'warning': None,
    # }
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def detect_value_per_count_unit(
    df: pd.DataFrame,
    monetary_col: str,
    count_col: str,
    trim_pct: float = 0.10,
    cv_warn_threshold: float = 0.20,
) -> Dict[str, Any]:
    """Auto-suggest value_per_count_unit (e.g. цена за упаковку, ценность лида).

    Логика:
    1. Ratio per period: value_t = monetary_t / count_t (skip rows where count=0).
    2. Trimmed mean (cut top/bottom 10%) — robust против outliers (промо-периоды).
    3. CV = std/mean > 20% → warning «нестабильна».

    Args:
        df: pandas DataFrame с колонками monetary_col и count_col.
        monetary_col: имя колонки с monetary value (sales_rub, revenue).
        count_col: имя колонки с count value (sales_packs, leads).
        trim_pct: доля для trimmed mean (default 10% top + 10% bottom).
        cv_warn_threshold: CV выше этого → warning.

    Returns:
        {
          'value': float,  # ₽ за единицу
          'cv': float,     # coefficient of variation
          'method': 'trimmed_mean' | 'simple_mean' | 'unavailable',
          'n_periods': int,
          'warning': str | None,
        }
    """
    if monetary_col not in df.columns or count_col not in df.columns:
        return {
            'value': None,
            'cv': None,
            'method': 'unavailable',
            'n_periods': 0,
            'warning': f"Columns not found: {monetary_col}, {count_col}",
        }

    monetary = df[monetary_col].fillna(0).values
    count = df[count_col].fillna(0).values

    # Filter: rows where count > 0 (нельзя делить на 0).
    valid_mask = count > 0
    if not valid_mask.any():
        return {
            'value': None,
            'cv': None,
            'method': 'unavailable',
            'n_periods': 0,
            'warning': 'No valid periods (count > 0) for ratio calculation',
        }

    ratios = monetary[valid_mask] / count[valid_mask]
    n_periods = len(ratios)

    # Filter zero/negative ratios (защита от nonsensical data).
    ratios = ratios[ratios > 0]
    if len(ratios) == 0:
        return {
            'value': None,
            'cv': None,
            'method': 'unavailable',
            'n_periods': 0,
            'warning': 'All ratios are zero or negative',
        }

    if len(ratios) >= 10:
        # Trimmed mean — robust против outliers.
        sorted_ratios = np.sort(ratios)
        trim_n = max(1, int(trim_pct * len(sorted_ratios)))
        trimmed = sorted_ratios[trim_n:-trim_n] if trim_n * 2 < len(sorted_ratios) else sorted_ratios
        value = float(np.mean(trimmed))
        method = 'trimmed_mean'
    else:
        # Малая выборка — simple mean без trim.
        value = float(np.mean(ratios))
        method = 'simple_mean'

    cv = float(np.std(ratios) / np.mean(ratios)) if np.mean(ratios) > 0 else 0.0

    warning = None
    if cv > cv_warn_threshold:
        warning = (
            f'Нестабильная ценность (CV={cv:.1%}). '
            f'Возможны промо-периоды или разный SKU-mix. '
            f'Подтвердите или скорректируйте вручную.'
        )

    return {
        'value': value,
        'cv': cv,
        'method': method,
        'n_periods': n_periods,
        'warning': warning,
    }


def get_value_label_for_kpi(kpi_type: str) -> str:
    """Возвращает UI label для value_per_count_unit поля per KPI type.

    Wrapper around utils.kpi_registry.get_value_per_count_unit_label() с fallback
    на 'Ценность единицы, ₽' для unknown KPIs.
    """
    try:
        from utils.kpi_registry import get_value_per_count_unit_label
        label = get_value_per_count_unit_label(kpi_type)
        if label:
            return label
    except Exception:
        pass
    return 'Ценность единицы, ₽'
