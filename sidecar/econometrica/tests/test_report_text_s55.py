"""Клиентский текст отчётов HTML/PPTX – правки выпуска 2.5.7 (s55, решения
владельца 28.09.2026).

Каждый тест поведенческий: строит отчёт (или его часть) штатным кодом и
смотрит на то, что увидит покупатель, а не на наличие строки в исходнике.
Все тесты проверены мутацией «вернуть старое – тест краснеет – откатить»
(см. Projects/FIX_s55_text.md).
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.channel_action import ACTION_KEYS, VERDICT_DISPLAY_RU  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")


def _payload() -> dict:
    """Фикстура-образец, но обоснования вердиктов – от ЖИВОГО движка.

    В фикстуре `action_reasoning` запечён старым движком («Optimizer
    рекомендует … - недо-инвестирован»); без пересчёта тесты мерили бы
    фикстуру, а не код.
    """
    from engines.channel_action import compute_channel_action
    with open(_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    for c in data.get("channels") or []:
        c["action_reasoning"] = compute_channel_action(c).reasoning
    return data


def _pptx_text(prs) -> str:
    """Весь видимый текст презентации: рамки и ячейки таблиц."""
    out = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        out.append(cell.text)
    return "\n".join(out)


def _html_text(page: str) -> str:
    """Видимый текст страницы: без script/style, блоки – отдельными строками."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return _html.unescape(re.sub(r"<[^>]+>", "\n", body))


def _js_object(page: str, var: str) -> dict:
    """Замороженный JSON, который страница кладёт в `var <var> = {...};`."""
    m = re.search(r"var " + var + r"\s*=\s*(\{.*?\});\n", page)
    assert m, f"в странице нет var {var}"
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def html_page() -> str:
    from aurora_html import build_html
    return build_html(_payload())


# ─── П.1: вердикты в выдвижной панели канала (интерактивный HTML) ──────────

def test_js_verdict_dictionary_is_russian_single_source(html_page):
    """Словарь STRINGS.verdicts страницы = VERDICT_DISPLAY_RU (единый источник
    таблиц), со всеми ключами, включая Uncertain; ни один ключ не переводится
    сам в себя (было: {"Scale": "Scale", …} – покупатель видел «Scale/Cut»)."""
    verdicts = _js_object(html_page, "STRINGS")["verdicts"]
    assert verdicts == VERDICT_DISPLAY_RU
    assert set(verdicts) == set(ACTION_KEYS)
    for key, text in verdicts.items():
        assert text != key
        assert not re.search(r"[A-Za-z]", text), f"{key} → {text!r}"


def test_drill_panel_verdict_matches_table_cell(html_page):
    """Панель канала показывает ту же подпись, что ячейка «Вердикт» таблицы
    (со смягчением «(предв.)»), а не голый словарь по ключу."""
    details = _js_object(html_page, "CHART_DATA")["mroas"]["details"]
    assert details
    cells = dict(re.findall(
        r'<tr data-channel="([^"]+)">.*?<span class="verdict-badge[^"]*">([^<]+)</span>',
        html_page, flags=re.S,
    ))
    checked = 0
    for name, d in details.items():
        key = _html.escape(name)
        if key not in cells:
            continue  # таблица показывает топ-10, панель знает все каналы
        assert d["verdict_display"] == _html.unescape(cells[key]), name
        assert not re.search(r"[A-Za-z]", d["verdict_display"]), d["verdict_display"]
        checked += 1
    assert checked >= 3


def test_drill_panel_js_prefers_verdict_display():
    """Структурная страховка к тесту выше: JS панели читает verdict_display
    первым (словарь по ключу – только запасной путь для старых данных)."""
    from aurora_html.interactive import bootstrap_js
    js = bootstrap_js("light", "{}", "{}", {})
    line = next(l for l in js.splitlines() if "var verdictText" in l)
    assert line.split("=", 1)[1].strip().startswith("d.verdict_display ||"), line


# ─── П.2: дефис-минус в роли тире ───────────────────────────────────────────

# Доработка s55: диапазон в скобках тоже пишется через « – » («[2.06 – 2.83]»),
# поэтому исключения для «[a - b]» больше нет – он ловится общим шаблоном.
_HYPHEN_AS_DASH = re.compile(r"\S - \S")


