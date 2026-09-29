"""Клиентский текст отчётов HTML/PPTX – правки выпуска 2.5.9 (s58, поток Б).

N18 – доля канала в «ЗАТРУДНЕНИИ» подписана «медиа-вклада», как везде, а не «эффекта».
N19 – вторая часть «ЗАТРУДНЕНИЯ» в презентации с заглавной («. По mROAS», не «. по mROAS»).
N20 – «тянет/тянут» по числу отстающих; HTML печатает «опережает» и «тянут» по тем же
      условиям, что презентация (раньше – всегда, даже без отстающих).
N21 – подсказка времени в подвале HTML по-русски, без ISO («2026-09-29T04:24:26»).
N22 и L-2 – mROAS и ROI в прозе двумя цифрами, как в таблицах («27.03×», «0.80×»).

Тесты поведенческие: строят отчёт штатным кодом из фикстуры-образца и смотрят на
видимый текст. Каждый проверен мутацией «вернуть старое – тест краснеет»
(Projects/_s58/FIXB_259.md).
"""
from __future__ import annotations

import copy
import html as _html
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# В фикстуре: лидер Performance, герой Social (mROAS 27.0337), бюджет забирает
# «TRPs бренд (W 25-54)» (88.9% бюджета, 15.3% медиа-вклада) – он же источник
# сокращения; средневзвешенный ROI 0.8016.
_DOMINATOR = "TRPs бренд (W 25-54)"


