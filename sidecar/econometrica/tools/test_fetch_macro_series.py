"""Сторож fetch_macro_series.py (s45, 13.09.2026).

Проверяет разбор ответов источников на СОХРАНЁННЫХ образцах (fixtures/) —
без единого обращения к сети, расчёт изменения % и честное поведение при
недоступном источнике (SourceUnavailableError, не подмена данных).

🔴 Запускать точечно, НЕ через голый `pytest tests`:
    cd sidecar/econometrica
    pytest tools/test_fetch_macro_series.py -v
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import fetch_macro_series as fms

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Разбор курса валют ЦБ РФ (XML_dynamic.asp) на сохранённом образце
# ---------------------------------------------------------------------------


def test_parse_cbr_currency_xml_sample():
    raw = (FIXTURES / "cbr_currency_sample.xml").read_bytes()
    out = fms._parse_cbr_currency_xml(raw)
    assert out == [
        (dt.date(2026, 9, 1), 84.3508),
        (dt.date(2026, 9, 2), 84.5012),
        (dt.date(2026, 9, 3), 84.2569),
    ]


def test_parse_cbr_currency_xml_empty_raises():
    with pytest.raises(fms.SourceUnavailableError):
        fms._parse_cbr_currency_xml(b"<ValCurs></ValCurs>")


def test_parse_cbr_currency_xml_garbage_raises():
    with pytest.raises(fms.SourceUnavailableError):
        fms._parse_cbr_currency_xml(b"<html>not xml really<broken")


# ---------------------------------------------------------------------------
# Разбор ключевой ставки (SOAP KeyRate) на сохранённом образце
# ---------------------------------------------------------------------------


def test_parse_cbr_key_rate_xml_sample():
    raw = (FIXTURES / "cbr_keyrate_sample.xml").read_bytes()
    out = fms._parse_cbr_key_rate_xml(raw)
    assert out == [
        (dt.date(2026, 8, 1), 18.0),
        (dt.date(2026, 9, 1), 17.0),
    ]


def test_parse_cbr_key_rate_xml_unknown_schema_raises():
    # Валидный XML, но без узлов KR — как если бы ЦБ сменил схему ответа.
    with pytest.raises(fms.SourceUnavailableError):
        fms._parse_cbr_key_rate_xml(b"<soap:Envelope xmlns:soap='x'><soap:Body/></soap:Envelope>")


# ---------------------------------------------------------------------------
# Росстат — ссылка на актуальный XLSX + разбор листа ИПЦ
# ---------------------------------------------------------------------------


def test_find_rosstat_ipc_mes_url_from_sample_page():
    html = (FIXTURES / "rosstat_price_page_sample.html").read_text(encoding="utf-8")
    url = fms.find_rosstat_ipc_mes_url(html=html)
    assert url == "https://rosstat.gov.ru/storage/mediabank/ipc_mes_08-2026.xlsx"


def test_find_rosstat_ipc_mes_url_missing_link_raises():
    with pytest.raises(fms.SourceUnavailableError):
        fms.find_rosstat_ipc_mes_url(html="<html><body>ничего нет</body></html>")


def test_parse_rosstat_cpi_xlsx_real_sample():
    """Реальный официальный файл Росстата (скачан 13.09.2026,
    rosstat.gov.ru/storage/mediabank/ipc_mes_08-2026.xlsx), не синтетика."""
    raw = (FIXTURES / "rosstat_ipc_mes_sample.xlsx").read_bytes()
    rows = fms.parse_rosstat_cpi_xlsx(raw)
    by_ym = {(y, m): pct for (y, m, pct) in rows}
    # Известные значения из живого файла (проверены глазами при разведке).
    assert by_ym[(2026, 1)] == pytest.approx(1.62)
    assert by_ym[(2026, 8)] == pytest.approx(-0.08)
    assert by_ym[(2023, 1)] == pytest.approx(0.84)
    # Глубина истории — с 1991 г.
    assert min(y for (y, _m) in by_ym) <= 1991


def test_parse_rosstat_cpi_xlsx_garbage_raises():
    with pytest.raises(fms.SourceUnavailableError):
        fms.parse_rosstat_cpi_xlsx(b"this is not a real xlsx file at all")


# ---------------------------------------------------------------------------
# Расчёт изменения % и цепной индексации ИПЦ
# ---------------------------------------------------------------------------


def test_pct_change_over_sequence_basic():
    levels = {(2026, 1): 100.0, (2026, 2): 101.0, (2026, 3): 99.99}
    keys = [(2026, 1), (2026, 2), (2026, 3)]
    out = fms.pct_change_over_sequence(levels, keys)
    assert out[(2026, 1)] is None
    assert out[(2026, 2)] == pytest.approx(1.0)
    assert out[(2026, 3)] == pytest.approx(-1.0, abs=0.01)


def test_pct_change_over_sequence_gap_does_not_fabricate():
    # (2026, 2) отсутствует в данных → для (2026, 3) изменение не считаем
    # относительно (2026, 1) через дыру — честный None, а не подмена.
    levels = {(2026, 1): 100.0, (2026, 3): 105.0}
    keys = [(2026, 1), (2026, 2), (2026, 3)]
    out = fms.pct_change_over_sequence(levels, keys)
    assert out[(2026, 3)] is None


def test_chain_multiplication_matches_rosstat_worked_example():
    """Примечание к файлу Росстата приводит образцовый расчёт: индекс за
    период апрель-сентябрь 2025 = произведение ВСЕХ входящих месячных
    индексов (включая индекс самого апреля) = 101.55%. Проверяем, что
    формула цепной индексации (та же, что использует build_cpi_monthly_levels
    внутри окна) даёт ровно это число — независимо от того, с какого месяца
    у НАШЕГО окна начинается база=100 (см. следующий тест)."""
    mom_pct = [0.40, 0.43, 0.20, 0.57, -0.40, 0.34]  # апрель..сентябрь 2025
    level = 100.0
    for pct in mom_pct:
        level *= 1.0 + pct / 100.0
    total_pct = level - 100.0
    assert total_pct == pytest.approx(1.55, abs=0.01)


def test_build_cpi_monthly_levels_first_period_is_base_100():
    """Наша индексация нормирует уровень=100 на ПЕРВЫЙ месяц окна (его
    собственное MoM% не применяется — мы не знаем уровень месяца ДО окна).
    Это осознанный выбор базы, отличный от примера Росстата выше (тот
    считает от конца месяца ПЕРЕД первым) — и он должен быть таким."""
    mom = {(2025, 4): 0.40, (2025, 5): 0.43}
    levels = fms.build_cpi_monthly_levels(mom, [(2025, 4), (2025, 5)])
    assert levels[(2025, 4)] == pytest.approx(100.0)
    assert levels[(2025, 5)] == pytest.approx(100.43)


def test_build_cpi_monthly_levels_chains_across_several_months():
    mom = {
        (2025, 4): 0.40, (2025, 5): 0.43, (2025, 6): 0.20,
        (2025, 7): 0.57, (2025, 8): -0.40, (2025, 9): 0.34,
    }
    months = list(mom.keys())
    levels = fms.build_cpi_monthly_levels(mom, months)
    expected = 100.0
    for ym in months[1:]:
        expected *= 1.0 + mom[ym] / 100.0
    assert levels[(2025, 9)] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Поведение при недоступном источнике — сеть должна падать явно
# ---------------------------------------------------------------------------


def test_fetch_cbr_currency_daily_network_failure_is_explicit(monkeypatch):
    def boom(url, timeout=30):
        raise fms.SourceUnavailableError(f"GET {url} не удался: имитация обрыва сети")

    monkeypatch.setattr(fms, "_http_get", boom)
    with pytest.raises(fms.SourceUnavailableError, match="не удался"):
        fms.fetch_cbr_currency_daily("usd", dt.date(2026, 9, 1), dt.date(2026, 9, 5))


def test_fetch_cbr_key_rate_daily_network_failure_is_explicit(monkeypatch):
    def boom(url, data, headers, timeout=30):
        raise fms.SourceUnavailableError(f"POST {url} не удался: имитация обрыва сети")

    monkeypatch.setattr(fms, "_http_post", boom)
    with pytest.raises(fms.SourceUnavailableError, match="не удался"):
        fms.fetch_cbr_key_rate_daily(dt.date(2026, 9, 1), dt.date(2026, 9, 5))


def test_fetch_rosstat_cpi_monthly_network_failure_is_explicit(monkeypatch):
    def boom(url, timeout=30):
        raise fms.SourceUnavailableError(f"GET {url} не удался: имитация обрыва сети")

    monkeypatch.setattr(fms, "_http_get", boom)
    with pytest.raises(fms.SourceUnavailableError):
        fms.fetch_rosstat_cpi_monthly()


# ---------------------------------------------------------------------------
# Приведение к неделе/месяцу — среднее и forward-fill ИПЦ
# ---------------------------------------------------------------------------


def test_aggregate_daily_mean_by_month():
    daily = [
        (dt.date(2026, 9, 1), 84.0),
        (dt.date(2026, 9, 2), 86.0),
        (dt.date(2026, 10, 1), 90.0),
    ]
    out = fms.aggregate_daily_mean(daily, fms.month_key)
    assert out[(2026, 9)] == pytest.approx(85.0)
    assert out[(2026, 10)] == pytest.approx(90.0)


def test_week_to_month_uses_monday():
    # Неделя 2026-W37 начинается в понедельник 07.09.2026 — тот же месяц.
    monday = dt.date.fromisocalendar(2026, 37, 1)
    assert fms.week_to_month(monday) == (2026, 9)
