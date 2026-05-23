"""Tests для optimize/auto_price.py - value_per_count_unit detection (ADR-016 P0.3)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from optimize.auto_price import detect_value_per_count_unit, get_value_label_for_kpi


# ─── Stable price detection ─────────────────────────────────────────────────

def test_stable_price_detected_correctly():
    """Цена 100 ₽ за упаковку, без вариаций → value=100, low CV."""
    df = pd.DataFrame({
        'sales_rub': [10000, 12000, 11000, 13000, 9500, 11500] * 4,
        'sales_packs': [100, 120, 110, 130, 95, 115] * 4,
    })
    # ratio = sales_rub / sales_packs = 100 для всех.
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    assert result['value'] == 100.0
    assert result['cv'] < 0.01  # near-zero
    assert result['warning'] is None


def test_unstable_price_warning():
    """High CV (промо-периоды) → warning."""
    np.random.seed(42)
    n = 30
    packs = np.random.uniform(100, 200, n)
    # Цена меняется сильно: random 50–200 ₽/упак (промо-микс).
    prices = np.random.uniform(50, 200, n)
    rub = packs * prices

    df = pd.DataFrame({'sales_rub': rub, 'sales_packs': packs})
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    assert result['cv'] > 0.20
    assert result['warning'] is not None
    assert 'CV' in result['warning']


# ─── Edge cases ─────────────────────────────────────────────────────────────

def test_missing_columns_returns_unavailable():
    df = pd.DataFrame({'sales_rub': [1, 2, 3]})
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    assert result['value'] is None
    assert result['method'] == 'unavailable'


def test_zero_count_periods_skipped():
    """Periods with count=0 not divided."""
    df = pd.DataFrame({
        'sales_rub': [100, 200, 300, 400],
        'sales_packs': [10, 0, 30, 0],  # 2 valid periods
    })
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    # ratios = [10, 10] (period 1: 100/10, period 3: 300/30)
    assert result['value'] == 10.0
    assert result['n_periods'] == 2


def test_all_zero_count_returns_unavailable():
    df = pd.DataFrame({
        'sales_rub': [100, 200],
        'sales_packs': [0, 0],
    })
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    assert result['value'] is None
    assert result['method'] == 'unavailable'


def test_small_sample_uses_simple_mean():
    """Меньше 10 valid periods - без trim."""
    df = pd.DataFrame({
        'sales_rub': [100, 200, 300, 400, 500],
        'sales_packs': [10, 20, 30, 40, 50],
    })
    result = detect_value_per_count_unit(df, 'sales_rub', 'sales_packs')
    assert result['method'] == 'simple_mean'
    assert result['value'] == 10.0


# ─── get_value_label_for_kpi ────────────────────────────────────────────────

def test_label_for_sales_packs():
    label = get_value_label_for_kpi('sales_packs')
    assert label == 'Маржа на упаковку, ₽'


def test_label_for_leads():
    label = get_value_label_for_kpi('leads')
    assert label == 'Ценность лида, ₽'


def test_label_for_subscriptions():
    label = get_value_label_for_kpi('subscriptions')
    assert label == 'MRR на подписку, ₽'


def test_label_for_unknown_kpi_uses_fallback():
    label = get_value_label_for_kpi('totally_unknown_kpi_type')
    assert label == 'Ценность единицы, ₽'


def test_label_for_monetary_kpi_returns_empty():
    """Monetary KPIs не имеют value_per_count_unit поля → empty."""
    label = get_value_label_for_kpi('sales')  # monetary
    assert label == 'Ценность единицы, ₽'  # fallback (empty string в registry → fallback)
