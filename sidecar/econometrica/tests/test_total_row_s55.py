"""L4 (s55): строка «итого» без даты в хвосте входного файла.

Проба на демо-файле до правки: итог с пустой датой и суммами столбцов
проходил проверку данных со статусом «ok» без единого предупреждения и
обучался как ещё один период (OLS `n_obs` 49 вместо 48, продажи удвоены);
«Итого» в колонке даты давал расплывчатое `date_parse` и падение обучения
`DateParseError`; в файле с медиапланом итог с пустым KPI становился 33-м
«периодом плана» с датой `None`.

Правило: итог в хвосте (после последней строки с датой) — в данные не берём,
человеку сообщаем номер строки; обучение на таком файле отказывает с тем же
текстом. Пустая дата в СЕРЕДИНЕ данных — прежнее поведение (другая ошибка).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.planning import find_trailing_total_rows  # noqa: E402

N_HIST = 36


def _frame(n_hist: int = N_HIST, n_plan: int = 0) -> pd.DataFrame:
    """Месячные данные: история (KPI заполнен) + план (KPI пуст)."""
    n = n_hist + n_plan
    rng = np.random.RandomState(3)
    return pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=n, freq="MS"),
        "sales": list(rng.uniform(1000, 2000, n_hist)) + [np.nan] * n_plan,
        "tv_spend": rng.uniform(100, 300, n),
        "digital_spend": rng.uniform(50, 150, n),
        "price_index": rng.uniform(0.9, 1.1, n),
    })


def _with_total(df: pd.DataFrame, date_value, *, kpi_empty: bool = False) -> pd.DataFrame:
    """Дописать в конец строку-итог: суммы числовых столбцов."""
    total = {c: df[c].sum() for c in df.columns if c != "date"}
    if kpi_empty:
        total["sales"] = np.nan
    total["date"] = date_value
    out = df.copy()
    out["date"] = out["date"].astype(object)
    out.loc[len(out)] = total
    return out


def _save(df: pd.DataFrame, tmp_path: Path, name: str = "data.xlsx") -> Path:
    p = tmp_path / name
    df.to_excel(p, index=False)
    return p


def _validate(p: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(p))


def _total_issues(res: dict) -> list[dict]:
    return [i for i in res.get("issues", []) if i.get("type") == "total_row_in_data"]


# ─── Проверка данных: оба вида итога ─────────────────────────────────────────


@pytest.mark.parametrize("date_value", [None, "Итого"], ids=["blank_date", "itogo_in_date"])
def test_validate_reports_total_row_with_file_row_number(tmp_path, date_value):
    p = _save(_with_total(_frame(), date_value), tmp_path)
    res = _validate(p)
    issues = _total_issues(res)
    assert len(issues) == 1, res.get("issues")
    # 36 строк данных + заголовок → итог в строке 38 файла.
    assert issues[0]["rows"] == [N_HIST + 2]
    assert f"Строка {N_HIST + 2} " in issues[0]["message"]
    assert issues[0]["severity"] == "critical"
    assert res["status"] == "error"
    # В статистику итог не попал: строк ровно 36, сумма продаж — сумма истории.
    assert res["file"]["rows"] == N_HIST
    sales = next(c for c in res["columns"] if c["name"] == "sales")
    assert sales["stats"]["sum"] == pytest.approx(_frame()["sales"].sum(), rel=1e-6)


def test_validate_total_word_in_text_cell_without_sums(tmp_path):
    """Слово «Итого» в любой текстовой ячейке — итог, даже если суммы не сходятся."""
    df = _frame()
    df["comment"] = ""
    out = df.copy()
    out["date"] = out["date"].astype(object)
    out.loc[len(out)] = {"date": None, "sales": 1.0, "tv_spend": 2.0,
                         "digital_spend": 3.0, "price_index": 1.0, "comment": "ИТОГО:"}
    res = _validate(_save(out, tmp_path))
    assert [i["rows"] for i in _total_issues(res)] == [[N_HIST + 2]]


def test_plan_file_total_with_empty_kpi_not_counted_as_plan_period(tmp_path):
    """Сценарий аудита s53: итог с пустым KPI в файле с медиапланом."""
    p = _save(_with_total(_frame(n_plan=6), None, kpi_empty=True), tmp_path)
    res = _validate(p)
    assert len(_total_issues(res)) == 1
    plan = res["media_plan_detected"]
    assert plan is not None
    assert plan["n_future_periods"] == 6
    assert None not in plan["future_dates"]


def test_plan_file_total_with_kpi_keeps_plan_detected(tmp_path):
    """До правки итог с суммой продаж прятал медиаплан целиком."""
    p = _save(_with_total(_frame(n_plan=6), None), tmp_path)
    res = _validate(p)
    assert len(_total_issues(res)) == 1
    assert (res["media_plan_detected"] or {}).get("n_future_periods") == 6


# ─── Контроль: чего правка не трогает ────────────────────────────────────────


def test_blank_date_in_the_middle_is_not_a_total(tmp_path):
    """Пустая дата в середине данных — другая ошибка, прежнее поведение."""
    df = _frame()
    df["date"] = df["date"].astype(object)
    df.loc[10, "date"] = None
    assert find_trailing_total_rows(df, "date", "sales") == []
    res = _validate(_save(df, tmp_path))
    assert _total_issues(res) == []
    assert res["file"]["rows"] == N_HIST


def test_trailing_row_without_date_and_without_totals_is_not_flagged():
    """Строка без даты в хвосте, но без слова и без сумм — не итог."""
    df = _frame()
    df["date"] = df["date"].astype(object)
    df.loc[len(df)] = {"date": None, "sales": 1500.0, "tv_spend": 200.0,
                       "digital_spend": 100.0, "price_index": 1.0}
    assert find_trailing_total_rows(df, "date", "sales") == []


def test_clean_file_has_no_total_rows(tmp_path):
    res = _validate(_save(_frame(), tmp_path))
    assert _total_issues(res) == []
    assert find_trailing_total_rows(_frame(n_plan=6), "date", "sales") == []


# ─── Обучение отказывает ─────────────────────────────────────────────────────


def _train_cfg(p: Path) -> dict:
    return {"data_file": str(p), "kpi_column": "sales",
            "media_columns": ["tv_spend", "digital_spend"],
            "control_columns": ["price_index"], "date_column": "date",
            "adstock_config": {}}


@pytest.mark.parametrize("date_value", [None, "Итого"], ids=["blank_date", "itogo_in_date"])
def test_ols_training_refuses_total_row(tmp_path, date_value):
    from engines.ols_modeler import train_ols
    p = _save(_with_total(_frame(), date_value), tmp_path)
    res = train_ols(_train_cfg(p), str(tmp_path / "proj"))
    assert res["status"] == "error"
    assert res["error_code"] == "TOTAL_ROW_IN_DATA"
    assert f"Строка {N_HIST + 2} " in res["message"]


def test_bayesian_training_refuses_total_row(tmp_path):
    from engines.modeler import train_model
    p = _save(_with_total(_frame(), None), tmp_path)
    res = train_model(_train_cfg(p), str(tmp_path / "proj"))
    assert res["status"] == "error"
    assert res["error_code"] == "TOTAL_ROW_IN_DATA"


# ─── Аудит s55 (AUDIT_s55_257.md): H-1, H-2, M-1, M-2, L-2 ─────────────────


def _append(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    """Дописать строку без даты; незаданные ячейки пусты."""
    out = df.copy()
    out["date"] = out["date"].astype(object)
    out.loc[len(out)] = {**{c: np.nan for c in out.columns}, "date": None, **row}
    return out


def _plan_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["sales"].isna()]


def test_plan_total_over_plan_rows_only_is_detected(tmp_path):
    """H-1 сценарий A: итог под бюджетами плана, посчитанный только по строкам плана."""
    df = _frame(n_plan=6)
    plan = _plan_rows(df)
    out = _append(df, {"tv_spend": plan["tv_spend"].sum(),
                       "digital_spend": plan["digital_spend"].sum()})
    assert find_trailing_total_rows(out, "date", "sales") == [
        {"index": N_HIST + 6, "file_row": N_HIST + 6 + 2, "reason": "sums"}]
    res = _validate(_save(out, tmp_path))
    assert len(_total_issues(res)) == 1
    plan_det = res["media_plan_detected"]
    assert plan_det["n_future_periods"] == 6
    assert None not in plan_det["future_dates"]


def test_plan_total_with_zero_kpi_refused_by_training(tmp_path):
    """H-1 сценарий B: итог плана по всем столбцам, в ячейке KPI 0 (=СУММ пустого)."""
    from engines.ols_modeler import train_ols
    df = _frame(n_plan=6)
    plan = _plan_rows(df)
    out = _append(df, {"sales": 0.0, "tv_spend": plan["tv_spend"].sum(),
                       "digital_spend": plan["digital_spend"].sum(),
                       "price_index": plan["price_index"].sum()})
    p = _save(out, tmp_path)
    assert len(_total_issues(_validate(p))) == 1
    res = train_ols(_train_cfg(p), str(tmp_path / "proj"))
    assert res["status"] == "error"
    assert res["error_code"] == "TOTAL_ROW_IN_DATA"


def test_kpi_sum_alone_is_a_total(tmp_path):
    """H-2: «подбили итог продаж» – одна ячейка, сумма KPI."""
    from engines.ols_modeler import train_ols
    df = _frame()
    out = _append(df, {"sales": df["sales"].sum()})
    assert [r["reason"] for r in find_trailing_total_rows(out, "date", "sales")] == ["sums"]
    p = _save(out, tmp_path)
    res = train_ols(_train_cfg(p), str(tmp_path / "proj"))
    assert res["error_code"] == "TOTAL_ROW_IN_DATA"


def test_kpi_sum_with_averaged_other_columns_is_a_total():
    """H-2: сумма по KPI, средние по прочим столбцам (совпадений меньше половины)."""
    df = _frame()
    out = _append(df, {"sales": df["sales"].sum(), "tv_spend": df["tv_spend"].mean(),
                       "digital_spend": df["digital_spend"].mean(),
                       "price_index": df["price_index"].mean()})
    assert [r["reason"] for r in find_trailing_total_rows(out, "date", "sales")] == ["sums"]


def test_single_non_kpi_sum_match_is_not_a_total():
    """Одно совпадение вне KPI – по-прежнему случайность."""
    df = _frame()
    last = df.iloc[-1]
    out = _append(df, {"sales": last["sales"], "tv_spend": df["tv_spend"].sum(),
                       "digital_spend": last["digital_spend"],
                       "price_index": last["price_index"]})
    assert find_trailing_total_rows(out, "date", "sales") == []


def test_kpi_with_negative_values_needs_majority():
    """KPI со знаком (прибыль): одно совпадение с суммой ничего не доказывает."""
    df = _frame()
    df["sales"] = df["sales"] - 1500.0
    last = df.iloc[-1]
    out = _append(df, {"sales": df["sales"].sum(), "tv_spend": last["tv_spend"],
                       "digital_spend": last["digital_spend"],
                       "price_index": last["price_index"]})
    assert find_trailing_total_rows(out, "date", "sales") == []


@pytest.mark.parametrize("note", [
    "Источник: внутренняя отчётность клиента, суммы без НДС",
    "Примечание: всего 48 месяцев, 2025 – предварительные данные",
    "Source: client data, total market excluded",
], ids=["summ", "vsego", "total_en"])
def test_note_row_with_total_word_but_no_numbers_is_not_a_total(tmp_path, note):
    """M-1: строка-сноска без чисел в хвосте – не итог, обучение идёт."""
    from engines.ols_modeler import train_ols
    out = _append(_frame(), {"date": note})
    assert find_trailing_total_rows(out, "date", "sales") == []
    p = _save(out, tmp_path)
    res = _validate(p)
    assert _total_issues(res) == []
    assert res["status"] != "error"
    tr = train_ols(_train_cfg(p), str(tmp_path / "proj"))
    assert tr["status"] == "ok", tr.get("message")


def test_training_detects_date_column_when_config_names_default(tmp_path):
    """M-2: в файле «Дата», в конфиге переоткрытого проекта date_column='date'."""
    from engines.ols_modeler import train_ols
    from engines.modeler import train_model
    out = _with_total(_frame(), None).rename(columns={"date": "Дата"})
    assert [r["file_row"] for r in find_trailing_total_rows(out, "date", "sales")] == [N_HIST + 2]
    p = _save(out, tmp_path)
    cfg = _train_cfg(p)
    assert cfg["date_column"] == "date"
    assert train_ols(cfg, str(tmp_path / "proj"))["error_code"] == "TOTAL_ROW_IN_DATA"
    assert train_model(cfg, str(tmp_path / "proj_b"))["error_code"] == "TOTAL_ROW_IN_DATA"


@pytest.mark.parametrize("word", ["Totals", "Subtotal", "Sum"])
def test_english_total_words_detected(word):
    """L-2: «Totals», «Subtotal», «Sum» при числе в строке."""
    df = _frame()
    out = _append(df, {"date": word, "sales": 1.0})
    assert [r["reason"] for r in find_trailing_total_rows(out, "date", "sales")] == ["word"]
