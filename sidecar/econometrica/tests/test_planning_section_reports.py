"""
Раздел «Планирование» в уносимых документах (13.09.2026).

Шаг «Планирование» показывал клиенту на экране срок плана, принятый вариант с
правдоподобным диапазоном, отличие от базового плана из файла и вердикт
различимости вариантов – а в колоде и веб-отчёте оставалась одна таблица
сценариев без единого из этих ответов. Человек уносил со встречи документ без
того, ради чего считали.

Покрывают:
  (a) summarize_forecast – сводка считается из тех же сценариев, что на экране
  (b) summarize_forecast – отсутствующее значение остаётся None (INV-50)
  (c) summarize_forecast – вердикт различимости: перекрытие / непересечение
  (d) HTML – срок, принятый план, диапазон, отличие от базового, вердикт
  (e) HTML – без базового плана колонки Δ и блока отличия нет
  (f) PPTX – блоки раздела попадают в XML слайда
  (g) SSOT – число в документе равно числу в results/scenarios/<имя>.json
"""
import copy
import json
import os

import pytest

from aurora_html.sections import render_forecast_plan
from engines.planning import BASELINE_VARIANT_NAME, summarize_forecast

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(
    os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json"),
    encoding="utf-8",
) as _f:
    _STRINGS = json.load(_f)


def _s(ctx: dict) -> dict:
    """ctx["strings"] кладёт боевой builder — sections.py читает без .get()."""
    return {**ctx, "strings": _STRINGS}


def _scenario(name, kpi, lo, hi, spend, roas=1.5, labels=("2026-01", "2026-02", "2026-03")):
    return {
        "name": name,
        "variant_id": name,
        "predictions": [kpi / 3.0] * 3,
        "ci_low": [lo / 3.0] * 3,
        "ci_high": [hi / 3.0] * 3,
        "total_kpi": kpi,
        "total_kpi_ci_low": lo,
        "total_kpi_ci_high": hi,
        "total_spend_money": spend,
        "roas_money": roas,
        "period_labels": list(labels),
        "disclaimers": [],
    }


def _forecast(scenarios, accepted):
    return {
        "status": "ok",
        "scenarios": scenarios,
        "accepted_variant": accepted,
        "disclaimers": ["прогноз при неизменных прочих условиях"],
    }


# Базовый план из файла и вариант «что если» с бОльшим бюджетом. Диапазоны
# перекрываются (10 000 < 12 500 и 11 500 < 13 000) – вердикт «не доказано».
FC_TWO = _forecast(
    [
        _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
        _scenario("Плюс 20%", 12_000.0, 11_500.0, 12_500.0, 6_000_000.0),
    ],
    accepted="Плюс 20%",
)


# ─── (a) сводка ───────────────────────────────────────────────────────────────

def test_summary_reads_screen_numbers():
    """Сводка берёт горизонт, принятый вариант и отличие от базового."""
    s = summarize_forecast(FC_TWO)
    assert s is not None
    assert s["horizon_periods"] == 3
    assert s["period_first"] == "2026-01"
    assert s["period_last"] == "2026-03"
    assert s["accepted"]["name"] == "Плюс 20%"
    assert s["accepted"]["total_kpi"] == 12_000.0
    # ширина диапазона = (12 500 – 11 500) / 12 000 = 8,33%
    assert s["accepted"]["ci_width_pct"] == pytest.approx(8.3333, rel=1e-3)
    assert s["baseline"]["name"] == BASELINE_VARIANT_NAME
    d = s["diff_vs_baseline"]
    assert d["spend_abs"] == 1_000_000.0
    assert d["spend_pct"] == pytest.approx(20.0)
    assert d["kpi_abs"] == 1_000_000.0 / 1_000.0  # 1 000
    assert d["kpi_pct"] == pytest.approx(9.0909, rel=1e-3)


