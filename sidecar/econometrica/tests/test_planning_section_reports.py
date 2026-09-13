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


def _scenario(name, kpi, lo, hi, spend, roas=1.5, labels=("2026-01", "2026-02", "2026-03"),
              per_channel_money=None):
    return {
        "per_channel_money": dict(per_channel_money or {}),
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

def test_section_title_names_the_screen_step():
    """Владелец 13.09.2026: экранный шаг называется «Планирование», документ –
    «Прогноз на будущий период»; клиент ищет в отчёте то, что видел на экране и
    не находит. Заголовок обязан называть оба имени – в обоих документах."""
    html = render_forecast_plan(_s({"forecast": FC_TWO}))
    assert "Планирование" in html
    assert "Планирование: прогноз на будущий период" in html


def test_width_disclaimer_names_the_accepted_plan():
    """Аудит s46 (противоречие оговорок, 13.09.2026): экран (insights-rules.js
    P4) судил базовый план, документ – принятый; на одних данных советы
    выходили взаимоисключающими. Документ уже судил принятый, но не называл
    его в самой фразе про ширину – её можно было прочитать про любой план.
    Имя внутри фразы делает её самодостаточной (правило владельца)."""
    html = render_forecast_plan(_s({"forecast": FC_TWO}))
    assert "У принятого плана «Плюс 20%» ширина диапазона" in html


def test_html_section_carries_planning_answers():
    """В разделе есть срок, принятый план, диапазон, отличие и вердикт."""
    html = render_forecast_plan(_s({"forecast": FC_TWO}))
    assert "Срок плана" in html and "3 периода" in html
    assert "2026-01" in html and "2026-03" in html
    assert "Принятый план" in html
    assert "Правдоподобный диапазон 90&#160;%" in html
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
        per_channel = {"ТВ": spend * 0.6, "Диджитал": spend * 0.4}
        (sc_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "scenario_name": name,
                    "predictions": [kpi / 3.0] * 3,
                    "future_dates": ["2026-01", "2026-02", "2026-03"],
                    "per_channel_spend": {"native": per_channel, "money": per_channel},
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

    # Разбивка по каналам доезжает тем же путём и складывается в бюджет плана.
    chs = s["accepted"]["channels"]
    assert [c["name"] for c in chs] == ["ТВ", "Диджитал"]
    assert sum(c["spend_money"] for c in chs) == 6_000_000.0

    html = render_forecast_plan(_s({"forecast": loaded}))
    assert "12 000" in html
    assert "6 000 000" in html
    assert "3 600 000" in html  # ТВ за весь срок плана


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
    assert "правдоподобный диапазон 90 % 11 500 – 12 500" in text
    assert "Против «Базовый план»" in text
    assert "+1 000 000 ₽" in text
    assert "не доказано" in text


def test_deck_section_title_names_the_screen_step(base_payload, tmp_path):
    """Владелец 13.09.2026: заголовок слайда и строка оглавления обязаны
    называть экранный шаг «Планирование», не только «Прогноз на будущий
    период» – иначе клиент не находит в колоде то, что видел на экране.

    Проверяет заголовок САМОГО слайда отдельным признаком (не подстрокой всей
    колоды) – первая редакция сторожа находила текст только в строке
    оглавления и не падала, если сам заголовок слайда откатили назад.
    """
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_TWO
    prs, text = _deck_text(payload, str(tmp_path / "deck_title.pptx"))

    plan_slide_texts = None
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if "ВАРИАНТЫ БЮДЖЕТНОГО ПЛАНА" in texts:
            plan_slide_texts = texts
            break
    assert plan_slide_texts is not None, "Слайд плана в колоде не найден"
    assert any("Планирование: прогноз на будущий период" in t for t in plan_slide_texts), (
        "Заголовок именно слайда плана не связывает имена"
    )
    assert "в том числе «Планирование: прогноз на будущий период»" in text


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


# ─── (h) куда идёт бюджет: разбивка принятого плана по каналам ────────────────

FC_CHANNELS = _forecast(
    [
        _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 13_000.0, 5_000_000.0),
        _scenario(
            "Плюс 20%", 12_000.0, 11_500.0, 12_500.0, 6_000_000.0,
            per_channel_money={"Диджитал": 1_800_000.0, "ТВ": 3_600_000.0, "Радио": 600_000.0},
        ),
    ],
    accepted="Плюс 20%",
)


def test_summary_channel_split_sorted_and_shares_sum_to_hundred():
    """Каналы – по убыванию бюджета, доли складываются в 100% (та же сумма,
    что «Бюджет плана»: движок кладёт в per_channel_spend.money только когда
    перевёл в рубли все каналы, и тогда их сумма равна total_spend_money)."""
    s = summarize_forecast(FC_CHANNELS)
    chs = s["accepted"]["channels"]
    assert [c["name"] for c in chs] == ["ТВ", "Диджитал", "Радио"]
    assert chs[0]["spend_money"] == 3_600_000.0
    assert chs[0]["share_pct"] == pytest.approx(60.0)
    assert sum(c["share_pct"] for c in chs) == pytest.approx(100.0)
    assert sum(c["spend_money"] for c in chs) == s["accepted"]["total_spend_money"]


def test_summary_no_channel_split_without_money():
    """Движок не перевёл каналы в рубли – разбивки нет вовсе, доли не считаем
    из натуральных единиц (TRP и показы в рубли не складываются)."""
    s = summarize_forecast(FC_TWO)
    assert s["accepted"]["channels"] is None


def test_html_channel_split_shown(tmp_path):
    """Веб-отчёт: таблица «Куда идёт бюджет» с суммой и долей по каналу."""
    html = render_forecast_plan(_s({"forecast": FC_CHANNELS}))
    assert "Куда идёт бюджет" in html
    assert "Бюджет за срок плана, ₽" in html
    assert "3 600 000" in html and "60%" in html
    assert "Радио" in html


def test_html_no_channel_split_without_money():
    """Нет денег по каналам – блока «Куда идёт бюджет» нет."""
    html = render_forecast_plan(_s({"forecast": FC_TWO}))
    assert "Куда идёт бюджет" not in html


def test_deck_channel_split_one_line(base_payload, tmp_path):
    """Колода: строка «Куда идёт бюджет» с крупнейшими каналами."""
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_CHANNELS
    _, text = _deck_text(payload, str(tmp_path / "deck_channels.pptx"))
    assert "Куда идёт бюджет: ТВ 3 600 000 ₽ (60%)" in text
    assert "Диджитал 1 800 000 ₽ (30%)" in text


def test_deck_channel_split_collapses_tail(base_payload, tmp_path):
    """Каналов больше шести – хвост свёрнут в «прочие», сумма не теряется."""
    many = {f"Канал {i}": float(1_000_000 - i * 10_000) for i in range(9)}
    fc = _forecast(
        [
            _scenario(BASELINE_VARIANT_NAME, 11_000.0, 10_000.0, 13_000.0, sum(many.values())),
            _scenario("Много каналов", 12_000.0, 11_500.0, 12_500.0, sum(many.values()),
                      per_channel_money=many),
        ],
        accepted="Много каналов",
    )
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = fc
    _, text = _deck_text(payload, str(tmp_path / "deck_many.pptx"))
    assert "прочие 3 канала" in text


def test_deck_channel_split_no_overflow(base_payload, tmp_path):
    """Слайд плана с разбивкой по каналам не наезжает сам на себя."""
    from aurora_pptx.check_overflow import check

    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_CHANNELS
    payload["waterfall"] = _WATERFALL
    out = str(tmp_path / "deck_channels_overflow.pptx")
    _deck_text(payload, out)
    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"Слайд плана с каналами получил наезд:\n{detail}"


def _plan_slide_text(prs):
    """Текст ИМЕННО слайда плана, не всей колоды.

    Первая редакция этого сторожа искала термин по всей колоде – и прошла на
    мутации, потому что «Правдоподобный диапазон» стоит и на другом слайде
    (витрина проверки на истории). Сторож, который не может упасть, хуже
    отсутствия сторожа: он создаёт видимость проверки. Слайд плана опознаём по
    двум независимым признакам-ячейкам, как это уже делает test_forecast_report.
    """
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if "Планирование: прогноз на будущий период" in texts and "ВАРИАНТЫ БЮДЖЕТНОГО ПЛАНА" in texts:
            return "\n".join(texts)
    return None


def test_both_documents_call_the_range_the_same(base_payload, tmp_path):
    """Одна величина – одно имя в обоих документах: «правдоподобный диапазон».
    Слова «доверительный интервал» и «CI» в разделе плана запрещены (INV-50)."""
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_CHANNELS
    prs, _ = _deck_text(payload, str(tmp_path / "deck_term.pptx"))
    slide_text = _plan_slide_text(prs)
    assert slide_text is not None, "Слайд плана в колоде не найден"
    html_section = render_forecast_plan(_s({"forecast": FC_CHANNELS}))

    assert "Правдоподобный диапазон" in slide_text
    assert "Правдоподобный диапазон" in html_section
    for banned in ("доверительный интервал", "Доверительный интервал",
                   "доверительный", "Доверительный", "90%-интервал", " CI ", "CI 90"):
        assert banned not in slide_text, f"На слайде плана запрещённое слово: {banned}"
        assert banned not in html_section, f"В разделе веб-отчёта запрещённое слово: {banned}"


# ─── (i) аудит s46, находка 5: колода не округляет процент до лживых «+0%» ────

FC_SMALL_PCT = _forecast(
    [
        _scenario(BASELINE_VARIANT_NAME, 1_000_000.0, 900_000.0, 1_100_000.0, 100_000_000.0),
        _scenario("Чуть больше", 1_000_400.0, 900_400.0, 1_100_400.0, 100_400_000.0),
    ],
    accepted="Чуть больше",
)


def test_deck_pct_precision_matches_html_not_rounded_to_zero(base_payload, tmp_path):
    """Аудит s46 (находка 5): было `{:.0f}%` в builder.py – 0.4% бюджета печаталось
    как «+0%», хотя веб-отчёт на тех же числах писал «+0.4%» (два уносимых
    документа по одному расчёту с разными процентами читаются как сбой счёта).
    Общий `fmt_pct` из utils/kpi_display – оба документа обязаны совпасть."""
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_SMALL_PCT
    prs, _ = _deck_text(payload, str(tmp_path / "deck_pct.pptx"))
    slide_text = _plan_slide_text(prs)
    assert slide_text is not None, "Слайд плана в колоде не найден"
    html = render_forecast_plan(_s({"forecast": FC_SMALL_PCT}))

    assert "+0.4%" in slide_text, slide_text
    assert "+0.4%" in html, html
    assert "(+0%)" not in slide_text, "Колода снова округлила реальную разницу до лживых +0%"


# ─── (j) аудит s46, находка 6: принятый план и участники вердикта — в таблице ──

FC_FIVE = _forecast(
    [
        _scenario(BASELINE_VARIANT_NAME, 10_000.0, 9_500.0, 10_500.0, 5_000_000.0),
        _scenario("Вариант А", 10_200.0, 9_700.0, 10_700.0, 5_100_000.0),
        _scenario("Вариант Б", 10_400.0, 9_900.0, 10_900.0, 5_200_000.0),
        _scenario("Вариант В", 10_600.0, 10_100.0, 11_100.0, 5_300_000.0),
        _scenario("Вариант Д", 13_000.0, 12_500.0, 13_500.0, 6_000_000.0),
    ],
    accepted="Вариант Д",
)


def test_html_table_shows_accepted_variant_beyond_first_four():
    """Аудит s46 (находка 6): таблица резалась `[:4]` – при пяти вариантах, где
    принят пятый («Вариант Д»), в таблице стояли только Базовый план/А/Б/В, а
    текст раздела крупно называл «Вариант Д» принятым и сравнивал его с «Вариант
    В» в вердикте. ★ пропадал из таблицы, названный вариант в ней не находился."""
    html = render_forecast_plan(_s({"forecast": FC_FIVE}))
    summary = summarize_forecast(FC_FIVE)
    assert summary["verdict"]["kind"] == "distinct"
    assert summary["verdict"]["leader"] == "Вариант Д"
    assert summary["verdict"]["runner_up"] == "Вариант В"
    assert "★ Вариант Д" in html, "Принятый план должен появиться в таблице со звёздочкой"


def test_deck_table_shows_accepted_variant_beyond_first_four(base_payload, tmp_path):
    """То же самое, что выше, но для колоды: `builder.py` резал ту же таблицу
    `[:4]` независимо от `sections.py`."""
    payload = copy.deepcopy(base_payload)
    payload["forecast"] = FC_FIVE
    prs, text = _deck_text(payload, str(tmp_path / "deck_five.pptx"))
    assert "★ Вариант Д" in text, "Принятый план должен появиться в таблице колоды со звёздочкой"


# ─── (k) аудит s46, находка 7: подпись слайда декомпозиции не врёт о форме ─────

def test_deck_decomposition_caption_does_not_claim_columns(base_payload, tmp_path):
    """Аудит s46 (находка 7): диаграмма декомпозиции – BAR_STACKED (PowerPoint
    Bar = горизонтальные полосы, ряд один), а старая подпись обещала «столбцы
    складываются в итог» – буквально неверно (складывать нечего, стека нет)."""
    payload = copy.deepcopy(base_payload)
    payload["waterfall"] = _WATERFALL
    _, text = _deck_text(payload, str(tmp_path / "deck_decomp_caption.pptx"))
    assert "Столбцы складываются в итог" not in text
    assert "самостоятельное значение" in text
    assert "полос" in text
