"""«Отстающие» каналы: один список для HTML и PPTX (s59, приоритет 1 владельца, 2.5.10).

До правки презентация брала отстающих по действию Cut/Reduce (без источника сокращения),
HTML – по `facts.underperformer_names` (Cut/Watch, тоже без источника), а без разрыва
«бюджет/вклад» >= 5 пп HTML вообще не печатал частей «опережает» и «тянут». Теперь:

- состав и порядок – ОДНА функция `engines.channel_action.underperformer_names`:
  Cut и Reduce, худший mROAS первым, Watch и Uncertain не входят;
- ЗАТРУДНЕНИЕ (HTML) и ПРОБЛЕМА (PPTX) называют ПОЛНЫЙ список – в нём и источник сокращения
  (раньше худший канал пропадал из «тянет портфель вниз»);
- ОТВЕТ в обоих форматах называет список БЕЗ источника сокращения (он назван рядом – «из X»);
- три части ЗАТРУДНЕНИЯ/ПРОБЛЕМЫ независимы: [разрыв >= 5 пп] [герой опережает] [отстающие тянут];
- у предельного значения героя подпись «mROAS», а не «ROI» (денежный KPI, любой режим кроме доли);
- число героя на слайде 3 – у канала с ИМЕНЕМ героя.

Тесты строят отчёт штатным кодом: факты – через адаптер (`_derive_narrative_facts` поверх
фикстуры, а не ручной подменой), потом `build_html` и `AuroraPPTXBuilder(data).build()`.
Каждому условию соответствует мутация «вернуть старое – тест краснеет» (Projects/_s59/FIX1_2510.md).
"""
from __future__ import annotations

import copy
import html as _html
import json
import os
import re
import sys
from functools import lru_cache
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.channel_action import underperformer_names  # noqa: E402
from engines.narrative_adapter import _derive_narrative_facts, derive_action_headline  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# Фикстура (порядок каналов – по вкладу): Performance (лидер, Scale, mROAS 16.23),
# Social (герой, Scale, 27.03), «TRPs бренд (W 25-54)» (Cut, 0.0853, 88.9% бюджета при 15.3%
# вклада – он же источник сокращения), Banners (Scale, 1.67), OLV (Scale, 1.54).
_TRPS = "TRPs бренд (W 25-54)"
_FALLBACK = "Портфель сбалансирован – резких диспропорций между бюджетом и эффектом не выявлено."
_GAP_HEAD = f"{_TRPS} занимает 89% бюджета, но даёт 15.3% медиа-вклада."
_HERO_PART = "По mROAS Social опережает (27.03×)."


# ─── сборка сценариев ───────────────────────────────────────────────────────

def _scenario_data(spec=None, optimize=None, balanced=False, kpi_patch=None, facts_patch=None) -> dict:
    """Фикстура с управляемыми каналами; факты – штатно через адаптер.

    spec: {имя канала: {поле: значение}}; «action» выставляется вместе с «verdict»
    (у данных адаптера это один ключ). balanced: доля бюджета каждого канала = доле
    вклада (разрыв < 5 пп).
    """
    with open(_FIXTURE, encoding="utf-8") as fh:
        data = copy.deepcopy(json.load(fh))
    for c in data["channels"]:
        for k, v in ((spec or {}).get(c["name"]) or {}).items():
            c[k] = v
            if k == "action":
                c["verdict"] = v
    if balanced:
        for c in data["channels"]:
            c["spend"] = float(c["contribution"]) * 0.5
    derived = _derive_narrative_facts(
        data["channels"], optimize or {"expected_lift_pct": 7.1}, None, None)
    keep = {k: data["narrative_facts"][k] for k in
            ("total_sales", "baseline_pct", "media_contribution_pct", "honest_narrative")}
    data["narrative_facts"] = {**data["narrative_facts"], **derived, **keep, **(facts_patch or {})}
    if kpi_patch:
        patch = dict(kpi_patch)
        labels = {**data["kpi"].get("labels", {}), **patch.pop("labels", {})}
        data["kpi"] = dict(data["kpi"], labels=labels, **patch)
    return data


