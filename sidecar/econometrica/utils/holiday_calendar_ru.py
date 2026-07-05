"""
Aurora Econometrica - РФ holiday calendar auto-injection (v2.1, 2026-07-05).

Per ADR-019 §5: silent auto-injection 12 hardcoded РФ-events как dummy
control columns. Customer customization (opt-out specific holidays, custom events)
отложено в v2.2.0 (Quality of Life sprint).

🔴 Принцип окон (решение Антона 2026-07-05): окно события = период
ПОКУПАТЕЛЬСКОЙ ПОДГОТОВКИ (когда покупают подарки / делают закупки), а не
календарные праздничные дни — подарки к Новому году покупают в декабре, не
1 января; ~1-3 недели до события в зависимости от подарочного цикла. Именно
это окно видно эконометрике в продажах. Дефиниции ниже — preshop-окна для
gift-событий (НГ 15-31 дек, Valentine 1-14 фев, 23 февраля 15-23 фев,
8 марта 1-8 мар, back-to-school 15 авг-1 сен); для распродаж (ЧП/Cyber
Monday) окно = сама распродажа (покупка происходит в момент события).

🔴 Грануляция (аудит 2026-07-05): значение дамми = ДОЛЯ дней периода строки,
попавших в окно (0..1), а не принадлежность точечной даты строки окну.
На месячных данных с датой конца месяца точечная проверка давала 6/12
вечно-нулевых праздников (14 февраля никогда не конец месяца) и флаки-ЧП
(окно цепляет 30-е число в 2/4 лет). Дневная грануляция вырождается в
прежние 0/1. Старые модели (β обучены на бинарных X) воспроизводятся через
mode='binary_point' — decomposer выбирает по normalization.holiday_dummies_mode.

12 holidays cover ~80%+ типичной РФ-сезонности для FMCG / OTC / ритейл / e-commerce.

Auto-injection происходит в modeler (data preprocessing). Model
подхватывает holidays как control factors через `validator.py::CONTROL_PATTERNS`
(`holiday` pattern уже существовал). Coefficient per holiday estimated в
Bayesian model с zero-centered Gaussian prior (unconstrained sign — некоторые
holidays могут давать positive lift, другие negative).

Reference:
- docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md §1.3
- docs/v2_0_0_design/PRE_FLIGHT_FIXES.md H3 (collinearity check)
- aurora-meta/ENGINEERING_INVARIANTS.md INV-30
"""
from __future__ import annotations

import re

import pandas as pd
from datetime import date, datetime, timedelta
from itertools import combinations
from typing import Dict, List, Optional


# ─── Holiday definitions (12 events, hardcoded РФ-календарь) ───────────────

# Each holiday: column_name, category, date predicate fn (year → list of dates).
# Date predicates handle fixed dates + movable feasts (Black Friday = last Friday
# of November, Cyber Monday = first Monday after Black Friday, etc.).
# Окна gift-событий — ПОДГОТОВИТЕЛЬНЫЕ (см. принцип в докстринге модуля).

