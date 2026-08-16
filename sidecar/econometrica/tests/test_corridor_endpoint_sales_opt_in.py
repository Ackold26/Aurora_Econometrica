"""🔴 F-08 (внешний аудит 2026-08-16): коридор не платит за то, чего не просили.

Точка `/optimize/corridor` была дешёвой (перцентили по прочитанным данным). С
появлением `aggregate_sales` каждый вызов стал поднимать прямой проход: чтение
`models/latest.pkl` + повторное чтение файла данных + три прохода — ×4,8 к времени
ответа (замер аудитора на проекте в 31 строку: 0,047 → 0,228 с), причём за поле,
которого интерфейс ещё не показывает.

Продажи считаются только по явному `include_sales=true`. Без него поле не молчит
и не отдаёт нулей — отдаёт статус `not_requested` с причиной.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _project(tmp_path: Path) -> dict:
    """Проект с моделью-пустышкой (загрузчик подменён) и файлом данных."""
    (tmp_path / 'models').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'models' / 'latest.pkl').write_bytes(b'')
    data_file = tmp_path / 'data.csv'
    data_file.write_text(
        'TV,Digital\n100,50\n120,60\n90,40\n110,55\n130,65\n95,45\n105,52\n115,58\n',
        encoding='utf-8',
    )
    return {'config': {'media_columns': ['TV', 'Digital'],
                       'data_file': str(data_file)}}


@pytest.fixture
def forward_calls(monkeypatch, tmp_path):
    """Считает, сколько раз поднимался прямой проход."""
    import math

    calls: list[str] = []
    model_data = _project(tmp_path)  # файлы должны лежать ДО запроса

    def _build(project_dir, unit_costs_override=None):
        calls.append(str(project_dir))

        def forward(budget: float):
            b = max(float(budget), 0.0)
            return {'expected_sales': 5.0e6 + 3000.0 * math.sqrt(b),
                    'distribution': {}, 'status': 'ok'}

        return forward, {'n_periods': 8, 'baseline_total': 5.0e6,
                         'current_total_money': 1.0e6}

    monkeypatch.setattr('optimize.inverse.build_proportional_forward', _build)
    monkeypatch.setattr('optimize.inverse._resolve_current_unit_costs',
                        lambda project_dir, cfg, override=None: {})
    monkeypatch.setattr('engines.persistence.load_model_with_compat',
                        lambda path: model_data)
    return calls


def test_corridor_without_include_sales_does_not_touch_the_model(
        client, forward_calls, tmp_path):
    """Дефолт: продаж не просили → прямой проход не поднимается вовсе."""
    resp = client.post('/optimize/corridor', json={'project_dir': str(tmp_path)})

    body = resp.json()
    assert resp.status_code == 200
    assert body['status'] == 'ok'
    assert body['aggregate_budget']['current'] > 0
    assert body['aggregate_sales']['status'] == 'not_requested'
    assert body['aggregate_sales']['reason'] == 'include_sales_off'
    assert forward_calls == [], 'прямой проход поднялся без запроса продаж'


def test_corridor_with_include_sales_computes_them(client, forward_calls, tmp_path):
    """По явному запросу продажи считаются — один подъём прохода на вызов."""
    resp = client.post('/optimize/corridor',
                       json={'project_dir': str(tmp_path), 'include_sales': True})

    body = resp.json()
    assert resp.status_code == 200
    sales = body['aggregate_sales']
    assert sales['status'] == 'ok'
    assert sales['sales']['lo'] < sales['sales']['hi']
    assert len(forward_calls) == 1
