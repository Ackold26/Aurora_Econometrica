"""s56 fix05: находки внешнего аудита AUDIT03_s56.txt.

H-1 – дата, прочитанная как число («01.2022» из CSV русского Excel – 1.2022,
     ГГГГММ из xlsx): проверка отвечала «ГОТОВ», OLS и байес обучались на
     датах 1970-01-01. Теперь – отказ с понятным текстом.
M-1 – колонка с точкой (дата «01.2022», одна колонка «10.5») выключала
     десятичную запятую всему файлу «;».
M-2 – табуляция + «1,234» без дробей читалась тихо в 1000 раз меньше.
L-1 – UTF-16 (Excel «Юникод-текст») не читался.
L-2 – текст в числовой колонке модели ронял обучение сырым ValueError.
L-3 – «16 October 2023» среди дат xlsx стало «строкой без даты».
L-4 – тесты на выжившие мутации аудитора: N3, N16, N11, N12, A7.
Попутно – server.py: `pd` не определён в /project/save_kpi_settings.

s56 fix06 – повторный аудит (ч.4 AUDIT03):
M-3 – подсказка про календарную колонку велела «выбрать её на шаге
     настройки», чего интерфейс не умеет; текст – под кнопку «Сбросить шаг»
     (проверяется в тестах H-1 и test_undated_row_s56).
L-5 – «;» + «1,234» без дробей + колонка с точкой читались тихо как 1.234.
L-7 – годы date_stats по дате-числу (1970) не покрыты тестом.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.data_io import read_data_file  # noqa: E402

N = 36
MEDIA = ["tv_spend", "digital_spend"]
CONTROL = ["price_index"]


def _frame() -> pd.DataFrame:
    """Помесячно 3 года: дата объектом Timestamp, числа с дробями."""
    rng = np.random.RandomState(5)
    return pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=N, freq="MS"),
        "sales": np.round(rng.uniform(1000, 2000, N), 1),
        "tv_spend": np.round(rng.uniform(100, 300, N), 1),
        "digital_spend": np.round(rng.uniform(50, 150, N), 1),
        "price_index": np.round(rng.uniform(0.9, 1.1, N), 3),
    })


def _cfg(p: Path) -> dict:
    return {"data_file": str(p), "kpi_column": "sales", "media_columns": list(MEDIA),
            "control_columns": list(CONTROL), "date_column": "date", "adstock_config": {}}


def _ru(v: float) -> str:
    """Число как в русском Excel: десятичная запятая."""
    return repr(float(v)).replace(".", ",").removesuffix(",0")


def _ru_csv(df: pd.DataFrame, p: Path, date_fmt: str, sep: str = ";",
            encoding: str = "cp1251", point_cols: tuple = ()) -> Path:
    """CSV русского Excel: даты в `date_fmt`, числа с запятой (колонки
    `point_cols` – с точкой)."""
    lines = [sep.join(df.columns)]
    for _, r in df.iterrows():
        cells = [r["date"].strftime(date_fmt)]
        for c in df.columns[1:]:
            cells.append(repr(float(r[c])) if c in point_cols else _ru(r[c]))
        lines.append(sep.join(cells))
    p.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return p


def _validate(p: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(p))


def _issues(res: dict, kind: str) -> list[dict]:
    return [i for i in res.get("issues", []) if i.get("type") == kind]


def _ols(p: Path, tmp_path: Path, **over) -> dict:
    from engines.ols_modeler import train_ols
    return train_ols({**_cfg(p), **over}, str(tmp_path / "proj_ols"))


def _bayes(p: Path, tmp_path: Path, **over) -> dict:
    """Байес отказывает до MCMC – вызов дешёвый."""
    from engines.modeler import train_model
    return train_model({**_cfg(p), **over}, str(tmp_path / "proj_bayes"))


def _reference_r2(tmp_path: Path) -> float:
    """r² OLS на том же кадре из xlsx – эталон для вариантов CSV."""
    p = tmp_path / "ref.xlsx"
    _frame().to_excel(p, index=False)
    res = _ols(p, tmp_path / "ref")
    assert res["status"] == "ok", res.get("message")
    return res["diagnostics"]["metrics"]["r_squared"]


# ─── H-1: дата, прочитанная как число ────────────────────────────────────────


def _date_refusal(example: str) -> str:
    return (f"Дата в колонке «date» прочитана как число (например {example}). "
            f"Сохраните даты в виде ДД.ММ.ГГГГ и загрузите файл заново.")


def _h1_file(tmp_path: Path, kind: str) -> tuple[Path, str]:
    """Файл с датой-числом и ожидаемый пример в тексте отказа."""
    df = _frame()
    if kind == "semicolon_mmyyyy_cp1251":
        # Сценарий аудита (v9): CSV «;» cp1251 из русского Excel, «ММ.ГГГГ».
        return _ru_csv(df, tmp_path / "v9.csv", "%m.%Y"), "01.2022"
    if kind == "semicolon_yyyymm_dot":
        return _ru_csv(df, tmp_path / "c16.csv", "%Y.%m"), "2022.01"
    if kind == "comma_mmyyyy_utf8":
        # Путь «,» utf-8 – ровно pd.read_csv: колонка числовая 1.2022.
        out = df.copy()
        out["date"] = out["date"].dt.strftime("%m.%Y")
        p = tmp_path / "v9d.csv"
        out.to_csv(p, index=False)
        return p, "1.2022"
    if kind == "xlsx_yyyymm_int":
        out = df.copy()
        out["date"] = out["date"].dt.strftime("%Y%m").astype(int)
        p = tmp_path / "v9e.xlsx"
        out.to_excel(p, index=False)
        return p, "202201"
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["semicolon_mmyyyy_cp1251", "semicolon_yyyymm_dot",
                                  "comma_mmyyyy_utf8", "xlsx_yyyymm_int"])
def test_numeric_date_refused_by_validation_and_both_trainings(tmp_path, kind):
    p, example = _h1_file(tmp_path, kind)
    res = _validate(p)
    issues = _issues(res, "date_column_numeric")
    assert [(i["column"], i["severity"], i["message"]) for i in issues] == [
        ("date", "critical", _date_refusal(example))]
    assert res["status"] == "error"
    # Единственная критическая причина – дата: ни ложного «строки без даты»,
    # ни совета чинить десятичную запятую (M-1).
    assert [i["type"] for i in res["issues"] if i["severity"] == "critical"] == [
        "date_column_numeric"]
    # Совета «YYYY-MM-DD» рядом с отказом нет, частота по датам 1970 не считается.
    assert not [w for w in res.get("warnings", []) if w.get("type") == "date_parse"]
    assert res["detected"]["date_frequency"] == "unknown"
    for tr in (_ols(p, tmp_path), _bayes(p, tmp_path)):
        assert (tr["status"], tr["error_code"], tr["column"], tr["message"]) == (
            "error", "DATE_COLUMN_NUMERIC", "date", _date_refusal(example))


@pytest.mark.parametrize("order", [["Неделя", "date"], ["date", "Неделя"]],
                         ids=["week_first", "date_first"])
def test_week_number_next_to_real_dates(tmp_path, order):
    """Вариант Б ведущей: [Неделя-номер, Дата] в CSV русского Excel –
    detected.date – календарная колонка при любом порядке, проверка без H-1,
    обучение на настоящих датах. Старый конфиг с «Неделей» – отказ, и текст
    называет колонку с датами."""
    df = _frame()
    df["Неделя"] = range(1, N + 1)
    cell = {"date": lambda r: r["date"].strftime("%d.%m.%Y"), "Неделя": lambda r: str(r["Неделя"])}
    lines = [";".join(order + ["sales", *MEDIA, *CONTROL])] + [
        ";".join([cell[c](r) for c in order] + [_ru(r[c]) for c in ["sales", *MEDIA, *CONTROL]])
        for _, r in df.iterrows()]
    p = tmp_path / "week.csv"
    p.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1251"))
    res = _validate(p)
    assert res["detected"]["date"] == "date"
    assert _issues(res, "date_column_numeric") == []
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["actual_vs_predicted"]["dates"][0] == "2022-01-01"
    expected = ("Дата в колонке «Неделя» прочитана как число (например 1). В файле есть "
                "колонка с датами «date» – на шаге «Валидация» нажмите «Сбросить шаг»: "
                "программа заново проверит данные и сама возьмёт её колонкой даты. Затем "
                "снова подтвердите настройки шага и запустите обучение.")
    for tr in (_ols(p, tmp_path, date_column="Неделя"), _bayes(p, tmp_path, date_column="Неделя")):
        assert (tr["error_code"], tr["column"], tr["message"]) == (
            "DATE_COLUMN_NUMERIC", "Неделя", expected)


def test_mmyyyy_column_is_text_and_commas_still_decimal(tmp_path):
    """data_io: «01.2022» остаётся текстом, числа с запятой – числами (M-1:
    колонка с точкой больше не выключает запятую всему файлу)."""
    p, _ = _h1_file(tmp_path, "semicolon_mmyyyy_cp1251")
    df = read_data_file(p)
    assert df["date"].tolist()[:3] == ["01.2022", "02.2022", "03.2022"]
    ref = _frame()
    for c in ["sales", *MEDIA, *CONTROL]:
        assert df[c].tolist() == ref[c].tolist(), c


def test_number_like_values_that_are_not_dates_stay_numbers(tmp_path):
    """Колонка «1500.25» / «13.2022» – не дата-число (месяц вне 1–12): читается
    числом, как раньше; колонка с датами – текстом только целиком."""
    p = tmp_path / "data.csv"
    p.write_text("date;price;code;mixed\n"
                 "01.01.2024;1500.25;13.2022;01.2022\n"
                 "08.01.2024;1600.5;14.2022;5.5\n", encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["price"].tolist() == [1500.25, 1600.5]
    assert df["code"].tolist() == [13.2022, 14.2022]
    assert df["mixed"].tolist() == [1.2022, 5.5]


def test_real_dates_are_not_refused(tmp_path):
    """Настоящие даты – ДД.ММ.ГГГГ в CSV и объекты даты в xlsx – не отказ."""
    csv = _ru_csv(_frame(), tmp_path / "ok.csv", "%d.%m.%Y")
    xlsx = tmp_path / "ok.xlsx"
    _frame().to_excel(xlsx, index=False)
    for p in (csv, xlsx):
        assert _issues(_validate(p), "date_column_numeric") == []
        assert _ols(p, tmp_path)["status"] == "ok"


# ─── M-1: решение о десятичной запятой – по колонкам ─────────────────────────


def test_point_column_does_not_disable_commas_in_semicolon_file(tmp_path):
    """v8 аудита: одна колонка введена с точкой, прочие с запятой – числа
    верные, проверка без замечаний о формате, обучение как у xlsx."""
    p = _ru_csv(_frame(), tmp_path / "v8.csv", "%d.%m.%Y", point_cols=("price_index",))
    df = read_data_file(p)
    ref = _frame()
    for c in ["sales", *MEDIA, *CONTROL]:
        assert df[c].tolist() == ref[c].tolist(), c
    res = _validate(p)
    assert not [i for i in res["issues"] if i["type"].startswith("non_numeric")]
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["metrics"]["r_squared"] == pytest.approx(
        _reference_r2(tmp_path), rel=1e-12)


def test_integer_column_with_blank_cell_keeps_decimal_comma(tmp_path):
    """N16 аудита: целая колонка с пустой ячейкой (pandas даёт float) не
    выключает десятичную запятую соседним колонкам."""
    p = tmp_path / "n16.csv"
    p.write_text("date;sales;tv;radio\n01.01.2024;1234,5;100;5\n08.01.2024;1334,5;;6\n"
                 "15.01.2024;1434,5;120;7\n", encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["sales"].tolist() == [1234.5, 1334.5, 1434.5]
    assert df["tv"].tolist()[0] == 100.0 and pd.isna(df["tv"].iloc[1])


def test_english_thousands_still_protect_semicolon_file(tmp_path):
    """«1,234.56» в файле «;» – английский формат: запятые не десятичные."""
    p = tmp_path / "data.csv"
    p.write_text("date;sales;units\n2023-01-01;1,234.5;1,234\n2023-02-01;2,000.25;2,500\n",
                 encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["units"].tolist() == ["1,234", "2,500"]


# ─── M-2: табуляция и «1,234» без дробей ─────────────────────────────────────


@pytest.mark.parametrize("encoding,values,expected", [
    ("utf-8", ["1,234", "2,345"], ["1,234", "2,345"]),
    ("utf-8", ["999", "1,234"], ["999", "1,234"]),
    ("utf-8", ["1,5", "1,234"], [1.5, 1.234]),
    ("utf-8", ["1 234", "2 345"], [1234.0, 2345.0]),
    ("cp1251", ["1,234", "2,345"], [1.234, 2.345]),
], ids=["tab_thousands_only", "tab_mixed_int_and_thousands", "tab_sure_decimal",
        "tab_space_thousands", "tab_cp1251"])
def test_tab_comma_converted_only_when_surely_decimal(tmp_path, encoding, values, expected):
    """c12 аудита: «1,234» в TSV без единой однозначной дроби – не 1.234, а
    текст (проверка откажет громко); однозначная запятая или cp1251 – дробь."""
    # Кириллица в заголовке: иначе ASCII-файл декодируется как utf-8.
    p = tmp_path / "data.tsv"
    p.write_bytes(("Дата\tsales\n" + "".join(f"2024-01-0{i + 1}\t{v}\n" for i, v in enumerate(values)))
                  .encode(encoding))
    assert read_data_file(p)["sales"].tolist() == expected


def test_tab_thousands_refused_by_validation(tmp_path):
    # Проверка принимает только .csv/.xlsx – TSV клиент сохраняет как .csv.
    p = tmp_path / "c12.csv"
    df = _frame()
    lines = ["\t".join(df.columns)] + [
        "\t".join([r["date"].strftime("%Y-%m-%d"), f"{int(r['sales']) * 1000:,}",
                   *(repr(float(r[c])) for c in [*MEDIA, *CONTROL])])
        for _, r in df.iterrows()]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    res = _validate(p)
    assert [i["column"] for i in _issues(res, "non_numeric_format")] == ["sales"]
    assert _ols(p, tmp_path)["error_code"] == "NON_NUMERIC_COLUMN"


# ─── L-1: UTF-16 (Excel «Юникод-текст») ──────────────────────────────────────


@pytest.mark.parametrize("codec,bom", [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")],
                         ids=["le", "be"])
def test_utf16_unicode_text_reads_and_trains_like_xlsx(tmp_path, codec, bom):
    df = _frame()
    lines = ["\t".join(df.columns)] + [
        "\t".join([r["date"].strftime("%d.%m.%Y"), *(_ru(r[c]) for c in df.columns[1:])])
        for _, r in df.iterrows()]
    p = tmp_path / "v5.csv"
    p.write_bytes(bom + ("\r\n".join(lines) + "\r\n").encode(codec))
    got = read_data_file(p)
    assert list(got.columns) == list(df.columns)
    for c in ["sales", *MEDIA, *CONTROL]:
        assert got[c].tolist() == df[c].tolist(), c
    assert _validate(p)["status"] == "ok"
    tr = _ols(p, tmp_path)
    assert tr["status"] == "ok", tr.get("message")
    assert tr["diagnostics"]["metrics"]["r_squared"] == pytest.approx(
        _reference_r2(tmp_path), rel=1e-12)


# ─── L-2: текст в числовой колонке модели ────────────────────────────────────


def _text_cell_file(tmp_path: Path, column: str, cell: str) -> Path:
    df = _frame().astype({column: object})
    df.loc[[5, 17], column] = cell
    p = tmp_path / "text.csv"
    df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(p, index=False)
    return p


@pytest.mark.parametrize("column,cell", [("digital_spend", " - "), ("sales", "1 234 ₽"),
                                         ("price_index", "н/д")],
                         ids=["media_dash_zero", "kpi_currency", "control_text"])
def test_text_in_model_column_is_refusal_not_exception(tmp_path, column, cell):
    p = _text_cell_file(tmp_path, column, cell)
    for tr in (_ols(p, tmp_path), _bayes(p, tmp_path)):
        assert (tr["status"], tr["error_code"], tr["column"]) == (
            "error", "NON_NUMERIC_COLUMN", column)
        assert f"В колонке «{column}»" in tr["message"]
        assert f"(например: {cell.strip()})" in tr["message"]


def test_text_in_media_plan_tail_is_not_refused(tmp_path):
    """Строки хвоста с пустым KPI в обучение не идут – текст в них отказа не
    даёт: проверка стоит после отсева хвоста."""
    df = _frame()
    tail = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=3, freq="MS"),
                         "sales": [np.nan] * 3, "tv_spend": ["-", "-", "-"],
                         "digital_spend": [60.0, 70.0, 80.0], "price_index": [1.0, 1.0, 1.0]})
    out = pd.concat([df.astype({"tv_spend": object}), tail], ignore_index=True)
    p = tmp_path / "tail.xlsx"
    out.to_excel(p, index=False)
    for tr in (_ols(p, tmp_path),):
        assert tr.get("error_code") != "NON_NUMERIC_COLUMN", tr.get("message")
        assert tr["status"] == "ok", tr.get("message")


# ─── L-3: «16 October 2023» среди дат ────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["%d %B %Y", "%d %b %Y"], ids=["month_name", "month_abbr"])
def test_month_name_dates_among_dates_recognized(tmp_path, fmt):
    from engines.planning import _dates_recognized
    base = pd.date_range("2023-01-02", periods=30, freq="W-MON")
    ts_mix = pd.Series(list(base[:25]) + list(base[25:].strftime(fmt)), dtype=object)
    iso_mix = pd.Series(list(base[:20].strftime("%Y-%m-%d")) + list(base[20:].strftime(fmt)))
    assert int(_dates_recognized(ts_mix).sum()) == 30
    assert int(_dates_recognized(iso_mix).sum()) == 30
    # Через точку входа: xlsx с меньшинством текстовых дат – не «строка без даты».
    df = _frame()
    df["date"] = list(df["date"][:30]) + list(df["date"][30:].dt.strftime(fmt))
    df["date"] = df["date"].astype(object)
    p = tmp_path / "mix.xlsx"
    df.to_excel(p, index=False)
    assert _issues(_validate(p), "undated_row_in_data") == []


# ─── L-4: выжившие мутации аудитора ──────────────────────────────────────────


def test_separator_priority_semicolon_over_comma_when_fields_tie(tmp_path):
    """N3: заголовок «Дата;Продажи, руб;ТВ, GRP» и дроби с запятой дают по три
    поля и для «;», и для «,» – побеждает «;» (порядок «;» > таб > «,»)."""
    p = tmp_path / "c13.csv"
    p.write_bytes("Дата;Продажи, руб;ТВ, GRP\n01.01.2024;1234,5;100,2\n08.01.2024;1334,5;110,2\n"
                  .encode("cp1251"))
    df = read_data_file(p)
    assert list(df.columns) == ["Дата", "Продажи, руб", "ТВ, GRP"]
    assert df["Продажи, руб"].tolist() == [1234.5, 1334.5]


def test_row_map_mismatch_falls_back_to_position_and_logs(tmp_path, caplog):
    """N11: строка из пустых кавычек – pandas даёт строку таблицы, csv – пустую
    запись; карта не сходится → «позиция + 2» и запись в журнал."""
    p = tmp_path / "quotes.csv"
    p.write_text('date;sales;tv\n01.01.2024;1,5;10\n""\n08.01.2024;2,5;20\n15.01.2024;3,5;30\n',
                 encoding="utf-8", newline="")
    with caplog.at_level(logging.WARNING, logger="engines.data_io"):
        df, rows = read_data_file(p, keep_row_map=True)
    assert len(df) == 4
    assert rows == [2, 3, 4, 5]
    assert any("row map of quotes.csv not built" in r.getMessage() for r in caplog.records)


def test_causal_load_panel_reads_requested_sheet(tmp_path):
    """N12: sheet_name доходит до чтения – лист «B», а не первый."""
    from engines.causal._panel_data import load_panel
    p = tmp_path / "two.xlsx"
    with pd.ExcelWriter(p) as w:
        pd.DataFrame({"unit": ["a", "b"], "week": [1, 1], "kpi": [1.0, 2.0]}).to_excel(
            w, sheet_name="A", index=False)
        pd.DataFrame({"unit": ["x", "y", "z"], "week": [1, 1, 1], "kpi": [7.0, 8.0, 9.0]}).to_excel(
            w, sheet_name="B", index=False)
    df, meta, err = load_panel(str(p), unit_column="unit", time_column="week",
                               kpi_column="kpi", sheet_name="B")
    assert err is None
    assert df["unit"].tolist() == ["x", "y", "z"]
    df_first, _, _ = load_panel(str(p), unit_column="unit", time_column="week", kpi_column="kpi")
    assert df_first["unit"].tolist() == ["a", "b"]


def test_sample_row_is_nearest_to_first_undated_row(tmp_path):
    """A7: две строки без даты – первая строкой данных (ближайшая с датой –
    ниже, строка 3), последняя в конце (ближайшая – выше). Образец в отказе –
    от первой строки отказа."""
    df = _frame()
    means = {c: round(float(df[c].mean()), 1) for c in ["sales", *MEDIA, *CONTROL]}
    out = pd.concat([pd.DataFrame([{"date": None, **means}]), df.astype({"date": object}),
                     pd.DataFrame([{"date": None, **means}])], ignore_index=True)
    p = tmp_path / "a7.xlsx"
    out.to_excel(p, index=False)
    issues = _issues(_validate(p), "undated_row_in_data")
    assert [i["rows"] for i in issues] == [[2, N + 3]]
    assert "так же, как в строке 3," in issues[0]["message"]
    tr = _ols(p, tmp_path)
    assert tr["error_code"] == "UNDATED_ROW_IN_DATA"
    assert "так же, как в строке 3," in tr["message"]


# ─── Попутно: /project/save_kpi_settings ─────────────────────────────────────


def test_save_kpi_settings_succeeds(tmp_path, monkeypatch):
    """server.py: `pd` в обработчике не был импортирован – любое успешное
    сохранение падало NameError → 500 (AUDIT03 ч.2 п.5, ruff F821)."""
    from fastapi.testclient import TestClient
    from server import app
    monkeypatch.setenv("AURORA_PROJECTS_ROOT", str(tmp_path))
    proj = tmp_path / "p1"
    proj.mkdir()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/project/save_kpi_settings",
                    json={"project_dir": str(proj), "kpi_kind": "monetary"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    import json
    saved = json.loads((proj / "settings" / "v13_kpi.json").read_text(encoding="utf-8"))
    assert pd.Timestamp(saved["updated_at"]).year >= 2026


# ─── L-5 (fix06): «;», «1,234» и колонка с десятичной точкой ─────────────────


def _semicolon(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "l5.csv"
    p.write_text(body, encoding="utf-8", newline="")
    return p


def test_semicolon_thousands_next_to_point_column_stay_text(tmp_path):
    """p7/r1 аудита: в файле «;» есть колонка «12.5» – соглашения смешаны,
    «1,234» без единой однозначной дроби остаётся текстом, а не 1.234."""
    df = read_data_file(_semicolon(
        tmp_path, "date;sales;tv\n01.01.2024;1,234;12.5\n08.01.2024;2,345;13.5\n"))
    assert df["sales"].tolist() == ["1,234", "2,345"]
    assert df["tv"].tolist() == [12.5, 13.5]


@pytest.mark.parametrize("body,expected", [
    ("date;sales;tv\n01.01.2024;1,234;12\n08.01.2024;2,345;13\n", [1.234, 2.345]),
    ("date;sales;tv\n01.01.2024;1,234;12,5\n08.01.2024;2,345;13,5\n", [1.234, 2.345]),
    ("date;sales\n01.2024;1,234\n02.2024;2,345\n", [1.234, 2.345]),
    ("date;sales;note\n01.01.2024;1,234;12.5\n08.01.2024;2,345;н/д\n", [1.234, 2.345]),
    ("date;sales;tv\n01.01.2024;1,234;12.5\n08.01.2024;2,5;13.5\n", [1.234, 2.5]),
], ids=["integer_column", "no_point_column", "mmyyyy_date_is_not_point", "text_column",
        "sure_decimal"])
def test_semicolon_comma_decimal_without_mixed_conventions(tmp_path, body, expected):
    """Без колонки чисел с точкой – как раньше: русское «1,234» = 1.234.
    Целая колонка, дата «01.2024» и колонка с текстом («12.5», «н/д»)
    колонкой с точкой не считаются; при колонке с точкой однозначная дробь
    («2,5») переводит колонку."""
    assert read_data_file(_semicolon(tmp_path, body))["sales"].tolist() == expected


def test_semicolon_thousands_next_to_point_column_refused_loudly(tmp_path):
    """Проверка и обучение отказывают по колонке «1,234», а не обучаются на
    числах в 1000 раз меньше."""
    p = tmp_path / "r1.csv"
    df = _frame()
    lines = [";".join(df.columns)] + [
        ";".join([r["date"].strftime("%d.%m.%Y"), f"{int(r['sales']):,}",
                  *(repr(float(r[c])) for c in [*MEDIA, *CONTROL])])
        for _, r in df.iterrows()]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    res = _validate(p)
    assert [i["column"] for i in _issues(res, "non_numeric_format")] == ["sales"]
    assert _ols(p, tmp_path)["error_code"] == "NON_NUMERIC_COLUMN"


# ─── L-7 (fix06): годы date_stats по дате-числу ──────────────────────────────


def _date_info(res: dict) -> dict:
    return next(c for c in res["columns"] if c["name"] == res["detected"]["date"])


@pytest.mark.parametrize("kind", ["semicolon_mmyyyy_cp1251", "semicolon_yyyymm_dot",
                                  "comma_mmyyyy_utf8", "xlsx_yyyymm_int"])
def test_numeric_date_gives_no_year_stats(tmp_path, kind):
    """Дата-число дала бы в date_stats годы 1970 – они ушли бы в
    UnitCostsPanel (инфляция цен по годам). Годов по такой колонке нет."""
    p, _ = _h1_file(tmp_path, kind)
    res = _validate(p)
    assert res["detected"]["date"] == "date"
    assert "date_stats" not in _date_info(res)


def test_calendar_date_gives_year_stats(tmp_path):
    """Контроль: у настоящих дат годы есть – тест выше не пустой."""
    p = tmp_path / "ok.xlsx"
    _frame().to_excel(p, index=False)
    stats = _date_info(_validate(p))["date_stats"]
    assert stats["unique_years"] == [2022, 2023, 2024]
    assert (stats["min_date"], stats["max_date"]) == ("2022-01-01", "2024-12-01")