_SCENARIOS = {
    "no_budget_share": dict(facts_patch={"budget_dominator_spend_pct": None, "leader_share_spend_pct": None,
                                          "budget_dominator_contrib_pct": 40.0}),
    # естественная фикстура: отстающий один – источник сокращения, разрыв 89 против 15.3
    "fixture": dict(),
    "gap_ge5_two_reduce": dict(spec={"Banners": {"action": "Reduce"}, "OLV": {"action": "Reduce"}}),
    "gap_lt5_cut_only": dict(balanced=True),
    "gap_lt5_two_reduce": dict(balanced=True, spec={
        "Banners": {"action": "Reduce"}, "OLV": {"action": "Reduce"}}),
    "gap_lt5_one_reduce": dict(balanced=True, spec={
        _TRPS: {"action": "Hold"}, "Banners": {"action": "Reduce"}}),
    # ни одной части: герой = лидер, разрыва нет, отстающих нет
    "no_parts": dict(balanced=True, spec={
        _TRPS: {"action": "Hold"}, "Performance": {"mroas": 40.0}}),
    "hero_is_leader": dict(balanced=True, spec={"Performance": {"mroas": 40.0}}),
    "watch_mix": dict(balanced=True, spec={
        "Banners": {"action": "Reduce"}, "OLV": {"action": "Watch"},
        "Performance": {"action": "Watch"}}),
    # три Watch и один Cut при слабом герое: раньше Watch считались отстающими и включали
    # заголовки «Сократить неэффективные каналы…» (слайд mROAS) и «Сократить X, Y…» (SCQAR)
    "watch_majority_weak_hero": dict(balanced=True, spec={
        "Social": {"mroas": 1.1}, "Performance": {"action": "Watch", "mroas": 1.0},
        "Banners": {"action": "Watch", "mroas": 1.0}, "OLV": {"action": "Watch", "mroas": 0.9}}),
    "all_cut": dict(balanced=True, spec={
        n: {"action": "Cut"} for n in ("Performance", "Social", "Banners", "OLV")}),
    # переброска незначима (оптимальные траты = текущим, см. _built); отстающий кроме источника – Banners
    "insignificant_realloc": dict(balanced=True, spec={"Banners": {"action": "Reduce"}}),
    "refused": dict(balanced=True, spec={"Banners": {"action": "Reduce"}},
                    optimize={"expected_lift_pct": 7.1,
                              "model_reliability": {"verdict": "unreliable", "refused": True}}),
    # равный mROAS у двух Cut: голова списка обязана совпасть с cut_source
    "tie": dict(balanced=True, spec={
        _TRPS: {"mroas": 0.5}, "Banners": {"action": "Cut", "mroas": 0.5}}),
    # лучший по mROAS канал с unit_smell – не герой; число слайда 3 – от героя
    "unit_smell_hero": dict(spec={"Social": {"mroas": 99.0, "unit_smell": True}}),
    "hero_under_breakeven": dict(spec={"Social": {"mroas": 0.85}, "Performance": {"mroas": 0.5},
                                       "Banners": {"mroas": 0.4}, "OLV": {"mroas": 0.3}}),
    # честный режим (медиа < 10% продаж): находка героя в HTML – ветка «единственный канал близкий к окупаемости»
    "honest": dict(balanced=True, facts_patch={
        "honest_narrative": True, "media_contribution_pct": 5.0, "baseline_pct": 95.0}),
    "kpi_manual": dict(balanced=True, kpi_patch={"derived_mode": "manual"}),
    "kpi_count": dict(
        balanced=True, spec={"Banners": {"action": "Reduce"}},
        kpi_patch={"kpi_kind": "count", "derived_mode": "roi", "kpi_type": "leads"}),
    "kpi_effectiveness": dict(
        balanced=True, spec={"Banners": {"action": "Reduce"}},
        kpi_patch={"kpi_kind": "monetary", "derived_mode": "effectiveness", "kpi_type": "awareness",
                   "labels": {"metric_short_label": "Доля", "metric_label": "Доля эффекта"}}),
}


def _fix_insignificant(data: dict) -> dict:
    """Переброска незначима: оптимальные траты равны текущим (адаптер считает сумму от них)."""
    for c in data["channels"]:
        c["optimal_spend"] = c["current_spend"]
    return data


def _html_blocks(page: str) -> dict:
    out = {}
    for label, body in re.findall(
            r'<div class="scqar-label">(.*?)</div><div class="scqar-body">(.*?)</div>', page, flags=re.S):
        out[_html.unescape(label)] = _html.unescape(re.sub(r"<[^>]+>", "", body)).strip()
    return out