def _payload(underperf: tuple[str, ...] = (), hero_is_leader: bool = False) -> dict:
    """Фикстура с управляемым числом отстающих (кроме источника сокращения).

    Отстающие заданы согласованно для обоих строителей: вердикт канала (его читает
    презентация) и `underperformer_names` фактов (его читает HTML).
    """
    with open(_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    data = copy.deepcopy(data)
    for c in data["channels"]:
        if c["name"] in underperf:
            c["verdict"] = "Reduce"
    facts = data["narrative_facts"]
    facts["underperformer_names"] = list(underperf)
    if hero_is_leader:
        facts["hero_channel"] = facts["leader_channel"]
    return data


def _html_text(page: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = _html.unescape(re.sub(r"<[^>]+>", "\n", body))
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def _pptx_text(prs) -> str:
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


def _html_page(data: dict) -> str:
    from aurora_html import build_html
    return build_html(data)


def _pptx(data: dict) -> str:
    from aurora_pptx.builder import AuroraPPTXBuilder
    return _pptx_text(AuroraPPTXBuilder(data).build())


def _complication(text: str) -> str:
    """Абзац «ЗАТРУДНЕНИЕ/ПРОБЛЕМА»: строка, начинающаяся с канала, забирающего бюджет."""
    lines = [l for l in text.splitlines() if l.startswith(f"{_DOMINATOR} занимает")]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.fixture(scope="module")
def html_one() -> str:
    return _html_text(_html_page(_payload(("Banners",))))


@pytest.fixture(scope="module")
def pptx_one() -> str:
    return _pptx(_payload(("Banners",)))


# ─── N18: «медиа-вклада», не «эффекта» ─────────────────────────────────────

def test_complication_share_is_media_contribution(html_one, pptx_one):
    for text in (html_one, pptx_one):
        c = _complication(text)
        assert "но даёт 15.3% медиа-вклада" in c, c
        assert "эффекта" not in c, c


# ─── N19: заглавная у второй части в презентации ───────────────────────────

def test_pptx_second_part_capitalized(pptx_one):
    c = _complication(pptx_one)
    assert ". По mROAS Social опережает" in c, c
    assert not re.search(r"\.\s+[а-яё]", c), c


# ─── N20: число глагола и условия HTML = условия презентации ───────────────

@pytest.mark.parametrize("underperf, phrase", [
    (("Banners",), "Banners тянет портфель вниз."),
    (("Banners", "OLV"), "Banners, OLV тянут портфель вниз."),
], ids=["one", "two"])
def test_pull_verb_agrees_with_number(underperf, phrase):
    data = _payload(underperf)
    for text in (_html_text(_html_page(data)), _pptx(data)):
        c = _complication(text)
        assert phrase in c, c


def test_no_underperformers_no_pull_phrase_in_both():
    """Отстающих нет – ни «Слабые каналы тянут», ни «тянет» (раньше HTML печатал всегда)."""
    data = _payload(())
    for text in (_html_text(_html_page(data)), _pptx(data)):
        c = _complication(text)
        assert "тян" not in c, c


def test_hero_is_leader_no_outperform_phrase_in_both():
    """Герой = лидер – «опережает» не печатается ни в HTML, ни в презентации."""
    data = _payload(("Banners",), hero_is_leader=True)
    for text in (_html_text(_html_page(data)), _pptx(data)):
        c = _complication(text)
        assert "опережает" not in c, c


def test_html_complication_kpi_aware_not_mroas_for_count():
    """Штучный KPI: «По CPU …», как в презентации, а не «По mROAS … ×».

    HTML – на уровне раздела, как в tools/test_aurora_html_kpi_aware.py; целая
    сборка со штучным KPI – test_built_html_sections_follow_kpi_like_pptx ниже.
    """
    from aurora_html.sections import render_executive_summary
    data = _payload(("Banners",))
    data["kpi"] = dict(data["kpi"], kpi_kind="count", value_per_count_unit=None,
                       labels=dict(data["kpi"]["labels"], metric_short_label="CPU"))
    with open(os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json"),
              encoding="utf-8") as f:
        strings = json.load(f)
    ctx = {"meta": {"client": "Kagocel"}, "facts": data["narrative_facts"],
           "channels": data["channels"], "diagnostics": {"mqs_score": 70},
           "strings": strings, "report_id": "T", "model_version": "1.0",
           "period_unit": "неделям", "kpi": data["kpi"]}
    html_text = _html_text(render_executive_summary(ctx))
    for text in (html_text, _pptx(data)):
        c = _complication(text)
        assert "mROAS" not in c and "×" not in c, c
        assert "По CPU Social опережает" in c, c


# ─── N22 / L-2: mROAS и ROI в прозе – две цифры, как в таблицах ────────────

def _one_decimal_multipliers(text: str) -> list[str]:
    """Множители с одной цифрой после точки («4.2×»), кроме постоянных пояснений
    вида «1.0× = безубыточность», «ROI 1.5× = 1.5 рубля…» (не числа модели)."""
    return [text[max(0, m.start() - 30):m.end() + 20]
            for m in re.finditer(r"\b\d+\.\d×", text)
            if not text.startswith(" = ", m.end())]


def test_prose_multipliers_two_decimals_html(html_one):
    assert "По mROAS Social опережает (27.03×)." in html_one
    assert "Social – самый эффективный канал с mROAS 27.03×" in html_one
    assert "Средневзвешенный ROI 0.80×" in html_one
    assert "ROI 0.80× средневзвешенный по каналам" in html_one
    assert _one_decimal_multipliers(html_one) == []


def test_prose_multipliers_two_decimals_pptx(pptx_one):
    assert "По mROAS Social опережает (27.03×)." in pptx_one
    assert "Средневзвешенный ROI 0.80×" in pptx_one
    assert "ROI 0.80× средневзвешенный по каналам" in pptx_one
    assert _one_decimal_multipliers(pptx_one) == []


def test_html_hero_under_breakeven_two_decimals():
    """Находка 2 HTML, ветка «герой под безубыточностью» (sections.py `hero_m_fmt`):
    0.85, а не «0.8×»/«0.9×». Обычная ветка «самый эффективный» идёт через
    шаблон strings_ru.json и этой строки не касается."""
    data = _payload(("Banners",))
    for c in data["channels"]:
        c["mroas"] = min(float(c.get("mroas") or 0), 0.5)
    next(c for c in data["channels"] if c["name"] == "Social")["mroas"] = 0.85
    text = _html_text(_html_page(data))
    assert "Social – лучший среди медиа, но всё ещё под breakeven (ROI 0.85×)" in text, \
        [l for l in text.splitlines() if "breakeven" in l]


def test_decomposer_insight_roi_two_decimals():
    from engines.decomposer import _build_channel_insight
    ins = _build_channel_insight([
        {"name": "TV", "roi": 1.55, "efficiency_gap": 12, "unit_smell": False},
        {"name": "OOH", "roi": 0.6, "efficiency_gap": -8, "unit_smell": False},
    ])
    assert "1.55×" in ins, ins


def test_scenario_compare_insight_roas_two_decimals(tmp_path: Path):
    from engines.scenario import compare_scenarios
    d = tmp_path / "results" / "scenarios"
    d.mkdir(parents=True)
    for name, roas in (("Базовый", 1.55), ("Смелый", 1.25)):
        (d / f"{name}.json").write_text(json.dumps({
            "status": "ok", "scenario_name": name, "media_plan": {},
            "totals": {"predicted_kpi": 12000, "baseline_kpi": 10000, "incremental_kpi": 2000,
                       "lift_pct": 20.0, "total_spend": 500.0, "total_spend_money": 500_000.0,
                       "roas": roas, "roas_money": roas, "roas_total": roas,
                       "units_fully_covered": True, "roas_method": "incremental"},
        }, ensure_ascii=False), encoding="utf-8")
    res = compare_scenarios(str(tmp_path))
    assert "(ROAS 1.55×," in res["insight"], res["insight"]


# ─── N21: подвал HTML без ISO-времени в подсказке ──────────────────────────

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:T|\b)")


def test_footer_title_is_russian_time_not_iso():
    page = _html_page(_payload(("Banners",)))
    m = re.search(r'<span class="footer-value" title="([^"]*)">', page)
    assert m, "в подвале нет времени сборки"
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", m.group(1)), m.group(1)
    visible_attrs = re.findall(r'\b(?:title|aria-label|alt|placeholder)="([^"]*)"', page)
    assert [a for a in visible_attrs if _ISO.search(a)] == []


# ─── KPI в разделах готового HTML (находка s58, в 2.5.9) ───────────────────

def _without_glossary(page: str) -> str:
    """Страница без раздела-словаря: словарь статичен и определяет термины
    («Средневзвешенный ROI», «ROI», «mROAS») для любого отчёта."""
    return re.sub(r'<section id="glossary".*?</section>', "", page, flags=re.S)


@pytest.mark.parametrize("kpi_patch", [
    {"kpi_kind": "count", "derived_mode": "roi", "kpi_type": "leads"},
    {"kpi_kind": "monetary", "derived_mode": "effectiveness", "kpi_type": "awareness"},
], ids=["count", "effectiveness"])
def test_built_html_sections_follow_kpi_like_pptx(kpi_patch):
    """Строитель HTML не передавал «kpi» в контекст разделов – готовый отчёт со
    штучным KPI или долей печатал «Средневзвешенный ROI 0.80×», а презентация
    того же прогона – CPU/долю. Проверка на ЦЕЛОЙ сборке (build_html), не разделе."""
    data = _payload(("Banners",))
    data["kpi"] = dict(data["kpi"], **kpi_patch)
    html_text = _html_text(_without_glossary(_html_page(copy.deepcopy(data))))
    pptx_text = _pptx(copy.deepcopy(data))
    assert "Средневзвешенный ROI" not in html_text
    html_sit = [l for l in html_text.splitlines() if " размещает " in l]
    pptx_sit = [l for l in pptx_text.splitlines() if " размещает " in l]
    assert len(html_sit) == 1 and len(pptx_sit) == 1, (html_sit, pptx_sit)
    assert html_sit[0] == pptx_sit[0], (html_sit[0], pptx_sit[0])
