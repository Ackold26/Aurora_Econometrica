"""N7 (выпуск 2.5.10): «Переобучите модель» для проекта, обученного прежней версией.

До 2.5.9 CSV «ДД.ММ.ГГГГ» читался месяцем вперёд («01.02.2021» – 2 января), и
модель подбиралась на таких датах. Декомпозиция 2.5.9+ читает файл верно, а
коэффициенты остаются прежними – числа молча перестают быть согласованными.
Сторож `_dates_retrain_warning` сверяет даты из `results/model-diagnostics.json`
(`actual_vs_predicted.dates`) с `parse_dates` файла сейчас.

Тесты – на ЗНАЧЕНИЯХ и через точку входа `decompose`: старое прочтение дат
воспроизводится подменой поля `dates` в диагностике обученного (OLS, быстрый
путь) проекта, эталон «месяцем вперёд» строится явным форматом `%m.%d.%Y`, а не
копией логики разбора.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

MONTHS = pd.date_range("2021-01-01", periods=36, freq="MS")
RU_STR = [d.strftime("%d.%m.%Y") for d in MONTHS]
# Так 2.5.8 читала «01.02.2021»: месяц и день местами, итог – 2 января 2021.
OLD_READ = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(RU_STR, format="%m.%d.%Y")]
ISO = [d.strftime("%Y-%m-%d") for d in MONTHS]
WARNING_HEAD = "Даты, на которых обучена модель, не совпадают с датами файла сейчас"


def _frame(dates) -> pd.DataFrame:
    rng = np.random.RandomState(21)
    tv = rng.uniform(2e4, 6e4, 36).round(0)
    dg = rng.uniform(5e3, 2e4, 36).round(0)
    season = 1 + 0.25 * np.sin(2 * np.pi * (MONTHS.month - 1) / 12)
    sales = (season * 1.2e5 + 0.9 * tv + 1.6 * dg + rng.normal(0, 4e3, 36)).round(0)
    return pd.DataFrame({"date": dates, "sales": sales, "tv_spend": tv, "digital_spend": dg})


def _train(data_file: Path, proj: Path) -> Path:
    from engines.ols_modeler import train_ols
    cfg = {"data_file": str(data_file), "kpi_column": "sales",
           "media_columns": ["tv_spend", "digital_spend"], "control_columns": [],
           "date_column": "date", "adstock_config": {}}
    t = train_ols(cfg, str(proj))
    assert t["status"] == "ok", t.get("message")
    return proj


@pytest.fixture(scope="module")
def ru_project(tmp_path_factory) -> Path:
    """Проект OLS на русском CSV «ДД.ММ.ГГГГ» (обучен верно, как 2.5.9+)."""
    base = tmp_path_factory.mktemp("n7_ru")
    csv = base / "ru.csv"
    _frame(RU_STR).to_csv(csv, sep=";", decimal=",", index=False, encoding="cp1251")
    proj = _train(csv, base / "proj")
    avp = json.loads((proj / "results" / "model-diagnostics.json").read_text("utf-8"))["actual_vs_predicted"]
    assert avp["dates"] == ISO, "основа теста: обучение дало верные даты"
    return proj


@pytest.fixture
def proj(ru_project: Path, tmp_path: Path) -> Path:
    """Свежая копия проекта на тест: диагностику каждый тест правит свою."""
    dst = tmp_path / "proj"
    shutil.copytree(ru_project, dst)
    return dst


def _diag_path(p: Path) -> Path:
    return p / "results" / "model-diagnostics.json"


def _set_dates(p: Path, dates) -> None:
    f = _diag_path(p)
    d = json.loads(f.read_text("utf-8"))
    if dates is _DROP:
        d["actual_vs_predicted"].pop("dates", None)
    else:
        d["actual_vs_predicted"]["dates"] = dates
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


_DROP = object()


def _decompose(p: Path, **kw) -> dict:
    from engines.decomposer import decompose
    r = decompose(str(p), save_results=False, **kw)
    assert r["status"] == "ok", r.get("message")
    return r


def test_old_reading_of_dates_warns_to_retrain(proj):
    """(а) Даты модели – прочтение месяцем вперёд: предупреждение с призывом переобучить."""
    assert OLD_READ[:3] == ["2021-01-01", "2021-01-02", "2021-01-03"]
    _set_dates(proj, OLD_READ)
    w = _decompose(proj)["model_warning"]
    assert w and WARNING_HEAD in w and "Переобучите модель" in w
    # Первая расходящаяся пара – вторая ячейка «01.02.2021»: сырое значение и обе даты словами.
    assert "«01.02.2021»" in w
    assert "прочитано как 2 января 2021" in w
    assert "читается как 1 февраля 2021" in w
    assert "—" not in w and "–" in w


def test_example_is_taken_from_first_diverging_pair(proj):
    """Пример в тексте – из ПЕРВОЙ расходящейся пары, а не из первой или последней ячейки."""
    wrong = list(ISO)
    wrong[5] = "2021-01-06"       # «01.06.2021», прочитано как 6 января
    wrong[20] = "2022-01-09"      # позже: в пример попасть не должно
    _set_dates(proj, wrong)
    w = _decompose(proj)["model_warning"]
    assert "«01.06.2021»" in w and "6 января 2021" in w and "1 июня 2021" in w
    assert "«01.09.2022»" not in w


def test_correct_dates_do_not_warn(proj):
    """(б) Даты модели равны датам файла: предупреждения про даты нет."""
    w = _decompose(proj)["model_warning"]
    assert WARNING_HEAD not in (w or "") and "Переобучите" not in (w or "")


def test_missing_dates_field_does_not_warn(proj):
    """(в) В диагностике нет поля `dates`."""
    _set_dates(proj, _DROP)
    w = _decompose(proj)["model_warning"]
    assert WARNING_HEAD not in (w or "")


def test_missing_diagnostics_file_does_not_warn(proj):
    """(в') Нет самого файла диагностики."""
    _diag_path(proj).unlink()
    w = _decompose(proj)["model_warning"]
    assert WARNING_HEAD not in (w or "")


@pytest.mark.parametrize("cut", [35, 1, 0])
def test_other_length_does_not_warn(proj, cut):
    """(г) Другая длина ряда – это иной случай (файл менялся после обучения): молчим."""
    _set_dates(proj, OLD_READ[:cut])
    w = _decompose(proj)["model_warning"]
    assert WARNING_HEAD not in (w or "")


def test_archive_generation_does_not_warn(proj):
    """(д) Архивное поколение (`models/history/`): диагностика в проекте чужая – молчим."""
    hist = proj / "models" / "history"
    hist.mkdir(parents=True, exist_ok=True)
    arch = hist / "gen_old.pkl"
    shutil.copy(proj / "models" / "latest.pkl", arch)
    for side in (proj / "models").glob("latest.pkl.*"):
        shutil.copy(side, hist / side.name.replace("latest.pkl", "gen_old.pkl"))
    _set_dates(proj, OLD_READ)
    # Контроль: на latest.pkl с теми же подменёнными датами предупреждение есть.
    assert WARNING_HEAD in _decompose(proj)["model_warning"]
    w = _decompose(proj, model_path=str(arch))["model_warning"]
    assert WARNING_HEAD not in (w or "")


@pytest.mark.parametrize("garbage", ["{не json", "", "[1, 2", "null", "[]"])
def test_broken_diagnostics_does_not_fail_or_warn(proj, garbage):
    """(е) Битая диагностика: декомпозиция не падает, предупреждения про даты нет."""
    _diag_path(proj).write_text(garbage, encoding="utf-8")
    w = _decompose(proj)["model_warning"]
    assert WARNING_HEAD not in (w or "")


def test_iso_csv_project_not_affected(tmp_path):
    """(ж) CSV с ISO-датами: обе версии читали одинаково – проект не затронут."""
    csv = tmp_path / "iso.csv"
    _frame(ISO).to_csv(csv, index=False)
    p = _train(csv, tmp_path / "proj")
    avp = json.loads(_diag_path(p).read_text("utf-8"))["actual_vs_predicted"]
    assert avp["dates"] == ISO
    w = _decompose(p)["model_warning"]
    assert WARNING_HEAD not in (w or "")


def test_xlsx_project_not_affected(tmp_path):
    """(ж') xlsx с настоящими датами: не затронут."""
    xlsx = tmp_path / "data.xlsx"
    _frame(MONTHS).to_excel(xlsx, index=False)
    p = _train(xlsx, tmp_path / "proj")
    avp = json.loads(_diag_path(p).read_text("utf-8"))["actual_vs_predicted"]
    assert avp["dates"] == ISO
    w = _decompose(p)["model_warning"]
    assert WARNING_HEAD not in (w or "")


def test_new_warning_goes_before_existing_ols_warning(proj):
    """(з) Склейка: новое предупреждение – первым, прежнее OLS сохранено целиком после него."""
    base = _decompose(proj)["model_warning"]
    assert base and base.startswith("Режим малых данных (OLS)"), "основа теста: у OLS прежнее предупреждение непустое"
    _set_dates(proj, OLD_READ)
    w = _decompose(proj)["model_warning"]
    assert w.startswith(WARNING_HEAD)
    assert w.endswith(base)
    assert w.index("Переобучите модель") < w.index("Режим малых данных (OLS)")
    assert w == f"{w[:-len(base)].rstrip()} {base}" and w.count("Режим малых данных (OLS)") == 1


def test_warning_does_not_change_numbers(proj):
    """Расчёт не меняется: те же вклады с предупреждением и без."""
    a = _decompose(proj)
    _set_dates(proj, OLD_READ)
    b = _decompose(proj)
    assert [(c["name"], c["contribution"]) for c in a["channels"]] == \
           [(c["name"], c["contribution"]) for c in b["channels"]]
    assert a["baseline_pct"] == b["baseline_pct"]
