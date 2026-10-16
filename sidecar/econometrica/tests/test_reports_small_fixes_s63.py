"""s63, малые правки отчётов (аудит s62): №2, №5, №6, №8.

№2  Заголовок «{герой} – лучший канал по …» (веб-отчёт, раздел рекомендаций) называет метрику
    страницы: штучный KPI – CPU, режим «доля» – «доле эффекта»; денежный – прежний mROAS.
№5  Склейка предупреждений декомпозиции: при предупреждении о датах хвост прежнего («Переобучите
    модель …») опускается – в итоге ровно один совет переобучить; англицизмы «OLS-режим»,
    «предиктивные интервалы», «премиум-модели» заменены.
№6  Подзаголовок графика CPU – по-русски, без «incremental cost-per-unit».
№8  Канал без mROAS в веб-отчёте – «значение не определено», а не нулевая полоса «0.00×».
Мутации – Projects/_s63/report_reports.md.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import test_headlines_hero_cut_s60 as H  # noqa: E402
import test_underperformers_unified as U  # noqa: E402
# Проект OLS и помощники склейки дат – из теста N7 (фикстуры подхватываются по имени).
from test_n7_dates_retrain import (  # noqa: E402,F401
    OLD_READ, WARNING_HEAD, _decompose, _set_dates, proj, ru_project,
)


# ─── №2 ─────────────────────────────────────────────────────────────────────

def _title(b) -> str:
    m = re.search(r"Social – лучший канал по [^,]+, но оптимизатор рекомендует сократить бюджет канала", b.flat)
    assert m, "заголовок героя с Cut/Reduce не найден"
    return m.group(0)


def test_hero_title_metric_monetary_is_mroas():
    b = H._build(spec={"Social": H._ch("Reduce")})
    assert _title(b) == "Social – лучший канал по mROAS, но оптимизатор рекомендует сократить бюджет канала"


def test_hero_title_metric_count_kpi_is_cpu():
    b = H.Built(U._scenario_data(**{**U._SCENARIOS["kpi_count"], "spec": {"Social": H._ch("Reduce")}}))
    assert _title(b) == "Social – лучший канал по CPU, но оптимизатор рекомендует сократить бюджет канала"
    assert "по mROAS" not in _title(b)


def test_hero_title_metric_share_mode_is_share_of_effect():
    kw = copy.deepcopy(U._SCENARIOS["kpi_effectiveness"])
    kw["spec"] = {"Social": H._ch("Reduce")}
    b = H.Built(U._scenario_data(**kw))
    assert _title(b) == "Social – лучший канал по доле эффекта, но оптимизатор рекомендует сократить бюджет канала"
    assert "по mROAS" not in _title(b)


# ─── №5 ─────────────────────────────────────────────────────────────────────

def _warning_with_version(proj, monkeypatch, version):
    import engines.persistence as persistence
    real = persistence.load_model_with_compat

    def _load(path, *a, **kw):
        data = real(path, *a, **kw)
        data["model_version"] = version
        return data

    monkeypatch.setattr(persistence, "load_model_with_compat", _load)
    r = _decompose(proj)
    assert r["model_version"] == version
    return r["model_warning"]


@pytest.mark.parametrize("version, kept, dropped", [
    ("1.1.5", "Правдоподобные диапазоны не учитывают неопределённость переноса эффекта.",
     "для получения честного правдоподобного диапазона"),
    ("1.1", "Правдоподобные диапазоны недоступны.", "для поддержки правдоподобных диапазонов"),
])
def test_dates_plus_legacy_warning_has_exactly_one_retrain_advice(proj, monkeypatch, version, kept, dropped):
    """Оба предупреждения: одно «Переобучите» (в предупреждении о датах), описание ограничения прежней
    модели остаётся, её хвост-совет опущен."""
    plain = _warning_with_version(proj, monkeypatch, version)
    assert plain.count("Переобучите") == 1 and dropped in plain       # без дат – прежний текст целиком
    _set_dates(proj, OLD_READ)
    w = _warning_with_version(proj, monkeypatch, version)
    assert w.startswith(WARNING_HEAD)
    assert w.count("Переобучите") == 1, w
    assert "Переобучите модель – числа изменятся." in w
    assert kept in w and dropped not in w
    assert w.endswith(kept) or w.endswith(".")


def test_ols_warning_after_dates_warning_is_kept_whole(proj):
    """У режима малых данных совета «Переобучите» нет – его текст остаётся целиком (прежняя склейка)."""
    base = _decompose(proj)["model_warning"]
    _set_dates(proj, OLD_READ)
    w = _decompose(proj)["model_warning"]
    assert w.endswith(base) and w.count("Переобучите") == 1


def test_ols_warning_is_russian_in_product_terms(proj):
    w = _decompose(proj)["model_warning"]
    assert w.startswith("Режим малых данных (OLS): n=")
    for bad in ("OLS-режим", "предиктивн", "премиум", "premium"):
        assert bad not in w, bad
    assert "интервалы прогноза на y" in w
    assert "Соберите больше данных для байесовской модели." in w


# ─── №6 ─────────────────────────────────────────────────────────────────────

def _count_deck_subtitles():
    from aurora_pptx.builder import AuroraPPTXBuilder
    data = U._scenario_data(**{**U._SCENARIOS["kpi_count"]})
    prs = AuroraPPTXBuilder(copy.deepcopy(data)).build()
    return [sh.text_frame.text for s in prs.slides for sh in s.shapes
            if sh.has_text_frame and sh.text_frame.text.startswith("Стоимость следующей единицы")]


def test_cpu_chart_subtitle_has_no_latin_pptx():
    subs = _count_deck_subtitles()
    assert len(subs) == 1, subs
    assert subs[0].startswith("Стоимость следующей единицы (прирост стоимости на единицу)")
    assert not re.search(r"[A-Za-z]", subs[0]), subs[0]


def test_cpu_chart_subtitle_has_no_latin_html():
    from aurora_html import build_html
    page = build_html(U._scenario_data(**U._SCENARIOS["kpi_count"]))
    subs = re.findall(r'<div class="chart-subtitle">(Стоимость следующей единицы[^<]*)</div>', page)
    assert subs == ["Стоимость следующей единицы (прирост стоимости на единицу)"]


# ─── №8 ─────────────────────────────────────────────────────────────────────

def _chart_data(page: str) -> dict:
    idx = page.index("{", page.index("var CHART_DATA"))
    return json.JSONDecoder().raw_decode(page, idx)[0]


def test_channel_without_mroas_is_not_drawn_as_zero_in_html_chart_data():
    from aurora_html import build_html
    data = U._scenario_data(spec={"Banners": {"mroas": None}})
    cd = _chart_data(build_html(copy.deepcopy(data)))["mroas"]
    by_name = dict(zip(cd["names"], cd["values"]))
    assert by_name["Banners"] is None, by_name              # не 0.0: ноль читается как «не окупается»
    assert cd["details"]["Banners"]["mroas"] is None
    # остальные каналы – числа как были
    assert by_name["Social"] == pytest.approx(27.03, abs=0.01)
    assert cd["details"]["Social"]["mroas"] == pytest.approx(27.03, abs=0.01)


def test_zero_mroas_stays_zero_and_nan_becomes_undefined():
    """Настоящий ноль – число (канал не окупается); нечисло – «не определено» (как у презентации)."""
    from aurora_html import build_html
    data = U._scenario_data(spec={"Banners": {"mroas": 0.0}, "OLV": {"mroas": float("nan")}})
    cd = _chart_data(build_html(copy.deepcopy(data)))["mroas"]
    by_name = dict(zip(cd["names"], cd["values"]))
    assert by_name["Banners"] == 0.0 and by_name["OLV"] is None


def test_chart_script_labels_missing_value_honestly():
    """JS-ветка (в тестах движка браузера нет – проверяется живой отрисовкой, см. отчёт): формат значения и
    подпись у канала без значения."""
    from aurora_html import build_html
    page = build_html(U._scenario_data(spec={"Banners": {"mroas": None}}))
    assert "значение не определено" in page and "undef: true" in page
