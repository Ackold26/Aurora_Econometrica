"""График качества модели в колоде (2026-09-11, задача владельца): слайд
«Факт против прогноза» — родная диаграмма PowerPoint (LINE_MARKERS, два ряда),
НЕ картинка. Строится ТОЛЬКО когда есть ряд actual_vs_predicted (тот же
источник, что у веб-отчёта — engines/narrative_adapter.py), рисуется своим
вставным слайдом (aurora_pptx/builder.py: AuroraPPTXBuilder.s10e_quality_chart),
поскольку на самом слайде «Данные и качество» свободной полосы для читаемого
графика нет (измерено на боевой фикстуре Kagocel).

Стережём: (1) график появляется и несёт ТЕ ЖЕ числа, что в diagnostics, когда
ряд есть; (2) слайда/графика нет вовсе, когда ряда нет — колода не растёт на
пустой слайд; (3) значения в книге графика НЕ округлены относительно входа.
"""
from __future__ import annotations

import copy
import json
import os

from aurora_pptx.builder import AuroraPPTXBuilder

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")


def _payload(avp=None):
    with open(_FIXTURE, encoding="utf-8") as f:
        p = json.load(f)
    p = copy.deepcopy(p)
    if avp is not None:
        p["diagnostics"]["actual_vs_predicted"] = avp
    return p


def _avp_fixture():
    return {
        "dates": ["2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22"],
        "actual": [1005000.123, 1015000.0, 1030000.0, 1045000.0],
        "predicted": [1000000.0, 1014500.0, 1029000.0, 1043500.0],
        "residuals": [5000.123, 500.0, 1000.0, 1500.0],
    }


def _quality_chart_slide(prs):
    """Находит слайд с нативным графиком «Факт против прогноза» (по тексту
    заголовка), возвращает (slide, chart) или (None, None)."""
    for slide in prs.slides:
        texts = [
            sh.text_frame.text.strip() for sh in slide.shapes
            if sh.has_text_frame and sh.text_frame.text.strip()
        ]
        if any("Факт против прогноза" in t for t in texts):
            for sh in slide.shapes:
                if sh.has_chart:
                    return slide, sh.chart
            return slide, None
    return None, None


def test_слайд_и_график_строятся_когда_есть_ряд():
    prs = AuroraPPTXBuilder(_payload(_avp_fixture())).build()
    slide, chart = _quality_chart_slide(prs)
    assert slide is not None, "слайд «Факт против прогноза» не найден при наличии ряда"
    assert chart is not None, "на слайде нет нативной диаграммы (add_chart)"


def test_график_несёт_те_же_числа_что_в_diagnostics():
    avp = _avp_fixture()
    prs = AuroraPPTXBuilder(_payload(avp)).build()
    _, chart = _quality_chart_slide(prs)
    series_by_name = {s.name: list(s.values) for s in chart.plots[0].series}
    assert series_by_name["Факт"] == avp["actual"]
    assert series_by_name["Прогноз"] == avp["predicted"]


def test_легенда_родная():
    prs = AuroraPPTXBuilder(_payload(_avp_fixture())).build()
    _, chart = _quality_chart_slide(prs)
    assert chart.has_legend is True


def test_слайда_нет_когда_ряда_нет():
    """Нет actual_vs_predicted в диагностике — колода остаётся 12-слайдовой,
    без слайда «Факт против прогноза» и без лишнего графика."""
    prs = AuroraPPTXBuilder(_payload(None)).build()
    slide, _ = _quality_chart_slide(prs)
    assert slide is None
    assert len(prs.slides) == 12


def test_слайда_нет_при_пустых_списках():
    prs = AuroraPPTXBuilder(_payload({"dates": [], "actual": [], "predicted": []})).build()
    slide, _ = _quality_chart_slide(prs)
    assert slide is None


def test_нумерация_остальных_слайдов_сдвигается_на_один():
    """Приём тот же, что у backtest/gen_compare/promises/forecast: появление
    вставного слайда двигает нумерацию хвоста колоды (_page_shift)."""
    prs_without = AuroraPPTXBuilder(_payload(None)).build()
    prs_with = AuroraPPTXBuilder(_payload(_avp_fixture())).build()
    assert len(prs_with.slides) == len(prs_without.slides) + 1
