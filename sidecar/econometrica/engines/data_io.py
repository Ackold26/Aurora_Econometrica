"""Единое чтение клиентского файла данных (s56 fix04, L-5 + L-1).

Зачем
-----
До этого модуля проверка данных читала CSV «умно» (разделитель «;»), а
обучение, декомпозиция, сценарии и остальные движки – `pd.read_csv` по
умолчанию. CSV русского Excel («;», десятичная запятая, cp1251) проверка
пропускала, а обучение падало с «KPI column not found» (зонд CSVPROBE_s56).
Теперь все, кто читает `data_file` клиента, читают его одним способом –
`read_data_file`.

Что делает
----------
- xlsx / xls / xlsm – `pd.read_excel`, как было.
- Остальное – как CSV:
  - кодировка: utf-8 (с меткой BOM – utf-8-sig), иначе cp1251;
  - разделитель – «;», табуляция или «,» по заголовку и первым строкам
    (у всех строк образца одинаковое число полей, больше одного);
  - десятичная запятая и пробел-разделитель тысяч («1 234,56», «1234,56») –
    в числа, только если разделитель не «,» и в файле нет чисел с десятичной
    точкой: в файле «,» запятая в кавычках – разделитель тысяч английского
    формата, её не трогаем.
  - Файл с «,» читается ровно `pd.read_csv(path)` – таблица и её отпечаток
    (`utils/data_fingerprint`) не меняются.
- Карта строк (`keep_row_map=True`): для каждой строки таблицы – номер строки
  файла, как его видит клиент в Excel (заголовок – строка 1). pandas
  пропускает пустые строки CSV, и номер «позиция + 2» в отказах уезжал вверх
  (аудит s56, H3: 22 при реальной 24).
"""
from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_EXCEL_SUFFIXES = ('.xlsx', '.xls', '.xlsm')
_SEPARATORS = (';', '\t', ',')
# Сколько записей файла смотреть при выборе разделителя.
_SNIFF_RECORDS = 30
# Доля строк образца с тем же числом полей, что у заголовка.
_SNIFF_CONSISTENT = 0.8

# Число с десятичной запятой и/или пробелом-разделителем тысяч.
_DECIMAL_COMMA_RE = re.compile(
    r'\s*[-+−]?(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:,\d+)?\s*'
)
# Английский формат: «1,234.56» – запятая здесь разделитель тысяч.
_ENGLISH_THOUSANDS_RE = re.compile(r'\d{1,3}(?:,\d{3})+\.\d+')


def is_excel_path(path: Any) -> bool:
    return str(path).lower().endswith(_EXCEL_SUFFIXES)


def read_data_file(
    path: Any,
    *,
    keep_row_map: bool = False,
    sheet_name: Any = None,
) -> Any:
    """Прочитать клиентский файл данных.

    Возвращает таблицу, а при `keep_row_map=True` – пару (таблица, карта
    строк): список номеров строк файла по позициям таблицы. Для xlsx карта –
    «позиция + 2», как и раньше. Если карту CSV собрать не удалось (число
    записей не сошлось с таблицей), тоже «позиция + 2».
    """
    p = Path(path)
    if is_excel_path(p):
        df = pd.read_excel(p, sheet_name=sheet_name) if sheet_name else pd.read_excel(p)
        row_map = [i + 2 for i in range(len(df))]
    else:
        df, row_map = _read_csv(p, keep_row_map)
    if keep_row_map:
        return df, row_map
    return df


def _decode(raw: bytes) -> tuple[str, str]:
    """(текст, кодировка): utf-8 / utf-8-sig, иначе cp1251."""
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp1251', errors='replace'), 'cp1251'
    if text.startswith('﻿'):
        return text[1:], 'utf-8-sig'
    return text, 'utf-8'


def _is_blank_record(rec: list[str]) -> bool:
    """Запись, которую pandas пропускает как пустую строку: без полей или
    одно поле из пробелов."""
    return not rec or (len(rec) == 1 and not rec[0].strip())


