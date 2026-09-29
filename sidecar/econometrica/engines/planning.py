"""SSOT-модуль детекции хвоста медиаплана (planning mode).

Задача: в одном Excel-файле после исторических строк (KPI заполнен) может
идти «хвост будущего» — строки с пустым KPI и заполненными инвестициями.
Этот модуль распознаёт границу истории/будущего и возвращает чистые DataFrame
без сайд-эффектов.

Публичное API:
  detect_media_plan_tail(df, date_col, kpi_col, media_cols) -> dict
  find_trailing_total_rows(df, date_col, kpi_col, file_rows) -> list[dict]
  total_rows_message(total_rows) -> str
  find_undated_rows(df, date_col, value_cols, exclude_index, min_numbers, file_rows) -> list[dict]
  nearest_dated_row(df, date_col, undated_rows, file_rows) -> int | None
  undated_rows_message(undated_rows, dated_row) -> str
  compute_source_hash(data_file) -> str
  load_frames(data_file, date_col, kpi_col, media_cols) -> dict
  load_saved_forecast(project_dir) -> dict | None
  summarize_forecast(forecast) -> dict | None
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from utils.dates import parse_dates
from utils.safe_io import unique_export_path

logger = logging.getLogger(__name__)

# Размер блока для хэша (первые 512 КБ — дёшево, детерминированно)
_HASH_READ_BYTES = 512 * 1024


# ─── Вспомогательные ────────────────────────────────────────────────────────


def _period_label(dt: "pd.Timestamp", granularity: str) -> str:
    """Человекочитаемый ярлык периода по гранулярности."""
    if granularity == "M":
        return dt.strftime("%Y-%m")
    if granularity == "W":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "D":
        return dt.strftime("%Y-%m-%d")
    if granularity == "Q":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    if granularity == "Y":
        return str(dt.year)
    return dt.strftime("%Y-%m-%d")


def _expected_next(last_hist: "pd.Timestamp", granularity: str) -> "pd.Timestamp":
    """Ожидаемая первая дата будущего (ровно один период за последней историей)."""
    if granularity == "D":
        return last_hist + pd.Timedelta(days=1)
    if granularity == "W":
        return last_hist + pd.Timedelta(weeks=1)
    if granularity == "M":
        return last_hist + pd.DateOffset(months=1)
    if granularity == "Q":
        return last_hist + pd.DateOffset(months=3)
    if granularity == "Y":
        return last_hist + pd.DateOffset(years=1)
    # Для «unknown» / прочих — используем медианный шаг как запас, возвращаем None-sentinel
    return last_hist + pd.Timedelta(days=1)


def _days_gap_tolerance(granularity: str) -> float:
    """Допустимое отклонение от «ровного» следующего периода (в днях).

    Месяцы имеют 28-31 день — нужен более широкий допуск.
    """
    return {
        "D": 0.5,
        "W": 1.0,
        "M": 5.0,
        "Q": 10.0,
        "Y": 30.0,
    }.get(granularity, 3.0)


# ─── Строка «итого» в хвосте таблицы (L4, s55) ───────────────────────────────

# Слово-признак итоговой строки в любой текстовой ячейке («Итого», «ИТОГО:»,
# «Всего», «Grand Total», «Subtotal», «Sum», «Сумма за период») или строки
# средних по столбцам («Среднее», «Average», «Avg», «Mean» – L-1n, аудит s55:
# с суммами она не совпадает и без слова обучалась лишним периодом). Одно
# слово итогом строку не делает – см. `_row_is_total`.
_TOTAL_WORD_RE = re.compile(
    r"(?<!\w)(итог\w*|всего|(?:sub)?totals?|sum|сумм\w*|средн\w*|average|avg|mean)(?!\w)",
    re.IGNORECASE,
)
# Допуск «значение ≈ сумме столбца»: Excel-сумма точна, запас — на округление
# отображаемых значений при ручном вводе итога.
_TOTAL_SUM_REL_TOL = 1e-3


def _row_is_total(
    row: "pd.Series",
    above: "pd.DataFrame",
    date_col: str,
    kpi_col: str | None,
) -> str | None:
    """Причина считать строку итоговой: 'word' / 'sums' / None.

    Итог — строка, где есть числа И (слово-признак ИЛИ совпадение с суммами).
    """
    import datetime as _dt
    import numpy as _np

    values: dict[Any, float] = {}
    for col, val in row.items():
        if col == date_col:
            continue
        # N9 (2.5.9): дата и пустая дата (NaT) второй колонки дат – не число:
        # `to_numeric` давал им наносекунды, и сноска под таблицей
        # [date, date_end] получала ложный отказ «похожа на итоговую».
        if val is pd.NaT or isinstance(val, (_dt.date, _np.datetime64)):
            continue
        v = pd.to_numeric(pd.Series([val]), errors="coerce").iloc[0]
        if pd.notna(v):
            values[col] = float(v)
    # Строка без единого числа — примечание («Источник: …, суммы без НДС»):
    # KPI в ней пуст, в обучение она не попадает, и слово-признак в тексте
    # сноски отказа не даёт (M-1, аудит s55).
    if not values:
        return None
    for val in row.values:
        if isinstance(val, str) and _TOTAL_WORD_RE.search(val):
            return "word"
    # Суммы сверяем со всеми вариантами, которыми их считают в Excel: по всем
    # строкам выше, только по истории (KPI заполнен) и только по плану (KPI
    # пуст) — итог медиаплана клиент мог посчитать любым из них (H-1, аудит s55).
    parts = [above]
    if kpi_col and kpi_col in above.columns:
        has_kpi = pd.to_numeric(above[kpi_col], errors="coerce").notna()
        parts += [above[has_kpi], above[~has_kpi]]
    n_match = 0
    for col, v in values.items():
        for part in parts:
            col_vals = pd.to_numeric(part[col], errors="coerce").dropna()
            # Сумма столбца с одним ненулевым значением равна ему самому —
            # совпадение с ней ничего не доказывает.
            if int((col_vals != 0).sum()) < 2:
                continue
            s = col_vals.sum()
            if s != 0 and abs(v - s) <= _TOTAL_SUM_REL_TOL * abs(s):
                # Значение, равное сумме неотрицательного KPI с ≥2 ненулевыми
                # строками выше, у настоящего периода невозможно (все прочие
                # были бы нулями) — итог уже по одной ячейке: «подбили итог
                # продаж» или суммы лишь в части столбцов (H-2, аудит s55).
                if col == kpi_col and bool((col_vals >= 0).all()):
                    return "sums"
                n_match += 1
                break
    # Одно совпадение вне KPI — случайность; итог повторяет суммы большинства
    # столбцов.
    if n_match >= 2 and n_match * 2 >= len(values):
        return "sums"
    return None


def _resolve_role_column(df: "pd.DataFrame", col: str | None, role: str) -> str | None:
    """Колонка роли: названная, если она есть в таблице, иначе — та, что
    распознаёт проверка данных (`detect_column_role_with_confidence`).

    Конфиг обучения переоткрытого проекта несёт `date_column='date'` по
    умолчанию и при файле с «Дата»; без распознавания защита от итога молча
    выключалась бы (M-2, аудит s55).
    """
    if col and col in df.columns:
        return col
    from engines.validator import detect_column_role_with_confidence
    return next(
        (c for c in df.columns if detect_column_role_with_confidence(str(c))[0] == role),
        None,
    )


def _file_row(file_rows: list[int] | None, pos: int) -> int:
    """Номер строки файла для позиции таблицы: по карте строк, если она
    есть и сходится с таблицей, иначе позиция + 2 (заголовок – строка 1)."""
    if file_rows is not None and 0 <= pos < len(file_rows):
        return int(file_rows[pos])
    return pos + 2


def find_trailing_total_rows(
    df: "pd.DataFrame",
    date_col: str | None,
    kpi_col: str | None = None,
    file_rows: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Найти строки-итоги в ХВОСТЕ таблицы (после последней строки с датой).

    Итог — строка без распознаваемой даты, в которой есть числа и слово
    «итого / всего / total / сумма / среднее» ИЛИ значение KPI (либо большинства
    числовых столбцов) равно сумме столбца по строкам выше — всем, истории
    или плану. Такая строка, попав в обучение,
    удваивает продажи и бюджеты; в файле с медиапланом она же становится
    лишним «периодом плана» без даты.

    Строки без даты В СЕРЕДИНЕ данных сюда не попадают — это другая ошибка,
    её ловит `find_undated_rows` (s56). Полностью пустые строки итогом не
    считаются.

    Последнюю строку С ДАТОЙ проверяем тоже, только по KPI: итог с датой –
    `reason='dated_sums'` и `column` – колонка KPI (N6, 2.5.9).

    Возвращает [{index, file_row, reason}] в порядке файла: index — метка
    строки в df, file_row — номер строки в файле (заголовок — строка 1):
    `file_rows[позиция]`, если карта строк передана (`data_io.read_data_file`,
    пустые строки CSV), иначе позиция + 2.
    Колонки даты и KPI, которых нет в таблице (или None), распознаются тем же
    способом, что в проверке данных.
    """
    if df.empty:
        return []
    date_col = _resolve_role_column(df, date_col, "date")
    kpi_col = _resolve_role_column(df, kpi_col, "kpi")
    if not date_col:
        return []
    # Числовая колонка роли «дата» (номера недель) – «дата есть» там, где
    # есть число: для неё помощник дат отдаёт NaT (N0, 2.5.9).
    if pd.api.types.is_numeric_dtype(df[date_col]):
        dates = df[date_col]
    else:
        dates = parse_dates(df[date_col])
    positions = [i for i in range(len(df)) if pd.notna(dates.iloc[i])]
    if not positions:
        return []
    last_dated = positions[-1]
    above = df.iloc[: last_dated + 1]
    found: list[dict[str, Any]] = []
    # N6 (2.5.9): итог С ДАТОЙ последней строкой («2023-12-31» и сумма продаж
    # за год) обучался периодом с удвоенными продажами без замечаний. Сверяем
    # только KPI последней датированной строки с суммой KPI выше – у
    # настоящего периода она невозможна (см. `_row_is_total`). Подытог с
    # датой в середине таблицы – не здесь (M-3, в 2.5.10).
    if kpi_col and kpi_col in df.columns and kpi_col != date_col:
        if _row_is_total(df.iloc[last_dated][[kpi_col]], df.iloc[:last_dated],
                         date_col, kpi_col) == "sums":
            found.append({"index": df.index[last_dated],
                          "file_row": _file_row(file_rows, last_dated),
                          "reason": "dated_sums", "column": kpi_col})
    for pos in range(last_dated + 1, len(df)):
        row = df.iloc[pos]
        if row.isna().all():
            continue
        reason = _row_is_total(row, above, date_col, kpi_col)
        if reason:
            found.append({"index": df.index[pos], "file_row": _file_row(file_rows, pos),
                          "reason": reason})
    return found


