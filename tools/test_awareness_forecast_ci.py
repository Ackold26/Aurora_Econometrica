"""Awareness forecast CI — характеризующие тесты мат-аудита 2026-07-02 (F-26).

Прежний «CI» = std(awareness)×0.5 — константа без статистического смысла:
прогноз на 12 периодов вперёд имел ту же ширину, что на 1. Теперь — честный
прогнозный интервал AR(1): var[h] = σ²_resid·Σ decay^(2i) (стандартная
прогнозная дисперсия авторегрессии), 90% (z=1.645), с ростом по горизонту
и сходимостью к асимптоте при |decay|<1.
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

from engines.awareness import forecast_awareness  # noqa: E402


def _make_project(tmp_path: Path, n: int = 36, seed: int = 5) -> tuple[str, str]:
    rng = np.random.default_rng(seed)
    aw = np.empty(n)
    aw[0] = 50.0
    spend = rng.uniform(80, 120, n)
    for t in range(1, n):
        aw[t] = 0.85 * aw[t - 1] + 0.05 * spend[t] + 2.0 + rng.normal(0, 1.2)
    df = pd.DataFrame({
        'date': pd.date_range('2023-01-31', periods=n, freq='ME'),
        'awareness_%': np.round(aw, 1),
        'tv_spend': np.round(spend, 1),
    })
    data_file = tmp_path / 'aw.csv'
    df.to_csv(data_file, index=False)
    return str(data_file), str(tmp_path)


def test_ci_grows_with_horizon(tmp_path):
    data_file, pdir = _make_project(tmp_path)
    res = forecast_awareness({
        'data_file': data_file,
        'awareness_column': 'awareness_%',
        'media_columns': ['tv_spend'],
        'forecast_periods': 12,
    }, pdir)
    assert res['status'] == 'ok'
    assert res['ci_method'] == 'ar1_forecast_variance_90'
    widths = [u - lo for lo, u in zip(res['ci_lower'], res['ci_upper'])]
    # Ширина растёт с горизонтом (клипы к [0,100] не мешают: awareness в середине шкалы)
    assert widths[0] < widths[3] < widths[-1] or (
        widths[0] < widths[-1]), f'CI не растёт с горизонтом: {widths}'
    # И не взрывается: |decay|<1 → сходимость к конечной асимптоте
    assert widths[-1] < 100


def test_smalln_falls_back_to_proxy(tmp_path):
    data_file, pdir = _make_project(tmp_path, n=6)
    res = forecast_awareness({
        'data_file': data_file,
        'awareness_column': 'awareness_%',
        'media_columns': ['tv_spend'],
        'forecast_periods': 6,
    }, pdir)
    assert res['status'] == 'ok'
    assert res['ci_method'] == 'std_proxy_smalln'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
