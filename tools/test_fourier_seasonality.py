"""Автосезонность А (2026-07-04): Фурье-компонента сезонности — юниты.

Канон: Prophet (Taylor & Letham 2018) §3.2 — гибкая сезонная волна как ряд
Фурье sum_k[a_k·sin(2πkt/P)+b_k·cos(2πkt/P)]; Robyn/Meridian переняли.
Честный гейт INV-50: сезонность периода P оценима лишь при ≥2 полных циклах.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.fourier_seasonality import (  # noqa: E402
    FOURIER_COL_PREFIX,
    decide_n_harmonics,
    generate_fourier_terms,
    list_fourier_columns,
    should_inject_seasonality,
)


# ─── generate_fourier_terms ─────────────────────────────────────────────────

def test_fourier_shape_and_columns():
    df = generate_fourier_terms(n_obs=52, period=52, n_harmonics=3)
    assert df.shape == (52, 6)  # 3 пары sin/cos
    assert list(df.columns) == [
        f'{FOURIER_COL_PREFIX}_sin_1', f'{FOURIER_COL_PREFIX}_cos_1',
        f'{FOURIER_COL_PREFIX}_sin_2', f'{FOURIER_COL_PREFIX}_cos_2',
        f'{FOURIER_COL_PREFIX}_sin_3', f'{FOURIER_COL_PREFIX}_cos_3',
    ]


def test_fourier_values_in_unit_range():
    df = generate_fourier_terms(n_obs=100, period=13, n_harmonics=2)
    assert df.to_numpy().min() >= -1.0 - 1e-9
    assert df.to_numpy().max() <= 1.0 + 1e-9


def test_fourier_first_harmonic_period_correct():
    # Первая гармоника sin с периодом P: t=0 → 0, t=P/4 → ~1 (четверть цикла).
    period = 12
    df = generate_fourier_terms(n_obs=13, period=period, n_harmonics=1)
    sin1 = df[f'{FOURIER_COL_PREFIX}_sin_1'].to_numpy()
    cos1 = df[f'{FOURIER_COL_PREFIX}_cos_1'].to_numpy()
    assert abs(sin1[0]) < 1e-9          # sin(0)=0
    assert abs(cos1[0] - 1.0) < 1e-9    # cos(0)=1
    assert abs(sin1[period // 4] - 1.0) < 1e-9   # sin(π/2)=1 при t=P/4
    # Полный цикл: t=P возвращает к старту.
    assert abs(sin1[period] - sin1[0]) < 1e-9
    assert abs(cos1[period] - cos1[0]) < 1e-9


def test_fourier_deterministic():
    a = generate_fourier_terms(60, 26, 2)
    b = generate_fourier_terms(60, 26, 2)
    assert np.array_equal(a.to_numpy(), b.to_numpy())


def test_fourier_degenerate_params_empty():
    assert generate_fourier_terms(0, 52, 3).empty
    assert generate_fourier_terms(50, 1, 3).empty      # period<2
    assert generate_fourier_terms(50, 52, 0).empty      # harmonics<1


# ─── decide_n_harmonics ─────────────────────────────────────────────────────

@pytest.mark.parametrize('period,expected', [
    (52, 4),   # min(4, 52//4=13)=4
    (13, 3),   # min(4, 13//4=3)=3
    (12, 3),   # min(4, 12//4=3)=3
    (4, 1),    # min(4, 4//4=1)=1
    (2, 1),    # period//2=1 Nyquist cap
    (1, 1),    # вырожден → 1
])
def test_decide_n_harmonics(period, expected):
    assert decide_n_harmonics(period) == expected


def test_harmonics_never_exceed_nyquist():
    for p in range(2, 60):
        assert decide_n_harmonics(p) <= max(1, p // 2)


# ─── should_inject_seasonality (гейт INV-50) ────────────────────────────────

def test_gate_none_detected():
    inject, reason = should_inject_seasonality(None, n_obs=100)
    assert inject is False
    assert 'не обнаружена' in reason


def test_gate_insufficient_cycles():
    # period 52, данных 60 < 2·52=104 → отказ (Kagocel-класс: короткий ряд).
    inject, reason = should_inject_seasonality(
        {'period': 52, 'autocorr': 0.5}, n_obs=60)
    assert inject is False
    assert 'циклов' in reason


def test_gate_quarterly_passes_on_short_series():
    # Kagocel 31 нед: годовая (52) не проходит, квартальная (13) проходит: 31≥26.
    inject, reason = should_inject_seasonality(
        {'period': 13, 'autocorr': 0.4}, n_obs=31)
    assert inject is True
    assert '13' in reason


def test_gate_rejects_antiphase():
    # Отрицательная автокорреляция (анти-фаза полупериода) — не инжектим.
    inject, reason = should_inject_seasonality(
        {'period': 26, 'autocorr': -0.5}, n_obs=100)
    assert inject is False
    assert 'автокорреляц' in reason


def test_gate_rejects_invalid_period():
    inject, reason = should_inject_seasonality(
        {'period': 1, 'autocorr': 0.5}, n_obs=100)
    assert inject is False
    assert 'период' in reason


def test_gate_accepts_valid_yearly():
    inject, reason = should_inject_seasonality(
        {'period': 52, 'autocorr': 0.6}, n_obs=156)  # 3 года недельных
    assert inject is True


def test_gate_rejects_noise_autocorr_on_short_series():
    # Боевой случай: бессезонная синтетика n=26 дала ложный period=3, autocorr
    # 0.265. Порог значимости 1.96/√26≈0.384 > 0.265 → отказ (шум, не сезонность).
    inject, reason = should_inject_seasonality(
        {'period': 3, 'autocorr': 0.265}, n_obs=26)
    assert inject is False
    assert 'шум' in reason or 'неотличима' in reason


def test_significance_threshold_scales_with_n():
    # Одна и та же autocorr 0.30: значима на длинном ряду, шум на коротком.
    long_inject, _ = should_inject_seasonality(
        {'period': 12, 'autocorr': 0.30}, n_obs=200)  # порог 0.2 (пол) < 0.30
    short_inject, _ = should_inject_seasonality(
        {'period': 12, 'autocorr': 0.30}, n_obs=36)   # порог 1.96/√36=0.327 > 0.30
    assert long_inject is True
    assert short_inject is False


# ─── list_fourier_columns паритет ───────────────────────────────────────────

def test_list_columns_matches_generate():
    period, K = 26, 2
    df = generate_fourier_terms(40, period, K)
    assert list_fourier_columns(period, K) == list(df.columns)


def test_list_columns_degenerate():
    assert list_fourier_columns(1, 3) == []
    assert list_fourier_columns(52, 0) == []