def total_rows_message(total_rows: list[dict[str, Any]]) -> str:
    """Текст для человека: какие строки похожи на итог и что с ними делать.

    Итог с датой (`reason='dated_sums'`, N6 2.5.9) – свой текст: «в ней нет
    даты» о нём было бы неправдой."""
    dated = [r for r in total_rows if r.get("reason") == "dated_sums"]
    undated = [r for r in total_rows if r.get("reason") != "dated_sums"]
    parts = [_undated_total_rows_message(undated)] if undated else []
    for r in dated:
        parts.append(
            f"Строка {r['file_row']} файла похожа на итоговую: дата в ней заполнена, "
            f"но число в колонке «{r['column']}» равно сумме этой колонки во всех "
            f"строках выше. В расчёт её брать нельзя – при "
            f"обучении она станет лишним периодом и исказит продажи и бюджеты. "
            f"Удалите эту строку из файла и загрузите его заново."
        )
    return " ".join(parts)


def _undated_total_rows_message(total_rows: list[dict[str, Any]]) -> str:
    nums = ", ".join(str(r["file_row"]) for r in total_rows)
    if len(total_rows) == 1:
        return (
            f"Строка {nums} файла похожа на итоговую или среднюю: в ней нет даты, "
            f"а в ячейках слово «Итого» или «Среднее» либо суммы столбцов. В расчёт "
            f"её брать нельзя – при обучении она станет лишним периодом и исказит "
            f"продажи и бюджеты. Удалите эту строку из файла и загрузите его заново."
        )
    return (
        f"Строки {nums} файла похожи на итоговые или средние: в них нет даты, "
        f"а в ячейках слово «Итого» или «Среднее» либо суммы столбцов. В расчёт "
        f"их брать нельзя – при обучении они станут лишними периодами и исказят "
        f"продажи и бюджеты. Удалите эти строки из файла и загрузите его заново."
    )


# ─── Строка с числами без даты в любом месте файла (в-1, s56) ────────────────

# Больше номеров строк в тексте отказа не перечисляем – остальные «и ещё K».
_UNDATED_ROWS_SHOWN = 5


# Ячейка – полная дата: три числовые группы (день, месяц, год в любом
# порядке) через «.», «/» или «-» либо «число месяц-словом год»
# («16 October 2023», «16 Oct 2023» – L-3, AUDIT03 s56), допускается хвост
# времени.
_FULL_DATE_RE = re.compile(
    r"\s*(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[^\W\d_]+\.?\s+\d{2,4})(?:[T\s].*)?"
)


def _full_date_cells(series: "pd.Series") -> "pd.Series":
    """Ячейка – полная дата: объект даты (из xlsx), строка из трёх
    числовых групп или «16 October 2023». Голый год «2023», «2023-12»,
    «Dec 2023» – нет."""
    import datetime as _dt
    import numpy as _np

    def full(v: Any) -> bool:
        if isinstance(v, str):
            return _FULL_DATE_RE.fullmatch(v) is not None
        return isinstance(v, (_dt.date, _np.datetime64)) and not pd.isna(v)

    return series.map(full).astype(bool)


