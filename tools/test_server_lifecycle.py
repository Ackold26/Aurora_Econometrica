"""E3 (2026-07-03): endpoints жизненного цикла модели — контракт доставки.

/compute/generation-compare (+read_only) и /compute/drift-check: валидация
(422 на мусорный baseline_ts), честные 404 (NO_MODEL/GENERATION_NOT_FOUND),
insufficient = 200-результат, боевой OLS-путь на двух поколениях.
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
from test_model_compare import _retrain_with_new_tail  # noqa: E402


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


@pytest.fixture(scope='module')
def gen_project(tmp_path_factory):
    """Проект с двумя поколениями (архив создаётся авто-архивацией ретрейна)."""
    base = tmp_path_factory.mktemp('srv_gen')
    pdir = _make_ols_project(base, 'proj')
    _retrain_with_new_tail(pdir)
    return pdir


def test_validation_422_on_junk_ts(client):
    for path in ('/compute/generation-compare', '/compute/drift-check'):
        r = client.post(path, json={'project_dir': 'x', 'baseline_ts': 'мусор'})
        assert r.status_code == 422, f'{path}: {r.status_code}'
        r2 = client.post(path, json={})
        assert r2.status_code == 422


def test_no_model_404(client, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    for path in ('/compute/generation-compare', '/compute/drift-check'):
        r = client.post(path, json={'project_dir': str(empty)})
        assert r.status_code == 404, path
        assert r.json()['error_code'] == 'NO_MODEL'


def test_insufficient_is_200(client, tmp_path):
    pdir = _make_ols_project(tmp_path, 'nohist')
    for path in ('/compute/generation-compare', '/compute/drift-check'):
        r = client.post(path, json={'project_dir': str(pdir)})
        assert r.status_code == 200, path
        assert r.json()['status'] == 'insufficient'


def test_generation_not_found_404(client, gen_project):
    r = client.post('/compute/generation-compare', json={
        'project_dir': str(gen_project), 'baseline_ts': '19990101_000000',
    })
    assert r.status_code == 404
    assert r.json()['error_code'] == 'GENERATION_NOT_FOUND'


def test_happy_compare_and_read_only(client, gen_project):
    r = client.post('/compute/generation-compare', json={'project_dir': str(gen_project)})
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert len(body['channels']) == 2
    assert body['summary']['headline']
    assert body['saved_to']

    r2 = client.post('/compute/generation-compare', json={
        'project_dir': str(gen_project), 'read_only': True,
    })
    assert r2.status_code == 200
    assert r2.json()['generated_at'] == body['generated_at']


def test_read_only_not_found(client, tmp_path):
    pdir = tmp_path / 'no_cmp'
    pdir.mkdir()
    r = client.post('/compute/generation-compare', json={
        'project_dir': str(pdir), 'read_only': True,
    })
    assert r.status_code == 200
    assert r.json()['status'] == 'not_found'


def test_happy_drift(client, gen_project):
    r = client.post('/compute/drift-check', json={'project_dir': str(gen_project)})
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert body['verdict'] in {'fresh_ok', 'retrain_recommended'}
    assert body['n_tail_points'] == 6
    assert 'thresholds' in body


def test_model_history_lists_generation(client, gen_project):
    """F-E3-1/F-E3-2: history-endpoint видит OLS-поколение (params-снимок есть)."""
    r = client.post('/compute/model_history', json={'project_dir': str(gen_project)})
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert len(body['versions']) == 1
    v = body['versions'][0]
    assert v['n_channels'] == 2
    assert v['r_squared'] is not None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
