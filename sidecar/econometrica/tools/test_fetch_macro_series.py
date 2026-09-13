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


def test_parse_cbr_currency_xml_divides_by_nominal():
    """Регресс на реальный дефект, найденный при своде s46: старый код брал
    голое <Value>, игнорируя <Nominal>. У юаня Nominal реально скачет 1↔10
    (cbr_raw/cny.xml, найдено 13.09.2026) – без деления курс был бы занижен
    в 10 раз. Фикстура с Nominal=10 воспроизводит ровно эту схему записи."""
    raw = b"""<?xml version="1.0" encoding="windows-1251"?>
<ValCurs><Record Date="01.09.2016" Id="R01375">
<Nominal>10</Nominal><Value>97,7127</Value></Record>
<Record Date="12.04.2018" Id="R01375">
<Nominal>1</Nominal><Value>10,1915</Value></Record>
</ValCurs>"""
    out = fms._parse_cbr_currency_xml(raw)
    assert out == [
        (dt.date(2016, 9, 1), pytest.approx(9.77127)),
        (dt.date(2018, 4, 12), pytest.approx(10.1915)),
    ]


def test_parse_cbr_currency_xml_real_usd_sample_matches_verified_values():
    """Реальный файл ЦБ (cbr_raw/usd.xml, скачан через московский узел
    13.09.2026, окно 01.09.2016-12.09.2026). Первое/последнее значение
    сверены лично Антоном перед задачей s46 – не синтетика."""
    raw_dir = Path(__file__).resolve().parents[3] / "Projects" / "macro_series_draft" / "cbr_raw"
    raw = (raw_dir / "usd.xml").read_bytes()
    out = fms._parse_cbr_currency_xml(raw)
    assert out[0] == (dt.date(2016, 9, 1), pytest.approx(65.2535))
    assert out[-1] == (dt.date(2026, 9, 12), pytest.approx(84.2569))
    assert len(out) == 2477


def test_parse_cbr_currency_xml_real_cny_sample_nominal_changes_mid_series():
    """Юань – самый рискованный ряд: Nominal реально переключается 1↔10 по
    ходу истории. Проверяем оба режима на настоящем файле, не на фикстуре."""
    raw_dir = Path(__file__).resolve().parents[3] / "Projects" / "macro_series_draft" / "cbr_raw"
    raw = (raw_dir / "cny.xml").read_bytes()
    out = dict(fms._parse_cbr_currency_xml(raw))
    assert out[dt.date(2016, 9, 1)] == pytest.approx(9.77127)  # Nominal=10 в файле
    assert out[dt.date(2018, 4, 12)] == pytest.approx(10.1915)  # Nominal=1 в файле
    assert out[dt.date(2026, 9, 12)] == pytest.approx(12.5519)  # Nominal=1, конец окна


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


def test_parse_cbr_key_rate_xml_real_sample_matches_verified_values():
    """Реальный ответ SOAP (cbr_raw/keyrate_soap.xml, скачан через
    московский узел 13.09.2026). Найдено при своде s46: документация
    называла тег записи <KeyRate>, фактически он <KR> — парсер уже
    ориентировался на факт (name in ("DT","Date") / ("Rate","KeyRate")),
    этот тест закрепляет находку на настоящем файле, не на фикстуре."""
    raw_dir = Path(__file__).resolve().parents[3] / "Projects" / "macro_series_draft" / "cbr_raw"
    raw = (raw_dir / "keyrate_soap.xml").read_bytes()
    out = dict(fms._parse_cbr_key_rate_xml(raw))
    assert out[dt.date(2016, 9, 1)] == pytest.approx(10.5)
    assert out[dt.date(2026, 9, 11)] == pytest.approx(14.0)
    assert len(out) == 2524


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


# ---------------------------------------------------------------------------
# Маршрут через узел (--через-узел) — ssh, без прямого сетевого вызова
# ---------------------------------------------------------------------------


def test_http_get_via_node_calls_ssh_with_curl_and_returns_stdout(monkeypatch):
    monkeypatch.setattr(fms, "NODE_HOST", "moscow-node")
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = b"<ValCurs></ValCurs>"
        stderr = b""

    def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return FakeProc()

    monkeypatch.setattr(fms.subprocess, "run", fake_run)
    out = fms._http_get("https://www.cbr.ru/scripts/XML_dynamic.asp?x=1", timeout=30)
    assert out == b"<ValCurs></ValCurs>"
    assert captured["cmd"][:2] == ["ssh", "moscow-node"]
    assert "curl" in captured["cmd"][2]
    assert "https://www.cbr.ru/scripts/XML_dynamic.asp?x=1" in captured["cmd"][2]
    assert captured["input"] is None


