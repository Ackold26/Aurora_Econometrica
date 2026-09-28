"""в-1 (s56): строка с числами без даты в любом месте входного файла.

Зонд s56 до правки: строка средних без слова с пустой датой проходила
проверку данных со статусом «ok» и обучалась ещё одним периодом (OLS
`n_obs` 49 вместо 48) – в хвосте, в середине (там ещё и сдвигала адсток
следующих периодов) и после медиаплана (там же прятала план целиком);
строка реального периода со стёртой датой тоже обучалась молча.

Правило: строка, где есть ненулевое число в колонках модели, а дата не
заполнена или не распознаётся, – отказ с номерами строк файла, в проверке
данных и в обоих движках обучения. Пустые строки, строки без чисел и строки
с числами только вне модели или нулями пропускаются. Итоговая строка
сохраняет свой текст. Предохранитель: дата должна распознаваться у
большинства строк с числами, иначе это формат дат, и правило молчит.

Аудит s56 (AUDIT01_s56.txt): H-1 – одна колонка даты в проверке и обучении,
H-2/H-3 – числа только ненулевые и только в колонках модели, M-1 – текст
«не заполнена или не распознана», M-2 – дата с днём впереди, M-5, M-6.
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
# Колонки модели в `_train_cfg`: KPI + медиа + контроль.
VALUE_COLS = ["sales", "tv_spend", "digital_spend", "price_index"]


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
    assert find_undated_rows(out, "date", VALUE_COLS) == [{"index": pos, "file_row": file_row}]
    p = _save(out, tmp_path)
    res = _validate(p)
    issues = _issues(res, "undated_row_in_data")
    assert [i["rows"] for i in issues] == [[file_row]]
    assert issues[0]["severity"] == "critical"
    assert issues[0]["message"].startswith(f"В строке {file_row} файла не заполнена или не распознана дата")
    assert res["status"] == "error"
    # В статистику строка не попала: 36 периодов, сумма продаж – сумма истории.
    assert res["file"]["rows"] == N_HIST
    sales = next(c for c in res["columns"] if c["name"] == "sales")
    assert sales["stats"]["sum"] == pytest.approx(df["sales"].sum(), rel=1e-6)
    tr = _ols(p, tmp_path)
    assert tr["status"] == "error"
    assert tr["error_code"] == "UNDATED_ROW_IN_DATA"
    # Образец даты – ближайшая строка с датой, при равенстве верхняя (L-5).
    assert tr["message"] == undated_rows_message([{"file_row": file_row}], file_row - 1)
    assert issues[0]["message"] == tr["message"]
    tb = _bayes(p, tmp_path)
    assert tb["status"] == "error"
    assert tb["error_code"] == "UNDATED_ROW_IN_DATA"
    assert tb["message"] == tr["message"]


@pytest.mark.parametrize("pos", [24, N_HIST - 1], ids=["middle_c3", "tail_c4"])
def test_real_period_with_erased_date_refused(tmp_path, pos):
    """c3/c4: у реального периода стёрта дата – до правки он молча обучался
    без подписи на оси, а последний месяц выпадал из диапазона дат."""
    out = _frame()
    out.loc[pos, "date"] = None
    assert find_undated_rows(out, "date", VALUE_COLS) == [{"index": pos, "file_row": pos + 2}]
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
    assert find_undated_rows(df, "date", VALUE_COLS) == []
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
    totals = find_trailing_total_rows(out, "date", "sales")
    assert [r["file_row"] for r in totals] == [N_HIST + 2]
    # Итоги исключает вызывающий (M-6): сам детектор итогов не зовёт.
    assert find_undated_rows(out, "date", VALUE_COLS,
                             exclude_index=[r["index"] for r in totals]) == []
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
    assert find_undated_rows(out, "date", VALUE_COLS) == []
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
    assert find_undated_rows(out, "date", VALUE_COLS + ["week_end"]) == []


@pytest.mark.parametrize("pos", [12, N_HIST], ids=["middle", "tail"])
def test_note_row_without_numbers_is_skipped(tmp_path, pos):
    """Текстовая сноска без чисел – не отказ (как M-1 у итога)."""
    df = _frame()
    df["comment"] = ""
    out = _insert(df, pos, {"comment": "* данные за этот месяц уточняются, 2023 г."})
    assert find_undated_rows(out, "date", VALUE_COLS) == []
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
    assert find_undated_rows(df, "date", VALUE_COLS) == []
    assert _issues(_validate(_save(df, tmp_path)), "undated_row_in_data") == []


def test_guard_needs_strict_majority():
    """Ровно половина строк с датой – ещё формат, правило молчит; на одну
    больше – уже отдельные строки без даты."""
    df = _frame(n_hist=10)
    half = df.copy()
    half.loc[5:, "date"] = None
    assert find_undated_rows(half, "date", VALUE_COLS) == []
    more = df.copy()
    more.loc[6:, "date"] = None
    assert [r["file_row"] for r in find_undated_rows(more, "date", VALUE_COLS)] == [8, 9, 10, 11]


def test_guard_silent_without_date_column():
    df = _frame().rename(columns={"date": "x"})
    assert find_undated_rows(df, None, VALUE_COLS) == []


# ─── Несколько строк: множественное число и «и ещё K» ────────────────────────


def test_several_rows_plural_message(tmp_path):
    out = _frame()
    for pos in (3, 7, 20):
        out.loc[pos, "date"] = None
    rows = find_undated_rows(out, "date", VALUE_COLS)
    assert [r["file_row"] for r in rows] == [5, 9, 22]
    msg = undated_rows_message(rows)
    assert msg.startswith("В строках 5, 9, 22 файла не заполнены или не распознаны даты, "
                          "а в ячейках есть числа. Строки без даты")
    assert "и ещё" not in msg
    res = _validate(_save(out, tmp_path))
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[5, 9, 22]]
    assert res["file"]["rows"] == N_HIST - 3


def test_more_than_five_rows_listed_with_rest_count():
    out = _frame()
    positions = [1, 5, 7, 10, 13, 16, 19, 22, 25]
    for pos in positions:
        out.loc[pos, "date"] = None
    rows = find_undated_rows(out, "date", VALUE_COLS)
    assert [r["file_row"] for r in rows] == [p + 2 for p in positions]
    assert undated_rows_message(rows).startswith(
        "В строках 3, 7, 9, 12, 15 и ещё в 4 строках файла не заполнены")
    # согласование: одна оставшаяся строка – «в 1 строке», 11 – «в 11 строках»
    six = [{"file_row": n} for n in range(2, 8)]
    assert "и ещё в 1 строке файла не заполнены" in undated_rows_message(six)
    sixteen = [{"file_row": n} for n in range(2, 18)]
    assert "и ещё в 11 строках файла не заполнены" in undated_rows_message(sixteen)
    # L-3 аудита s56: 21 – снова «в 21 строке» (не «строках»), а 12 – «строках».
    twenty_six = [{"file_row": n} for n in range(2, 28)]
    assert "и ещё в 21 строке файла не заполнены" in undated_rows_message(twenty_six)
    seventeen = [{"file_row": n} for n in range(2, 19)]
    assert "и ещё в 12 строках файла не заполнены" in undated_rows_message(seventeen)


def test_single_row_message_verbatim():
    """L-5 (аудит s56): вместо «например 01.02.2024» – строка-образец."""
    assert undated_rows_message([{"file_row": 26}], 25) == (
        "В строке 26 файла не заполнена или не распознана дата, а в ячейках есть "
        "числа. Строку без даты программа не может поставить на шкалу времени: "
        "если это итог, среднее или примечание, при обучении она станет лишним "
        "периодом и исказит продажи и бюджеты. Заполните дату в этой строке – так "
        "же, как в строке 25, – или удалите строку и загрузите файл заново.")
    assert undated_rows_message([{"file_row": 26}]) == (
        "В строке 26 файла не заполнена или не распознана дата, а в ячейках есть "
        "числа. Строку без даты программа не может поставить на шкалу времени: "
        "если это итог, среднее или примечание, при обучении она станет лишним "
        "периодом и исказит продажи и бюджеты. Заполните дату в этой строке – в "
        "том же виде, что и в остальных строках, – или удалите строку и загрузите "
        "файл заново.")


def test_plural_message_verbatim():
    rows = [{"file_row": n} for n in (3, 7, 9)]
    assert undated_rows_message(rows, 2) == (
        "В строках 3, 7, 9 файла не заполнены или не распознаны даты, а в "
        "ячейках есть числа. Строки без даты программа не может поставить на "
        "шкалу времени: если это итоги, средние или примечания, при обучении "
        "они станут лишними периодами и исказят продажи и бюджеты. Заполните "
        "даты в этих строках – так же, как в строке 2, – или удалите строки и "
        "загрузите файл заново.")
    assert undated_rows_message(rows) == (
        "В строках 3, 7, 9 файла не заполнены или не распознаны даты, а в "
        "ячейках есть числа. Строки без даты программа не может поставить на "
        "шкалу времени: если это итоги, средние или примечания, при обучении "
        "они станут лишними периодами и исказят продажи и бюджеты. Заполните "
        "даты в этих строках – в том же виде, что и в остальных строках, – или "
        "удалите строки и загрузите файл заново.")
    assert "01.02.2024" not in undated_rows_message(rows)


def test_training_resolves_date_column_like_total_detector(tmp_path):
    """Конфиг переоткрытого проекта несёт date_column='date' при файле с
    «Дата» – колонка распознаётся, как у детектора итогов (M-2, s55)."""
    out = _frame().rename(columns={"date": "Дата"})
    out.loc[12, "Дата"] = None
    p = _save(out, tmp_path)
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
    assert _bayes(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


# ─── Аудит s56 (AUDIT01_s56.txt) ─────────────────────────────────────────────


def _append_rows(df: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    """Дописать строки в конец; незаданные ячейки пусты, дата пуста."""
    new = pd.DataFrame([{**{c: np.nan for c in df.columns}, "date": None, **r} for r in rows])
    return pd.concat([df, new], ignore_index=True)


@pytest.mark.parametrize("case", ["avg_both_empty", "week_blank", "date_blank"])
@pytest.mark.parametrize("order", [["Дата", "Неделя"], ["Неделя", "Дата"]],
                         ids=["date_first", "week_first"])
def test_two_date_columns_validation_and_training_agree(tmp_path, order, case):
    """H-1: две колонки роли «дата». Проверка судит по той же колонке, что
    отдаёт в detected.date (последней), обучение – по date_column из конфига,
    куда detected.date и попадает. До правки проверка брала первую колонку:
    «проверка зелёная – обучение отказало» и наоборот (probe5)."""
    from engines.ols_modeler import train_ols
    df = _frame().rename(columns={"date": "Дата"})
    df["Неделя"] = pd.Series(range(1, len(df) + 1), dtype=object)
    df = df[order + VALUE_COLS]
    if case == "avg_both_empty":
        df = pd.concat([df, pd.DataFrame([{"Дата": None, "Неделя": None, **_means(df)}])],
                       ignore_index=True)
    elif case == "week_blank":
        df.loc[10, "Неделя"] = None
    else:
        df.loc[10, "Дата"] = None
    p = _save(df, tmp_path)
    res = _validate(p)
    det = res["detected"]["date"]
    assert det == order[-1]
    val_refused = bool(_issues(res, "undated_row_in_data"))
    tr = train_ols({**_train_cfg(p), "date_column": det}, str(tmp_path / "proj"))
    assert val_refused == (tr.get("error_code") == "UNDATED_ROW_IN_DATA"), tr.get("message")
    if val_refused:
        # Байес отказывает до MCMC – проверяем, что и он берёт колонку из конфига.
        from engines.modeler import train_model
        tb = train_model({**_train_cfg(p), "date_column": det}, str(tmp_path / "proj_b"))
        assert tb.get("error_code") == "UNDATED_ROW_IN_DATA"
    # По сути: «Неделя» – номера (числовая), календарь – «Дата» при любом
    # порядке колонок; отказ – ровно когда пуста «Дата» (приёмка fix02, (б)).
    expected = case in ("avg_both_empty", "date_blank")
    assert val_refused == expected


@pytest.mark.parametrize("kind", [
    "formula_zeros", "numbering", "reference_block", "bool_flag", "region_code",
    "year_in_comment",
])
def test_service_rows_outside_model_are_not_refused(tmp_path, kind):
    """H-2 (probe3/probe4 F1, F3, F4, E1–E3): строки без даты и без KPI, где
    число только в колонке вне модели или ноль, – без отказа, как до в-1
    (их отсекал фильтр пустого KPI)."""
    df = _frame()
    if kind == "formula_zeros":
        df["cpp"] = df["tv_spend"] / 10
        tail = [{"cpp": 0.0}] * 5
    elif kind == "numbering":
        df.insert(0, "№", range(1, len(df) + 1))
        tail = [{"№": len(df) + i} for i in (1, 2, 3)]
    elif kind == "reference_block":
        df["note"] = ""
        tail = [{"note": "Курс USD"}, {"date": "Справочно:", "note": "92.5"}]
    elif kind == "bool_flag":
        df["promo"] = False
        tail = [{"promo": False}]
    elif kind == "region_code":
        df["region_code"] = 77
        tail = [{"region_code": 77}]
    else:
        df["comment"] = ""
        tail = [{"comment": "Источник: Nielsen"}, {"comment": "2023"}]
    out = _append_rows(df, tail)
    assert find_undated_rows(out, "date", VALUE_COLS) == []
    p = _save(out, tmp_path)
    assert _issues(_validate(p), "undated_row_in_data") == []
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["n_obs"] == N_HIST


def test_zero_model_values_do_not_count_as_numbers():
    """Нули в колонках модели – не «числа»; одно ненулевое – уже строка."""
    df = _frame()
    zero = _append_rows(df, [{"tv_spend": 0.0, "digital_spend": 0.0}])
    assert find_undated_rows(zero, "date", VALUE_COLS) == []
    one = _append_rows(df, [{"tv_spend": 0.0, "digital_spend": 5.0}])
    assert [r["file_row"] for r in find_undated_rows(one, "date", VALUE_COLS)] == [N_HIST + 2]


def test_average_row_found_despite_long_formula_drag(tmp_path):
    """H-3 (probe6): строка средних + формула протянута на 40 строк нулями.
    До правки нули попадали в знаменатель предохранителя, правило молчало, и
    строка средних обучалась 37-м периодом."""
    df = _frame()
    df["cpp"] = df["tv_spend"] / 10
    out = _append_rows(df, [{**_means(df), "cpp": df["cpp"].mean()}] + [{"cpp": 0.0}] * 40)
    assert find_undated_rows(out, "date", VALUE_COLS) == [{"index": N_HIST, "file_row": N_HIST + 2}]
    p = _save(out, tmp_path)
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[N_HIST + 2]]
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


@pytest.mark.parametrize("kind", ["ddmm_weekly_10", "ddmm_daily_16", "iso_plus_one_ddmm"])
def test_day_first_dates_are_recognized(tmp_path, kind):
    """M-2 (probe2/probe3/probe4 G1, G2, A3): pandas выводит формат по первой
    ячейке («04.01.2023» – месяц впереди), и дни > 12 ниже не разбирались;
    «13.03.2023» среди дат 2023-03-13 – тоже. Ложный отказ на файле, который
    OLS обучал."""
    if kind == "ddmm_weekly_10":
        dates = [d.strftime("%d.%m.%Y") for d in pd.date_range("2023-01-04", periods=10, freq="7D")]
    elif kind == "ddmm_daily_16":
        dates = [d.strftime("%d.%m.%Y") for d in pd.date_range("2023-01-01", periods=16, freq="D")]
    else:
        dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2023-01-02", periods=N_HIST, freq="7D")]
        dates[10] = "13.03.2023"
    df = _frame(n_hist=len(dates))
    df["date"] = dates
    assert pd.to_datetime(df["date"], errors="coerce").isna().any()
    assert find_undated_rows(df, "date", VALUE_COLS) == []
    p = tmp_path / "data.csv"
    df.to_csv(p, index=False)
    assert _issues(_validate(p), "undated_row_in_data") == []
    assert _ols(p, tmp_path).get("error_code") != "UNDATED_ROW_IN_DATA"


def test_month_name_date_still_refused_with_honest_text(tmp_path):
    """M-1: «13 марта 2023» не разбирается ни одним способом – отказ, но текст
    говорит «не заполнена или не распознана» и подсказывает вид даты."""
    df = _frame()
    df.loc[10, "date"] = "13 марта 2023"
    assert [r["file_row"] for r in find_undated_rows(df, "date", VALUE_COLS)] == [12]
    msg = _issues(_validate(_save(df, tmp_path)), "undated_row_in_data")[0]["message"]
    assert msg.startswith("В строке 12 файла не заполнена или не распознана дата")
    assert "Заполните дату в этой строке – так же, как в строке 11, –" in msg


def test_zero_row_after_plan_is_not_refused(tmp_path):
    """M-5 (probe4 F5): строка нулей без даты после медиаплана. Ненулевых
    чисел в ней нет – правило её не ловит, как было до в-1: проверка считает
    её седьмым периодом плана без даты, обучение идёт на 36 периодах истории
    (KPI пуст – строку отсекает фильтр). Долг – см. FIX02_s56.md."""
    df = _frame(n_plan=6)
    out = _append_rows(df, [{"tv_spend": 0.0, "digital_spend": 0.0}])
    assert find_undated_rows(out, "date", VALUE_COLS) == []
    p = _save(out, tmp_path)
    res = _validate(p)
    assert _issues(res, "undated_row_in_data") == []
    assert _issues(res, "total_row_in_data") == []
    plan = res["media_plan_detected"]
    assert plan["n_future_periods"] == 7
    assert plan["future_dates"][-1] is None
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["n_obs"] == N_HIST


def test_undated_detector_does_not_call_total_detector(monkeypatch):
    """M-6: итоговые строки передаются снаружи (`exclude_index`); сбой
    детектора итогов больше не выключает правило строк без даты."""
    from engines import planning

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(planning, "find_trailing_total_rows", boom)
    df = _frame()
    out = _insert(df, len(df), _means(df))
    assert find_undated_rows(out, "date", VALUE_COLS) == [{"index": N_HIST, "file_row": N_HIST + 2}]
    assert find_undated_rows(out, "date", VALUE_COLS, exclude_index=[N_HIST]) == []


def test_validation_reports_undated_row_when_total_detector_fails(tmp_path, monkeypatch):
    """M-6 (probe6): детектор итогов падает – строка средних всё равно
    отказ проверки данных, а не «warning» без единой проблемы."""
    from engines import planning

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    df = _frame()
    p = _save(_insert(df, len(df), _means(df)), tmp_path)
    monkeypatch.setattr(planning, "find_trailing_total_rows", boom)
    res = _validate(p)
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[N_HIST + 2]]
    assert res["status"] == "error"


def test_guard_counts_only_rows_with_numbers():
    """L-2 (мутация М-А): в предохранителе участвуют только строки с числами.
    Даты, проставленные на 60 периодов вперёд без данных, не «добирают»
    большинство: из 10 строк с числами дата у 4 – это формат, правило молчит."""
    df = _frame(n_hist=10)
    df.loc[4:, "date"] = None
    future = pd.DataFrame({"date": list(pd.date_range("2023-01-01", periods=60, freq="MS"))})
    out = pd.concat([df, future], ignore_index=True)
    assert find_undated_rows(out, "date", VALUE_COLS) == []


def test_validator_value_columns_follow_detected_roles():
    """Колонки модели в проверке – роли, которые проверка отдаёт; без ролей –
    все числовые, кроме даты."""
    from engines.validator import _detected_date_and_value_columns
    df = _frame()
    df.insert(0, "№", range(1, len(df) + 1))
    assert _detected_date_and_value_columns(df) == ("date", VALUE_COLS, 1)
    bare = pd.DataFrame({"date": ["2023-01-01", "2023-02-01"], "x1": [1.0, 2.0],
                         "x2": ["a", "b"]})
    assert _detected_date_and_value_columns(bare) == ("date", ["x1"], 1)


# ─── Приёмка fix02: числовая колонка с ролью «дата» – не календарь ───────────


def test_numeric_date_column_like_macro_monthly_is_not_refused(tmp_path):
    """macro_monthly.csv: «период» строками + числовые «…_конец_месяца» (роль
    «дата» по имени). detected.date – последняя, числовая; `to_datetime`
    берёт число за дату от 1970-го, и пустая последняя ячейка давала ложный
    отказ «строка 38». Числовая колонка календарём не считается."""
    from engines.ols_modeler import train_ols
    df = _frame()
    df["date"] = [d.strftime("%Y-%m") for d in pd.to_datetime(df["date"])]
    df = df.rename(columns={"date": "период"})
    rng = np.random.RandomState(7)
    df["курс_доллара_уровень_конец_месяца"] = rng.uniform(60, 100, len(df))
    df["индекс_потребительских_цен_уровень_конец_месяца"] = rng.uniform(100, 110, len(df))
    df.loc[len(df) - 1, "индекс_потребительских_цен_уровень_конец_месяца"] = np.nan
    p = tmp_path / "macro.csv"
    df.to_csv(p, index=False, sep=";")
    res = _validate(p)
    det = res["detected"]["date"]
    assert det == "индекс_потребительских_цен_уровень_конец_месяца"
    assert _issues(res, "undated_row_in_data") == []
    assert res["file"]["rows"] == N_HIST
    cfg = {**_train_cfg(p), "date_column": det}
    tr = train_ols(cfg, str(tmp_path / "proj"))
    # CSVPROBE s56: прежняя проверка «не UNDATED» маскировала падение
    # обучения на CSV с «;» («KPI column not found») – теперь успех целиком.
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["n_obs"] == N_HIST


@pytest.mark.parametrize("kind", ["xlsx_datetime64", "csv_iso_strings", "csv_year_month"])
def test_calendar_date_columns_still_checked(tmp_path, kind):
    """Настоящие даты правило по-прежнему проверяет: из xlsx приходят
    datetime64, из CSV – строки (в т.ч. «2024-01»)."""
    df = _frame()
    if kind == "csv_year_month":
        df["date"] = [d.strftime("%Y-%m") for d in pd.to_datetime(df["date"])]
    elif kind == "csv_iso_strings":
        df["date"] = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(df["date"])]
    df.loc[12, "date"] = None
    if kind == "xlsx_datetime64":
        p = _save(df, tmp_path)
        back = pd.read_excel(p)
        assert pd.api.types.is_datetime64_any_dtype(back["date"])
    else:
        p = tmp_path / "data.csv"
        df.to_csv(p, index=False)
        back = pd.read_csv(p)
        # pandas 3: строковый тип str, в pandas 2 – object; оба не числовые.
        assert not pd.api.types.is_numeric_dtype(back["date"])
    assert [r["file_row"] for r in find_undated_rows(back, "date", VALUE_COLS)] == [14]
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[14]]


def test_excel_serial_numbers_as_date_are_silent_by_design(tmp_path):
    """Осознанный компромисс: дата целыми серийными номерами Excel во всей
    колонке – числовой тип, правило молчит (пустая ячейка отказа не даёт)."""
    df = _frame()
    df["date"] = [(d - pd.Timestamp("1899-12-30")).days for d in pd.to_datetime(df["date"])]
    df["date"] = df["date"].astype(float)
    df.loc[12, "date"] = np.nan
    p = _save(df, tmp_path)
    assert pd.api.types.is_numeric_dtype(pd.read_excel(p)["date"])
    assert find_undated_rows(pd.read_excel(p), "date", VALUE_COLS) == []
    assert _issues(_validate(p), "undated_row_in_data") == []


def test_bool_date_column_is_not_a_calendar():
    df = _frame()
    df["date"] = True
    df.loc[3, "date"] = False
    df["date"] = df["date"].astype(bool)
    assert find_undated_rows(df, "date", VALUE_COLS) == []


def test_calendar_column_chosen_over_numeric_detected_date():
    """Вариант (б) приёмки fix02: detected.date числовая – правило берёт
    первую календарную колонку с ролью «дата» («период» в macro_monthly)."""
    from engines.planning import _calendar_date_column
    df = _frame()
    df["date"] = [d.strftime("%Y-%m") for d in pd.to_datetime(df["date"])]
    df = df.rename(columns={"date": "период"})
    df["индекс_потребительских_цен_уровень_конец_месяца"] = np.linspace(100, 110, len(df))
    assert _calendar_date_column(df, "индекс_потребительских_цен_уровень_конец_месяца") == "период"
    assert _calendar_date_column(df, "период") == "период"
    # «период» стёрт в строке – отказ по «периоду», хотя preferred числовая.
    df.loc[12, "период"] = None
    assert [r["file_row"] for r in find_undated_rows(
        df, "индекс_потребительских_цен_уровень_конец_месяца", VALUE_COLS)] == [14]


def test_all_date_role_columns_numeric_is_silent(tmp_path):
    """Все колонки роли «дата» числовые (номер недели, номер месяца) –
    календаря нет, правило молчит и в проверке, и в обучении."""
    df = _frame().rename(columns={"date": "Неделя"})
    df["Неделя"] = range(1, len(df) + 1)
    df["Месяц"] = [(i % 12) + 1 for i in range(len(df))]
    df = df[["Неделя", "Месяц"] + VALUE_COLS]
    out = pd.concat([df, pd.DataFrame([{"Неделя": None, "Месяц": None, **_means(df)}])],
                    ignore_index=True)
    p = _save(out, tmp_path)
    # Как прочитает программа: из xlsx номера с пустой ячейкой – float64.
    back = pd.read_excel(p)
    assert pd.api.types.is_numeric_dtype(back["Неделя"])
    assert find_undated_rows(back, "Неделя", VALUE_COLS) == []
    res = _validate(p)
    assert _issues(res, "undated_row_in_data") == []
    from engines.ols_modeler import train_ols
    tr = train_ols({**_train_cfg(p), "date_column": res["detected"]["date"]}, str(tmp_path / "proj"))
    assert tr.get("error_code") != "UNDATED_ROW_IN_DATA"


# ─── Повторный аудит s56 (AUDIT02_s56.txt), fix04 ────────────────────────────


def _monthly_csv_with_year_subtotals(tmp_path: Path, fmt: str) -> Path:
    """S8/S10 аудита: помесячно 2022–2023 датами-строками, после декабря
    каждого года – подытог с меткой «2022» / «2023» и суммами."""
    df = _frame(n_hist=24)
    stamps = pd.to_datetime(df["date"])
    df["date"] = [d.strftime("%Y-%m-%d" if fmt == "iso" else "%d.%m.%Y") for d in stamps]
    out = _insert(df, 12, {"date": "2022", **{c: df[c].iloc[:12].sum() for c in VALUE_COLS}})
    out = _append_rows(out, [{"date": "2023", **{c: df[c].iloc[12:].sum() for c in VALUE_COLS}}])
    p = tmp_path / "data.csv"
    out.to_csv(p, index=False)
    return p


@pytest.mark.parametrize("fmt", ["iso", "ddmm"])
def test_year_subtotal_label_is_not_a_date(tmp_path, fmt):
    """A2-H1: второй разбор (`format="mixed"`) брал голый год «2023» за дату –
    подытоги года снова обучались лишними периодами (OLS n_obs 26 вместо
    отказа). Теперь – отказ в проверке и в обоих обучениях."""
    p = _monthly_csv_with_year_subtotals(tmp_path, fmt)
    res = _validate(p)
    assert res["status"] == "error"
    assert [i["rows"] for i in _issues(res, "undated_row_in_data")] == [[14, 27]]
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
    assert _bayes(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


# Метки подытогов из прогона p_lbl.py аудита: ни одна не дата.
_NOT_DATE_LABELS = [
    "2023", "2023 г.", "2023 год", "Итого 2023", "итог 2023", "Всего за 2023", "12.2023",
    "2023-12", "1 кв", "Q4", "Dec", "Декабрь", "Avg", "Mean", "Sum", "1", "12", "31", "52",
    "100", "2023.0", "Jan 2023", "FY2023", "H1 2023", "Н1 2023", "1-е полугодие", "TOTAL",
    "AVG 2023", "2023 total", "Dec 2023",
]


@pytest.mark.parametrize("base", [
    ["2022-01-01", "2022-02-01", "2022-03-01"],
    ["01.01.2022", "01.02.2022", "01.03.2022"],
    [pd.Timestamp("2022-01-01"), pd.Timestamp("2022-02-01"), pd.Timestamp("2022-03-01")],
], ids=["iso", "ddmm", "xlsx_timestamps"])
@pytest.mark.parametrize("label", _NOT_DATE_LABELS)
def test_subtotal_labels_table(base, label):
    """A2-H1 таблично: среди полных дат метка подытога – не дата ни в первом,
    ни во втором разборе."""
    from engines.planning import _dates_recognized
    s = pd.Series(base + [label], dtype=object)
    assert _dates_recognized(s).tolist() == [True, True, True, False]


@pytest.mark.parametrize("cell", [
    "13.03.2023", "2023-03-13", "13/03/2023", "02.01.23", "2023-01-16 10:30",
    "2023-01-16T10:30:00", " 13.03.2023 ",
])
def test_full_dates_still_recognized_among_iso(cell):
    """Полные даты в любом из видов по-прежнему дата (M-2 не сломан)."""
    from engines.planning import _dates_recognized
    s = pd.Series(["2023-01-02", "2023-01-09", "2023-01-16", cell], dtype=object)
    assert _dates_recognized(s).all()


def test_partial_date_columns_still_calendar():
    """Колонка из одних неполных дат («2024-01», «Jan-23», «2023-Q1») не
    ограничивается полными датами – это календарь, как и прежде."""
    from engines.planning import _is_calendar
    for vals in (["2024-01", "2024-02", "2024-03"], ["Jan-23", "Feb-23", "Mar-23"],
                 ["2023-Q1", "2023-Q2", "2023-Q3"]):
        assert _is_calendar(pd.Series(vals, dtype=object)), vals


@pytest.mark.parametrize("label", ["2022", 2022], ids=["text", "number"])
def test_xlsx_dates_with_year_label_refused(tmp_path, label):
    """S9 аудита: xlsx с настоящими датами и подытогом «2022» (текстом или
    числом) – первый разбор смешанной колонки брал его за дату, строка
    обучалась. Теперь отказ."""
    df = _frame(n_hist=24)
    out = _insert(df, 12, {"date": label, **{c: df[c].iloc[:12].sum() for c in VALUE_COLS}})
    p = _save(out, tmp_path)
    back = pd.read_excel(p)
    assert not pd.api.types.is_datetime64_any_dtype(back["date"])
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[14]]
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


def _norole_frame(n: int = 52) -> pd.DataFrame:
    """p_norole.py аудита: ни одна колонка модели не распознаётся по имени."""
    rng = np.random.RandomState(9)
    return pd.DataFrame({
        "№": range(1, n + 1),
        "Дата": list(pd.date_range("2023-01-02", periods=n, freq="7D")),
        "Упаковки": rng.uniform(1e4, 2e4, n),
        "ТВ": rng.uniform(1e5, 5e5, n),
        "Интернет": rng.uniform(1e4, 5e4, n),
    }).astype({"Дата": object})


def _norole_cfg(p: Path) -> dict:
    return {"data_file": str(p), "kpi_column": "Упаковки", "media_columns": ["ТВ", "Интернет"],
            "control_columns": [], "date_column": "Дата", "adstock_config": {}}


@pytest.mark.parametrize("numbering", ["№", "№ п/п", "N", "Строка"])
def test_no_roles_numbering_below_data_not_refused(tmp_path, numbering):
    """A2-M1: без распознанных ролей проверка берёт все числовые колонки;
    «№», протянутый на 3 строки ниже данных, давал отказ [54, 55, 56], хотя
    обучение по конфигу проходило. «Строка» – нумерация без имени-признака
    (целые с шагом 1)."""
    from engines.ols_modeler import train_ols
    df = _norole_frame().rename(columns={"№": numbering})
    out = pd.concat([df, pd.DataFrame({numbering: [53, 54, 55]})], ignore_index=True)
    p = _save(out, tmp_path)
    res = _validate(p)
    assert not res["detected"]["kpi"]
    assert _issues(res, "undated_row_in_data") == []
    tr = train_ols(_norole_cfg(p), str(tmp_path / "proj"))
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["n_obs"] == 52


def test_no_roles_average_row_still_refused(tmp_path):
    """A2-M1: тот же файл без ролей + строка средних по «Упаковки/ТВ» без
    даты – отказ в проверке (числа в двух колонках запасного набора) и в
    обучении."""
    from engines.ols_modeler import train_ols
    df = _norole_frame()
    avg = {"Упаковки": df["Упаковки"].mean(), "ТВ": df["ТВ"].mean()}
    out = pd.concat([df, pd.DataFrame({"№": [53, 54, 55]}), pd.DataFrame([avg])],
                    ignore_index=True)
    p = _save(out, tmp_path)
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[57]]
    assert train_ols(_norole_cfg(p), str(tmp_path / "proj"))["error_code"] == "UNDATED_ROW_IN_DATA"


def test_no_roles_single_number_in_row_not_refused():
    """A2-M1: без ролей одно число в строке (протянутая формула, сноска с
    цифрой) – не период; с ролями одного числа по-прежнему достаточно."""
    from engines.validator import _detected_date_and_value_columns
    df = _norole_frame()
    out = pd.concat([df, pd.DataFrame([{"ТВ": 5.0}])], ignore_index=True)
    date_col, cols, min_numbers = _detected_date_and_value_columns(out)
    assert (date_col, cols, min_numbers) == ("Дата", ["Упаковки", "ТВ", "Интернет"], 2)
    assert find_undated_rows(out, date_col, cols, min_numbers=min_numbers) == []
    assert find_undated_rows(out, date_col, cols) == [{"index": 52, "file_row": 54}]


def _week_number_total_frame() -> pd.DataFrame:
    """T3 из p_two.py: [Дата, Неделя-номер] + «Итого» с суммами по всем
    числовым колонкам, включая «Неделю»."""
    rng = np.random.RandomState(5)
    n = 40
    c = pd.DataFrame({
        "Дата": list(pd.date_range("2023-01-02", periods=n, freq="7D")),
        "Неделя": list(range(1, n + 1)),
        "sales": rng.uniform(1e3, 2e3, n),
        "tv_spend": rng.uniform(100, 300, n),
        "digital_spend": rng.uniform(50, 150, n),
    })
    tot = {"Дата": "Итого", **{k: c[k].sum() for k in ["Неделя", "sales", "tv_spend", "digital_spend"]}}
    return pd.concat([c.astype({"Дата": object}), pd.DataFrame([tot])], ignore_index=True)


def test_total_row_with_numeric_detected_date_keeps_total_text(tmp_path):
    """L-2 (мутация M7): detected.date – «Неделя» с номерами; детектор итогов
    судил по ней, и «Итого» получало общий текст про дату. Теперь – та же
    календарная колонка, что у правила строк без даты: свой код и текст в
    проверке, отказ итога в обоих обучениях."""
    p = _save(_week_number_total_frame(), tmp_path)
    res = _validate(p)
    assert res["detected"]["date"] == "Неделя"
    totals = _issues(res, "total_row_in_data")
    assert [i["rows"] for i in totals] == [[42]]
    assert "похожа на итоговую" in totals[0]["message"]
    assert _issues(res, "undated_row_in_data") == []
    cfg = {"data_file": str(p), "kpi_column": "sales", "media_columns": ["tv_spend", "digital_spend"],
           "control_columns": [], "date_column": "Неделя", "adstock_config": {}}
    from engines.modeler import train_model
    from engines.ols_modeler import train_ols
    assert train_ols(cfg, str(tmp_path / "proj"))["error_code"] == "TOTAL_ROW_IN_DATA"
    assert train_model(cfg, str(tmp_path / "proj_b"))["error_code"] == "TOTAL_ROW_IN_DATA"


def test_nearest_dated_row_for_text_sample():
    """L-5: образец – ближайшая строка с датой к первой строке без даты;
    первая строка данных без даты – образец ниже; дат нет – образца нет."""
    from engines.planning import nearest_dated_row
    df = _frame()
    first = _insert(df, 0, _means(df))
    rows = find_undated_rows(first, "date", VALUE_COLS)
    assert rows == [{"index": 0, "file_row": 2}]
    assert nearest_dated_row(first, "date", rows) == 3
    assert "так же, как в строке 3," in undated_rows_message(rows, nearest_dated_row(first, "date", rows))
    tail = _insert(df, len(df), _means(df))
    assert nearest_dated_row(tail, "date", find_undated_rows(tail, "date", VALUE_COLS)) == N_HIST + 1
    no_dates = df.assign(date=None)
    assert nearest_dated_row(no_dates, "date", [{"index": 0, "file_row": 2}]) is None


def test_text_week_column_with_one_date_is_not_calendar():
    """L-4 (мутация M1): текстовая «Неделя N» с одной ячейкой-датой – не
    календарь (большинство, а не «хотя бы одна»). Иначе правило выбрало бы
    её вместо настоящей даты и промолчало на строке средних."""
    from engines.planning import _calendar_date_column, _is_calendar
    df = _frame()
    df.insert(0, "Неделя", [f"Неделя {i + 1}" for i in range(len(df))])
    df.loc[5, "Неделя"] = "2022-06-01"
    assert not _is_calendar(df["Неделя"])
    assert _calendar_date_column(df, "Неделя") == "date"
    out = _insert(df, len(df), _means(df))
    assert find_undated_rows(out, "Неделя", VALUE_COLS) == [{"index": N_HIST, "file_row": N_HIST + 2}]


def test_first_calendar_column_chosen_when_preferred_not_calendar():
    """L-4 (мутация M2): две календарные колонки, preferred – номер недели:
    правило берёт ПЕРВУЮ календарную («Дата начала»), как обещано."""
    from engines.planning import _calendar_date_column
    df = _frame().rename(columns={"date": "Дата начала"})
    ends = [d + pd.Timedelta(days=6) for d in pd.to_datetime(df["Дата начала"])]
    df.insert(1, "Дата окончания", pd.Series(ends, dtype=object))
    df.insert(2, "Неделя", range(1, len(df) + 1))
    assert _calendar_date_column(df, "Неделя") == "Дата начала"
    df.loc[10, "Дата начала"] = None
    assert [r["file_row"] for r in find_undated_rows(df, "Неделя", VALUE_COLS)] == [12]


def test_number_only_in_control_column_refused_in_training(tmp_path):
    """L-4 (мутации M5/M6): строка без даты с числом только в контроле
    (price_index) – отказ в проверке и в обоих обучениях: контроли входят в
    колонки модели."""
    df = _frame()
    out = _insert(df, len(df), {"price_index": 1.02})
    p = _save(out, tmp_path)
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[N_HIST + 2]]
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
    assert _bayes(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"


def test_numbering_column_detection():
    """A2-M1: нумерация – по имени («№», «№ п/п», «N») или не меньше 5 целых
    с шагом ровно 1 по ВСЕМ непустым строкам (с протяжкой ниже данных);
    прочие числовые колонки – нет. Короткий отрезок подряд идущих целых
    (две-четыре строки) нумерацией не считается."""
    from engines.validator import _detected_date_and_value_columns, _is_numbering_column
    step = pd.Series([1, 2, 3, 4, 5, 6])
    assert _is_numbering_column("Строка", step)
    assert _is_numbering_column("Строка", pd.Series([7, None, 8, 9, 10, 11]))
    assert not _is_numbering_column("Строка", pd.Series([1, 2]))
    assert not _is_numbering_column("Строка", pd.Series([1, 2, 3, 4]))
    assert not _is_numbering_column("ТВ", pd.Series([3, 4, 5, 6, 7, 9]))
    assert not _is_numbering_column("ТВ", pd.Series([5, 3, 4, 5, 6, 7, 8]))
    assert _is_numbering_column("№ п/п", pd.Series([10.5, 3.0]))
    assert not _is_numbering_column("ТВ", pd.Series([1, 2, 4, 5]))
    assert not _is_numbering_column("ТВ", pd.Series([1.5, 2.5, 3.5]))
    assert not _is_numbering_column("ТВ", pd.Series([True, False]))
    df = _norole_frame().rename(columns={"№": "Строка"})
    out = pd.concat([df, pd.DataFrame({"Строка": [53, 54, 55]})], ignore_index=True)
    assert _detected_date_and_value_columns(out) == ("Дата", ["Упаковки", "ТВ", "Интернет"], 2)


@pytest.mark.parametrize("channel", ["tv_spend", "price_index"])
def test_consecutive_integer_channel_untouched_when_roles_known(tmp_path, channel):
    """A2-M1: детектор нумерации работает только в запасном ходе. При
    распознанных ролях канал или контроль, чьи значения – целые подряд
    (1, 2, 3 … в каждой строке), остаётся колонкой модели, и строка без
    даты с числом только в нём – отказ, как и прежде."""
    from engines.validator import _detected_date_and_value_columns, _is_numbering_column
    df = _frame()
    df[channel] = np.arange(1, len(df) + 1, dtype=float)
    assert _is_numbering_column(channel, df[channel])
    assert _detected_date_and_value_columns(df) == ("date", VALUE_COLS, 1)
    out = _insert(df, len(df), {channel: 5.0})
    p = _save(out, tmp_path)
    assert [i["rows"] for i in _issues(_validate(p), "undated_row_in_data")] == [[N_HIST + 2]]
    assert _ols(p, tmp_path)["error_code"] == "UNDATED_ROW_IN_DATA"
