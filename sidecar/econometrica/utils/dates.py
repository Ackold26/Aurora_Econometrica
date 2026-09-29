"""Единый разбор дат колонки клиентского файла (N0, выпуск 2.5.9).

Зачем
-----
Колонку даты разбирали сырым `pd.to_datetime` в полутора десятках мест, и
pandas выводил формат по первой ячейке без правила дня:
- «01.02.2021» из CSV русского Excel/1С (месячные данные) читался месяцем
  впереди – месяцы молча становились днями января, праздники, план,
  сезонность и ROI считались от них; недельный «02.01.2023, 09.01.2023…»
  ронял байес на «16.01.2023» (C-1, PLANAUDIT_259);
- «Jan-23» читался как 23 января ГОДА 1, «янв.23» не читался вовсе (C-2, N1);
- «+00:00/+03:00» в одной колонке – сырой «Mixed timezones» и HTTP 500 (N3).

Правило – на всю колонку, возвращаются ЗНАЧЕНИЯ, а не признак «дата есть»:
- объект даты (xlsx) – как есть;
- «Ч.Ч.ГГГГ» / «Ч/Ч/ГГГГ» / «Ч-Ч-ГГГГ» (год и двумя цифрами): если у
  какой-то ячейки первое число больше 12 – день впереди; если второе больше
  12 – месяц впереди; если все не больше 12 – день впереди (русский
  формат), а для «/» и «-» это неоднозначно, и проверка данных
  предупреждает (`ambiguous_day_month_example`);
- «ГГГГ-ММ-ДД», «ГГГГ/ММ/ДД», «ГГГГ.ММ.ДД» – год, месяц, день;
- «Jan-23», «янв.23», «январь 2023», «янв 2023», «16 октября 2023» – явным
  правилом «месяц словом + год», год из двух цифр – 20ГГ, без pandas;
- пояс «+03:00» снимается с сохранением местного времени ячейки (не
  перевод в UTC: полночь «+03:00» иначе уехала бы в предыдущие сутки);
- прочие строки с четырёхзначным годом («2016-09», «Dec 2023», «2023-Q1»,
  «20230115») – как их читает pandas, если год разумный (1900–2200);
- нераспознанное, числа (в том числе целиком числовая колонка – её отвергает
  `planning.numeric_date_refusal`) и пустое – NaT.
"""
from __future__ import annotations

import datetime as _dt
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

# Разумные годы: «Jan-23» у pandas – год 1, «01.2022» – тоже.
_MIN_YEAR = 1900
_MAX_YEAR = 2200

_TIME = r"(?:(?:T|\s+)(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
# Год впереди: «2023-01-15», «2023/01/15», «2023.01.15», с временем без пояса.
_YMD_RE = re.compile(r"(\d{4})([./-])(\d{1,2})\2(\d{1,2})" + _TIME)
# Год в конце: «15.01.2023», «01/15/2023», «15-01-23».
_DMY_RE = re.compile(r"(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})" + _TIME)
_YEAR_SUFFIX = r"(?:\s*г(?:ода?)?\.?)?"
# Месяц словом и год: «Jan-23», «янв.23», «январь 2023», «Dec 2023».
_MONTH_YEAR_RE = re.compile(r"([^\W\d_]{3,})\.?[\s\-./']*(\d{4}|\d{2})" + _YEAR_SUFFIX)
# День, месяц словом, год: «16 October 2023», «02-Jan-2023», «16 окт. 2023 г.».
_DAY_MONTH_YEAR_RE = re.compile(
    r"(\d{1,2})[\s\-./]*([^\W\d_]{3,})\.?[\s\-./,]*(\d{4}|\d{2})" + _YEAR_SUFFIX
)
_FOUR_DIGITS_RE = re.compile(r"\d{4}")

_MONTH_NAMES = {
    1: ("январь", "января", "january"),
    2: ("февраль", "февраля", "february"),
    3: ("март", "марта", "march"),
    4: ("апрель", "апреля", "april"),
    5: ("май", "мая", "may"),
    6: ("июнь", "июня", "june"),
    7: ("июль", "июля", "july"),
    8: ("август", "августа", "august"),
    9: ("сентябрь", "сентября", "september"),
    10: ("октябрь", "октября", "october"),
    11: ("ноябрь", "ноября", "november"),
    12: ("декабрь", "декабря", "december"),
}


def _month_number(word: str) -> int | None:
    """Номер месяца по слову: полное имя или его начало от трёх букв
    («янв», «сент», «мая», «Sept»); иначе None."""
    w = word.lower()
    if len(w) < 3:
        return None
    for month, names in _MONTH_NAMES.items():
        if any(name.startswith(w) for name in names):
            return month
    return None


def _year(text: str) -> int:
    y = int(text)
    return 2000 + y if len(text) == 2 else y


def _make(year: int, month: int, day: int, hh: Any = None, mm: Any = None,
          ss: Any = None) -> pd.Timestamp:
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        return pd.NaT
    try:
        return pd.Timestamp(year, month, day, int(hh or 0), int(mm or 0), int(ss or 0))
    except ValueError:
        return pd.NaT


