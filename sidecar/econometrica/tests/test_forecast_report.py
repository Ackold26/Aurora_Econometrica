"""
Тесты секции «Прогноз на будущий период» (E5, 2026-07-10).

Покрывают:
  (a) PPTX с forecast → лишний слайд + проверка overflow
  (b) PPTX без forecast → кол-во слайдов не меняется (INV-50)
  (c) Оговорки попадают в XML
  (d) _page_shift == 3 при backtest + gen_compare + forecast
  (e) HTML render_forecast_plan возвращает "" при отсутствии forecast
  (f) HTML render_forecast_plan возвращает таблицу при наличии forecast
"""
import copy
import json
import os
import tempfile

import pytest

from aurora_html.builder import AuroraHTMLBuilder
from aurora_pptx.builder import AuroraPPTXBuilder
from aurora_html.sections import render_forecast_plan

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# ─── strings_ru.json — как и другие тесты sections.py (test_report_text_hygiene.py
# и т.д.), render_forecast_plan/render_retro_insights читают ctx["strings"] ────

with open(
    os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json"),
    encoding="utf-8",
) as _f:
    _STRINGS = json.load(_f)


def _s(ctx: dict) -> dict:
    """Добавляет ctx["strings"] к минимальному контексту теста (боевой builder.py
    всегда кладёт strings — sections.py на это полагается без .get())."""
    return {**ctx, "strings": _STRINGS}


# ─── Минимальный валидный forecast ────────────────────────────────────────────

FORECAST_DATA = {
    "status": "ok",
    "scenarios": [
        {
            "name": "Базовый",
            "variant_id": "v1",
            "predictions": [100, 110, 120, 130],
            "ci_low": [90, 99, 108, 117],
            "ci_high": [110, 121, 132, 143],
            "total_kpi": 460.0,
            # P-2 (2026-07-16): интервал СУММЫ за горизонт (totals.predicted_kpi_ci_*
            # из load_saved_forecast) — именно он рендерится в колонке интервала,
            # НЕ CI последнего периода.
            "total_kpi_ci_low": 414.0,
            "total_kpi_ci_high": 506.0,
            "total_spend_money": 5_000_000.0,
            "roas_money": 0.092,
            "period_labels": ["Янв", "Фев", "Мар", "Апр"],
            "disclaimers": ["Прогноз при неизменных условиях рынка"],
        }
    ],
    "historical_actual": [80, 85, 90, 95],
    "historical_dates": ["Сен", "Окт", "Ноя", "Дек"],
    "cutoff_index": 4,
    "accepted_variant": "v1",
    "disclaimers": ["Прогноз при неизменных условиях рынка"],
}


# ─── Fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def base_payload():
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _build_deck(payload, path):
    prs = AuroraPPTXBuilder(payload).build()
    prs.save(path)
    return prs


def _xml_text(prs):
    """Собрать весь текст из XML всех слайдов."""
    from pptx.oxml.ns import qn
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return "\n".join(texts)


# ─── (a) С forecast → дополнительный слайд ───────────────────────────────────

def test_forecast_slide_added(base_payload, tmp_path):
    """При наличии forecast данных колода получает на 1 слайд больше."""
    # Базовая колода без forecast
    payload_base = copy.deepcopy(base_payload)
    payload_base.pop("forecast", None)
    out_base = str(tmp_path / "deck_base.pptx")
    prs_base = _build_deck(payload_base, out_base)
    n_base = len(prs_base.slides)

    # Колода с forecast
    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = FORECAST_DATA
    out_fc = str(tmp_path / "deck_forecast.pptx")
    prs_fc = _build_deck(payload_fc, out_fc)
    n_fc = len(prs_fc.slides)

    assert n_fc == n_base + 1, (
        f"Ожидали {n_base + 1} слайдов с forecast, получили {n_fc}"
    )


def test_forecast_slide_overflow_clean(base_payload, tmp_path):
    """Колода с forecast не должна иметь overflow."""
    from aurora_pptx.check_overflow import check

    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = FORECAST_DATA
    out = str(tmp_path / "deck_forecast_overflow.pptx")
    _build_deck(payload_fc, out)
    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"PPTX с forecast получил overflow/overlap:\n{detail}"


def test_forecast_slide_contains_title(base_payload, tmp_path):
    """Слайд прогноза должен содержать текст «Прогноз»."""
    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = FORECAST_DATA
    out = str(tmp_path / "deck_forecast_title.pptx")
    prs = _build_deck(payload_fc, out)
    all_text = _xml_text(prs)
    assert "Прогноз" in all_text, "Текст «Прогноз» не найден в XML колоды"


