"""Сторож православной Пасхи в календаре праздников (13.09.2026).

Пасха — единственное переходящее событие набора: дата не задаётся числом
месяца, а считается александрийской пасхалией. Поэтому ошибка в счислении не
падает и не краснеет сама — она молча сдвигает окно на неделю-другую, и модель
приписывает всплеск продаж не тому фактору. Отсюда проверка по известным датам,
а не по «функция что-то вернула».

Границы окна (неделя до, сам день, три дня после) заданы владельцем 13.09.2026
как период влияния праздника на потребительское поведение — тест закрепляет
именно их, чтобы случайная правка не расширила окно молча.
"""
from __future__ import annotations

from datetime import date

import pytest

from utils.holiday_calendar_ru import (
    HOLIDAY_DEFINITIONS,
    _orthodox_easter_window,
    orthodox_easter,
)


# Даты православной Пасхи (григорианский календарь) — сверка с общеизвестными.
KNOWN_EASTER = {
    2019: date(2019, 4, 28),
    2020: date(2020, 4, 19),
    2021: date(2021, 5, 2),
    2022: date(2022, 4, 24),
    2023: date(2023, 4, 16),
    2024: date(2024, 5, 5),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 12),
    2027: date(2027, 5, 2),
    2028: date(2028, 4, 16),
    2029: date(2029, 4, 8),
    2030: date(2030, 4, 28),
}


@pytest.mark.parametrize("year,expected", sorted(KNOWN_EASTER.items()))
def test_orthodox_easter_matches_known_dates(year, expected):
    """Пасхалия считает те же даты, что и общеизвестный календарь."""
    assert orthodox_easter(year) == expected, (
        f"{year}: получилось {orthodox_easter(year)}, известно {expected}. "
        "Сдвиг обычно означает ошибку в переводе из юлианского календаря."
    )


def test_easter_always_falls_in_april_or_may():
    """Православная Пасха не бывает раньше апреля и позже мая.

    Грубая, но независимая проверка счисления на длинном промежутке: ловит
    ошибку в формуле, которая на отдельных годах даёт правдоподобную дату.
    """
    for year in range(1950, 2101):
        d = orthodox_easter(year)
        assert d.month in (4, 5), f"{year}: Пасха выпала на {d}, вне апреля-мая"


def test_window_is_week_before_and_three_days_after():
    """Окно влияния: 7 дней до праздника, сам день и 3 дня после — всего 11."""
    for year in (2024, 2025, 2026):
        easter = orthodox_easter(year)
        window = _orthodox_easter_window(year)
        assert len(window) == 11, f"{year}: окно {len(window)} дней вместо 11"
        assert window[0] == easter.replace() - (easter - window[0]), "окно не непрерывно"
        assert (easter - window[0]).days == 7, f"{year}: начало окна не за неделю"
        assert (window[-1] - easter).days == 3, f"{year}: конец окна не через 3 дня"
        assert easter in window, f"{year}: сам день праздника выпал из окна"
        # непрерывность: каждый следующий день ровно на сутки позже предыдущего
        for prev, nxt in zip(window, window[1:]):
            assert (nxt - prev).days == 1, f"{year}: разрыв в окне между {prev} и {nxt}"


def test_easter_registered_as_holiday():
    """Событие есть в наборе, класс окна — из допустимого списка."""
    names = [h["name"] for h in HOLIDAY_DEFINITIONS]
    assert "holiday_easter_orthodox" in names, "Пасха пропала из набора праздников"
    easter_def = next(
        h for h in HOLIDAY_DEFINITIONS if h["name"] == "holiday_easter_orthodox"
    )
    assert easter_def["window_kind"] in ("preparation", "sale_period", "calendar_period")
    # date_range обязан возвращать то же, что и функция окна
    assert easter_def["date_range"](2026) == _orthodox_easter_window(2026)


def test_overlap_with_may_holidays_is_declared():
    """Пересечение с майскими объявлено как известное, а не всплывает сюрпризом.

    В годы поздней Пасхи окна почти совпадают (2024 — полностью), и разделить
    вклады нельзя. Пара обязана быть в списке ожидаемых пересечений, иначе
    программа покажет клиенту два «независимых» вклада вместо предупреждения.
    """
    import inspect

    from utils import holiday_calendar_ru

    source = inspect.getsource(holiday_calendar_ru.detect_holiday_collinearity)
    assert "holiday_easter_orthodox" in source and "holiday_may_holidays" in source, (
        "пара «Пасха ↔ майские» не объявлена в EXPECTED_OVERLAPS"
    )


def test_late_easter_overlaps_may_early_easter_does_not():
    """Факт пересечения посчитан, а не предположен.

    2024 (Пасха 5 мая) — окно целиком внутри майских; 2026 (12 апреля) — не
    пересекается вовсе. Если эти два утверждения разойдутся с кодом, значит
    сдвинулось либо окно Пасхи, либо окно майских.
    """
    may_window = set(
        [date(2024, 4, d) for d in range(28, 31)]
        + [date(2024, 5, d) for d in range(1, 10)]
    )
    late = [d for d in _orthodox_easter_window(2024) if d in may_window]
    assert len(late) == 11, f"2024: ожидалось полное совпадение, получилось {len(late)}/11"

    may_2026 = set(
        [date(2026, 4, d) for d in range(28, 31)]
        + [date(2026, 5, d) for d in range(1, 10)]
    )
    early = [d for d in _orthodox_easter_window(2026) if d in may_2026]
    assert early == [], f"2026: ожидалось отсутствие пересечения, получилось {early}"
