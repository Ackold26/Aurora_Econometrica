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


def test_decompose_aggregates_fourier_into_one_seasonality_factor(tmp_path):
    """Декомпозиция агрегирует 2K sin/cos колонок в ОДИН фактор «Сезонность»
    (не 6 полос отдельных гармоник), выносит его полосой в decomposition_series
    с type='seasonality', group='Сезонность', top_group='БАЗА' и pct_of_base[]."""
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    from engines.decomposer import decompose
    r = train_model(_config(data_file), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')
    md = _load_pickle(tmp_path)
    fs = md.get('fourier_seasonality')
    assert fs is not None and len(fs['columns']) >= 2, 'нужны ≥2 Фурье-колонки для теста агрегации'

    d = decompose(str(tmp_path), save_results=False)
    assert d.get('status') == 'ok', d.get('message')

    sfc = d['signed_factor_contributions']
    # Агрегация: НИ ОДНА season_fourier_* колонка не выходит отдельным фактором.
    assert not any(str(k).startswith('season_fourier') for k in sfc), (
        f'Фурье-колонки не должны быть отдельными факторами: {list(sfc)}'
    )
    # Ровно один агрегированный фактор сезонности.
    season_factors = [k for k, v in sfc.items() if isinstance(v, dict) and v.get('type') == 'seasonality']
    assert len(season_factors) == 1, f'ожидался 1 фактор сезонности, найдено: {season_factors}'
    season = sfc[season_factors[0]]
    assert len(season['per_period']) == len(df), 'per_period помесячно по всему ряду'
    assert 'beta_mean' not in season, 'beta_mean для суммы гармоник не осмыслен → опущен'

    # Полоса в decomposition_series: type/group/top_group + pct_of_base волна.
    series = d['decomposition_series']['series']
    band = next((s for s in series if s['type'] == 'seasonality'), None)
    assert band is not None, 'полоса «Сезонность» должна быть в decomposition_series'
    assert band['group'] == 'Сезонность'
    assert band['top_group'] == 'БАЗА'
    assert 'pct_of_base' in band and len(band['pct_of_base']) == len(df)
    # Сезонная волна ненулевая (амплитуда есть).
    assert max(abs(v) for v in band['data']) > 0, 'сезонная волна не должна быть плоской'


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


def test_ols_filters_fourier_from_bayesian_config(tmp_path):
    """Аудит 2026-07-04: config байесовской модели несёт season_fourier_* в
    control_columns; train_ols (backtest mode='ols' окна / переключение движка)
    не инжектит Фурье и падал бы KeyError на df[control_cols]. Фильтр в OLS
    честно исключает runtime-колонки — обучение проходит."""
    df = _seasonal_dataset(n=40, period=52)
    data_file = tmp_path / 'ols.xlsx'
    df.to_excel(data_file, index=False)

    cfg = _config(data_file)
    cfg['control_columns'] = [
        'season_fourier_sin_1', 'season_fourier_cos_1',  # из bayesian-конфига
    ]
    from engines.ols_modeler import train_ols
    r = train_ols(cfg, str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')


def test_backtest_with_seasonality_not_error(tmp_path):
    """Регресс: backtest переобучает окна через train_model; Фурье-колонки
    из config.control_columns (полной модели) НЕ должны валить окна как
    «отсутствующие контроли». Инжект перенесён ДО валидации control + синхро
    control_cols с df. Ожидание: backtest status ok, окна отработали."""
    df = _seasonal_dataset(n=110, period=52)
    data_file = tmp_path / 'seasonal.xlsx'
    df.to_excel(data_file, index=False)

    from engines.modeler import train_model
    from engines.backtest import run_rolling_backtest
    r = train_model(_config(data_file), str(tmp_path))
    assert r.get('status') == 'ok', r.get('message')
    # Убедимся, что Фурье реально инжектированы (иначе тест не проверяет баг).
    assert _load_pickle(tmp_path).get('fourier_seasonality') is not None

    bt = run_rolling_backtest(str(tmp_path), max_windows=3, save=False)
    assert bt.get('status') == 'ok', (
        f"backtest упал: {bt.get('message')} | failed={bt.get('failed_windows')}"
    )
    assert bt.get('n_windows', 0) >= 1
