"""Канарейка детекторов ролей на КОРПУСЕ ТИПОВЫХ КЛИЕНТСКИХ ИМЁН (аудит 2026-07-05).

Существующая канарейка (test_role_detectors_parity.py) сверяет два детектора на
именах наших served-примеров — чистых, в едином стиле (snake_case). Реальные
клиенты называют колонки иначе: русские слова, пробелы, запятые, единицы в
названии, CamelCase. Этот корпус ловит два класса регресса на клиентском слое:
  1. detect_column_role (роль в UI / Traffic Light) перестал распознавать частую
     клиентскую форму → клиент видит «не найден KPI / медиа / дата»;
  2. два детектора разошлись на клиентском имени (класс Д-1 — apteka/GMV/период).

Корпус вскрыл боем 4 пробела (исправлены): GMV и русское «период» знал только
classify_column, не validator (рассинхрон → «не найден KPI/дата»).

⚠️ Известный НЕ закрытый класс (вынесен рекомендацией Антону, НЕ баг корпуса):
паттерны с зашитым underscore (`курс_доллара`, `индекс_цен`) не матчат
клиентскую форму с ПРОБЕЛОМ («курс доллара»). Здесь underscore-форма проверяется
как позитивный инвариант; пробельные формы макро в строгий корпус НЕ включены.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SIDECAR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from utils.column_detection import classify_column   # noqa: E402
from engines.validator import detect_column_role      # noqa: E402

# Тот же контракт kind→role, что в test_role_detectors_parity (держим локально —
# независимый якорь; при расхождении обоих детекторов от контракта тест краснеет).
KIND_TO_ROLE = {
    'date': 'date', 'target_monetary': 'kpi', 'target_count': 'kpi',
    'monetary': 'media', 'physical': 'media', 'control': 'control',
    'signed_competitor': 'control', 'signed_price': 'control',
    'signed_weather': 'control', 'signed_macro': 'control', 'holiday': 'control',
    'seasonality': 'control', 'category': 'control',
}

# {клиентское имя: роль, которую detect_column_role ОБЯЗАН вернуть}.
# Реалистичные формы: RU/EN, пробелы, запятые, единицы, CamelCase.
CLIENT_CORPUS = {
    # ── KPI ──────────────────────────────────────────────────────────────
    'Продажи, руб': 'kpi', 'Выручка': 'kpi', 'Продажи упаковок': 'kpi',
    'Продажи, шт': 'kpi', 'Количество заказов': 'kpi', 'Заявки': 'kpi',
    'Лиды': 'kpi', 'Leads': 'kpi', 'Revenue': 'kpi', 'GMV': 'kpi',
    # ── Media ────────────────────────────────────────────────────────────
    'ТВ, TRP': 'media', 'Бюджет ТВ': 'media', 'ТВ бюджет': 'media',
    'OLV просмотры': 'media', 'Digital показы': 'media', 'Наружка контакты': 'media',
    'Performance клики': 'media', 'Радио GRP': 'media', 'Контекст клики': 'media',
    'TV Spend': 'media', 'Search clicks': 'media',
    # ── Controls ─────────────────────────────────────────────────────────
    'Цена': 'control', 'Индекс цен': 'control', 'Средняя цена': 'control',
    'SOV конкурентов': 'control', 'Погода': 'control', 'Температура': 'control',
    'Праздники': 'control', 'Дистрибуция': 'control', 'Инфляция': 'control',
    # ── Date ─────────────────────────────────────────────────────────────
    'Дата': 'date', 'Месяц': 'date', 'Период': 'date', 'Week': 'date',
}

CORPUS_ITEMS = sorted(CLIENT_CORPUS.items())


@pytest.mark.parametrize('name,want', CORPUS_ITEMS, ids=[n for n, _ in CORPUS_ITEMS])
def test_validator_assigns_expected_role(name, want):
    """detect_column_role распознаёт типовое клиентское имя в ожидаемую роль."""
    role = detect_column_role(name)
    assert role == want, (
        f'{name!r}: detect_column_role вернул {role!r}, ожидалось {want!r} — '
        f'клиент увидит «не найден {want}» / неверную роль в UI'
    )


@pytest.mark.parametrize('name,want', CORPUS_ITEMS, ids=[n for n, _ in CORPUS_ITEMS])
def test_detectors_not_contradicting(name, want):
    """classify_column не ПРОТИВОРЕЧИТ validator: либо unknown (не мешает), либо
    его kind по контракту даёт ту же роль. Ловит рассинхрон класса Д-1."""
    kind = classify_column(name)
    if kind == 'unknown':
        return  # тонкий детектор промолчал — не противоречие (валидатор рулит ролью)
    mapped = KIND_TO_ROLE.get(kind)
    assert mapped == want, (
        f'{name!r}: classify_column→kind={kind!r} даёт роль {mapped!r}, а validator '
        f'ожидает {want!r} — детекторы разошлись (правь оба)'
    )


class TestHolidayClientForms:
    """Аудит №4 (2026-07-05): клиентские событийные дамми БЕЗ префикса holiday_.

    Дыра Д2: `black_friday` без префикса падала в unknown→unused у ОБОИХ
    детекторов, а углублённый дедуп при этом гасил авто-инжект → контроль
    события терялся ПОЛНОСТЬЮ (OVB молча — хуже дубля). FIX: SSOT-предикат
    is_holiday_like_name (те же алиасы, та же анти-ложная защита) в обоих
    детекторах: classify→'holiday' (до generic-date: «день_россии» ловился
    ложной датой), validator→'control'.
    """

    HOLIDAY_FORMS = [
        'black_friday', 'blackfriday', 'чёрная_пятница', 'черная пятница',
        'cyber_monday', 'back_to_school', 'школьные_каникулы', 'valentine',
        '8_марта', '23_февраля', '14_февраля', '1_сентября', '9_мая',
        'день_россии', 'день_победы', 'майские_праздники', '4_ноября',
    ]

    @pytest.mark.parametrize('name', HOLIDAY_FORMS)
    def test_validator_gives_control(self, name):
        assert detect_column_role(name) == 'control', (
            f'{name!r}: событийная дамми не распознана контролом — уйдёт в '
            f'unused, а дедуп погасит авто-инжект → контроль потерян (OVB)'
        )

    @pytest.mark.parametrize('name', HOLIDAY_FORMS)
    def test_classify_gives_holiday(self, name):
        assert classify_column(name) == 'holiday', (
            f'{name!r}: classify_column дал {classify_column(name)!r} — '
            f'prior/полоса декомпозиции разойдутся с ролью control'
        )

    @pytest.mark.parametrize('name', [
        'валентина_план',    # имя человека — не событие (сужение алиаса Д1)
        'день_недели',       # generic date, не праздник
        'friday_traffic', 'monday_sales', 'школа_танцев',
        'победа_бренд', 'россия_регион', 'сентябрь_продажи',
    ])
    def test_no_false_holiday(self, name):
        assert classify_column(name) != 'holiday', (
            f'ЛОЖНЫЙ holiday: {name!r}'
        )


class TestUnderscoreMacroPositive:
    """Позитивный инвариант: макро/цена в НАШЕЙ underscore-форме распознаются.

    Пробельная клиентская форма («курс доллара») — известный пробел паттернов
    (рекомендация Антону), в строгий корпус не включена. Здесь фиксируем, что
    хотя бы underscore-форма работает — регресс её потери будет пойман."""

    @pytest.mark.parametrize('name', [
        'курс_доллара', 'курс_рубля', 'usd_rub', 'exchange_rate', 'cpi', 'инфляция',
    ])
    def test_macro_underscore_is_control(self, name):
        assert detect_column_role(name) == 'control', (
            f'{name!r}: макро-контроль в underscore-форме не распознан'
        )

    @pytest.mark.parametrize('name', ['price_index', 'индекс_цен', 'unit_price'])
    def test_price_underscore_is_control(self, name):
        assert detect_column_role(name) == 'control'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
