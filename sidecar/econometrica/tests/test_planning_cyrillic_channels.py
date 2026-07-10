"""F-AVT-1 (2026-07-10, живой прогон): детекция медиаплана-хвоста для кириллических
имён каналов. Role-детекция по имени их не ловит («ТВ»/«Онлайн-видео» → unknown),
fallback на числовые колонки должен наполнить channels. Иначе медиаплан пуст →
scenario MEDIA_PLAN_EMPTY → фича не работает для русских клиентов."""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path


def _make_cyrillic_fixture(tmp_path: Path, n_hist=24, n_future=6) -> str:
    rng = np.random.default_rng(7)
    n = n_hist + n_future
    dates = pd.date_range('2024-01-31', periods=n, freq='ME')
    tv = rng.uniform(2e6, 5e6, n).round(-3)
    olv = rng.uniform(1e6, 3e6, n).round(-3)
    sales = (8e6 + 1.2 * tv + 2.0 * olv + rng.normal(0, 3e5, n)).round(-3)
    df = pd.DataFrame({'Дата': dates, 'Продажи': sales, 'ТВ': tv, 'Онлайн-видео': olv})
    df.loc[df.index >= n_hist, 'Продажи'] = np.nan  # хвост будущего
    out = tmp_path / 'cyrillic.xlsx'
    df.to_excel(out, index=False)
    return str(out)


def test_cyrillic_channels_detected_in_media_plan(tmp_path):
    from engines.validator import validate_data
    fixture = _make_cyrillic_fixture(tmp_path)
    proj = tmp_path / 'proj'
    proj.mkdir()
    v = validate_data(fixture, str(proj))
    mpd = v.get('media_plan_detected')
    assert mpd is not None, 'хвост будущего должен детектироваться'
    assert mpd['n_future_periods'] == 6
    # F-AVT-1: channels НЕ пустой несмотря на кириллические имена
    assert mpd['channels'], 'channels не должен быть пустым для кириллических каналов'
    assert 'ТВ' in mpd['channels'] and 'Онлайн-видео' in mpd['channels']
    assert len(mpd['channels']['ТВ']) == 6


def test_cyrillic_plan_feeds_scenario(tmp_path):
    """Полный путь: детекция → обучение → прогноз не падает MEDIA_PLAN_EMPTY."""
    import json
    from engines.validator import validate_data
    from engines.ols_modeler import train_ols
    from engines.scenario import predict_scenario
    fixture = _make_cyrillic_fixture(tmp_path)
    proj = tmp_path / 'proj'
    proj.mkdir()
    validate_data(fixture, str(proj))
    train_ols({'data_file': fixture, 'kpi_column': 'Продажи',
               'media_columns': ['ТВ', 'Онлайн-видео'], 'control_columns': [],
               'kpi_type': 'sales', 'mode': 'ols'}, str(proj))
    mp = json.loads((proj / 'results' / 'media_plan.json').read_text(encoding='utf-8'))
    res = predict_scenario({'scenario_name': 'p', 'media_plan': mp['channels'],
                            'forecast_periods': 6, 'future_dates': mp['future_dates'],
                            'carry_in': True}, str(proj))
    assert res.get('status') == 'ok', res.get('message')
    assert res.get('carry_in_applied') is True
    assert len(res['predictions']) == 6
