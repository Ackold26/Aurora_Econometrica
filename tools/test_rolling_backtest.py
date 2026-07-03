"""E1 (2026-07-03): rolling-origin backtest-витрина — «модель vs факт».

Канон: out-of-sample rolling origin (Gelman BW §9.4 — CV predictive checking;
McElreath §7.5 — in-sample fit благоволит сложным моделям; Robyn 2024 —
индустриальный out-of-sample gate). Главная метрика — coverage 90% PI;
модель обязана бить наивный прогноз, иначе вердикт честно worse_than_naive.

Канарейки: coverage и MAPE пересчитываются в тестах независимым кодом
из per-period деталей — заявленное число обязано сойтись с пересчётом.
"""
from __future__ import annotations

import json
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

from engines.backtest import (  # noqa: E402
    _mape,
    _naive_forecasts,
    _plan_windows,
    _rolling_verdict,
    _widen_pi_with_noise,
    load_saved_backtest,
    run_rolling_backtest,
)


# ─── Фикстура: реальный OLS-проект на синтетике с зависимостью ───────────────


def _make_ols_project(base_dir: Path, name: str = 'proj', n_obs: int = 40) -> Path:
    """Проект с data.xlsx (sales зависит от TV/Digital) + БОЕВОЕ обучение OLS —
    rolling-бэктест затем переобучает на подокнах тем же путём, что и прод."""
    rng = np.random.default_rng(42)
    project_dir = base_dir / name
    (project_dir / 'models').mkdir(parents=True, exist_ok=True)

    tv = np.clip(rng.normal(100, 25, n_obs), 10, None)
    digital = np.clip(rng.normal(200, 50, n_obs), 20, None)
    sales = 500.0 + 2.5 * tv + 1.2 * digital + rng.normal(0, 30, n_obs)
    df = pd.DataFrame({
        'date': pd.date_range('2022-01-31', periods=n_obs, freq='ME').strftime('%Y-%m-%d'),
        'TV': tv.round(2),
        'Digital': digital.round(2),
        'sales': sales.round(2),
    })
    data_file = project_dir / 'data.xlsx'
    df.to_excel(data_file, index=False)

    config = {
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['TV', 'Digital'],
        'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'TV': 'geometric', 'Digital': 'geometric'},
        'unit_costs': {'TV': 1.0, 'Digital': 1.0},
        'merge_rules': {},
        'kpi_type': 'sales',
    }
    from engines.ols_modeler import train_ols
    result = train_ols(config, str(project_dir))
    assert result.get('status') == 'ok', f'фикстура: обучение OLS упало: {result.get("message")}'
    return project_dir


@pytest.fixture(scope='module')
def ols_backtest(tmp_path_factory):
    """Один боевой rolling-прогон на модуль (экономия времени): проект + результат."""
    base = tmp_path_factory.mktemp('bt')
    pdir = _make_ols_project(base)
    res = run_rolling_backtest(str(pdir), max_windows=6)
    return pdir, res


# ─── Юниты чистых функций ────────────────────────────────────────────────────


def test_plan_windows_chronological_no_overlap():
    w = _plan_windows(n_obs=40, h=3, min_train=12, max_windows=8)
    assert len(w) == 8
    # Хронологический порядок, шаг ровно h, без нахлёста
    for i in range(1, len(w)):
        assert w[i][0] == w[i - 1][1]
    assert all(end - start == 3 for start, end in w)
    # Последнее окно упирается в конец ряда, обучение первого ≥ min_train
    assert w[-1][1] == 40
    assert w[0][0] >= 12


def test_plan_windows_min_train_and_cap():
    assert _plan_windows(20, 3, 18, 8) == []          # train не дотягивает
    assert len(_plan_windows(100, 3, 12, 4)) == 4     # потолок max_windows
    w = _plan_windows(21, 3, 18, 8)
    assert w == [(18, 21)]                            # ровно одно окно


