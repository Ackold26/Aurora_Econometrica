"""К-4 (внешний аудит, 2026-07-27): подмена класса ответа НЕ покрывает
обработчики, возвращающие ГОЛЫЙ СЛОВАРЬ (`return {...}` / `return result`,
без явного `JSONResponse(...)`). Такие ответы сериализует сама FastAPI через
`default_response_class` приложения - подкласс `JSONResponse` с дезинфекцией
non-finite (см. коммит 5455336, класс задачи 5) туда не попадает, если явно
не назначен приложению.

Правка (найдена и застейджена другим исполнителем, проверена этим фиксом):
`server.py::app = FastAPI(..., default_response_class=JSONResponse)` -
штатный параметр FastAPI, задающий класс ответа по умолчанию для ВСЕХ
маршрутов, не переопределяющих response_class индивидуально (в server.py
таких переопределений нет - проверено грепом `response_class=`).

Живой пример - `/compute/model_history` (server.py:1999): при вырожденной
модели (NaN в r_squared) до этой правки бросал 500 'Out of range float
values are not JSON compliant', а `default_response_class` даёт честный
`null` (INV: «нет числа - нет подписи», а не крэш и не 500 вместо ответа).
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _write_history_with_nan_metric(tmp_path):
    history_dir = tmp_path / 'models' / 'history'
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'diagnostics': {
            'mqs': {'score': 40, 'tier_label': 'Слабое'},
            # allow_nan=True (дефолт json.dump) - именно так на диске мог
            # оказаться литерал NaN из вырожденного расчёта; json.load читает
            # его штатно (decoder принимает NaN/Infinity независимо от
            # allow_nan, тот управляет только encoder'ом).
            'metrics': {'r_squared': float('nan'), 'mape_pct': 12.3},
        },
        'channel_params': {'tv': {}},
        'config': {},
    }
    with open(history_dir / 'params-20260101_000000.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, allow_nan=True)


class TestBareDictHandlerSanitizesNonFinite:

    def test_model_history_survives_nan_metric_via_default_response_class(self, client, tmp_path):
        """До правки: 500 'Out of range float values are not JSON compliant:
        nan'. После: 200, r_squared честно null (не 0, не 'nan', не крэш)."""
        _write_history_with_nan_metric(tmp_path)
        resp = client.post('/compute/model_history', json={'project_dir': str(tmp_path)})
        assert resp.status_code == 200, (
            f'Ожидался честный ответ, получено {resp.status_code}: {resp.text}'
        )
        body = resp.json()
        assert body['status'] == 'ok'
        assert body['versions'][0]['r_squared'] is None
        # Настоящее число рядом (mape_pct=12.3) не задето санацией.
        assert body['versions'][0]['mape'] == 12.3
        # NaN не должен утечь в тело ответа ни в каком виде (число/строка).
        assert not re.search(r'\bnan\b', resp.text, re.IGNORECASE)

    def test_normal_history_unaffected(self, client, tmp_path):
        """Регресс-контроль: обычная (конечная) метрика проходит как есть."""
        history_dir = tmp_path / 'models' / 'history'
        history_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'diagnostics': {
                'mqs': {'score': 87, 'tier_label': 'Хорошее'},
                'metrics': {'r_squared': 0.9134, 'mape_pct': 6.7},
            },
            'channel_params': {'tv': {}},
            'config': {},
        }
        with open(history_dir / 'params-20260102_000000.json', 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        resp = client.post('/compute/model_history', json={'project_dir': str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()['versions'][0]['r_squared'] == 0.9134

    def test_status_codes_of_bare_dict_handlers_unaffected(self, client):
        """Регресс-контроль п.2 (координатор): коды состояния не сломаны -
        bare-dict хендлер (train_cancel на несуществующий task_id) по-прежнему
        200 с ожидаемым телом, неизвестный маршрут - штатные 404 FastAPI (не
        наш класс ответа - подмена default_response_class их не касается)."""
        r = client.post('/compute/train/cancel/does-not-exist')
        assert r.status_code == 200
        assert r.json() == {'status': 'not_found'}

        r404 = client.get('/no-such-route-at-all')
        assert r404.status_code == 404

    def test_explicit_status_code_from_middleware_unaffected(self, client):
        """Регресс-контроль: явный status_code=409 из session_guard
        (handshake protection, server.py) по-прежнему доезжает как есть -
        default_response_class не подменяет и не глушит статус для явных
        JSONResponse(status_code=...). '/health' и '/shutdown' сами исключены
        из гейта (см. session_guard), поэтому проверяем на обычном маршруте."""
        r = client.post(
            '/compute/recommend',
            json={'n_obs': 50},
            headers={'X-Expected-Session': 'not-the-real-session-id'},
        )
        assert r.status_code == 409
        assert r.json()['status'] == 'session_mismatch'