def _flat(page: str) -> str:
    """Видимый текст страницы HTML одной строкой (без скриптов, стилей и тегов)."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", body)))


def _pptx_texts(prs) -> list[list[str]]:
    return [[sh.text_frame.text for sh in s.shapes if sh.has_text_frame] for s in prs.slides]


def _pptx_blocks(prs) -> tuple[dict, str]:
    """Блоки слайда SCQAR (по метке, тело – шейп сразу за меткой) и его заголовок."""
    for texts in _pptx_texts(prs):
        stripped = [t.strip() for t in texts]
        if "ПРОБЛЕМА" in stripped and "ОТВЕТ" in stripped:
            blocks = {}
            for label in ("СИТУАЦИЯ", "ПРОБЛЕМА", "ВОПРОС", "ОТВЕТ"):
                i = stripped.index(label)
                blocks[label] = texts[i + 1]
            return blocks, "\n".join(texts)
    raise AssertionError("слайд SCQAR не найден")


def _all_text(prs) -> str:
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


@lru_cache(maxsize=None)
def _built(name: str) -> SimpleNamespace:
    from aurora_html import build_html
    from aurora_pptx.builder import AuroraPPTXBuilder
    kw = copy.deepcopy(_SCENARIOS[name])
    data = _scenario_data(**kw)
    if name == "insignificant_realloc":
        # оптимальные траты равны текущим -> адаптер даёт сумму 0; факты пересчитываем штатно
        data = _fix_insignificant(data)
        derived = _derive_narrative_facts(data["channels"], {"expected_lift_pct": 7.1}, None, None)
        data["narrative_facts"] = {**data["narrative_facts"], **derived}
    html_page = build_html(copy.deepcopy(data))
    prs = AuroraPPTXBuilder(copy.deepcopy(data)).build()
    pptx_blocks, scqar_slide = _pptx_blocks(prs)
    return SimpleNamespace(
        data=data, facts=data["narrative_facts"], channels=data["channels"],
        html=_html_blocks(html_page), html_page=html_page,
        pptx=pptx_blocks, scqar_slide=scqar_slide, pptx_all=_all_text(prs))


_PULL = re.compile(r"(?:^|\.\s)([^.]+?) (тянет|тянут) портфель вниз\.")
_STOP = re.compile(r"[Сс]ократить или остановить ([^.;]+?)\.")


def _pull(text: str):
    m = _PULL.search(text)
    return ([n.strip() for n in m.group(1).split(", ")], m.group(2)) if m else ([], None)


def _stop(text: str):
    m = _STOP.search(text)
    return [n.strip() for n in m.group(1).split(", ")] if m else []


# ─── функция: состав, порядок, защита ───────────────────────────────────────

def test_function_composition_and_order():
    ch = [
        {"name": "A", "action": "Scale", "mroas": 3.0},
        {"name": "B", "action": "Reduce", "mroas": 1.2},
        {"name": "C", "action": "Watch", "mroas": 0.9},
        {"name": "D", "action": "Cut", "mroas": 0.3},
        {"name": "E", "action": "Uncertain", "mroas": 0.1},
        {"name": "F", "action": "Hold", "mroas": 1.0},
        {"name": "G", "action": "Cut", "mroas": 0.7},
    ]
    assert underperformer_names(ch) == ["D", "G", "B"]  # Cut и Reduce, худший mROAS первым
    assert underperformer_names(ch, exclude="D") == ["G", "B"]
    assert underperformer_names(ch, exclude="нет такого") == ["D", "G", "B"]
    assert underperformer_names([]) == [] and underperformer_names(None) == []


def test_function_ties_keep_input_order_and_bad_mroas_is_zero():
    ch = [
        {"name": "Б", "action": "Cut", "mroas": 0.5},
        {"name": "А", "action": "Cut", "mroas": 0.5},      # равный mROAS: порядок входа, не имени
        {"name": "Н", "action": "Cut", "mroas": float("nan")},
        {"name": "Т", "action": "Reduce", "mroas": "не число"},
        {"name": "П", "action": "Reduce", "mroas": None},
        {"name": "Х", "action": "Cut", "mroas": -0.2},
    ]
    # NaN, строка и None -> 0.0 (порядок входа среди них), отрицательный – худший
    assert underperformer_names(ch) == ["Х", "Н", "Т", "П", "Б", "А"]


def test_function_reads_verdict_when_no_action():
    ch = [{"name": "A", "verdict": "Cut", "mroas": 0.1}, {"name": "B", "verdict": "Watch", "mroas": 0.1},
          {"name": "", "action": "Cut", "mroas": 0.0}, {"action": "Cut", "mroas": 0.0}]
    assert underperformer_names(ch) == ["A"]


# ─── адаптер: два списка, голова = источник сокращения ──────────────────────

@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_adapter_lists_come_from_one_function(name):
    b = _built(name)
    all_names = b.facts["underperformer_names_all"]
    assert all_names == underperformer_names(b.channels)
    cut_source = b.facts["cut_source_channel"]
    assert b.facts["underperformer_names"] == [n for n in all_names if n != cut_source]
    if all_names:
        # голова полного списка = источник сокращения при ЛЮБОМ порядке и равных mROAS
        assert all_names[0] == cut_source, (all_names, cut_source)
    else:
        assert cut_source is None


def test_tie_head_of_list_is_cut_source_and_named_once_in_answer():
    b = _built("tie")
    assert b.facts["underperformer_names_all"][:2] == [_TRPS, "Banners"]  # порядок входа, не имени
    assert b.facts["cut_source_channel"] == _TRPS
    for answer in (b.html["ОТВЕТ"], b.pptx["ОТВЕТ"]):
        assert answer.count(_TRPS) == 1, answer
        assert _stop(answer) == ["Banners"], answer


# ─── Watch не называется нигде ──────────────────────────────────────────────

def test_watch_channels_are_never_named_as_underperformers():
    b = _built("watch_mix")
    assert b.facts["underperformer_names_all"] == [_TRPS, "Banners"]
    for where, text in (("HTML ЗАТРУДНЕНИЕ", b.html["ЗАТРУДНЕНИЕ"]), ("HTML ОТВЕТ", b.html["ОТВЕТ"]),
                        ("PPTX ПРОБЛЕМА", b.pptx["ПРОБЛЕМА"]), ("PPTX ОТВЕТ", b.pptx["ОТВЕТ"])):
        for watch in ("OLV", "Performance"):
            assert watch not in text, (where, watch, text)
    for hint in ("mroas", "scqar"):
        h = derive_action_headline(b.channels, b.facts, hint) or ""
        assert "OLV" not in h, (hint, h)


def test_watch_majority_does_not_trigger_risk_headlines():
    """Заголовки слайдов mROAS и SCQAR читают тот же список: три Watch и один Cut – не «все
    отстающие» (раньше были) – заголовки идут по обычным веткам, Watch в них не назван."""
    b = _built("watch_majority_weak_hero")
    assert b.facts["underperformer_names_all"] == [_TRPS]
    mroas_h = derive_action_headline(b.channels, b.facts, "mroas")
    scqar_h = derive_action_headline(b.channels, b.facts, "scqar")
    assert mroas_h == "Сбалансировать портфель по mROAS – один канал не доминирует", mroas_h
    assert scqar_h.startswith("Перераспределить "), scqar_h
    assert "Сократить неэффективные каналы" not in b.pptx_all
    for watch in ("Performance", "Banners", "OLV"):
        assert watch not in scqar_h
    assert b.html["ОТВЕТ"].count("сократить или остановить") == 0


def test_scqar_headline_names_two_worst_channels_not_watch():
    """Заголовок слайда SCQAR при «все отстающие»: два худших по mROAS (Cut/Reduce), не Watch.
    Пять каналов, все Cut: источник – худший, следом – второй по mROAS. Было (s60): «… и сфокусировать
    бюджет на Social». Стало (s63, страж): Social сам Cut (герой срезан оптимизатором) – фокусироваться
    на нём заголовок не зовёт: «… – явного канала для роста нет»."""
    b = _built("all_cut")
    expected = f"Сократить {_TRPS}, OLV – явного канала для роста нет"
    assert derive_action_headline(b.channels, b.facts, "scqar") == expected
    assert expected in b.scqar_slide, b.scqar_slide


# ─── равенство HTML = PPTX: имена и порядок ─────────────────────────────────

_WITH_UNDERPERF = ["fixture", "gap_ge5_two_reduce", "gap_lt5_cut_only", "gap_lt5_two_reduce",
                   "gap_lt5_one_reduce", "hero_is_leader", "all_cut", "insignificant_realloc",
                   "refused", "tie", "kpi_manual", "kpi_count", "kpi_effectiveness"]


@pytest.mark.parametrize("name", _WITH_UNDERPERF)
def test_problem_names_equal_in_html_and_pptx_and_ordered_by_mroas(name):
    b = _built(name)
    html_names, html_verb = _pull(b.html["ЗАТРУДНЕНИЕ"])
    pptx_names, pptx_verb = _pull(b.pptx["ПРОБЛЕМА"])
    # s59 (P3 2510, H4): герой, названный «опережает», в «тянут» не входит (в факте адаптера
    # он остаётся: [all_cut] – Social, mROAS 27.03, действие Cut). Остальные параметры
    # героя в списке не содержат – ожидание для них прежнее.
    hero = b.facts["hero_channel"]
    hero_m = float(next(c["mroas"] for c in b.channels if c["name"] == hero))
    hero_named = hero != b.facts["leader_channel"] and hero_m >= 1.0
    expected = [n for n in b.facts["underperformer_names_all"] if not (hero_named and n == hero)]
    assert html_names == pptx_names == expected, (html_names, pptx_names)
    assert html_names, name
    mroas = {c["name"]: float(c["mroas"]) for c in b.channels}
    assert [mroas[n] for n in html_names] == sorted(mroas[n] for n in html_names)  # худший первым
    assert html_verb == pptx_verb == ("тянет" if len(html_names) == 1 else "тянут")


def test_answer_names_equal_in_html_and_pptx_without_cut_source():
    b = _built("gap_lt5_two_reduce")
    # источник – TRPs (худший), из списка отстающих в ОТВЕТЕ вычтен; порядок по mROAS: OLV 1.54, Banners 1.67
    assert _stop(b.html["ОТВЕТ"]) == _stop(b.pptx["ОТВЕТ"]) == ["OLV", "Banners"]
    assert _stop(b.html["ОТВЕТ"]) == b.facts["underperformer_names"]
    for answer in (b.html["ОТВЕТ"], b.pptx["ОТВЕТ"]):
        assert answer.count(_TRPS) == 1, answer          # источник назван ровно один раз («из …»)
        assert f"из {_TRPS}" in answer, answer
        assert "сократить или остановить OLV, Banners." in answer and "; остановить" not in answer, answer


def test_full_problem_list_includes_cut_source_while_answer_excludes_it():
    """Худший канал, он же источник сокращения, раньше пропадал из «тянет портфель вниз»."""
    b = _built("gap_lt5_cut_only")
    for text in (b.html["ЗАТРУДНЕНИЕ"], b.pptx["ПРОБЛЕМА"]):
        assert _pull(text)[0] == [_TRPS], text
    for answer in (b.html["ОТВЕТ"], b.pptx["ОТВЕТ"]):
        assert answer.count(_TRPS) == 1, answer
        assert "остановить" not in answer, answer          # списка без источника нет


# ─── три независимые части: разрыв < 5 пп, >= 5 пп, ни одной ────────────────

def test_parts_independent_of_gap_in_both_formats():
    """Разрыв бюджет/вклад < 5 пп: герой и отстающие названы и в HTML, и в PPTX
    (раньше HTML давал запасную фразу «Портфель сбалансирован…» без них)."""
    b = _built("gap_lt5_cut_only")
    expected = f"{_HERO_PART} {_TRPS} тянет портфель вниз."
    assert b.html["ЗАТРУДНЕНИЕ"] == expected, b.html["ЗАТРУДНЕНИЕ"]
    assert b.pptx["ПРОБЛЕМА"].startswith(expected + " "), b.pptx["ПРОБЛЕМА"]
    assert "занимает" not in b.html["ЗАТРУДНЕНИЕ"] and "занимает" not in b.pptx["ПРОБЛЕМА"]
    assert "сбалансирован" not in b.html["ЗАТРУДНЕНИЕ"]


def test_gap_part_comes_first_when_gap_at_least_5pp():
    b = _built("fixture")
    expected = f"{_GAP_HEAD} {_HERO_PART} {_TRPS} тянет портфель вниз."
    assert b.html["ЗАТРУДНЕНИЕ"] == expected, b.html["ЗАТРУДНЕНИЕ"]
    assert b.pptx["ПРОБЛЕМА"].startswith(expected + " "), b.pptx["ПРОБЛЕМА"]


def test_hero_is_leader_only_underperformers_remain():
    b = _built("hero_is_leader")
    expected = f"{_TRPS} тянет портфель вниз."
    assert b.html["ЗАТРУДНЕНИЕ"] == expected, b.html["ЗАТРУДНЕНИЕ"]
    assert b.pptx["ПРОБЛЕМА"].startswith(expected + " "), b.pptx["ПРОБЛЕМА"]
    for text in (b.html["ЗАТРУДНЕНИЕ"], b.pptx["ПРОБЛЕМА"]):
        assert "опережает" not in text, text


def test_no_parts_html_fallback_and_pptx_tail():
    """Ни одной части: HTML – запасная фраза, PPTX – хвост-вывод. Расхождение сохранено
    намеренно (вопрос владельцу, L3 в FIX1_2510.md)."""
    b = _built("no_parts")
    assert b.facts["underperformer_names_all"] == []
    assert b.html["ЗАТРУДНЕНИЕ"] == _FALLBACK
    body = b.pptx["ПРОБЛЕМА"]
    assert body.startswith(("Портфель требует перебалансировки.", "Однако ")), body
    for text in (b.html["ЗАТРУДНЕНИЕ"], body):
        assert "тян" not in text and "опережает" not in text, text


# ─── ОТВЕТ PPTX: «сократить или остановить», заглавная в начале ─────────────

def test_pptx_answer_says_reduce_or_stop_like_html():
    b = _built("gap_lt5_two_reduce")
    assert "сократить или остановить OLV, Banners" in b.pptx["ОТВЕТ"], b.pptx["ОТВЕТ"]
    assert "; остановить" not in b.pptx["ОТВЕТ"]


def test_pptx_answer_capitalized_when_stop_clause_is_first():
    """Переброска незначима: ОТВЕТ – одно предложение, его первая часть – с заглавной.

    s63 пакет (п.1, Д1): было «Сократить или остановить Banners.» – источник сокращения TRPs (Cut) из
    списка ОТВЕТА вычитался всегда, а частью «из … в …» при незначимой переброске не назывался, и канал,
    который таблица велит остановить, в ОТВЕТЕ пропадал. Стало: заголовок «Крупной переброски нет, но …
    – слабый канал», ОТВЕТ называет все слабые каналы и что делать. Заглавная у придаточного «Сократить
    или остановить …» в начале ОТВЕТА – в test_slide_coherence_s63 (сценарий «Риск» без переброски)."""
    b = _built("insignificant_realloc")
    assert b.facts["reallocation_mln"] == 0
    assert b.pptx["ОТВЕТ"] == (
        f"Сохранить аллокацию без переброски; сократить или остановить {_TRPS}, Banners после проверки вклада."
    ), b.pptx["ОТВЕТ"]


def test_model_refused_known_divergence_is_recorded_not_cured():
    """Было (FIX1_2510.md, вне объёма): при отказе модели PPTX отключал переброску в ОТВЕТЕ, а HTML –
    нет; тест фиксировал расхождение (`"Модель не завершила" not in b.html["ОТВЕТ"]`). Стало (s63 Б1):
    расхождение закрыто – ОТВЕТ веб-отчёта тот же, что у презентации (общая константа)."""
    from engines.channel_action import MODEL_REFUSED_ANSWER
    b = _built("refused")
    assert b.pptx["ОТВЕТ"].startswith("Модель не завершила расчёт корректно"), b.pptx["ОТВЕТ"]
    assert b.html["ОТВЕТ"] == b.pptx["ОТВЕТ"] == MODEL_REFUSED_ANSWER, b.html["ОТВЕТ"]
    # а ПРОБЛЕМА/ЗАТРУДНЕНИЕ при этом совпадают
    assert _pull(b.html["ЗАТРУДНЕНИЕ"]) == _pull(b.pptx["ПРОБЛЕМА"])


# ─── подпись «mROAS» у предельного значения героя ───────────────────────────

def test_slide3_hero_line_uses_mroas_label_not_roi():
    b = _built("fixture")
    assert "Social – самый эффективный канал, mROAS 27.03×" in b.pptx_all
    assert "самый эффективный канал, ROI" not in b.pptx_all
    # портфельный ROI подписан «ROI» – не трогали
    assert "Средневзвешенный ROI 0.80×" in b.pptx["СИТУАЦИЯ"]


def test_slide3_hero_under_breakeven_uses_mroas_label():
    b = _built("hero_under_breakeven")
    assert "Social – лучший среди медиа, но под breakeven (mROAS 0.85×)" in b.pptx_all
    assert "под breakeven (ROI" not in b.pptx_all
    html_text = _flat(b.html_page)
    assert "Social – лучший среди медиа, но всё ещё под breakeven (mROAS 0.85×)" in html_text
    assert "под breakeven (ROI" not in html_text


def test_html_finding_honest_branch_uses_mroas_label():
    b = _built("honest")
    assert "Social – единственный канал близкий к окупаемости (mROAS 27.03×)" in _flat(b.html_page)
    assert "близкий к окупаемости (ROI" not in _flat(b.html_page)


def test_manual_monetary_mode_also_labels_hero_mroas():
    """Денежный режим `manual`: is_legacy ложен, подпись «ROI» из паспорта – но у предельного
    значения героя должна быть «mROAS» (условие – по виду KPI и режиму, не через is_legacy)."""
    b = _built("kpi_manual")
    assert b.data["kpi"]["derived_mode"] == "manual"
    assert "Social – самый эффективный канал, mROAS 27.03×" in b.pptx_all
    assert "По mROAS Social опережает (27.03×)." in b.pptx["ПРОБЛЕМА"]
    assert "По mROAS Social опережает (27.03×)." in b.html["ЗАТРУДНЕНИЕ"]
    assert "Social – самый эффективный канал с mROAS 27.03×" in _flat(b.html_page)


@pytest.mark.parametrize("name, label", [("kpi_count", "CPU"), ("kpi_effectiveness", "Доля")])
def test_count_and_share_kpi_keep_own_label_and_lists_agree(name, label):
    """Штучный KPI и доля: подпись из паспорта (CPU/Доля), «mROAS» в прозе героя не появляется,
    сборка не падает, а ЗАТРУДНЕНИЕ и ПРОБЛЕМА совпадают дословно. (Часть «опережает» у этих
    KPI на реальных данных почти не бывает из-за порога «метрика героя >= 1» – вне объёма;
    здесь она есть только потому, что в фикстуре mROAS героя 27.)"""
    b = _built(name)
    html_z = b.html["ЗАТРУДНЕНИЕ"]
    assert f"По {label} Social опережает" in html_z and "mROAS" not in html_z, html_z
    assert b.pptx["ПРОБЛЕМА"].startswith(html_z + " "), (html_z, b.pptx["ПРОБЛЕМА"])
    assert _pull(html_z)[0] == [_TRPS, "Banners"]


# ─── число героя на слайде 3 – у канала с именем героя ───────────────────────

def test_slide3_hero_number_comes_from_named_hero_not_unit_smell_channel():
    b = _built("unit_smell_hero")
    assert b.facts["hero_channel"] == "Performance"        # Social с unit_smell героем не стал
    assert "Performance – самый эффективный канал, mROAS 16.23×" in b.pptx_all
    assert "Social – самый эффективный" not in b.pptx_all
    assert "Performance – самый эффективный канал с mROAS 16.23×" in _flat(b.html_page)


# ─── безопасность текста ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_no_em_dash_in_scqar_texts(name):
    b = _built(name)
    for text in list(b.html.values()) + list(b.pptx.values()):
        assert "—" not in text, text


def test_missing_budget_share_prints_no_gap_part_in_either_format():
    """Аудит s59: без доли бюджета в фактах HTML не печатает «0% бюджета, но даёт N%»
    (раньше `or 0` превращал None в 0, а условие `is not None` пропускало часть)."""
    b = _built("no_budget_share")
    assert "бюджета, но даёт" not in b.html["ЗАТРУДНЕНИЕ"], b.html["ЗАТРУДНЕНИЕ"]
    assert "бюджета, но даёт" not in b.pptx["ПРОБЛЕМА"], b.pptx["ПРОБЛЕМА"]
    assert "0% бюджета" not in b.html["ЗАТРУДНЕНИЕ"]