def test_forecast_interval_is_horizon_total_not_last_period(base_payload, tmp_path):
    """P-2 регресс (2026-07-16): в таблице сценариев — интервал СУММЫ за
    горизонт (total_kpi_ci_*), не CI последнего периода (масштабы несоизмеримы
    с колонкой «Прогноз KPI»)."""
    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = FORECAST_DATA
    out = str(tmp_path / "deck_forecast_interval.pptx")
    prs = _build_deck(payload_fc, out)
    all_text = _xml_text(prs)
    assert "414 – 506" in all_text, "Интервал суммы за горизонт не найден"
    assert "117 – 143" not in all_text, (
        "CI последнего периода попал в таблицу — регресс P-2"
    )


def _find_forecast_plan_slide(prs):
    """Слайд ПЛАНА (таблица сценариев бюджета), не слайд оглавления.

    10.09.2026, второе уточнение (zond5, probe1_results.md): оба слайда содержат
    фразу «Прогноз на будущий период», но по-разному. У оглавления это ПОДСТРОКА
    внутри булета «в том числе "Прогноз на будущий период" – стр. NN»
    (`aurora_pptx/builder.py:1388`) — и оглавление идёт РАНЬШЕ по порядку слайдов
    (index=1, footer «2/13»), чем сам слайд плана (index=5, footer «6/13»). Старый
    substring-поиск (`any(... in t for t in texts)`) матчился на оглавление и
    останавливался, до слайда плана не доходя НИКОГДА — ни поиск слайда, ни
    последующая проверка ложного нуля не работали ни разу.

    Два НЕЗАВИСИМЫХ структурных признака слайда плана (не совпадение по случайной
    подстроке): (1) заголовок «Прогноз на будущий период» — ОТДЕЛЬНАЯ ячейка
    (точное совпадение элемента списка, не substring), которой у оглавления в
    принципе быть не может — там это часть более длинной строки; (2) заголовок
    таблицы «ВАРИАНТЫ БЮДЖЕТНОГО ПЛАНА», которого на оглавлении нет вовсе.
    Возвращает (индекс слайда, список текстов фигур) или (None, None).
    """
    for idx, slide in enumerate(prs.slides):
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if "Планирование: прогноз на будущий период" in texts and "ВАРИАНТЫ БЮДЖЕТНОГО ПЛАНА" in texts:
            return idx, texts
    return None, None


def _missing_money_marked(cell_values):
    """Отсутствующие деньги на слайде плана — отдельно стоящая ячейка «н/д»
    (`aurora_pptx/builder.py::s_forecast_plan`, budget_str/roas_str fallback),
    НЕ символ тире. Проверено прямой инспекцией: короткое тире на этом слайде
    встречается ТОЛЬКО как разделитель диапазона в интервале KPI («414 – 506»),
    к отсутствующим деньгам отношения не имеет. Комментарий раньше описывал
    поведение, которого в коде для денежных полей нет (тире вместо «н/д») —
    исправлено под фактический рендер, не под прежнее предположение."""
    return "н/д" in cell_values


def _false_zero_present(cell_values):
    """INV-50: ложный ноль — отдельно стоящий «0» или «0.00» в ячейке таблицы."""
    return "0" in cell_values or "0.00" in cell_values


def test_forecast_missing_money_renders_dash_not_zero(base_payload, tmp_path):
    """INV-50: сценарий физметрик (spend/roas = None) рисует «н/д», не ложный 0,
    на слайде ПЛАНА (не на оглавлении)."""
    payload_fc = copy.deepcopy(base_payload)
    fc = copy.deepcopy(FORECAST_DATA)
    fc["scenarios"][0]["total_spend_money"] = None
    fc["scenarios"][0]["roas_money"] = None
    payload_fc["forecast"] = fc
    out = str(tmp_path / "deck_forecast_dash.pptx")
    prs = _build_deck(payload_fc, out)

    idx, target = _find_forecast_plan_slide(prs)
    assert target is not None, "Слайд плана («ВАРИАНТЫ БЮДЖЕТНОГО ПЛАНА») не найден"
    cells = [t.strip() for t in target]

    # Доказательство, что это именно слайд плана (footer «6/13»), а не оглавление
    # (footer «2/13») — эмпирически подтверждено дважды (zond5 и это же прогоном).
    assert "6/13" in cells, (
        f"Найден слайд с неожиданным footer (ожидали «6/13» — слайд плана): {cells}"
    )

    assert _missing_money_marked(cells), (
        f"«н/д» для отсутствующих денег не найдено как отдельная ячейка: {cells}"
    )
    assert not _false_zero_present(cells), (
        f"Ложный ноль в ячейках слайда прогноза (INV-50): {cells}"
    )


