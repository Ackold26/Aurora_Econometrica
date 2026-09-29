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
  - кодировка: utf-16 по метке BOM (Excel «Юникод-текст»), utf-8 (с меткой
    BOM – utf-8-sig), иначе cp1251;
  - разделитель – «;», табуляция или «,» по заголовку и первым строкам
    (у всех строк образца одинаковое число полей, больше одного);
  - десятичная запятая и пробел-разделитель тысяч («1 234,56», «1234,56») –
    в числа, только если разделитель не «,» и в файле нет английского
    «1,234.56»: в файле «,» запятая в кавычках – разделитель тысяч
    английского формата, её не трогаем. Решение – по колонке: колонка с
    точкой («10.5», дата «01.2022») запятую в соседних колонках не
    выключает (M-1, AUDIT03 s56). Для табуляции (кроме cp1251) колонку, где
    после каждой запятой ровно три цифры («1,234»), не переводим – это может
    быть английский разделитель тысяч; она остаётся текстом, и проверка
    откажет громко, а не прочитает в 1000 раз меньше (M-2, AUDIT03 s56).
    Так же – при любом разделителе, если в файле есть колонка чисел с
    десятичной точкой («12.5»): соглашения смешаны, и «1,234» рядом с ней –
    скорее английские тысячи (L-5, AUDIT03 s56).
  - Колонка, где каждое значение – «ММ.ГГГГ» или «ГГГГ.ММ» (дата, которую
    Excel записал как число), остаётся текстом «01.2022», а не числом 1.2022:
    проверка и обучение отказывают по ней с понятным текстом (H-1, AUDIT03
    s56). Путь файла «,» utf-8 это не меняет.
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
# Запятая, после которой не ровно три цифры, – точно десятичная («1,5»).
_SURE_DECIMAL_COMMA_RE = re.compile(r',(?!\d{3}\s*$)\d+\s*$')
# Число с десятичной точкой или целое: «12.5», «-3», «100».
_POINT_NUMBER_RE = re.compile(r'\s*[-+−]?\d+(?:\.\d+)?\s*')
# Дата, которую Excel записал как число: «01.2022» (ММ.ГГГГ), «2022.01» (ГГГГ.ММ).
_NUMBER_LIKE_DATE_RE = re.compile(r'\s*(?:(\d{1,2})\.(\d{4})|(\d{4})\.(\d{1,2}))\s*')


def is_excel_path(path: Any) -> bool:
    return str(path).lower().endswith(_EXCEL_SUFFIXES)


def is_number_like_date(value: Any) -> bool:
    """Строка «ММ.ГГГГ» или «ГГГГ.ММ»: месяц 1–12, год 1900–2100."""
    if not isinstance(value, str):
        return False
    m = _NUMBER_LIKE_DATE_RE.fullmatch(value)
    if m is None:
        return False
    month, year = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return 1 <= int(month) <= 12 and 1900 <= int(year) <= 2100


def is_number_like_date_column(series: pd.Series) -> bool:
    """Каждое непустое значение колонки – «ММ.ГГГГ» / «ГГГГ.ММ»."""
    filled = series.dropna()
    return not filled.empty and all(is_number_like_date(v) for v in filled)


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
    """(текст, кодировка): utf-16 по метке BOM, utf-8 / utf-8-sig, иначе
    cp1251."""
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        # Excel «Юникод-текст»: метку BOM декодер снимает сам (L-1, AUDIT03 s56).
        return raw.decode('utf-16'), 'utf-16'
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


def _has_point_decimal_column(as_text: pd.DataFrame, skip: Any) -> bool:
    """В файле есть колонка чисел, где хотя бы одно записано с десятичной
    точкой («12.5»). Колонки `skip` (даты «01.2022») не в счёт."""
    for col in as_text.columns:
        if col in skip:
            continue
        filled = as_text[col].dropna()
        if (not filled.empty
                and all(_POINT_NUMBER_RE.fullmatch(v) for v in filled)
                and any('.' in v for v in filled)):
            return True
    return False


def _convert_decimal_comma(df: pd.DataFrame, need_sure_comma: bool) -> pd.DataFrame:
    """Текстовые колонки, где КАЖДОЕ непустое значение – число с десятичной
    запятой и/или пробелом-разделителем тысяч, – в числа. Колонка, где есть
    хоть один текст («н/д», «Итого», дата), остаётся как есть.

    `need_sure_comma` – колонку с запятыми переводим, только если хотя бы
    одна запятая точно десятичная (после неё не ровно три цифры): «1,234»
    иначе может оказаться английским разделителем тысяч."""
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        filled = s.dropna()
        if filled.empty or not all(isinstance(v, str) for v in filled):
            continue
        if not all(_DECIMAL_COMMA_RE.fullmatch(v) for v in filled):
            continue
        if (need_sure_comma and any(',' in v for v in filled)
                and not any(_SURE_DECIMAL_COMMA_RE.search(v) for v in filled)):
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
        # «01.2022» pandas прочитал бы числом 1.2022 – такие колонки берём
        # текстом (H-1, AUDIT03 s56).
        as_text = pd.read_csv(path, sep=sep, encoding=encoding, dtype=str)
        keep_text = {c: str for c in as_text.columns
                     if is_number_like_date_column(as_text[c])}
        df = pd.read_csv(path, sep=sep, encoding=encoding, dtype=keep_text or None)
        if sep != ',' and not _ENGLISH_THOUSANDS_RE.search(text):
            df = _convert_decimal_comma(
                df, need_sure_comma=(sep == '\t' and encoding != 'cp1251')
                or _has_point_decimal_column(as_text, keep_text),
            )
    row_map = None
    if keep_row_map:
        row_map = _row_map(text, sep, len(df))
        if row_map is None:
            logger.warning('row map of %s not built – row numbers fall back to position + 2', path.name)
            row_map = [i + 2 for i in range(len(df))]
    return df, row_map
