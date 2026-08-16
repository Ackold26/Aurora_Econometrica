"""Сторож: умолчание загрузчика не уезжает в документ под видом записи модели.

Critical C-1 внешнего аудита 2026-08-16. Загрузчик моделей
(`engines/persistence.load_model_with_compat`) при чтении файла сам подставляет
`kpi_type='sales'`, `kpi_likelihood='normal'`, `kpi_kind`, `model_version='1.0'`,
`per_channel_input`. Выгрузка параметров метила эти значения как «прочитано из
файла модели как есть», и модель, обученная на знании марки, уходила третьей
стороне моделью продаж, а `absent_fields` про KPI молчал.

🔴 Модель здесь ВСЕГДА проходит через `load_model_with_compat` и настоящее
сохранение. Прежний сторож (`test_json_export_params.py`) кормил выгрузку голым
словарём и подстановку увидеть не мог по построению: продукт читает модель
только загрузчиком, а голый словарь загрузчик обходит.

Что доказывается:
    1. у модели без верхнеуровневых полей KPI документ не называет тип, род и
       правдоподобие записанными и перечисляет их в absent_fields;
    2. записанный тип KPI остаётся записанным – защита не съедает правду там,
       где значение в модели есть;
    3. то же для версии схемы модели и для единиц каналов;
    4. след подстановки переживает пересохранение модели: `save_v20_diagnostics`
       и `clear_sensitivity_cache` пишут в файл УЖЕ ЗАГРУЖЕННУЮ модель вместе с
       подставленными значениями, и без сохранения следа умолчание после первого
       же такого сохранения стало бы неотличимо от записи обучения.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.json_export import (  # noqa: E402
    ЗАПИСАНО,
    ПОДСТАВЛЕНО,
    export_model_params_json,
)
from engines.persistence import load_model_with_compat, write_pkl_sha256_sidecar  # noqa: E402
from engines.persistence_safe import save_model_safe  # noqa: E402

КАНАЛ = 'ТВ'


def _модель(**поля) -> dict:
    """Скелет файла модели: только то, что читает выгрузка параметров."""
    модель = {
        'config': {
            'kpi_column': 'Продажи',
            'media_columns': [КАНАЛ],
            'date_column': 'Дата',
        },
        'channel_params': {
            КАНАЛ: {
                'beta': 0.1,
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


def _сохранить(каталог: Path, модель: dict) -> Path:
    путь = каталог / 'models' / 'latest.pkl'
    путь.parent.mkdir(parents=True, exist_ok=True)
    save_model_safe(модель, путь)
    write_pkl_sha256_sidecar(путь)
    return путь


def _выгрузка(каталог: Path, модель: dict) -> dict:
    """Полный путь продукта: сохранение → штатный загрузчик → выгрузка."""
    путь = _сохранить(каталог, модель)
    return json.loads(export_model_params_json(load_model_with_compat(путь)))


def _отсутствующие(документ: dict) -> dict[str, str]:
    return {запись['field']: запись['reason'] for запись in документ['absent_fields']}


# ── 1. Подстановка не выдаётся за запись ─────────────────────────────────────

@pytest.mark.parametrize(
    'поле_документа, ключ_значения',
    [('kpi.type', 'type'), ('kpi.kind', 'kind'), ('kpi.likelihood', 'likelihood')],
)
def test_поле_kpi_подставленное_загрузчиком_не_называется_записанным(
    tmp_path, поле_документа, ключ_значения
):
    """Модель без полей KPI: документ обязан молчать о типе, а не сочинять продажи."""
    документ = _выгрузка(tmp_path, _модель(model_version='1.2-ols'))

    kpi = документ['kpi']
    assert kpi[ключ_значения] is None, 'подставленное загрузчиком значение уехало в документ'
    assert kpi[f'{ключ_значения}_origin'] == ПОДСТАВЛЕНО
    отсутствующие = _отсутствующие(документ)
    assert поле_документа in отсутствующие, 'подстановка обязана быть названа в absent_fields'
    assert 'загрузчик' in отсутствующие[поле_документа]


def test_род_величины_kpi_подставлен_и_в_unit_kind(tmp_path):
    """`unit_kind` – то же значение под другим именем, и лгать оно тоже не вправе."""
    документ = _выгрузка(tmp_path, _модель())

    assert документ['kpi']['unit_kind'] is None
    assert документ['kpi']['unit_kind_origin'] == ПОДСТАВЛЕНО


def test_версия_схемы_подставленная_загрузчиком_не_называется_записанной(tmp_path):
    """Загрузчик кладёт '1.0' моделям, где версии нет, – это не запись обучения."""
    документ = _выгрузка(tmp_path, _модель())

    assert документ['model']['version'] is None
    assert документ['model']['version_origin'] == ПОДСТАВЛЕНО
    assert 'model.version' in _отсутствующие(документ)


def test_единицы_каналов_подставленные_загрузчиком_не_называются_записанными(tmp_path):
    """Нет `per_channel_input` – загрузчик объявляет все каналы денежными."""
    документ = _выгрузка(tmp_path, _модель())

    канал = документ['channels'][КАНАЛ]
    assert канал['unit_kind'] is None
    assert канал['origin']['unit_kind'] == ПОДСТАВЛЕНО
    assert f'channels["{КАНАЛ}"].unit_kind' in _отсутствующие(документ)


# ── 2. Правда там, где значение записано ─────────────────────────────────────

def test_записанные_поля_kpi_остаются_записанными(tmp_path):
    """Защита не вправе стирать правду: записанное в файле – записано."""
    документ = _выгрузка(tmp_path, _модель(
        kpi_type='awareness',
        kpi_kind='proportional',
        kpi_likelihood='beta',
        model_version='2.0.0',
        per_channel_input={КАНАЛ: 'physical'},
    ))

    kpi = документ['kpi']
    assert (kpi['type'], kpi['type_origin']) == ('awareness', ЗАПИСАНО)
    assert (kpi['kind'], kpi['kind_origin']) == ('proportional', ЗАПИСАНО)
    assert (kpi['unit_kind'], kpi['unit_kind_origin']) == ('proportional', ЗАПИСАНО)
    assert (kpi['likelihood'], kpi['likelihood_origin']) == ('beta', ЗАПИСАНО)
    assert (документ['model']['version'], документ['model']['version_origin']) == ('2.0.0', ЗАПИСАНО)
    канал = документ['channels'][КАНАЛ]
    assert (канал['unit_kind'], канал['origin']['unit_kind']) == ('physical', ЗАПИСАНО)
    отсутствующие = _отсутствующие(документ)
    assert not [поле for поле in отсутствующие if поле.startswith('kpi.type')]


# ── 3. Пересохранение не отбеливает подстановку ──────────────────────────────

def test_след_подстановки_переживает_пересохранение_модели(tmp_path):
    """`save_v20_diagnostics` пишет загруженную модель обратно в файл вместе с
    подставленным 'sales'. Без следа второе чтение объявило бы его записью."""
    путь = _сохранить(tmp_path, _модель())

    первое_чтение = load_model_with_compat(путь)
    assert первое_чтение['kpi_type'] == 'sales', 'умолчание загрузчика не изменилось'
    save_model_safe(первое_чтение, путь)          # тот же путь, что у save_v20_diagnostics
    write_pkl_sha256_sidecar(путь)

    документ = json.loads(export_model_params_json(load_model_with_compat(путь)))
    assert документ['kpi']['type'] is None
    assert документ['kpi']['type_origin'] == ПОДСТАВЛЕНО