HOLIDAY_DEFINITIONS = [
    {
        'name': 'holiday_newyear_preshop',
        'category': 'gift',
        'description': 'Pre-Новогодние закупки подарков (15-31 декабря)',
        'date_range': lambda year: [
            date(year, 12, d) for d in range(15, 32)
        ],
    },
    {
        'name': 'holiday_newyear_postsale',
        'category': 'commercial',
        'description': 'Новогодние распродажи + январские каникулы (25 дек - 8 янв)',
        'date_range': lambda year: (
            [date(year, 12, d) for d in range(25, 32)]
            + [date(year + 1, 1, d) for d in range(1, 9)]
        ),
    },
    {
        'name': 'holiday_valentine',
        'category': 'gift',
        'description': 'День Святого Валентина (1-14 февраля)',
        'date_range': lambda year: [
            date(year, 2, d) for d in range(1, 15)
        ],
    },
    {
        'name': 'holiday_defender_day',
        'category': 'gift',
        'description': '23 февраля shopping (15-23 февраля)',
        'date_range': lambda year: [
            date(year, 2, d) for d in range(15, 24)
        ],
    },
    {
        'name': 'holiday_march8',
        'category': 'gift',
        'description': '8 марта shopping (1-8 марта)',
        'date_range': lambda year: [
            date(year, 3, d) for d in range(1, 9)
        ],
    },
    {
        'name': 'holiday_may_holidays',
        'category': 'general',
        'description': 'Майские праздники (28 апреля - 9 мая)',
        'date_range': lambda year: (
            [date(year, 4, d) for d in range(28, 31)]
            + [date(year, 5, d) for d in range(1, 10)]
        ),
    },
    {
        'name': 'holiday_russia_day',
        'category': 'general',
        'description': 'День России (11-12 июня)',
        'date_range': lambda year: [
            date(year, 6, 11),
            date(year, 6, 12),
        ],
    },
    {
        'name': 'holiday_back_to_school',
        'category': 'category_specific',
        'description': 'Back-to-school (15 августа - 1 сентября)',
        'date_range': lambda year: (
            [date(year, 8, d) for d in range(15, 32)]
            + [date(year, 9, 1)]
        ),
    },
    {
        'name': 'holiday_unity_day',
        'category': 'general',
        'description': 'День народного единства (3-4 ноября)',
        'date_range': lambda year: [
            date(year, 11, 3),
            date(year, 11, 4),
        ],
    },
    {
        'name': 'holiday_black_friday',
        'category': 'commercial',
        'description': 'Чёрная Пятница (последняя пятница ноября + weekend)',
        'date_range': lambda year: _black_friday_dates(year),
    },
    {
        'name': 'holiday_cyber_monday',
        'category': 'commercial',
        'description': 'Cyber Monday (понедельник после Чёрной пятницы)',
        'date_range': lambda year: [_cyber_monday_date(year)],
    },
    {
        'name': 'holiday_school_breaks',
        'category': 'family',
        'description': 'Школьные каникулы (4 окна: осенние / зимние / весенние / летние)',
        'date_range': lambda year: _school_breaks_dates(year),
    },
]


def _last_friday_of_november(year: int) -> date:
    """Compute date of last Friday in November."""
    # Start from Nov 30, walk back to find Friday (weekday()==4).
    d = date(year, 11, 30)
    while d.weekday() != 4:
        d = date(year, 11, d.day - 1)
    return d


def _black_friday_dates(year: int) -> List[date]:
    """Black Friday (last Friday Nov) + Saturday + Sunday."""
    friday = _last_friday_of_november(year)
    return [
        friday,
        date(year, 11, friday.day + 1) if friday.day + 1 <= 30 else date(year, 12, 1),
        date(year, 11, friday.day + 2) if friday.day + 2 <= 30 else date(year, 12, (friday.day + 2 - 30)),
    ]


def _cyber_monday_date(year: int) -> date:
    """Monday after Black Friday."""
    friday = _last_friday_of_november(year)
    # +3 days from Friday = Monday
    monday_day = friday.day + 3
    if monday_day <= 30:
        return date(year, 11, monday_day)
    return date(year, 12, monday_day - 30)


def _school_breaks_dates(year: int) -> List[date]:
    """4 окна школьных каникул РФ (approx):
    - Осенние: ~28 окт - 4 нояб
    - Зимние: 28 дек - 8 янв (overlaps с newyear_postsale, see H3 collinearity)
    - Весенние: ~22-30 марта
    - Летние: 1 июня - 31 авг (long window, partial overlap с back_to_school)
    """
    dates = []
    # Autumn break
    dates.extend([date(year, 10, d) for d in range(28, 32)])
    dates.extend([date(year, 11, d) for d in range(1, 5)])
    # Winter break (overlaps newyear_postsale - this is known H3 collinearity)
    dates.extend([date(year, 12, d) for d in range(28, 32)])
    dates.extend([date(year + 1, 1, d) for d in range(1, 9)])
    # Spring break
    dates.extend([date(year, 3, d) for d in range(22, 31)])
    # Summer (truncated to first week only — too long otherwise dominates control variable)
    dates.extend([date(year, 6, d) for d in range(1, 8)])
    return dates