def test_summary_none_without_live_plan():
    """Нет живого плана – сводки нет, суррогата тоже (INV-50)."""
    assert summarize_forecast(None) is None
    assert summarize_forecast({}) is None
    assert summarize_forecast({"status": "error", "scenarios": [_scenario("A", 1, 1, 1, 1)]}) is None
    assert summarize_forecast({"status": "ok", "scenarios": []}) is None


# ─── (b) отсутствующее значение не подменяется нулём ──────────────────────────

def test_summary_missing_values_stay_none():
    """Бюджет не переведён в рубли (физметрика) – None, а не 0."""
    fc = copy.deepcopy(FC_TWO)
    for sc in fc["scenarios"]:
        sc["total_spend_money"] = None
        sc["roas_money"] = None
    s = summarize_forecast(fc)
    assert s["accepted"]["total_spend_money"] is None
    assert s["accepted"]["roas_money"] is None
    # Отличие по KPI остаётся, отличие по бюджету посчитать не из чего.
    assert s["diff_vs_baseline"]["spend_abs"] is None
    assert s["diff_vs_baseline"]["kpi_abs"] == 1_000.0


def test_summary_no_baseline_no_diff():
    """Базового плана среди сценариев нет – блока отличия нет вовсе."""
    fc = _forecast(
        [
            _scenario("Вариант 1", 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
            _scenario("Вариант 2", 12_000.0, 11_500.0, 12_500.0, 6_000_000.0),
        ],
        accepted="Вариант 2",
    )
    s = summarize_forecast(fc)
    assert s["baseline"] is None
    assert s["diff_vs_baseline"] is None


# ─── (c) вердикт различимости ─────────────────────────────────────────────────

def test_verdict_overlap():
    """Диапазоны пересекаются – преимущество лидера данными не доказано."""
    s = summarize_forecast(FC_TWO)
    assert s["verdict"]["kind"] == "overlap"
    assert s["verdict"]["leader"] == "Плюс 20%"
    assert s["verdict"]["runner_up"] == BASELINE_VARIANT_NAME


def test_verdict_distinct():
    """Нижняя граница лидера выше верхней границы второго – устойчиво лучше."""
    fc = _forecast(
        [
            _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 11_400.0, 5_000_000.0),
            _scenario("Плюс 20%", 13_000.0, 12_000.0, 14_000.0, 6_000_000.0),
        ],
        accepted="Плюс 20%",
    )
    s = summarize_forecast(fc)
    assert s["verdict"]["kind"] == "distinct"
    assert s["verdict"]["leader"] == "Плюс 20%"


def test_verdict_silent_on_exact_touch():
    """Границы совпали ровно – молчим, как и панель подсказок на экране."""
    fc = _forecast(
        [
            _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 12_000.0, 5_000_000.0),
            _scenario("Плюс 20%", 13_000.0, 12_000.0, 14_000.0, 6_000_000.0),
        ],
        accepted="Плюс 20%",
    )
    assert summarize_forecast(fc)["verdict"] is None


def test_verdict_needs_two_comparable():
    """Один сравнимый вариант – вердикта нет (сравнивать не с чем)."""
    fc = _forecast([_scenario("Один", 11_000.0, 10_000.0, 12_000.0, 5_000_000.0)], accepted="Один")
    assert summarize_forecast(fc)["verdict"] is None


# ─── (d) веб-отчёт ────────────────────────────────────────────────────────────

def test_html_section_carries_planning_answers():
    """В разделе есть срок, принятый план, диапазон, отличие и вердикт."""
    html = render_forecast_plan(_s({"forecast": FC_TWO}))
    assert "Срок плана" in html and "3 периода" in html
    assert "2026-01" in html and "2026-03" in html
    assert "Принятый план" in html
    assert "Правдоподобный диапазон" in html
    assert "11 500 – 12 500" in html
    assert "Чем план отличается" in html
    assert "+1 000 000 ₽" in html and "+20%" in html
    assert "Различимы ли варианты" in html
    assert "не доказано" in html
    # Δ к базовому плану в таблице сравнения
    assert "Δ к «Базовый план»" in html
    assert "+9%" in html


