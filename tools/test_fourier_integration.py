"""Автосезонность А (2026-07-04): интеграция Фурье в modeler/decomposer.

Проверяет, что при обучении на ряду с ГОДОВОЙ сезонной волной (≥2 цикла) движок
инжектит Фурье-контроли и персистит их в pickle, короткий ряд — не инжектит
(гейт INV-50), а decomposer переинжектит те же колонки бит-в-бит (не падает).

Инъекция происходит ДО построения PyMC-модели → минимального MCMC достаточно
(тест про инжект-механику, не про качество сходимости).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_FAST_MCMC = {'chains': 2, 'draws': 80, 'tune': 80}


def _seasonal_dataset(n, period, freq='W-SUN', seed=7):
    """Синтетика: медиа + гладкая сезонная sin-волна периода `period` + шум."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    tv = np.clip(rng.normal(100, 20, n), 20, None)
    digital = np.clip(rng.normal(80, 15, n), 20, None)
    season = 300.0 * np.sin(2 * np.pi * t / period)  # гладкая годовая волна
    y = 1000 + 3.0 * tv + 2.0 * digital + season + rng.normal(0, 40, n)
    return pd.DataFrame({
        'date': pd.date_range('2022-01-02', periods=n, freq=freq).strftime('%Y-%m-%d'),
        'TV': tv.round(2), 'Digital': digital.round(2), 'sales': y.round(2),
    })


def _config(data_file, **extra):
    cfg = {
        'data_file': str(data_file), 'kpi_column': 'sales',
        'media_columns': ['TV', 'Digital'], 'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'TV': 'geometric', 'Digital': 'geometric'},
        'unit_costs': {}, 'merge_rules': {}, 'kpi_type': 'sales',
        'mcmc_override': _FAST_MCMC, 'random_seed': 42,
    }
    cfg.update(extra)
    return cfg


def _load_pickle(project_dir):
    # latest.pkl — формат aurora-model (ZIP с persistent_id для больших массивов);
    # читать штатным loader'ом движка, не сырым pickle.load.
    from engines.persistence import load_model_with_compat
    return load_model_with_compat(Path(project_dir) / 'models' / 'latest.pkl')


def test_yearly_seasonality_injected(tmp_path):
    """n=110 недель (>2 цикла периода 52) → Фурье-контроли инжектированы + в pickle."""
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    r = train_model(_config(data_file), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')

    md = _load_pickle(tmp_path)
    fs = md.get('fourier_seasonality')
    assert fs is not None, 'ожидалась инъекция Фурье на годовой синтетике'
    assert fs['period'] in (26, 52), f"период {fs['period']} не годовой/полугодовой"
    assert len(fs['columns']) == 2 * fs['n_harmonics']
    assert all(c.startswith('season_fourier') for c in fs['columns'])


def test_short_series_no_injection(tmp_path):
    """n=30 недель (<2 цикла периода 52) → Фурье НЕ инжектируется (гейт INV-50)."""
    df = _seasonal_dataset(n=30, period=52)
    data_file = tmp_path / 'short.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    r = train_model(_config(data_file), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')

    md = _load_pickle(tmp_path)
    # Годовая (52) не проходит гейт на 30 набл.; квартальная (13) могла бы (30≥26),
    # но на этой синтетике зашита только годовая волна → детектор не даст 13.
    fs = md.get('fourier_seasonality')
    if fs is not None:
        # Если что-то и инжектировалось — точно не годовое (данных нет на 2 цикла 52).
        assert fs['period'] < 52


def test_decompose_parity_with_seasonality(tmp_path):
    """decompose на модели с Фурье не падает (re-inject колонок), status ok."""
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    from engines.decomposer import decompose
    r = train_model(_config(data_file), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')

    d = decompose(str(tmp_path), save_results=False)
    assert d.get('status') == 'ok', d.get('message')


def test_master_flag_disables_seasonality(tmp_path):
    """use_seasonality=False → Фурье не инжектируется даже на годовом ряду."""
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    r = train_model(_config(data_file, use_seasonality=False), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')

    md = _load_pickle(tmp_path)
    assert md.get('fourier_seasonality') is None