def test_naive_forecasts_last_and_seasonal():
    y = np.arange(1.0, 25.0)  # 24 точки
    nf = _naive_forecasts(y, h=3, season=12)
    assert nf['naive_last'] == [24.0, 24.0, 24.0]
    assert nf['seasonal_naive'] == [13.0, 14.0, 15.0]  # значения сезон назад
    # Истории меньше сезона → сезонного бенчмарка честно нет
    assert 'seasonal_naive' not in _naive_forecasts(y[:10], h=3, season=12)
    # Горизонт больше сезона → тоже нет (нельзя составить без повтора)
    assert 'seasonal_naive' not in _naive_forecasts(y, h=13, season=12)


def test_widen_pi_quadrature():
    """E1-5 fix (Kagocel-зонд): предиктивный интервал = средняя ⊕ шум наблюдения
    квадратурой; всегда шире интервала средней; при нулевом шуме — без изменений."""
    preds = [100.0, 200.0]
    lo_m = [90.0, 185.0]
    hi_m = [112.0, 210.0]
    lo, hi = _widen_pi_with_noise(preds, lo_m, hi_m, noise_half_width=20.0)
    for i in range(2):
        assert lo[i] < lo_m[i] and hi[i] > hi_m[i], 'предиктивный обязан быть шире средней'
    # Квадратура точно: hw_lo[0] = sqrt(10² + 20²)
    assert lo[0] == pytest.approx(100.0 - np.sqrt(10 ** 2 + 20 ** 2))
    assert hi[0] == pytest.approx(100.0 + np.sqrt(12 ** 2 + 20 ** 2))
    # Нулевой шум — интервал средней не трогаем
    lo0, hi0 = _widen_pi_with_noise(preds, lo_m, hi_m, noise_half_width=0.0)
    assert lo0 == pytest.approx(lo_m) and hi0 == pytest.approx(hi_m)


def test_verdict_priorities_and_russian():
    v, txt = _rolling_verdict(coverage_per_period=0.95, mape_model=20.0, mape_naive_best=15.0)
    assert v == 'worse_than_naive' and 'наивн' in txt
    v, txt = _rolling_verdict(coverage_per_period=0.5, mape_model=8.0, mape_naive_best=15.0)
    assert v == 'coverage_low' and 'самоуверен' in txt
    v, txt = _rolling_verdict(coverage_per_period=0.92, mape_model=8.0, mape_naive_best=15.0)
    assert v == 'validated'
    assert 'точнее наивного' in txt and '%' in txt
    # Проигрыш наивному важнее слабого покрытия (оба плохи — вердикт один)
    v, _ = _rolling_verdict(coverage_per_period=0.4, mape_model=20.0, mape_naive_best=10.0)
    assert v == 'worse_than_naive'


# ─── Боевой OLS-путь ─────────────────────────────────────────────────────────


def test_rolling_ok_structure(ols_backtest):
    _, res = ols_backtest
    assert res['status'] == 'ok', res
    assert res['mode'] == 'ols'
    assert res['granularity'] == 'M'
    assert res['horizon_periods'] == 3
    assert res['n_windows'] >= 3
    assert res['verdict'] in {'validated', 'coverage_low', 'worse_than_naive'}
    assert res['pi_method'] in {'conformal_90', 'residual_z90'}
    assert res['pi_level'] == 0.9
    assert res['mape_model'] > 0
    assert 'naive_last' in res['naive_mape']
    assert 'rolling_origin' in res['method']
    # Даты окон из данных, не порядковые номера
    assert '—' in res['windows'][0]['window']
    assert res['windows'][0]['per_period'][0]['date'] is not None


