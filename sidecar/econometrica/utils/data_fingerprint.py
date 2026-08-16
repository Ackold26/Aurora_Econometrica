"""Aurora Econometrica — отпечаток исходных данных (воспроизводимость).

Зачем
-----
Посторонний аналитик, получив наш документ, обязан суметь ответить на вопрос
«те ли это данные, на которых обучалась модель». Ответ должен быть двойным:

1. **Отпечаток содержимого** (``compute_frame_fingerprint``) — хеш таблицы как
   набора значений. Устойчив к пересохранению файла: клиент открыл xlsx,
   ничего не менял, сохранил — отпечаток содержимого тот же.
2. **Отпечаток файла** (``compute_file_digest``) — полный SHA-256 байтов.
   Строгое равенство «это ровно тот файл», которое пересохранение ломает
   законно.

Почему нельзя обойтись хешом байтов
-----------------------------------
xlsx — это ZIP, внутри которого лежат временные метки записи. Два
пересохранения одной и той же таблицы подряд дают два разных архива и два
разных хеша байтов (проверено зондом). Предъявлять такой хеш клиенту как
«тот ли файл» — значит регулярно обвинять его в подмене данных за то, что он
открыл файл в Excel.

Почему нельзя обойтись отпечатком содержимого
---------------------------------------------
Отпечаток содержимого намеренно не видит того, что не попало в таблицу:
других листов книги, форматирования, скрытых столбцов, самого имени файла.
Для вопроса «тот ли файл целиком» нужен хеш байтов.

Почему полный SHA-256, а не первые 512 КБ
------------------------------------------
Усечённый хеш дешевле, но не отвечает на заданный вопрос: два файла,
совпадающие в первых 512 КБ и в размере, дают один хеш. Замер снял и повод
экономить: полный SHA-256 файла на 50 МБ — 36 мс.

Почему имя ``source_hash`` не используется
------------------------------------------
Имя занято планированием (``engines/planning.py``) с ИНОЙ механикой (512 КБ +
размер). Два разных ответа на вопрос «тот ли файл» под одним именем — прямой
путь к тому, что читатель документа сверит не то с тем.

Версия алгоритма
----------------
``FRAME_ALGO`` входит в хешируемые байты. Смена правил канонизации обязана
менять и метку: старые документы остаются проверяемыми по своей версии, а не
молча начинают «не сходиться».
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

# Метка алгоритма канонизации таблицы. Входит в хеш.
FRAME_ALGO = 'aurora-frame-v1'

# Метка алгоритма хеширования файла.
FILE_ALGO = 'sha256-full-file'

# Значащих цифр в текстовом представлении числа. Двенадцать — заведомо больше
# точности любых медийных данных (расходы, TRP, продажи) и заведомо меньше
# 17 значащих цифр float64, на последних из которых и расходятся версии
# pandas / openpyxl при записи и чтении.
NUM_SIGNIFICANT_DIGITS = 12

# Каноническое представление пропуска. Единое для float('nan'), None, pd.NA и
# pd.NaT: в документе «пусто» — одно понятие, а не четыре.
_NA_TOKEN = '\x00NA'

# Разделители внутри хешируемого потока. Управляющие символы взяты намеренно:
# в ячейке таблицы они практически не встречаются, поэтому склейка
# «значение + разделитель» не даёт двусмысленности.
_CELL_SEP = b'\x1f'
_FIELD_SEP = b'\x1e'

# Размер блока чтения файла. 1 МБ — компромисс между числом системных вызовов
# и пиковой памятью.
_FILE_CHUNK_BYTES = 1024 * 1024


def _canon_scalar(value: Any) -> str:
    """Каноническое текстовое представление одной ячейки.

    Правила:
        * пропуск (NaN / None / NaT / pd.NA) → единый токен;
        * логическое → ``TRUE`` / ``FALSE`` (отдельно от чисел: в Excel это
          отдельный тип, и превращать его в 1/0 значило бы потерять различие);
        * число → фиксированное число значащих цифр, ноль без знака;
        * дата-время → ISO-8601;
        * прочее → ``str``.
    """
    # Порядок проверок важен: bool — подкласс int, дата-время у pandas
    # отвечает True на проверку пропуска только будучи NaT.
    if value is None:
        return _NA_TOKEN

    # Скаляр numpy разворачиваем в родной тип Python: np.float64 наследует
    # float и прошёл бы сам, а np.int64 и np.bool_ — нет, и ушли бы в ветку
    # str, где логическое дало бы 'True' вместо 'TRUE'. Дата-время numpy
    # оставляем как есть: её ``item()`` для наносекунд отдаёт целое число.
    try:
        import numpy as np

        if isinstance(value, np.generic) and not isinstance(
            value, (np.datetime64, np.timedelta64)
        ):
            value = value.item()
    except ImportError:  # pragma: no cover — numpy есть всегда, где есть pandas
        pass

    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'

    # Пропуск. pandas.isna на массиве возвращает массив — поэтому только для
    # скаляров, а список/массив в ячейке уходит в ветку str ниже.
    try:
        import pandas as pd

        if not isinstance(value, (list, tuple, set, dict)) and pd.isna(value):
            return _NA_TOKEN
    except (TypeError, ValueError):
        pass  # объект, для которого понятие пропуска не определено

    if isinstance(value, (int,)):
        return str(int(value))
    if isinstance(value, float):
        if math.isnan(value):
            return _NA_TOKEN
        if math.isinf(value):
            return 'inf' if value > 0 else '-inf'
        if value == 0:
            return '0'  # снимает различие 0.0 / -0.0
        return f'{value:.{NUM_SIGNIFICANT_DIGITS}g}'

    isoformat = getattr(value, 'isoformat', None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except Exception:  # noqa: BLE001 — экзотический тип, падать не за что
            return str(value)

    # numpy-скаляры (np.float64, np.int64) сюда не доходят: они наследуют
    # float / int. Всё прочее — как есть.
    text = str(value)
    if text in ('nan', 'NaN', 'NaT', '<NA>'):
        return _NA_TOKEN
    return text


def _column_digest(values: Any) -> str:
    """SHA-256 канонизированных значений одного столбца, в порядке строк."""
    h = hashlib.sha256()
    for value in values:
        h.update(_canon_scalar(value).encode('utf-8'))
        h.update(_CELL_SEP)
    return h.hexdigest()


def compute_frame_fingerprint(df: Any) -> dict[str, Any]:
    """Канонический отпечаток СОДЕРЖИМОГО таблицы.

    Чувствителен к: значению любой ячейки, имени столбца, порядку столбцов,
    порядку и числу строк.

    Не чувствителен к: представлению числа (int / float / версия pandas),
    способу записи пропуска, пересохранению файла, имени и пути файла.

    Args:
        df: pandas.DataFrame. Тип не аннотирован жёстко, чтобы модуль
            импортировался без pandas — он нужен только внутри.

    Returns:
        Словарь со статусом. При успехе::

            {'status': 'ok', 'algo': 'aurora-frame-v1',
             'content_sha256': <64 hex>, 'n_rows': int, 'n_cols': int,
             'columns': [имена столбцов в порядке таблицы]}

        При неудаче — ``{'status': 'unavailable', 'reason': ...}``.
        Исключение наружу не выпускается: отпечаток — свидетельство, а не
        условие расчёта, и его отсутствие не повод рушить обучение.
    """
    try:
        columns = [str(c) for c in df.columns]
        n_rows = int(len(df.index))
        n_cols = len(columns)

        h = hashlib.sha256()
        h.update(FRAME_ALGO.encode('utf-8'))
        h.update(_FIELD_SEP)
        h.update(f'rows={n_rows};cols={n_cols}'.encode('utf-8'))
        h.update(_FIELD_SEP)
        for index, name in enumerate(columns):
            # Чувствительность к перестановке столбцов даёт сам порядок обхода:
            # столбцы уходят в хеш в порядке таблицы, и перестановка меняет
            # поток. Номер позиции добавлен вторым слоем — проверено мутацией:
            # без него свойство сохраняется, то есть он избыточен и держится
            # только как страховка от будущей канонизации порядка.
            h.update(str(index).encode('utf-8'))
            h.update(_FIELD_SEP)
            h.update(name.encode('utf-8'))
            h.update(_FIELD_SEP)
            h.update(_column_digest(df.iloc[:, index].tolist()).encode('utf-8'))
            h.update(_FIELD_SEP)

        return {
            'status': 'ok',
            'algo': FRAME_ALGO,
            'content_sha256': h.hexdigest(),
            'n_rows': n_rows,
            'n_cols': n_cols,
            'columns': columns,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'Отпечаток содержимого таблицы не снят: {exc}')
        return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}


def compute_file_digest(path: Any) -> dict[str, Any]:
    """Полный SHA-256 файла, его размер и имя.

    Путь НЕ сохраняется целиком намеренно: он часто содержит имя клиента, а
    документ воспроизводимости уезжает за пределы проекта. Имя файла (без
    каталогов) оставлено — оно нужно, чтобы посторонний нашёл, что искать.

    Args:
        path: путь к файлу исходных данных.

    Returns:
        При успехе::

            {'status': 'ok', 'algo': 'sha256-full-file',
             'file_sha256': <64 hex>, 'size_bytes': int,
             'file_name': 'данные.xlsx', 'file_ext': '.xlsx'}

        При неудаче (файла нет, нет прав, чтение оборвалось) —
        ``{'status': 'unavailable', 'reason': ...}``.
    """
    try:
        file_path = os.fspath(path)
        size_bytes = int(os.path.getsize(file_path))
        base_name = os.path.basename(file_path)
        _, ext = os.path.splitext(base_name)

        h = hashlib.sha256()
        with open(file_path, 'rb') as fh:
            while True:
                chunk = fh.read(_FILE_CHUNK_BYTES)
                if not chunk:
                    break
                h.update(chunk)

        return {
            'status': 'ok',
            'algo': FILE_ALGO,
            'file_sha256': h.hexdigest(),
            'size_bytes': size_bytes,
            'file_name': base_name,
            'file_ext': ext.lower(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'Отпечаток файла исходных данных не снят: {exc}')
        return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}


def build_data_fingerprint(df: Any, data_file: Any) -> dict[str, Any]:
    """Обе половины отпечатка одним вызовом — то, что едет в паспорт.

    Собрано отдельной функцией, а не двумя вызовами на месте, чтобы форма
    поля ``data_fingerprint`` задавалась в одном месте: читатель документа
    и обучение обязаны понимать её одинаково.

    Не бросает исключений ни при каких входных данных.

    Returns:
        ``{'content': <compute_frame_fingerprint>, 'file': <compute_file_digest>}``
        — у каждой половины свой статус, потому что они отказывают
        независимо (файл могли удалить, таблица при этом в памяти есть).
    """
    try:
        content = compute_frame_fingerprint(df)
    except Exception as exc:  # noqa: BLE001 — двойная защита: наружу не течёт
        content = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}
    try:
        file_part = compute_file_digest(data_file)
    except Exception as exc:  # noqa: BLE001
        file_part = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}
    return {'content': content, 'file': file_part}
