"""
Aurora Econometrica - РФ holiday calendar auto-injection (v2.1, 2026-07-05).

Per ADR-019 §5: silent auto-injection 12 hardcoded РФ-events как dummy
control columns. Customer customization (opt-out specific holidays, custom events)
отложено в v2.2.0 (Quality of Life sprint).

🔴 Принцип окон (решения Антона 2026-07-05, два уточнения): окно события —
это период ПОВЫШЕННОЙ ПОКУПАТЕЛЬСКОЙ АКТИВНОСТИ, и его положение зависит
от КЛАССА события (window_kind):
  * 'preparation' — праздники (НГ, 8 марта, 14/23 февраля, back-to-school):
    активность идёт ДО события — закупки подарков/товаров ~1-3 недели до
    (подарки к НГ покупают в декабре, не 1 января). Окно = [событие − 1-3
    недели → событие].
  * 'sale_period' — распродажи (Чёрная пятница, Cyber Monday, новогодние
    распродажи): активность идёт С МОМЕНТА СТАРТА распродажи и по её
    завершении, обычно ~2-3 недели от старта. Окно = [старт → старт + N].
  * 'calendar_period' — календарные периоды потребления (майские, короткие
    госвыходные, школьные каникулы): активность в сам период. Окно = период.
Именно эти окна видит эконометрика в продажах.

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

# window_kind (решение Антона 2026-07-05, второе уточнение):
#   'preparation'     — активность ДО события (окно подготовки/закупок);
#   'sale_period'     — активность ОТ старта распродажи (~2-3 недели);
#   'calendar_period' — активность в сам календарный период.
# У распродаж дополнительно date_range_v20 — узкие окна v2.0 (сам момент
# события): их обязан воспроизводить mode='binary_point' для старых моделей
# (β обучены на тех X — см. generate_holiday_dummies).
HOLIDAY_DEFINITIONS = [
    {
        'name': 'holiday_newyear_preshop',
        'category': 'gift',
        'window_kind': 'preparation',
        'description': 'Pre-Новогодние закупки подарков (15-31 декабря)',
        'date_range': lambda year: [
            date(year, 12, d) for d in range(15, 32)
        ],
    },
    {
        'name': 'holiday_newyear_postsale',
        'category': 'commercial',
        'window_kind': 'sale_period',
        'description': 'Новогодние распродажи + январские каникулы (старт 25 дек → 8 янв)',
        'date_range': lambda year: (
            [date(year, 12, d) for d in range(25, 32)]
            + [date(year + 1, 1, d) for d in range(1, 9)]
        ),
    },
    {
        'name': 'holiday_valentine',
        'category': 'gift',
        'window_kind': 'preparation',
        'description': 'День Святого Валентина (подготовка 1-14 февраля)',
        'date_range': lambda year: [
            date(year, 2, d) for d in range(1, 15)
        ],
    },
    {
        'name': 'holiday_defender_day',
        'category': 'gift',
        'window_kind': 'preparation',
        'description': '23 февраля (подготовка 15-23 февраля)',
        'date_range': lambda year: [
            date(year, 2, d) for d in range(15, 24)
        ],
    },
    {
        'name': 'holiday_march8',
        'category': 'gift',
        'window_kind': 'preparation',
        'description': '8 марта (подготовка 1-8 марта)',
        'date_range': lambda year: [
            date(year, 3, d) for d in range(1, 9)
        ],
    },
    {
        'name': 'holiday_may_holidays',
        'category': 'general',
        'window_kind': 'calendar_period',
        'description': 'Майские праздники (28 апреля - 9 мая)',
        'date_range': lambda year: (
            [date(year, 4, d) for d in range(28, 31)]
            + [date(year, 5, d) for d in range(1, 10)]
        ),
    },
    {
        'name': 'holiday_russia_day',
        'category': 'general',
        'window_kind': 'calendar_period',
        'description': 'День России (11-12 июня)',
        'date_range': lambda year: [
            date(year, 6, 11),
            date(year, 6, 12),
        ],
    },
    {
        'name': 'holiday_back_to_school',
        'category': 'category_specific',
        'window_kind': 'preparation',
        'description': 'Back-to-school — подготовка к 1 сентября (15 августа - 1 сентября)',
        'date_range': lambda year: (
            [date(year, 8, d) for d in range(15, 32)]
            + [date(year, 9, 1)]
        ),
    },
    {
        'name': 'holiday_unity_day',
        'category': 'general',
        'window_kind': 'calendar_period',
        'description': 'День народного единства (3-4 ноября)',
        'date_range': lambda year: [
            date(year, 11, 3),
            date(year, 11, 4),
        ],
    },
    {
        'name': 'holiday_black_friday',
        'category': 'commercial',
        'window_kind': 'sale_period',
        'description': 'Чёрная Пятница — распродажный период (старт: последняя пятница ноября, ~2 недели)',
        # Активность идёт ОТ старта распродажи (уточнение Антона): 14 дней.
        'date_range': lambda year: _sale_window(_last_friday_of_november(year), 14),
        # v2.0-окно (сам момент: пятница + weekend) — для binary_point.
        'date_range_v20': lambda year: _black_friday_dates(year),
    },
    {
        'name': 'holiday_cyber_monday',
        'category': 'commercial',
        'window_kind': 'sale_period',
        'description': 'Cyber Monday — онлайн-распродажная неделя (старт: пн после ЧП, 7 дней)',
        # Короткая онлайн-распродажа: Cyber Week от старта (внутри ЧП-периода —
        # перекрытие ожидаемо, помечено в EXPECTED_OVERLAPS).
        'date_range': lambda year: _sale_window(_cyber_monday_date(year), 7),
        # v2.0-окно (один день) — для binary_point.
        'date_range_v20': lambda year: [_cyber_monday_date(year)],
    },
    {
        'name': 'holiday_school_breaks',
        'category': 'family',
        'window_kind': 'calendar_period',
        'description': 'Школьные каникулы (4 окна: осенние / зимние / весенние / летние)',
        'date_range': lambda year: _school_breaks_dates(year),
    },
]


def _sale_window(start: date, days: int) -> List[date]:
    """Окно распродажи ОТ старта (уточнение Антона 2026-07-05): повышенная
    покупательская активность идёт с момента старта распродажи и по её
    завершении (~2-3 недели), а не до события, как у праздников."""
    return [start + timedelta(days=i) for i in range(days)]


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

    # Build holiday date sets per holiday.
    # binary_point (decompose моделей v2.0) обязан воспроизводить И точечную
    # семантику, И СТАРЫЕ окна распродаж (date_range_v20) — β тех моделей
    # обучены на тех X; новые окна sale_period существуют только в 'fraction'.
    holiday_date_sets: Dict[str, set] = {}
    for h_def in holiday_defs:
        name = h_def['name']
        range_fn = h_def['date_range']
        if mode == 'binary_point' and 'date_range_v20' in h_def:
            range_fn = h_def['date_range_v20']
        dates_set: set = set()
        for year in years_in_data:
            year_dates = range_fn(year)
            dates_set.update(year_dates)
            # Also include preceding year holiday (since some span year boundary)
            try:
                prev_year_dates = range_fn(year - 1)
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


# ─── Семантический дедуп имён (аудит 2026-07-05, углублён по решению Антона) ──
# Дедуп авто-инжекта с ручными колонками шёл по ТОЧНОМУ имени → юзерская
# `holiday_blackfriday` не гасила авто `holiday_black_friday`, обе уходили в
# модель (частичный двойной учёт события). Расширено: клиент НЕ знает нашу
# конвенцию префикса `holiday_` и назовёт колонку `black_friday` / `blackfriday`
# / `чёрная_пятница` / `8_марта` — их тоже надо опознать и погасить авто-дубль.
#
# 🔴 АСИММЕТРИЯ РИСКА (ключевой принцип дизайна): ЛОЖНОЕ гашение ОПАСНЕЕ
# пропущенного. Пропустили → двойной учёт (оба контроля в модели, слегка
# коллинеарны — терпимо). Ложно погасили → контроль ПОТЕРЯН → эффект праздника
# уходит в медиа (OVB, завышенный ROI — молча). Поэтому:
#   1. Алиасы — КУРИРУЕМЫЙ whitelist специфичных «ядер», НЕ автоген из имени.
#      Никаких голых коротких неоднозначных слов (may/russia/unity/march) —
#      только полные формы: не погасит mayonnaise_sales / russian_market /
#      community_reach / marchmadness_promo.
#   2. Дата-формы (8марта, 23февраля, 4ноября) специфичны цифрой месяца.
#   3. _alias_matches: короткий безцифровой алиас (<5) сматчит ТОЛЬКО точным
#      равенством норм-имён (страховка на случай будущего короткого алиаса).
#   4. ТОЧНОЕ совпадение с авто-именем покрывает РОВНО его (не расширяется на
#      алиасы) — клиент, скопировавший наш шаблон, получает точное намерение.

_MIN_SUBSTRING_ALIAS = 5  # ниже — только точное равенство (если нет цифры)

# Курируемые алиасы события БЕЗ префикса holiday_ (варианты имени + синонимы
# RU/EN + дата-формы). ⚠️ Добавляя алиас — держи его специфичным (длинным или
# с цифрой месяца): substring-матч на коротком слове ложно гасит контроль.
_HOLIDAY_ALIASES: Dict[str, tuple] = {
    # Общий `newyear`/`новыйгод` намеренно в ОБОИХ НГ-событиях: клиент, назвавший
    # колонку обобщённо «Новый год», берёт весь НГ-период на себя → гасим оба
    # авто-дубля (а не плодим их рядом). Точное имя авто-события этот общий
    # алиас не задевает (см. приоритет точного совпадения в user_covered_*).
    'holiday_newyear_preshop': (
        'newyear', 'новыйгод', 'newyearshopping', 'newyeargifts', 'предновогодн',
    ),
    'holiday_newyear_postsale': (
        'newyear', 'новыйгод', 'newyearsale', 'newyearpostsale',
        'новогодниераспродажи', 'январскиераспродажи', 'январскиеканикулы',
    ),
    # ⚠️ НЕ голое 'валентин': имя человека в названии колонки («Валентина_план»)
    # дало бы ложное срабатывание — только событийные формы.
    'holiday_valentine': (
        'valentine', 'валентинк', 'деньвалентина', 'деньсвятоговалентина',
        'деньвлюблённых', 'деньвлюбленных',
        '14февраля', '14february', 'february14',
    ),
    'holiday_defender_day': (
        'defenderday', 'деньзащитника', '23февраля', '23february', 'february23',
    ),
    'holiday_march8': (
        'march8', '8march', '8марта', 'womensday', 'internationalwomensday',
        'женскийдень', 'международныйженскийдень',
    ),
    'holiday_may_holidays': (
        'mayholidays', 'майскиепраздники', 'майские', '1мая', '9мая',
        'деньпобеды', 'victoryday', 'labourday',
    ),
    'holiday_russia_day': (
        'russiaday', 'деньроссии', '12июня', 'june12',
    ),
    'holiday_back_to_school': (
        'backtoschool', 'back2school', 'ктошколе', 'кшколе', '1сентября',
        'backtoschoolseason',
    ),
    'holiday_unity_day': (
        'unityday', 'деньнародногоединства', 'народногоединства',
        '4ноября', 'november4',
    ),
    'holiday_black_friday': (
        'blackfriday', 'чёрнаяпятница', 'чернаяпятница', 'блэкфрайдей',
    ),
    'holiday_cyber_monday': (
        'cybermonday', 'киберпонедельник', 'кибермонди',
    ),
    'holiday_school_breaks': (
        'schoolbreaks', 'школьныеканикулы', 'каникулы',
    ),
}


def normalize_holiday_name(name: str) -> str:
    """Каноническая форма имени для сравнения: lower + без разделителей.

    'holiday_black_friday' == 'holiday_blackfriday' == 'Holiday Black-Friday'.
    """
    return re.sub(r'[\s_\-]+', '', str(name).lower())


def _alias_matches(alias: str, col_norm: str) -> bool:
    """Норм-имя колонки опознаётся алиасом события.

    Длинный (≥_MIN_SUBSTRING_ALIAS) или содержащий цифру алиас — substring-матч
    (ловит префиксы/суффиксы клиента: promo_black_friday_2024). Короткий
    безцифровой — только точное равенство (страховка от ложных гашений)."""
    if len(alias) >= _MIN_SUBSTRING_ALIAS or any(ch.isdigit() for ch in alias):
        return alias in col_norm
    return alias == col_norm


def is_holiday_like_name(name: str) -> bool:
    """Имя колонки — событийная дамми (точное авто-имя ИЛИ курируемый алиас).

    SSOT-предикат для ОБОИХ детекторов (аудит №4, 2026-07-05): клиентская
    колонка `black_friday`/`8_марта`/`чёрная_пятница` без нашего префикса
    обязана получить роль control (validator) и kind 'holiday' (classify) —
    иначе она unused, а дедуп гасит авто-инжект → контроль события ТЕРЯЕТСЯ
    полностью (хуже дубля: OVB молча). Анти-ложная защита та же, что у дедупа
    (whitelist специфичных ядер + гейт длины _alias_matches).
    """
    col_norm = normalize_holiday_name(name)
    if not col_norm:
        return False
    for h in HOLIDAY_DEFINITIONS:
        if col_norm == normalize_holiday_name(h['name']):
            return True
        if any(_alias_matches(a, col_norm) for a in _HOLIDAY_ALIASES.get(h['name'], ())):
            return True
    return False


def user_covered_auto_holidays(existing_columns: List[str]) -> set:
    """Авто-праздники, уже покрытые колонками пользователя.

    Инжект обязан их пропустить: ручная колонка = источник истины пользователя,
    авто-дубль (в т.ч. с иным написанием или без префикса holiday_) дал бы
    двойной учёт события. Порядок: (1) точное совпадение норм-имени с авто-именем
    покрывает РОВНО его; (2) иначе — курируемые алиасы (могут покрыть несколько
    родственных событий, напр. общий «Новый год» → оба НГ-окна).

    Returns:
        set канонических имён авто-праздников (из HOLIDAY_DEFINITIONS),
        конфликтующих с existing_columns.
    """
    existing_norm = {n for n in (normalize_holiday_name(c) for c in existing_columns) if n}
    auto_norms = {normalize_holiday_name(h['name']): h['name'] for h in HOLIDAY_DEFINITIONS}
    covered: set = set()
    for col_norm in existing_norm:
        # 1. Точное совпадение с авто-именем → покрывает РОВНО его.
        if col_norm in auto_norms:
            covered.add(auto_norms[col_norm])
            continue
        # 2. Иначе — курируемые алиасы (без-префиксные / синонимы / даты).
        for h in HOLIDAY_DEFINITIONS:
            name = h['name']
            if any(_alias_matches(a, col_norm) for a in _HOLIDAY_ALIASES.get(name, ())):
                covered.add(name)
    return covered


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


def _merge_dates_into_ranges(dates: List[date]) -> List[Dict[str, str]]:
    """Список дат → список непрерывных отрезков [начало, конец] в ISO-8601.

    Окно события задано перечислением дат (в том числе через границу года),
    а читателю документа нужен диапазон: «15.12–31.12», а не семнадцать дат.
    """
    ranges: List[Dict[str, str]] = []
    for d in sorted(set(dates)):
        if ranges and (date.fromisoformat(ranges[-1]['end']) + timedelta(days=1)) == d:
            ranges[-1]['end'] = d.isoformat()
            ranges[-1]['days'] += 1
        else:
            ranges.append({'start': d.isoformat(), 'end': d.isoformat(), 'days': 1})
    return ranges


def _короткое_тире(текст: str) -> str:
    """Типографика клиентского текста: длинное тире меняется на короткое.

    Описания событий писались для журнала и экрана разработчика, а теперь
    уезжают в документ, который клиент показывает третьей стороне, – там
    принято короткое тире. Правится только копия, уходящая в описание:
    сами определения событий не трогаем, у них другие читатели.
    """
    return str(текст).replace('—', '–')


def describe_holiday_windows(
    years: List[int],
    holidays: Optional[List[str]] = None,
    mode: str = 'fraction',
) -> Dict[str, object]:
    """Календарные определения праздничных окон – в виде, пригодном для чужой сборки.

    Зачем: в документе воспроизводимости имена двенадцати признаков и режим
    «доля периода» не позволяют собрать регрессор заново – нужны сами даты и
    правило пересчёта дат в число. Описание порождается из тех же
    ``HOLIDAY_DEFINITIONS`` и тех же функций окна, которыми считаются дамми:
    отдельного текста, способного разойтись с расчётом, здесь нет.

    Args:
        years: годы, встречающиеся в обучающем ряду. Как и в
            ``generate_holiday_dummies``, к каждому году добавляется
            предшествующий – окна событий переходят через границу года
            (новогодние распродажи 25 декабря → 8 января).
        holidays: какие события описывать. ``None`` – все двенадцать.
        mode: режим, которым построены дамми. От него зависит, какое окно
            применялось у распродаж: ``'fraction'`` берёт окно распродажного
            периода, ``'binary_point'`` – узкое окно версии 2.0.

    Returns:
        Словарь: правило режима, правило периода строки, годы и по каждому
        событию – категория, класс окна, человеческое описание и календарные
        отрезки.
    """
    defs = HOLIDAY_DEFINITIONS if holidays is None else [
        h for h in HOLIDAY_DEFINITIONS if h['name'] in holidays
    ]
    годы = sorted({int(y) for y in years} | {int(y) - 1 for y in years})

    события: List[Dict[str, object]] = []
    for h_def in defs:
        поле_окна = 'date_range'
        if mode == 'binary_point' and 'date_range_v20' in h_def:
            поле_окна = 'date_range_v20'
        собранные: List[date] = []
        for year in годы:
            try:
                собранные.extend(h_def[поле_окна](year))
            except Exception:  # noqa: BLE001 – экзотический год не должен рушить описание
                continue
        события.append({
            'name': h_def['name'],
            'category': h_def['category'],
            'window_kind': h_def.get('window_kind', 'calendar_period'),
            'description': _короткое_тире(h_def['description']),
            'window_source': поле_окна,
            'windows': _merge_dates_into_ranges(собранные),
            'n_days_total': len(set(собранные)),
        })

    return {
        'source': (
            'utils/holiday_calendar_ru.py – HOLIDAY_DEFINITIONS, generate_holiday_dummies, '
            '_row_period, _infer_step_days'
        ),
        'mode': mode,
        'mode_rules': {
            'fraction': (
                'Значение признака в строке = доля дней периода этой строки, попавших в окно '
                'события: (число дней окна внутри периода) / (число дней в периоде), округление '
                'до 4 знаков. Диапазон 0..1. На месячных данных декабрь получает 17/31 у '
                'предновогодних закупок, а не 0 или 1.'
            ),
            'binary_point': (
                'Значение признака = 1, если сама дата строки попадает в окно события, иначе 0. '
                'Режим моделей до 05.07.2026; у распродаж применяются узкие окна версии 2.0 '
                '(сам день события), а не распродажный период.'
            ),
        },
        'row_period_rule': [
            'Шаг ряда определяется как медиана разностей между соседними датами в днях.',
            'Шаг 28–31 день – период строки равен календарному месяцу её даты, от первого числа '
            'до последнего. Дата начала месяца и дата конца месяца дают один и тот же период.',
            'Шаг 1 день и меньше – период равен самой дате (доля вырождается в 0 или 1).',
            'Прочий шаг (например недельный) – период равен [дата; дата + шаг − 1 день], то есть '
            'дата считается началом периода.',
        ],
        'window_kinds': {
            'preparation': 'окно подготовки: активность идёт ДО события (закупка подарков)',
            'sale_period': 'окно распродажи: активность идёт ОТ старта распродажи',
            'calendar_period': 'сам календарный период потребления',
        },
        'years_covered': годы,
        'years_rule': (
            'В набор дат события входят окна каждого года, встречающегося в данных, и '
            'предшествующего ему года – иначе события, переходящие через границу года, '
            'потерялись бы в первом году ряда.'
        ),
        'events': события,
    }


def get_holiday_metadata(holiday_name: str) -> Optional[Dict[str, str]]:
    """Get description + category + window_kind для конкретного holiday."""
    for h in HOLIDAY_DEFINITIONS:
        if h['name'] == holiday_name:
            return {
                'name': h['name'],
                'category': h['category'],
                'window_kind': h.get('window_kind', 'calendar_period'),
                'description': h['description'],
            }
    return None