def _dates_recognized(series: "pd.Series") -> "pd.Series":
    """Разобрана ли дата в каждой ячейке – тем же помощником, что даёт
    значения дат обучению и всем движкам (`utils.dates.parse_dates`, N0
    2.5.9): «дата есть» ровно там, где у помощника не NaT. Прежний разбор
    pandas здесь признавал «Jan-23» датой года 1, а значения брались другим
    разбором (C-2, PLANAUDIT_259).

    Помощник берёт за дату и голый год «2023», и «2023-12», «Dec 2023» –
    подытог года с такой меткой снова обучался бы лишним периодом (A2-H1,
    аудит s56). Поэтому в колонке, где полные даты – большинство непустых,
    признаём только их: в столбце дат из xlsx текст «2022» и число 2022 –
    не дата (S9 аудита). Колонку «2024-01», «Jan-23», «2023-Q1» это не
    трогает – полных дат в ней нет.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.notna()
    filled = series.notna().to_numpy()
    full = _full_date_cells(series).to_numpy()
    ok = parse_dates(series).notna().to_numpy(copy=True)
    if int(full.sum()) * 2 > int(filled.sum()):
        ok &= full
    return pd.Series(ok, index=series.index)


def _is_calendar(series: "pd.Series") -> bool:
    """Колонка – календарь: datetime64 либо нечисловая колонка, у которой
    дата распознаётся у большинства непустых значений. Числовая (и bool) –
    не календарь: `to_datetime` берёт любое число за дату от 1970-го, и
    пустая ячейка давала ложный отказ (macro_monthly.csv, приёмка fix02).
    Цена – целые серийные номера Excel во всей колонке тоже не календарь.
    Текст «01.2022» / «2022.01» (дата, записанная Excel как число) – тоже
    не календарь: по ней отказывает `numeric_date_example` (H-1, AUDIT03 s56).
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series):
        return False
    filled = series.dropna()
    if filled.empty:
        return False
    from engines.data_io import is_number_like_date_column
    if is_number_like_date_column(filled):
        return False
    return int(_dates_recognized(filled).sum()) * 2 > len(filled)


def numeric_date_example(series: "pd.Series") -> str | None:
    """Колонка даты прочитана как число – пример её значения для текста
    отказа, иначе None.

    «Как число» – числовой тип (не bool): «01.2022» из CSV (pandas даёт
    1.2022), ГГГГММ, серийные номера Excel, номера недель; либо текст, где
    каждое значение «ММ.ГГГГ» / «ГГГГ.ММ» (`data_io` оставляет его текстом).
    `to_datetime` берёт число за наносекунды от 1970 года, и модель молча
    обучалась на датах 1970-01-01: праздники и сезонность байеса считались
    от них (H-1, AUDIT03 s56).
    """
    filled = series.dropna()
    if filled.empty:
        return None
    if pd.api.types.is_bool_dtype(series):
        return None
    if pd.api.types.is_numeric_dtype(series):
        v = filled.iloc[0]
        if float(v).is_integer():
            return str(int(v))
        return str(v)
    from engines.data_io import is_number_like_date_column
    if is_number_like_date_column(filled):
        return str(filled.iloc[0]).strip()
    return None


def numeric_date_message(column: Any, example: str, calendar: Any = None) -> str:
    """Текст отказа: дата в колонке `column` прочитана как число. Если в
    файле есть колонка с датами `calendar` – назвать её и сказать, как её
    получить: колонка даты в конфиг обучения идёт только из detected.date
    проверки, разметка ролей её не меняет, а новая проверка сама выбирает
    календарную колонку. Перезапускает проверку в открытом проекте кнопка
    «Сбросить шаг» на шаге «Валидация» (M-3, AUDIT03 s56)."""
    if calendar is not None:
        return (
            f"Дата в колонке «{column}» прочитана как число (например {example}). "
            f"В файле есть колонка с датами «{calendar}» – на шаге «Валидация» "
            f"нажмите «Сбросить шаг»: программа заново проверит данные и сама "
            f"возьмёт её колонкой даты. Кнопка сбросит и ваши правки на этом шаге – "
            f"роли колонок и настройки KPI, их нужно будет задать снова. Затем "
            f"запустите обучение."
        )
    return (
        f"Дата в колонке «{column}» прочитана как число (например {example}). "
        f"Сохраните даты в виде ДД.ММ.ГГГГ и загрузите файл заново."
    )


def numeric_date_refusal(df: "pd.DataFrame", column: Any) -> str | None:
    """Текст отказа H-1 для колонки даты `column` (из detected.date или
    date_column конфига), если она прочитана как число; иначе None.

    Проверка отдаёт в detected.date календарную колонку, когда она есть,
    поэтому текст с подсказкой про колонку «Дата» видит только обучение со
    старым или ручным конфигом. Один текст для проверки, OLS и
    байеса.
    """
    if column is None or column not in df.columns:
        return None
    example = numeric_date_example(df[column])
    if example is None:
        return None
    return numeric_date_message(column, example, _calendar_date_column(df, column))


def find_non_numeric_column(
    df: "pd.DataFrame", columns: list[Any],
) -> tuple[Any, list[str]] | None:
    """Первая колонка модели, которую обучение не сможет привести к числу
    (`astype(float)`), и до трёх примеров непригодных значений; иначе None.

    Обучение на CSV с « - » или «1 234 ₽» в числовой колонке падало сырым
    ValueError вместо понятного отказа (L-2, AUDIT03 s56). Колонки, которых
    нет в таблице, пропускаем – для них у обучения свои отказы.
    """
    for col in dict.fromkeys(c for c in columns if c is not None):
        if col not in df.columns:
            continue
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            continue
        bad = set()
        for v in s.dropna():
            try:
                float(v)
            except (TypeError, ValueError):
                bad.add(str(v).strip())
        if bad:
            return col, sorted(bad)[:3]
    return None


def non_numeric_column_message(column: Any, examples: list[str]) -> str:
    """Текст отказа: в колонке модели есть значения не-числа."""
    return (
        f"В колонке «{column}» есть значения, которые не читаются как числа "
        f"(например: {', '.join(examples)}). Обучение на такой колонке не "
        f"запустится: замените текст числами или задайте столбцу числовой формат "
        f"в исходном файле и загрузите файл заново."
    )


def date_not_parsed_message(column: Any, examples: list[str]) -> str:
    """Текст отказа: в колонке даты есть значения, которые не читаются как
    дата (N2, 2.5.9) – вместо сырого «time data … doesn't match format»."""
    return (
        f"В колонке «{column}» есть значения, которые не читаются как дата "
        f"(например: {', '.join(examples)}). Без дат программа не может учесть "
        f"праздники и сезонность. Запишите даты в виде ДД.ММ.ГГГГ и загрузите "
        f"файл заново."
    )


def _calendar_date_column(df: "pd.DataFrame", preferred: str | None) -> str | None:
    """Колонка даты для правила строк без даты: `preferred`, если она есть в
    таблице и это календарь; иначе первая колонка с ролью «дата», которая
    календарь; иначе None – правило молчит.

    Проверка данных передаёт detected.date, обучение – date_column конфига
    (куда detected.date и попадает), поэтому обе стороны выбирают одну
    колонку. В файле [Дата, Неделя] detected.date – «Неделя» с номерами
    недель; без этого выбора правило на ней молчало бы, и строка средних
    снова обучалась лишним периодом.
    """
    if preferred is not None and preferred in df.columns and _is_calendar(df[preferred]):
        return preferred
    from engines.validator import detect_column_role_with_confidence
    return next(
        (c for c in df.columns
         if detect_column_role_with_confidence(str(c))[0] == "date" and _is_calendar(df[c])),
        None,
    )


