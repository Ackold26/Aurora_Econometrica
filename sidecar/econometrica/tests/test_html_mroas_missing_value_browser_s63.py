"""s63 №8 (JS-часть): диаграмма mROAS веб-отчёта у канала без значения – полосы нет, подпись
«значение не определено», а не «0.00×».

Python-часть (в данных диаграммы None, не 0) проверена в `test_reports_small_fixes_s63.py`; здесь –
поведение страницы в настоящем браузере (Playwright + Chromium). Нет браузера на машине – тест
пропускается (CI без Playwright), на машине разработки он обязан проходить.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

pytest.importorskip("playwright.sync_api")
import test_underperformers_unified as U  # noqa: E402
from aurora_html import build_html  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

_PROBE = """() => {
  var chart = echarts.getInstanceByDom(document.getElementById('chart-mroas'));
  if (!chart) return {error: 'нет диаграммы'};
  var opt = chart.getOption();
  var names = opt.yAxis[0].data, data = opt.series[0].data, out = {};
  names.forEach(function(n, i) {
    var d = data[i], lab = null;
    var fmt = (d.label && d.label.formatter) || opt.series[0].label.formatter;
    if (typeof fmt === 'function') lab = fmt({value: d.value, name: n, data: d});
    out[n] = {value: d.value, undef: !!d.undef, label: lab, color: d.itemStyle && d.itemStyle.color};
  });
  return out;
}"""


_PANEL = """() => {
  var e = document.querySelector('[class*=drill]');
  return e ? e.innerText : null;
}"""


@pytest.fixture(scope="module")
def chart_state(tmp_path_factory):
    page_file = tmp_path_factory.mktemp("mroas_js") / "report.html"
    page_file.write_text(build_html(U._scenario_data(spec={"Banners": {"mroas": None}})), encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                pg = browser.new_page(viewport={"width": 1400, "height": 900})
                pg.goto(page_file.as_uri())
                pg.evaluate("document.getElementById('chart-mroas').scrollIntoView()")
                pg.wait_for_function(
                    "() => document.getElementById('chart-mroas') && echarts.getInstanceByDom("
                    "document.getElementById('chart-mroas'))", timeout=15000)
                state = pg.evaluate(_PROBE)
                # Выдвижная панель канала (клик по строке таблицы действий): значение mROAS у канала
                # без значения – та же честная подпись, без ошибки скрипта.
                errors: list[str] = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                row = pg.locator('#action-table tbody tr[data-channel="Banners"]').first
                row.scroll_into_view_if_needed()
                row.click()
                pg.wait_for_timeout(500)
                state["__panel"] = pg.evaluate(_PANEL)
                state["__errors"] = errors
                return state
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 – нет браузера/драйвера на машине
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip(f"Chromium для Playwright не установлен: {type(exc).__name__}")
        raise


def test_channel_without_mroas_has_no_bar_and_honest_label(chart_state):
    banners = chart_state["Banners"]
    assert banners["undef"] is True
    assert banners["label"] == "значение не определено"
    assert banners["color"] == "transparent"          # полосы нет


def test_channels_with_mroas_keep_value_labels(chart_state):
    social = chart_state["Social"]
    assert social["undef"] is False and social["label"] == "27.03×"
    assert chart_state["Performance"]["label"] == "16.23×"


def test_drill_panel_of_channel_without_mroas_says_undefined(chart_state):
    panel = chart_state["__panel"]
    assert panel and re.search(r"mROAS\s+значение не определено", panel), panel
    assert "0.00×" not in panel
    assert chart_state["__errors"] == []