def test_html_section_horizon_absent_without_labels():
    """Меток периодов нет – строки срока нет, выдуманного срока тоже."""
    fc = copy.deepcopy(FC_TWO)
    for sc in fc["scenarios"]:
        sc["period_labels"] = []
        sc["predictions"] = []
    html = render_forecast_plan(_s({"forecast": fc}))
    assert "Срок плана" not in html


# ─── (e) без базового плана ───────────────────────────────────────────────────

def test_html_section_without_baseline_has_no_delta():
    """Нет базового плана – ни блока отличия, ни колонки Δ."""
    fc = _forecast(
        [
            _scenario("Вариант 1", 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
            _scenario("Вариант 2", 12_000.0, 11_500.0, 12_500.0, 6_000_000.0),
        ],
        accepted="Вариант 2",
    )
    html = render_forecast_plan(_s({"forecast": fc}))
    assert "Чем план отличается" not in html
    assert "Δ к" not in html


# ─── (g) SSOT: документ читает те же файлы, что экран ─────────────────────────

def test_document_numbers_come_from_scenario_files(tmp_path):
    """Число раздела равно числу в results/scenarios/<имя>.json (тот же файл,
    который показывает экран шага). Путь целиком: манифест → сценарий →
    load_saved_forecast → summarize_forecast → HTML."""
    from engines.planning import load_saved_forecast, save_planning_manifest

    sc_dir = tmp_path / "results" / "scenarios"
    sc_dir.mkdir(parents=True)
    for name, kpi, lo, hi, spend in (
        (BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
        ("Плюс 20%", 12_000.0, 11_500.0, 12_500.0, 6_000_000.0),
    ):
        (sc_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "scenario_name": name,
                    "predictions": [kpi / 3.0] * 3,
                    "future_dates": ["2026-01", "2026-02", "2026-03"],
                    "totals": {
                        "predicted_kpi": kpi,
                        "predicted_kpi_ci_low": lo,
                        "predicted_kpi_ci_high": hi,
                        "total_spend_money": spend,
                        "roas_money": 1.5,
                    },
                    "disclaimers": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    save_planning_manifest(str(tmp_path), [BASELINE_VARIANT_NAME, "Плюс 20%"], "Плюс 20%", [])

    loaded = load_saved_forecast(str(tmp_path))
    s = summarize_forecast(loaded)
    assert s["accepted"]["total_kpi"] == 12_000.0
    assert s["accepted"]["total_spend_money"] == 6_000_000.0

    html = render_forecast_plan(_s({"forecast": loaded}))
    assert "12 000" in html
    assert "6 000 000" in html


# ─── (f) колода ───────────────────────────────────────────────────────────────

_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

_WATERFALL = {
    "labels": ["База", "ТВ", "Радио", "Итого"],
    "values": [700_000.0, 200_000.0, 100_000.0, 1_000_000.0],
    "types": ["baseline", "channel", "channel", "total"],
}


@pytest.fixture(scope="module")
def base_payload():
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _deck_text(payload, path):
    from aurora_pptx.builder import AuroraPPTXBuilder
    prs = AuroraPPTXBuilder(payload).build()
    prs.save(path)
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return prs, "\n".join(texts)


def test_deck_planning_slide_carries_answers(base_payload, tmp_path):
    """Слайд плана несёт срок, принятый вариант, отличие от базового и вердикт."""
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_TWO
    _, text = _deck_text(payload, str(tmp_path / "deck_plan.pptx"))
    assert "Срок плана: 3 периода" in text
    assert "2026-01 – 2026-03" in text
    assert "Принятый план: «Плюс 20%»" in text
    assert "правдоподобный диапазон (90%) 11 500 – 12 500" in text
    assert "Против «Базовый план»" in text
    assert "+1 000 000 ₽" in text
    assert "не доказано" in text


def test_deck_planning_slide_no_overflow(base_payload, tmp_path):
    """Расширенный слайд плана не наезжает сам на себя."""
    from aurora_pptx.check_overflow import check

    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_TWO
    payload["waterfall"] = _WATERFALL
    out = str(tmp_path / "deck_plan_overflow.pptx")
    _deck_text(payload, out)
    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"Колода с планом и декомпозицией получила наезд:\n{detail}"


# ─── (б) декомпозиция в колоде ────────────────────────────────────────────────

def test_deck_decomposition_slide_appears_with_waterfall(base_payload, tmp_path):
    """Функция графика декомпозиции была написана и не вызывалась ни разу –
    теперь при живом waterfall колода получает свой слайд «Декомпозиция продаж»."""
    without = copy.deepcopy(base_payload)
    without.pop("waterfall", None)
    prs_without, text_without = _deck_text(without, str(tmp_path / "d0.pptx"))

    with_wf = copy.deepcopy(base_payload)
    with_wf["waterfall"] = _WATERFALL
    prs_with, text_with = _deck_text(with_wf, str(tmp_path / "d1.pptx"))

    assert "Декомпозиция продаж" not in text_without
    assert "Декомпозиция продаж" in text_with
    assert "БАЗОВЫЙ СПРОС И ВКЛАД КАЖДОГО КАНАЛА" in text_with
    assert len(prs_with.slides) == len(prs_without.slides) + 1


def test_deck_decomposition_chart_is_native_with_waterfall_numbers(base_payload, tmp_path):
    """График – родная диаграмма PowerPoint с теми же числами, что в веб-отчёте."""
    payload = copy.deepcopy(base_payload)
    payload["waterfall"] = _WATERFALL
    prs, _ = _deck_text(payload, str(tmp_path / "d2.pptx"))

    charts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_chart:
                charts.append(shape.chart)
    decomp = [
        c for c in charts
        if [str(x) for x in c.plots[0].categories] == _WATERFALL["labels"]
    ]
    assert decomp, "Родной диаграммы с категориями декомпозиции в колоде нет"
    values = list(decomp[0].plots[0].series[0].values)
    assert values == _WATERFALL["values"], (
        f"Числа графика разошлись с waterfall: {values}"
    )


def test_deck_decomposition_needs_live_numbers(base_payload, tmp_path):
    """Меток и значений разной длины быть не должно – слайда нет, суррогата нет."""
    payload = copy.deepcopy(base_payload)
    payload["waterfall"] = {"labels": ["База", "ТВ"], "values": [1.0], "types": []}
    _, text = _deck_text(payload, str(tmp_path / "d3.pptx"))
    assert "Декомпозиция продаж" not in text


def test_adapter_passes_waterfall_to_deck():
    """Адаптер кладёт waterfall из декомпозиции – без этого билдер вызвать
    график не мог, потому что чисел у него не было."""
    from engines.narrative_adapter import _map_pipeline_to_builder_data

    data = _map_pipeline_to_builder_data(
        {"diagnostics": {}},
        {"waterfall": _WATERFALL, "channels": []},
        {},
        None,
        project_id="test",
    )
    assert data["waterfall"]["labels"] == _WATERFALL["labels"]
    assert data["waterfall"]["values"] == _WATERFALL["values"]


def test_same_budget_is_named_in_words_not_plus_zero():
    """Перекладка долей при той же сумме – «бюджет тот же», не «+0 ₽ (+0%)»."""
    fc = _forecast(
        [
            _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
            _scenario("Перекладка", 12_000.0, 11_500.0, 12_500.0, 5_000_000.0),
        ],
        accepted="Перекладка",
    )
    html = render_forecast_plan(_s({"forecast": fc}))
    assert "бюджет тот же" in html
    assert "+0 ₽" not in html