def test_forecast_missing_money_guard_catches_mutations(base_payload, tmp_path):
    """Сторож обязан уметь покраснеть — три обязательные мутации (Антон, 10.09.2026):
    1) «н/д» → «0» (в данных прогона) — проверка ложного нуля обязана упасть;
    2) «н/д» → «» (в данных прогона) — проверка «н/д» обязана упасть;
    3) слайд плана не строится вовсе (payload без forecast) — поиск слайда
       обязан провалиться сам, а не молча найти оглавление."""
    payload_fc = copy.deepcopy(base_payload)
    fc = copy.deepcopy(FORECAST_DATA)
    fc["scenarios"][0]["total_spend_money"] = None
    fc["scenarios"][0]["roas_money"] = None
    payload_fc["forecast"] = fc
    out = str(tmp_path / "deck_forecast_dash_mut.pptx")
    prs = _build_deck(payload_fc, out)

    idx, target = _find_forecast_plan_slide(prs)
    assert target is not None
    cells = [t.strip() for t in target]
    assert "н/д" in cells, "sanity: в реальном выводе нет «н/д» - мутацию ставить не на что"

    # Мутация 1: «н/д» → «0» (ложный ноль на месте отсутствующих денег).
    mutated_to_zero = ["0" if c == "н/д" else c for c in cells]
    assert _false_zero_present(mutated_to_zero), (
        "проверка не покраснела при подмене «н/д» на ложный ноль — мутация 1 не сработала"
    )

    # Мутация 2: «н/д» → «» (прочерк исчезает молча).
    mutated_to_empty = ["" if c == "н/д" else c for c in cells]
    assert not _missing_money_marked(mutated_to_empty), (
        "проверка не покраснела при подмене «н/д» на пустую строку — мутация 2 не сработала"
    )

    # Мутация 3: слайд плана не строится вовсе (payload без ключа 'forecast') —
    # поиск обязан провалиться (target is None), а НЕ молча подобрать оглавление
    # (что и было исходным дефектом до починки этой сессии).
    payload_no_fc = copy.deepcopy(base_payload)
    payload_no_fc.pop("forecast", None)
    out_no_fc = str(tmp_path / "deck_no_forecast_mut.pptx")
    prs_no_fc = _build_deck(payload_no_fc, out_no_fc)
    idx_no_fc, target_no_fc = _find_forecast_plan_slide(prs_no_fc)
    assert target_no_fc is None, (
        "слайд плана 'найден' в колоде без forecast — поиск матчится на что-то постороннее "
        f"(мутация 3 не сработала): idx={idx_no_fc}, texts={target_no_fc}"
    )


def test_toc_mentions_forecast_when_present(base_payload, tmp_path):
    """P-2 UX: оглавление содержит подстроку про прогноз при его наличии —
    и не содержит без него (INV-50)."""
    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = FORECAST_DATA
    out_fc = str(tmp_path / "deck_toc_fc.pptx")
    prs_fc = _build_deck(payload_fc, out_fc)
    toc_text = _xml_text(prs_fc)
    assert "в том числе «Планирование: прогноз на будущий период»" in toc_text, (
        "TOC-подстрока о прогнозе не найдена"
    )

    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("forecast", None)
    out_no = str(tmp_path / "deck_toc_no_fc.pptx")
    prs_no = _build_deck(payload_no, out_no)
    assert "в том числе «Планирование: прогноз на будущий период»" not in _xml_text(prs_no), (
        "TOC упоминает прогноз, которого нет (INV-50)"
    )


# ─── (b) Без forecast → кол-во слайдов не меняется (INV-50) ─────────────────

def test_no_forecast_no_extra_slide(base_payload, tmp_path):
    """Без forecast дека не получает лишний слайд-суррогат (INV-50)."""
    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("forecast", None)

    out1 = str(tmp_path / "deck_no_fc_1.pptx")
    out2 = str(tmp_path / "deck_no_fc_2.pptx")
    prs1 = _build_deck(payload_no, out1)
    prs2 = _build_deck(payload_no, out2)
    assert len(prs1.slides) == len(prs2.slides), "Без forecast кол-во слайдов нестабильно"

    # С пустым / невалидным forecast — тот же эффект
    payload_invalid = copy.deepcopy(base_payload)
    payload_invalid["forecast"] = {"status": "error"}
    out3 = str(tmp_path / "deck_invalid_fc.pptx")
    prs3 = _build_deck(payload_invalid, out3)
    assert len(prs3.slides) == len(prs1.slides), (
        "Невалидный forecast породил лишний слайд-суррогат (INV-50)"
    )


# ─── (c) Оговорки попадают в XML ─────────────────────────────────────────────

def test_forecast_disclaimers_in_xml(base_payload, tmp_path):
    """Оговорки из forecast.disclaimers должны присутствовать в тексте слайда."""
    payload_fc = copy.deepcopy(base_payload)
    payload_fc["forecast"] = copy.deepcopy(FORECAST_DATA)
    payload_fc["forecast"]["disclaimers"] = ["неизменных условиях"]
    payload_fc["forecast"]["scenarios"][0]["disclaimers"] = ["неизменных условиях"]

    out = str(tmp_path / "deck_disclaimers.pptx")
    prs = _build_deck(payload_fc, out)
    all_text = _xml_text(prs)
    assert "неизменных условиях" in all_text, (
        "Оговорки из forecast не попали в XML колоды"
    )


