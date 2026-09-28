"""в-1 (s56): строка с числами без даты в любом месте входного файла.

Зонд s56 до правки: строка средних без слова с пустой датой проходила
проверку данных со статусом «ok» и обучалась ещё одним периодом (OLS
`n_obs` 49 вместо 48) – в хвосте, в середине (там ещё и сдвигала адсток
следующих периодов) и после медиаплана (там же прятала план целиком);
строка реального периода со стёртой датой тоже обучалась молча.

Правило: строка, где есть числа, а дата не распознаётся, – отказ с номерами
строк файла, в проверке данных и в обоих движках обучения. Пустые строки и
строки без чисел пропускаются. Итоговая строка сохраняет свой текст.
Предохранитель: дата должна распознаваться у большинства строк с числами,
иначе это формат дат, и правило молчит.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.planning import (  # noqa: E402
    find_trailing_total_rows,
    find_undated_rows,
    undated_rows_message,
)

N_HIST = 36


def _frame(n_hist: int = N_HIST, n_plan: int = 0) -> pd.DataFrame:
    """Месячные данные: история (KPI заполнен) + план (KPI пуст)."""
    n = n_hist + n_plan
    rng = np.random.RandomState(3)
    df = pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=n, freq="MS"),
        "sales": list(rng.uniform(1000, 2000, n_hist)) + [np.nan] * n_plan,
        "tv_spend": rng.uniform(100, 300, n),
        "digital_spend": rng.uniform(50, 150, n),
        "price_index": rng.uniform(0.9, 1.1, n),
    })
    df["date"] = df["date"].astype(object)
    return df


def _means(df: pd.DataFrame) -> dict:
    return {c: df[c].mean() for c in ("sales", "tv_spend", "digital_spend", "price_index")}


def _insert(df: pd.DataFrame, pos: int, row: dict) -> pd.DataFrame:
    """Вставить строку на позицию pos (0 – первая строка данных);
    незаданные ячейки пусты, дата пуста."""
    new = pd.DataFrame([{**{c: np.nan for c in df.columns}, "date": None, **row}])
    return pd.concat([df.iloc[:pos], new, df.iloc[pos:]], ignore_index=True)


def _save(df: pd.DataFrame, tmp_path: Path, name: str = "data.xlsx") -> Path:
    p = tmp_path / name
    df.to_excel(p, index=False)
    return p


def _validate(p: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(p))


def _issues(res: dict, kind: str) -> list[dict]:
    return [i for i in res.get("issues", []) if i.get("type") == kind]


def _train_cfg(p: Path) -> dict:
    return {"data_file": str(p), "kpi_column": "sales",
            "media_columns": ["tv_spend", "digital_spend"],
            "control_columns": ["price_index"], "date_column": "date",
            "adstock_config": {}}


def _ols(p: Path, tmp_path: Path) -> dict:
    from engines.ols_modeler import train_ols
    return train_ols(_train_cfg(p), str(tmp_path / "proj"))


def _bayes(p: Path, tmp_path: Path) -> dict:
    from engines.modeler import train_model
    return train_model(_train_cfg(p), str(tmp_path / "proj_b"))


# ─── Отказ: хвост, середина, стёртая дата, после плана ───────────────────────


@pytest.mark.parametrize("pos", [N_HIST, 12], ids=["tail_c1", "middle_c2"])
def test_average_row_without_date_refused_everywhere(tmp_path, pos):
    """c1/c2: строка средних без слова и без даты – в хвосте и в середине."""
    df = _frame()
    out = _insert(df, pos, _means(df))
    file_row = pos + 2
    assert find_trailing_total_rows(out, "date", "sales") == []
    assert find_undated_rows(out, "date", "sales") == [{"index": pos, "file_row": file_row}]
    p = _save(out, tmp_path)
    res = _validate(p)
    issues = _issues(res, "undated_row_in_data")
    assert [i["rows"] for i in issues] == [[file_row]]
    assert issues[0]["severity"] == "critical"
    assert issues[0]["message"].startswith(f"В строке {file_row} файла нет даты")
    assert res["status"] == "error"
    # В статистику строка не попала: 36 периодов, сумма продаж – сумма истории.
    assert res["file"]["rows"] == N_HIST
    sales = next(c for c in res["columns"] if c["name"] == "sales")
    assert sales["stats"]["sum"] == pytest.approx(df["sales"].sum(), rel=1e-6)
    tr = _ols(p, tmp_path)
    assert tr["status"] == "error"
    assert tr["error_code"] == "UNDATED_ROW_IN_DATA"
    assert tr["message"] == undated_rows_message([{"file_row": file_row}])
    tb = _bayes(p, tmp_path)
    assert tb["status"] == "error"
    assert tb["error_code"] == "UNDATED_ROW_IN_DATA"


@pytest.mark.parametrize("pos", [24, N_HIST - 1], ids=["middle_c3", "tail_c4"])
def test_real_period_with_erased_date_refused(tmp_path, pos):
    """c3/c4: у реального периода стёрта дата – до правки он молча обучался
    без подписи на оси, а последний месяц выпадал из диапазона дат."""
    out = _frame()
    out.loc[pos, "date"] = None
    assert find_undated_rows(out, "date", "sales") == [{"index": pos, "file_row": pos + 2}]
    p = _save(out, tmp_path)
    res = _validate(p)
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[pos + 2]]
    assert res["file"]["rows"] == N_HIST - 1
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


def test_average_row_after_media_plan_refused_and_plan_kept(tmp_path):
    """p1: строка средних по истории после плана. До правки прятала план
    (`media_plan_detected` = null) и обучалась 105-м периодом."""
    df = _frame(n_plan=6)
    out = _insert(df, len(df), _means(df[df["sales"].notna()]))
    file_row = N_HIST + 6 + 2
    p = _save(out, tmp_path)
    res = _validate(p)
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[file_row]]
    assert _issues(res, "total_row_in_data") == []
    plan = res["media_plan_detected"]
    assert plan is not None and plan["n_future_periods"] == 6
    assert None not in plan["future_dates"]
    tr = _ols(p, tmp_path)
    assert tr["error_code"] == "UNDATED_ROW_IN_DATA"
    assert f"В строке {file_row} " in tr["message"]


def test_plan_rows_with_dates_not_refused(tmp_path):
    """p0: плановые строки С датами (KPI пуст) – не строки без даты."""
    df = _frame(n_plan=6)
    assert find_undated_rows(df, "date", "sales") == []
    p = _save(df, tmp_path)
    res = _validate(p)
    assert _issues(res, "undated_row_in_data") == []
    assert res["media_plan_detected"]["n_future_periods"] == 6
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["n_obs"] == N_HIST


# ─── Итоговая строка – прежний текст, одну строку дважды не сообщаем ─────────


def test_total_row_keeps_its_own_message(tmp_path):
    """Итог со словом – текст итога (`total_row_in_data`), не новый."""
    df = _frame()
    df["comment"] = ""
    out = _insert(df, len(df), {**_means(df), "comment": "Среднее"})
    assert find_undated_rows(out, "date", "sales") == []
    p = _save(out, tmp_path)
    res = _validate(p)
    assert [i["rows"] for i in _issues(res, "total_row_in_data")] == [[N_HIST + 2]]
    assert _issues(res, "undated_row_in_data") == []
    tr = _ols(p, tmp_path)
    assert tr["error_code"] == "TOTAL_ROW_IN_DATA"
    assert "итоговую или среднюю" in tr["message"]


def test_total_and_undated_rows_reported_separately(tmp_path):
    """Итог в хвосте и строка без даты в середине: каждая – в своей
    проблеме, одна и та же строка дважды не сообщается."""
    df = _frame()
    df["comment"] = ""
    out = _insert(df, 12, _means(df))
    out = _insert(out, len(out), {"sales": df["sales"].sum(), "comment": "Итого"})
    res = _validate(_save(out, tmp_path))
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[14]]
    assert [i["rows"] for i in _issues(res, "total_row_in_data")] == [[N_HIST + 3]]
    assert res["file"]["rows"] == N_HIST


# ─── Что правило пропускает ──────────────────────────────────────────────────


def test_fully_empty_row_is_skipped(tmp_path):
    """Полностью пустая строка в середине – не отказ (в обучение она и так
    не попадает: KPI пуст)."""
    out = _insert(_frame(), 12, {})
    assert find_undated_rows(out, "date", "sales") == []
    p = _save(out, tmp_path)
    assert _issues(_validate(p), "undated_row_in_data") == []
    assert _ols(p, tmp_path)["status"] == "ok"


def test_empty_row_with_blank_second_date_column_is_skipped():
    """Пустая ячейка второй колонки дат (NaT) – не число: `to_numeric`
    превращает NaT в целое, без поправки пустая строка дала бы отказ."""
    df = _frame()
    df["week_end"] = pd.date_range("2022-01-31", periods=len(df), freq="ME")
    out = _insert(df, 12, {"week_end": pd.NaT})
    assert out["week_end"].dtype.kind == "M"
    assert find_undated_rows(out, "date", "sales") == []


@pytest.mark.parametrize("pos", [12, N_HIST], ids=["middle", "tail"])
def test_note_row_without_numbers_is_skipped(tmp_path, pos):
    """Текстовая сноска без чисел – не отказ (как M-1 у итога)."""
    df = _frame()
    df["comment"] = ""
    out = _insert(df, pos, {"comment": "* данные за этот месяц уточняются, 2023 г."})
    assert find_undated_rows(out, "date", "sales") == []
    p = _save(out, tmp_path)
    res = _validate(p)
    assert _issues(res, "undated_row_in_data") == []
    assert res["status"] != "error"
    assert _ols(p, tmp_path)["status"] == "ok"


# ─── Предохранитель: формат дат не распознан – правило молчит ────────────────


def test_guard_silent_when_most_dates_unparsed(tmp_path):
    """Даты вида «2022-W05» `to_datetime` не разбирает: это формат дат,
    а не строки без даты, – отказа «нет даты» нет."""
    df = _frame()
    df["date"] = [f"2022-W{i + 1:02d}" for i in range(len(df))]
    assert pd.to_datetime(df["date"], errors="coerce").notna().sum() == 0
    assert find_undated_rows(df, "date", "sales") == []
    assert _issues(_validate(_save(df, tmp_path)), "undated_row_in_data") == []


def test_guard_needs_strict_majority():
    """Ровно половина строк с датой – ещё формат, правило молчит; на одну
    больше – уже отдельные строки без даты."""
    df = _frame(n_hist=10)
    half = df.copy()
    half.loc[5:, "date"] = None
    assert find_undated_rows(half, "date", "sales") == []
    more = df.copy()
    more.loc[6:, "date"] = None
    assert [r["file_row"] for r in find_undated_rows(more, "date", "sales")] == [8, 9, 10, 11]


def test_guard_silent_without_date_column():
    df = _frame().rename(columns={"date": "x"})
    assert find_undated_rows(df, None, "sales") == []


# ─── Несколько строк: множественное число и «и ещё K» ────────────────────────


def test_several_rows_plural_message(tmp_path):
    out = _frame()
    for pos in (3, 7, 20):
        out.loc[pos, "date"] = None
    rows = find_undated_rows(out, "date", "sales")
    assert [r["file_row"] for r in rows] == [5, 9, 22]
    msg = undated_rows_message(rows)
    assert msg.startswith("В строках 5, 9, 22 файла нет даты, а в ячейках есть числа. "
                          "Строки без даты")
    assert "и ещё" not in msg
    res = _validate(_save(out, tmp_path))
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[5, 9, 22]]
    assert res["file"]["rows"] == N_HIST - 3


def test_more_than_five_rows_listed_with_rest_count():
    out = _frame()
    positions = [1, 5, 7, 10, 13, 16, 19, 22, 25]
    for pos in positions:
        out.loc[pos, "date"] = None
    rows = find_undated_rows(out, "date", "sales")
    assert [r["file_row"] for r in rows] == [p + 2 for p in positions]
    assert undated_rows_message(rows).startswith(
        "В строках 3, 7, 9, 12, 15 и ещё в 4 строках файла нет даты")
    # согласование: одна оставшаяся строка – «в 1 строке», 11 – «в 11 строках»
    six = [{"file_row": n} for n in range(2, 8)]
    assert "и ещё в 1 строке файла нет даты" in undated_rows_message(six)
    sixteen = [{"file_row": n} for n in range(2, 18)]
    assert "и ещё в 11 строках файла нет даты" in undated_rows_message(sixteen)


def test_single_row_message_verbatim():
    assert undated_rows_message([{"file_row": 26}]) == (
        "В строке 26 файла нет даты, а в ячейках есть числа. Строку без даты "
        "программа не может поставить на шкалу времени: если это итог, среднее "
        "или примечание, при обучении она станет лишним периодом и исказит "
        "продажи и бюджеты. Заполните дату в этой строке или удалите строку и "
        "загрузите файл заново.")


def test_plural_message_verbatim():
    rows = [{"file_row": n} for n in (3, 7, 9)]
    assert undated_rows_message(rows) == (
        "В строках 3, 7, 9 файла нет даты, а в ячейках есть числа. Строки без "
        "даты программа не может поставить на шкалу времени: если это итоги, "
        "средние или примечания, при обучении они станут лишними периодами и "
        "исказят продажи и бюджеты. Заполните даты в этих строках или удалите "
        "строки и загрузите файл заново.")


def test_training_resolves_date_column_like_total_detector(tmp_path):
    """Конфиг переоткрытого проекта несёт date_column='date' при файле с
    «Дата» – колонка распознаётся, как у детектора итогов (M-2, s55)."""
    out = _frame().rename(columns={"date": "Дата"})
    out.loc[12, "Дата"] = None
    p = _save(out, tmp_path)
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
    assert _bayes(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
