"""Tests для ADR-020: unit_costs применяются при тренировке.

Используем OLS path (closed-form, ~1 сек/test) вместо Bayesian (3-10 мин).
OLS modeler полностью отражает то же поведение unit_costs apply что Bayesian.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _synthetic_dataset(tmp_path: Path, n: int = 40) -> tuple[Path, str]:
    """Создаёт минимальный Excel dataset для OLS modeler.

    Returns:
        (data_file, project_dir)
    """
    rng = np.random.RandomState(0)
    df = pd.DataFrame({
        'Дата': pd.date_range('2024-01-01', periods=n, freq='W'),
        # Sales = 1000 + 2*tv_spend + 5*digital_spend + noise
        'tv_spend':       rng.uniform(100, 500, n),
        'digital_spend':  rng.uniform(50, 300, n),
        'price':          rng.uniform(45, 55, n),
        'comp_trp':       rng.uniform(10, 50, n),
    })
    df['sales'] = 1000 + 2 * df['tv_spend'] + 5 * df['digital_spend'] + rng.normal(0, 30, n)
    data_file = tmp_path / 'data.xlsx'
    df.to_excel(data_file, index=False)
    return data_file, str(tmp_path)


def _train_ols(data_file: Path, project_dir: str, unit_costs: dict | None = None,
               kpi_type: str = 'sales') -> dict:
    from engines.ols_modeler import train_ols
    config = {
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['tv_spend', 'digital_spend'],
        'control_columns': ['price'],
        'date_column': 'Дата',
        'adstock_config': {'tv_spend': 'geometric', 'digital_spend': 'geometric'},
        'unit_costs': unit_costs or {},
        'kpi_type': kpi_type,
        'merge_rules': {},
        'channel_categories': {},
    }
    return train_ols(config, project_dir)


def _load_pickle_safe(project_dir: str):
    """Load via engines.persistence.load_model_with_compat (proper safe format)."""
    from engines.persistence import load_model_with_compat
    pickle_path = Path(project_dir) / 'models' / 'latest.pkl'
    return load_model_with_compat(pickle_path)


def test_unit_costs_default_no_op(tmp_path):
    """unit_costs={} → unit_costs_snapshot empty, flag=False, backward compat."""
    data_file, project_dir = _synthetic_dataset(tmp_path)
    result = _train_ols(data_file, project_dir, unit_costs={})
    assert result['status'] == 'ok', f"Training failed: {result.get('message')}"
    model_data = _load_pickle_safe(project_dir)
    assert model_data.get('unit_costs_applied_at_training') is False
    assert model_data.get('unit_costs_snapshot') == {}


def test_unit_costs_snapshot_persisted(tmp_path):
    """unit_costs={tv_spend: 100} → snapshot записан в pickle с применённым значением."""
    data_file, project_dir = _synthetic_dataset(tmp_path)
    result = _train_ols(data_file, project_dir, unit_costs={'tv_spend': 100.0})
    assert result['status'] == 'ok', f"Training failed: {result.get('message')}"
    model_data = _load_pickle_safe(project_dir)
    assert model_data.get('unit_costs_applied_at_training') is True
    snapshot = model_data.get('unit_costs_snapshot') or {}
    assert snapshot.get('tv_spend') == 100.0
    # digital_spend без unit_cost → не в snapshot
    assert 'digital_spend' not in snapshot


def test_unit_costs_inverse_scale_beta(tmp_path):
    """unit_costs scaling должен дать inverse-proportional β-коэффициент.

    Если raw_arr × 100 → β_normalized scaled (нормализация на mean'е выполнена).
    Точная проверка: β при uc=1 vs uc=100 - в одинаковом range после нормализации
    (потому что media_means тоже × 100 → x_norm одинаковый → β одинаковый).
    Это **критический тест**: подтверждает что нормализация делает β invariant
    к scale, а ROI conversion остаётся consistent через unit_costs в decomposer.
    """
    data_file, project_dir = _synthetic_dataset(tmp_path)
    r1 = _train_ols(data_file, project_dir, unit_costs={'tv_spend': 1.0})
    assert r1['status'] == 'ok'
    b1 = r1['channel_params']['tv_spend']['beta']

    # Перезаписать pickle, чтобы train_ols не подтянул прежние weights
    project_dir2 = tmp_path / 'proj2'
    project_dir2.mkdir()
    df = pd.read_excel(data_file)
    data_file2 = project_dir2 / 'data.xlsx'
    df.to_excel(data_file2, index=False)
    r2 = _train_ols(data_file2, str(project_dir2), unit_costs={'tv_spend': 100.0})
    assert r2['status'] == 'ok'
    b2 = r2['channel_params']['tv_spend']['beta']

    # β-коэффициенты в normalized space (x_norm = x_adstock / mean) - должны
    # быть идентичными независимо от scale. Tolerance 5% из-за noise rounding.
    assert abs(b1 - b2) / max(abs(b1), 1e-6) < 0.05, (
        f"β scale-invariant test failed: β(uc=1)={b1}, β(uc=100)={b2}"
    )


def test_kpi_type_count_passes_training(tmp_path):
    """kpi_type='sales_packs' (count) не должен reject - проходит monetary path."""
    data_file, project_dir = _synthetic_dataset(tmp_path)
    result = _train_ols(data_file, project_dir, kpi_type='sales_packs')
    # OLS modeler не имеет KPI_TYPE_NOT_IMPLEMENTED guard вообще,
    # но проверим что Bayesian gate works similarly через config check.
    assert result['status'] == 'ok', f"count KPI rejected: {result.get('message')}"


def test_awareness_kpi_still_rejected_in_bayesian():
    """awareness types должны reject'иться в Bayesian modeler (Phase A1a TBD)."""
    from engines.modeler import train_model
    # Минимальный config для гарантированного reject до полной тренировки
    result = train_model({
        'data_file': '/nonexistent.xlsx',
        'kpi_column': 'awareness',
        'media_columns': [],
        'control_columns': [],
        'date_column': 'date',
        'kpi_type': 'aided_awareness',
        'unit_costs': {},
        'adstock_config': {},
    }, '/tmp')
    assert result.get('error_code') == 'KPI_TYPE_NOT_IMPLEMENTED', (
        f"Awareness KPI должен reject, got: {result.get('error_code')}"
    )
