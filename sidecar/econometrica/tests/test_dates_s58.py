"""Единый разбор дат колонки (N0, выпуск 2.5.9) и пункты потока А.

До 2.5.9 колонку даты разбирал сырой `pd.to_datetime` в полутора десятках
мест, и у клиентов 2.5.8 жили молча неверные ЗНАЧЕНИЯ дат (PLANAUDIT_259):
- C-1: «01.02.2021» из CSV русского Excel читался месяцем впереди – месячные
  данные становились днями января (гранулярность «D», план «2024-01-01 …
  2024-01-06»), недельный «02.01.2023 …» ронял байес HTTP 500;
- C-2: «Jan-23» – 23 января года 1, «янв.23» – падение байеса;
- N3: «+00:00/+03:00» в одной колонке – сырой «Mixed timezones», HTTP 500.

Тесты – на ЗНАЧЕНИЯ, против эталона `pd.date_range`, а не на «дата есть».
Там же: N4 (нулевая строка после плана), N5/L-1 (план по календарной колонке),
N6 (итог с датой), N8 (сбой детектора), N9 (NaT второй колонки дат), N13
(текст NON_NUMERIC), тест на выжившую мутацию M7, N22 (mROAS в прозе).
"""
from __future__ import annotations

import datetime as dt
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dates import (  # noqa: E402
    ambiguous_day_month_example,
    parse_dates,
    unparsed_examples,
)

RU_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
RU_FULL = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
           "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS = pd.date_range("2021-01-01", periods=36, freq="MS")
# Первый день ≤ 12 – pandas брал «02.01.2023» за 1 февраля.
WEEKS = pd.date_range("2023-01-02", periods=54, freq="7D")


def _eq(parsed: pd.Series, expected) -> None:
    got = [pd.Timestamp(x) if pd.notna(x) else None for x in parsed.tolist()]
    want = [pd.Timestamp(x) if x is not None else None for x in expected]
    assert got == want


# ─── Помощник: значения по каждому формату ──────────────────────────────────

VALUE_CASES = {
    "monthly_ddmm": ([d.strftime("%d.%m.%Y") for d in MONTHS], MONTHS),
    "weekly_ddmm_first_day_le_12": ([d.strftime("%d.%m.%Y") for d in WEEKS], WEEKS),
    "weekly_ddmm_short_year": ([d.strftime("%d.%m.%y") for d in WEEKS], WEEKS),
    "ddmm_with_time": ([d.strftime("%d.%m.%Y 0:00:00") for d in WEEKS], WEEKS),
    "Jan-23": ([d.strftime("%b-%y") for d in MONTHS], MONTHS),
    "Jan 2023": ([d.strftime("%b %Y") for d in MONTHS], MONTHS),
    "янв.23": ([f"{RU_SHORT[d.month - 1]}.{d:%y}" for d in MONTHS], MONTHS),
    "январь 2023": ([f"{RU_FULL[d.month - 1].capitalize()} {d.year}" for d in MONTHS], MONTHS),
    "янв 2023": ([f"{RU_SHORT[d.month - 1]} {d.year}" for d in MONTHS], MONTHS),
    "iso": ([d.strftime("%Y-%m-%d") for d in WEEKS], WEEKS),
    "iso_T": ([d.strftime("%Y-%m-%dT00:00:00") for d in WEEKS], WEEKS),
    "iso_midnight_+03": ([d.strftime("%Y-%m-%dT00:00:00+03:00") for d in MONTHS], MONTHS),
    "iso_midnight_mixed_tz": (
        [d.strftime("%Y-%m-%dT00:00:00") + ("+00:00" if i % 2 else "+03:00")
         for i, d in enumerate(MONTHS)], MONTHS),
    "slash_ymd": ([d.strftime("%Y/%m/%d") for d in WEEKS], WEEKS),
    "slash_mdy_second_gt_12": ([d.strftime("%m/%d/%Y") for d in WEEKS], WEEKS),
    "slash_dmy_first_gt_12": ([d.strftime("%d/%m/%Y") for d in WEEKS], WEEKS),
    "day_month_word_year": ([f"{d.day} {d:%B %Y}" for d in WEEKS], WEEKS),
    "day_ru_month_year": ([f"{d.day} {RU_SHORT[d.month - 1]}. {d.year} г." for d in WEEKS], WEEKS),
    "datetime_objects": (list(WEEKS.to_pydatetime()), WEEKS),
    "date_objects": ([d.date() for d in WEEKS], WEEKS),
    "iso_plus_one_ddmm": (
        [d.strftime("%Y-%m-%d") for d in WEEKS[:10]] + [WEEKS[10].strftime("%d.%m.%Y")]
        + [d.strftime("%Y-%m-%d") for d in WEEKS[11:]], WEEKS),
    "timestamps_and_ddmm": (list(WEEKS[:20]) + [d.strftime("%d.%m.%Y") for d in WEEKS[20:]], WEEKS),
}


@pytest.mark.parametrize("kind", list(VALUE_CASES))
def test_parse_dates_values_match_reference(kind):
    cells, expected = VALUE_CASES[kind]
    _eq(parse_dates(pd.Series(cells, dtype=object)), list(expected))


