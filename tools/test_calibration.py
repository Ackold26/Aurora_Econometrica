"""E2 (2026-07-03): калибровка lift-тестами — юниты подготовки + характеризующий.

Канон: Robyn (Meta 2024) §4.3 — калибровка двигает оценки к RCT-истине;
реализация Aurora — lift как дополнительное наблюдение правдоподобия.
Характеризующий критерий ROADMAP §E2: на синтетике с ЗАШИТЫМ истинным вкладом
калиброванная модель восстанавливает вклад канала ЛУЧШЕ некалиброванной.
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

from utils.calibration import (  # noqa: E402
    CalibrationError,
    prepare_calibrations,
)


# ─── Юниты prepare_calibrations (без PyMC) ──────────────────────────────────


def _df(n=24):
    return pd.DataFrame({
        'date': pd.date_range('2024-01-31', periods=n, freq='ME').strftime('%Y-%m-%d'),
        'TV': np.linspace(80, 120, n).round(1),
        'Digital': np.linspace(150, 210, n).round(1),
        'sales': np.linspace(900, 1100, n).round(1),
    })


def test_prepare_ok_with_interval():
    df = _df()
    out = prepare_calibrations(
        df,
        [{'channel': 'TV', 'date_from': '2024-06-30', 'date_to': '2024-09-30',
          'lift_abs': 240.0, 'lift_low': 140.0, 'lift_high': 340.0,
          'confidence_level': 0.9, 'test_type': 'geo_lift'}],
        media_columns=['TV', 'Digital'], date_column='date',
    )
    assert len(out) == 1
    c = out[0]
    assert c['n_periods'] == 4 and c['idx_to'] - c['idx_from'] == 4
    # σ из интервала: (340-140)/(2·1.6449) ≈ 60.79
    assert c['sigma_abs'] == pytest.approx(200 / (2 * 1.6449), rel=1e-3)
    assert c['test_type'] == 'geo_lift'


def test_prepare_errors_russian():
    df = _df()
    with pytest.raises(CalibrationError, match='не входит в медиа-каналы'):
        prepare_calibrations(df, [{'channel': 'Radio', 'date_from': '2024-06-30',
                                   'date_to': '2024-08-31', 'lift_abs': 1.0,
                                   'sigma_abs': 1.0}],
                             media_columns=['TV'], date_column='date')
    with pytest.raises(CalibrationError, match='наблюдений'):
        prepare_calibrations(df, [{'channel': 'TV', 'date_from': '2024-06-30',
                                   'date_to': '2024-06-30', 'lift_abs': 1.0,
                                   'sigma_abs': 1.0}],
                             media_columns=['TV'], date_column='date')
    with pytest.raises(CalibrationError, match='интервал теста'):
        prepare_calibrations(df, [{'channel': 'TV', 'date_from': '2024-06-30',
                                   'date_to': '2024-08-31', 'lift_abs': 1.0}],
                             media_columns=['TV'], date_column='date')
    with pytest.raises(CalibrationError, match='не поддерживается'):
        prepare_calibrations(df, [{'channel': 'TV', 'date_from': '2024-06-30',
                                   'date_to': '2024-08-31', 'lift_abs': 1.0,
                                   'lift_low': 0.0, 'lift_high': 2.0,
                                   'confidence_level': 0.77}],
                             media_columns=['TV'], date_column='date')
    zero_spend = df.copy()
    zero_spend.loc[5:8, 'TV'] = 0.0
    with pytest.raises(CalibrationError, match='нет затрат'):
        prepare_calibrations(zero_spend,
                             [{'channel': 'TV', 'date_from': '2024-06-30',
                               'date_to': '2024-09-30', 'lift_abs': 1.0,
                               'sigma_abs': 1.0}],
                             media_columns=['TV'], date_column='date')
    assert prepare_calibrations(df, [], media_columns=['TV']) == []
    assert prepare_calibrations(df, None, media_columns=['TV']) == []


def test_ols_refuses_calibrations(tmp_path):
    """D-E2-4: OLS честно отказывается — у него нет вероятностной модели."""
    df = _df(30)
    f = tmp_path / 'd.xlsx'
    df.to_excel(f, index=False)
    from engines.ols_modeler import train_ols
    r = train_ols({
        'data_file': str(f), 'kpi_column': 'sales',
        'media_columns': ['TV', 'Digital'], 'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'TV': 'geometric', 'Digital': 'geometric'},
        'unit_costs': {}, 'merge_rules': {}, 'kpi_type': 'sales',
        'calibrations': [{'channel': 'TV', 'date_from': '2024-06-30',
                          'date_to': '2024-09-30', 'lift_abs': 1.0,
                          'sigma_abs': 1.0}],
    }, str(tmp_path / 'p'))
    assert r['status'] == 'error'
    assert r['error_code'] == 'CALIBRATION_REQUIRES_BAYESIAN'
    assert 'байесовскому' in r['message']


# ─── Характеризующий тест (критерий ROADMAP §E2) ────────────────────────────


def _geometric_adstock(x, decay):
    out = np.zeros_like(x, dtype=float)
    out[0] = x[0]
    for t in range(1, len(x)):
        out[t] = x[t] + decay * out[t - 1]
    return out


def _hill(x_norm, alpha, gamma):
    xs = np.maximum(x_norm, 0)
    return xs ** alpha / (xs ** alpha + gamma ** alpha + 1e-10)


@pytest.mark.slow
def test_calibrated_recovers_contribution_better(tmp_path):
    """Синтетика с зашитой истиной: TV и Digital сильно коррелированы →
    некалиброванная модель размывает вклад между ними; lift-тест по TV
    (истинный вклад за период, σ=15% от него) обязан подтянуть оценку
    ПОЛНОГО вклада TV ближе к истине. Сравнение — decompose (канонический
    путь чтения вкладов), критерий — |err_calib| < |err_uncalib|."""
    rng = np.random.default_rng(11)
    n = 26
    base_tv = np.clip(rng.normal(100, 22, n), 20, None)
    # Digital почти повторяет TV (r≈0.97) — коллинеарность размывает β.
    digital = np.clip(base_tv * 1.8 + rng.normal(0, 9, n), 30, None)
    tv = base_tv

    decay, alpha, gamma = 0.4, 1.5, 0.8
    beta_tv_norm, beta_dig_norm, intercept_norm = 0.9, 0.15, 0.0
    y_std_true, y_mean_true = 120.0, 1000.0

    ad_tv = _geometric_adstock(tv, decay)
    ad_dig = _geometric_adstock(digital, decay)
    sat_tv = _hill(ad_tv / ad_tv.mean(), alpha, gamma)
    sat_dig = _hill(ad_dig / ad_dig.mean(), alpha, gamma)
    noise = rng.normal(0, 0.18, n)
    y = (intercept_norm + beta_tv_norm * sat_tv + beta_dig_norm * sat_dig + noise) \
        * y_std_true + y_mean_true

    df = pd.DataFrame({
        'date': pd.date_range('2023-01-31', periods=n, freq='ME').strftime('%Y-%m-%d'),
        'TV': tv.round(2), 'Digital': digital.round(2), 'sales': y.round(2),
    })
    data_file = tmp_path / 'synत.xlsx'
    df.to_excel(data_file, index=False)

    # Истинный ПОЛНЫЙ вклад TV (native) — мишень восстановления.
    true_tv_total = float((beta_tv_norm * sat_tv).sum() * y_std_true)
    # Истинный lift за период теста (месяцы 12..18) — вход калибровки.
    t0, t1 = 12, 18
    true_lift = float((beta_tv_norm * sat_tv[t0:t1]).sum() * y_std_true)

    base_config = {
        'data_file': str(data_file), 'kpi_column': 'sales',
        'media_columns': ['TV', 'Digital'], 'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'TV': 'geometric', 'Digital': 'geometric'},
        'unit_costs': {}, 'merge_rules': {}, 'kpi_type': 'sales',
        'mcmc_override': {'chains': 2, 'draws': 600, 'tune': 600},
        'random_seed': 42,
    }
    from engines.modeler import train_model
    from engines.decomposer import decompose

    def tv_contribution(project_dir, config):
        r = train_model(config, project_dir)
        assert r.get('status') == 'ok', r.get('message')
        d = decompose(project_dir, save_results=False)
        assert d.get('status') == 'ok', d.get('message')
        ch = {c['name']: c for c in d['channels']}
        return float(ch['TV']['contribution'])

    contrib_uncalib = tv_contribution(str(tmp_path / 'p_un'), dict(base_config))

    calib_config = dict(base_config)
    calib_config['calibrations'] = [{
        'channel': 'TV',
        'date_from': str(df['date'].iloc[t0]),
        'date_to': str(df['date'].iloc[t1 - 1]),
        'lift_abs': true_lift,
        'sigma_abs': 0.15 * true_lift,
        'test_type': 'geo_lift',
    }]
    contrib_calib = tv_contribution(str(tmp_path / 'p_cal'), calib_config)

    err_un = abs(contrib_uncalib - true_tv_total)
    err_cal = abs(contrib_calib - true_tv_total)
    print(f'\nистина TV={true_tv_total:.0f} | без калибровки {contrib_uncalib:.0f} '
          f'(err {err_un:.0f}) | с калибровкой {contrib_calib:.0f} (err {err_cal:.0f})')
    assert err_cal < err_un, (
        f'Калибровка обязана приближать вклад к истине: err_calib {err_cal:.0f} '
        f'>= err_uncalib {err_un:.0f}'
    )


@pytest.mark.slow
def test_calibration_check_delivered(tmp_path):
    """diagnostics.calibration_check доставляется: канал, lift, CI, within_ci."""
    rng = np.random.default_rng(3)
    n = 24
    tv = np.clip(rng.normal(100, 20, n), 20, None)
    y = 1000 + 2.2 * tv + rng.normal(0, 25, n)
    df = pd.DataFrame({
        'date': pd.date_range('2023-01-31', periods=n, freq='ME').strftime('%Y-%m-%d'),
        'TV': tv.round(2), 'sales': y.round(2),
    })
    f = tmp_path / 'd.xlsx'
    df.to_excel(f, index=False)
    from engines.modeler import train_model
    r = train_model({
        'data_file': str(f), 'kpi_column': 'sales', 'media_columns': ['TV'],
        'control_columns': [], 'date_column': 'date',
        'adstock_config': {'TV': 'geometric'}, 'unit_costs': {},
        'merge_rules': {}, 'kpi_type': 'sales',
        'mcmc_override': {'chains': 2, 'draws': 400, 'tune': 400},
        'random_seed': 42,
        'calibrations': [{'channel': 'TV', 'date_from': str(df['date'].iloc[8]),
                          'date_to': str(df['date'].iloc[13]),
                          'lift_abs': 700.0, 'sigma_abs': 120.0}],
    }, str(tmp_path / 'p'))
    assert r.get('status') == 'ok', r.get('message')
    checks = (r.get('diagnostics') or {}).get('calibration_check')
    assert checks and checks[0]['channel'] == 'TV'
    assert checks[0]['test_lift'] == 700.0
    lo, hi = checks[0]['model_contrib_ci90']
    assert lo < hi
    assert isinstance(checks[0]['within_ci'], bool)
    applied = (r.get('diagnostics') or {}).get('calibration_applied')
    assert applied and applied[0]['channel'] == 'TV'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q', '-m', 'slow or not slow']))
