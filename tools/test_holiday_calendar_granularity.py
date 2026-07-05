"""Праздничный календарь v2.1 (2026-07-05): окна подготовки × грануляция периодов.

Принцип (решение Антона): окно события = период ПОКУПАТЕЛЬСКОЙ ПОДГОТОВКИ
(закупки подарков ~1-3 недели до события), а значение дамми = ДОЛЯ дней
периода строки в этом окне — не принадлежность точечной даты строки.

Класс закрываемого дефекта (аудит 2026-07-05): на месячных данных с датой
конца месяца точечная проверка давала 6/12 вечно-нулевых праздников
(14 февраля никогда не конец месяца) и флаки-ЧП (окно «пятница+уикенд»
цепляет 30-е число лишь в части лет: 2022/2023 → 0, 2024/2025 → 1).

Также: семантический дедуп авто-инжекта с ручными колонками (точное имя
не гасило `holiday_blackfriday` против авто `holiday_black_friday`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_SIDECAR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from utils.holiday_calendar_ru import (  # noqa: E402
    generate_holiday_dummies,
    detect_holiday_collinearity,
    normalize_holiday_name,
    user_covered_auto_holidays,
)

# Месячный ряд с датой КОНЦА месяца — ровно как served-примеры программы.
MONTHLY_EOM = pd.Series(pd.date_range('2022-01-31', periods=48, freq='ME'))
# Тот же ряд с датой НАЧАЛА месяца.
MONTHLY_SOM = pd.Series(pd.date_range('2022-01-01', periods=48, freq='MS'))


def _month_values(dates: pd.Series, dummies: pd.DataFrame, col: str, month: int):
    """Значения дамми col для всех строк заданного календарного месяца."""
    months = pd.to_datetime(dates).dt.month
    return dummies.loc[months == month, col].tolist()


class TestMonthlyFraction:
    """Месячная грануляция: доля дней месяца в окне подготовки."""

    def test_black_friday_stable_every_november(self):
        """ЧП видна КАЖДЫЙ ноябрь и декабрь-хвост (раньше — флаки 2/4 лет).

        Уточнение Антона (v2.2): ЧП — РАСПРОДАЖНЫЙ период, активность идёт
        ОТ старта (~2 недели), не до события: окно [посл. пятница ноября, +13].
        Ноябрь несёт старт (1-6 дней), декабрь — хвост периода.
        """
        d = generate_holiday_dummies(MONTHLY_EOM)
        nov = _month_values(MONTHLY_EOM, d, 'holiday_black_friday', 11)
        dec = _month_values(MONTHLY_EOM, d, 'holiday_black_friday', 12)
        assert len(nov) == 4
        assert all(v > 0 for v in nov), f'ЧП пропала в части ноябрей: {nov}'
        assert all(v > 0 for v in dec), f'хвост распродажи пропал в декабрях: {dec}'
        # 14-дневное окно: старт = посл. пятница ноября (24-30 число) →
        # ноябрьская часть 1-7 дней, декабрьская 7-13 дней.
        assert all(v <= 7 / 30 + 1e-9 for v in nov)
        assert all(v <= 13 / 31 + 1e-9 for v in dec)
        # Вне ноября/декабря ЧП нулевая.
        for m in (1, 5, 7, 10):
            assert all(v == 0 for v in _month_values(MONTHLY_EOM, d, 'holiday_black_friday', m))

    def test_sale_period_runs_from_start(self):
        """Класс sale_period: окно ОТ старта. BF-2022: старт 25 ноя → окно
        [25 ноя, 8 дек]: ноябрь 6/30, декабрь 8/31 (точные доли)."""
        d = generate_holiday_dummies(MONTHLY_EOM)
        years = pd.to_datetime(MONTHLY_EOM).dt.year
        months = pd.to_datetime(MONTHLY_EOM).dt.month
        bf = d['holiday_black_friday']
        assert bf[(years == 2022) & (months == 11)].iloc[0] == pytest.approx(6 / 30, abs=1e-4)
        assert bf[(years == 2022) & (months == 12)].iloc[0] == pytest.approx(8 / 31, abs=1e-4)
        # Cyber Week 7 дней от старта: CM-2022 = 28 ноя → ноябрь 3/30, декабрь 4/31.
        cm = d['holiday_cyber_monday']
        assert cm[(years == 2022) & (months == 11)].iloc[0] == pytest.approx(3 / 30, abs=1e-4)
        assert cm[(years == 2022) & (months == 12)].iloc[0] == pytest.approx(4 / 31, abs=1e-4)

    def test_previously_dead_holidays_alive(self):
        """6 праздников, вечно-нулевых на точечной дате конца месяца, теперь видны."""
        d = generate_holiday_dummies(MONTHLY_EOM)
        expectations = {
            'holiday_valentine': 2,        # 1-14 февраля
            'holiday_defender_day': 2,     # 15-23 февраля
            'holiday_march8': 3,           # 1-8 марта
            'holiday_russia_day': 6,       # 11-12 июня
            'holiday_unity_day': 11,       # 3-4 ноября
            'holiday_cyber_monday': 11,    # пн после ЧП (обычно ноябрь)
        }
        for col, month in expectations.items():
            vals = _month_values(MONTHLY_EOM, d, col, month)
            assert any(v > 0 for v in vals), f'{col}: все нули в месяце {month}'

    def test_fraction_values_exact(self):
        """Точные доли для фиксированных окон (не-високосный 2022)."""
        d = generate_holiday_dummies(MONTHLY_EOM)
        y2022 = pd.to_datetime(MONTHLY_EOM).dt.year == 2022
        months = pd.to_datetime(MONTHLY_EOM).dt.month
        feb22 = d.loc[y2022 & (months == 2), 'holiday_valentine'].iloc[0]
        assert feb22 == pytest.approx(14 / 28, abs=1e-4)   # всё окно в феврале
        mar22 = d.loc[y2022 & (months == 3), 'holiday_march8'].iloc[0]
        assert mar22 == pytest.approx(8 / 31, abs=1e-4)
        dec22 = d.loc[y2022 & (months == 12), 'holiday_newyear_preshop'].iloc[0]
        assert dec22 == pytest.approx(17 / 31, abs=1e-4)   # закупки подарков 15-31 дек
        jun22 = d.loc[y2022 & (months == 6), 'holiday_russia_day'].iloc[0]
        assert jun22 == pytest.approx(2 / 30, abs=1e-4)

    def test_som_eom_invariant(self):
        """Дата начала и конца месяца означают ОДИН месяц → одинаковые дамми."""
        d_eom = generate_holiday_dummies(MONTHLY_EOM)
        d_som = generate_holiday_dummies(MONTHLY_SOM)
        pd.testing.assert_frame_equal(d_eom, d_som, check_dtype=False)

    def test_values_bounded_0_1(self):
        d = generate_holiday_dummies(MONTHLY_EOM)
        assert (d.values >= 0).all() and (d.values <= 1).all()


class TestWeeklyDailyFraction:
    def test_weekly_partial_overlap(self):
        """Неделя, частично попавшая в окно, получает долю — не 0/1 точечной даты."""
        weeks = pd.Series(pd.date_range('2024-12-02', periods=4, freq='7D'))
        d = generate_holiday_dummies(weeks)
        pre = d['holiday_newyear_preshop'].tolist()
        # 02-08 дек: 0 · 09-15 дек: 1 день (15-е) → 1/7 · 16-22 дек: все 7 → 1.0 · 23-29: 1.0
        assert pre[0] == 0.0
        assert pre[1] == pytest.approx(1 / 7, abs=1e-4)
        assert pre[2] == 1.0
        assert pre[3] == 1.0

    def test_daily_degenerates_to_binary(self):
        """Дневная грануляция: fraction вырождается в 0/1; для событий БЕЗ
        v2.0-переопределения окна значения поэлементно равны binary_point.
        (У распродаж окна режимов РАЗНЫЕ by-design: fraction — период от
        старта, binary_point — узкое v2.0-окно для старых моделей.)"""
        from utils.holiday_calendar_ru import HOLIDAY_DEFINITIONS
        days = pd.Series(pd.date_range('2024-12-01', '2024-12-31', freq='D'))
        frac = generate_holiday_dummies(days)
        binary = generate_holiday_dummies(days, mode='binary_point')
        # (а) На daily все доли целые 0/1.
        assert set(float(v) for v in frac.values.ravel()) <= {0.0, 1.0}
        # (б) События без date_range_v20 — идентичны между режимами.
        same_window = [h['name'] for h in HOLIDAY_DEFINITIONS if 'date_range_v20' not in h]
        assert len(same_window) == 10  # все, кроме ЧП и Cyber Monday
        for col in same_window:
            assert (frac[col].values == binary[col].values.astype(float)).all(), col


class TestLegacyBinaryPointMode:
    """binary_point воспроизводит поведение v2.0 — для decompose старых моделей
    (их β обучены на бинарных X; режим приходит из normalization.holiday_dummies_mode)."""

    def test_monthly_eom_legacy_flaky_reproduced(self):
        d = generate_holiday_dummies(MONTHLY_EOM, mode='binary_point')
        years = pd.to_datetime(MONTHLY_EOM).dt.year
        months = pd.to_datetime(MONTHLY_EOM).dt.month
        bf = d['holiday_black_friday']
        # 2022: окно 25-27 ноя, 30-е вне → 0; 2024: окно 29 ноя-1 дек, 30-е внутри → 1.
        assert bf[(years == 2022) & (months == 11)].iloc[0] == 0
        assert bf[(years == 2024) & (months == 11)].iloc[0] == 1
        # Valentine на конце месяца никогда не ловится точечной датой.
        assert (d['holiday_valentine'] == 0).all()

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            generate_holiday_dummies(MONTHLY_EOM, mode='nonsense')


class TestNameDedup:
    """Семантический дедуп авто-инжекта с ручными holiday-колонками.

    Углублён по решению Антона (2026-07-05): клиент не знает нашу конвенцию
    префикса `holiday_` — колонки `black_friday`/`8_марта`/`valentine` тоже
    опознаются. 🔴 Инвариант: ложное гашение (потеря контроля → OVB) опаснее
    пропущенного → whitelist специфичных алиасов, без ложных гашений на
    обычных колонках.
    """

    @pytest.mark.parametrize('a,b', [
        ('holiday_black_friday', 'holiday_blackfriday'),
        ('holiday_black_friday', 'Holiday Black-Friday'),
        ('holiday_newyear_preshop', 'HOLIDAY NEWYEAR PRESHOP'),
    ])
    def test_normalize_equivalence(self, a, b):
        assert normalize_holiday_name(a) == normalize_holiday_name(b)

    def test_user_column_covers_auto(self):
        covered = user_covered_auto_holidays(['date', 'sales', 'holiday_blackfriday'])
        assert covered == {'holiday_black_friday'}

    @pytest.mark.parametrize('col,expected', [
        # Без нашего префикса holiday_ (клиент не знает конвенцию).
        ('black_friday', 'holiday_black_friday'),
        ('blackfriday', 'holiday_black_friday'),
        ('BlackFriday', 'holiday_black_friday'),
        ('promo_black_friday_2024', 'holiday_black_friday'),   # + префикс/суффикс
        ('cyber_monday', 'holiday_cyber_monday'),
        ('back_to_school', 'holiday_back_to_school'),
        ('valentine_promo', 'holiday_valentine'),
        ('defender_day', 'holiday_defender_day'),
        # Русские синонимы.
        ('чёрная_пятница', 'holiday_black_friday'),
        ('черная пятница', 'holiday_black_friday'),
        ('день_россии', 'holiday_russia_day'),
        ('школьные_каникулы', 'holiday_school_breaks'),
        ('женский_день', 'holiday_march8'),
        # Дата-формы (специфичны цифрой месяца).
        ('8_march', 'holiday_march8'),
        ('8марта', 'holiday_march8'),
        ('march8_sales', 'holiday_march8'),
        ('23_февраля', 'holiday_defender_day'),
        ('14_февраля', 'holiday_valentine'),
        ('4_ноября', 'holiday_unity_day'),
        ('9_мая', 'holiday_may_holidays'),
        ('1_сентября', 'holiday_back_to_school'),
    ])
    def test_covers_without_prefix_and_synonyms(self, col, expected):
        assert expected in user_covered_auto_holidays([col]), (
            f'{col!r} не погасил {expected}'
        )

    # 🔴 Анти-ложное-гашение: реалистичные не-праздничные колонки НЕ должны
    # гасить ни один контроль (ложное гашение → OVB). Коварные: mayonnaise (may),
    # russian_market (russia), community (unity), marchmadness (march).
    NON_HOLIDAY_COLUMNS = [
        'sales_rub', 'sales_packs', 'leads', 'tv_spend', 'tv_trp', 'tv_grp',
        'digital_spend', 'digital_impressions', 'ooh_spend', 'ooh_contacts',
        'performance_spend', 'performance_clicks', 'apteka_spend', 'apteka_contacts',
        'retail_media_spend', 'competitor_trp', 'competitor_promo', 'competitor_activity',
        'price_index', 'category_sales', 'weather_temp_low', 'macro_cpi', 'promo_indicator',
        'mayonnaise_sales', 'russian_market', 'community_reach', 'marchmadness_promo',
        'may_revenue', 'unity_engine_ver', 'marketing_budget', 'friday_traffic',
        'monday_sales', 'summer_promo', 'победа_бренд', 'россия_регион', 'школа_танцев',
    ]

    @pytest.mark.parametrize('col', NON_HOLIDAY_COLUMNS)
    def test_no_false_coverage_realistic_columns(self, col):
        assert user_covered_auto_holidays([col]) == set(), (
            f'ЛОЖНОЕ гашение: {col!r} погасил {user_covered_auto_holidays([col])}'
        )

    def test_exact_name_covers_exactly_one(self):
        """Точное авто-имя покрывает РОВНО его (клиент скопировал наш шаблон)."""
        assert user_covered_auto_holidays(['holiday_newyear_preshop']) == {'holiday_newyear_preshop'}

    def test_generic_newyear_covers_both(self):
        """Обобщённый «Новый год» (не наше точное имя) → оба НГ-окна: клиент
        берёт весь НГ-период на себя, авто-дубли гасятся (а не плодятся)."""
        covered = user_covered_auto_holidays(['new_year'])
        assert covered == {'holiday_newyear_preshop', 'holiday_newyear_postsale'}

    def test_ssot_every_definition_has_aliases(self):
        """Каждое авто-событие имеет непустой набор алиасов (не забыли при
        добавлении нового праздника)."""
        from utils.holiday_calendar_ru import HOLIDAY_DEFINITIONS, _HOLIDAY_ALIASES
        for h in HOLIDAY_DEFINITIONS:
            assert _HOLIDAY_ALIASES.get(h['name']), f"нет алиасов для {h['name']}"

    def test_empty(self):
        assert user_covered_auto_holidays([]) == set()


class TestWindowKinds:
    """Классы окон (уточнение Антона 2026-07-05): подготовка ДО события /
    распродажа ОТ старта / календарный период."""

    def test_every_definition_has_window_kind(self):
        from utils.holiday_calendar_ru import HOLIDAY_DEFINITIONS
        allowed = {'preparation', 'sale_period', 'calendar_period'}
        for h in HOLIDAY_DEFINITIONS:
            assert h.get('window_kind') in allowed, (
                f"{h['name']}: window_kind={h.get('window_kind')!r} вне {allowed}"
            )

    def test_expected_classification(self):
        from utils.holiday_calendar_ru import get_holiday_metadata
        expected = {
            'holiday_newyear_preshop': 'preparation',
            'holiday_valentine': 'preparation',
            'holiday_defender_day': 'preparation',
            'holiday_march8': 'preparation',
            'holiday_back_to_school': 'preparation',
            'holiday_newyear_postsale': 'sale_period',
            'holiday_black_friday': 'sale_period',
            'holiday_cyber_monday': 'sale_period',
            'holiday_may_holidays': 'calendar_period',
            'holiday_russia_day': 'calendar_period',
            'holiday_unity_day': 'calendar_period',
            'holiday_school_breaks': 'calendar_period',
        }
        for name, kind in expected.items():
            meta = get_holiday_metadata(name)
            assert meta is not None, name
            assert meta['window_kind'] == kind, (
                f'{name}: window_kind={meta["window_kind"]!r}, ожидалось {kind!r}'
            )

    def test_sale_windows_only_widen_in_fraction_mode(self):
        """v2.0-окна распродаж (узкие) живут ТОЛЬКО в binary_point (старые
        модели); fraction использует новые окна от старта."""
        days = pd.Series(pd.date_range('2022-11-20', '2022-12-15', freq='D'))
        legacy = generate_holiday_dummies(days, mode='binary_point')
        frac = generate_holiday_dummies(days)
        # binary_point: ровно 3 дня ЧП (25-27 ноя 2022) и 1 день CM (28 ноя).
        assert int(legacy['holiday_black_friday'].sum()) == 3
        assert int(legacy['holiday_cyber_monday'].sum()) == 1
        # fraction на daily: 14 дней ЧП-периода и 7 дней Cyber Week.
        assert int(frac['holiday_black_friday'].sum()) == 14
        assert int(frac['holiday_cyber_monday'].sum()) == 7


class TestCollinearityOnFraction:
    def test_expected_overlap_detected(self):
        """NY-postsale × school_breaks (зимние каникулы ⊂ распродаж) ловится и на
        fraction-значениях (>0 семантика; winter break 28дек-8янв целиком в
        postsale 25дек-8янв → overlap 100% по меньшему окну)."""
        days = pd.Series(pd.date_range('2024-01-01', '2024-12-31', freq='D'))
        d = generate_holiday_dummies(days)
        warnings = detect_holiday_collinearity(d)
        pairs = {tuple(sorted((w['holiday_a'], w['holiday_b']))) for w in warnings}
        assert ('holiday_newyear_postsale', 'holiday_school_breaks') in pairs


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