def test_parse_dates_monthly_all_le_12_is_day_first():
    """Все числа ≤ 12, разделитель «.» – русский формат, день впереди: «01.02.2021»
    – 1 февраля, а не 2 января (C-1)."""
    s = pd.Series(["01.01.2021", "01.02.2021", "01.03.2021"])
    _eq(parse_dates(s), ["2021-01-01", "2021-02-01", "2021-03-01"])
    assert ambiguous_day_month_example(s) is None


def test_parse_dates_slash_all_le_12_is_day_first_and_ambiguous():
    """Все ≤ 12 и ни одно число не постоянно – день впереди, порядок не
    определён (предупреждение проверки). Переписан осознанно (H-1
    AUDIT_259): прежний пример «01/02/2023, 01/03/2023» – постоянное «01»,
    теперь это день, и порядок определён."""
    s = pd.Series(["02/01/2023", "03/02/2023", "04/03/2023"])
    _eq(parse_dates(s), ["2023-01-02", "2023-02-03", "2023-03-04"])
    assert ambiguous_day_month_example(s) == "02/01/2023"


def test_parse_dates_midnight_plus_03_keeps_local_date():
    """H-2: utc=True уводил полночь «+03:00» в предыдущие сутки (2022-12-31)."""
    s = pd.Series(["2023-01-01T00:00:00+03:00"])
    assert parse_dates(s).iloc[0] == pd.Timestamp("2023-01-01")


def test_parse_dates_xlsx_column(tmp_path):
    """Даты из xlsx – как есть, тот же ряд, что эталон."""
    from engines.data_io import read_data_file
    p = tmp_path / "d.xlsx"
    pd.DataFrame({"date": WEEKS, "sales": range(len(WEEKS))}).to_excel(p, index=False)
    _eq(parse_dates(read_data_file(p)["date"]), list(WEEKS))


def test_parse_dates_not_a_date_is_nat():
    # «12:30» pandas берёт за сегодняшнюю дату, «23 Jan» – за год 1: год без
    # четырёх цифр не выдумываем.
    s = pd.Series(["2023-01-02", "Итого", "Среднее", "23 Jan", "12:30", "2016-W37", None, 5],
                  dtype=object)
    parsed = parse_dates(s)
    assert parsed.iloc[0] == pd.Timestamp("2023-01-02")
    assert parsed.iloc[1:].isna().all()
    assert unparsed_examples(s, parsed) == ["Итого", "Среднее", "23 Jan"]
    assert unparsed_examples(s, parsed, limit=5) == ["Итого", "Среднее", "23 Jan", "12:30", "2016-W37"]


def test_parse_dates_numeric_column_is_nat():
    """Номера недель / серийные номера – не дата (прежде 1970-01-01)."""
    assert parse_dates(pd.Series([1, 2, 3])).isna().all()


def test_parse_dates_keeps_index():
    s = pd.Series(["01.02.2023", "13.02.2023"], index=[7, 3])
    assert list(parse_dates(s).index) == [7, 3]


# ─── Проверка данных: значения, план, предупреждения ───────────────────────


def _base(n_hist: int, dates, n_plan: int = 6) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    n = n_hist + n_plan
    df = pd.DataFrame({
        "date": list(dates[:n]),
        "sales": list(rng.uniform(1e5, 2e5, n_hist).round(0)) + [np.nan] * n_plan,
        "tv_spend": rng.uniform(1e4, 5e4, n).round(0),
        "digital_spend": rng.uniform(1e3, 9e3, n).round(0),
        "price": rng.uniform(90, 110, n).round(1),
    })
    return df


def _ru_csv(df: pd.DataFrame, path: Path, fmt: str = "%d.%m.%Y") -> Path:
    """CSV русского Excel: «;», десятичная запятая, даты строкой."""
    out = df.copy()
    out["date"] = [d.strftime(fmt) for d in out["date"]]
    out.to_csv(path, sep=";", decimal=",", index=False)
    return path


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


@pytest.mark.parametrize("kind,dates,fmt", [
    ("monthly", pd.date_range("2021-01-01", periods=42, freq="MS"), "%d.%m.%Y"),
    ("weekly", pd.date_range("2023-01-02", periods=60, freq="7D"), "%d.%m.%Y"),
    ("monthly_jan23", pd.date_range("2021-01-01", periods=42, freq="MS"), "%b-%y"),
])
def test_ru_csv_validation_equals_xlsx(tmp_path, kind, dates, fmt):
    """C-1/C-2: CSV «;» с датами строкой проверка видит так же, как xlsx с теми
    же числами: диапазон дат, частота, гранулярность и подписи плана."""
    n_hist = len(dates) - 6
    df = _base(n_hist, dates)
    ctrl = tmp_path / "ctrl.xlsx"
    df.to_excel(ctrl, index=False)
    ru = _ru_csv(df, tmp_path / "ru.csv", fmt)
    a, b = _plan_view(_validate(ru)), _plan_view(_validate(ctrl))
    assert a == b
    assert a["n"] == 6 and a["gran"] in ("M", "W")