def _hyphen_dashes(text: str) -> list[str]:
    return [text[max(0, m.start() - 40):m.end() + 40].replace("\n", " / ")
            for m in _HYPHEN_AS_DASH.finditer(text)]


@pytest.fixture(scope="module")
def pptx_text() -> str:
    from aurora_pptx.builder import AuroraPPTXBuilder
    return _pptx_text(AuroraPPTXBuilder(_payload()).build())


def test_pptx_has_no_hyphen_as_dash(pptx_text):
    """«Онлайн-видео - 45.0% …», «… в Performance - +5 пп к ROAS» → « – »."""
    assert _hyphen_dashes(pptx_text) == []
    assert "\u2014" not in pptx_text


def test_pptx_preview_has_no_hyphen_as_dash():
    """Предпросмотр без данных (зашитый пилотный текст) – то же правило."""
    from aurora_pptx.builder import AuroraPPTXBuilder
    assert _hyphen_dashes(_pptx_text(AuroraPPTXBuilder({}).build())) == []


def test_html_has_no_hyphen_as_dash(html_page):
    text = _html_text(html_page)
    assert _hyphen_dashes(text) == []
    assert "\u2014" not in text


# ─── П.3: mROAS в таблице PPTX – две цифры после запятой, как в HTML ───────

@pytest.mark.parametrize("kpi", ["fixture", "other-mode"], ids=["roi", "monetary-other"])
def test_pptx_mroas_two_decimals(kpi):
    """ТВ 0.24 и наружная реклама 0.17 не сливаются в «0.2» и «0.2»;
    диапазон – тоже две цифры, как в HTML «0.24× [0.03 – 0.39]»."""
    from aurora_pptx.builder import AuroraPPTXBuilder
    data = _payload()
    if kpi == "other-mode":
        # запасная ветка денежного KPI (не roi и не effectiveness) – builder.py:1224
        data["kpi"] = dict(data["kpi"], derived_mode="margin")
    chs = data["channels"]
    chs[2].update(mroas=0.24, mroas_ci_low=0.03, mroas_ci_high=0.39)
    chs[3].update(mroas=0.17, mroas_ci_low=0.004, mroas_ci_high=0.28)
    text = _pptx_text(AuroraPPTXBuilder(data).build())
    # Таблица действий собрана из текстовых рамок: ячейка mROAS = «0.24 [0.03 – 0.39]».
    assert "0.24 [0.03 – 0.39]" in text
    assert "0.17 [0.00 – 0.28]" in text


# ─── П.4 и П.5: даты окон проверки на истории и сроки квартальных/годовых данных ─

_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _quarterly_dates(start_year: int = 2023, n: int = 8, end_of_period: bool = False) -> list[str]:
    """Квартальные метки начала (01.01, 01.04 …) или конца (31.03, 30.06 …) периода."""
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    out = []
    for i in range(n):
        y, q = start_year + i // 4, i % 4 + 1
        out.append(f"{y}-{ends[q]}" if end_of_period else f"{y}-{3 * q - 2:02d}-01")
    return out


@pytest.mark.parametrize("end_of_period", [False, True], ids=["QS", "QE"])
def test_quarterly_data_window_names_quarters(end_of_period):
    """L1: метки начала квартала давали «янв 2023 – окт 2024», конца – «мар 2023 –
    дек 2024»; оба искажают края. Правильно – «I кв. 2023 – IV кв. 2024»."""
    from engines.narrative_adapter import _derive_data_coverage
    cov = _derive_data_coverage({"time_series": {"dates": _quarterly_dates(end_of_period=end_of_period)}})
    assert cov["granularity"] == "Q"
    assert cov["window_label"] == "I кв. 2023 – IV кв. 2024"


@pytest.mark.parametrize("dates", [
    ["2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"],
    ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"],
], ids=["YS", "YE"])
def test_yearly_data_window_names_years(dates):
    from engines.narrative_adapter import _derive_data_coverage
    cov = _derive_data_coverage({"time_series": {"dates": dates}})
    assert cov["granularity"] == "Y"
    assert cov["window_label"] == "2021 – 2024"


