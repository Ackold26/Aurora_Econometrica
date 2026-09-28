"""s56 fix04 (L-5 + L-1): единое чтение клиентского файла данных.

Зонд CSVPROBE_s56: проверка данных читала CSV «умно», обучение и остальные
движки – `pd.read_csv` по умолчанию. CSV русского Excel («;», десятичная
запятая, cp1251) проверку проходил или падал на ней, а обучение падало с
«KPI column not found». Номер строки в отказе для CSV с пустыми строками
уезжал вверх (AUDIT01 H3: 22 при реальной 24).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.data_io import read_data_file  # noqa: E402

N = 36


def _frame() -> pd.DataFrame:
    rng = np.random.RandomState(11)
    return pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in pd.date_range("2022-01-01", periods=N, freq="MS")],
        "sales": np.round(rng.uniform(1000, 2000, N), 2),
        "tv_spend": np.round(rng.uniform(100000, 300000, N), 2),
        "digital_spend": np.round(rng.uniform(50, 150, N), 3),
        "price_index": np.round(rng.uniform(0.9, 1.1, N), 4),
    })


def _cfg(p: Path) -> dict:
    return {"data_file": str(p), "kpi_column": "sales",
            "media_columns": ["tv_spend", "digital_spend"],
            "control_columns": ["price_index"], "date_column": "date",
            "adstock_config": {}}


def _ru(v: float, thousands: bool = False) -> str:
    """Число как в русском Excel: запятая, по желанию – неразрывный пробел
    между разрядами."""
    whole, _, frac = f"{v:.4f}".rstrip("0").rstrip(".").partition(".")
    if thousands:
        whole = f"{int(whole):,}".replace(",", " ")
    return whole + ("," + frac if frac else "")


def _ru_lines(df: pd.DataFrame, sep: str = ";", thousands: bool = False) -> list[str]:
    """Строки CSV русского Excel: заголовок + по строке на период."""
    lines = [sep.join(df.columns)]
    for _, r in df.iterrows():
        date = r["date"] if isinstance(r["date"], str) else ""
        lines.append(sep.join([date] + [_ru(r[c], thousands) for c in df.columns[1:]]))
    return lines


def _write_ru(df: pd.DataFrame, p: Path, sep: str = ";", encoding: str = "utf-8",
              thousands: bool = False) -> Path:
    p.write_bytes(("\r\n".join(_ru_lines(df, sep, thousands)) + "\r\n").encode(encoding))
    return p


# ─── Разделитель, десятичная запятая, кодировка ───────────────────────────────


@pytest.mark.parametrize("sep,encoding,thousands", [
    (";", "utf-8", False),
    (";", "utf-8-sig", False),
    (";", "cp1251", False),
    (";", "cp1251", True),
    ("\t", "utf-8", False),
    ("\t", "cp1251", True),
], ids=["semicolon_utf8", "semicolon_utf8sig", "semicolon_cp1251", "semicolon_cp1251_nbsp",
        "tab_utf8", "tab_cp1251_nbsp"])
def test_russian_excel_csv_reads_like_comma_csv(tmp_path, sep, encoding, thousands):
    df = _frame()
    comma = tmp_path / "comma.csv"
    df.to_csv(comma, index=False)
    ru = _write_ru(df, tmp_path / "ru.csv", sep, encoding, thousands)
    pd.testing.assert_frame_equal(read_data_file(ru), read_data_file(comma))


def test_comma_csv_is_read_exactly_like_pandas(tmp_path):
    """Обычный CSV – ровно `pd.read_csv`: таблица и её отпечаток не меняются
    у моделей, обученных до правки."""
    df = _frame()
    p = tmp_path / "data.csv"
    df.to_csv(p, index=False)
    pd.testing.assert_frame_equal(read_data_file(p), pd.read_csv(p))


def test_cyrillic_headers_cp1251(tmp_path):
    p = tmp_path / "data.csv"
    p.write_bytes("Дата;Продажи;ТВ\r\n01.01.2023;1 234,5;100\r\n08.01.2023;2 000,25;200\r\n"
                  .replace(" ", " ").encode("cp1251"))
    df = read_data_file(p)
    assert list(df.columns) == ["Дата", "Продажи", "ТВ"]
    assert df["Продажи"].tolist() == [1234.5, 2000.25]
    assert df["Дата"].tolist() == ["01.01.2023", "08.01.2023"]


def test_english_thousands_in_comma_csv_untouched(tmp_path):
    """В файле «,» запятая в кавычках – разделитель тысяч английского
    формата: колонку не превращаем в дробь."""
    p = tmp_path / "data.csv"
    p.write_text('date,sales\n2023-01-01,"1,234"\n2023-02-01,"2,500"\n', encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["sales"].tolist() == ["1,234", "2,500"]


def test_decimal_point_file_keeps_commas_as_text(tmp_path):
    """В файле «;» с числами через точку запятая – не десятичная: колонка
    «1,234.5» остаётся текстом, дробные через точку – числа."""
    p = tmp_path / "data.csv"
    p.write_text("date;sales;units;tv\n2023-01-01;1,234.5;1,234;10.5\n"
                 "2023-02-01;2,000.25;2,500;11.5\n", encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["tv"].tolist() == [10.5, 11.5]
    assert df["sales"].tolist() == ["1,234.5", "2,000.25"]
    # «1,234» при числах через точку – разделитель тысяч, не 1.234.
    assert df["units"].tolist() == ["1,234", "2,500"]


def test_text_cells_keep_column_as_text(tmp_path):
    """Колонка, где есть текст («н/д», «Итого», дата), в числа не
    превращается; колонка из чисел с запятой – превращается."""
    p = tmp_path / "data.csv"
    p.write_text("date;sales;note\n01.01.2023;1,5;н/д\nИтого;3,5;2,5\n", encoding="utf-8", newline="")
    df = read_data_file(p)
    assert df["date"].tolist() == ["01.01.2023", "Итого"]
    assert df["sales"].tolist() == [1.5, 3.5]
    assert df["note"].tolist() == ["н/д", "2,5"]


def test_single_column_file_stays_single_column(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("sales\n1\n2\n", encoding="utf-8", newline="")
    df = read_data_file(p)
    pd.testing.assert_frame_equal(df, pd.read_csv(p))


def test_xlsx_read_as_before(tmp_path):
    df = _frame()
    p = tmp_path / "data.xlsx"
    df.to_excel(p, index=False)
    got, rows = read_data_file(p, keep_row_map=True)
    pd.testing.assert_frame_equal(got, pd.read_excel(p))
    assert rows == [i + 2 for i in range(len(got))]


# ─── Карта строк: номер строки файла, как в Excel ────────────────────────────


def test_row_map_counts_blank_and_multiline_records(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text('\na;b\n1;2\n\n3;4\n   \n;\n5;6\n"x\ny";7\n', encoding="utf-8", newline="")
    df, rows = read_data_file(p, keep_row_map=True)
    assert len(df) == 5
    # строка 1 пустая, заголовок – 2; пустая 4 и строка из пробелов 6
    # пропущены pandas; «;» – строка 7 (пустые ячейки); поле с переносом
    # в кавычках – одна строка Excel (9).
    assert rows == [3, 5, 7, 8, 9]


def test_undated_row_number_matches_file_with_blank_lines(tmp_path):
    """H3 аудита s56: две пустые строки выше строки без даты – в отказе
    номер строки файла (24), а не позиции таблицы (22); в проверке, в OLS и в
    байесе одинаково, образец даты – тоже по файлу."""
    from engines.modeler import train_model
    from engines.ols_modeler import train_ols
    from engines.validator import validate_data
    df = _frame()
    df.loc[20, "date"] = None
    lines = _ru_lines(df)
    # две пустые строки после 5-й строки данных (строки файла 7 и 8)
    lines = lines[:6] + ["", ""] + lines[6:]
    p = tmp_path / "data.csv"
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    res = validate_data(str(p))
    undated = [i for i in res["issues"] if i["type"] == "undated_row_in_data"]
    assert [i["rows"] for i in undated] == [[24]]
    assert "В строке 24 файла" in undated[0]["message"]
    assert "так же, как в строке 23," in undated[0]["message"]
    tr = train_ols(_cfg(p), str(tmp_path / "proj"))
    assert tr["error_code"] == "UNDATED_ROW_IN_DATA"
    assert tr["message"] == undated[0]["message"]
    tb = train_model(_cfg(p), str(tmp_path / "proj_b"))
    assert tb["error_code"] == "UNDATED_ROW_IN_DATA"
    assert tb["message"] == undated[0]["message"]


def test_total_row_number_matches_file_with_blank_lines(tmp_path):
    """Итоговая строка в хвосте CSV с пустой строкой выше – номер по файлу
    в проверке и в обоих обучениях."""
    from engines.modeler import train_model
    from engines.ols_modeler import train_ols
    from engines.validator import validate_data
    df = _frame()
    sums = ";".join(["Итого"] + [_ru(df[c].sum()) for c in df.columns[1:]])
    lines = _ru_lines(df) + ["", sums]
    p = tmp_path / "data.csv"
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    res = validate_data(str(p))
    totals = [i for i in res["issues"] if i["type"] == "total_row_in_data"]
    assert [i["rows"] for i in totals] == [[N + 3]]
    tr = train_ols(_cfg(p), str(tmp_path / "proj"))
    assert tr["error_code"] == "TOTAL_ROW_IN_DATA"
    assert tr["message"] == totals[0]["message"]
    tb = train_model(_cfg(p), str(tmp_path / "proj_b"))
    assert tb["error_code"] == "TOTAL_ROW_IN_DATA"
    assert tb["message"] == totals[0]["message"]


def test_xlsx_blank_row_number_unchanged(tmp_path):
    """H2 аудита s56: в xlsx пустая строка в середине остаётся строкой
    таблицы – номер верен и без карты (не сломан)."""
    from engines.validator import validate_data
    df = _frame()
    df["date"] = pd.to_datetime(df["date"]).astype(object)
    blank = pd.DataFrame([{c: None for c in df.columns}])
    out = pd.concat([df.iloc[:5], blank, df.iloc[5:]], ignore_index=True)
    out.loc[21, "date"] = None
    p = tmp_path / "data.xlsx"
    out.to_excel(p, index=False)
    res = validate_data(str(p))
    assert [i["rows"] for i in res["issues"] if i["type"] == "undated_row_in_data"] == [[23]]


# ─── Проверка и обучение читают одинаково (CSVPROBE_s56) ─────────────────────


@pytest.mark.parametrize("sep,encoding", [(";", "cp1251"), (";", "utf-8-sig"), ("\t", "utf-8")])
def test_validation_and_training_agree_on_russian_csv(tmp_path, sep, encoding):
    """Зонд s56: «;» с точкой – проверка «ГОТОВ», обучение «KPI column not
    found»; «;» с запятой – отказ проверки. Теперь – как у CSV «,»: проверка
    без критических замечаний, OLS обучается на тех же числах."""
    from engines.ols_modeler import train_ols
    from engines.validator import validate_data
    df = _frame()
    comma = tmp_path / "comma.csv"
    df.to_csv(comma, index=False)
    ru = _write_ru(df, tmp_path / "ru.csv", sep, encoding)
    v_ru, v_c = validate_data(str(ru)), validate_data(str(comma))
    assert v_ru["status"] == v_c["status"]
    assert [i["type"] for i in v_ru["issues"]] == [i["type"] for i in v_c["issues"]]
    t_ru = train_ols(_cfg(ru), str(tmp_path / "p_ru"))
    t_c = train_ols(_cfg(comma), str(tmp_path / "p_c"))
    assert t_ru["status"] == "ok", t_ru.get("message")
    assert t_ru["diagnostics"]["n_obs"] == t_c["diagnostics"]["n_obs"] == N
    assert t_ru["diagnostics"]["metrics"]["r_squared"] == pytest.approx(
        t_c["diagnostics"]["metrics"]["r_squared"], rel=1e-9)


class _StopAfterFingerprint(Exception):
    pass


def test_fingerprint_taken_from_table_exactly_as_read(tmp_path, monkeypatch):
    """Свойство, которое стережёт test_train_model_computes_fingerprint_right_after_read,
    проверено поведением: байес снимает отпечаток с таблицы ровно такой, какой
    её отдаёт `read_data_file`, – до отсева хвоста медиаплана (KPI пуст) и
    любых преобразований. Файл – CSV русского Excel с пустой строкой."""
    import utils.data_fingerprint as fp_mod
    from engines.modeler import train_model
    df = _frame()
    df.loc[N - 3:, "sales"] = np.nan  # хвост медиаплана: 3 периода без KPI
    lines = [x.replace(";nan;", ";;") for x in _ru_lines(df)]
    lines = lines[:4] + [""] + lines[4:]
    p = tmp_path / "data.csv"
    p.write_text("\r\n".join(lines) + "\r\n", encoding="cp1251", newline="")
    seen = {}

    def capture(frame, data_file):
        seen["df"] = frame.copy()
        raise _StopAfterFingerprint()

    monkeypatch.setattr(fp_mod, "build_data_fingerprint", capture)
    with pytest.raises(_StopAfterFingerprint):
        train_model(_cfg(p), str(tmp_path / "proj_b"))
    as_read = read_data_file(p)
    assert len(as_read) == N
    assert as_read["sales"].isna().sum() == 3
    pd.testing.assert_frame_equal(seen["df"], as_read)
