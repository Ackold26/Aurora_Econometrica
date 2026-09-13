#!/usr/bin/env python3
"""fetch_macro_series.py – загрузчик пяти макропоказателей для Optimizer MMM.

Справочник закрыт владельцем (13.09.2026): доллар, евро, юань, ключевая
ставка, индекс потребительских цен (ИПЦ) – все пять из официальных
источников ЦБ РФ и Росстата.

🔴 INV-50: ряды не выдумывать. Каждое значение обязано происходить из
официального источника. При недоступности источника или неожиданном
формате ответа функции этого файла поднимают SourceUnavailableError –
колонка остаётся пустой, а не подставленной. Никакой синтетики,
интерполяции «на глаз» и данных из памяти модели.

Источники (разведка 13.09.2026, см. Projects/PULSE_s45_macro.md):

  курс_доллара / курс_евро / курс_юаня
    ЦБ РФ, XML_dynamic.asp – https://www.cbr.ru/scripts/XML_dynamic.asp
    Параметры: date_req1/date_req2 (DD/MM/YYYY), VAL_NM_RQ (внутренний код
    валюты ЦБ: USD=R01235, EUR=R01239, CNY=R01375). Формат: XML,
    windows-1251, десятичная запятая, курс = Value / Nominal (Nominal НЕ
    всегда 1 – у юаня скачет 1↔10 на истории, проверено на реальном файле
    cbr_raw/cny.xml 13.09.2026; без деления курс был бы занижен в 10 раз на
    части окна – находка при своде s46, правка внесена и покрыта сторожем).
    Официальный курс устанавливается по рабочим дням (не каждый календарный
    день). История – с 1992 г.
    🔴 cbr.ru недоступен из dev-песочницы этой сессии: DNS резолвится
    (185.178.208.7), но TCP-соединение на 443 не устанавливается –
    таймаут, воспроизведено и через curl, и через внешнюю инфраструктуру
    WebFetch. Похоже на гео-фильтрацию исходящих адресов не из РФ (частый
    паттерн для государственных/банковских сайтов РФ). На машине владельца
    доступ должен быть – это ограничение среды разработки, не адреса.
    Обход (13.09.2026, s46): параметр CLI --через-узел <имя из
    ~/.ssh/config> – скачивание выполняется на узле по ssh, файл
    забирается потоком (пароль не запрашивается, ключ не хранится –
    расчёт на уже поднятый ssh-агент); прямой путь остаётся рабочим по
    умолчанию, потому что доступ у машин разный. Отдельно параметр
    --cbr-raw-dir <каталог> позволяет один раз скормить уже скачанные
    вручную usd.xml/eur.xml/cny.xml/keyrate_soap.xml (обходит сеть только
    для этих четырёх рядов – ИПЦ всё равно тянется с Росстата, он доступен
    напрямую с этой машины).

  ключевая_ставка
    ЦБ РФ, SOAP веб-сервис DailyInfoWebServ/DailyInfo.asmx, метод KeyRate –
    https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx (SOAPAction
    "http://web.cbr.ru/KeyRate", тело – FromDate/ToDate). Официальный метод,
    задокументирован независимо (1С-интеграции, инфостарт и т.д.).
    🔴 Схема ответа СВЕРЕНА вживую 13.09.2026 на реальном файле
    (Projects/macro_series_draft/cbr_raw/keyrate_soap.xml, 2524 записи,
    скачан через московский узел – см. находку №2 закрыта в
    PULSE_s46_macro_merge.md): документация ошибалась в имени тега записи
    (по ней – <KeyRate>, фактически – <KR>), а вложенные поля <DT>/<Rate>
    документация указала верно. Парсер ниже ищет именно <KR><DT>/<Rate> по
    факту содержимого, а не по документации, и падает с полным ответом в
    тексте ошибки, если не найдёт ни одной пары.

  индекс_потребительских_цен (ИПЦ)
    Росстат, официальный XLSX. Страница https://rosstat.gov.ru/statistics/price
    содержит ссылку на файл "ipc_mes_MM-YYYY.xlsx" (имя МЕНЯЕТСЯ каждый
    месяц – поэтому загрузчик сначала скрейпит страницу и достаёт текущую
    ссылку, а не хранит её захардкоженной). Лист "01" книги – индекс на
    товары и услуги по РФ, блок "к концу предыдущего месяца": значения вида
    101.62 = +1.62% к предыдущему месяцу. История – с 1991 г., помесячно.
    🔴 Находка №3: официального ПОНЕДЕЛЬНОГО агрегата ИПЦ Росстат не
    публикует. Проверено: соседний файл "Nedel_ipc.xlsx" ("еженедельный
    мониторинг цен") – это ~116 отдельных товаров/услуг (говядина, масло,
    услуги и т.д.), НЕ композитный индекс, использовать как замену ИПЦ
    нельзя (другой показатель). Понедельные значения ИПЦ в этом загрузчике
    – честный forward-fill месячного значения (см. build_output ниже), не
    отдельный недельный расчёт.

Приведение к периоду (неделя/месяц) и обоснование выбора (пересмотрено
13.09.2026 по прямому указанию Антона при своде реальных рядов ЦБ –
см. Projects/PULSE_s46_macro_merge.md):

  Курс и ключевая ставка, МЕСЯЧНЫЙ ряд – ДВЕ колонки: «_уровень» (среднее
  доступных официальных дневных значений внутри месяца, ОСНОВНАЯ колонка,
  от неё же считается «_изменение_pct») и «_уровень_конец_месяца»
  (последнее по дате значение внутри месяца). Среднее выбрано основным,
  потому что показывает условия, в которых бизнес принимал решения на
  протяжении всего месяца, тогда как «конец месяца» – случайный
  однодневный снимок, легко искажаемый разовым скачком на валютном рынке;
  для ставки среднее к тому же честно отражает смену ставки в середине
  месяца (была 18%, стала 17% – среднее покажет промежуточное значение, а
  не одну из границ). «Конец месяца» держим отдельной колонкой – это
  устоявшийся ориентир для отчётности (курс ЦБ «на конец периода»),
  который тоже нужен читателю таблицы.

  Курс и ключевая ставка, НЕДЕЛЬНЫЙ ряд – ОДНА колонка «_уровень» = значение
  НА КОНЕЦ недели (последнее по дате значение внутри недели), не среднее.
  Прямое указание к своду 13.09.2026: на недельном шаге снимок «где рынок
  оказался к концу недели» важнее среднего за 5 рабочих дней.

  ИПЦ – месячное значение MoM% берётся напрямую из файла Росстата (не
  пересчитывается заново), уровень – цепная (chain-linked) индексация от
  MoM%, ровно по формуле, которую Росстат сам приводит в примечании к
  файлу («индекс за период = произведение входящих в него месячных
  индексов»). У ИПЦ нет дневной гранулярности – официально публикуется
  ровно одно значение в месяц, поэтому колонка «_уровень_конец_месяца»
  для ИПЦ численно совпадает с «_уровень» (не второй независимый расчёт,
  честное отражение того, что источник даёт одну точку в месяц, а не
  фабрикация отдельного значения). Понедельно – forward-fill месячного
  значения (см. находку №3).

Изменение % – везде «к предыдущему периоду ТОЙ ЖЕ частоты»:
  (уровень_t / уровень_{t-1} - 1) * 100, посчитано по колонке уровня той же
  таблицы (курсы/ставка/ИПЦ – единая формула, без исключений).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import logging
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import openpyxl
except ImportError as exc:  # pragma: no cover - уже в requirements.txt sidecar
    raise SystemExit(
        "Нужен openpyxl (см. sidecar/econometrica/requirements.txt): " + str(exc)
    )

LOG = logging.getLogger("fetch_macro_series")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "AuroraEconometricaMacroLoader/1.0"
)


class SourceUnavailableError(RuntimeError):
    """Источник недоступен или отдал неожиданный формат.

    Намеренно НЕ перехватывается тихо внутри модуля дальше уровня отдельного
    показателя – вызывающий код (main) ловит её сам и оставляет колонку
    пустой. INV-50: пустой ряд честнее выдуманного.
    """


# ---------------------------------------------------------------------------
# HTTP-примитивы (только стандартная библиотека – новых зависимостей нет)
# ---------------------------------------------------------------------------


# Имя узла из ~/.ssh/config, если задан --через-узел – маршрут для машин,
# с которых cbr.ru недоступен напрямую (гео-фильтрация). None = прямой путь
# по умолчанию (см. докстринг модуля). Ключ не хранится, пароль не
# запрашивается – расчёт на уже поднятый ssh-агент.
NODE_HOST: str | None = None


def _run_on_node(remote_cmd: str, timeout: int, input_data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["ssh", NODE_HOST, remote_cmd],
            input=input_data,
            capture_output=True,
            timeout=timeout + 15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise SourceUnavailableError(
            f"ssh {NODE_HOST} не удался: {exc!r}"
        ) from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:300]
        raise SourceUnavailableError(
            f"скачивание через узел {NODE_HOST} упало (код {proc.returncode}): {stderr}"
        )
    return proc.stdout


def _http_get(url: str, timeout: int = 30) -> bytes:
    if NODE_HOST:
        remote_cmd = (
            f"curl -sS --max-time {timeout} -A {shlex.quote(USER_AGENT)} "
            f"{shlex.quote(url)}"
        )
        return _run_on_node(remote_cmd, timeout)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailableError(f"GET {url} не удался: {exc!r}") from exc


def _http_post(url: str, data: bytes, headers: dict, timeout: int = 30) -> bytes:
    if NODE_HOST:
        header_flags = " ".join(
            f"-H {shlex.quote(f'{k}: {v}')}" for k, v in headers.items()
        )
        remote_cmd = (
            f"curl -sS --max-time {timeout} -X POST --data-binary @- "
            f"{header_flags} {shlex.quote(url)}"
        )
        return _run_on_node(remote_cmd, timeout, input_data=data)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailableError(f"POST {url} не удался: {exc!r}") from exc


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# ЦБ РФ – курсы валют (XML_dynamic.asp)
# ---------------------------------------------------------------------------

CBR_XML_DYNAMIC_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"

CBR_CURRENCY_CODES = {
    "usd": "R01235",  # доллар США
    "eur": "R01239",  # евро
    "cny": "R01375",  # юань
}


def fetch_cbr_currency_daily(
    code: str, date_from: dt.date, date_to: dt.date
) -> list[tuple[dt.date, float]]:
    val_id = CBR_CURRENCY_CODES[code]
    url = (
        f"{CBR_XML_DYNAMIC_URL}?date_req1={date_from:%d/%m/%Y}"
        f"&date_req2={date_to:%d/%m/%Y}&VAL_NM_RQ={val_id}"
    )
    raw = _http_get(url)
    return _parse_cbr_currency_xml(raw)


def _parse_cbr_currency_xml(raw: bytes) -> list[tuple[dt.date, float]]:
    try:
        text = raw.decode("windows-1251")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceUnavailableError(
            f"ЦБ РФ вернул не-XML ответ: {text[:300]!r}"
        ) from exc

    out: list[tuple[dt.date, float]] = []
    for record in root.findall("Record"):
        date_str = record.get("Date")
        value_el = record.find("Value")
        if not date_str or value_el is None or not value_el.text:
            continue
        date = dt.datetime.strptime(date_str, "%d.%m.%Y").date()
        raw_value = float(value_el.text.replace(",", "."))
        # 🔴 Курс = Value / Nominal, НЕ голое Value. У юаня Nominal скачет
        # 1↔10 на истории (проверено на реальном файле cbr_raw/cny.xml,
        # 13.09.2026) – без деления курс занижен в 10 раз на части окна.
        nominal_el = record.find("Nominal")
        nominal = float(nominal_el.text) if nominal_el is not None and nominal_el.text else 1.0
        value = raw_value / nominal
        out.append((date, value))

    if not out:
        raise SourceUnavailableError(
            "ЦБ РФ вернул XML без единой записи Record – возможно, сменился "
            f"формат. Начало ответа: {text[:300]!r}"
        )
    out.sort()
    return out


# ---------------------------------------------------------------------------
# ЦБ РФ – ключевая ставка (SOAP DailyInfo.asmx / KeyRate)
# ---------------------------------------------------------------------------

CBR_SOAP_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
CBR_SOAP_ACTION = "http://web.cbr.ru/KeyRate"
CBR_SOAP_NS = "http://web.cbr.ru/"

_KEY_RATE_SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xmlns:xsd="http://www.w3.org/2001/XMLSchema" \
xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRate xmlns="{ns}">
      <FromDate>{date_from}</FromDate>
      <ToDate>{date_to}</ToDate>
    </KeyRate>
  </soap:Body>
</soap:Envelope>"""