# ─── (d) _page_shift == 3 при backtest + gen_compare + forecast ──────────────

def test_page_shift_all_three(base_payload):
    """При backtest + gen_compare + forecast _page_shift должен быть 3."""
    payload = copy.deepcopy(base_payload)

    # Минимальный валидный backtest
    payload["backtest"] = {
        "status": "ok",
        "windows": [{"window": "Q1", "actual_total": 100, "predicted_total": 98,
                     "pi_low_total": 80, "pi_high_total": 120, "hit_total": True}],
        "windows_hit_total": 1,
        "windows_with_interval": 1,
        "verdict": "validated",
        "granularity": "M",
        "horizon_periods": 3,
        "mape_model": 5.0,
        "mape_naive_best": 10.0,
        "coverage_per_period": 0.9,
        "n_holdout_points_with_interval": 3,
    }

    # Минимальный валидный gen_compare
    payload["generation_compare"] = {
        "status": "ok",
        "channels": [{"name": "TV", "roi_old": 1.2, "roi_new": 1.5,
                      "verdict": "stable", "verdict_ru": "стабильно"}],
        "summary": {"counts": {"stable": 1, "shift_within_ci": 0, "shift_strong": 0}},
        "baseline": {"timestamp": "2026-01-01T00:00:00"},
    }

    # Forecast
    payload["forecast"] = FORECAST_DATA

    builder = AuroraPPTXBuilder(payload)
    assert builder._page_shift == 3, (
        f"Ожидали _page_shift=3 при backtest+gen_compare+forecast, "
        f"получили {builder._page_shift}"
    )
    assert builder.total_slides == 15, (
        f"Ожидали total_slides=15, получили {builder.total_slides}"
    )


# ─── (e) HTML: нет forecast → render_forecast_plan возвращает "" ─────────────

def test_html_render_forecast_empty_without_data():
    """render_forecast_plan возвращает '' при отсутствии forecast (INV-50)."""
    assert render_forecast_plan(_s({})) == ""
    assert render_forecast_plan(_s({"forecast": None})) == ""
    assert render_forecast_plan(_s({"forecast": {}})) == ""
    assert render_forecast_plan(_s({"forecast": {"status": "error"}})) == ""
    assert render_forecast_plan(_s({"forecast": {"status": "ok", "scenarios": []}})) == ""


# ─── (f) HTML: есть forecast → render_forecast_plan возвращает таблицу ───────

def test_html_render_forecast_with_data():
    """render_forecast_plan возвращает HTML-таблицу при наличии forecast."""
    ctx = _s({"forecast": FORECAST_DATA})
    html = render_forecast_plan(ctx)
    assert html != "", "render_forecast_plan вернул '' при валидных данных"
    assert "Прогноз" in html, "Заголовок «Прогноз» не найден в HTML"
    assert "Базовый" in html, "Название сценария «Базовый» не найден в HTML"
    assert "неизменных условиях" in html, "Оговорка не попала в HTML"
    assert "<table" in html, "Таблица сценариев не найдена в HTML"
    assert "★" in html, "Звёздочка accepted-сценария не найдена в HTML"


def test_html_render_forecast_multiple_scenarios():
    """Несколько сценариев: показываем до 4, остальные отбрасываем."""
    fc = copy.deepcopy(FORECAST_DATA)
    fc["scenarios"] = [
        {**fc["scenarios"][0], "name": f"Сценарий {i}", "variant_id": f"v{i}"}
        for i in range(6)
    ]
    fc["accepted_variant"] = "v2"
    html = render_forecast_plan(_s({"forecast": fc}))
    # Первые 4 сценария должны быть, 5-й и 6-й — нет
    assert "Сценарий 0" in html
    assert "Сценарий 3" in html
    assert "Сценарий 4" not in html
    assert "Сценарий 5" not in html


# ─── scenarios_comparison_chart ───────────────────────────────────────────────

def test_scenarios_comparison_chart_basic():
    """scenarios_comparison_chart генерирует непустой base64 PNG для 1 сценария."""
    from charts.generators import scenarios_comparison_chart
    import base64

    scenarios = [
        {
            "name": "Базовый",
            "total_kpi": 460.0,
            "total_spend_money": 5_000_000.0,
            "roas_money": 0.092,
        }
    ]
    result = scenarios_comparison_chart(scenarios)
    assert result != "", "scenarios_comparison_chart вернул пустую строку для 1 сценария"
    # Проверяем что это валидный base64
    decoded = base64.b64decode(result)
    assert len(decoded) > 100, "base64-строка слишком короткая, PNG невалиден"


def test_scenarios_comparison_chart_five_or_more():
    """При >=5 вариантах возвращается валидный base64 (горизонтальный layout)."""
    from charts.generators import scenarios_comparison_chart
    import base64

    scenarios = [
        {
            "name": f"Вариант {i + 1}",
            "total_kpi": float(400 + i * 20),
            "total_spend_money": float(5_000_000 + i * 500_000),
            "roas_money": round(0.08 + i * 0.01, 3),
        }
        for i in range(6)
    ]
    result = scenarios_comparison_chart(scenarios)
    assert result != "", "scenarios_comparison_chart вернул '' для 6 вариантов"
    decoded = base64.b64decode(result)
    assert len(decoded) > 100, "PNG для 6 вариантов невалиден"