def test_weekly_and_monthly_windows_unchanged():
    """Недельные и месячные данные – «мес год – мес год», как после s53."""
    from datetime import date, timedelta
    from engines.narrative_adapter import _derive_data_coverage
    weekly = [(date(2024, 12, 30) + timedelta(weeks=i)).isoformat() for i in range(32)]
    monthly = [f"2024-{m:02d}-01" for m in range(1, 13)]
    assert _derive_data_coverage({"time_series": {"dates": weekly}})["window_label"] == "дек 2024 – авг 2025"
    assert _derive_data_coverage({"time_series": {"dates": monthly}})["window_label"] == "янв 2024 – дек 2024"


def _quarterly_payload() -> dict:
    """Фикстура с квартальной историей: meta – из боевого _derive_data_coverage,
    план на 4 квартала 2025 (метки начала квартала), проверка на истории – окна
    по датам ISO, как их пишет engines/backtest.py."""
    from engines.narrative_adapter import _derive_data_coverage
    data = _payload()
    hist = _quarterly_dates(2023, 8)
    cov = _derive_data_coverage({"time_series": {"dates": hist}})
    data["meta"] = dict(data["meta"], data_window_label=cov["window_label"],
                        period_label=cov["window_label"],
                        period_granularity=cov["granularity"])
    labels = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01"]
    sc = {
        "name": "Базовый план", "variant_id": "v1", "predictions": [1.0] * 4,
        "ci_low": [0.9] * 4, "ci_high": [1.1] * 4, "total_kpi": 4.0e9,
        "total_kpi_ci_low": 3.6e9, "total_kpi_ci_high": 4.4e9,
        "total_spend_money": 9.0e8, "roas_money": 4.4, "period_labels": labels,
        "per_channel_money": {}, "disclaimers": [],
    }
    data["forecast"] = {"status": "ok", "scenarios": [sc], "accepted_variant": "v1",
                        "disclaimers": []}
    data["backtest"] = {
        "status": "ok", "granularity": "Q", "horizon_periods": 1,
        "windows_hit_total": 1, "windows_with_interval": 2,
        "mape_model": 5.0, "mape_naive_best": 7.0,
        "windows": [
            {"window": "2024-01-01 – 2024-01-01", "actual_total": 1.0e9, "predicted_total": 1.1e9,
             "pi_low_total": 0.9e9, "pi_high_total": 1.2e9, "hit_total": True},
            {"window": "2024-04-01 – 2024-07-01", "actual_total": 2.0e9, "predicted_total": 1.5e9,
             "pi_low_total": 1.4e9, "pi_high_total": 1.8e9, "hit_total": False},
        ],
    }
    return data


def test_html_quarterly_plan_and_backtest_windows():
    from aurora_html import build_html
    text = _html_text(build_html(_quarterly_payload()))
    assert "I кв. 2025 – IV кв. 2025" in text          # срок плана
    assert "II кв. 2024 – III кв. 2024" in text         # окно проверки
    assert "I кв. 2023 – IV кв. 2024" in text           # период данных
    assert not _ISO_DATE.findall(text), _ISO_DATE.findall(text)[:5]
    assert "окт 2025" not in text and "янв 2025 –" not in text


def test_pptx_quarterly_plan_and_backtest_windows():
    from aurora_pptx.builder import AuroraPPTXBuilder
    text = _pptx_text(AuroraPPTXBuilder(_quarterly_payload()).build())
    assert "I кв. 2025 – IV кв. 2025" in text
    assert "II кв. 2024 – III кв. 2024" in text
    assert not _ISO_DATE.findall(text), _ISO_DATE.findall(text)[:5]


def _weekly_backtest_payload() -> dict:
    data = _payload()
    data["backtest"] = {
        "status": "ok", "granularity": "W", "horizon_periods": 13,
        "windows_hit_total": 1, "windows_with_interval": 1,
        "mape_model": 5.0, "mape_naive_best": 7.0,
        "windows": [{"window": "2023-10-02 – 2023-12-25", "actual_total": 1.0e9,
                     "predicted_total": 1.1e9, "pi_low_total": 0.9e9,
                     "pi_high_total": 1.2e9, "hit_total": True}],
    }
    return data


