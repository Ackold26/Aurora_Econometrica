"""Первая ступень CHART_SPEC_static_reports.md (2026-09-13) — дешёвые точечные
правки пяти графиков веб-отчёта: подписи значений там, где число раньше
читалось только по оси, и scale:true там, где принудительный ноль в диапазоне
сжимает линии/облако точек (см. F-A3-01 в ConvergenceDashboard.svelte — тот же
класс дефекта, уже закрытый в интерфейсе программы, но не в html-отчёте).

Стережём наличие конкретных фрагментов в собранном JS-бандле (aurora_html.
interactive.bootstrap_js), а не поведение ECharts в браузере — дешёвая и
точная проверка на уровне текста, которая физически не может пройти до
правки (фрагментов не было в файле) и не может молча перестать проходить
при откате (grep по опции, а не по факту существования функции).
"""
from __future__ import annotations

from aurora_html.interactive import bootstrap_js

_STRINGS = {"ui": {}, "empty_states": {}, "verdicts": {}}


def _js() -> str:
    return bootstrap_js("light", "{}", "{}", _STRINGS)


def test_waterfall_2_1_несёт_подпись_значения_на_столбце():
    js = _js()
    assert "function buildWaterfallOption" in js
    waterfall = js.split("function buildWaterfallOption", 1)[1].split("function build", 1)[0]
    assert "label:" in waterfall and "show: true" in waterfall


def test_share_2_3_несёт_подписи_процентов_на_обеих_сериях():
    js = _js()
    assert "function buildShareOption" in js
    share = js.split("function buildShareOption", 1)[1].split("function build", 1)[0]
    assert share.count("label:") == 2
    assert "{c}%" in share


def test_optimize_2_5_несёт_подписи_млн_на_обеих_сериях():
    js = _js()
    assert "function buildOptimizeOption" in js
    optimize = js.split("function buildOptimizeOption", 1)[1].split("function initChart", 1)[0]
    assert optimize.count("label:") == 2
    assert "млн" in optimize


def test_quality_avp_2_6_ось_y_несёт_scale_true():
    js = _js()
    assert "function buildQualityAvpOption" in js
    avp = js.split("function buildQualityAvpOption", 1)[1].split("function build", 1)[0]
    assert "yAxis: Object.assign({ type: 'value', scale: true }" in avp


def test_quality_scatter_2_8_ось_x_несёт_scale_true_ось_y_без_него():
    js = _js()
    assert "function buildQualityScatterOption" in js
    scatter = js.split("function buildQualityScatterOption", 1)[1].split("function build", 1)[0]
    x_axis, y_axis = scatter.split("yAxis: Object.assign(", 1)
    assert "scale: true" in x_axis
    assert "scale: true" not in y_axis