def fetch_cbr_key_rate_daily(
    date_from: dt.date, date_to: dt.date
) -> list[tuple[dt.date, float]]:
    body = _KEY_RATE_SOAP_TEMPLATE.format(
        ns=CBR_SOAP_NS,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    ).encode("utf-8")
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{CBR_SOAP_ACTION}"',
        "User-Agent": USER_AGENT,
    }
    raw = _http_post(CBR_SOAP_URL, body, headers)
    return _parse_cbr_key_rate_xml(raw)


def _parse_cbr_key_rate_xml(raw: bytes) -> list[tuple[dt.date, float]]:
    """См. предупреждение в докстринге модуля – схема не проверена вживую."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("windows-1251", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceUnavailableError(
            f"ЦБ РФ (KeyRate) вернул не-XML ответ: {text[:500]!r}"
        ) from exc

    out: list[tuple[dt.date, float]] = []
    for el in root.iter():
        if _strip_ns(el.tag) != "KR":
            continue
        dt_el = rate_el = None
        for child in el:
            name = _strip_ns(child.tag)
            if name in ("DT", "Date"):
                dt_el = child
            elif name in ("Rate", "KeyRate"):
                rate_el = child
        if dt_el is None or rate_el is None or not dt_el.text or not rate_el.text:
            continue
        date = dt.datetime.fromisoformat(dt_el.text[:10]).date()
        rate = float(rate_el.text.replace(",", "."))
        out.append((date, rate))

    if not out:
        raise SourceUnavailableError(
            "ЦБ РФ (KeyRate) не отдал ни одной распознанной записи "
            "<KR><DT>/<Rate> – схема ответа отличается от документированной, "
            f"нужна сверка вручную. Начало ответа: {text[:500]!r}"
        )
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Росстат – ИПЦ (XLSX, лист "01")
# ---------------------------------------------------------------------------

ROSSTAT_PRICE_PAGE = "https://rosstat.gov.ru/statistics/price"
ROSSTAT_HOST = "https://rosstat.gov.ru"
_IPC_MES_HREF_RE = re.compile(r'href="(/storage/mediabank/ipc_mes_\d{2}-\d{4}\.xlsx)"')

MONTHS_RU = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def find_rosstat_ipc_mes_url(html: str | None = None) -> str:
    if html is None:
        html = _http_get(ROSSTAT_PRICE_PAGE).decode("utf-8", errors="replace")
    match = _IPC_MES_HREF_RE.search(html)
    if not match:
        raise SourceUnavailableError(
            "На странице rosstat.gov.ru/statistics/price не нашлась ссылка "
            "ipc_mes_MM-YYYY.xlsx – структура страницы изменилась."
        )
    return ROSSTAT_HOST + match.group(1)


def fetch_rosstat_cpi_monthly() -> list[tuple[int, int, float]]:
    """[(год, месяц, MoM_%)] – официальный Росстат, лист '01', блок
    'к концу предыдущего месяца' (ИПЦ на товары и услуги в целом)."""
    url = find_rosstat_ipc_mes_url()
    raw = _http_get(url)
    return parse_rosstat_cpi_xlsx(raw)


def parse_rosstat_cpi_xlsx(raw: bytes) -> list[tuple[int, int, float]]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    except Exception as exc:  # noqa: BLE001 – openpyxl кидает разные типы на битый файл
        raise SourceUnavailableError(f"XLSX Росстата не читается: {exc!r}") from exc
    if "01" not in wb.sheetnames:
        raise SourceUnavailableError(
            f"В книге Росстата нет листа '01' (общий ИПЦ). Листы: {wb.sheetnames}"
        )
    ws = wb["01"]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 4:
        raise SourceUnavailableError("Лист '01' Росстата короче ожидаемого.")

    year_row = rows[3]
    years: dict[int, int] = {
        col_idx: val for col_idx, val in enumerate(year_row) if isinstance(val, int)
    }
    if not years:
        raise SourceUnavailableError(
            f"В строке 4 листа '01' не нашлось ни одного года. Строка: {year_row!r}"
        )

    out: list[tuple[int, int, float]] = []
    for offset, month_name in enumerate(MONTHS_RU):
        row_idx = 5 + offset  # строка 6 = январь (индекс 5), ... строка 17 = декабрь
        if row_idx >= len(rows):
            break
        row = rows[row_idx]
        label = str(row[0] or "").strip().lower()
        if label != month_name:
            raise SourceUnavailableError(
                f"Строка {row_idx + 1} листа '01' – {row[0]!r}, ожидался "
                f"{month_name!r}. Структура файла Росстата изменилась."
            )
        for col_idx, year in years.items():
            if col_idx >= len(row):
                continue
            value = row[col_idx]
            if not isinstance(value, (int, float)):
                continue
            out.append((year, offset + 1, float(value) - 100.0))

    if not out:
        raise SourceUnavailableError(
            "Не удалось разобрать ни одного месяца ИПЦ из XLSX Росстата."
        )
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Приведение к периодам (неделя/месяц) + изменение %
# ---------------------------------------------------------------------------


def iso_week_key(d: dt.date) -> tuple[int, int]:
    year, week, _ = d.isocalendar()
    return (year, week)


def month_key(d: dt.date) -> tuple[int, int]:
    return (d.year, d.month)


def aggregate_daily_mean(
    daily: list[tuple[dt.date, float]], key_fn
) -> dict[tuple[int, int], float]:
    """Среднее доступных дневных значений внутри периода (см. докстринг
    модуля – обоснование выбора «среднее» как основной колонки уровня)."""
    buckets: dict[tuple[int, int], list[float]] = {}
    for date, value in daily:
        buckets.setdefault(key_fn(date), []).append(value)
    return {k: sum(v) / len(v) for k, v in buckets.items()}


def aggregate_daily_last(
    daily: list[tuple[dt.date, float]], key_fn
) -> dict[tuple[int, int], float]:
    """Значение на КОНЕЦ периода – последнее по дате доступное дневное
    значение внутри периода (не среднее). Используется для отдельной
    колонки «_конец_месяца» в месячной таблице и как основная колонка
    недельной таблицы (решение Антона 13.09.2026, см. докстринг модуля)."""
    buckets: dict[tuple[int, int], tuple[dt.date, float]] = {}
    for date, value in daily:
        key = key_fn(date)
        prev = buckets.get(key)
        if prev is None or date > prev[0]:
            buckets[key] = (date, value)
    return {k: v[1] for k, v in buckets.items()}


def pct_change_over_sequence(
    levels: dict[tuple[int, int], float], ordered_keys: list[tuple[int, int]]
) -> dict[tuple[int, int], float | None]:
    """Изменение % к непосредственно предыдущему периоду В ЭТОЙ ЖЕ
    последовательности (пропуски в данных не «перепрыгиваются»: если
    предыдущий период пуст, изменение для текущего – None, не подделка)."""
    out: dict[tuple[int, int], float | None] = {}
    prev_key = None
    for k in ordered_keys:
        if k not in levels:
            prev_key = None
            continue
        if prev_key is not None and prev_key in levels and levels[prev_key]:
            out[k] = (levels[k] / levels[prev_key] - 1.0) * 100.0
        else:
            out[k] = None
        prev_key = k
    return out


def full_week_sequence(date_from: dt.date, date_to: dt.date) -> list[tuple[int, int]]:
    seq = []
    d = date_from - dt.timedelta(days=date_from.weekday())  # понедельник недели date_from
    end = date_to
    seen = set()
    while d <= end:
        k = iso_week_key(d)
        if k not in seen:
            seq.append(k)
            seen.add(k)
        d += dt.timedelta(days=1)
    return seq


def full_month_sequence(date_from: dt.date, date_to: dt.date) -> list[tuple[int, int]]:
    seq = []
    y, m = date_from.year, date_from.month
    while (y, m) <= (date_to.year, date_to.month):
        seq.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return seq


def build_cpi_monthly_levels(
    mom_by_ym: dict[tuple[int, int], float], ordered_months: list[tuple[int, int]]
) -> dict[tuple[int, int], float]:
    """Цепная (chain-linked) индексация: уровень = 100 на первый месяц
    окна, дальше – произведение (1 + MoM%/100) официальных Росстата
    значений. Ровно формула из примечания к файлу Росстата (см. докстринг)."""
    levels: dict[tuple[int, int], float] = {}
    level = 100.0
    started = False
    for ym in ordered_months:
        if ym not in mom_by_ym:
            continue
        if not started:
            levels[ym] = level
            started = True
        else:
            level = level * (1.0 + mom_by_ym[ym] / 100.0)
            levels[ym] = level
    return levels


def week_to_month(week_monday: dt.date) -> tuple[int, int]:
    """Неделя относится к месяцу, которому принадлежит её понедельник."""
    return month_key(week_monday)


# ---------------------------------------------------------------------------
# Оркестрация: собрать все пять показателей, записать CSV + README
# ---------------------------------------------------------------------------

INDICATORS = [
    # (заголовок_колонки, human-читаемое имя, единица)
    ("курс_доллара", "Курс доллара США (ЦБ РФ)", "руб. за 1 USD"),
    ("курс_евро", "Курс евро (ЦБ РФ)", "руб. за 1 EUR"),
    ("курс_юаня", "Курс юаня (ЦБ РФ)", "руб. за 1 CNY"),
    ("ключевая_ставка", "Ключевая ставка (ЦБ РФ)", "% годовых"),
    ("индекс_потребительских_цен", "Индекс потребительских цен (Росстат)", "индекс, база=100 на начало окна"),
]


class FetchResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.error: str | None = None
        self.weekly_level: dict[tuple[int, int], float] = {}
        self.weekly_change: dict[tuple[int, int], float | None] = {}
        self.monthly_level: dict[tuple[int, int], float] = {}
        self.monthly_level_eom: dict[tuple[int, int], float] = {}
        self.monthly_change: dict[tuple[int, int], float | None] = {}
        self.last_date: dt.date | None = None


def fetch_currency_result(
    code: str,
    name: str,
    date_from: dt.date,
    date_to: dt.date,
    raw_override: bytes | None = None,
) -> FetchResult:
    res = FetchResult(name)
    try:
        daily = (
            _parse_cbr_currency_xml(raw_override)
            if raw_override is not None
            else fetch_cbr_currency_daily(code, date_from, date_to)
        )
        res.last_date = daily[-1][0]
        weeks = full_week_sequence(date_from, date_to)
        months = full_month_sequence(date_from, date_to)
        # Недельный ряд – конец недели (решение 13.09.2026, см. докстринг
        # модуля); месячный – среднее (основная колонка) + конец месяца
        # (доп. колонка).
        res.weekly_level = aggregate_daily_last(daily, iso_week_key)
        res.monthly_level = aggregate_daily_mean(daily, month_key)
        res.monthly_level_eom = aggregate_daily_last(daily, month_key)
        res.weekly_change = pct_change_over_sequence(res.weekly_level, weeks)
        res.monthly_change = pct_change_over_sequence(res.monthly_level, months)
        res.ok = True
    except SourceUnavailableError as exc:
        res.error = str(exc)
        LOG.error("%s: %s", name, exc)
    return res


def fetch_key_rate_result(
    name: str, date_from: dt.date, date_to: dt.date, raw_override: bytes | None = None
) -> FetchResult:
    res = FetchResult(name)
    try:
        daily = (
            _parse_cbr_key_rate_xml(raw_override)
            if raw_override is not None
            else fetch_cbr_key_rate_daily(date_from, date_to)
        )
        res.last_date = daily[-1][0]
        weeks = full_week_sequence(date_from, date_to)
        months = full_month_sequence(date_from, date_to)
        res.weekly_level = aggregate_daily_last(daily, iso_week_key)
        res.monthly_level = aggregate_daily_mean(daily, month_key)
        res.monthly_level_eom = aggregate_daily_last(daily, month_key)
        res.weekly_change = pct_change_over_sequence(res.weekly_level, weeks)
        res.monthly_change = pct_change_over_sequence(res.monthly_level, months)
        res.ok = True
    except SourceUnavailableError as exc:
        res.error = str(exc)
        LOG.error("%s: %s", name, exc)
    return res


def fetch_cpi_result(name: str, date_from: dt.date, date_to: dt.date) -> FetchResult:
    res = FetchResult(name)
    try:
        rows = fetch_rosstat_cpi_monthly()
        mom_by_ym = {(y, m): pct for (y, m, pct) in rows}
        months = full_month_sequence(date_from, date_to)
        res.monthly_level = build_cpi_monthly_levels(mom_by_ym, months)
        # ИПЦ публикуется Росстатом ровно одним значением в месяц – нет
        # отдельной дневной гранулярности, поэтому «конец месяца» численно
        # совпадает с «уровнем» (не второй независимый расчёт, честное
        # отражение источника, см. докстринг модуля).
        res.monthly_level_eom = dict(res.monthly_level)
        # изменение помесячно – берём официальный MoM% напрямую (не
        # пересчитываем через уровень второй раз, избегаем накопления
        # ошибок округления).
        res.monthly_change = {ym: mom_by_ym[ym] for ym in months if ym in mom_by_ym}
        last_ym = max(res.monthly_level) if res.monthly_level else None
        res.last_date = dt.date(last_ym[0], last_ym[1], 1) if last_ym else None

        # Понедельно – forward-fill месячного значения (находка №3 в
        # докстринге: официального понедельного агрегата ИПЦ нет).
        weeks = full_week_sequence(date_from, date_to)
        for wk in weeks:
            wk_monday = dt.date.fromisocalendar(wk[0], wk[1], 1)
            ym = week_to_month(wk_monday)
            if ym in res.monthly_level:
                res.weekly_level[wk] = res.monthly_level[ym]
        res.weekly_change = pct_change_over_sequence(res.weekly_level, weeks)
        res.ok = True
    except SourceUnavailableError as exc:
        res.error = str(exc)
        LOG.error("%s: %s", name, exc)
    return res


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.4f}"


def write_csv(
    path: Path,
    period_keys: list[tuple[int, int]],
    period_label_fn,
    results: dict[str, FetchResult],
    level_attr: str,
    change_attr: str,
    eom_attr: str | None = None,
) -> None:
    """eom_attr задан только для месячной таблицы – добавляет колонку
    «_уровень_конец_месяца» (см. докстринг модуля, решение 13.09.2026).
    Недельная таблица (eom_attr=None) колонку не получает – там «_уровень»
    сам по себе уже значение на конец недели."""
    header = ["период"]
    for col, _name, _unit in INDICATORS:
        header.append(f"{col}_уровень")
        if eom_attr:
            header.append(f"{col}_уровень_конец_месяца")
        header.append(f"{col}_изменение_pct")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        for key in period_keys:
            row = [period_label_fn(key)]
            for col, _name, _unit in INDICATORS:
                res = results[col]
                levels = getattr(res, level_attr)
                changes = getattr(res, change_attr)
                row.append(_fmt(levels.get(key)))
                if eom_attr:
                    eoms = getattr(res, eom_attr)
                    row.append(_fmt(eoms.get(key)))
                row.append(_fmt(changes.get(key)))
            w.writerow(row)


def week_label(key: tuple[int, int]) -> str:
    year, week = key
    monday = dt.date.fromisocalendar(year, week, 1)
    return f"{year}-W{week:02d} (нед. с {monday:%Y-%m-%d})"


def month_label(key: tuple[int, int]) -> str:
    year, month = key
    return f"{year}-{month:02d}"


def write_readme(
    path: Path,
    results: dict[str, FetchResult],
    date_from: dt.date,
    date_to: dt.date,
    cbr_raw_dir: Path | None = None,
) -> None:
    lines = [
        "# Макропоказатели – черновая выгрузка (заготовка, НЕ поставка)",
        "",
        f"Окно: {date_from:%Y-%m-%d} – {date_to:%Y-%m-%d} (10 лет).",
        f"Сгенерировано: {dt.datetime.now():%Y-%m-%d %H:%M}.",
        "",
        "🔴 Это черновик на проверку (Projects/macro_series_draft/), не файл поставки.",
        "Укладка в content-packs/ и пере-подпись пакета – следующая ступень.",
        "",
        "## Маршрут скачивания",
        "",
        (
            f"Курсы и ключевая ставка прочитаны из заранее скачанных файлов "
            f"(`--cbr-raw-dir {cbr_raw_dir}`), сеть для этих четырёх рядов не "
            "использовалась в этом прогоне."
            if cbr_raw_dir is not None
            else (
                f"Курсы и ключевая ставка получены через узел `{NODE_HOST}` (ssh) – "
                "cbr.ru недоступен с этой машины напрямую (гео-фильтрация)."
                if NODE_HOST
                else (
                    "Курсы и ключевая ставка получены напрямую с cbr.ru. Если с "
                    "вашей машины cbr.ru недоступен – запустите с "
                    "`--через-узел <имя из ~/.ssh/config>` (нужен поднятый "
                    "ssh-агент, пароль не запрашивается) либо предзагрузите "
                    "usd.xml/eur.xml/cny.xml/keyrate_soap.xml вручную и укажите "
                    "`--cbr-raw-dir <каталог>`."
                )
            )
        ),
        "ИПЦ получен напрямую с rosstat.gov.ru (доступен без обхода).",
        "",
        "## Правила агрегации по периодам",
        "",
        "- Курсы и ключевая ставка, МЕСЯЧНЫЙ ряд: колонка `_уровень` – "
        "среднее доступных официальных дневных значений внутри месяца "
        "(основная колонка, от неё считается `_изменение_pct`); колонка "
        "`_уровень_конец_месяца` – последнее по дате значение внутри "
        "месяца (курс/ставка «на конец месяца»).",
        "- Курсы и ключевая ставка, НЕДЕЛЬНЫЙ ряд: колонка `_уровень` – "
        "значение НА КОНЕЦ недели (последнее по дате внутри недели), не "
        "среднее.",
        "- ИПЦ (Росстат) публикуется ровно одним значением в месяц – нет "
        "дневной гранулярности, поэтому `_уровень_конец_месяца` для ИПЦ "
        "численно совпадает с `_уровень` (не отдельный расчёт, честное "
        "отражение источника).",
        "- 🔴 Понедельного агрегата ИПЦ Росстат не публикует. В недельном "
        "ряду `индекс_потребительских_цен_уровень` – ЧЕСТНЫЙ forward-fill "
        "месячного значения (то же число повторяется во все недели месяца), "
        "не отдельный недельный расчёт. Это осознанное намеренное "
        "протягивание, помечено здесь явно (см. правило INV-50).",
        "- Пропуски не заполняются: если для периода нет ни одного "
        "официального дневного наблюдения (курсы/ставка) или Росстат не "
        "публиковал значение (ИПЦ) – клетка пустая, а не подставленное "
        "соседнее значение.",
        "- Изменение % везде – к непосредственно предыдущему периоду ТОЙ ЖЕ "
        "частоты, посчитано по основной колонке уровня той же таблицы.",
        "",
        "## Статус источников",
        "",
    ]
    for col, name, unit in INDICATORS:
        res = results[col]
        status = "OK" if res.ok else "ОШИБКА"
        last = f"актуально на {res.last_date:%Y-%m-%d}" if res.last_date else "нет данных"
        lines.append(f"### {name} (`{col}`, {unit})")
        lines.append(f"- Статус: **{status}**, {last}")
        if not res.ok:
            lines.append(f"- Ошибка: {res.error}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=10, help="глубина истории, лет")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "Projects" / "macro_series_draft",
        help="куда писать macro_weekly.csv / macro_monthly.csv / README",
    )
    parser.add_argument(
        "--через-узел",
        dest="node",
        default=None,
        metavar="ИМЯ_УЗЛА",
        help=(
            "имя узла из ~/.ssh/config – скачивание источников ЦБ (курсы + "
            "ключевая ставка) выполняется на узле по ssh, файл забирается "
            "потоком; обход гео-блокировки cbr.ru из dev-песочницы. Прямой "
            "путь остаётся рабочим по умолчанию (флаг не задан) – доступ у "
            "машин разный. Требует уже поднятого ssh-агента, пароль не "
            "запрашивается."
        ),
    )
    parser.add_argument(
        "--cbr-raw-dir",
        type=Path,
        default=None,
        help=(
            "каталог с заранее скачанными usd.xml/eur.xml/cny.xml/"
            "keyrate_soap.xml – читает их вместо сети для этих четырёх "
            "рядов (ИПЦ всё равно тянется с Росстата напрямую)."
        ),
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    global NODE_HOST
    NODE_HOST = args.node
    if NODE_HOST:
        LOG.info("Источники ЦБ будут скачаны через узел %s (ssh).", NODE_HOST)

    date_to = dt.date.today()
    date_from = date_to.replace(year=date_to.year - args.years)

    LOG.info("Окно загрузки: %s – %s", date_from, date_to)

    def _read_raw(filename: str) -> bytes | None:
        if args.cbr_raw_dir is None:
            return None
        p = args.cbr_raw_dir / filename
        if not p.exists():
            raise SystemExit(f"--cbr-raw-dir указан, но файла нет: {p}")
        return p.read_bytes()

    results: dict[str, FetchResult] = {}
    results["курс_доллара"] = fetch_currency_result(
        "usd", "Курс доллара", date_from, date_to, raw_override=_read_raw("usd.xml")
    )
    results["курс_евро"] = fetch_currency_result(
        "eur", "Курс евро", date_from, date_to, raw_override=_read_raw("eur.xml")
    )
    results["курс_юаня"] = fetch_currency_result(
        "cny", "Курс юаня", date_from, date_to, raw_override=_read_raw("cny.xml")
    )
    results["ключевая_ставка"] = fetch_key_rate_result(
        "Ключевая ставка", date_from, date_to, raw_override=_read_raw("keyrate_soap.xml")
    )
    results["индекс_потребительских_цен"] = fetch_cpi_result("ИПЦ", date_from, date_to)

    weeks = full_week_sequence(date_from, date_to)
    months = full_month_sequence(date_from, date_to)

    write_csv(
        args.out_dir / "macro_weekly.csv",
        weeks, week_label, results, "weekly_level", "weekly_change",
    )
    write_csv(
        args.out_dir / "macro_monthly.csv",
        months, month_label, results, "monthly_level", "monthly_change",
        eom_attr="monthly_level_eom",
    )
    write_readme(
        args.out_dir / "README_macro_series.md", results, date_from, date_to,
        cbr_raw_dir=args.cbr_raw_dir,
    )

    n_failed = sum(1 for r in results.values() if not r.ok)
    if n_failed:
        LOG.error("%d из %d показателей не загружены – см. README_macro_series.md", n_failed, len(results))
    else:
        LOG.info("Все %d показателей загружены успешно.", len(results))
    return n_failed


if __name__ == "__main__":
    sys.exit(main())