def test_backtest_weekly_window_not_iso_html_and_pptx():
    """П.4: «2023-10-02 – 2023-12-25» → «окт 2023 – дек 2023» (помощник s53)."""
    from aurora_html import build_html
    from aurora_pptx.builder import AuroraPPTXBuilder
    data = _weekly_backtest_payload()
    html_text = _html_text(build_html(data))
    pptx_text = _pptx_text(AuroraPPTXBuilder(data).build())
    for text in (html_text, pptx_text):
        assert "окт 2023 – дек 2023" in text
        assert "2023-10-02" not in text and "2023-12-25" not in text


# ─── П.7: латиница в клиентском тексте ──────────────────────────────────────

# Утверждённые владельцем формулировки (28.09) – не переписывать без решения.
_FORBIDDEN_LATIN = ("Marginal ROI", "Bayesian MMM", "Report ID", "Quarterly",
                    "posterior", "Marketing Mix Modeling · ")
_VS = re.compile(r"(?<![A-Za-zА-Яа-я])vs(?![A-Za-zА-Яа-я])")


def test_html_listed_latin_replaced(html_page):
    text = _html_text(html_page)
    for bad in _FORBIDDEN_LATIN:
        assert bad not in text, bad
    assert not _VS.findall(text)
    for good in ("Бюджет и эффект", "ДОЛЯ БЮДЖЕТА И ДОЛЯ ЭФФЕКТА",
                 "Доля бюджета и доля эффекта – выявление дисбаланса",
                 "Доля бюджета и доля эффекта · %",
                 "Текущий и оптимальный бюджет · млн ₽",
                 "Отдача последнего вложенного рубля (mROAS)",
                 "Байесовская модель MMM",
                 "Байесовская модель MMM · правдоподобный диапазон 90%, "
                 "показаны средние апостериорного распределения",
                 "Номер отчёта:"):
        assert good in text, good


def test_html_head_description_without_latin(html_page):
    head = html_page.split("</head>", 1)[0]
    assert "Report ID" not in head and "Marketing Mix Modeling" not in head
    assert "Номер отчёта:" in head


def test_strings_json_approved_wording():
    """Строки strings_ru.json, которые сейчас не выводятся ни одним модулем
    (tagline, source_notes, report_id_hint), тоже приведены – чтобы при
    подключении латиница не вернулась."""
    path = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    assert s["brand"]["tagline"] == "Моделирование маркетингового микса · Отчёт"
    assert s["brand"]["methodology_badge"] == "Байесовская модель MMM"
    assert s["source_notes"]["posterior"] == (
        "правдоподобный диапазон 90%, показаны средние апостериорного распределения")
    assert s["closing"]["report_id_hint"] == (
        "Используйте номер отчёта при обсуждении этого отчёта.")
    assert "Bayesian" not in s["source_notes"]["data"]
    assert "Bayesian" not in s["methodology"]["prior_note"]
    assert "verdicts" not in s  # самоперевод ключей удалён, источник – VERDICT_DISPLAY_RU


@pytest.mark.parametrize("engine", ["bayes", "ols"])
def test_pptx_listed_latin_replaced(engine):
    from aurora_pptx.builder import AuroraPPTXBuilder
    data = _payload()
    if engine == "ols":
        data["diagnostics"] = dict(data["diagnostics"], engine="ols")
    text = _pptx_text(AuroraPPTXBuilder(data).build())
    for bad in _FORBIDDEN_LATIN:
        assert bad not in text, bad
    assert not _VS.findall(text)
    assert "Отдача последнего вложенного рубля (mROAS)" in text
    if engine == "bayes":
        assert "Источник: байесовская модель MMM Aurora AI" in text
        assert "бенчмарков байесовской модели MMM" in text


# ─── П.8: глоссарий – «русское имя (английское)», HTML и PPTX не расходятся ──

