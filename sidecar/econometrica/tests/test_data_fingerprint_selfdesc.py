"""Сторож самоописания алгоритма отпечатка таблицы (`aurora-frame-v1`).

Зачем файл: отпечаток без описания правил непроверяем. Посторонний аналитик,
получив документ, не может пересчитать хеш своей таблицы – значит поле,
поставленное как главный контроль подготовки данных, не работает вовсе
(находка приёмки опытом 2026-08-16, раздел «где поле есть, а пользы нет»).

Что доказывается:
    1. описание порождается модулем и подставляет его фактические константы;
    2. по этому описанию – и ТОЛЬКО по нему – пишется независимая реализация,
       которая даёт тот же хеш, что `compute_frame_fingerprint`. Это и есть
       проверка описания на полноту: недосказанное правило разведёт хеши;
    3. независимая реализация ловит те же изменения таблицы, что и наша
       (значение, имя столбца, порядок строк и столбцов).

🔴 Независимая реализация ниже написана по тексту описания и намеренно НЕ
вызывает ничего из `utils.data_fingerprint`, кроме самого описания: иначе она
проверяла бы код против самого себя.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.data_fingerprint import (  # noqa: E402
    compute_frame_fingerprint,
    describe_frame_algorithm,
)


# ─────────────────────────────────────────────────────────────────────
# Независимая реализация по описанию
# ─────────────────────────────────────────────────────────────────────

def _чужая_ячейка(значение, значащих_цифр: int, токен_пропуска: bytes) -> bytes:
    """Каноническое представление ячейки по тексту описания."""
    if значение is None:
        return токен_пропуска
    if isinstance(значение, bool):
        return b'TRUE' if значение else b'FALSE'
    # Скаляр numpy разворачивается в родной тип Python – так сказано в описании.
    item = getattr(значение, 'item', None)
    if callable(item) and type(значение).__module__ == 'numpy' and not hasattr(значение, 'isoformat'):
        значение = значение.item()
        if isinstance(значение, bool):
            return b'TRUE' if значение else b'FALSE'
    if isinstance(значение, int):
        return str(int(значение)).encode('utf-8')
    if isinstance(значение, float):
        if math.isnan(значение):
            return токен_пропуска
        if math.isinf(значение):
            return b'inf' if значение > 0 else b'-inf'
        if значение == 0:
            return b'0'
        return f'{значение:.{значащих_цифр}g}'.encode('utf-8')
    isoformat = getattr(значение, 'isoformat', None)
    if callable(isoformat):
        if значение is pd.NaT:
            return токен_пропуска
        return str(isoformat()).encode('utf-8')
    текст = str(значение)
    if текст in ('nan', 'NaN', 'NaT', '<NA>'):
        return токен_пропуска
    return текст.encode('utf-8')


def чужой_отпечаток(df: pd.DataFrame, правила: dict) -> str:
    """Отпечаток таблицы, посчитанный по описанию, без нашего кода."""
    константы = правила['constants']
    значащих = int(константы['significant_digits'])
    ячейка_раздел = bytes([int(константы['cell_separator_hex'], 16)])
    поле_раздел = bytes([int(константы['field_separator_hex'], 16)])
    токен_пропуска = bytes(int(б, 16) for б in константы['na_token_bytes_hex'].split())
    метка = константы['algo_label'].encode('utf-8')

    столбцы = [str(c) for c in df.columns]
    общий = hashlib.sha256()
    общий.update(метка)
    общий.update(поле_раздел)
    общий.update(f'rows={len(df.index)};cols={len(столбцы)}'.encode('utf-8'))
    общий.update(поле_раздел)
    for номер, имя in enumerate(столбцы):
        столбец = hashlib.sha256()
        for значение in df.iloc[:, номер].tolist():
            столбец.update(_чужая_ячейка(значение, значащих, токен_пропуска))
            столбец.update(ячейка_раздел)
        общий.update(str(номер).encode('utf-8'))
        общий.update(поле_раздел)
        общий.update(имя.encode('utf-8'))
        общий.update(поле_раздел)
        общий.update(столбец.hexdigest().encode('ascii'))
        общий.update(поле_раздел)
    return общий.hexdigest()


# ─────────────────────────────────────────────────────────────────────
# Таблицы для проверки
# ─────────────────────────────────────────────────────────────────────

def _таблица_разнотипная() -> pd.DataFrame:
    return pd.DataFrame({
        'Date': pd.to_datetime(['2023-01-31', '2023-02-28', '2023-03-31', '2023-04-30']),
        'Продажи в руб. бренд': [1234567.89, 2345678.0, float('nan'), 4456789.125],
        'Кол-во запросов': [100, 200, 300, 400],
        'Banners Бюджет \nДО НДС до АК': [0.0, -0.0, 1e-7, 12345678901234.5],
        'Флаг': [True, False, True, False],
        'Заметка': ['да', '', 'NaT', None],
    })


def test_описание_подставляет_фактические_константы():
    """Описание порождается модулем, а не написано рядом отдельным текстом."""
    from utils import data_fingerprint as модуль

    правила = describe_frame_algorithm()
    константы = правила['constants']
    assert константы['algo_label'] == модуль.FRAME_ALGO
    assert константы['significant_digits'] == модуль.NUM_SIGNIFICANT_DIGITS
    assert int(константы['cell_separator_hex'], 16) == модуль._CELL_SEP[0]
    assert int(константы['field_separator_hex'], 16) == модуль._FIELD_SEP[0]
    assert bytes(int(б, 16) for б in константы['na_token_bytes_hex'].split()) == \
        модуль._NA_TOKEN.encode('utf-8')
    # Правила должны быть перечислимыми шагами, а не одной фразой «см. код».
    assert len(правила['cell_canonical_form']) >= 5
    assert len(правила['frame_digest']) >= 4


def test_чужая_реализация_по_описанию_даёт_тот_же_хеш():
    """Главное доказательство: описание достаточно для независимого пересчёта."""
    таблица = _таблица_разнотипная()
    наш = compute_frame_fingerprint(таблица)
    assert наш['status'] == 'ok'
    assert чужой_отпечаток(таблица, describe_frame_algorithm()) == наш['content_sha256']


@pytest.mark.parametrize('правка', ['значение', 'имя_столбца', 'порядок_строк', 'порядок_столбцов'])
def test_чужая_реализация_ловит_те_же_изменения(правка):
    """Описанные свойства чувствительности выполняются и у чужой реализации."""
    правила = describe_frame_algorithm()
    исходная = _таблица_разнотипная()
    изменённая = исходная.copy()
    if правка == 'значение':
        изменённая.loc[0, 'Кол-во запросов'] = 101
    elif правка == 'имя_столбца':
        изменённая = изменённая.rename(columns={'Флаг': 'флаг'})
    elif правка == 'порядок_строк':
        изменённая = изменённая.iloc[::-1].reset_index(drop=True)
    else:
        изменённая = изменённая[list(изменённая.columns)[::-1]]

    assert чужой_отпечаток(исходная, правила) != чужой_отпечаток(изменённая, правила)
    assert чужой_отпечаток(изменённая, правила) == compute_frame_fingerprint(изменённая)['content_sha256']


def test_пересохранение_и_тип_числа_отпечаток_не_меняют(tmp_path):
    """Описанная нечувствительность – тоже проверяемое свойство, не обещание."""
    правила = describe_frame_algorithm()
    таблица = pd.DataFrame({'a': [1, 2, 3], 'b': [1.5, 2.5, 3.5]})
    как_дробные = pd.DataFrame({'a': [1.0, 2.0, 3.0], 'b': [1.5, 2.5, 3.5]})
    assert чужой_отпечаток(таблица, правила) == чужой_отпечаток(как_дробные, правила)

    путь = tmp_path / 'таблица.csv'
    таблица.to_csv(путь, index=False)
    прочитанная = pd.read_csv(путь)
    assert чужой_отпечаток(прочитанная, правила) == compute_frame_fingerprint(таблица)['content_sha256']