def test_scenarios_comparison_chart_with_ci():
    """График с доверительными интервалами не падает, CI берётся из predictions_ci_low/high."""
    from charts.generators import scenarios_comparison_chart
    import base64

    scenarios = [
        {
            "name": "С интервалами",
            "total_kpi": 460.0,
            "predictions_ci_low": [90, 99, 108, 117],
            "predictions_ci_high": [110, 121, 132, 143],
        },
        {
            "name": "Без интервалов",
            "total_kpi": 440.0,
        },
    ]
    result = scenarios_comparison_chart(scenarios, kpi_label="Продажи")
    assert result != "", "scenarios_comparison_chart упал при смешанном наличии CI"
    base64.b64decode(result)  # не должно кидать исключение


def test_scenarios_comparison_chart_empty_returns_empty():
    """Пустой список сценариев возвращает пустую строку, не падает."""
    from charts.generators import scenarios_comparison_chart

    assert scenarios_comparison_chart([]) == "", "Пустой список должен возвращать ''"
    assert scenarios_comparison_chart(None) == "", "None должен возвращать ''"


def test_scenarios_comparison_chart_skips_none_kpi():
    """P-2 (аудит 2026-07-16): сценарий с total_kpi=None исключается из графика
    (таблица рядом рисует «—» — нулевой столбец был бы ложью того же класса);
    если ни у одного сценария нет KPI — график не строится вовсе."""
    from charts.generators import scenarios_comparison_chart
    import base64

    mixed = [
        {"name": "С данными", "total_kpi": 460.0},
        {"name": "Без данных", "total_kpi": None},
    ]
    result = scenarios_comparison_chart(mixed)
    assert result != "", "График должен строиться по сценариям с KPI"
    base64.b64decode(result)

    all_none = [{"name": "v1", "total_kpi": None}, {"name": "v2", "total_kpi": None}]
    assert scenarios_comparison_chart(all_none) == "", (
        "Без единого KPI график обязан вернуть '' (INV-50), а не нулевые столбцы"
    )


# ─── HTML: блок планирования рисует ЖИВОЙ график, а не картинку ─────────────
# 14.09.2026 (жалоба владельца): здесь стояла растровая картинка matplotlib –
# единственная среди девяти графиков отчёта. Сторожа ниже держат два условия:
# (1) в блоке живой контейнер ECharts, а не <img>; (2) ось значений не
# начинается с нуля на близких значениях – иначе разница вариантов не видна, –
# и усечение честно подписано (INV-50).


def _forecast_chart_payload(html_str: str) -> dict:
    """Данные живого графика из атрибута контейнера (сущности → JSON)."""
    import re
    from html import unescape

    m = re.search(r'data-payload="([^"]*)"', html_str)
    assert m, "В блоке планирования нет контейнера с данными живого графика"
    return json.loads(unescape(m.group(1)))


def _fc_two(kpi_a=460.0, kpi_b=520.0, ci_a=(414.0, 506.0), ci_b=(468.0, 572.0)):
    """Прогноз с двумя вариантами; ci_* = None → вариант без диапазона."""
    fc = copy.deepcopy(FORECAST_DATA)
    base = fc["scenarios"][0]
    def _mk(name, vid, kpi, ci):
        sc = {**base, "name": name, "variant_id": vid, "total_kpi": kpi}
        if ci is None:
            sc.pop("total_kpi_ci_low", None)
            sc.pop("total_kpi_ci_high", None)
        else:
            sc["total_kpi_ci_low"], sc["total_kpi_ci_high"] = ci
        return sc
    fc["scenarios"] = [_mk("Базовый", "v1", kpi_a, ci_a),
                       _mk("Агрессивный", "v2", kpi_b, ci_b)]
    fc["accepted_variant"] = "v1"
    return fc


def test_html_forecast_chart_is_live_not_raster():
    """При ≥2 сценариях в блоке планирования живой контейнер ECharts, не <img>.

    Сторож на возврат к картинке: растровая вставка ломает единство отчёта –
    остальные восемь графиков интерактивные и следуют теме.
    """
    html = render_forecast_plan(_s({"forecast": _fc_two()}))
    assert 'id="chart-forecast-compare"' in html, (
        "Ожидаем живой контейнер графика сравнения вариантов"
    )
    assert 'class="chart-host"' in html, "Контейнер должен быть тем же chart-host, что у остальных"
    assert "data-payload=" in html, "Данные графика должны ехать в атрибуте контейнера"
    assert "<img" not in html, "Растровая картинка в блоке планирования запрещена"
    assert "data:image/png;base64," not in html, (
        "base64-PNG в блоке планирования запрещён – график обязан быть живым"
    )


