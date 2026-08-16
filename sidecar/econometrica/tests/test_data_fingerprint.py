"""Отпечаток исходных данных: устойчивость, чувствительность, отказы.

Что здесь стережётся
--------------------
1. Пересохранение файла НЕ меняет отпечаток содержимого, хотя байты файла и
   его полный хеш меняются. Это то самое свойство, ради которого отпечаток
   содержимого вообще заведён: хеш байтов xlsx зависит от времени записи
   (внутри ZIP лежат метки), и предъявлять его клиенту как «тот ли файл»
   значит регулярно обвинять его в подмене за то, что он открыл файл.
2. Любое изменение таблицы отпечаток меняет: ячейка, порядок столбцов,
   число строк, имя столбца.
3. Хеш файла считается по ВСЕМУ файлу, а не по первым 512 КБ: два файла,
   совпадающие в начале и в размере, обязаны различаться.
4. Отказ (файла нет, вход не таблица) даёт честный статус, а не исключение.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.data_fingerprint import (  # noqa: E402
    build_data_fingerprint,
    compute_file_digest,
    compute_frame_fingerprint,
)


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            'date': pd.date_range('2026-01-05', periods=6, freq='W'),
            'sales': [1200.5, 1310.25, 990.0, 1450.75, 1502.0, 1388.125],
            'tv': [100, 0, 250, 300, 0, 180],
            'digital': [50.5, 60.25, 70.0, np.nan, 90.5, 100.0],
            'канал ООН': ['да', 'нет', 'да', 'да', 'нет', 'да'],
        }
    )


def _repack_zip_with_other_timestamps(src: Path, dst: Path) -> None:
    """Переупаковать xlsx с другими метками времени внутри архива.

    Ровно тот механизм, которым пересохранение в Excel меняет байты файла, не
    меняя таблицу. Берём его напрямую, а не через паузу в 2,5 с (метки в ZIP
    имеют шаг 2 с): прогон не должен зависеть от часов.
    """
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(
        dst, 'w', zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=(2030, 6, 1, 12, 30, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, zin.read(item.filename))


# ---------------------------------------------------------------------------
# 1. Устойчивость к пересохранению — оба факта в одном тесте
# ---------------------------------------------------------------------------

def test_resave_keeps_content_hash_and_changes_file_hash(tmp_path):
    """Пересохранение: содержимое то же — хеш байтов другой."""
    df = _sample_frame()
    first = tmp_path / 'данные.xlsx'
    second = tmp_path / 'данные-пересохранён.xlsx'
    df.to_excel(first, index=False)
    _repack_zip_with_other_timestamps(first, second)

    # Читаем обе копии тем же способом, каким читает обучение.
    fp_first = compute_frame_fingerprint(pd.read_excel(first))
    fp_second = compute_frame_fingerprint(pd.read_excel(second))
    assert fp_first['status'] == 'ok'
    assert fp_second['status'] == 'ok'
    assert fp_first['content_sha256'] == fp_second['content_sha256'], (
        'Отпечаток содержимого обязан пережить пересохранение файла'
    )

    digest_first = compute_file_digest(first)
    digest_second = compute_file_digest(second)
    assert digest_first['status'] == 'ok'
    assert digest_second['status'] == 'ok'
    assert digest_first['file_sha256'] != digest_second['file_sha256'], (
        'Хеш байтов от пересохранения обязан измениться — иначе тест не '
        'доказывает, что устойчивость даёт именно отпечаток содержимого'
    )

    # То же самое через сборку, которая и едет в паспорт: половина «содержимое»
    # обязана остаться половиной содержимого, а не подмениться хешом байтов.
    built_first = build_data_fingerprint(pd.read_excel(first), first)
    built_second = build_data_fingerprint(pd.read_excel(second), second)
    assert (
        built_first['content']['content_sha256']
        == built_second['content']['content_sha256']
    )
    assert built_first['file']['file_sha256'] != built_second['file']['file_sha256']


def test_resave_under_other_sheet_name_keeps_content_hash(tmp_path):
    """Тот же набор данных на листе с другим именем — тот же отпечаток."""
    df = _sample_frame()
    first = tmp_path / 'a.xlsx'
    second = tmp_path / 'b.xlsx'
    df.to_excel(first, index=False, sheet_name='Sheet1')
    df.to_excel(second, index=False, sheet_name='Данные 2026')

    assert (
        compute_frame_fingerprint(pd.read_excel(first))['content_sha256']
        == compute_frame_fingerprint(pd.read_excel(second))['content_sha256']
    )
    assert (
        compute_file_digest(first)['file_sha256']
        != compute_file_digest(second)['file_sha256']
    )


def test_csv_roundtrip_keeps_content_hash(tmp_path):
    """Запись в csv и чтение обратно отпечаток содержимого не меняют."""
    df = pd.DataFrame({'sales': [1.5, 2.25, 3.0], 'tv': [10, 20, 30]})
    path = tmp_path / 'данные.csv'
    df.to_csv(path, index=False)

    assert (
        compute_frame_fingerprint(df)['content_sha256']
        == compute_frame_fingerprint(pd.read_csv(path))['content_sha256']
    )


# ---------------------------------------------------------------------------
# 2. Чувствительность
# ---------------------------------------------------------------------------

def test_single_cell_change_changes_fingerprint():
    base = _sample_frame()
    changed = base.copy()
    changed.loc[2, 'sales'] = changed.loc[2, 'sales'] + 0.01

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(changed)['content_sha256']
    )


def test_column_reorder_changes_fingerprint():
    base = _sample_frame()
    reordered = base[['sales', 'date', 'digital', 'tv', 'канал ООН']]

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(reordered)['content_sha256']
    )


def test_row_removal_changes_fingerprint():
    base = _sample_frame()
    shorter = base.iloc[:-1].reset_index(drop=True)

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(shorter)['content_sha256']
    )
    assert compute_frame_fingerprint(shorter)['n_rows'] == len(base) - 1


def test_row_reorder_changes_fingerprint():
    base = _sample_frame()
    shuffled = base.iloc[::-1].reset_index(drop=True)

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(shuffled)['content_sha256']
    )


def test_column_rename_changes_fingerprint():
    base = _sample_frame()
    renamed = base.rename(columns={'tv': 'ТВ'})

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(renamed)['content_sha256']
    )


def test_nan_appearance_changes_fingerprint():
    """Затёртая ячейка (стало пусто) обязана менять отпечаток."""
    base = _sample_frame()
    with_gap = base.copy()
    with_gap.loc[0, 'tv'] = np.nan

    assert (
        compute_frame_fingerprint(base)['content_sha256']
        != compute_frame_fingerprint(with_gap)['content_sha256']
    )


# ---------------------------------------------------------------------------
# 3. Нечувствительность к представлению — то, что и делает отпечаток
#    сравнимым между прогонами и версиями pandas
# ---------------------------------------------------------------------------

def test_int_and_float_representation_give_same_fingerprint():
    """Один и тот же ряд как int64 и как float64 — один отпечаток."""
    as_int = pd.DataFrame({'tv': pd.Series([10, 20, 30], dtype='int64')})
    as_float = pd.DataFrame({'tv': pd.Series([10.0, 20.0, 30.0], dtype='float64')})

    assert (
        compute_frame_fingerprint(as_int)['content_sha256']
        == compute_frame_fingerprint(as_float)['content_sha256']
    )


def test_all_missing_forms_are_one_token():
    """None, np.nan и pd.NA в объектном столбце — одно «пусто»."""
    a = pd.DataFrame({'x': pd.Series([None, 'да'], dtype='object')})
    b = pd.DataFrame({'x': pd.Series([np.nan, 'да'], dtype='object')})
    c = pd.DataFrame({'x': pd.Series([pd.NA, 'да'], dtype='object')})

    first = compute_frame_fingerprint(a)['content_sha256']
    assert compute_frame_fingerprint(b)['content_sha256'] == first
    assert compute_frame_fingerprint(c)['content_sha256'] == first


def test_negative_zero_equals_zero():
    a = pd.DataFrame({'x': [0.0, 1.0]})
    b = pd.DataFrame({'x': [-0.0, 1.0]})

    assert (
        compute_frame_fingerprint(a)['content_sha256']
        == compute_frame_fingerprint(b)['content_sha256']
    )


def test_algo_label_is_versioned():
    """Метка версии алгоритма присутствует и входит в форму записи."""
    result = compute_frame_fingerprint(_sample_frame())
    assert result['algo'] == 'aurora-frame-v1'
    assert len(result['content_sha256']) == 64


# ---------------------------------------------------------------------------
# 4. Хеш файла — полный, без пути, с честным отказом
# ---------------------------------------------------------------------------

def test_file_digest_is_full_file_not_prefix(tmp_path):
    """Файлы, совпадающие в первых 512 КБ и по размеру, обязаны различаться.

    Именно этим полный SHA-256 отличается от усечённого хеша планирования
    (`engines/planning.py::compute_source_hash`, 512 КБ + размер): под
    усечённым правилом оба файла ниже — «один и тот же файл».
    """
    head = b'A' * (512 * 1024)
    first = tmp_path / 'один.bin'
    second = tmp_path / 'два.bin'
    first.write_bytes(head + 'хвост-1'.encode('utf-8').ljust(64, b'\x00'))
    second.write_bytes(head + 'хвост-2'.encode('utf-8').ljust(64, b'\x00'))

    d1 = compute_file_digest(first)
    d2 = compute_file_digest(second)
    assert d1['size_bytes'] == d2['size_bytes'], 'размеры должны совпасть'
    assert d1['file_sha256'] != d2['file_sha256']


def test_file_digest_keeps_name_but_not_path(tmp_path):
    """Путь может содержать имя клиента — в документ уезжает только имя файла."""
    folder = tmp_path / 'клиент-ООО-Ромашка'
    folder.mkdir()
    path = folder / 'данные для эконометрики.xlsx'
    _sample_frame().to_excel(path, index=False)

    digest = compute_file_digest(path)
    assert digest['file_name'] == 'данные для эконометрики.xlsx'
    assert digest['file_ext'] == '.xlsx'
    joined = ' '.join(str(v) for v in digest.values())
    assert 'клиент-ООО-Ромашка' not in joined
    assert str(tmp_path) not in joined


def test_file_digest_matches_reference_sha256(tmp_path):
    """Сверка с независимой реализацией: hashlib по всему файлу."""
    import hashlib

    path = tmp_path / 'x.bin'
    payload = b'aurora' * 5000
    path.write_bytes(payload)

    assert compute_file_digest(path)['file_sha256'] == hashlib.sha256(payload).hexdigest()


def test_missing_file_gives_unavailable_status(tmp_path):
    """Файла нет — честный статус, не исключение и не молчание."""
    result = compute_file_digest(tmp_path / 'нет-такого.xlsx')
    assert result['status'] == 'unavailable'
    assert result['reason']
    assert 'file_sha256' not in result


def test_frame_fingerprint_never_raises_on_garbage():
    """Вход не таблица — статус, а не падение обучения."""
    result = compute_frame_fingerprint(object())
    assert result['status'] == 'unavailable'
    assert result['reason']


# ---------------------------------------------------------------------------
# 5. Сборка обеих половин
# ---------------------------------------------------------------------------

def test_build_data_fingerprint_has_both_halves(tmp_path):
    path = tmp_path / 'данные.xlsx'
    df = _sample_frame()
    df.to_excel(path, index=False)

    result = build_data_fingerprint(pd.read_excel(path), str(path))
    assert result['content']['status'] == 'ok'
    assert result['file']['status'] == 'ok'
    assert len(result['content']['content_sha256']) == 64
    assert len(result['file']['file_sha256']) == 64


def test_build_data_fingerprint_survives_missing_file(tmp_path):
    """Файл исчез — содержимое всё равно отпечатано, файл честно недоступен.

    Половины отказывают независимо: таблица уже в памяти, файла может не быть.
    """
    result = build_data_fingerprint(_sample_frame(), str(tmp_path / 'нет.xlsx'))
    assert result['content']['status'] == 'ok'
    assert result['file']['status'] == 'unavailable'


def test_build_data_fingerprint_never_raises():
    """Ни при каком входе наружу не летит исключение."""
    result = build_data_fingerprint(None, None)
    assert result['content']['status'] == 'unavailable'
    assert result['file']['status'] == 'unavailable'
