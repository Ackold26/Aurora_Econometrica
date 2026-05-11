"""Tests для engines/verdicts.py — v1.3.0 KPI/mode-aware verdicts (ADR-016)."""
from __future__ import annotations

import pytest

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from engines.verdicts import (
    compute_verdict_count_kpi,
    compute_verdict_effectiveness_mode,
    compute_verdict_kpi_aware,
)


# ─── compute_verdict_count_kpi ──────────────────────────────────────────────

def test_count_cpu_far_above_value_is_deep_loss():
    """CPU = 300, value = 100 → CPU > 2x value → глубоко убыточный."""
    label, tone = compute_verdict_count_kpi(cpu=300, value_per_count_unit=100)
    assert tone == 'bad'
    assert 'Глубоко убыточный' in label


def test_count_cpu_above_value_is_loss():
    """CPU = 130, value = 100 → CPU > 1x value (1.3x) → убыточный."""
    label, tone = compute_verdict_count_kpi(cpu=130, value_per_count_unit=100)
    assert tone == 'bad'
    assert 'Убыточный' in label


def test_count_cpu_near_value_is_breakeven():
    """CPU = 95, value = 100 → 0.95 ratio → на грани."""
    label, tone = compute_verdict_count_kpi(cpu=95, value_per_count_unit=100)
    assert tone == 'warn'
    assert 'грани' in label.lower()


def test_count_cpu_below_value_is_profitable():
    """CPU = 50, value = 100 → ratio 0.5 → окупаемый."""
    label, tone = compute_verdict_count_kpi(cpu=50, value_per_count_unit=100)
    assert tone == 'good'


def test_count_high_efficiency_gap_promotes_to_high_perf():
    """CPU = 50, value = 100, gap=0.15 → высокоэффективен."""
    label, tone = compute_verdict_count_kpi(
        cpu=50, value_per_count_unit=100, efficiency_gap=0.15
    )
    assert tone == 'good'
    assert 'Высокоэффективен' in label


def test_count_missing_value_falls_back_to_share_based():
    """Без value — нейтральные тэги (efficiency gap)."""
    label, tone = compute_verdict_count_kpi(
        cpu=100, value_per_count_unit=None, efficiency_gap=0.0
    )
    assert tone == 'neutral'
    assert 'Сбалансирован' in label


def test_count_wide_ci_adds_suffix():
    """Wide CI → suffix '(широкий интервал CPU)'."""
    label, tone = compute_verdict_count_kpi(
        cpu=50, value_per_count_unit=100,
        cpu_ci_low=10, cpu_ci_high=100,  # span 90 > cpu 50
    )
    assert 'широкий интервал CPU' in label


def test_count_unit_smell_warns_low_cpu():
    """Канал на physical metrics + low CPU → warn about units."""
    label, tone = compute_verdict_count_kpi(
        cpu=5, value_per_count_unit=100, unit_smell=True
    )
    assert tone == 'warn'
    assert 'единицы' in label.lower()


def test_count_negative_cpu_is_artifact():
    label, tone = compute_verdict_count_kpi(cpu=-10, value_per_count_unit=100)
    assert tone == 'warn'
    assert 'отрицателен' in label.lower() or 'артефакт' in label.lower()


# ─── compute_verdict_effectiveness_mode ─────────────────────────────────────

def test_effectiveness_top_share_is_top_driver():
    """Share выше P75 → Топ-драйвер."""
    label, tone = compute_verdict_effectiveness_mode(
        sales_share=0.30, median_share=0.10, p75_share=0.20, p25_share=0.05
    )
    assert tone == 'good'
    assert 'Топ-драйвер' in label


def test_effectiveness_above_median_is_significant():
    label, tone = compute_verdict_effectiveness_mode(
        sales_share=0.15, median_share=0.10, p75_share=0.20, p25_share=0.05
    )
    assert tone == 'good'
    assert 'Значимый' in label


def test_effectiveness_below_p25_is_weak():
    label, tone = compute_verdict_effectiveness_mode(
        sales_share=0.03, median_share=0.10, p75_share=0.20, p25_share=0.05
    )
    assert tone == 'warn'
    assert 'Слабый' in label


def test_effectiveness_negligible_share():
    label, tone = compute_verdict_effectiveness_mode(
        sales_share=0.001, threshold_share=0.005
    )
    assert tone == 'warn'
    assert 'Пренебрежимо' in label


# ─── compute_verdict_kpi_aware unified dispatch ─────────────────────────────

def test_kpi_aware_monetary_roi_delegates_to_v12():
    """kpi_kind='monetary' + mode='roi' → старая v1.2 логика compute_roi_verdict."""
    label, tone = compute_verdict_kpi_aware(
        kpi_kind='monetary', mode='roi',
        roi=0.3, efficiency_gap=-0.15,
    )
    # ROI < 0.5 → Глубоко убыточный (v1.2 behavior).
    assert 'Глубоко убыточный' in label
    assert tone == 'bad'


def test_kpi_aware_count_uses_cpu_logic():
    """kpi_kind='count' + mode='roi' → CPU vs value."""
    label, tone = compute_verdict_kpi_aware(
        kpi_kind='count', mode='roi',
        cpu=120, value_per_count_unit=80, efficiency_gap=0.0,
    )
    # CPU 120 > value 80 (1.5x) → убыточный (CPU > value).
    assert tone == 'bad'


def test_kpi_aware_effectiveness_uses_share():
    """mode='effectiveness' → share-based independently of kpi_kind."""
    label, tone = compute_verdict_kpi_aware(
        mode='effectiveness', kpi_kind='monetary',
        sales_share=0.25, median_share=0.10, p75_share=0.20,
    )
    assert tone == 'good'
    assert 'Топ-драйвер' in label


def test_kpi_aware_count_missing_cpu_returns_neutral():
    label, tone = compute_verdict_kpi_aware(
        kpi_kind='count', mode='roi',
        cpu=None, value_per_count_unit=100,
    )
    assert tone == 'neutral'
    assert 'CPU' in label


def test_kpi_aware_effectiveness_missing_share_returns_neutral():
    label, tone = compute_verdict_kpi_aware(
        mode='effectiveness',
        sales_share=None,
    )
    assert tone == 'neutral'


def test_kpi_aware_monetary_missing_roi_returns_neutral():
    label, tone = compute_verdict_kpi_aware(
        kpi_kind='monetary', mode='roi',
        roi=None,
    )
    assert tone == 'neutral'