_APPROVED_GLOSSARY = (
    "Базовые продажи (Baseline)",
    "Апостериорное распределение (Posterior)",
    "Априорное распределение (Prior)",
    "Эффект переноса (Adstock)",
    "Насыщение (Saturation, кривая Хилла)",
    "Байесовский вывод (Bayesian inference)",
    "Доля голоса (Share of Voice)",
    "Охват и частота (Reach & Frequency)",
    "Узнаваемость бренда (Awareness)",
    "Дополнительные продажи от рекламы (Incremental sales)",
)
# Термины PPTX-глоссария, совпадающие с HTML (Posterior и Incremental sales в PPTX
# названы внутри определений соседних терминов, Awareness в PPTX нет).
_PPTX_SHARED = (
    "Базовые продажи (Baseline)", "Априорное распределение (Prior)",
    "Эффект переноса (Adstock)", "Насыщение (Saturation, кривая Хилла)",
    "Доля голоса (Share of Voice)", "Охват и частота (Reach & Frequency)",
)


def _html_glossary_terms() -> list[str]:
    from aurora_html.sections import render_glossary
    path = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")
    with open(path, encoding="utf-8") as f:
        strings = json.load(f)
    html = render_glossary({"strings": strings, "kpi": {}, "meta": {}})
    return [_html.unescape(t) for t in
            re.findall(r'<div class="glossary-term-name">([^<]+)</div>', html)]


def test_html_glossary_uses_approved_names():
    terms = _html_glossary_terms()
    for name in _APPROVED_GLOSSARY:
        assert name in terms, name
    # Латинский термин без русского имени остался только у сокращений.
    abbreviations = {"MMM", "ROI", "mROAS", "TRP", "CPP", "MAPE", "ESS", "R-hat",
                     "MCMC", "NUTS", "MQS", "R²"}
    for t in terms:
        if t in abbreviations:
            continue
        assert re.search(r"[А-Яа-яЁё]", t.split("(", 1)[0]), t


def _pptx_glossary_slide_text(prs) -> str:
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if "Глоссарий терминов" in texts:
            return "\n".join(texts)
    raise AssertionError("слайд глоссария не найден")


@pytest.mark.parametrize("engine", ["bayes", "ols"])
def test_pptx_glossary_matches_html_names(engine):
    from aurora_pptx.builder import AuroraPPTXBuilder
    data = _payload()
    if engine == "ols":
        data["diagnostics"] = dict(data["diagnostics"], engine="ols")
    text = _pptx_glossary_slide_text(AuroraPPTXBuilder(data).build())
    html_terms = set(_html_glossary_terms())
    shared = ["Базовые продажи (Baseline)", "Эффект переноса (Adstock)",
              "Насыщение (Saturation, кривая Хилла)", "Доля голоса (Share of Voice)",
              "Охват и частота (Reach & Frequency)"]
    if engine == "bayes":  # в OLS-ветке глоссария байесовских терминов нет
        shared += ["Байесовский вывод (Bayesian inference)", "Априорное распределение (Prior)"]
    for name in shared:
        assert name in text, name
        assert name in html_terms, name
    for old in ("Охват (Reach)", "Доля голоса (SoV)", "Априорное / апостериорное",
                "Базовый / инкрементальный"):
        assert old not in text, old
    assert "дополнительные продажи от рекламы (Incremental sales)" in text
    if engine == "bayes":
        assert "апостериорное распределение (Posterior)" in text


# ─── П.6: ось waterfall – русские разряды, все категории подписаны ─────────

