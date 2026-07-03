"""E1 (2026-07-03): endpoint /compute/backtest — контракт доставки витрины.

Проверяет проводку слоя server: валидация запроса (422 на мусор), честные
404 (NO_MODEL/NO_DATA), insufficient как результат (200, не сбой), read_only
мгновенное чтение сохранённой витрины, боевой OLS-прогон через TestClient.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_rolling_backtest import _make_ols_project  # noqa: E402


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


# ─── Валидация запроса (pydantic → 422) ──────────────────────────────────────


def test_validation_422_on_junk(client):
    for bad in (
        {'project_dir': 'x', 'mode': 'quantum'},          # mode вне Literal
        {'project_dir': 'x', 'max_windows': 1},           # ge=3
        {'project_dir': 'x', 'max_windows': 99},          # le=12
        {'project_dir': 'x', 'horizon_periods': 0},       # ge=1
        {'project_dir': 'x', 'min_train': 3},             # ge=8
        {},                                                # project_dir обязателен
    ):
        r = client.post('/compute/backtest', json=bad)
        assert r.status_code == 422, f'{bad} → {r.status_code}'


# ─── Честные отказы ──────────────────────────────────────────────────────────


def test_no_model_404_russian(client, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    r = client.post('/compute/backtest', json={'project_dir': str(empty)})
    assert r.status_code == 404
    body = r.json()
    assert body['error_code'] == 'NO_MODEL'
    assert 'обучите модель' in body['message']


def test_no_data_404_russian(client, tmp_path):
    pdir = _make_ols_project(tmp_path, 'lost')
    (pdir / 'data.xlsx').rename(tmp_path / 'gone.xlsx')
    r = client.post('/compute/backtest', json={'project_dir': str(pdir)})
    assert r.status_code == 404
    body = r.json()
    assert body['error_code'] == 'NO_DATA'
    assert 'Errno' not in body['message']


def test_insufficient_is_200_result(client, tmp_path):
    """«Истории недостаточно» — честный результат проверки, не сбой."""
    pdir = _make_ols_project(tmp_path, 'short', n_obs=18)
    r = client.post('/compute/backtest', json={'project_dir': str(pdir)})
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'insufficient'
    assert 'Истории недостаточно' in body['message']


def test_read_only_not_found(client, tmp_path):
    empty = tmp_path / 'no_vitrina'
    empty.mkdir()
    r = client.post('/compute/backtest', json={
        'project_dir': str(empty), 'read_only': True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'not_found'
    assert 'не проводилась' in body['message']


# ─── Боевой путь через endpoint ──────────────────────────────────────────────


def test_happy_ols_and_read_only_roundtrip(client, tmp_path):
    pdir = _make_ols_project(tmp_path, 'happy')
    r = client.post('/compute/backtest', json={
        'project_dir': str(pdir), 'max_windows': 4,
    })
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert body['mode'] == 'ols'
    assert body['n_windows'] >= 3
    assert body['verdict'] in {'validated', 'coverage_low', 'worse_than_naive'}
    assert body['coverage_per_period'] is not None
    assert body['saved_to'], 'витрина обязана сохраниться'

    # read_only отдаёт РОВНО сохранённое (без пересчёта)
    r2 = client.post('/compute/backtest', json={
        'project_dir': str(pdir), 'read_only': True,
    })
    assert r2.status_code == 200
    saved = r2.json()
    assert saved['generated_at'] == body['generated_at']
    assert saved['mape_model'] == body['mape_model']


def test_friendly_error_envelope():
    """П6: generic-500 конверт человеческий — что случилось + что делать;
    техдеталь усечена, пустое исключение не рождает пустоту."""
    from server import _friendly_error
    msg = _friendly_error(ValueError('division by zero in xyz'))
    assert 'division by zero' in msg
    assert 'Повторите действие' in msg and 'поддержку' in msg
    long = _friendly_error(RuntimeError('x' * 500))
    assert len(long) < 400, 'техдеталь обязана усекаться'
    empty = _friendly_error(KeyError())
    assert 'KeyError' in empty, 'пустое исключение → хотя бы тип'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