def test_ru_monthly_csv_plan_labels_are_months(tmp_path):
    df = _base(36, pd.date_range("2021-01-01", periods=42, freq="MS"))
    v = _plan_view(_validate(_ru_csv(df, tmp_path / "ru.csv")))
    assert v["gran"] == "M"
    assert v["labels"] == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    assert v["date_stats"]["min_date"] == "2021-01-01"
    assert v["date_stats"]["max_date"] == "2023-12-01"


def test_date_frequency_without_plan(tmp_path):
    """Без плана частоту считают по сырой колонке файла (с планом – по уже
    разобранной истории): месячный «01.ММ.ГГГГ» – «monthly», а не «daily»."""
    df = _base(36, MONTHS, n_plan=0)
    v = _validate(_ru_csv(df, tmp_path / "ru.csv"))
    assert v["detected"]["date_frequency"] == "monthly"
    assert v.get("media_plan_detected") is None


def _ambiguous_monthly(d) -> str:
    """Месячный ряд, где день и месяц оба ≤ 12 и оба меняются: «02/01/2021»,
    «03/02/2021» … – порядок по файлу не определить."""
    return f"{d.month % 12 + 1:02d}/{d.month:02d}/{d.year}"


@pytest.mark.parametrize("n_plan", [0, 6])
def test_slash_ambiguous_dates_warn(tmp_path, n_plan):
    """M-1 (AUDIT_259): с планом df подменяется историей, где даты уже
    разобраны, – предупреждение считается по СЫРОЙ колонке и не пропадает.
    Переписан осознанно (H-1): прежний месячный «01/ММ/ГГГГ» теперь
    определён постоянным днём «01»."""
    df = _base(36, pd.date_range("2021-01-01", periods=42, freq="MS"), n_plan=n_plan)
    df["date"] = [_ambiguous_monthly(d) for d in df["date"]]
    p = tmp_path / "amb.csv"
    df.to_csv(p, sep=";", decimal=",", index=False)
    v = _validate(p)
    warn = [w for w in v["warnings"] if w["type"] == "date_order_ambiguous"]
    assert len(warn) == 1
    assert "«02/01/2021» как 2 января 2021" in warn[0]["message"]
    assert (v.get("media_plan_detected") or {}).get("n_future_periods") == (n_plan or None)


def test_slash_unambiguous_dates_do_not_warn(tmp_path):
    df = _base(48, pd.date_range("2023-01-02", periods=48, freq="7D"), n_plan=0)
    v = _validate(_ru_csv(df, tmp_path / "ru.csv", "%d/%m/%Y"))
    assert not [w for w in v["warnings"] if w["type"] == "date_order_ambiguous"]


def test_unparsed_date_warning_asks_ddmmyyyy(tmp_path):
    """H-4: совет «Убедитесь в формате YYYY-MM-DD» спорил с отказом
    «ДД.ММ.ГГГГ» – теперь один вид даты в обоих текстах."""
    df = _base(48, pd.date_range("2023-01-02", periods=48, freq="7D"), n_plan=0)
    df["date"] = [d.strftime("%d.%m.%Y") for d in df["date"]]
    df.loc[20:, "date"] = [f"Неделя {i}" for i in range(21, 49)]
    p = tmp_path / "bad.csv"
    df.to_csv(p, sep=";", decimal=",", index=False)
    v = _validate(p)
    msgs = [w["message"] for w in v["warnings"] if w["type"] == "date_parse"]
    assert msgs and "ДД.ММ.ГГГГ" in msgs[0] and "YYYY-MM-DD" not in msgs[0]


def test_mixed_timezones_validate_and_train(tmp_path):
    """N3: «+00:00/+03:00» – проверка без сырого «Mixed timezones», OLS обучается."""
    df = _base(48, pd.date_range("2023-01-02", periods=48, freq="7D"), n_plan=0)
    df["date"] = [d.strftime("%Y-%m-%dT00:00:00") + ("+00:00" if i % 2 else "+03:00")
                  for i, d in enumerate(df["date"])]
    p = tmp_path / "tz.csv"
    df.to_csv(p, index=False)
    v = _validate(p)
    assert v["status"] != "error", v.get("message") or v.get("issues")
    ds = next(c["date_stats"] for c in v["columns"] if c["name"] == "date")
    assert (ds["min_date"], ds["max_date"]) == ("2023-01-02", "2023-11-27")
    t = _ols(p, tmp_path)
    assert t["status"] == "ok", t.get("message")
    assert t["diagnostics"]["n_obs"] == 48


# ─── Обучение ────────────────────────────────────────────────────────────────


def _cfg(p: Path, date: str = "date", **kw) -> dict:
    return {"data_file": str(p), "kpi_column": "sales",
            "media_columns": ["tv_spend", "digital_spend"], "control_columns": ["price"],
            "date_column": date, "adstock_config": {}, **kw}


def _ols(p: Path, tmp_path: Path, date: str = "date") -> dict:
    from engines.ols_modeler import train_ols
    return train_ols(_cfg(p, date), str(tmp_path / "proj_ols"))