def _js_function(js: str, name: str) -> str:
    start = js.index("function " + name)
    nxt = js.find("\n  function ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_waterfall_axis_formatted_like_neighbours():
    """Ось Y waterfall – тот же формат, что подписи столбцов и ось графика
    сравнения прогнозов (`toLocaleString('ru-RU')`), а не формат ECharts по
    умолчанию («25,000,000,000»); ось X – `interval: 0` (все категории, без
    молчаливого прореживания) с поворотом при >4 категориях. Поведение в
    браузере (подписи на полотне и в PNG) – проверка образцов, см. отчёт."""
    from aurora_html.interactive import bootstrap_js
    fn = _js_function(bootstrap_js("light", "{}", "{}", {}), "buildWaterfallOption")
    y_axis = fn[fn.index("yAxis:"):fn.index("series:")]
    assert "formatter: function(v) { return Math.round(v).toLocaleString('ru-RU'); }" in y_axis
    x_axis = fn[fn.index("xAxis:"):fn.index("yAxis:")]
    assert "interval: 0" in x_axis
    assert "rotate: data.labels.length > 4 ? 20 : 0" in x_axis
    # Запас слева: при 8 первая цифра «25 000 000 000» обрезалась краем полотна
    # (замер в браузере на образцах s55: левый край подписи −0,9 px).
    assert "grid: { left: 16," in fn


# ─── Доработка s55: интервалы, прочерк в таблице прогноза, «Tier-1» ─────────

# Разделитель внутри скобок-интервала: группа 1 – то, чем он напечатан.
_INTERVAL = re.compile(r"\[-?\d[\d.]* ([-–]) -?\d[\d.]*\]")


@pytest.mark.parametrize("kpi", [
    None,
    {"kpi_kind": "monetary", "derived_mode": "effectiveness"},
    {"kpi_kind": "count", "derived_mode": "roi"},
    {"kpi_kind": "monetary", "derived_mode": "margin"},
], ids=["roi", "effectiveness", "count", "monetary-other"])
def test_interval_brackets_use_en_dash_html_and_pptx(kpi):
    """«[2.06 - 2.83]» → «[2.06 – 2.83]» во всех ветках KPI: HTML-ячейки
    (`_fmt_x_with_ci`, `_fmt_metric_with_ci`) и таблица каналов PPTX."""
    from aurora_html.sections import _fmt_metric_with_ci, _fmt_x_with_ci, _kpi_view
    from aurora_pptx.builder import AuroraPPTXBuilder
    if kpi is None:
        cell = _fmt_x_with_ci(0.24, 0.03, 0.39)
    else:
        cell = _fmt_metric_with_ci(0.24, 0.03, 0.39, _kpi_view({"kpi": kpi}))
    cell_text = _html.unescape(re.sub(r"<[^>]+>", "", cell))
    assert [m.group(1) for m in _INTERVAL.finditer(cell_text)] == ["–"], cell_text
    data = _payload()
    if kpi is not None:
        data["kpi"] = dict(data["kpi"], **kpi)
    text = _pptx_text(AuroraPPTXBuilder(data).build())
    seps = [m.group(1) for m in _INTERVAL.finditer(text)]
    assert seps and set(seps) == {"–"}, seps


def test_forecast_table_empty_cell_is_en_dash():
    """Строка прогноза «… 7 283 199 890 - н/д»: прочерк в ячейке «Δ к базовому»
    у самой базовой строки – «–», не дефис-минус; знаки чисел не тронуты."""
    from aurora_html.sections import render_forecast_plan
    path = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")
    with open(path, encoding="utf-8") as f:
        strings = json.load(f)

    def sc(name, kpi, spend):
        return {"name": name, "variant_id": name, "predictions": [kpi / 3] * 3,
                "ci_low": [kpi / 3.3] * 3, "ci_high": [kpi / 2.7] * 3,
                "total_kpi": kpi, "total_kpi_ci_low": kpi * 0.9, "total_kpi_ci_high": kpi * 1.1,
                "total_spend_money": spend, "roas_money": 1.5,
                "period_labels": ["2026-01", "2026-02", "2026-03"],
                "per_channel_money": {}, "disclaimers": []}

    fc = {"status": "ok", "accepted_variant": "Базовый план", "disclaimers": [],
          "scenarios": [sc("Базовый план", 11_000.0, None), sc("Плюс 20%", 12_000.0, 6.0e6)]}
    html = render_forecast_plan({"strings": strings, "forecast": fc, "meta": {}, "kpi": {}})
    cells = re.findall(r'<td class="num">(?:<strong>)?([^<]*)(?:</strong>)?</td>', html)
    assert "–" in cells, cells
    assert "-" not in cells, cells
    assert "+9%" in cells  # знак разницы у второго сценария – как был


def test_methodology_badge_without_tier_jargon(html_page):
    """«Байесовская модель MMM · Tier-1 методология» → «Байесовская модель MMM»."""
    text = _html_text(html_page)
    assert "Tier-1" not in text and "Tier 1" not in text
    assert "Байесовская модель MMM" in text.split("\n")