def find_undated_rows(
    df: "pd.DataFrame",
    date_col: str | None,
    value_cols: list[str],
    exclude_index: Any = (),
    min_numbers: int = 1,
    file_rows: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Найти строки с числами, у которых дата не заполнена или не
    распознаётся, – в любом месте таблицы: хвост, середина, после медиаплана.

    Зонд s56: строка средних без слова, строка со стёртой датой обучались
    лишним периодом без единого предупреждения (OLS n_obs 49 вместо 48),
    а в середине файла ещё и сдвигали адсток следующих периодов.

    «Строка с числами» – в ней есть НЕНУЛЕВОЕ число хотя бы в одной из
    `value_cols` (колонки модели: KPI, медиа, контроли). Протянутая формула
    с нулями, «№ п/п», справочный блок под таблицей в колонках вне модели
    отказа не дают (H-2, аудит s56). Строки из `exclude_index` (итоговые – у
    них свой текст `total_rows_message`) не сообщаем. `min_numbers` – в скольких
    колонках нужно ненулевое число: проверка без распознанных ролей берёт все
    числовые колонки и требует двух (A2-M1, аудит s56).

    Колонка даты – `date_col`, если это календарь, иначе первая колонка с
    ролью «дата», которая календарь (`_calendar_date_column`); проверка
    передаёт detected.date, обучение – date_column конфига, и обе стороны
    приходят к одной колонке (H-1, приёмка fix02).

    Предохранитель: правило молчит, если календарной колонки даты нет или дата
    распознана не более чем у половины строк с числами, – это формат дат,
    а не отдельные строки без даты. Считается по тем же строкам с числами,
    поэтому нули протянутой формулы его не выключают (H-3).

    Возвращает [{index, file_row}] в порядке файла, как
    `find_trailing_total_rows` (с той же картой строк `file_rows`).
    """
    if df.empty:
        return []
    date_col = _calendar_date_column(df, date_col)
    if not date_col:
        return []
    if isinstance(value_cols, str):
        value_cols = [value_cols]
    cols = [c for c in dict.fromkeys(value_cols) if c in df.columns and c != date_col]
    if not cols:
        return []
    raw = df[cols]
    vals = raw.apply(pd.to_numeric, errors="coerce")
    # Пустую ячейку колонки дат (NaT) `to_numeric` превращает в целое число –
    # числом её не считаем.
    has_numbers = (vals.notna() & (vals != 0) & raw.notna()).sum(axis=1) >= max(1, min_numbers)
    dated = _dates_recognized(df[date_col])
    n_with_numbers = int(has_numbers.sum())
    n_dated = int((has_numbers & dated).sum())
    if n_dated * 2 <= n_with_numbers:
        return []
    excluded = set(exclude_index)
    return [
        {"index": df.index[pos], "file_row": _file_row(file_rows, pos)}
        for pos in range(len(df))
        if has_numbers.iloc[pos] and not dated.iloc[pos]
        and df.index[pos] not in excluded
    ]


def nearest_dated_row(
    df: "pd.DataFrame",
    date_col: str | None,
    undated_rows: list[dict[str, Any]],
    file_rows: list[int] | None = None,
) -> int | None:
    """Номер строки файла с распознанной датой, ближайшей к первой строке из
    `undated_rows` (при равенстве – верхняя), – образец для текста отказа.
    Колонка даты выбирается, как в `find_undated_rows`; нет такой строки –
    None. Нумерация – та же карта строк `file_rows`."""
    if df.empty or not undated_rows:
        return None
    date_col = _calendar_date_column(df, date_col)
    if not date_col:
        return None
    dated = _dates_recognized(df[date_col]).to_numpy()
    positions = [i for i in range(len(df)) if dated[i]]
    if not positions:
        return None
    first = df.index.get_loc(undated_rows[0]["index"])
    best = min(positions, key=lambda i: (abs(i - first), i))
    return _file_row(file_rows, best)


def undated_rows_message(
    undated_rows: list[dict[str, Any]],
    dated_row: int | None = None,
) -> str:
    """Текст для человека: в каких строках нет даты и что с ними делать.

    `dated_row` – строка файла с распознанной датой (`nearest_dated_row`):
    образец «так же, как в строке N». Готовый пример вида «01.02.2024»
    противоречил «в том же виде» в файле с датами 2024-02-01 и читался
    двояко (L-5, аудит s56).
    """
    if dated_row is not None:
        how = f"так же, как в строке {dated_row},"
    else:
        how = "в том же виде, что и в остальных строках,"
    if len(undated_rows) == 1:
        return (
            f"В строке {undated_rows[0]['file_row']} файла не заполнена или не "
            f"распознана дата, а в ячейках есть числа. Строку без даты программа не "
            f"может поставить на шкалу времени: если это итог, среднее или примечание, "
            f"при обучении она станет лишним периодом и исказит продажи и бюджеты. "
            f"Заполните дату в этой строке – {how} – или удалите строку и загрузите "
            f"файл заново."
        )
    nums = ", ".join(str(r["file_row"]) for r in undated_rows[:_UNDATED_ROWS_SHOWN])
    rest = len(undated_rows) - _UNDATED_ROWS_SHOWN
    if rest > 0:
        # «и ещё 4 файла» читалось как «ещё четыре файла» – называем строки явно.
        word = "строке" if rest % 10 == 1 and rest % 100 != 11 else "строках"
        nums += f" и ещё в {rest} {word}"
    return (
        f"В строках {nums} файла не заполнены или не распознаны даты, а в ячейках "
        f"есть числа. Строки без даты программа не может поставить на шкалу "
        f"времени: если это итоги, средние или примечания, при обучении они станут "
        f"лишними периодами и исказят продажи и бюджеты. Заполните даты в этих "
        f"строках – {how} – или удалите строки и загрузите файл заново."
    )


# ─── Основная функция ────────────────────────────────────────────────────────


def detect_media_plan_tail(
    df: "pd.DataFrame",
    date_col: str,
    kpi_col: str,
    media_cols: list[str],
) -> dict[str, Any]:
    """Обнаружить хвост медиаплана в DataFrame.

    Аргументы:
        df: DataFrame со смешанными историческими строками и строками плана.
        date_col: имя колонки с датами.
        kpi_col: имя KPI-колонки (продажи).
        media_cols: список колонок инвестиций/медиа.

    Возвращает dict:
        {found: False}  — хвоста нет.
        {found: False, error: 'no_history'}  — весь KPI пуст.
        {found: False, reason: 'internal_gaps'}  — NaN в середине истории (не хвост).
        {
            found: True,
            n_future_periods: int,
            history_df: DataFrame,
            future_df: DataFrame,
            future_dates: [isoformat str],
            period_labels: [str],
            granularity: str ('D'|'W'|'M'|'Q'|'Y'|'unknown'),
            channels: {col: [float]},
            continuous: bool,
            warnings: [{type, message}],
        }
    """
    # Работаем на копии, не трогаем оригинал
    work = df.copy()

    # Приводим даты (единым помощником, N0 2.5.9) и сортируем
    work[date_col] = parse_dates(work[date_col])
    # N4 (2.5.9): строка без даты, без KPI и без ненулевых медиа (протянутые
    # нули под планом) – не период плана. Иначе план становился на период
    # длиннее («7 недель» при 6), а прогноз базового плана с датой null
    # отказывал 422. Строку без даты с числами ловит `find_undated_rows`.
    _media_in = [c for c in media_cols if c in work.columns]
    _media_nonzero = (
        work[_media_in].apply(pd.to_numeric, errors="coerce").fillna(0).ne(0).any(axis=1)
        if _media_in else pd.Series(False, index=work.index)
    )
    work = work[~(work[date_col].isna() & work[kpi_col].isna() & ~_media_nonzero)]
    work = work.sort_values(date_col).reset_index(drop=True)

    kpi = work[kpi_col]

    # Случай 1: весь KPI пуст
    if kpi.last_valid_index() is None:
        return {"found": False, "error": "no_history"}

    last_idx = len(work) - 1

    # Случай 2: хвоста нет — последняя строка заполнена
    if pd.notna(kpi.iloc[-1]):
        return {"found": False}

    # Граница истории: последний индекс с непустым KPI
    boundary = int(kpi.last_valid_index())  # type: ignore[arg-type]

    # Хвост = строки после boundary
    tail_kpi = kpi.iloc[boundary + 1:]

    # Случай 3: проверка непрерывности хвоста.
    # Все строки ПОСЛЕ boundary должны иметь пустой KPI.
    # Если хоть одна строка хвоста имеет непустой KPI — это дыры в середине, не хвост.
    if tail_kpi.notna().any():
        return {"found": False, "reason": "internal_gaps"}

    history_df = work.iloc[: boundary + 1].copy()
    future_df = work.iloc[boundary + 1 :].copy()

    # Определяем гранулярность по истории
    from utils.forecast_validation import detect_granularity  # SSOT

    gran_result = detect_granularity(history_df[date_col])
    granularity: str = gran_result.get("granularity", "W")

    warnings: list[dict[str, str]] = []

    # Проверка непрерывности дат (A8)
    last_hist_date = history_df[date_col].dropna().iloc[-1]
    first_future_date = future_df[date_col].dropna().iloc[0]
    expected = _expected_next(last_hist_date, granularity)
    gap_days = abs((first_future_date - expected).total_seconds()) / 86400
    tolerance = _days_gap_tolerance(granularity)
    continuous = gap_days <= tolerance

    if not continuous:
        warnings.append(
            {
                "type": "date_gap",
                "message": (
                    f"Разрыв дат между историей и будущим: ожидалась {expected.date()}, "
                    f"получена {first_future_date.date()} "
                    f"(отклонение {gap_days:.1f} дн. при допуске {tolerance} дн.)."
                ),
            }
        )

    # Предупреждение: пустые медиа в будущем
    for col in media_cols:
        if col in future_df.columns:
            if future_df[col].isna().any():
                warnings.append(
                    {
                        "type": "empty_media_in_future",
                        "message": f"Колонка «{col}» содержит пустые значения в строках плана.",
                    }
                )

    # Собираем каналы: {col: [float]} — NaN → None для JSON-безопасности
    channels: dict[str, list[Any]] = {}
    for col in media_cols:
        if col in future_df.columns:
            vals = future_df[col].tolist()
            channels[col] = [float(v) if pd.notna(v) else None for v in vals]

    future_dates = [
        ts.isoformat() if pd.notna(ts) else None
        for ts in future_df[date_col]
    ]
    period_labels = [
        _period_label(ts, granularity) if pd.notna(ts) else ""
        for ts in future_df[date_col]
    ]

    return {
        "found": True,
        "n_future_periods": len(future_df),
        "history_df": history_df,
        "future_df": future_df,
        "future_dates": future_dates,
        "period_labels": period_labels,
        "granularity": granularity,
        "channels": channels,
        "continuous": continuous,
        "warnings": warnings,
    }


# ─── Хэш файла ──────────────────────────────────────────────────────────────


def compute_source_hash(data_file: str) -> str:
    """SHA-256 первых 512 КБ + размер файла.

    Детерминирован, дёшев — для сверки «тот ли файл был при обучении».

    Args:
        data_file: путь к xlsx/csv.

    Returns:
        hex-строка SHA-256 (64 символа).
    """
    p = Path(data_file)
    file_size = p.stat().st_size
    h = hashlib.sha256()
    with open(p, "rb") as f:
        chunk = f.read(_HASH_READ_BYTES)
        h.update(chunk)
    # Добавляем размер файла в хэш для устойчивости к коротким файлам
    h.update(file_size.to_bytes(8, "big"))
    return h.hexdigest()


# ─── Обёртка для чтения файла ────────────────────────────────────────────────


def _read_file(path: Path) -> "pd.DataFrame":
    """Читаем xlsx/csv в DataFrame – единым чтением клиентского файла
    (`engines.data_io`, s56 fix04)."""
    if path.suffix in (".xlsx", ".xls", ".csv"):
        from engines.data_io import read_data_file
        return read_data_file(path)
    raise ValueError(f"Неподдерживаемый формат: {path.suffix}. Нужен xlsx или csv.")


def load_frames(
    data_file: str,
    date_col: str | None = None,
    kpi_col: str | None = None,
    media_cols: list[str] | None = None,
) -> dict[str, Any]:
    """SSOT-точка входа: читает файл, авто-детектирует роли, разделяет историю/план.

    Аргументы:
        data_file: путь к xlsx/csv.
        date_col: имя колонки дат (если None — автодетект).
        kpi_col: имя KPI-колонки (если None — автодетект).
        media_cols: список медиа-колонок (если None — автодетект).

    Возвращает:
        {
            history_df: DataFrame с историческими строками,
            future_df: DataFrame | None — строки медиаплана или None,
            detection: dict — результат detect_media_plan_tail,
            source_hash: str,
        }

    Без сайд-эффектов: никакой записи файлов.
    """
    path = Path(data_file)
    df = _read_file(path)

    # Автодетект ролей при необходимости
    if date_col is None or kpi_col is None or media_cols is None:
        from engines.validator import detect_column_role_with_confidence

        detected_date: str | None = None
        detected_kpi: str | None = None
        detected_media: list[str] = []

        for col in df.columns:
            role, _conf = detect_column_role_with_confidence(col)
            if role == "date" and detected_date is None:
                detected_date = str(col)
            elif role == "kpi" and detected_kpi is None:
                detected_kpi = str(col)
            elif role == "media":
                detected_media.append(str(col))
        # N5 (2.5.9): колонка даты – календарная колонка роли «дата», как
        # detected.date проверки. Первая по порядку в [Неделя, Дата] – номера
        # недель, и даты плана выходили 1970-01-01.
        detected_date = _calendar_date_column(df, detected_date) or detected_date

        if date_col is None:
            date_col = detected_date
        if kpi_col is None:
            kpi_col = detected_kpi
        if media_cols is None:
            media_cols = detected_media

    if not date_col:
        raise ValueError("Не удалось определить колонку дат. Передайте date_col явно.")
    if not kpi_col:
        raise ValueError("Не удалось определить KPI-колонку. Передайте kpi_col явно.")
    if not media_cols:
        media_cols = []

    src_hash = compute_source_hash(data_file)
    detection = detect_media_plan_tail(df, date_col, kpi_col, media_cols)

    if detection.get("found"):
        history_df = detection["history_df"]
        future_df = detection["future_df"]
    else:
        history_df = df.copy()
        future_df = None

    return {
        "history_df": history_df,
        "future_df": future_df,
        "detection": detection,
        "source_hash": src_hash,
    }


# ─── Прогноз-план: загрузка сохранённого артефакта ──────────────────────────


def load_saved_forecast(project_dir: str) -> dict[str, Any] | None:
    """Прочитать сохранённый план-прогноз из results/planning.json.

    Структура planning.json:
        {
          "variant_ids": ["v1", "v2", ...],
          "accepted_variant": "v1" | null,
          "disclaimers": [...]
        }

    Для каждого variant_id читается results/scenarios/<variant_id>.json —
    РЕАЛЬНАЯ схема сценария, которую пишет scenario-движок (P-2 fix 2026-07-16:
    прежняя версия читала top-level ключи total_kpi/total_spend_money/roas_money,
    которых в файле нет — движок кладёт суммы в totals.* — и подменяла их 0.0,
    поэтому слайд/HTML показывали ложные нули):
        {
          "scenario_name": str,
          "predictions": [...],
          "predictions_ci_low": [...],           # per-period серии
          "predictions_ci_high": [...],
          "totals": {
            "predicted_kpi": float,              # сумма KPI за горизонт
            "predicted_kpi_ci_low": float,       # интервал СУММЫ за горизонт
            "predicted_kpi_ci_high": float,
            "total_spend_money": float | null,   # null для физметрик (TRP/показы)
            "roas_money": float | null,
            ...
          },
          "disclaimers": [...],
          "future_dates": [...]
        }
    Легаси top-level ключи (name/total_kpi/...) читаются как fallback.

    Возвращает None если planning.json отсутствует или не загружается.
    Возвращает None если ни один сценарий не загрузился.
    INV-50: никаких wireframe-суррогатов — только живые данные; отсутствующее
    значение остаётся None (в отчёте «—»), НЕ подменяется нулём.
    """
    base = Path(project_dir)
    planning_path = base / 'results' / 'planning.json'

    if not planning_path.exists():
        return None

    try:
        with open(planning_path, encoding='utf-8') as f:
            planning = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('planning.json повреждён (%s) — прогноз считается отсутствующим', e)
        return None

    variant_ids: list[str] = planning.get('variant_ids') or []
    accepted_variant: str | None = planning.get('accepted_variant')
    plan_disclaimers: list[str] = list(planning.get('disclaimers') or [])

    if not variant_ids:
        logger.warning('planning.json: variant_ids пуст — прогноз не загружен')
        return None

    scenarios_dir = base / 'results' / 'scenarios'
    scenarios: list[dict] = []
    all_disclaimers: list[str] = list(plan_disclaimers)

    def _first_float(*vals) -> float | None:
        """Первое не-None значение как float; иначе None (не 0 — INV-50)."""
        for v in vals:
            if v is not None:
                return float(v)
        return None

    for vid in variant_ids:
        sc_path = scenarios_dir / f'{vid}.json'
        if not sc_path.exists():
            logger.warning('Сценарий %s не найден: %s', vid, sc_path)
            continue
        try:
            with open(sc_path, encoding='utf-8') as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('Сценарий %s повреждён (%s) — пропускаем', vid, e)
            continue

        sc_disclaimers: list[str] = list(sc.get('disclaimers') or [])
        for d in sc_disclaimers:
            if d not in all_disclaimers:
                all_disclaimers.append(d)

        totals = sc.get('totals') or {}

        scenarios.append({
            'name': str(sc.get('scenario_name') or sc.get('name') or vid),
            'variant_id': vid,
            'predictions': list(sc.get('predictions') or []),
            'ci_low': list(sc.get('predictions_ci_low') or []),
            'ci_high': list(sc.get('predictions_ci_high') or []),
            'total_kpi': _first_float(totals.get('predicted_kpi'), sc.get('total_kpi')),
            'total_spend_money': _first_float(totals.get('total_spend_money'), sc.get('total_spend_money')),
            'roas_money': _first_float(totals.get('roas_money'), sc.get('roas_money')),
            # Интервал СУММЫ за горизонт (тот же, что в GUI-карточке варианта —
            # SSOT чисел клиенту; per-period серии выше — для графиков).
            'total_kpi_ci_low': _first_float(totals.get('predicted_kpi_ci_low')),
            'total_kpi_ci_high': _first_float(totals.get('predicted_kpi_ci_high')),
            'period_labels': list(sc.get('period_labels') or sc.get('future_dates') or []),
            # Бюджет по каналам за весь горизонт — ТОЛЬКО в деньгах
            # (`per_channel_spend.money`). Движок кладёт туда суммы лишь когда
            # перевёл в рубли ВСЕ активные каналы (scenario.py:1203,
            # units_fully_covered), и тогда же их сумма равна total_spend_money —
            # то есть доли в отчёте складываются ровно в 100%. Ряд в натуральных
            # единицах (TRP, показы) сюда НЕ подставляем: сложить рубли с
            # пунктами рейтинга нельзя, а подписать сумму рублём — неправда.
            'per_channel_money': dict(
                (sc.get('per_channel_spend') or {}).get('money') or {}
            ),
            'disclaimers': sc_disclaimers,
        })

    if not scenarios:
        logger.warning('planning.json: ни один сценарий не загрузился')
        return None

    return {
        'status': 'ok',
        'scenarios': scenarios,
        'historical_actual': [],
        'historical_dates': [],
        'cutoff_index': 0,
        'accepted_variant': accepted_variant,
        'disclaimers': all_disclaimers,
    }


# ─── Сводка плана для уносимых документов ───────────────────────────────────

# Имя базового сценария пишет шаг «Планирование» во фронтенде
# (`src/lib/components/pipeline/PlanningStep.svelte`, константа BASELINE_NAME) —
# это и имя файла results/scenarios/<имя>.json, и ключ манифеста. Здесь оно нужно
# только чтобы отличить план из файла клиента от вариантов «что если»; совпадения
# нет — блока сравнения просто не будет, суррогата вместо него не появится.
BASELINE_VARIANT_NAME = 'Базовый план'


def summarize_forecast(forecast: dict[str, Any] | None) -> dict[str, Any] | None:
    """Сводка шага «Планирование» для колоды и веб-отчёта — общий счётчик на оба.

    Вход — ровно то, что вернул `load_saved_forecast` (сценарии с диска). Своих
    чисел функция не заводит: всё считается из `total_kpi`, `total_kpi_ci_*`,
    `total_spend_money` тех же файлов `results/scenarios/<имя>.json`, которые
    показывает экран шага. Это и есть общий источник экрана и документа.

    Возвращает None, когда сводке неоткуда взяться (плана нет, сценариев нет).
    Отсутствующая величина остаётся None и печатается прочерком — подстановки
    правдоподобного нуля здесь нет по построению (INV-50).

    Состав:
        horizon_periods            число периодов плана (по длине меток/прогноза)
        period_first / period_last метки краёв горизонта
        accepted                   принятый вариант (★) — имя, центр, диапазон,
                                   ширина диапазона в % от центра, бюджет, ROAS
        baseline                   то же для «Базовый план», если он в сценариях
        diff_vs_baseline           отличие принятого от базового: KPI и бюджет,
                                   абсолютом и процентом
        verdict                    различимы ли лидер и ближайший преследователь
                                   по перекрытию правдоподобных диапазонов
    """
    if not forecast or forecast.get('status') != 'ok':
        return None
    scenarios: list[dict] = list(forecast.get('scenarios') or [])
    if not scenarios:
        return None

    def _num(v: Any) -> float | None:
        """float или None; ноль вместо отсутствия не подставляем (INV-50)."""
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if f != f else f  # NaN — то же отсутствие

    def _channels(sc: dict) -> list[dict[str, Any]] | None:
        """Бюджет по каналам за весь горизонт: сумма в рублях и доля.

        Отвечает на вопрос «сколько куда положить» — то, ради чего документ
        уносят со встречи. Разбивки по периодам внутри горизонта здесь нет
        намеренно (решение владельца 13.09.2026): она нужна единицам и стоит
        полстраницы.

        None, если движок не перевёл каналы в деньги — тогда строк бюджета в
        отчёте нет вовсе, а доли не считаются из натуральных единиц.
        """
        money = (sc.get('per_channel_money') or {})
        pairs = [(str(k), _num(v)) for k, v in money.items()]
        pairs = [(k, v) for k, v in pairs if v is not None]
        if not pairs:
            return None
        total = sum(v for _, v in pairs)
        out = [
            {
                'name': k,
                'spend_money': v,
                'share_pct': (v / total * 100.0) if total else None,
            }
            for k, v in pairs
        ]
        out.sort(key=lambda c: c['spend_money'], reverse=True)
        return out

    def _view(sc: dict) -> dict[str, Any]:
        kpi = _num(sc.get('total_kpi'))
        lo = _num(sc.get('total_kpi_ci_low'))
        hi = _num(sc.get('total_kpi_ci_high'))
        width_pct = None
        if lo is not None and hi is not None and kpi is not None and kpi > 0:
            width_pct = (hi - lo) / kpi * 100.0
        return {
            'name': str(sc.get('name') or sc.get('variant_id') or ''),
            'variant_id': sc.get('variant_id'),
            'total_kpi': kpi,
            'ci_low': lo,
            'ci_high': hi,
            'ci_width_pct': width_pct,
            'total_spend_money': _num(sc.get('total_spend_money')),
            'roas_money': _num(sc.get('roas_money')),
            'channels': _channels(sc),
        }

    views = [_view(sc) for sc in scenarios]

    # Горизонт — из принятого сценария, а при его отсутствии из первого: метки
    # периодов у всех вариантов одни и те же (общий медиаплан на тот же срок).
    accepted_id = forecast.get('accepted_variant')
    accepted_idx = next(
        (i for i, sc in enumerate(scenarios) if sc.get('variant_id') == accepted_id),
        None,
    )
    horizon_src = scenarios[accepted_idx] if accepted_idx is not None else scenarios[0]
    labels = [str(x) for x in (horizon_src.get('period_labels') or [])]
    preds = list(horizon_src.get('predictions') or [])
    horizon = len(labels) or len(preds) or None

    accepted = views[accepted_idx] if accepted_idx is not None else None
    baseline = next(
        (v for v in views if v['name'] == BASELINE_VARIANT_NAME
         or v['variant_id'] == BASELINE_VARIANT_NAME),
        None,
    )

    # Отличие принятого плана от базового. Формула та же, что в таблице сравнения
    # на экране (`MultiScenarioPage.svelte`, upliftPct): (вариант − база) / |база|.
    diff = None
    if accepted is not None and baseline is not None and accepted is not baseline:
        kpi_abs = kpi_pct = spend_abs = spend_pct = None
        if accepted['total_kpi'] is not None and baseline['total_kpi'] is not None:
            kpi_abs = accepted['total_kpi'] - baseline['total_kpi']
            if baseline['total_kpi'] != 0:
                kpi_pct = kpi_abs / abs(baseline['total_kpi']) * 100.0
        if accepted['total_spend_money'] is not None and baseline['total_spend_money'] is not None:
            spend_abs = accepted['total_spend_money'] - baseline['total_spend_money']
            if baseline['total_spend_money'] != 0:
                spend_pct = spend_abs / abs(baseline['total_spend_money']) * 100.0
        if kpi_abs is not None or spend_abs is not None:
            diff = {
                'baseline_name': baseline['name'],
                'kpi_abs': kpi_abs,
                'kpi_pct': kpi_pct,
                'spend_abs': spend_abs,
                'spend_pct': spend_pct,
            }

    # Различимость. Выборка и неравенства — дословно как в панели подсказок шага
    # (`src/lib/insights-rules.js`, правила P8/P9): сравнивается ОДНА пара —
    # лидер по центральной оценке и ближайший преследователь, а не все пары.
    # Ровное касание границ намеренно молчит, как и на экране.
    verdict = None
    comparable = [v for v in views
                  if v['total_kpi'] is not None and v['ci_low'] is not None and v['ci_high'] is not None]
    if len(comparable) >= 2:
        ordered = sorted(comparable, key=lambda v: v['total_kpi'], reverse=True)
        first, second = ordered[0], ordered[1]
        if first['ci_low'] < second['ci_high'] and second['ci_low'] < first['ci_high']:
            kind = 'overlap'
        elif first['ci_low'] > second['ci_high']:
            kind = 'distinct'
        else:
            kind = None
        if kind:
            verdict = {
                'kind': kind,
                'leader': first['name'],
                'leader_kpi': first['total_kpi'],
                'leader_ci_low': first['ci_low'],
                'runner_up': second['name'],
                'runner_up_kpi': second['total_kpi'],
                'runner_up_ci_high': second['ci_high'],
            }

    return {
        'horizon_periods': horizon,
        'period_first': labels[0] if labels else None,
        'period_last': labels[-1] if labels else None,
        'accepted': accepted,
        'baseline': baseline,
        'diff_vs_baseline': diff,
        'verdict': verdict,
        'scenario_count': len(views),
    }


# ─── Шаблон медиаплана ───────────────────────────────────────────────────────


def generate_media_plan_template(project_dir: str, n_future_periods: int = 12) -> dict[str, Any]:
    """Генерирует Excel-шаблон медиаплана на основе обученной модели.

    Логика:
    1. Читает models/latest.pkl → получает media_columns, kpi_column, date_column, data_file.
    2. Читает data_file через load_frames → историческая часть.
    3. Строит Excel: все исторические строки как есть + n_future_periods строк будущего:
       - даты продолжены от последней исторической с правильной гранулярностью,
       - медиа-колонки и KPI — пустые (NaN).
    4. Атомарная запись в <project_dir>/exports/media_plan_template.xlsx.
       CPD-70: если имя уже занято (шаблон уже сформирован и, возможно,
       заполнен клиентом) — файл ложится рядом со счётчиком
       ("media_plan_template (2).xlsx" и т.д.), прежний не трогается.
    5. Возвращает {'status': 'ok', 'path': '<абс. путь к файлу>', 'renamed': bool}.

    Ошибки: {'status': 'error', 'message': '...'}.
    """
    import tempfile

    import openpyxl

    base = Path(project_dir)
    model_path = base / "models" / "latest.pkl"
    if not model_path.exists():
        return {"status": "error", "message": "Модель не найдена: models/latest.pkl. Сначала обучите модель."}

    # F-AVT-3 (2026-07-10): модели Econometrica сохраняются кастомным pickle
    # (persistent_id для posterior) — голый pickle.load падает на реальных моделях.
    # Грузим через централизованный compat-хелпер (как scenario/decomposer).
    try:
        from engines.persistence import load_model_with_compat
        model_obj = load_model_with_compat(model_path)
    except Exception as e:
        return {"status": "error", "message": f"Не удалось загрузить модель: {e}"}

    # Мета-данные лежат в model_obj['config'] (реальный формат), с fallback
    # на корень dict (упрощённые тестовые pickle) и на __dict__ (объекты).
    if isinstance(model_obj, dict):
        config = model_obj.get("config") if isinstance(model_obj.get("config"), dict) else model_obj
    elif hasattr(model_obj, "__dict__"):
        config = model_obj.__dict__
    else:
        config = {}

    media_columns: list[str] = list(config.get("media_columns") or config.get("channel_columns") or [])
    kpi_column: str = str(config.get("kpi_column") or config.get("target_column") or "sales")
    date_column: str = str(config.get("date_column") or "date")
    data_file: str | None = config.get("data_file") or config.get("file_path")
    control_columns: list[str] = list(config.get("control_columns") or [])

    if not data_file or not Path(data_file).exists():
        # Пробуем найти data_file в project_dir
        for ext in ("*.xlsx", "*.xls", "*.csv"):
            candidates = list((base / "data").glob(ext)) + list(base.glob(ext))
            if candidates:
                data_file = str(candidates[0])
                break

    if not data_file or not Path(data_file).exists():
        return {"status": "error", "message": "Исходный файл данных не найден. Загрузите данные снова."}

    # F-AVT-3: config не всегда хранит date_column (обучение его не сохраняет) —
    # детектим колонку даты из файла, если дефолт 'date' в нём отсутствует.
    try:
        from engines.data_io import read_data_file
        _probe = read_data_file(data_file)
        if date_column not in _probe.columns:
            from engines.validator import detect_column_role_with_confidence as _role
            _date_cands = [c for c in _probe.columns if _role(str(c))[0] == "date"]
            # L-1 (2.5.9): календарная колонка роли «дата», как в load_frames.
            date_column = _calendar_date_column(_probe, None) or (_date_cands[0] if _date_cands else None)
    except Exception:
        date_column = None if date_column not in ("date",) else date_column

    try:
        frames = load_frames(data_file, date_col=date_column, kpi_col=kpi_column, media_cols=media_columns or None)
    except Exception as e:
        return {"status": "error", "message": f"Не удалось прочитать файл данных: {e}"}
    # Резолвим фактическую колонку даты (load_frames мог авто-детектить при None)
    if not date_column or date_column not in frames["history_df"].columns:
        _hist_cols = list(frames["history_df"].columns)
        from engines.validator import detect_column_role_with_confidence as _role2
        _dc = [c for c in _hist_cols if _role2(str(c))[0] == "date"]
        date_column = (_calendar_date_column(frames["history_df"], None)
                       or (_dc[0] if _dc else _hist_cols[0]))

    history_df: "pd.DataFrame" = frames["history_df"]
    if history_df.empty:
        return {"status": "error", "message": "Исторические данные пусты – нечего продолжать."}

    # Определяем гранулярность по истории
    from utils.forecast_validation import detect_granularity  # SSOT

    gran_result = detect_granularity(history_df[date_column])
    granularity: str = gran_result.get("granularity", "M")

    # Строим будущие даты
    # Колонка целиком – правило дня решается по всем датам (N0, 2.5.9).
    last_date = parse_dates(history_df[date_column]).dropna().iloc[-1]
    future_dates: list["pd.Timestamp"] = []
    cur = last_date
    for _ in range(n_future_periods):
        cur = _expected_next(cur, granularity)
        future_dates.append(cur)

    # Все колонки: дата + KPI + медиа + контроли
    all_cols = [date_column, kpi_column] + media_columns + [c for c in control_columns if c not in media_columns]
    # Убираем дубли, сохраняем порядок
    seen: set[str] = set()
    ordered_cols: list[str] = []
    for c in all_cols:
        if c not in seen and c in history_df.columns:
            ordered_cols.append(c)
            seen.add(c)
    # Добавляем колонки из истории, которые не попали
    for c in history_df.columns:
        if c not in seen:
            ordered_cols.append(c)
            seen.add(c)

    # Строим Excel через openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Медиаплан"

    # Заголовок
    ws.append(ordered_cols)

    # Исторические строки как есть
    for _, row in history_df[ordered_cols].iterrows():
        ws.append([
            (v.date() if isinstance(v, pd.Timestamp) else (None if pd.isna(v) else v))
            for v in row
        ])

    # Будущие строки: дата заполнена, всё остальное — пусто
    for fd in future_dates:
        future_row: list[Any] = []
        for col in ordered_cols:
            if col == date_column:
                future_row.append(fd.date())
            else:
                future_row.append(None)
        ws.append(future_row)

    # Атомарная запись
    exports_dir = base / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    # CPD-70: не затирать молча уже существующий (возможно, заполненный
    # клиентом) шаблон — при коллизии сохраняем рядом со счётчиком.
    out_path = unique_export_path(exports_dir / "media_plan_template.xlsx")
    renamed = out_path.name != "media_plan_template.xlsx"
    if renamed:
        logger.warning(
            "generate_media_plan_template: шаблон уже существует, сохраняю как %s", out_path
        )

    tmp_fd, tmp_name = tempfile.mkstemp(dir=exports_dir, prefix=".mpt_", suffix=".tmp")
    try:
        import os as _os
        _os.close(tmp_fd)
        wb.save(tmp_name)
        _os.replace(tmp_name, out_path)
    except Exception:
        try:
            import os as _os2
            _os2.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info("media_plan_template: записан %s (%d history + %d future)", out_path, len(history_df), n_future_periods)
    return {"status": "ok", "path": str(out_path), "renamed": renamed}


# ─── Подтверждение медиаплана ─────────────────────────────────────────────────


def confirm_media_plan(project_dir: str, confirmed: bool) -> dict[str, Any]:
    """Устанавливает поле 'confirmed' в results/media_plan.json.

    Аргументы:
        project_dir: абсолютный путь к папке проекта.
        confirmed: True — медиаплан подтверждён, False — отклонён/проигнорирован.

    Возвращает {'status': 'ok'} или {'status': 'error', 'message': '...'}.
    Атомарная запись через tempfile.mkstemp + os.replace.
    """
    import os as _os
    import tempfile

    mp_path = Path(project_dir) / "results" / "media_plan.json"
    if not mp_path.exists():
        return {"status": "error", "message": "media_plan.json not found"}

    try:
        with open(mp_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": f"Не удалось прочитать media_plan.json: {e}"}

    data["confirmed"] = confirmed

    mp_dir = mp_path.parent
    tmp_fd, tmp_name = tempfile.mkstemp(dir=mp_dir, prefix=".mp_confirm_", suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _os.replace(tmp_name, mp_path)
    except Exception:
        try:
            _os.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info("confirm_media_plan: confirmed=%s записан в %s", confirmed, mp_path)
    return {"status": "ok"}


# ─── Манифест прогноза-плана ──────────────────────────────────────────────────


def save_planning_manifest(
    project_dir: str,
    variant_ids: list[str],
    accepted_variant: str | None = None,
    disclaimers: list[str] | None = None,
) -> dict[str, Any]:
    """Записывает results/planning.json — манифест прогноза-плана.

    Манифест связывает сохранённые сценарии (results/scenarios/<id>.json) с
    отчётностью: PPTX/HTML/XLSX-раздел прогноза появляется только при наличии
    planning.json с непустым variant_ids (см. load_saved_forecast). Без него
    сценарии на диске есть, а раздел «не найден» — корень жалобы приёмки
    2026-07-10 (P-1: авто-прогноз базового плана пишет манифест сам).

    Аргументы:
        project_dir: абсолютный путь к папке проекта.
        variant_ids: имена сценариев (совпадают с results/scenarios/<id>.json).
        accepted_variant: выбранный вариант для витрины; по умолчанию — первый.
        disclaimers: оговорки прогноза (INV-50), показываются в отчёте.

    Возвращает {'status': 'ok', 'accepted_variant': ...} или
    {'status': 'error', 'message': '...'}. Атомарная запись (mkstemp + os.replace).
    """
    import os as _os
    import tempfile

    ids = [str(v) for v in (variant_ids or []) if v is not None and str(v) != '']
    if not ids:
        return {"status": "error", "message": "variant_ids пуст – нечего сохранять"}

    accepted = accepted_variant if accepted_variant in ids else ids[0]

    manifest = {
        "variant_ids": ids,
        "accepted_variant": accepted,
        "disclaimers": list(disclaimers or []),
    }

    results_dir = Path(project_dir) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    planning_path = results_dir / "planning.json"

    tmp_fd, tmp_name = tempfile.mkstemp(dir=results_dir, prefix=".planning_", suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        _os.replace(tmp_name, planning_path)
    except Exception:
        try:
            _os.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info(
        "save_planning_manifest: %d вариант(ов), accepted=%s → %s",
        len(ids), accepted, planning_path,
    )
    return {"status": "ok", "accepted_variant": accepted}