# ─── Public API ────────────────────────────────────────────────────────────


def _infer_step_days(dates: List[date]) -> int:
    """Медианный шаг между соседними датами в днях (1=daily, 7=weekly, ~30=monthly).

    Одна строка / пустой ряд → 1 (дневная семантика, безопасный минимум)."""
    diffs = sorted(
        (b - a).days for a, b in zip(dates, dates[1:])
        if (b - a).days > 0
    )
    return diffs[len(diffs) // 2] if diffs else 1


def _row_period(d: date, step_days: int) -> tuple:
    """Границы периода строки [start, end] ВКЛЮЧИТЕЛЬНО.

    Месячный шаг (28–31 дн): период = календарный месяц даты — клиенты дают
    дату и началом (2022-01-01), и концом месяца (2022-01-31), обе означают
    январь (инвариант: обе трактовки дают одинаковый ряд дамми).
    Дневной шаг (≤1): период = сама дата (вырождение в прежние 0/1).
    Иначе (недельный/прочий): [d, d+step-1] — конвенция «дата = начало
    периода» (стандарт недельных выгрузок; при дате-конце недели окно
    сместится на неделю — так же вела себя и точечная проверка)."""
    if 28 <= step_days <= 31:
        start = d.replace(day=1)
        if d.month == 12:
            end = date(d.year, 12, 31)
        else:
            end = date(d.year, d.month + 1, 1) - timedelta(days=1)
        return start, end
    if step_days <= 1:
        return d, d
    return d, d + timedelta(days=step_days - 1)


def generate_holiday_dummies(
    date_series: pd.Series,
    holidays: Optional[List[str]] = None,
    mode: str = 'fraction',
) -> pd.DataFrame:
    """Generate РФ holiday dummy DataFrame для given date series.

    Args:
        date_series: pandas Series of dates (datetime). Indexed by row.
            Строка = период наблюдения; частота выводится из медианного шага дат.
        holidays: optional subset of holiday names to inject. If None — all 12.
        mode: 'fraction' (default, v2.1) — значение = доля дней периода строки
            в окне подготовки к событию (0..1); честно работает на месячной и
            недельной грануляции (декабрь получает 17/31 НГ-закупок, а не 0/1
            по точечной дате). 'binary_point' — legacy-поведение v2.0 (дата
            строки ∈ окно → 1): для decompose моделей, обученных до v2.1
            (β согласованы с бинарными X; см. normalization.holiday_dummies_mode).

    Returns:
        DataFrame с columns = holiday names; values ∈ [0, 1] (float в
        'fraction', int 0/1 в 'binary_point'). Index match input date_series.
        На дневной грануляции 'fraction' совпадает с 'binary_point' по значениям.

    Examples:
        >>> dates = pd.Series(pd.date_range('2024-01-01', '2024-12-31', freq='D'))
        >>> dummies = generate_holiday_dummies(dates)
        >>> dummies.columns.tolist()
        ['holiday_newyear_preshop', 'holiday_newyear_postsale', 'holiday_valentine',
         'holiday_defender_day', 'holiday_march8', 'holiday_may_holidays',
         'holiday_russia_day', 'holiday_back_to_school', 'holiday_unity_day',
         'holiday_black_friday', 'holiday_cyber_monday', 'holiday_school_breaks']
    """
    if mode not in ('fraction', 'binary_point'):
        raise ValueError(f"mode must be 'fraction' | 'binary_point', got {mode!r}")

    if not isinstance(date_series, pd.Series):
        date_series = pd.Series(date_series)

    # Convert to date if datetime
    date_series_dates = pd.to_datetime(date_series).dt.date

    # Determine year range
    years_in_data = sorted(set(d.year for d in date_series_dates if d is not pd.NaT))

    if not years_in_data:
        # Empty input → empty DataFrame
        return pd.DataFrame(index=date_series.index)

    # Determine which holidays to include
    if holidays is None:
        holiday_defs = HOLIDAY_DEFINITIONS
    else:
        holiday_defs = [h for h in HOLIDAY_DEFINITIONS if h['name'] in holidays]

    # Build holiday date sets per holiday
    holiday_date_sets: Dict[str, set] = {}
    for h_def in holiday_defs:
        name = h_def['name']
        dates_set: set = set()
        for year in years_in_data:
            year_dates = h_def['date_range'](year)
            dates_set.update(year_dates)
            # Also include preceding year holiday (since some span year boundary)
            try:
                prev_year_dates = h_def['date_range'](year - 1)
                dates_set.update(prev_year_dates)
            except Exception:
                pass
        holiday_date_sets[name] = dates_set

    # Build DataFrame
    df = pd.DataFrame(index=date_series.index)

    if mode == 'binary_point':
        for name, dates_set in holiday_date_sets.items():
            df[name] = date_series_dates.isin(dates_set).astype(int)
        return df

    # mode == 'fraction': доля дней периода строки, попавших в окно события.
    valid_dates = [d for d in date_series_dates if d is not pd.NaT and d is not None]
    step_days = _infer_step_days(sorted(valid_dates))
    periods = []
    for d in date_series_dates:
        if d is pd.NaT or d is None:
            periods.append(None)
            continue
        periods.append(_row_period(d, step_days))

    for name, dates_set in holiday_date_sets.items():
        values = []
        for period in periods:
            if period is None:
                values.append(0.0)
                continue
            start, end = period
            period_len = (end - start).days + 1
            overlap = sum(1 for wd in dates_set if start <= wd <= end)
            values.append(round(overlap / period_len, 4))
        df[name] = values

    return df


# ─── Семантический дедуп имён (аудит 2026-07-05) ────────────────────────────
# Дедуп авто-инжекта с ручными колонками шёл по ТОЧНОМУ имени → юзерская
# `holiday_blackfriday` не гасила авто `holiday_black_friday`, обе уходили в
# модель (частичный двойной учёт события). Нормализация убирает разделители.


def normalize_holiday_name(name: str) -> str:
    """Каноническая форма имени для сравнения: lower + без разделителей.

    'holiday_black_friday' == 'holiday_blackfriday' == 'Holiday Black-Friday'.
    """
    return re.sub(r'[\s_\-]+', '', str(name).lower())


def user_covered_auto_holidays(existing_columns: List[str]) -> set:
    """Авто-праздники, уже покрытые колонками пользователя (по норм-имени).

    Инжект обязан их пропустить: ручная колонка = источник истины пользователя,
    авто-дубль с чуть иным написанием дал бы двойной учёт события.

    Returns:
        set канонических имён авто-праздников (из HOLIDAY_DEFINITIONS),
        конфликтующих с existing_columns.
    """
    existing_norm = {normalize_holiday_name(c) for c in existing_columns}
    return {
        h['name'] for h in HOLIDAY_DEFINITIONS
        if normalize_holiday_name(h['name']) in existing_norm
    }


def detect_holiday_collinearity(
    holidays_df: pd.DataFrame,
    threshold: float = 0.5,
) -> List[Dict[str, object]]:
    """Detect overlapping holiday windows (per audit H3).

    Returns warnings; не blocks model fitting. Documents для diagnostics panel.

    Args:
        holidays_df: DataFrame с holiday dummies (output of generate_holiday_dummies).
        threshold: overlap percentage threshold (default 0.5 = 50%).

    Returns:
        List of warning dicts:
        [{'holiday_a': str, 'holiday_b': str, 'overlap_pct': float,
          'severity': 'warn' | 'expected', 'message': str}]

    Examples:
        >>> # holiday_newyear_preshop (15-31 Dec) ∩ holiday_school_breaks (winter ~28 Dec-8 Jan)
        >>> # overlap ~50%, flagged as 'expected' (known known)
        ...
    """
    warnings = []
    holiday_cols = holidays_df.columns.tolist()

    # Known expected overlaps (documented, не surprise).
    # v2.0.0 audit fix (Arch H3): эти pairs all-but-guarantee multicollinearity;
    # severity 'warn_expected' surfaces в diagnostics так что customer aware.
    # При overlap >85% — additionally suggest merge.
    EXPECTED_OVERLAPS = {
        ('holiday_newyear_preshop', 'holiday_school_breaks'),
        ('holiday_newyear_postsale', 'holiday_school_breaks'),
        ('holiday_back_to_school', 'holiday_school_breaks'),  # summer break + back-to-school
        ('holiday_black_friday', 'holiday_cyber_monday'),  # adjacent
    }
    # Threshold for «very high overlap — merge recommended».
    MERGE_RECOMMENDED_THRESHOLD = 0.85

    for h1, h2 in combinations(holiday_cols, 2):
        # Активность периода = значение > 0: работает и для legacy binary 0/1,
        # и для fraction-долей v2.1 (0.1 «ЧП заняла 3 дня ноября» — период активен).
        overlap_count = ((holidays_df[h1] > 0) & (holidays_df[h2] > 0)).sum()
        h1_count = max(1, int((holidays_df[h1] > 0).sum()))
        h2_count = max(1, int((holidays_df[h2] > 0).sum()))
        # Use smaller denominator для proportion (small holiday vs large)
        overlap_pct = overlap_count / min(h1_count, h2_count)

        if overlap_pct > threshold:
            pair = tuple(sorted([h1, h2]))
            is_expected = pair in EXPECTED_OVERLAPS or tuple(reversed(pair)) in EXPECTED_OVERLAPS

            # v2.0.0 audit fix (Arch H3): even expected overlaps surface как 'warn_expected'
            # — they still cause multicollinearity, customer should be aware. Very high
            # overlap (>85%) triggers merge recommendation.
            if overlap_pct > MERGE_RECOMMENDED_THRESHOLD:
                severity = 'merge_recommended'
                message = (
                    f'{h1} and {h2} overlap {overlap_pct*100:.0f}% (>85%) — '
                    f'high multicollinearity, рекомендуем merge в single dummy.'
                )
            elif is_expected:
                severity = 'warn_expected'
                message = (
                    f'{h1} and {h2} overlap {overlap_pct*100:.0f}% '
                    f'(expected by design — both events span winter/holiday window). '
                    f'Coefficients для этих holidays могут быть correlated.'
                )
            else:
                severity = 'warn'
                message = (
                    f'{h1} and {h2} overlap {overlap_pct*100:.0f}% — may cause '
                    f'multicollinearity. Consider removing one or merging.'
                )

            warnings.append({
                'holiday_a': h1,
                'holiday_b': h2,
                'overlap_pct': float(overlap_pct),
                'severity': severity,
                'message': message,
            })

    return warnings


def list_holiday_names() -> List[str]:
    """Return list of all 12 holiday column names."""
    return [h['name'] for h in HOLIDAY_DEFINITIONS]


def get_holiday_metadata(holiday_name: str) -> Optional[Dict[str, str]]:
    """Get description + category для конкретного holiday."""
    for h in HOLIDAY_DEFINITIONS:
        if h['name'] == holiday_name:
            return {
                'name': h['name'],
                'category': h['category'],
                'description': h['description'],
            }
    return None
