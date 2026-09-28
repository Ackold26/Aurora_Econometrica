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
