"""Сторож против повторного задвоения источника истины числа праздников.

Контекст (найдено 13.09.2026): в `holiday_calendar_ru.py` живёт список
`HOLIDAY_DEFINITIONS` — 13 событий после добавления православной Пасхи. Рядом
в `validator.py::validate_data` годами лежала СВОЯ константа
`N_HOLIDAYS_DEFAULT = 12`, которой считался `n_params_effective_bayesian` —
число эффективных параметров модели ДО обучения. Задвоение источника истины:
календарь вырос на одно событие, константа — нет, и знаменатель «запас данных»
(наблюдений на параметр) занижался на единицу, показывая клиенту более
надёжную модель, чем есть на самом деле (нарушение INV-50).

Починка: число праздников берётся из календаря (`list_holiday_names()`), а не
из своей константы. Этот тест охраняет СВЯЗЬ, а не число: если завтра
добавится 14-е событие, тест обязан пройти без изменений — иначе он повторит
ту же ошибку, только с другой цифрой (см. поручение задачи, шаг 4).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


def _build(tmp_path: Path, n: int = 60, n_media: int = 3) -> Path:
    """Минимальный датасет без праздничных/пользовательских holiday-колонок,
    чтобы n_holidays_auto считался по ПОЛНОМУ списку календаря (_covered=0)."""
    rng = np.random.RandomState(0)
    data = {
        'Дата': pd.date_range('2022-01-01', periods=n, freq='W'),
        'sales_rub': rng.uniform(100, 1000, n),
    }
    for i in range(n_media):
        data[f'tv_spend_{i}'] = rng.uniform(50, 500, n)
    df = pd.DataFrame(data)
    f = tmp_path / 'data.xlsx'
    df.to_excel(f, index=False)
    return f


def test_n_holidays_auto_равно_длине_календаря_а_не_зашитому_числу(tmp_path):
    """Знаменатель обязан расти и падать ВМЕСТЕ с календарём.

    Не «== 13»: зашитая здесь цифра повторила бы ту же ошибку через полгода,
    когда в календаре появится 14-е событие. Сверка — с самим календарём.
    """
    from engines.validator import validate_data
    from utils.holiday_calendar_ru import list_holiday_names

    res = validate_data(str(_build(tmp_path)))
    detected = res['detected']

    n_calendar_holidays = len(list_holiday_names())
    assert detected['n_holidays_auto'] == n_calendar_holidays, (
        f"n_holidays_auto={detected['n_holidays_auto']} разошёлся с календарём "
        f"({n_calendar_holidays} событий) — источник истины снова задвоен."
    )

    # Знаменатель байесовской оценки обязан включать именно это число праздников
    # + intercept, а не какую-то отдельно живущую константу.
    expected_denominator = detected['n_predictors'] + n_calendar_holidays + detected['n_intercept']
    assert detected['n_params_effective_bayesian'] == expected_denominator