def test_html_forecast_chart_payload_matches_scenarios():
    """Имена, значения и диапазоны в данных графика совпадают со сценариями."""
    html = render_forecast_plan(_s({"forecast": _fc_two()}))
    p = _forecast_chart_payload(html)
    assert p["names"] == ["Базовый", "Агрессивный"]
    assert p["values"] == [460.0, 520.0]
    assert p["ci"] == [[414.0, 506.0], [468.0, 572.0]]
    assert p["accepted"] == "Базовый", "Принятый вариант должен называться для выделения цветом"


def test_html_forecast_chart_axis_does_not_start_at_zero():
    """Близкие значения → ось начинается не с нуля и это подписано.

    Сторож на возврат к отсчёту от нуля: при 1000.0 против 1000.5 столбцы от
    нуля неразличимы. Усечение обязано быть названо вслух – неподписанная
    усечённая ось преувеличивает разницу (INV-50).
    """
    html = render_forecast_plan(_s({"forecast": _fc_two(
        kpi_a=1000.0, kpi_b=1000.5, ci_a=None, ci_b=None)}))
    p = _forecast_chart_payload(html)
    assert p["yMin"] > 0, "На близких значениях ось обязана начинаться выше нуля"
    assert p["yMin"] < 1000.0 < p["yMax"], "Границы обязаны накрывать сами значения"
    assert p["zeroExcluded"] is True, "Признак усечения обязан быть выставлен"
    assert "Шкала начинается не с нуля" in html, (
        "Усечённая ось обязана быть подписана рядом с графиком"
    )


def test_html_forecast_chart_axis_covers_ci_bounds():
    """Границы оси накрывают края правдоподобных диапазонов – усы помещаются."""
    html = render_forecast_plan(_s({"forecast": _fc_two()}))
    p = _forecast_chart_payload(html)
    lows = [c[0] for c in p["ci"] if c]
    highs = [c[1] for c in p["ci"] if c]
    assert p["yMin"] <= min(lows), "Нижняя граница оси обязана накрывать низ диапазона"
    assert p["yMax"] >= max(highs), "Верхняя граница оси обязана накрывать верх диапазона"


def test_html_forecast_chart_identical_values_do_not_break():
    """Два одинаковых значения: диапазон не вырождается в точку, деления на ноль нет."""
    html = render_forecast_plan(_s({"forecast": _fc_two(
        kpi_a=500.0, kpi_b=500.0, ci_a=None, ci_b=None)}))
    p = _forecast_chart_payload(html)
    assert p["yMax"] > p["yMin"], "Вырожденный диапазон обязан быть расширен"
    assert p["yMin"] < 500.0 < p["yMax"]


def test_html_forecast_chart_negative_values():
    """Отрицательные прогнозы: ось уходит в минус, ноль сверху не приписывается."""
    html = render_forecast_plan(_s({"forecast": _fc_two(
        kpi_a=-100.0, kpi_b=-50.0, ci_a=None, ci_b=None)}))
    p = _forecast_chart_payload(html)
    assert p["yMin"] < -100.0 and p["yMax"] < 0, "Ось обязана лежать в минусе"
    assert p["zeroExcluded"] is True


def test_html_forecast_chart_mixed_signs_keep_zero():
    """Плюс и минус вместе: ось обязана показать ноль, пометки об усечении нет."""
    html = render_forecast_plan(_s({"forecast": _fc_two(
        kpi_a=-20.0, kpi_b=80.0, ci_a=None, ci_b=None)}))
    p = _forecast_chart_payload(html)
    assert p["yMin"] < 0 < p["yMax"], "При разных знаках ноль обязан остаться на оси"
    assert p["zeroExcluded"] is False
    assert "Шкала начинается не с нуля" not in html, (
        "Пометка об усечении не должна печататься, когда ноль на оси есть"
    )


def test_html_forecast_chart_without_ci():
    """Вариант без правдоподобного диапазона: график строится, усов нет."""
    html = render_forecast_plan(_s({"forecast": _fc_two(ci_a=None, ci_b=None)}))
    p = _forecast_chart_payload(html)
    assert p["ci"] == [None, None]
    assert "Серая полоса" not in html, "Без диапазонов подпись про полосу не нужна"


def test_html_forecast_chart_absent_for_one_scenario():
    """При одном сценарии сравнивать не с чем – графика нет."""
    fc = copy.deepcopy(FORECAST_DATA)
    assert len(fc["scenarios"]) == 1
    html = render_forecast_plan(_s({"forecast": fc}))
    assert html != "", "Секция должна рендериться даже при 1 сценарии"
    assert "chart-forecast-compare" not in html, "При 1 сценарии график не строится"
    assert "<img" not in html, "Картинки в блоке планирования нет ни при каком числе вариантов"


