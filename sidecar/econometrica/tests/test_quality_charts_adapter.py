"""Графики качества модели (2026-09-11, задача владельца): ряд «факт против
прогноза» + остатки в общем адаптере narrative_adapter._map_pipeline_to_builder_data.

Источник ряда — engines/modeler.py:1538-1542
(diagnostics['actual_vs_predicted'] = {'actual', 'predicted', 'dates'}).
Остатки движком отдельно не хранятся — адаптер считает их один раз
(actual[i] - predicted[i]), и этим же результатом пользуются ОБА выхода
(pptx_export.py и html_export.py импортируют одну и ту же функцию).

Стережём: (1) ряд и остатки доезжают до diagnostics при корректных входных
списках; (2) остатки посчитаны верно (не переставлены местами факт/прогноз);
(3) ряд ОТСУТСТВУЕТ (а не рисуется пустым/сломанным), когда источник пуст,
неполон или длины не совпадают — «график только если есть данные» начинается
уже здесь, на входе в адаптер.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.narrative_adapter import _map_pipeline_to_builder_data  # noqa: E402


def _собрать(actual_vs_predicted):
    model_data = {"diagnostics": {"actual_vs_predicted": actual_vs_predicted}}
    return _map_pipeline_to_builder_data(model_data, {}, {}, None, project_id="проверка")


def test_ряд_и_остатки_доезжают_до_diagnostics():
    данные = _собрать({
        "dates": ["2024-01-01", "2024-01-08", "2024-01-15"],
        "actual": [100.0, 110.0, 90.0],
        "predicted": [95.0, 108.0, 100.0],
    })
    avp = данные["diagnostics"]["actual_vs_predicted"]
    assert avp["dates"] == ["2024-01-01", "2024-01-08", "2024-01-15"]
    assert avp["actual"] == [100.0, 110.0, 90.0]
    assert avp["predicted"] == [95.0, 108.0, 100.0]
    # Остатки = факт - прогноз, в ТОМ порядке (не прогноз - факт).
    assert avp["residuals"] == [5.0, 2.0, -10.0]


def test_остатки_не_округляются_сверх_источника():
    данные = _собрать({
        "dates": ["2024-01-01", "2024-01-08"],
        "actual": [100.1234, 90.0],
        "predicted": [95.0001, 100.0],
    })
    avp = данные["diagnostics"]["actual_vs_predicted"]
    assert avp["residuals"][0] == 100.1234 - 95.0001
    assert avp["residuals"][1] == -10.0


def test_ряд_отсутствует_когда_источника_нет_вовсе():
    данные = _map_pipeline_to_builder_data(
        {"diagnostics": {}}, {}, {}, None, project_id="проверка",
    )
    assert "actual_vs_predicted" not in данные.get("diagnostics", {})


def test_ряд_отсутствует_при_пустых_списках():
    данные = _собрать({"dates": [], "actual": [], "predicted": []})
    assert "actual_vs_predicted" not in данные.get("diagnostics", {})


def test_ряд_отсутствует_при_несовпадении_длин():
    """Испорченный источник (даты короче факта/прогноза) не должен долетать
    до отчётов половинчатым рядом — либо ряд целый, либо его нет вовсе."""
    данные = _собрать({
        "dates": ["2024-01-01", "2024-01-08"],
        "actual": [100.0, 110.0, 90.0],
        "predicted": [95.0, 108.0, 100.0],
    })
    assert "actual_vs_predicted" not in данные.get("diagnostics", {})


def test_ряд_отсутствует_когда_predicted_не_список():
    """Защита от испорченного типа поля (например, число вместо списка) —
    адаптер не должен падать, секция просто не строится."""
    данные = _собрать({
        "dates": ["2024-01-01"],
        "actual": [100.0],
        "predicted": None,
    })
    assert "actual_vs_predicted" not in данные.get("diagnostics", {})
