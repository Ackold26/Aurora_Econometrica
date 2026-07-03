"""A5/OPP-07 (2026-07-03): awareness-движок до канона кабинета.

Канон §/awareness-forecast (New_AI_Agency/econometrist/CLAUDE.md):
- ESOV-модуль (Binet & Field, Fig. 31–32: ≈0.05 пп роста SOM/год на 1 пп
  ESOV, диапазон 0.05–0.07) — только при живых SOV/SOM;
- adstock с длинным Weibull-хвостом (знание строится и затухает медленно);
- CI на эластичность S-кривой (delta-метод из pcov curve_fit — ковариация
  была, но не доставлялась).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engines.awareness import (  # noqa: E402
    _esov_module, forecast_awareness, awareness_to_sales,
    ESOV_SLOPE_POINT,
)


def _df_with_awareness(n=30, seed=5):
    rng = np.random.default_rng(seed)
    spend = rng.uniform(80, 160, n)
    aw = np.zeros(n)
    aw[0] = 30.0
    for t in range(1, n):
        aw[t] = 0.9 * aw[t - 1] + 0.02 * spend[t] + rng.normal(0, 0.6)
    return pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=n, freq='MS').strftime('%Y-%m-%d'),
        'TV': spend.round(1),
        'awareness_%': aw.round(1),
    })


# ─── ESOV (Binet & Field) ────────────────────────────────────────────────────

def test_esov_computed_from_sov_som_percent():
    df = pd.DataFrame({'SOV': [30.0] * 12, 'SOM в руб': [20.0] * 12})
    r = _esov_module(df, {})
    assert r and r['available'] is True
    assert r['esov_mean_pp'] == pytest.approx(10.0)
    assert r['expected_som_growth_pp_per_year'] == pytest.approx(10.0 * ESOV_SLOPE_POINT)
    lo, hi = r['expected_som_growth_range_pp']
    assert lo == pytest.approx(0.5) and hi == pytest.approx(0.7)
    assert 'Binet' in r['slope_source']
    assert 'не гарантия' in r.get('note', '')


def test_esov_fractions_accepted_rubles_rejected():
    """Доли 0..1 конвертируются; рублёвые величины честно отклоняются."""
    df_frac = pd.DataFrame({'sov_share': [0.3] * 8, 'som_share': [0.2] * 8})
    r = _esov_module(df_frac, {'sov_column': 'sov_share', 'som_column': 'som_share'})
    assert r['available'] is True and r['esov_mean_pp'] == pytest.approx(10.0)

    df_rub = pd.DataFrame({'SOV': [30.0] * 8, 'SOM в руб': [1.2e9] * 8})
    r2 = _esov_module(df_rub, {})
    assert r2['available'] is False
    assert 'не похожи на доли' in r2['reason']


def test_esov_skipped_without_columns():
    df = pd.DataFrame({'TV': [1.0] * 8, 'awareness_%': [30.0] * 8})
    assert _esov_module(df, {}) is None


# ─── Weibull-хвост медиа→awareness ───────────────────────────────────────────

def test_forecast_uses_weibull_by_default_and_esov_delivered(tmp_path):
    df = _df_with_awareness()
    df['SOV'] = 32.0
    df['SOM'] = 22.0
    f = tmp_path / 'aw.csv'
    df.to_csv(f, index=False)
    res = forecast_awareness(
        {'data_file': str(f), 'awareness_column': 'awareness_%',
         'media_columns': ['TV'], 'forecast_periods': 6},
        str(tmp_path),
    )
    assert res['status'] == 'ok'
    assert res['model']['media_transform'] == 'weibull'
    assert res['ci_method'] == 'ar1_forecast_variance_90'
    assert res['esov'] and res['esov']['available'] is True
    assert res['esov']['esov_mean_pp'] == pytest.approx(10.0)


def test_forecast_adstock_opt_out(tmp_path):
    df = _df_with_awareness()
    f = tmp_path / 'aw2.csv'
    df.to_csv(f, index=False)
    res = forecast_awareness(
        {'data_file': str(f), 'awareness_column': 'awareness_%',
         'media_columns': ['TV'], 'forecast_periods': 4,
         'awareness_adstock': {'type': 'none'}},
        str(tmp_path),
    )
    assert res['status'] == 'ok'
    assert res['model']['media_transform'] == 'none'
    assert res['esov'] is None  # SOV/SOM нет — модуль честно пропущен


# ─── CI эластичности S-кривой ────────────────────────────────────────────────

def test_elasticity_ci_delivered(tmp_path):
    rng = np.random.default_rng(7)
    aw = np.linspace(10, 70, 36)
    sales = 1000.0 / (1 + np.exp(-0.15 * (aw - 40))) + rng.normal(0, 12, 36)
    f = tmp_path / 's.csv'
    pd.DataFrame({'awareness_%': aw.round(1), 'sales': sales.round(1)}).to_csv(f, index=False)
    res = awareness_to_sales(
        {'data_file': str(f), 'awareness_column': 'awareness_%', 'sales_column': 'sales'},
        str(tmp_path),
    )
    assert res['status'] == 'ok'
    ci = res['elasticity_ci']
    assert ci is not None and res['elasticity_ci_method'] == 'delta_pcov_90'
    assert ci[0] <= res['elasticity'] <= ci[1]
    assert ci[1] > ci[0], 'Интервал не должен схлопываться в точку'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
