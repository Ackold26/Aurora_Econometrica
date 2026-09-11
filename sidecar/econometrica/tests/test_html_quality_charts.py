"""Графики качества модели в веб-отчёте (2026-09-11, задача владельца):
факт против прогноза, остатки во времени, остатки против прогноза — все три
через встроенный ECharts (тот же движок, что у остальных графиков отчёта).

Данные приходят из общего адаптера (engines/narrative_adapter.py) в
diagnostics["actual_vs_predicted"]; aurora_html.builder.AuroraHTMLBuilder
кладёт их в CHART_DATA.quality (_chart_data_json/_quality_series), а
aurora_html.sections.render_sources рисует три контейнера графиков ТОЛЬКО
когда ряд есть.

Стережём: (1) CHART_DATA.quality несёт те же числа, что в diagnostics, без
округления; (2) три chart-host контейнера появляются в HTML секции «Качество
модели и источники данных», когда ряд есть; (3) раздела с графиками нет
ВООБЩЕ (ни одного chart-host id), когда ряда нет — не пустой плейсхолдер.
"""
from __future__ import annotations

import json
import os

from aurora_html.builder import AuroraHTMLBuilder
from aurora_html.sections import render_sources

_HERE = os.path.dirname(os.path.abspath(__file__))
_STRINGS_PATH = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")

_CHART_IDS = ("chart-quality-avp", "chart-quality-residuals", "chart-quality-scatter")


def _avp_fixture():
    return {
        "dates": ["2024-01-01", "2024-01-08", "2024-01-15"],
        "actual": [100.1234, 110.0, 90.0],
        "predicted": [95.0, 108.0, 100.0],
        "residuals": [5.1234, 2.0, -10.0],
    }


def _ctx(diagnostics: dict) -> dict:
    with open(_STRINGS_PATH, encoding="utf-8") as f:
        strings = json.load(f)
    return {
        "meta": {}, "facts": {}, "channels": [],
        "diagnostics": diagnostics, "strings": strings, "kpi": {},
    }


def test_chart_data_несёт_те_же_числа_без_округления():
    avp = _avp_fixture()
    b = AuroraHTMLBuilder({"diagnostics": {"actual_vs_predicted": avp}})
    payload = json.loads(b._chart_data_json())
    quality = payload["quality"]
    assert quality["dates"] == avp["dates"]
    assert quality["actual"] == avp["actual"]
    assert quality["predicted"] == avp["predicted"]
    assert quality["residuals"] == avp["residuals"]


def test_chart_data_quality_пуст_когда_ряда_нет():
    b = AuroraHTMLBuilder({"diagnostics": {}})
    payload = json.loads(b._chart_data_json())
    assert payload["quality"] == {"dates": [], "actual": [], "predicted": [], "residuals": []}


def test_три_контейнера_графиков_строятся_когда_есть_ряд():
    html = render_sources(_ctx({"actual_vs_predicted": _avp_fixture()}))
    for chart_id in _CHART_IDS:
        assert f'id="{chart_id}"' in html, f"{chart_id} отсутствует в HTML при наличии ряда"


def test_раздела_с_графиками_нет_когда_ряда_нет():
    html = render_sources(_ctx({}))
    for chart_id in _CHART_IDS:
        assert f'id="{chart_id}"' not in html, f"{chart_id} присутствует без данных"


def test_раздела_с_графиками_нет_при_неполном_ряде():
    """Испорченный/неполный источник (например, потерялся predicted) не должен
    рисовать половину графиков — секция целиком отсутствует."""
    html = render_sources(_ctx({"actual_vs_predicted": {
        "dates": ["2024-01-01"], "actual": [100.0], "predicted": [],
    }}))
    for chart_id in _CHART_IDS:
        assert f'id="{chart_id}"' not in html


def test_подписи_норм_присутствуют():
    html = render_sources(_ctx({"actual_vs_predicted": _avp_fixture()}))
    assert "Норма" in html
    assert "Факт против прогноза" in html
    assert "Остатки во времени" in html
    assert "Остатки против прогноза" in html