def _plain(ts: Any) -> pd.Timestamp:
    """Timestamp без пояса (местное время ячейки) в разумных годах, иначе NaT."""
    if ts is None or pd.isna(ts):
        return pd.NaT
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    if not _MIN_YEAR <= ts.year <= _MAX_YEAR:
        return pd.NaT
    return ts


def _dmy_cells(strings: dict[Any, str]) -> dict[Any, re.Match]:
    return {k: m for k, s in strings.items() if (m := _DMY_RE.fullmatch(s))}


def _day_first(matches: dict[Any, re.Match]) -> bool:
    """Решение на колонку «Ч?Ч?ГГГГ»: месяц впереди – только если второе
    число где-то больше 12, а первое нигде."""
    first_big = any(int(m.group(1)) > 12 for m in matches.values())
    second_big = any(int(m.group(3)) > 12 for m in matches.values())
    return first_big or not second_big


def _parse_string(s: str, day_first: bool) -> pd.Timestamp:
    m = _DMY_RE.fullmatch(s)
    if m:
        a, b = int(m.group(1)), int(m.group(3))
        day, month = (a, b) if day_first else (b, a)
        return _make(_year(m.group(4)), month, day, m.group(5), m.group(6), m.group(7))
    m = _YMD_RE.fullmatch(s)
    if m:
        return _make(int(m.group(1)), int(m.group(3)), int(m.group(4)),
                     m.group(5), m.group(6), m.group(7))
    m = _MONTH_YEAR_RE.fullmatch(s)
    if m:
        month = _month_number(m.group(1))
        return pd.NaT if month is None else _make(_year(m.group(2)), month, 1)
    m = _DAY_MONTH_YEAR_RE.fullmatch(s)
    if m:
        month = _month_number(m.group(2))
        return pd.NaT if month is None else _make(_year(m.group(3)), month, int(m.group(1)))
    # Без четырёхзначного года pandas подставил бы год сам («23 Jan» –
    # текущий, «Jan 23» – год 1).
    if not _FOUR_DIGITS_RE.search(s):
        return pd.NaT
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _plain(pd.to_datetime(s))
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _as_series(values: Any) -> pd.Series:
    if isinstance(values, pd.Series):
        return values
    return pd.Series(values)


def _strings(series: pd.Series) -> dict[Any, str]:
    """Позиция → текст ячейки без пробелов по краям, только для строк."""
    return {i: v.strip() for i, v in enumerate(series.tolist()) if isinstance(v, str)}


def parse_dates(values: Any) -> pd.Series:
    """ЗНАЧЕНИЯ дат колонки: Series datetime64 без пояса с тем же индексом;
    нераспознанная ячейка – NaT. Правила – в описании модуля."""
    series = _as_series(values)
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz_localize(None)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    strings = _strings(series)
    day_first = _day_first(_dmy_cells(strings))
    cache: dict[str, pd.Timestamp] = {}
    out: list[Any] = []
    for pos, v in enumerate(series.tolist()):
        if pos in strings:
            s = strings[pos]
            if s not in cache:
                cache[s] = _parse_string(s, day_first)
            out.append(cache[s])
        elif isinstance(v, (_dt.date, np.datetime64)) and not pd.isna(v):
            out.append(_plain(v))
        else:
            out.append(pd.NaT)
    return pd.Series(pd.to_datetime(pd.Series(out, dtype=object), errors="coerce").to_numpy(),
                     index=series.index)


def ambiguous_day_month_example(values: Any) -> str | None:
    """Колонка «Ч/Ч/ГГГГ» или «Ч-Ч-ГГГГ», где ни одно из двух первых чисел
    не больше 12: день и месяц не различить, прочитано днём впереди. Пример
    ячейки для предупреждения проверки, иначе None. Для «.» – русский
    формат, не предупреждаем."""
    series = _as_series(values)
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return None
    matches = _dmy_cells(_strings(series))
    if not matches:
        return None
    if any(int(m.group(1)) > 12 or int(m.group(3)) > 12 for m in matches.values()):
        return None
    for m in matches.values():
        if m.group(2) in "/-" and int(m.group(1)) != int(m.group(3)):
            return m.group(0)
    return None


def unparsed_examples(values: Any, parsed: pd.Series | None = None, limit: int = 3) -> list[str]:
    """До `limit` разных непустых значений колонки, которые не разобрались в
    дату, – примеры для текста отказа."""
    series = _as_series(values)
    if parsed is None:
        parsed = parse_dates(series)
    bad = series[series.notna().to_numpy() & parsed.isna().to_numpy()]
    return list(dict.fromkeys(str(v).strip() for v in bad))[:limit]


def ru_date_words(ts: Any) -> str:
    """«1 февраля 2023» – дата словами для текстов проверки."""
    return f"{ts.day} {_MONTH_NAMES[ts.month][1]} {ts.year}"