def test_html_forecast_chart_skips_scenario_without_kpi():
    """Вариант без прогноза столбцом не рисуется (INV-50), остальные – да."""
    fc = _fc_two()
    fc["scenarios"].append({**fc["scenarios"][0], "name": "Пустой",
                            "variant_id": "v3", "total_kpi": None})
    html = render_forecast_plan(_s({"forecast": fc}))
    p = _forecast_chart_payload(html)
    assert "Пустой" not in p["names"], "Вариант без прогноза не должен попадать в график"
    assert len(p["names"]) == 2


# ─── Движок отчёта: построитель живого графика на месте ─────────────────────

def test_report_engine_initializes_all_nine_charts():
    """Движок запускает все девять графиков отчёта, а не часть.

    14.09.2026: добавляя девятый график (сравнение вариантов плана), легко
    отхватить чужой запуск – своя точка входа `initChartFromHost` живёт рядом
    с общим `initChart`, и достаточно промахнуться скобкой, чтобы часть
    вызовов ушла из `initAllCharts`. Сторож перечисляет идентификаторы
    поимённо: пропажа любого видна сразу, а не по жалобе «половины графиков
    нет».
    """
    from aurora_html.interactive import bootstrap_js

    js = bootstrap_js("light", "{}", "{}", {})
    boot = js.split("function initAllCharts", 1)[1].split("// ─── Drill-down", 1)[0]
    for chart_id in (
        "chart-mroas", "chart-share", "chart-timeline", "chart-optimize",
        "chart-waterfall", "chart-quality-avp", "chart-quality-residuals",
        "chart-quality-scatter", "chart-forecast-compare",
    ):
        assert "'%s'" % chart_id in boot, (
            "График '%s' не запускается в initAllCharts – в отчёте он останется "
            "пустым контейнером" % chart_id
        )


def test_report_engine_avoids_series_absent_from_bundled_echarts():
    """Движок не просит серий, которых нет в поставляемой сборке ECharts.

    Боем 14.09.2026: правдоподобный диапазон был нарисован серией `custom`,
    и ECharts выбросил её МОЛЧА – ни исключения, ни записи в консоли, серия
    просто исчезала из getOption(), а клиент получил бы график без
    диапазонов. Проверено в браузере на `echarts.common.5.5.1.min.js`:
    custom, candlestick и boxplot дают 0 серий, bar/line/scatter/pie – по
    одной. Дешёвый сторож на весь движок, не только на блок планирования.
    """
    from aurora_html.interactive import bootstrap_js

    js = bootstrap_js("light", "{}", "{}", {})
    for kind in ("custom", "candlestick", "boxplot"):
        assert "type: '%s'" % kind not in js, (
            "Серия '%s' отсутствует в поставляемой сборке ECharts и будет "
            "выброшена молча – график уедет к клиенту неполным" % kind
        )


def test_report_engine_has_forecast_compare_builder():
    """JS-движок отчёта содержит построитель и запуск графика планирования."""
    from aurora_html.interactive import bootstrap_js

    js = bootstrap_js("light", "{}", "{}", {})
    assert "buildForecastCompareOption" in js, "Построитель графика планирования отсутствует"
    assert "initChartFromHost('chart-forecast-compare'" in js, (
        "График планирования не запускается при загрузке отчёта"
    )


# ─── Границы оси: вырожденные случаи считаются без падения ──────────────────

def test_forecast_axis_range_degenerate_cases():
    """Пустой ввод, единственное значение, нули – ответ корректный, деления на ноль нет."""
    from aurora_html.sections import _forecast_axis_range

    lo, hi, zero_excluded = _forecast_axis_range([], [])
    assert hi > lo and zero_excluded is False

    lo, hi, zero_excluded = _forecast_axis_range([460.0], [[414.0, 506.0]])
    assert lo < 414.0 and hi > 506.0 and zero_excluded is True

    lo, hi, zero_excluded = _forecast_axis_range([0.0, 0.0], [None, None])
    assert hi >= lo and zero_excluded is False, "На нулях усечения быть не может"

    lo, hi, zero_excluded = _forecast_axis_range([None, None], [None, None])
    assert hi > lo and zero_excluded is False


def test_forecast_axis_range_wide_spread_keeps_zero():
    """Широкий разброс: запас дотягивает до нуля – ось честно начинается с нуля."""
    from aurora_html.sections import _forecast_axis_range

    lo, hi, zero_excluded = _forecast_axis_range([5.0, 100.0], [None, None])
    assert lo == 0.0, "Запас не должен уводить положительные значения в минус"
    assert zero_excluded is False, "Ноль на оси есть – пометка об усечении не нужна"


# ─── HTML: render_retro_insights ──────────────────────────────────────────────

def test_retro_insights_empty_for_reliable_model():
    """Блок «Что улучшить» пустой при reliable-модели."""
    from aurora_html.sections import render_retro_insights

    ctx = _s({"diagnostics": {"honesty_verdict": "reliable", "honesty_reasons": ["Всё хорошо"]}})
    assert render_retro_insights(ctx) == "", "При reliable-модели блок должен быть пустым"


