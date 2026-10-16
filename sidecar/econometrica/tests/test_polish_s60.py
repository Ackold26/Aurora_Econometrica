"""s60, малые правки: клиентский текст предупреждений декомпозиции (П-9) и порядок
полос на слайде «Декомпозиция продаж» (П-5 i).

П-9. `model_warning` из `decompose` доезжает до клиента баннером в DecomposeStep.
Текст не должен содержать внутренних меток («Phase 1.9»), английских слов,
латиницы внутри русского слова («посterior»), дефиса с пробелами « - » вместо
короткого тире и длинного тире U+2014. Проверка идёт через точку входа
`decompose` на обученном OLS-проекте; ветки «1.1.5» и «1.1» получаются подменой
версии модели при загрузке (весь расчёт ниже по коду от версии не зависит –
различается только текст предупреждения).

П-5 (i). Горизонтальная диаграмма PowerPoint рисует первую категорию снизу;
ось категорий разворачивается, чтобы «База → каналы → Итого» читалось сверху вниз.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_FIXTURE = Path(__file__).parent / "fixtures" / "kagocel_builder_payload.json"

# ─── П-9: предупреждения декомпозиции ───────────────────────────────────────

_MONTHS = pd.date_range("2021-01-01", periods=36, freq="MS")
# Латиница, допустимая в клиентском тексте: сокращения и обозначения величин.
_LATIN_OK = {"OLS", "ROI", "mROAS", "n", "y"}
_LATIN_WORD = re.compile(r"[A-Za-z]+")
_MIXED_SCRIPT = re.compile(r"[А-Яа-яЁё][A-Za-z]|[A-Za-z][А-Яа-яЁё]")
_FORBIDDEN = ["Phase", "frequentist", "Bayesian", "posterior", "samples", "adstock",
              "carryover", "fallback", "small data", "Hill", "decay"]


@pytest.fixture(scope="module")
def ols_project(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("polish_s60")
    rng = np.random.RandomState(21)
    tv = rng.uniform(2e4, 6e4, 36).round(0)
    dg = rng.uniform(5e3, 2e4, 36).round(0)
    sales = (1.2e5 + 0.9 * tv + 1.6 * dg + rng.normal(0, 4e3, 36)).round(0)
    csv = base / "data.csv"
    pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in _MONTHS], "sales": sales,
                  "tv_spend": tv, "digital_spend": dg}).to_csv(csv, index=False)
    from engines.ols_modeler import train_ols
    cfg = {"data_file": str(csv), "kpi_column": "sales",
           "media_columns": ["tv_spend", "digital_spend"], "control_columns": [],
           "date_column": "date", "adstock_config": {}}
    t = train_ols(cfg, str(base / "proj"))
    assert t["status"] == "ok", t.get("message")
    return base / "proj"


def _warning(proj: Path, monkeypatch, version: str) -> str:
    import engines.persistence as persistence
    from engines.decomposer import decompose
    real = persistence.load_model_with_compat

    def _load(path, *a, **kw):
        data = real(path, *a, **kw)
        data["model_version"] = version
        return data

    monkeypatch.setattr(persistence, "load_model_with_compat", _load)
    r = decompose(str(proj), save_results=False)
    assert r["status"] == "ok", r.get("message")
    assert r["model_version"] == version, "основа теста: версия подменена"
    w = r["model_warning"]
    assert w, f"для версии {version} предупреждение должно быть"
    return w


# Ключевые фразы каждой ветки: смысл и условия сохранены (какая модель – какой текст).
_EXPECT = {
    "1.0-ols": ["Режим малых данных (OLS)", "частотным (классическим) методом",
                "интервалы прогноза", "фиксированы", "ROI/mROAS недоступны", "n≥30",
                "Соберите больше данных для байесовской модели"],
    "1.1.5": ["фиксированным затуханием отложенного эффекта", "не учитывают неопределённость",
              "Переобучите модель"],
    "1.1": ["апостериорных выборок", "Правдоподобные диапазоны недоступны",
            "Переобучите модель"],
}


@pytest.mark.parametrize("version", sorted(_EXPECT))
def test_decompose_warning_is_clean_russian(ols_project, monkeypatch, version):
    w = _warning(ols_project, monkeypatch, version)
    assert "Phase" not in w, w
    assert " - " not in w and "—" not in w, w          # короткое тире «–», не « - » и не «—»
    assert not _MIXED_SCRIPT.search(w), f"латиница внутри русского слова: {w}"
    for bad in _FORBIDDEN:
        assert bad not in w, f"«{bad}» в клиентском тексте: {w}"
    extra = {t for t in _LATIN_WORD.findall(w)} - _LATIN_OK
    assert not extra, f"лишняя латиница {sorted(extra)}: {w}"
    for part in _EXPECT[version]:
        assert part in w, f"пропал смысл ветки {version}: нет «{part}» в {w}"


def test_mixed_script_regex_sees_old_defect():
    """Регулярка латиницы внутри русского слова видит прежний дефект «посterior»."""
    assert _MIXED_SCRIPT.search("посterior samples")
    assert not _MIXED_SCRIPT.search("OLS-режим, n≥30, ROI/mROAS")


# ─── П-5 (i): порядок полос слайда «Декомпозиция продаж» ────────────────────

_WF = {"labels": ["База", "TRPs бренд (W 25-54)", "Social", "OLV", "Banners", "Performance", "Итого"],
       "values": [600.0, 50.0, 40.0, 20.0, 10.0, 5.0, 725.0],
       "types": ["baseline", "channel", "channel", "channel", "channel", "channel", "total"]}


def _decomposition_chart():
    from aurora_pptx.builder import AuroraPPTXBuilder
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["waterfall"] = copy.deepcopy(_WF)
    prs = AuroraPPTXBuilder(payload).build()
    found = [sh.chart for s in prs.slides for sh in s.shapes
             if sh.has_chart and "BAR_STACKED" in str(sh.chart.chart_type)]
    assert len(found) == 1, "ровно одна диаграмма декомпозиции"
    return found[0]


def test_decomposition_chart_reads_top_to_bottom():
    chart = _decomposition_chart()
    cats = list(chart.plots[0].categories)
    assert cats[0] == "База" and cats[-1] == "Итого"
    assert cats == _WF["labels"], "порядок и подписи категорий не менялись"
    assert chart.category_axis.reverse_order is True
    # В XML это c:scaling/c:orientation = maxMin: у PowerPoint первая категория – сверху.
    xml = chart.category_axis._element.xml
    assert 'c:orientation val="maxMin"' in xml


def test_decomposition_chart_values_unchanged():
    chart = _decomposition_chart()
    series = chart.plots[0].series[0]
    assert list(series.values) == _WF["values"]
    assert chart.plots[0].has_data_labels is True