def _detect_separator(text: str) -> str:
    """Разделитель по заголовку и первым строкам; не распознан – «,», как у
    `pd.read_csv` по умолчанию."""
    best: tuple[int, int] | None = None
    best_sep = ','
    for order, sep in enumerate(_SEPARATORS):
        try:
            records = []
            for rec in csv.reader(io.StringIO(text), delimiter=sep):
                if _is_blank_record(rec):
                    continue
                records.append(rec)
                if len(records) >= _SNIFF_RECORDS:
                    break
        except csv.Error:
            continue
        if not records:
            continue
        n_header = len(records[0])
        if n_header < 2:
            continue
        data = records[1:]
        if data:
            same = sum(1 for r in data if len(r) == n_header)
            if same < _SNIFF_CONSISTENT * len(data):
                continue
        # Больше полей – лучше; при равенстве – порядок _SEPARATORS.
        key = (n_header, -order)
        if best is None or key > best:
            best, best_sep = key, sep
    return best_sep


def _row_map(text: str, sep: str, n_rows: int) -> list[int] | None:
    """Номер строки файла (как в Excel) для каждой строки таблицы.

    Запись CSV – строка Excel (поле в кавычках с переносом – одна строка).
    Пустые записи pandas пропускает, в том числе перед заголовком; номер
    строки при этом считается.
    """
    rows: list[int] = []
    header_seen = False
    try:
        for num, rec in enumerate(csv.reader(io.StringIO(text), delimiter=sep), start=1):
            if _is_blank_record(rec):
                continue
            if not header_seen:
                header_seen = True
                continue
            rows.append(num)
    except csv.Error:
        return None
    if len(rows) != n_rows:
        return None
    return rows


def _uses_decimal_point(df: pd.DataFrame, text: str) -> bool:
    """В файле есть числа с десятичной точкой: дробные числовые колонки,
    прочитанные pandas, или «1,234.56» в тексте."""
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_float_dtype(s):
            vals = s.dropna()
            if len(vals) and bool((vals != vals.round()).any()):
                return True
    return bool(_ENGLISH_THOUSANDS_RE.search(text))


def _convert_decimal_comma(df: pd.DataFrame) -> pd.DataFrame:
    """Текстовые колонки, где КАЖДОЕ непустое значение – число с десятичной
    запятой и/или пробелом-разделителем тысяч, – в числа. Колонка, где есть
    хоть один текст («н/д», «Итого», дата), остаётся как есть."""
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        filled = s.dropna()
        if filled.empty or not all(isinstance(v, str) for v in filled):
            continue
        if not all(_DECIMAL_COMMA_RE.fullmatch(v) for v in filled):
            continue
        cleaned = (
            s.astype(object)
            .where(s.notna(), None)
            .map(lambda v: None if v is None else
                 re.sub(r'[\s  ]', '', v).replace('−', '-').replace(',', '.'))
        )
        df[col] = pd.to_numeric(cleaned, errors='coerce')
    return df


def _read_csv(path: Path, keep_row_map: bool) -> tuple[pd.DataFrame, list[int] | None]:
    raw = path.read_bytes()
    text, encoding = _decode(raw)
    sep = _detect_separator(text)
    if sep == ',' and encoding == 'utf-8':
        # Обычный CSV – ровно тот путь, которым его читали всегда.
        df = pd.read_csv(path)
    else:
        df = pd.read_csv(path, sep=sep, encoding=encoding)
        if sep != ',' and not _uses_decimal_point(df, text):
            df = _convert_decimal_comma(df)
    row_map = None
    if keep_row_map:
        row_map = _row_map(text, sep, len(df))
        if row_map is None:
            logger.warning('row map of %s not built – row numbers fall back to position + 2', path.name)
            row_map = [i + 2 for i in range(len(df))]
    return df, row_map