def test_ols_on_ru_month_names_clean_and_with_mean_row(tmp_path):
    """N1: «янв.23» – OLS обучается на 36 периодах; строка средних без даты –
    отказ, а не 37-й период."""
    df = _base(36, MONTHS, n_plan=0)
    df["date"] = [f"{RU_SHORT[d.month - 1]}.{d:%y}" for d in MONTHS]
    p = tmp_path / "ru.csv"
    df.to_csv(p, sep=";", decimal=",", index=False)
    t = _ols(p, tmp_path)
    assert t["status"] == "ok" and t["diagnostics"]["n_obs"] == 36
    means = {c: df[c].mean() for c in ("sales", "tv_spend", "digital_spend", "price")}
    df2 = pd.concat([df, pd.DataFrame([{"date": None, **means}])], ignore_index=True)
    p2 = tmp_path / "ru_mean.csv"
    df2.to_csv(p2, sep=";", decimal=",", index=False)
    t2 = _ols(p2, tmp_path)
    assert t2["status"] == "error"
    assert t2["error_code"] in ("TOTAL_ROW_IN_DATA", "UNDATED_ROW_IN_DATA")


def test_bayes_unparsed_dates_refused_before_sampling(tmp_path):
    """N2: нераспознанные даты – понятный отказ DATE_NOT_PARSED, а не сырой
    «time data … doesn't match format»."""
    from engines.modeler import train_model
    df = _base(48, WEEKS, n_plan=0)
    df["date"] = [f"Неделя {i}" for i in range(1, 49)]
    p = tmp_path / "w.csv"
    df.to_csv(p, index=False)
    r = train_model(_cfg(p, mcmc_override={"chains": 1, "draws": 10, "tune": 10}),
                    str(tmp_path / "proj"))
    assert r["status"] == "error"
    assert r["error_code"] == "DATE_NOT_PARSED"
    assert "Неделя 1" in r["message"] and "ДД.ММ.ГГГГ" in r["message"]


# ─── N8: сбой детектора ─────────────────────────────────────────────────────


def _boom(*args, **kwargs):
    raise RuntimeError("boom-detector")


@pytest.mark.parametrize("engine", ["ols", "bayes"])
def test_detector_failure_is_clear_refusal(tmp_path, monkeypatch, engine):
    from engines import planning
    monkeypatch.setattr(planning, "find_trailing_total_rows", _boom)
    df = _base(48, WEEKS, n_plan=0)
    p = tmp_path / "d.xlsx"
    df.to_excel(p, index=False)
    if engine == "ols":
        r = _ols(p, tmp_path)
    else:
        from engines.modeler import train_model
        r = train_model(_cfg(p), str(tmp_path / "proj"))
    assert r["status"] == "error"
    assert r["error_code"] == "DATA_CHECK_FAILED"
    assert "boom" not in r["message"] and "DATA_CHECK_FAILED" in r["message"]


@pytest.mark.parametrize("target", [
    "find_trailing_total_rows", "find_undated_rows", "_calendar_date_column",
])
def test_detector_failure_warns_in_validation(tmp_path, monkeypatch, target):
    from engines import planning
    monkeypatch.setattr(planning, target, _boom)
    df = _base(48, WEEKS, n_plan=0)
    p = tmp_path / "d.xlsx"
    df.to_excel(p, index=False)
    v = _validate(p)
    assert [w["type"] for w in v["warnings"]].count("data_check_failed") == 1


# ─── N5 / L-1: план по календарной колонке ───────────────────────────────────


def _week_date_frame(n_hist: int = 48, n_plan: int = 6) -> pd.DataFrame:
    df = _base(n_hist, pd.date_range("2023-01-02", periods=n_hist + n_plan, freq="7D"), n_plan)
    df.insert(0, "week", range(1, n_hist + n_plan + 1))
    return df


def test_plan_dates_from_calendar_column_not_week_number(tmp_path):
    """N5: [week, date] + план – даты и подписи плана по «date», а не
    1970-01-01 по номерам недель; как у [date, week]."""
    df = _week_date_frame()
    p1 = tmp_path / "wd.xlsx"
    df.to_excel(p1, index=False)
    p2 = tmp_path / "dw.xlsx"
    df[["date", "week", "sales", "tv_spend", "digital_spend", "price"]].to_excel(p2, index=False)
    a, b = _validate(p1)["media_plan_detected"], _validate(p2)["media_plan_detected"]
    assert a["future_dates"] == b["future_dates"]
    assert a["future_dates"][0].startswith("2023-12-04")
    assert a["period_labels"] == b["period_labels"]
    assert not any(lbl.startswith("1970") for lbl in a["period_labels"])


def test_load_frames_uses_calendar_column(tmp_path):
    from engines.planning import load_frames
    df = _week_date_frame()
    p = tmp_path / "wd.xlsx"
    df.to_excel(p, index=False)
    fr = load_frames(str(p))
    assert fr["detection"]["found"]
    assert fr["detection"]["future_dates"][0].startswith("2023-12-04")