def test_retro_insights_empty_without_diagnostics():
    """Блок «Что улучшить» пустой при отсутствии диагностики."""
    from aurora_html.sections import render_retro_insights

    assert render_retro_insights(_s({})) == ""
    assert render_retro_insights(_s({"diagnostics": {}})) == ""


def test_retro_insights_present_for_uncertain_model():
    """Блок «Что улучшить» появляется при uncertain-модели с reasons."""
    from aurora_html.sections import render_retro_insights

    ctx = _s({
        "diagnostics": {
            "honesty_verdict": "uncertain",
            "honesty_reasons": ["Мало наблюдений", "Широкие интервалы"],
            "thinness_cap": 50,
            "ratio": 1.8,
        }
    })
    html = render_retro_insights(ctx)
    assert html != "", "При uncertain-модели блок должен присутствовать"
    assert "Мало наблюдений" in html, "Причины honesty_reasons должны быть в тексте"
    assert "Что улучшить" in html, "Заголовок «Что улучшить» должен быть в тексте"


def test_retro_insights_present_for_unreliable_model():
    """Блок «Что улучшить» появляется при unreliable-модели."""
    from aurora_html.sections import render_retro_insights

    ctx = _s({
        "diagnostics": {
            "honesty_verdict": "unreliable",
            "honesty_reasons": ["R-hat > 1.05", "ESS < 100"],
            "r_squared": 0.45,
            "mape_pct": 28.0,
        }
    })
    html = render_retro_insights(ctx)
    assert html != "", "При unreliable-модели блок должен присутствовать"
    assert "R-hat" in html
    assert "R²" in html, "Должен быть пункт про низкий R²"
    assert "MAPE" in html, "Должен быть пункт про высокий MAPE"


def test_retro_insights_preflight_fail():
    """Блок включает пункт про provail приоров при prior_predictive_status=fail."""
    from aurora_html.sections import render_retro_insights

    ctx = _s({
        "diagnostics": {
            "honesty_verdict": "uncertain",
            "preflight": {
                "prior_predictive_status": "fail",
                "prior_predictive_coverage": 0.42,
            },
        }
    })
    html = render_retro_insights(ctx)
    assert html != ""
    assert "Априорные предположения расходятся" in html
    assert "42%" in html


# ─── (g) HTML-отчёт: пункт оглавления «Прогноз» ведёт в никуда без сценариев ──
# Находка внешнего аудита 13.09.2026 (повторная проверка): render_forecast_plan
# (sections.py:2488) честно возвращает "" без сценариев, а _toc_items
# (aurora_html/builder.py) добавлял пункт «Прогноз» БЕЗУСЛОВНО — читатель кликал
# и попадал на отсутствующий якорь #forecast. У «trust» такой же пропуск уже
# стоял (comment builder.py:548-556); теперь зеркально сделан и для «forecast».
# Четыре состояния — ровно те, что аудитор прогнал на боевом сборщике.

def test_html_toc_skips_forecast_link_without_scenarios(base_payload):
    """Пункта «Прогноз» в оглавлении нет ни без forecast, ни с пустыми/невалидными
    сценариями, ни при непройденном шаге (status != ok) — и он есть, когда
    сценарии реально сохранены."""
    # 1. forecast отсутствует вовсе (демо-проект без сохранённого плана).
    payload_absent = copy.deepcopy(base_payload)
    payload_absent.pop("forecast", None)
    toc = AuroraHTMLBuilder(payload_absent)._toc_items()
    assert 'data-toc-target="forecast"' not in toc, "пункт «Прогноз» есть при отсутствующем forecast"

    # 2. planning.json есть, но сценарии пустые.
    payload_empty = copy.deepcopy(base_payload)
    payload_empty["forecast"] = {"status": "ok", "scenarios": []}
    toc = AuroraHTMLBuilder(payload_empty)._toc_items()
    assert 'data-toc-target="forecast"' not in toc, "пункт «Прогноз» есть при пустых сценариях"

    # 3. Шаг не пройден (status != "ok").
    payload_not_ok = copy.deepcopy(base_payload)
    payload_not_ok["forecast"] = {"status": "error", "scenarios": [FORECAST_DATA["scenarios"][0]]}
    toc = AuroraHTMLBuilder(payload_not_ok)._toc_items()
    assert 'data-toc-target="forecast"' not in toc, "пункт «Прогноз» есть при status != ok"

    # 4. Сценарии реально сохранены (норма) — пункт обязан присутствовать.
    payload_ok = copy.deepcopy(base_payload)
    payload_ok["forecast"] = FORECAST_DATA
    toc = AuroraHTMLBuilder(payload_ok)._toc_items()
    assert 'data-toc-target="forecast"' in toc, "пункт «Прогноз» пропал при реально сохранённых сценариях"
