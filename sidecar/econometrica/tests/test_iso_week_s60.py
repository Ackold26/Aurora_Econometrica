"""Недели ISO «ГГГГ-Wнн» в колонке даты (s60, выпуск 2.5.10).

Источник – выгрузки статистики и макро-ряды: «2016-W37 (нед. с 2016-09-12)».
До правки такая ячейка не читалась (NaT), проверка отказывала «date_not_parsed».
Правка ТЗ – `Projects/_s60/PLANAUDIT_DATES.md`, вердикт §5.

Тесты – на ЗНАЧЕНИЯХ против независимой формулы понедельника недели 1 (неделя,
содержащая 4 января), а не против `fromisocalendar`, которым пользуется код.
Год 2023 не различает неделю ISO и «неделю с первого понедельника» (%W):
различают 2020, 2025, 2026 (1 января – чт, ср, чт) – они в проверках.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dates import (  # noqa: E402
    ambiguous_day_month_example,
    parse_dates,
    unparsed_examples,
)

FIXTURE = Path(__file__).parent / "fixtures" / "macro_weekly_iso_sample.csv"


def _monday_of_week_1(year: int) -> dt.date:
    """Понедельник недели 1 по ISO 8601: неделя, в которой лежит 4 января."""
    jan4 = dt.date(year, 1, 4)
    return jan4 - dt.timedelta(days=jan4.weekday())


def _weeks_in_year(year: int) -> int:
    return (_monday_of_week_1(year + 1) - _monday_of_week_1(year)).days // 7


def _monday(year: int, week: int) -> pd.Timestamp:
    return pd.Timestamp(_monday_of_week_1(year) + dt.timedelta(weeks=week - 1))


def _one(cell) -> pd.Timestamp:
    return parse_dates(pd.Series([cell], dtype=object)).iloc[0]


# ─── Значения ────────────────────────────────────────────────────────────────


def test_all_52_weeks_of_2023_are_mondays():
    cells = [f"2023-W{w:02d}" for w in range(1, 53)]
    want = list(pd.date_range("2023-01-02", periods=52, freq="7D"))
    got = list(parse_dates(pd.Series(cells, dtype=object)))
    assert got == want
    assert all(ts.weekday() == 0 for ts in got)


@pytest.mark.parametrize("year", list(range(2015, 2031)))
def test_every_week_of_every_year_against_independent_formula(year):
    n = _weeks_in_year(year)
    cells = [f"{year}-W{w:02d}" for w in range(1, n + 1)]
    want = [_monday(year, w) for w in range(1, n + 1)]
    assert list(parse_dates(pd.Series(cells, dtype=object))) == want
    # Недели n + 1 в году нет – отказ, а не перенос на следующий год.
    assert pd.isna(_one(f"{year}-W{n + 1:02d}"))


@pytest.mark.parametrize("cell,expected", [
    ("2020-W53", "2020-12-28"),  # в 2020 году 53 недели
    ("2020-W52", "2020-12-21"),
    ("2021-W01", "2021-01-04"),
    ("2025-W01", "2024-12-30"),  # неделя 1 начинается в декабре; %W дал бы 2025-01-06
    ("2026-W01", "2025-12-29"),
    ("2021-W52", "2021-12-27"),
])
def test_year_boundary_weeks(cell, expected):
    assert _one(cell) == pd.Timestamp(expected)


@pytest.mark.parametrize("cell", ["2021-W53", "2023-W53", "2023-W54", "2023-W00", "2023-W99",
                                  "0000-W01", "9999-W53"])
def test_nonexistent_week_is_nat(cell):
    """Недели, которой нет в календаре ISO, – NaT (отказ с номером строки)."""
    assert pd.isna(_one(cell))


@pytest.mark.parametrize("cell", ["2023-w01", "2023W01", "2023-W1", "2023 W01", "2023 - W 01",
                                  "  2023-W01  ", "2023-w1"])
def test_spelling_variants(cell):
    assert _one(cell) == pd.Timestamp("2023-01-02")


@pytest.mark.parametrize("cell,expected", [
    ("2023-W01-1", "2023-01-02"),
    ("2023-W01-3", "2023-01-04"),
    ("2023-W01-7", "2023-01-08"),
    ("2023-W1-2", "2023-01-03"),
    ("2023-W12", "2023-03-20"),   # неделя 12, а не «неделя 1, день 2»
    ("2023-W12-5", "2023-03-24"),
    ("2020-W53-7", "2021-01-03"),
])
def test_day_of_week_through_hyphen(cell, expected):
    assert _one(cell) == pd.Timestamp(expected)


@pytest.mark.parametrize("cell", ["2023-W01-8", "2023-W01-0", "2023-W1-12", "2023-W01-"])
def test_day_of_week_out_of_range_is_nat(cell):
    assert pd.isna(_one(cell))


# ─── Хвост «(нед. с …)» ──────────────────────────────────────────────────────


@pytest.mark.parametrize("cell,expected", [
    ("2023-W01 (нед. с 02.01.2023)", "2023-01-02"),
    ("2023-W01 (нед. с 2023-01-02)", "2023-01-02"),
    ("2023-W01(нед. с 2023-01-02)", "2023-01-02"),
    ("2023-W01 (нед. с 02.01.23)", "2023-01-02"),
    ("2023-W01 (нед. с 2023-01-08)", "2023-01-02"),  # воскресенье – ещё эта неделя
    ("2020-W53 (нед. с 28.12.2020)", "2020-12-28"),
    ("2025-W01 (нед. с 30.12.2024)", "2024-12-30"),
    ("2023-W01-3 (нед. с 02.01.2023)", "2023-01-04"),
    ("2023-W01 (неделя первая)", "2023-01-02"),      # в скобках нет даты – не сверять
    ("2023-W01 ()", "2023-01-02"),
])
def test_tail_matching_the_week_is_kept(cell, expected):
    assert _one(cell) == pd.Timestamp(expected)


@pytest.mark.parametrize("cell", [
    "2023-W01 (нед. с 01.01.2023)",   # воскресенье перед неделей: счёт «с воскресенья»
    "2023-W01 (нед. с 2023-01-01)",
    "2023-W01 (нед. с 09.01.2023)",   # понедельник следующей недели
    "2023-W01 (нед. с 2023-01-09)",
    "2023-W01 (нед. с 32.01.2023)",   # дата в скобках сама не дата
    "2023-W01-3 (нед. с 09.01.2023)",
])
def test_tail_contradicting_the_week_is_nat(cell):
    """Неделя посчитана не по ISO: молчаливый сдвиг на 1–8 дней хуже отказа."""
    assert pd.isna(_one(cell))


@pytest.mark.parametrize("cell,expected", [
    # Диапазон через дефис – обычная русская запись недели: «02.01-08» не дата 2008 года.
    ("2023-W01 (02.01-08.01.2023)", "2023-01-02"),
    ("2023-W02 (09.01-15.01.2023)", "2023-01-09"),
    ("2023-W01 (02.01.2023-08.01.2023)", "2023-01-02"),
    ("2023-W01 (нед. с 02.01.2023)", "2023-01-02"),
    ("2023-W01 (нед. с 2023-01-02)", "2023-01-02"),
])
def test_tail_range_with_hyphen_reads_a_whole_date(cell, expected):
    """Разделитель внутри даты один: «02.01-08.01.2023» читается как «08.01.2023»."""
    assert _one(cell) == pd.Timestamp(expected)


@pytest.mark.parametrize("cell", [
    "2023-W01 (нед. с 01.01.2023)",   # прежний отказ сохранён
    "2023-W02 (02.01-08.01.2023)",    # диапазон не той недели – отказ, а не сдвиг
])
def test_tail_range_of_another_week_is_nat(cell):
    assert pd.isna(_one(cell))


# ─── Только полное совпадение ────────────────────────────────────────────────


@pytest.mark.parametrize("cell", [
    "2023-W01 abc", "2023-W01abc", "2023-W01-3abc", "2023-W010", "2023-W013", "2023-W017",
    "2023-W01 (нед. с 02.01.2023) лишнее",
    "x2023-W01", "12023-W01", "W01-2023", "W01", "2023-Н01", "2023-W", "2023-W-1",
])
def test_partial_matches_are_not_taken(cell):
    assert pd.isna(_one(cell))


def test_foreign_formats_unchanged():
    """Правило не перехватывает чужие форматы: те же значения, что до правки."""
    cells = ["2023-05-01", "2023", "2023-01", "2023Q1", "2023-Q1", "23Q2", "20230115",
             "Jan-23", "янв.23", "16 октября 2023", "01.02.2023", "2023/05/01"]
    want = ["2023-05-01", "2023-01-01", "2023-01-01", "2023-01-01", "2023-01-01", "2023-04-01",
            "2023-01-15", "2023-01-01", "2023-01-01", "2023-10-16", "2023-02-01", "2023-05-01"]
    for cell, w in zip(cells, want):
        assert _one(cell) == pd.Timestamp(w), cell
    assert parse_dates(pd.Series([1, 2, 3])).isna().all()


def test_ymd_and_year_month_do_not_become_weeks():
    """«2023-01» и «2023-12» – год-месяц, а не год и неделя: буквы W нет."""
    assert _one("2023-12") == pd.Timestamp("2023-12-01")
    assert _one("2023-1-5") == pd.Timestamp("2023-01-05")


def test_mixed_column_keeps_each_format():
    s = pd.Series(["2023-W01", "16.01.2023", "2023-W03 (нед. с 2023-01-16)", "2023-01-23"],
                  dtype=object)
    assert list(parse_dates(s)) == [pd.Timestamp(x) for x in
                                    ["2023-01-02", "2023-01-16", "2023-01-16", "2023-01-23"]]


def test_iso_week_cells_do_not_make_day_month_order_ambiguous():
    s = pd.Series([f"2023-W{w:02d} (нед. с {_monday(2023, w):%d.%m.%Y})" for w in range(1, 20)],
                  dtype=object)
    assert ambiguous_day_month_example(s) is None
    assert list(parse_dates(s)) == [_monday(2023, w) for w in range(1, 20)]


def test_bad_week_among_good_is_nat_and_named_in_examples():
    s = pd.Series(["2021-W52", "2021-W53", "2022-W01"], dtype=object, index=[5, 6, 7])
    parsed = parse_dates(s)
    assert list(parsed.index) == [5, 6, 7]
    assert list(parsed.isna()) == [False, True, False]
    assert unparsed_examples(s, parsed) == ["2021-W53"]


# ─── Проверка данных, план, обучение ────────────────────────────────────────


def _base(n_hist: int, dates, n_plan: int = 0) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    n = n_hist + n_plan
    return pd.DataFrame({
        "date": list(dates[:n]),
        "sales": list(rng.uniform(1e5, 2e5, n_hist).round(0)) + [np.nan] * n_plan,
        "tv_spend": rng.uniform(1e4, 5e4, n).round(0),
        "digital_spend": rng.uniform(1e3, 9e3, n).round(0),
        "price": rng.uniform(90, 110, n).round(1),
    })


def _iso_labels(dates, with_tail: bool = False) -> list[str]:
    out = []
    for d in dates:
        y, w, _ = d.isocalendar()
        out.append(f"{y}-W{w:02d}" + (f" (нед. с {d:%d.%m.%Y})" if with_tail else ""))
    return out


def _validate(p: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(p))


def _plan_view(v: dict) -> dict:
    mp = v.get("media_plan_detected") or {}
    ds = next(c.get("date_stats") for c in v["columns"] if c["name"] == v["detected"]["date"])
    return {
        "status": v["status"], "date_stats": ds, "freq": v["detected"]["date_frequency"],
        "n": mp.get("n_future_periods"), "gran": mp.get("granularity"),
        "dates": mp.get("future_dates"), "labels": mp.get("period_labels"),
        "warn": sorted(w["type"] for w in v.get("warnings", [])),
    }


def _cfg(p: Path, **kw) -> dict:
    return {"data_file": str(p), "kpi_column": "sales",
            "media_columns": ["tv_spend", "digital_spend"], "control_columns": ["price"],
            "date_column": "date", "adstock_config": {}, **kw}


# 104 недели через стык 2022/2023 и через 53-ю неделю 2020 года.
@pytest.mark.parametrize("start", ["2022-01-03", "2020-09-28"])
@pytest.mark.parametrize("with_tail", [False, True])
def test_104_weeks_across_year_boundary_are_weekly(tmp_path, start, with_tail):
    dates = pd.date_range(start, periods=104, freq="7D")
    df = _base(104, dates)
    ctrl = tmp_path / "ctrl.xlsx"
    df.to_excel(ctrl, index=False)
    iso = df.copy()
    iso["date"] = _iso_labels(dates, with_tail)
    p = tmp_path / "iso.csv"
    iso.to_csv(p, sep=";", decimal=",", index=False)
    a, b = _plan_view(_validate(p)), _plan_view(_validate(ctrl))
    assert a == b
    assert a["freq"] == "weekly"
    assert a["date_stats"]["min_date"] == start
    assert a["date_stats"]["max_date"] == str(dates[-1].date())
    assert "date_parse" not in a["warn"]


def test_plan_tail_found_on_iso_weeks(tmp_path):
    """План-хвост (строки без KPI с медиа) находится и продолжает недели ISO."""
    dates = pd.date_range("2022-10-03", periods=60, freq="7D")  # хвост – через стык 2022/2023
    df = _base(54, dates, n_plan=6)
    ctrl = tmp_path / "ctrl.xlsx"
    df.to_excel(ctrl, index=False)
    iso = df.copy()
    iso["date"] = _iso_labels(dates)
    p = tmp_path / "iso.csv"
    iso.to_csv(p, sep=";", decimal=",", index=False)
    a, b = _plan_view(_validate(p)), _plan_view(_validate(ctrl))
    assert a == b
    assert a["n"] == 6 and a["gran"] == "W"
    assert a["dates"][0].startswith("2023-10-")
    assert not any(lbl.startswith("1970") for lbl in a["labels"])


def test_plan_tail_detector_directly_on_iso_strings():
    from engines.planning import detect_media_plan_tail
    dates = pd.date_range("2022-10-03", periods=60, freq="7D")
    df = _base(54, dates, n_plan=6)
    df["date"] = _iso_labels(dates)
    r = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert r["found"] and r["n_future_periods"] == 6


def test_ols_trains_on_iso_week_file(tmp_path):
    """Короткий путь обучения (OLS): файл с «ГГГГ-Wнн» обучается так же, как тот же
    ряд с датами-объектами."""
    from engines.ols_modeler import train_ols
    dates = pd.date_range("2022-06-06", periods=60, freq="7D")  # стык 2022/2023
    df = _base(60, dates)
    ctrl = tmp_path / "ctrl.xlsx"
    df.to_excel(ctrl, index=False)
    iso = df.copy()
    iso["date"] = _iso_labels(dates, with_tail=True)
    p = tmp_path / "iso.csv"
    iso.to_csv(p, sep=";", decimal=",", index=False)
    t = train_ols(_cfg(p), str(tmp_path / "proj_iso"))
    c = train_ols(_cfg(ctrl), str(tmp_path / "proj_ctrl"))
    assert t["status"] == "ok", t.get("message")
    assert c["status"] == "ok", c.get("message")
    assert t["diagnostics"]["n_obs"] == c["diagnostics"]["n_obs"] == 60


def _weeks_with_one_bad(tmp_path: Path) -> Path:
    dates = pd.date_range("2021-01-04", periods=48, freq="7D")
    df = _base(48, dates)
    labels = _iso_labels(dates)
    labels[20] = "2021-W53"  # в 2021 году 52 недели
    df["date"] = labels
    p = tmp_path / "w.csv"
    df.to_csv(p, index=False)
    return p


def test_validation_refuses_nonexistent_week_with_row_number(tmp_path):
    """«2021-W53» среди верных недель – честный отказ с номером строки файла
    (заголовок + 20 строк данных + 1 = строка 22), а не молчаливый сдвиг."""
    v = _validate(_weeks_with_one_bad(tmp_path))
    bad = [i for i in v["issues"] if i["type"] == "undated_row_in_data"]
    assert v["status"] == "error"
    assert bad and bad[0]["rows"] == [22] and "В строке 22 файла" in bad[0]["message"]


def test_bayes_nonexistent_week_refused_before_sampling(tmp_path):
    """Тот же отказ в обучении, до выборки; байесовскую цепочку не запускаем."""
    from engines.modeler import train_model
    r = train_model(_cfg(_weeks_with_one_bad(tmp_path),
                         mcmc_override={"chains": 1, "draws": 10, "tune": 10}),
                    str(tmp_path / "proj"))
    assert r["status"] == "error"
    assert r["error_code"] == "UNDATED_ROW_IN_DATA"
    assert "В строке 22 файла" in r["message"]


def test_whole_column_of_nonexistent_weeks_is_date_not_parsed(tmp_path):
    """Если не читается вся колонка – DATE_NOT_PARSED с самой ячейкой в примерах."""
    from engines.modeler import train_model
    df = _base(48, pd.date_range("2023-01-02", periods=48, freq="7D"))
    df["date"] = [f"2023-W{60 + i}" for i in range(48)]
    p = tmp_path / "w.csv"
    df.to_csv(p, index=False)
    r = train_model(_cfg(p, mcmc_override={"chains": 1, "draws": 10, "tune": 10}),
                    str(tmp_path / "proj"))
    assert r["status"] == "error"
    assert r["error_code"] == "DATE_NOT_PARSED"
    assert "2023-W60" in r["message"]


# ─── Фикстура: 20 недель выгрузки macro_weekly ──────────────────────────────


def test_macro_weekly_fixture_dates_read_and_match_tails():
    raw = pd.read_csv(FIXTURE, sep=";", encoding="utf-8-sig")
    col = raw.columns[0]
    assert len(raw) == 20
    parsed = parse_dates(raw[col])
    assert parsed.notna().all()
    # Независимая сверка: дата в скобках «нед. с ГГГГ-ММ-ДД» – понедельник той же недели.
    tails = pd.to_datetime(raw[col].str.extract(r"нед\. с (\d{4}-\d{2}-\d{2})")[0])
    assert list(parsed) == list(tails)
    assert parsed.iloc[0] == pd.Timestamp("2016-09-12")
    assert parsed.iloc[-1] == pd.Timestamp("2017-01-23")


def test_macro_weekly_fixture_has_no_date_not_parsed():
    v = _validate(FIXTURE)
    types = [i["type"] for i in v["issues"]]
    assert "date_not_parsed" not in types
    assert v["detected"]["date_frequency"] == "weekly"
    ds = next(c["date_stats"] for c in v["columns"] if c["name"] == v["detected"]["date"])
    assert (ds["min_date"], ds["max_date"]) == ("2016-09-12", "2017-01-23")
