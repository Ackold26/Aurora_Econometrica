"""s63 №16 + №17: слайд «Декомпозиция продаж» – ось значений внизу, шкала в удобной единице,
подписи малых полос не налезают на названия.

Дефекты (образцы s62, отрисовка LibreOffice):
  (16) после разворота порядка категорий (`reverse_order`, s60) ось значений уехала НАВЕРХ, над «Базой»;
  (17) подписи малых полос по центру крошечной полосы налезали на названия («ТВ бюджет271 271 483»),
       числа шкалы шли без разрядов («25000000000»).
Проверяется XML диаграммы: то, что читает PowerPoint. Отрисовка до/после – Projects/_s63/report_reports.md.
Примечание: у `CategoryAxis` python-pptx нет `crosses` – присвоение `category_axis.crosses = …` молча
создаёт атрибут без записи в XML; поэтому тест смотрит XML, а не атрибут объекта.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from aurora_pptx.builder import AuroraPPTXBuilder, _decomp_axis_plan  # noqa: E402

_FIXTURE = Path(_HERE) / "fixtures" / "kagocel_builder_payload.json"

# Рубли (как у боевого образца s62): база 17,6 млрд, итог 23,1 млрд, малые каналы 0,23 и 0,37 млрд.
_WF = {"labels": ["База", "Performance бюджет", "Онлайн-видео бюджет", "ТВ бюджет", "Наружная реклама бюджет", "Итого"],
       "values": [17_609_513_047.0, 2_408_874_829.0, 2_469_899_573.0, 371_271_483.0, 234_808_865.0, 23_094_367_798.0],
       "types": ["baseline", "channel", "channel", "channel", "channel", "total"]}

_NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
       "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _chart(waterfall=None, kpi_patch=None):
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["waterfall"] = copy.deepcopy(waterfall or _WF)
    if kpi_patch:
        payload["kpi"] = dict(payload.get("kpi") or {}, **kpi_patch)
    prs = AuroraPPTXBuilder(payload).build()
    found = [sh.chart for s in prs.slides for sh in s.shapes
             if sh.has_chart and "BAR_STACKED" in str(sh.chart.chart_type)]
    assert len(found) == 1, "ровно одна диаграмма декомпозиции"
    return found[0]


# ─── №16: ось значений внизу ────────────────────────────────────────────────

def test_value_axis_crosses_at_max_category_so_it_is_at_the_bottom():
    chart = _chart()
    # категории развёрнуты (сверху вниз: База → … → Итого), значит максимальная категория – внизу
    assert chart.category_axis.reverse_order is True
    crosses = chart._chartSpace.xpath("//c:valAx/c:crosses/@val")
    assert crosses == ["max"], crosses
    # ось категорий по-прежнему пересекает ось значений в нуле (полосы растут от оси названий)
    assert chart._chartSpace.xpath("//c:catAx/c:crosses/@val") == ["autoZero"]


def test_values_labels_order_and_type_unchanged():
    chart = _chart()
    assert "BAR_STACKED" in str(chart.chart_type)                 # тип закреплён спецификацией
    assert list(chart.plots[0].categories) == _WF["labels"]
    assert list(chart.plots[0].series[0].values) == _WF["values"]  # исходные рубли: «Изменить данные»


# ─── №17: шкала в удобной единице ───────────────────────────────────────────

def test_value_axis_scale_in_billions_with_title_and_round_ticks():
    chart = _chart()
    vax = chart._chartSpace.xpath("//c:valAx")[0]
    fmt = vax.xpath("c:numFmt/@formatCode")[0]
    assert fmt == "#,##0,,,"                                       # три запятые = деление на 10^9
    assert vax.xpath("c:numFmt/@sourceLinked")[0] == "0"
    assert float(vax.xpath("c:scaling/c:min/@val")[0]) == 0.0
    assert float(vax.xpath("c:scaling/c:max/@val")[0]) == 25e9
    assert float(vax.xpath("c:majorUnit/@val")[0]) == 5e9
    title = "".join(vax.xpath("c:title//a:t/text()"))
    assert title == "млрд ₽"


def test_data_labels_are_scaled_not_raw_digits():
    chart = _chart()
    fmts = chart._chartSpace.xpath("//c:ser/c:dLbls/c:dLbl/c:numFmt/@formatCode")
    assert len(fmts) == len(_WF["values"])
    assert set(fmts) == {"#,##0.0,,,"}                             # «17,6», «0,4» вместо «17 609 513 047»
    assert chart._chartSpace.xpath("//c:barChart/c:dLbls/c:numFmt/@formatCode") == ["#,##0.0,,,"]


# ─── №17: подписи малых полос ───────────────────────────────────────────────

def test_small_bars_get_label_at_base_large_bars_in_center():
    """Полоса короче 8 % самой длинной (ТВ 1,6 %, наружная 1,0 %): подпись у основания, идёт вправо от
    оси по пустому полю; не по центру – там она выходила влево на названия каналов. Длинные – по центру."""
    chart = _chart()
    pos = {int(d.xpath("c:idx/@val")[0]): d.xpath("c:dLblPos/@val")[0]
           for d in chart._chartSpace.xpath("//c:ser/c:dLbls/c:dLbl")}
    assert pos == {0: "ctr", 1: "ctr", 2: "ctr", 3: "inBase", 4: "inBase", 5: "ctr"}


def test_label_color_follows_fill_for_inside_and_dark_for_spill():
    """Подпись внутри тёмной полосы – белая, внутри светлой и у малых (выходит на белое поле) – тёмная."""
    chart = _chart()
    colors = {}
    for d in chart._chartSpace.xpath("//c:ser/c:dLbls/c:dLbl"):
        idx = int(d.xpath("c:idx/@val")[0])
        colors[idx] = d.xpath("c:txPr//a:srgbClr/@val")[0]
    assert colors[1] == "FFFFFF"            # Performance – тёмно-бирюзовая полоса, помещается
    assert colors[3] != "FFFFFF" and colors[4] != "FFFFFF"   # малые – тёмный текст на белом поле
    assert colors[0] != "FFFFFF"            # «База» – светлая полоса, тёмный текст


def test_dlbl_children_are_in_schema_order():
    """CT_DLbl: idx, numFmt, spPr, txPr, dLblPos, show* – иначе PowerPoint просит восстановить файл."""
    chart = _chart()
    order = ["idx", "layout", "tx", "numFmt", "spPr", "txPr", "dLblPos", "showLegendKey", "showVal",
             "showCatName", "showSerName", "showPercent", "showBubbleSize", "separator", "extLst"]
    for d in chart._chartSpace.xpath("//c:ser/c:dLbls/c:dLbl"):
        names = [re.sub(r"^\{.*\}", "", el.tag) for el in d]
        ranks = [order.index(n) for n in names]
        assert ranks == sorted(ranks), names


# ─── план оси: единицы и шаги (чистая функция) ──────────────────────────────

@pytest.mark.parametrize("values, unit_text, mx, step, axis_fmt, label_fmt", [
    ([17.6e9, 2.4e9, 23.1e9], "млрд ₽", 25e9, 5e9, "#,##0,,,", "#,##0.0,,,"),
    ([2.3e9, 1.1e9], "млрд ₽", 2.5e9, 5e8, "#,##0.0,,,", "#,##0.0,,,"),          # шаг 0,5 – десятые на шкале
    ([2.4e6, 5e5, 3e7], "млн ₽", 30e6, 10e6, "#,##0,,", "#,##0.0,,"),
    ([50_000.0, 120_000.0], "тыс. ₽", 150_000.0, 50_000.0, "#,##0,", "#,##0.0,"),
    ([100.0, 50.0, 200.0], "₽", 200.0, 50.0, "#,##0", "#,##0"),
])
def test_axis_plan_units_and_steps(values, unit_text, mx, step, axis_fmt, label_fmt):
    plan = _decomp_axis_plan(values, "₽")
    assert plan["unit_text"] == unit_text
    assert plan["axis_min"] == 0.0 and plan["axis_max"] == mx and plan["major_unit"] == step
    assert plan["axis_format"] == axis_fmt and plan["label_format"] == label_fmt


def test_axis_plan_negative_and_empty_and_count_unit():
    neg = _decomp_axis_plan([-5e6, 2e7], "₽")
    assert neg["axis_min"] == -5e6 and neg["axis_max"] == 20e6
    zero = _decomp_axis_plan([0.0, 0.0], "₽")
    assert zero["axis_max"] > zero["axis_min"]                      # график с нулями не вырождается
    assert _decomp_axis_plan([3e6], "лид.")["unit_text"] == "млн лид."   # единица – по KPI, не «₽» всегда


def test_count_kpi_unit_reaches_axis_title():
    chart = _chart(kpi_patch={"kpi_kind": "count", "kpi_type": "leads"})
    title = "".join(chart._chartSpace.xpath("//c:valAx/c:title//a:t/text()"))
    assert title == "млрд лид."
