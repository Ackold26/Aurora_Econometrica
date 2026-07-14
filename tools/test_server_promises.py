"""E4 (2026-07-03): endpoints прогнозов-обещаний — контракт доставки.

«Зафиксировать прогноз» (create) → список → сверка фактом (check):
валидация 422 (короткое действие, кривой горизонт), 404 NO_DATA/NO_MODEL,
полный цикл pending → kept на живых данных фикстуры.
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
from test_promises import _append_tail  # noqa: E402


@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


def test_validation_422(client):
    r = client.post('/compute/promises/create', json={
        'project_dir': 'x', 'action_text': 'аб',  # < 3 символов
        'expected_kpi_total': 1.0, 'horizon_periods': 4,
    })
    assert r.status_code == 422
    r = client.post('/compute/promises/create', json={
        'project_dir': 'x', 'action_text': 'Сдвинуть бюджет',
        'expected_kpi_total': 1.0, 'horizon_periods': 0,
    })
    assert r.status_code == 422
    assert client.post('/compute/promises', json={}).status_code == 422


def test_create_no_data_404(client, tmp_path):
    empty = tmp_path / 'empty'
    (empty / 'models').mkdir(parents=True)
    r = client.post('/compute/promises/create', json={
        'project_dir': str(empty), 'action_text': 'Сдвинуть бюджет',
        'expected_kpi_total': 100.0, 'horizon_periods': 4,
    })
    assert r.status_code == 404
    assert r.json()['error_code'] == 'NO_DATA'


def test_check_empty_list_is_ok_without_model(client, tmp_path):
    """Нет обещаний — нечего сверять: ok без требования модели (ранний выход)."""
    empty = tmp_path / 'nomodel'
    empty.mkdir()
    r = client.post('/compute/promises/check', json={'project_dir': str(empty)})
    assert r.status_code == 200
    assert r.json() == {'status': 'ok', 'promises': [], 'total': 0, 'checked': 0}


def test_check_no_model_404_when_promises_exist(client, tmp_path):
    """Обещания есть, модели нет → честный 404 NO_MODEL."""
    import json as _json
    pdir = tmp_path / 'orphan'
    (pdir / 'results').mkdir(parents=True)
    (pdir / 'results' / 'promises.json').write_text(_json.dumps([{
        'id': 'x1', 'status': 'pending',
        'expected': {'horizon_periods': 4}, 'check_after_index': 10,
    }]), encoding='utf-8')
    r = client.post('/compute/promises/check', json={'project_dir': str(pdir)})
    assert r.status_code == 404
    assert r.json()['error_code'] == 'NO_MODEL'


def test_full_cycle_create_list_check(client, tmp_path):
    pdir = _make_ols_project(tmp_path, 'cycle')  # 40 наблюдений
    r = client.post('/compute/promises/create', json={
        'project_dir': str(pdir),
        'action_text': 'Сдвинуть 10% бюджета с Digital на TV',
        'expected_kpi_total': 4000.0, 'ci_low': 3600.0, 'ci_high': 4400.0,
        'horizon_periods': 4,
        'channel_changes': {'TV': 10.0, 'Digital': -10.0},
        'extrapolation_flag': True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    pid = body['promise']['id']
    assert body['promise']['check_after_index'] == 40
    assert body['promise']['extrapolation_flag'] is True

    lst = client.post('/compute/promises', json={'project_dir': str(pdir)}).json()
    assert lst['total'] == 1 and lst['promises'][0]['id'] == pid

    # Данных ещё нет → pending со счётчиком
    chk = client.post('/compute/promises/check', json={'project_dir': str(pdir)}).json()
    assert chk['checked'] == 0
    assert 'Свежих периодов 0 из 4' in chk['promises'][0]['verdict_note']

    # Клиент принёс 4 свежих строки (сумма 4040 внутри CI) → kept
    _append_tail(pdir, [1000.0, 1010.0, 1015.0, 1015.0])
    chk2 = client.post('/compute/promises/check', json={'project_dir': str(pdir)}).json()
    assert chk2['checked'] == 1
    p = chk2['promises'][0]
    assert p['status'] == 'kept' and p['status_ru'] == 'сбылось'
    assert p['actual_kpi_total'] == pytest.approx(4040.0)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