def test_http_post_via_node_pipes_body_and_headers_through_stdin(monkeypatch):
    monkeypatch.setattr(fms, "NODE_HOST", "moscow-node")
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = b"<soap:Envelope></soap:Envelope>"
        stderr = b""

    def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return FakeProc()

    monkeypatch.setattr(fms.subprocess, "run", fake_run)
    out = fms._http_post(
        "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx",
        b"<soap:Envelope/>",
        {"SOAPAction": '"http://web.cbr.ru/KeyRate"', "Content-Type": "text/xml"},
        timeout=30,
    )
    assert out == b"<soap:Envelope></soap:Envelope>"
    assert captured["input"] == b"<soap:Envelope/>"
    assert "-X POST" in captured["cmd"][2]
    assert "SOAPAction" in captured["cmd"][2]


def test_http_get_via_node_nonzero_exit_raises_source_unavailable(monkeypatch):
    monkeypatch.setattr(fms, "NODE_HOST", "moscow-node")

    class FakeProc:
        returncode = 1
        stdout = b""
        stderr = b"ssh: connect to host moscow-node port 22: Connection refused"

    monkeypatch.setattr(fms.subprocess, "run", lambda *a, **k: FakeProc())
    with pytest.raises(fms.SourceUnavailableError, match="moscow-node"):
        fms._http_get("https://www.cbr.ru/scripts/XML_dynamic.asp", timeout=30)


def test_http_get_via_node_timeout_raises_source_unavailable(monkeypatch):
    monkeypatch.setattr(fms, "NODE_HOST", "moscow-node")
    import subprocess as sp

    def fake_run(*a, **k):
        raise sp.TimeoutExpired(cmd="ssh", timeout=30)

    monkeypatch.setattr(fms.subprocess, "run", fake_run)
    with pytest.raises(fms.SourceUnavailableError):
        fms._http_get("https://www.cbr.ru/scripts/XML_dynamic.asp", timeout=30)


def test_http_get_direct_path_unaffected_when_node_not_set(monkeypatch):
    """NODE_HOST=None (по умолчанию) — прямой путь остаётся рабочим, ssh не
    вызывается вовсе (проверка «оставить прямой путь рабочим по умолчанию»)."""
    monkeypatch.setattr(fms, "NODE_HOST", None)

    def fail_if_called(*a, **k):
        raise AssertionError("subprocess.run не должен вызываться без --через-узел")

    monkeypatch.setattr(fms.subprocess, "run", fail_if_called)

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"direct-ok"

    monkeypatch.setattr(fms.urllib.request, "urlopen", lambda req, timeout=30: FakeResp())
    out = fms._http_get("https://www.cbr.ru/scripts/XML_dynamic.asp", timeout=30)
    assert out == b"direct-ok"


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


def test_aggregate_daily_last_by_month_picks_end_of_period_not_mean():
    """«Конец месяца» = последняя ПО ДАТЕ запись, не последняя по порядку
    в списке — проверяем, что порядок ввода не важен (решение 13.09.2026)."""
    daily = [
        (dt.date(2026, 9, 15), 85.0),
        (dt.date(2026, 9, 1), 84.0),
        (dt.date(2026, 9, 30), 86.0),  # позже всех по дате, хотя не последний в списке
    ]
    out = fms.aggregate_daily_last(daily, fms.month_key)
    assert out[(2026, 9)] == pytest.approx(86.0)


def test_aggregate_daily_last_by_week_matches_task_requirement():
    # Понедельник 07.09.2026 — среда 09.09.2026 — одна и та же неделя ISO.
    daily = [
        (dt.date(2026, 9, 7), 84.0),
        (dt.date(2026, 9, 9), 86.5),
    ]
    out = fms.aggregate_daily_last(daily, fms.iso_week_key)
    assert out[fms.iso_week_key(dt.date(2026, 9, 7))] == pytest.approx(86.5)


def test_week_to_month_uses_monday():
    # Неделя 2026-W37 начинается в понедельник 07.09.2026 — тот же месяц.
    monday = dt.date.fromisocalendar(2026, 37, 1)
    assert fms.week_to_month(monday) == (2026, 9)
