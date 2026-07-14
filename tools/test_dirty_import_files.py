"""C1 (2026-07-03): импорт грязных клиентских файлов — понятные сообщения, не traceback.

Зонд tmp/probe_c1_dirty_files.py прогнал 14 мутаций РЕАЛЬНОГО Kagocel через
validate_data: 0 исключений, все исходы с русским текстом (валидатор здоров —
результат прошлых волн robustness). Этот тест закрепляет инвариант на
синтетике (без зависимости от TestData) + фиксы этой волны:
- CSV русского Excel с разделителем «;» больше не читается в одну колонку;
- полностью пустой файл получает понятный ранний отказ (не «переименуйте
  столбец» на пустоте).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engines.validator import validate_data, data_preview  # noqa: E402


def _base_df(n: int = 24) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=n, freq='MS').strftime('%Y-%m-%d'),
        'TV': rng.uniform(100, 200, n).round(1),
        'Digital': rng.uniform(50, 150, n).round(1),
        'OOH': rng.uniform(10, 80, n).round(1),
        'sales': rng.uniform(1000, 2000, n).round(0),
    })


def _no_exception_and_human_text(res: dict) -> None:
    """Инвариант C1: любой исход — либо ok, либо error с русским текстом."""
    assert isinstance(res, dict)
    status = res.get('status')
    texts = [str(i.get('message', '')) for i in (res.get('issues') or [])]
    if res.get('message'):
        texts.append(str(res['message']))
    joined = ' | '.join(texts)
    assert 'Traceback' not in joined, f'Traceback протёк в сообщение: {joined[:200]}'
    if status == 'error':
        assert any(len(t) > 10 for t in texts), (
            f'error без человекочитаемого текста: keys={sorted(res.keys())}'
        )


def test_semicolon_csv_parsed_into_columns(tmp_path):
    """CSV с «;» (русский Excel по умолчанию) парсится в нормальные колонки —
    прежде читался в одну и валился в невнятное «Не найден KPI-столбец»."""
    p = tmp_path / 'semi.csv'
    _base_df().to_csv(p, index=False, sep=';')
    res = validate_data(str(p))
    _no_exception_and_human_text(res)
    cols = [c['name'] for c in (res.get('columns') or [])]
    assert 'sales' in cols and 'TV' in cols, f'Колонки не распознаны: {cols}'


def test_empty_workbook_clear_message(tmp_path):
    """Пустой xlsx → ранний понятный отказ, без советов про переименование."""
    from openpyxl import Workbook
    p = tmp_path / 'empty.xlsx'
    Workbook().save(p)
    res = validate_data(str(p))
    assert res['status'] == 'error'
    assert 'пуст' in str(res.get('message', '')), f'Ожидали понятный текст о пустом файле: {res.get("message")}'


@pytest.mark.parametrize('mutation', [
    'double_header', 'onec_export', 'dup_columns', 'kpi_holes',
    'percent_strings', 'headers_only', 'dates_text_mixed', 'single_column',
])
def test_dirty_mutations_no_exceptions(tmp_path, mutation):
    """Классы грязи из первого дня пилота: ни одна не роняет валидатор
    исключением, каждый error несёт человекочитаемый текст."""
    df = _base_df()
    p = tmp_path / f'{mutation}.xlsx'
    if mutation == 'double_header':
        top = pd.DataFrame([['МЕДИА'] * len(df.columns)], columns=df.columns)
        pd.concat([top, df], ignore_index=True).to_excel(p, index=False)
    elif mutation == 'onec_export':
        pad = pd.DataFrame([[np.nan] * len(df.columns)] * 3, columns=df.columns)
        total = pd.DataFrame([['Итого', df['TV'].sum(), df['Digital'].sum(),
                               df['OOH'].sum(), df['sales'].sum()]], columns=df.columns)
        pd.concat([pad, df, total], ignore_index=True).to_excel(p, index=False)
    elif mutation == 'dup_columns':
        d2 = df.copy()
        d2['TV2'] = df['TV']
        d2.columns = list(df.columns) + ['TV']
        d2.to_excel(p, index=False)
    elif mutation == 'kpi_holes':
        d2 = df.copy()
        d2.loc[d2.index[3:9], 'sales'] = np.nan
        d2.to_excel(p, index=False)
    elif mutation == 'percent_strings':
        d2 = df.copy()
        d2['TV'] = d2['TV'].astype(object)
        d2.loc[2:6, 'TV'] = '12,5%'
        d2.to_excel(p, index=False)
    elif mutation == 'headers_only':
        df.head(0).to_excel(p, index=False)
    elif mutation == 'dates_text_mixed':
        d2 = df.copy()
        d2.loc[2, 'date'] = '01.02.2024'
        d2.loc[5, 'date'] = '2024/03/15'
        d2.to_excel(p, index=False)
    elif mutation == 'single_column':
        df[['date']].to_excel(p, index=False)

    res = validate_data(str(p))
    _no_exception_and_human_text(res)
    prev = data_preview(str(p))
    _no_exception_and_human_text(prev)


def test_truncated_xlsx_clear_error(tmp_path):
    """Обрезанный (битый) xlsx → русская обёртка ошибки чтения, не исключение."""
    good = tmp_path / 'good.xlsx'
    _base_df().to_excel(good, index=False)
    data = good.read_bytes()
    bad = tmp_path / 'bad.xlsx'
    bad.write_bytes(data[: len(data) // 2])
    res = validate_data(str(bad))
    assert res['status'] == 'error'
    assert 'Ошибка чтения файла' in str(res.get('message', ''))


def test_cyrillic_path_with_spaces(tmp_path):
    """Файл на кириллическом пути с пробелами и тире — читается штатно."""
    d = tmp_path / 'папка клиента (тест)'
    d.mkdir()
    p = d / 'данные — копия.xlsx'
    _base_df().to_excel(p, index=False)
    res = validate_data(str(p))
    _no_exception_and_human_text(res)
    cols = [c['name'] for c in (res.get('columns') or [])]
    assert 'sales' in cols


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