def test_canary_coverage_recount(ols_backtest):
    """Канарейка: coverage per-period и per-window пересчитаны независимо."""
    _, res = ols_backtest
    hits = [
        pp['hit']
        for w in res['windows']
        for pp in w['per_period']
        if pp['hit'] is not None
    ]
    assert hits, 'PI обязан присутствовать на OLS-пути (conformal/residual)'
    assert res['coverage_per_period'] == pytest.approx(np.mean(hits), abs=1e-4)
    assert res['n_holdout_points_with_interval'] == len(hits)

    window_hits = [w['hit_total'] for w in res['windows'] if w['hit_total'] is not None]
    assert res['coverage_per_window'] == pytest.approx(np.mean(window_hits), abs=1e-4)
    assert res['windows_hit_total'] == sum(window_hits)


def test_canary_mape_recount(ols_backtest):
    """Канарейка: MAPE модели пересчитан из per-period фактов и прогнозов."""
    _, res = ols_backtest
    actual = np.array([pp['actual'] for w in res['windows'] for pp in w['per_period']])
    pred = np.array([pp['predicted'] for w in res['windows'] for pp in w['per_period']])
    assert res['mape_model'] == pytest.approx(_mape(actual, pred), abs=0.05)
    assert res['n_holdout_points'] == len(actual)


def test_saved_json_roundtrip(ols_backtest):
    pdir, res = ols_backtest
    saved = load_saved_backtest(str(pdir))
    assert saved is not None
    assert saved['verdict'] == res['verdict']
    assert saved['mape_model'] == res['mape_model']
    assert saved['generated_at'] == res['generated_at']
    assert saved['model_trained_at'] <= saved['generated_at']
    # Файл — валидный JSON с русским текстом без экранирования
    raw = (pdir / 'models' / 'backtest.json').read_text(encoding='utf-8')
    assert 'модел' in raw.lower()


def test_determinism_two_runs(ols_backtest):
    """Повторный прогон на тех же данных → те же ключевые числа."""
    pdir, res = ols_backtest
    res2 = run_rolling_backtest(str(pdir), max_windows=6)
    assert res2['status'] == 'ok'
    assert res2['mape_model'] == res['mape_model']
    assert res2['coverage_per_period'] == res['coverage_per_period']
    assert res2['verdict'] == res['verdict']
    assert res2['windows'][0]['predicted_total'] == res['windows'][0]['predicted_total']


def test_horizon_override(tmp_path):
    pdir = _make_ols_project(tmp_path, 'hz', n_obs=32)
    res = run_rolling_backtest(str(pdir), horizon_periods=4, max_windows=3)
    assert res['status'] == 'ok'
    assert res['horizon_periods'] == 4
    assert all(w['test_periods'] == 4 for w in res['windows'])


# ─── Честные отказы ──────────────────────────────────────────────────────────


def test_insufficient_short_history(tmp_path):
    pdir = _make_ols_project(tmp_path, 'short', n_obs=18)
    res = run_rolling_backtest(str(pdir))
    assert res['status'] == 'insufficient'
    assert 'Истории недостаточно' in res['message']
    assert res['n_windows_possible'] < 3
    # Отказ НЕ сохраняется как витрина
    assert load_saved_backtest(str(pdir)) is None


def test_no_model_error(tmp_path):
    (tmp_path / 'empty').mkdir()
    res = run_rolling_backtest(str(tmp_path / 'empty'))
    assert res['status'] == 'error'
    assert res['error_code'] == 'NO_MODEL'
    assert 'обучите модель' in res['message']


def test_no_data_error_russian(tmp_path):
    pdir = _make_ols_project(tmp_path, 'lost')
    # Данные исчезли и из исходного пути, и из каталога проекта
    (pdir / 'data.xlsx').rename(tmp_path / 'moved_away.xlsx')
    res = run_rolling_backtest(str(pdir))
    assert res['status'] == 'error'
    assert res['error_code'] == 'NO_DATA'
    assert 'не найден' in res['message'] and 'Errno' not in res['message']


def test_corrupted_saved_json_returns_none(tmp_path):
    pdir = tmp_path / 'corr'
    (pdir / 'models').mkdir(parents=True)
    (pdir / 'models' / 'backtest.json').write_text('{оборвано', encoding='utf-8')
    assert load_saved_backtest(str(pdir)) is None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
