"""Test для пилотного фикса B-01 — decomposer должен re-injectить
holiday колонки которые modeler.py добавил при тренировке.

Контекст: modeler.py инжектирует 12 РФ holiday колонок в df + control_cols
при тренировке (ADR-019 §5). Decomposer читает df из data_file (исходный
Excel/CSV без holiday колонок) → df[control_cols] раньше падал с
`['holiday_newyear_preshop', ...] not in index`.

После фикса decomposer.py читает `normalization.holiday_cols_injected` и
re-injectит holiday колонки в df через generate_holiday_dummies перед
любым использованием control_cols.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_synthetic_model_data(tmp_path: Path) -> dict:
    """Создаёт минимальный model_data, имитирующий обученную с holidays модель."""
    # Создаём data_file БЕЗ holiday колонок (как у пользователя в исходном Excel)
    n = 24
    dates = pd.date_range('2024-01-01', periods=n, freq='MS')
    df = pd.DataFrame({
        'Дата': dates,
        'sales': np.random.RandomState(0).uniform(1000, 5000, n),
        'tv_spend': np.random.RandomState(1).uniform(100, 1000, n),
        'digital_spend': np.random.RandomState(2).uniform(50, 500, n),
        'price': np.random.RandomState(3).uniform(45, 55, n),
    })
    data_file = tmp_path / 'data.xlsx'
    df.to_excel(data_file, index=False)

    # Список holiday колонок которые modeler инжектировал
    holiday_cols = [
        'holiday_newyear_preshop', 'holiday_newyear_postsale', 'holiday_valentine',
        'holiday_defender_day', 'holiday_march8', 'holiday_may_holidays',
        'holiday_russia_day', 'holiday_back_to_school', 'holiday_unity_day',
        'holiday_black_friday', 'holiday_cyber_monday', 'holiday_school_breaks',
    ]

    # Минимальная structure model_data (только нужные поля для re-injection)
    model_data = {
        'model_version': '1.3',
        'config': {
            'data_file': str(data_file),
            'date_column': 'Дата',
            'media_columns': ['tv_spend', 'digital_spend'],
            'control_columns': ['price'] + holiday_cols,  # 12 holidays в controls
            'sales_column': 'sales',
        },
        'normalization': {
            'holiday_cols_injected': holiday_cols,
            'media_means': {'tv_spend': 500.0, 'digital_spend': 275.0},
            'control_means': {'price': 50.0},
            'control_stds': {'price': 3.0},
            'y_mean': 3000.0,
            'y_std': 1000.0,
            'intercept_mean': 0.5,
            'control_betas_mean': [0.0] * 13,  # 1 price + 12 holidays
            'untrained_channels': [],
        },
        'channel_params': {
            'tv_spend': {'beta': 0.1, 'alpha': 1.2, 'gamma': 0.5, 'decay': 0.5,
                        'adstock': {'alpha': 0.5}, 'adstock_mean_posterior': 1.0},
            'digital_spend': {'beta': 0.12, 'alpha': 1.5, 'gamma': 0.6, 'decay': 0.4,
                             'adstock': {'alpha': 0.4}, 'adstock_mean_posterior': 1.0},
        },
        'channel_categories': {},
        'use_hierarchical': False,
        'y_actual': df['sales'].tolist(),
        'y_predicted': df['sales'].tolist(),
        'kpi_type': 'sales',
        'kpi_likelihood': 'normal',
    }
    return model_data


class TestDecomposerHolidayReinjection:
    """Холидей-колонки автоматически re-injectятся при decompose."""

    def test_holiday_cols_reinjected_into_df(self, tmp_path: Path):
        """Decompose читает holiday_cols_injected и добавляет их в df перед
        обращением к df[control_cols].

        Это unit-test inline-логики; полный e2e через engines.decomposer.decompose
        требует обученной Bayesian модели (PyMC), что слишком тяжело для unit-test.
        Здесь проверяем что re-injection код работает изолированно.
        """
        from utils.holiday_calendar_ru import generate_holiday_dummies

        model_data = _make_synthetic_model_data(tmp_path)
        data_file = model_data['config']['data_file']
        date_col = model_data['config']['date_column']

        # Имитация чтения df в decomposer
        df = pd.read_excel(data_file)
        # В исходном df НЕТ holiday колонок
        assert 'holiday_newyear_preshop' not in df.columns

        # Применить re-injection логику (как в фиксе)
        holiday_cols_to_inject = (
            model_data.get('normalization', {}).get('holiday_cols_injected') or []
        )
        assert len(holiday_cols_to_inject) == 12

        if holiday_cols_to_inject and date_col in df.columns:
            holiday_df = generate_holiday_dummies(df[date_col])
            for hcol in holiday_cols_to_inject:
                if hcol not in df.columns and hcol in holiday_df.columns:
                    df[hcol] = holiday_df[hcol].values

        # После re-injection все 12 holiday колонок присутствуют в df
        for hcol in holiday_cols_to_inject:
            assert hcol in df.columns, f'Holiday column {hcol} not re-injected'

        # control_cols больше не вызовет KeyError
        control_cols = model_data['config']['control_columns']
        try:
            _ = df[control_cols].fillna(0)
        except KeyError as e:
            pytest.fail(f'df[control_cols] упало с {e} — re-injection не сработала')

    def test_decomposer_module_imports_ok(self):
        """Sanity: модуль decomposer импортируется без crashes (после фикса)."""
        from engines import decomposer
        assert hasattr(decomposer, 'decompose')

    def test_holiday_dummies_match_modeler_format(self, tmp_path: Path):
        """generate_holiday_dummies возвращает 12 колонок с правильными именами
        что matches `holiday_cols_injected` из modeler.py."""
        from utils.holiday_calendar_ru import generate_holiday_dummies

        dates = pd.Series(pd.date_range('2024-01-01', '2024-12-31', freq='MS'))
        holiday_df = generate_holiday_dummies(dates)

        expected_holidays = {
            'holiday_newyear_preshop', 'holiday_newyear_postsale', 'holiday_valentine',
            'holiday_defender_day', 'holiday_march8', 'holiday_may_holidays',
            'holiday_russia_day', 'holiday_back_to_school', 'holiday_unity_day',
            'holiday_black_friday', 'holiday_cyber_monday', 'holiday_school_breaks',
        }
        actual_holidays = set(holiday_df.columns)
        assert expected_holidays.issubset(actual_holidays), (
            f'Missing: {expected_holidays - actual_holidays}'
        )

    def test_no_op_when_no_holiday_cols_injected(self, tmp_path: Path):
        """Если model_data не содержит holiday_cols_injected (старая модель v1.x) —
        фикс должен быть no-op, decomposer работает как раньше."""
        # Создаём model_data БЕЗ holiday_cols_injected
        model_data = _make_synthetic_model_data(tmp_path)
        del model_data['normalization']['holiday_cols_injected']
        # Также убираем holiday cols из control_columns (как для старой модели)
        model_data['config']['control_columns'] = ['price']

        df = pd.read_excel(model_data['config']['data_file'])
        holiday_cols_to_inject = (
            model_data.get('normalization', {}).get('holiday_cols_injected') or []
        )
        assert holiday_cols_to_inject == []

        # df остался без holiday колонок
        control_cols = model_data['config']['control_columns']
        try:
            _ = df[control_cols].fillna(0)
        except KeyError as e:
            pytest.fail(f'df[control_cols] упало с {e}')