def test_media_plan_template_uses_calendar_column(tmp_path):
    """L-1: конфиг без date_column и файл [week, date] – шаблон продолжает
    даты по «date», а не 1970-01-02…"""
    from engines.planning import generate_media_plan_template
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    (project / "data").mkdir()
    df = _week_date_frame(n_plan=0)
    df = df.rename(columns={"date": "Дата", "week": "Неделя"})
    data_file = project / "data" / "data.xlsx"
    df.to_excel(data_file, index=False)
    with open(project / "models" / "latest.pkl", "wb") as f:
        pickle.dump({"media_columns": ["tv_spend", "digital_spend"], "kpi_column": "sales",
                     "data_file": str(data_file), "control_columns": []}, f)
    r = generate_media_plan_template(str(project), n_future_periods=3)
    assert r["status"] == "ok", r
    out = pd.read_excel(r["path"])
    tail = pd.to_datetime(out["Дата"]).iloc[-3:].dt.strftime("%Y-%m-%d").tolist()
    assert tail == ["2023-12-04", "2023-12-11", "2023-12-18"]


def test_media_plan_template_continues_ru_csv_dates(tmp_path):
    """Шаблон по CSV «ДД.ММ.ГГГГ»: последняя дата – по всей колонке (день
    впереди), а не по одной ячейке."""
    from engines.planning import generate_media_plan_template
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    (project / "data").mkdir()
    df = _base(40, pd.date_range("2023-01-02", periods=40, freq="7D"), n_plan=0)
    data_file = _ru_csv(df, project / "data" / "data.csv")
    with open(project / "models" / "latest.pkl", "wb") as f:
        pickle.dump({"media_columns": ["tv_spend", "digital_spend"], "kpi_column": "sales",
                     "date_column": "date", "data_file": str(data_file), "control_columns": []}, f)
    r = generate_media_plan_template(str(project), n_future_periods=2)
    assert r["status"] == "ok", r
    out = pd.read_excel(r["path"])
    assert [pd.Timestamp(x).strftime("%Y-%m-%d") for x in out["date"].iloc[-2:]] == [
        "2023-10-09", "2023-10-16"]


# ─── N4: нулевая строка после плана ─────────────────────────────────────────


def test_zero_row_after_plan_not_a_period_in_detector():
    from engines.planning import detect_media_plan_tail
    df = _base(36, pd.date_range("2021-01-01", periods=42, freq="MS"), n_plan=6)
    df = pd.concat([df, pd.DataFrame([{"tv_spend": 0.0, "digital_spend": 0.0}])], ignore_index=True)
    r = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert r["found"] and r["n_future_periods"] == 6
    assert None not in r["future_dates"]


def test_undated_row_with_media_after_plan_still_counted():
    """Строка без даты с НЕНУЛЕВЫМИ медиа – не протянутые нули: детектор её не
    выбрасывает (её отказом ловит `find_undated_rows`)."""
    from engines.planning import detect_media_plan_tail
    df = _base(36, pd.date_range("2021-01-01", periods=42, freq="MS"), n_plan=6)
    df = pd.concat([df, pd.DataFrame([{"tv_spend": 5.0, "digital_spend": 0.0}])], ignore_index=True)
    r = detect_media_plan_tail(df, "date", "sales", ["tv_spend", "digital_spend"])
    assert r["n_future_periods"] == 7


# ─── N6: итог с датой последней строкой ─────────────────────────────────────


def test_dated_total_last_row_refused(tmp_path):
    from engines.planning import find_trailing_total_rows
    df = _base(48, WEEKS, n_plan=0)
    tot = {c: df[c].sum() for c in ("sales", "tv_spend", "digital_spend", "price")}
    out = pd.concat([df, pd.DataFrame([{"date": pd.Timestamp("2023-12-31"), **tot}])],
                    ignore_index=True)
    rows = find_trailing_total_rows(out, "date", "sales")
    assert rows == [{"index": 48, "file_row": 50, "reason": "dated_sums", "column": "sales"}]
    p = tmp_path / "t.xlsx"
    out.to_excel(p, index=False)
    iss = [i for i in _validate(p)["issues"] if i["type"] == "total_row_in_data"]
    assert iss and iss[0]["rows"] == [50]
    assert "дата в ней заполнена" in iss[0]["message"] and "нет даты" not in iss[0]["message"]
    assert _ols(p, tmp_path)["error_code"] == "TOTAL_ROW_IN_DATA"


def test_ordinary_last_period_is_not_total(tmp_path):
    from engines.planning import find_trailing_total_rows
    df = _base(48, WEEKS, n_plan=0)
    assert find_trailing_total_rows(df, "date", "sales") == []
    p = tmp_path / "ok.xlsx"
    df.to_excel(p, index=False)
    assert not [i for i in _validate(p)["issues"] if i["type"] == "total_row_in_data"]


