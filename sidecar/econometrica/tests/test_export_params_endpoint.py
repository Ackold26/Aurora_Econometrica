"""H-5: сторож для `POST /export/params` — обещанная клиенту выгрузка параметров
подключена к HTTP, а не только к движку.

Паспорт модели (`engines/methodology_cert.py::оговорка_о_выгрузке_параметров`)
обещает клиенту отдельную выгрузку по запросу. До этой правки движок
(`engines/json_export.py`) существовал и был покрыт тестами, но нигде в дереве
не вызывался вне самого модуля и тестов — обещание было мёртвым.

Три вещи, которые обязаны быть верны:
    1. обработчик отдаёт файл с непустыми параметрами на живой модели (не
       заглушку, не пустой каркас);
    2. поле, подставленное загрузчиком (`load_model_with_compat`), в выгрузке
       помечено как подставленное — а не как записанное обучением (защита
       от регресса Critical C-1, см. `test_json_export_loader_defaults.py`).
       Модель для этого приходит ТОЛЬКО с диска через загрузчик — голый
       `model_data` из тела запроса эту защиту обходит по построению, поэтому
       эндпойнт его сознательно не принимает (см. `ParamsExportRequest.__doc__`
       в server.py);
    3. отказ на несуществующем проекте — внятный статус/причина, не тишина
       и не 500 с трассировкой.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import app  # noqa: E402
from engines.json_export import ЗАПИСАНО, ПОДСТАВЛЕНО  # noqa: E402
from engines.persistence import write_pkl_sha256_sidecar  # noqa: E402
from engines.persistence_safe import save_model_safe  # noqa: E402

КАНАЛ = 'ТВ'


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _модель(**поля) -> dict:
    """Скелет файла модели: канал с реальными коэффициентами + KPI-поля не
    заданы (загрузчик подставит kpi_type='sales' и т.п. сам — это и есть
    случай, который проверка №2 обязана поймать)."""
    модель = {
        'config': {
            'kpi_column': 'Продажи',
            'media_columns': [КАНАЛ],
            'date_column': 'Дата',
        },
        'channel_params': {
            КАНАЛ: {
                'beta': 0.42,
                'alpha': 1.5,
                'gamma': 0.5,
                'decay': 0.25,
                'adstock': {'type': 'geometric'},
            },
        },
        'normalization': {
            'y_mean': 100.0,
            'y_std': 10.0,
            'media_means': {КАНАЛ: 5.0},
        },
        'y_actual': [1.0, 2.0, 3.0],
    }
    модель.update(поля)
    return модель


def _project(tmp_path: Path, model: dict) -> Path:
    """Настоящий файл модели на диске — обработчик обязан читать именно его."""
    model_path = tmp_path / 'models' / 'latest.pkl'
    model_path.parent.mkdir(parents=True, exist_ok=True)
    save_model_safe(model, model_path)
    write_pkl_sha256_sidecar(model_path)
    return tmp_path


# ── 1 + 2: живая модель → непустые параметры, подстановка не выдана за запись ──

def test_export_params_returns_real_file_with_nonnull_coefficients_and_marks_loader_defaults(
    client, tmp_path,
):
    project_dir = _project(tmp_path, _модель())  # без kpi_type/kpi_likelihood/model_version

    resp = client.post('/export/params', json={
        'project_id': 'proj-1',
        'project_dir': str(project_dir),
    })
    body = resp.json()

    assert resp.status_code == 200, body
    assert body['status'] == 'ok'
    output_path = Path(body['path'])
    assert output_path.exists(), 'обработчик отчитался об успехе, но файла на диске нет'

    # Красная линия: доказательство читается с ДИСКА, не из ответа HTTP.
    документ = json.loads(output_path.read_text(encoding='utf-8'))

    # (1) непустые параметры канала на живой модели.
    канал = документ['channels'][КАНАЛ]
    assert канал['beta'] == pytest.approx(0.42)
    assert канал['origin']['beta'] == ЗАПИСАНО

    # (2) поле, подставленное загрузчиком (kpi_type не было в файле модели, как
    # и per_channel_input у канала), помечено как ПОДСТАВЛЕНО, а не выдано за
    # запись обучения — ни на верхнем уровне kpi.*, ни на уровне канала.
    assert документ['kpi']['type'] is None, 'умолчание загрузчика ушло в документ как значение'
    assert документ['kpi']['type_origin'] == ПОДСТАВЛЕНО
    assert канал['unit_kind'] is None
    assert канал['origin']['unit_kind'] == ПОДСТАВЛЕНО
    отсутствующие = {запись['field'] for запись in документ['absent_fields']}
    assert 'kpi.type' in отсутствующие, 'подстановка обязана быть названа в absent_fields'
    assert f'channels["{КАНАЛ}"].unit_kind' in отсутствующие


def test_export_params_records_written_field_as_written_not_defaulted(client, tmp_path):
    """Контрольный прогон: если поле ЗАПИСАНО в файле модели, подстановкой оно
    не считается — иначе проверка №2 ловила бы всё подряд без разбора."""
    project_dir = _project(tmp_path, _модель(kpi_type='sales', kpi_kind='monetary',
                                              kpi_likelihood='normal', model_version='2.0.0'))

    resp = client.post('/export/params', json={
        'project_id': 'proj-2',
        'project_dir': str(project_dir),
    })
    документ = json.loads(Path(resp.json()['path']).read_text(encoding='utf-8'))

    assert документ['kpi']['type'] == 'sales'
    assert документ['kpi']['type_origin'] == ЗАПИСАНО


# ── 3: несуществующий проект — внятный отказ ──────────────────────────────────

def test_export_params_on_missing_project_is_explicit_not_silent(client, tmp_path):
    missing_dir = tmp_path / 'нет-такого-проекта'

    resp = client.post('/export/params', json={
        'project_id': 'proj-ghost',
        'project_dir': str(missing_dir),
    })
    body = resp.json()

    assert resp.status_code == 404
    assert body['status'] == 'error'
    assert body['error_code'] == 'MODEL_NOT_FOUND'
    assert body['message'], 'отказ обязан объяснять причину, не молчать'
