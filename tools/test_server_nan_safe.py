"""F-MC-1 (2026-07-04, Венарус-зонд): NaN в HTTP-ответах train-семейства.

Файлы санитайзились (NaN→null), а ответы endpoints — нет: NaN в диагностике
(вырожденный канал) валил сериализацию 500-кой «Out of range float values»
прямо на кнопке «Обучить». Тест фиксирует класс на шве: движок вернул NaN →
endpoint обязан отдать 200 с null.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from server import app
    return TestClient(app)


def test_train_response_nan_sanitized(client, monkeypatch):
    import engines.modeler as modeler

    def fake_train(config, project_dir):
        return {
            'status': 'ok',
            'diagnostics': {'metrics': {
                'r_hat_max': float('nan'),
                'ess_min': float('inf'),
                'r_squared': 0.9,
            }},
        }

    monkeypatch.setattr(modeler, 'train_model', fake_train)
    r = client.post('/compute/train', json={
        'project_dir': 'x', 'data_file': 'x.xlsx', 'kpi_column': 'sales',
        'media_columns': ['TV'],
    })
    assert r.status_code == 200, r.text
    m = r.json()['diagnostics']['metrics']
    assert m['r_hat_max'] is None, 'NaN обязан стать null'
    assert m['ess_min'] is None, 'Inf обязан стать null'
    assert m['r_squared'] == 0.9


def test_decompose_response_nan_sanitized(client, monkeypatch):
    import engines.decomposer as decomposer

    def fake_decompose(project_dir, **kw):
        return {'status': 'ok', 'channels': [{'name': 'TV', 'roi': float('nan')}]}

    monkeypatch.setattr(decomposer, 'decompose', fake_decompose)
    r = client.post('/compute/decompose', json={'project_dir': 'x'})
    assert r.status_code == 200, r.text
    assert r.json()['channels'][0]['roi'] is None


def test_sanitize_helper_contract():
    from utils.safe_io import sanitize_nonfinite
    out = sanitize_nonfinite({'a': float('nan'), 'b': [1.0, float('inf')], 'c': 'x'})
    assert out['a'] is None and out['b'][1] is None and out['c'] == 'x'
    assert not any(
        isinstance(v, float) and not math.isfinite(v)
        for v in [out['a'] or 0.0, *out['b'][:1]]
    )


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