def test_dated_total_with_undated_total_both_named():
    from engines.planning import total_rows_message
    msg = total_rows_message([
        {"index": 1, "file_row": 50, "reason": "dated_sums", "column": "sales"},
        {"index": 2, "file_row": 51, "reason": "word"},
    ])
    assert "Строка 51 файла похожа на итоговую или среднюю: в ней нет даты" in msg
    assert "Строка 50 файла похожа на итоговую: дата в ней заполнена" in msg


# ─── N9: пустая вторая колонка дат – не число ───────────────────────────────


def test_footnote_with_nat_second_date_column_not_total(tmp_path):
    df = _base(48, WEEKS, n_plan=0)
    df.insert(1, "date_end", df["date"] + pd.Timedelta(days=6))
    note = pd.DataFrame([{"date": "Источник: панель, суммы без НДС"}])
    out = pd.concat([df, note], ignore_index=True)
    p = tmp_path / "de.xlsx"
    out.to_excel(p, index=False)
    t = _ols(p, tmp_path, date="date")
    assert t["status"] == "ok", t.get("message")
    assert t["diagnostics"]["n_obs"] == 48


def test_row_is_total_skips_dates_and_nat():
    from engines.planning import _row_is_total
    above = pd.DataFrame({"date": WEEKS[:3], "date_end": WEEKS[:3], "sales": [1.0, 2.0, 3.0]})
    row = pd.Series({"date": np.nan, "date_end": pd.NaT, "sales": np.nan, "note": "суммы"})
    assert _row_is_total(row, above, "date", "sales") is None
    row2 = pd.Series({"date": np.nan, "date_end": dt.datetime(2023, 1, 1), "sales": np.nan})
    assert _row_is_total(row2, above, "date", "sales") is None


# ─── N13: один текст NON_NUMERIC в проверке и обучении ──────────────────────


@pytest.mark.parametrize("bad", [" - ", "rub"])
def test_non_numeric_text_same_in_validation_and_training(tmp_path, bad):
    df = _base(48, WEEKS, n_plan=0)
    df["tv_spend"] = df["tv_spend"].astype(object)
    if bad == "rub":
        df["tv_spend"] = [f"{int(v):,} ₽".replace(",", " ") for v in df["tv_spend"]]
    else:
        df.loc[[3, 10, 20], "tv_spend"] = bad
    p = tmp_path / "nn.csv"
    df.to_csv(p, sep=";", index=False)
    v = _validate(p)
    iss = [i for i in v["issues"] if i.get("column") == "tv_spend"
           and i["type"] in ("non_numeric_values", "non_numeric_format")]
    t = _ols(p, tmp_path)
    assert t["error_code"] == "NON_NUMERIC_COLUMN"
    assert len(iss) == 1 and iss[0]["message"] == t["message"]
    assert "десятичной запятой" not in iss[0]["message"]


def test_decimal_comma_text_keeps_format_hint(tmp_path):
    """Колонка «1234,5» в CSV «,» (текст с запятой) – прежний совет про формат."""
    df = _base(48, WEEKS, n_plan=0)
    df["tv_spend"] = [f"{v:.1f}".replace(".", ",") for v in df["tv_spend"]]
    p = tmp_path / "dc.csv"
    df.to_csv(p, index=False)
    iss = [i for i in _validate(p)["issues"] if i.get("column") == "tv_spend"]
    assert iss and "десятичной запятой" in iss[0]["message"]


# ─── M7 (выжившая мутация AUDIT02 L-4) ──────────────────────────────────────


def test_total_row_detector_uses_calendar_column_with_week_numbers(tmp_path):
    """[Неделя-номер, Дата] + «Итого»: проверка называет строку итоговой
    (total_row_in_data), а не строкой без даты. Мутация M7 (детектор итогов
    без колонки даты) проходила все тесты."""
    df = _week_date_frame(n_plan=0).rename(columns={"week": "Неделя", "date": "Дата"})
    tot = {c: df[c].sum() for c in ("sales", "tv_spend", "digital_spend", "price")}
    out = pd.concat([df, pd.DataFrame([{"Неделя": "Итого", **tot}])], ignore_index=True)
    p = tmp_path / "wk.xlsx"
    out.to_excel(p, index=False)
    v = _validate(p)
    kinds = {i["type"]: i.get("rows") for i in v["issues"]}
    assert kinds.get("total_row_in_data") == [50]
    assert "undated_row_in_data" not in kinds


# ─── N22: mROAS в прозе двумя знаками ───────────────────────────────────────


def test_action_headline_mroas_two_decimals():
    from engines.narrative_adapter import derive_action_headline
    channels = [{"name": "ТВ", "mroas": 4.254}, {"name": "Digital", "mroas": 2.0}]
    h1 = derive_action_headline(channels, {"leader_channel": "Digital", "hero_channel": "ТВ"}, "mroas")
    assert h1 == "Нарастить ТВ – mROAS 4.25× против Digital"
    h2 = derive_action_headline(channels, {"leader_channel": "ТВ"}, "mroas")
    assert h2 == "Защитить лидерство ТВ – mROAS 4.25×"


# ─── Аудит 2.5.9 (AUDIT_259): H-1, M-1, M-2, L-1, L-2 ───────────────────────


