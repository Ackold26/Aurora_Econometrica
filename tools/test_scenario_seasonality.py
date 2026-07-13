"""У1 (2026-07-04): детерминированная сезонность в прогнозах predict_scenario.

Проверяет, что прогноз согласован с historical декомпозицией:
- helper _compute_scenario_seasonality даёт волну правильной фазы (t продолжается
  с n_obs), Σ по полному циклу ≈ 0 (промис «на Год» не смещается);
- модель без Фурье → нулевой вклад (поведение не меняется);
- живой predict_scenario на Фурье-модели: per-period прогноз несёт сезонную волну.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engines.scenario import _compute_scenario_seasonality  # noqa: E402


def _mk_model_data(period=12, n_harm=1, n_obs=24, beta_sin=1.0, beta_cos=0.0, y_std=100.0):
    cols = []
    for k in range(1, n_harm + 1):
        cols += [f'season_fourier_sin_{k}', f'season_fourier_cos_{k}']
    betas = []
    for k in range(1, n_harm + 1):
        betas += [beta_sin, beta_cos]
    return {
        'config': {'control_columns': list(cols)},
        'y_actual': list(np.zeros(n_obs)),
        'fourier_seasonality': {'period': period, 'n_harmonics': n_harm, 'columns': cols},
    }, {
        'control_betas_mean': betas,
        'control_means': {c: 0.0 for c in cols},
        'control_stds': {c: 1.0 for c in cols},
        'y_std': y_std,
    }


def test_helper_phase_continues_from_n_obs():
    """t продолжается с n_obs: при n_obs кратном периоду фаза совпадает с t=0."""
    md, norm = _mk_model_data(period=12, n_obs=24, beta_sin=1.0, y_std=100.0)
    season = _compute_scenario_seasonality(md, norm, n_periods=12)
    # season[i] = 100·sin(2π·(24+i)/12) = 100·sin(2π·i/12) (24/12=2 полных цикла)
    expected = 100.0 * np.sin(2 * np.pi * np.arange(12) / 12)
    assert np.allclose(season, expected, atol=1e-6)


def test_helper_full_cycle_sums_to_zero():
    """Σ сезонности по полному циклу ≈ 0 → baseline «на Год» не смещается."""
    md, norm = _mk_model_data(period=12, n_harm=2, n_obs=24, beta_sin=0.7, beta_cos=0.4)
    season = _compute_scenario_seasonality(md, norm, n_periods=12)
    assert abs(float(season.sum())) < 1e-6


def test_helper_partial_cycle_is_biased():
    """На неполном цикле (квартал) сумма НЕ нулевая — вот что раньше терялось."""
    md, norm = _mk_model_data(period=12, n_obs=24, beta_sin=1.0, y_std=100.0)
    season = _compute_scenario_seasonality(md, norm, n_periods=3)  # квартал вне сезона
    assert abs(float(season.sum())) > 1e-3
    assert len(season) == 3


def test_helper_no_fourier_returns_zeros():
    """Модель без Фурье → нулевой вклад (поведение прогноза не меняется)."""
    md = {'config': {'control_columns': []}, 'y_actual': list(np.zeros(24))}
    norm = {'control_betas_mean': [], 'control_means': {}, 'control_stds': {}, 'y_std': 100.0}
    season = _compute_scenario_seasonality(md, norm, n_periods=12)
    assert np.allclose(season, 0.0)


def test_helper_schema_mismatch_safe():
    """Рассинхрон betas/control_cols → безопасный нуль (не падение)."""
    md, norm = _mk_model_data(period=12, n_obs=24)
    norm['control_betas_mean'] = [1.0]  # длина не совпадает с 2 колонками
    season = _compute_scenario_seasonality(md, norm, n_periods=12)
    assert np.allclose(season, 0.0)


# ── Интеграция: живой predict_scenario несёт сезонную волну ─────────────────

_FAST_MCMC = {'chains': 2, 'draws': 120, 'tune': 120}


def _seasonal_dataset(n, period, freq='W-SUN', seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    tv = np.clip(rng.normal(100, 20, n), 20, None)
    season = 300.0 * np.sin(2 * np.pi * t / period)
    y = 1000 + 3.0 * tv + season + rng.normal(0, 40, n)
    return pd.DataFrame({
        'date': pd.date_range('2022-01-02', periods=n, freq=freq).strftime('%Y-%m-%d'),
        'TV': tv.round(2), 'sales': y.round(2),
    })


def test_predict_scenario_carries_seasonal_wave(tmp_path):
    """Живой прогноз на Фурье-модели: per-period predictions несут сезонную волну
    (не плоские при плоском медиаплане), т.к. сезонность детерминирована."""
    pytest.importorskip("pymc")  # MCMC-тест: CI lightweight без pymc (install-mcmc-deps=false)
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    from engines.scenario import predict_scenario
    from engines.persistence import load_model_with_compat

    cfg = {
        'data_file': str(data_file), 'kpi_column': 'sales',
        'media_columns': ['TV'], 'control_columns': [], 'date_column': 'date',
        'adstock_config': {'TV': 'geometric'}, 'unit_costs': {}, 'merge_rules': {},
        'kpi_type': 'sales', 'use_seasonality': True, 'use_holidays': False,
        'mcmc_override': _FAST_MCMC, 'random_seed': 42,
    }
    r = train_model(cfg, str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')
    fs = load_model_with_compat(tmp_path / 'models' / 'latest.pkl').get('fourier_seasonality')
    assert fs is not None, 'нужна Фурье-модель для теста сезонного прогноза'

    # Плоский медиаплан на 52 недели (полный годовой цикл) → любая помесячная
    # вариация predictions идёт от сезонности, не от медиа.
    horizon = 52
    plan = {'TV': [100.0] * horizon}
    sc = predict_scenario({'scenario_name': 's', 'media_plan': plan}, str(tmp_path))
    assert sc.get('status') == 'ok', sc.get('message')
    preds = np.array(sc['predictions'], dtype=float)
    assert len(preds) == horizon
    # Сезонная волна: размах прогноза заметно больше нуля (плоский план → волна = сезон).
    amp = float(preds.max() - preds.min())
    assert amp > 0.05 * abs(float(preds.mean())), (
        f'прогноз плоский (размах {amp:.0f}) — сезонность не проброшена в predict_scenario'
    )
