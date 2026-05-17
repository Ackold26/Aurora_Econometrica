"""Tests для пилот audit 2026-05-17: validator.py должен возвращать
`available_kpi_types` set на основе classify_column результатов.

Frontend KPISelector disable'ит cards вне этого списка — юзер не может
выбрать тип leads если backend нашёл только target_monetary колонку.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


def _build_dataset(tmp_path: Path, kpi_col_name: str) -> Path:
    """Создаёт минимальный валидный dataset с конкретным KPI column name."""
    n = 30
    rng = np.random.RandomState(0)
    df = pd.DataFrame({
        'Дата': pd.date_range('2024-01-01', periods=n, freq='W'),
        kpi_col_name: rng.uniform(100, 1000, n),
        'tv_spend': rng.uniform(50, 500, n),
        'digital_spend': rng.uniform(20, 200, n),
    })
    data_file = tmp_path / 'data.xlsx'
    df.to_excel(data_file, index=False)
    return data_file


def _validate(data_file: Path) -> dict:
    from engines.validator import validate_data
    return validate_data(str(data_file))


def test_available_kpi_types_monetary_target(tmp_path):
    """KPI колонка с monetary keyword ('sales_rub') → доступны sales/revenue/profit."""
    data_file = _build_dataset(tmp_path, 'sales_rub')
    result = _validate(data_file)
    avail = result.get('available_kpi_types', [])
    assert 'sales' in avail
    assert 'revenue' in avail
    assert 'profit' in avail
    # count-types НЕ должны быть в списке если нет target_count колонки
    assert 'sales_packs' not in avail
    assert 'leads' not in avail


def test_available_kpi_types_count_target(tmp_path):
    """KPI колонка с count keyword ('sales_packs') → доступны все 7 count KPI типов.

    v2.1.0 pilot R2 (2026-05-17 B2-04): whitelist расширен до 7 типов
    (sync с decomposer.py _count_types и frontend KPISelector countOptions).
    Раньше backend whitelist'ил только 4 типа.
    """
    data_file = _build_dataset(tmp_path, 'sales_packs')
    result = _validate(data_file)
    avail = result.get('available_kpi_types', [])
    assert 'sales_packs' in avail
    assert 'leads' in avail
    assert 'registrations' in avail
    assert 'count_custom' in avail
    # B2-04: новые 3 count типа теперь whitelisted
    assert 'loyalty_cards' in avail
    assert 'subscriptions' in avail
    assert 'app_installs' in avail


def test_available_kpi_types_fallback_all(tmp_path):
    """Если backend не нашёл target_* колонок (нечитаемое имя) - все типы доступны.

    v2.1.0 pilot R2 (2026-05-17 B2-04): fallback = 7 count + 3 monetary = 10 типов.
    """
    data_file = _build_dataset(tmp_path, 'something_obscure_target')
    result = _validate(data_file)
    avail = result.get('available_kpi_types', [])
    # Fallback: все 10 типов доступны (backend не блокирует выбор)
    assert len(avail) == 10
    assert 'sales' in avail
    assert 'revenue' in avail
    assert 'profit' in avail
    assert 'leads' in avail
    assert 'loyalty_cards' in avail
    assert 'subscriptions' in avail
    assert 'app_installs' in avail