US_MONTHS = pd.date_range("2021-01-01", periods=36, freq="MS")


@pytest.mark.parametrize("fmt", ["%m/%d/%Y", "%m-%d-%Y"])
def test_us_monthly_month_first(fmt):
    """H-1: «ММ/01/ГГГГ» (американская месячная выгрузка) – постоянное «01» –
    день, месяцы не становятся январём (2.5.8 читал верно)."""
    s = pd.Series([d.strftime(fmt) for d in US_MONTHS])
    _eq(parse_dates(s), list(US_MONTHS))
    assert ambiguous_day_month_example(s) is None


@pytest.mark.parametrize("fmt", ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"])
def test_ru_monthly_still_day_first_after_constancy_rule(fmt):
    """«01.ММ.ГГГГ» и «01/ММ/ГГГГ» – постоянное «01» впереди – день, порядок
    определён, предупреждения нет."""
    s = pd.Series([d.strftime(fmt) for d in US_MONTHS])
    _eq(parse_dates(s), list(US_MONTHS))
    assert ambiguous_day_month_example(s) is None


@pytest.mark.parametrize("fmt", ["%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%m-%d-%Y"])
def test_weekly_both_orders(fmt):
    _eq(parse_dates(pd.Series([d.strftime(fmt) for d in WEEKS])), list(WEEKS))


def test_us_monthly_csv_with_plan_equals_xlsx(tmp_path):
    """H-1 + M-1 на проверке: «ММ/01/ГГГГ» «,» + 6 строк плана – как xlsx."""
    df = _base(36, pd.date_range("2021-01-01", periods=42, freq="MS"))
    ctrl = tmp_path / "ctrl.xlsx"
    df.to_excel(ctrl, index=False)
    us = df.copy()
    us["date"] = [d.strftime("%m/%d/%Y") for d in us["date"]]
    p = tmp_path / "us.csv"
    us.to_csv(p, index=False)
    a, b = _plan_view(_validate(p)), _plan_view(_validate(ctrl))
    assert a == b and a["gran"] == "M"


QUARTERS = pd.date_range("2018-01-01", periods=26, freq="QS")


def _q(d) -> str:
    return f"{d:%y}Q{(d.month - 1) // 3 + 1}"


@pytest.mark.parametrize("fmt", [
    _q,
    lambda d: f"{d.year}Q{(d.month - 1) // 3 + 1}",
    lambda d: f"{d:%y}-Q{(d.month - 1) // 3 + 1}",
])
def test_quarter_values(fmt):
    """M-2: квартал «ГГQк», «ГГГГQк», «ГГ-Qк» – первый день квартала."""
    _eq(parse_dates(pd.Series([fmt(d) for d in QUARTERS])), list(QUARTERS))


def test_q23_with_plan_like_xlsx(tmp_path):
    """M-2: «23Q1» с планом – как в 2.5.8 и как xlsx: quarterly, план «Q»."""
    df = _base(24, QUARTERS, n_plan=2)
    ctrl = tmp_path / "q.xlsx"
    df.to_excel(ctrl, index=False)
    q = tmp_path / "q.csv"
    q_df = df.copy()
    q_df["date"] = [_q(d) for d in q_df["date"]]
    q_df.to_csv(q, sep=";", decimal=",", index=False)
    a, b = _plan_view(_validate(q)), _plan_view(_validate(ctrl))
    assert a == b
    assert a["gran"] == "Q" and a["freq"] == "quarterly"
    assert a["labels"] == ["2024-Q1", "2024-Q2"]


def _with_total(df: pd.DataFrame) -> pd.DataFrame:
    tot = {c: df[c].sum() for c in ("sales", "tv_spend", "digital_spend", "price")}
    return pd.concat([df, pd.DataFrame([{"date": "Итого", **tot}])], ignore_index=True)


def test_q23_total_row_refused(tmp_path):
    """M-2: «23Q1» + «Итого» – отказ итога (до правки OLS обучал 25-й период)."""
    df = _base(24, QUARTERS, n_plan=0)
    df["date"] = [_q(d) for d in df["date"]]
    p = tmp_path / "qt.csv"
    _with_total(df).to_csv(p, sep=";", decimal=",", index=False)
    crit = [i["type"] for i in _validate(p)["issues"] if i["severity"] == "critical"]
    assert crit == ["total_row_in_data"]
    assert _ols(p, tmp_path)["error_code"] == "TOTAL_ROW_IN_DATA"


def test_no_recognized_dates_refused_everywhere(tmp_path):
    """M-2: ни одной распознанной даты – детектор итогов молчал бы, и OLS обучал
    «Итого» периодом. Теперь проверка – критично, OLS и байес – DATE_NOT_PARSED."""
    from engines.modeler import train_model
    df = _base(48, WEEKS, n_plan=0)
    df["date"] = [f"Неделя {i}" for i in range(1, 49)]
    p = tmp_path / "nd.csv"
    _with_total(df).to_csv(p, sep=";", decimal=",", index=False)
    v = _validate(p)
    crit = [i for i in v["issues"] if i["severity"] == "critical"]
    assert [i["type"] for i in crit] == ["date_not_parsed"]
    assert "Неделя 1" in crit[0]["message"] and "ДД.ММ.ГГГГ" in crit[0]["message"]
    assert not [w for w in v["warnings"] if w["type"] == "date_parse"]
    t = _ols(p, tmp_path)
    assert t["error_code"] == "DATE_NOT_PARSED" and t["message"] == crit[0]["message"]
    r = train_model(_cfg(p), str(tmp_path / "proj_b"))
    assert r["error_code"] == "DATE_NOT_PARSED" and r["message"] == crit[0]["message"]


def test_two_digit_year_century_window():
    """L-1: «01.12.99» – 1999-12-01, а не 2099."""
    _eq(parse_dates(pd.Series(["01.10.99", "01.11.99", "01.12.99"])),
        ["1999-10-01", "1999-11-01", "1999-12-01"])
    _eq(parse_dates(pd.Series(["Jan-99", "Feb-99"])), ["1999-01-01", "1999-02-01"])


def test_month_day_weekly_is_not_years():
    """L-2: недельное «Jan-02, Jan-09 … Dec-25» (месяц и день) – не годы 2002…2031:
    ряд «месяц + год» немонотонен – NaT (громкий путь)."""
    weeks = pd.date_range("2023-01-02", periods=52, freq="7D")
    assert parse_dates(pd.Series([d.strftime("%b-%d") for d in weeks])).isna().all()


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_month_year_monthly_still_months(order):
    months = list(pd.date_range("2021-01-01", periods=36, freq="MS"))
    if order == "desc":
        months = months[::-1]
    _eq(parse_dates(pd.Series([d.strftime("%b-%y") for d in months])), months)


# ─── Потребители колонки даты: те же значения, что у помощника ─────────────

RU_MONTHLY = pd.date_range("2021-01-01", periods=36, freq="MS")
RU_MONTHLY_STR = [d.strftime("%d.%m.%Y") for d in RU_MONTHLY]


def test_ols_quality_dates_and_decompose_series_are_iso(tmp_path):
    """M-1: даты ряда качества OLS и декомпозиции (time_series.dates) – ISO по
    правилу дня; сырые «01.02.2021» отчёт не понимал («за анализируемый
    период»), а pandas читал их 2 января."""
    from engines.decomposer import decompose
    df = _base(36, RU_MONTHLY, n_plan=0)
    p = _ru_csv(df, tmp_path / "ru.csv")
    proj = tmp_path / "proj_ols"
    t = _ols(p, tmp_path)
    assert t["status"] == "ok", t.get("message")
    want = [d.strftime("%Y-%m-%d") for d in RU_MONTHLY]
    avp = (t.get("diagnostics") or {}).get("actual_vs_predicted") or t.get("actual_vs_predicted")
    assert avp["dates"] == want
    d = decompose(str(proj))
    assert d["status"] == "ok"
    assert d["time_series"]["dates"] == want
    assert d["decomposition_series"]["dates"] == want


def test_detect_granularity_on_raw_ru_strings():
    from utils.forecast_validation import detect_granularity
    assert detect_granularity(pd.Series(RU_MONTHLY_STR))["granularity"] == "M"
    weekly = [d.strftime("%d.%m.%Y") for d in WEEKS]
    assert detect_granularity(pd.Series(weekly))["granularity"] == "W"


def test_holiday_dummies_raw_ru_strings_equal_parsed():
    """Декомпозиция передаёт в календарь праздников сырую колонку файла."""
    from utils.holiday_calendar_ru import generate_holiday_dummies
    raw = generate_holiday_dummies(pd.Series(RU_MONTHLY_STR), mode="fraction")
    ref = generate_holiday_dummies(pd.Series(RU_MONTHLY), mode="fraction")
    pd.testing.assert_frame_equal(raw.reset_index(drop=True), ref.reset_index(drop=True))


def test_calibration_period_on_raw_ru_dates():
    from utils.calibration import prepare_calibrations
    df = _base(36, RU_MONTHLY, n_plan=0)
    df["date"] = RU_MONTHLY_STR
    out = prepare_calibrations(df, [{"channel": "tv_spend", "date_from": "2021-02-01",
                                     "date_to": "2021-04-01", "lift_abs": 100.0, "sigma_abs": 10.0}],
                               media_columns=["tv_spend", "digital_spend"], date_column="date")
    assert (out[0]["idx_from"], out[0]["idx_to"]) == (1, 4)


def test_training_year_ranges_on_raw_ru_dates(tmp_path):
    import server
    df = _base(36, RU_MONTHLY, n_plan=0)
    p = _ru_csv(df, tmp_path / "ru.csv")
    r = server._detect_training_year_ranges({"config": {"data_file": str(p), "date_column": "date"}})
    assert [(x["year"], x["n_periods"], x["start_date"], x["end_date"]) for x in r] == [
        (2021, 12, "2021-01-01", "2021-12-01"), (2022, 12, "2022-01-01", "2022-12-01"),
        (2023, 12, "2023-01-01", "2023-12-01")]
