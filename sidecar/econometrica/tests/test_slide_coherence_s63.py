"""Согласованность слайдов и веб-отчёта (s63, пакет «все сразу», решение владельца 16.10).

п.1 (Д1): переброска незначима, Cut-каналы есть (ниже порога «Риска») – заголовок слайда «Рекомендация»
    не «Портфель сбалансирован…», ОТВЕТ называет слабые каналы (источник сокращения больше не пропадает).
п.2: заголовок без получателя переброски («… – явного канала для роста нет») – тело слайда с ним
    согласовано: ПРОБЛЕМА, ВОПРОС, действие 01, действие 03, «Ожидаемый эффект» (и находка 3 на s02).
п.3: слайд mROAS при «все отстающие» – тот же страж, что на s09.
п.4–п.6: несошедшаяся оптимизация – заголовок действия 01, ВОПРОС, находка 3, «Ожидаемый эффект» и цитата
    «Ключевого сообщения» в веб-отчёте – те же, что в презентации (общие константы).
Везде регрессия: при значимой переброске с получателем и при сходящемся расчёте тексты прежние.

Тесты – поведением: вызов функций адаптера и сборка презентации и веб-отчёта штатными построителями
(фикстура Kagocel, урезанная до нужных каналов; факты – через адаптер).
"""
from __future__ import annotations

import copy
import html as _html
import os
import re
import sys
from functools import lru_cache

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import test_headlines_hero_cut_s60 as H  # noqa: E402
import test_underperformers_unified as U  # noqa: E402
from aurora_html import build_html  # noqa: E402
from aurora_pptx.builder import AuroraPPTXBuilder  # noqa: E402
from engines.channel_action import (  # noqa: E402
    OPT_NOT_CONVERGED_ACTION_01_TITLE,
    OPT_NOT_CONVERGED_FINDING,
    OPT_NOT_CONVERGED_FINDING_SUPPORT,
    OPT_NOT_CONVERGED_QUESTION,
)
from engines.narrative_adapter import (  # noqa: E402
    _derive_narrative_facts,
    derive_action_headline,
    scqar_headline_case,
)

_T = U._TRPS
_ALL = [_T, "Banners", "OLV", "Performance", "Social"]
_BALANCED = "Портфель сбалансирован – рекомендуется A/B тест перед ре-аллокацией"
_UNCERTAIN = "Снять неопределённость вердиктов перед ре-аллокацией – интервалы эффективности широки"
_NO_GROWTH_TAIL = "Явного канала для роста нет – перераспределять бюджет некуда."
_RESERVE_Q = "Есть ли в текущем миксе резерв эффективности, который стоит задействовать?"
_REALLOC_Q = "Как перераспределить бюджет, чтобы поднять ROAS без снижения охвата знания?"
_HTML_REALLOC_Q = "Как перераспределить бюджет, чтобы поднять ROAS, не снижая охвата знания?"
_S02_NO_RECIPIENT = "Явного канала для роста нет – прирост не определён"
_SIGNAL = "Сигнал к перераспределению части бюджета."


def _cut(m):
    return H._ch("Cut", mroas=m)


# ─── сборка ─────────────────────────────────────────────────────────────────

def _data(names, spec=None, insignificant=False, nc=False, extra=None, kpi_patch=None):
    data = U._scenario_data(spec=spec, kpi_patch=kpi_patch)
    chans = [c for c in data["channels"] if c["name"] in names]
    for e in extra or []:  # шестой канал – копия Banners под другим именем
        c = copy.deepcopy(next(c for c in data["channels"] if c["name"] == "Banners"))
        c.update(e)
        if "action" in e:
            c["verdict"] = e["action"]
        chans.append(c)
    data["channels"] = chans
    if insignificant:  # оптимальные траты = текущим – адаптер даёт сумму переброски 0
        for c in data["channels"]:
            c["optimal_spend"] = c["current_spend"]
    derived = _derive_narrative_facts(data["channels"], {"expected_lift_pct": 7.1}, None, None)
    keep = {k: data["narrative_facts"][k] for k in
            ("total_sales", "baseline_pct", "media_contribution_pct", "honest_narrative")}
    data["narrative_facts"] = {**data["narrative_facts"], **derived, **keep}
    if nc:
        data["narrative_facts"]["optimization_converged"] = False
    return data


def _slides(prs):
    return [[sh.text_frame.text for sh in s.shapes if sh.has_text_frame] for s in prs.slides]


def _scqar(prs) -> dict:
    """Слайд «Рекомендация»: блоки по метке, действия 01/03 (заголовок | тело), «Ожидаемый эффект»."""
    for texts in _slides(prs):
        st = [t.strip() for t in texts]
        if "ПРОБЛЕМА" in st and "ОТВЕТ" in st:
            out = {lab: texts[st.index(lab) + 1] for lab in ("ПРОБЛЕМА", "ВОПРОС", "ОТВЕТ")}
            for num in ("01", "03"):
                i = st.index(num)
                out[num] = (texts[i + 1], texts[i + 2])
            out["ЭФФЕКТ"] = texts[st.index("ОЖИДАЕМЫЙ ЭФФЕКТ") + 1]
            out["slide"] = "\n".join(texts)
            return out
    raise AssertionError("слайд «Рекомендация» не найден")


def _s02_f3(prs) -> tuple[str, str]:
    """Находка 3 презентации: текст и подпись под ним."""
    for texts in _slides(prs):
        for i, t in enumerate(texts):
            if t.startswith("Рекомендация:") or t == OPT_NOT_CONVERGED_FINDING:
                return t, texts[i + 1]
    raise AssertionError("находка 3 не найдена")


def _html_parts(page) -> dict:
    out = dict(U._html_blocks(page))
    f = re.findall(r'<div class="finding-headline">(.*?)</div><p class="finding-support">(.*?)</p>', page, flags=re.S)
    out["f3"] = (_html.unescape(f[2][0]), _html.unescape(f[2][1]))
    m = re.search(r'<div class="impact-value"[^>]*>(.*?)</div>', page, flags=re.S)
    out["ЭФФЕКТ"] = _html.unescape(m.group(1))
    m = re.search(r'<div class="recommendation-lead">(.*?)</div><div class="recommendation-body">(.*?)</div>',
                  page, flags=re.S)
    out["01"] = (_html.unescape(m.group(1)), _html.unescape(m.group(2)))
    m = re.search(r'<blockquote class="pull-quote">(.*?)</blockquote>', page, flags=re.S)
    out["цитата"] = _html.unescape(m.group(1))
    return out


class Built:
    def __init__(self, data):
        self.channels, self.facts = data["channels"], data["narrative_facts"]
        prs = AuroraPPTXBuilder(copy.deepcopy(data)).build()
        self.s09 = _scqar(prs)
        self.s02 = _s02_f3(prs)
        self.deck = "\n".join(t for s in _slides(prs) for t in s)
        self.html = _html_parts(build_html(copy.deepcopy(data)))

    def headline(self, hint):
        return derive_action_headline(self.channels, self.facts, hint)


_SCEN = {
    # n каналов, k Cut; «незн» – переброска незначима
    "N1 1Cut": dict(names=[_T]),
    "N2 1Cut незн": dict(names=[_T, "Social"], insignificant=True),
    "N2 2Cut": dict(names=[_T, "OLV"], spec={"OLV": _cut(0.6)}),
    "N2 2Cut незн": dict(names=[_T, "OLV"], spec={"OLV": _cut(0.6)}, insignificant=True),
    "N3 1Cut незн": dict(names=[_T, "OLV", "Social"], insignificant=True),
    "N3 2Cut": dict(names=[_T, "OLV", "Social"], spec={"OLV": _cut(0.6)}),
    "N3 2Cut незн": dict(names=[_T, "OLV", "Social"], spec={"OLV": _cut(0.6)}, insignificant=True),
    "N4 2Cut незн": dict(names=[_T, "OLV", "Social", "Banners"], spec={"OLV": _cut(0.6)}, insignificant=True),
    "N5 1Cut": dict(names=_ALL),
    "N5 1Cut nc": dict(names=_ALL, nc=True),
    "N5 2Cut": dict(names=_ALL, spec={"OLV": _cut(0.6)}),
    "N2 2Cut nc": dict(names=[_T, "OLV"], spec={"OLV": _cut(0.6)}, nc=True),
    "N5 герой-Reduce nc": dict(names=_ALL, spec={"Social": H._ch("Reduce")}, nc=True),
    "N5 герой-Reduce": dict(names=_ALL, spec={"Social": H._ch("Reduce")}),
    "N6 3Cut незн": dict(names=_ALL, spec={"OLV": _cut(0.6), "Banners": _cut(0.5)}, insignificant=True,
                         extra=[{"name": "Radio", "action": "Hold", "mroas": 1.3}]),
}


@lru_cache(maxsize=None)
def _b(key) -> Built:
    return Built(_data(**_SCEN[key]))


# ─── сценарий заголовка: одна функция для заголовка и тела ──────────────────

@pytest.mark.parametrize("key, case", [
    ("N1 1Cut", "single_cut"), ("N2 1Cut незн", "weak_no_shift"), ("N2 2Cut", "risk_no_recipient"),
    ("N2 2Cut незн", "risk_no_recipient"), ("N3 2Cut", "risk"), ("N3 2Cut незн", "risk"),
    ("N5 1Cut", "shift"), ("N5 1Cut nc", "not_converged"),
])
def test_scqar_headline_case_on_built_facts(key, case):
    b = _b(key)
    assert scqar_headline_case(b.channels, b.facts) == case


def test_scqar_headline_case_gates_and_rest():
    ch = H._syn(("S", "Hold", 1.3), ("A", "Hold", 1.2))
    f = H._syn_facts(ch, reallocation_mln=0.1)
    assert scqar_headline_case(ch, f) == "balanced"
    assert scqar_headline_case(ch, dict(f, model_refused=True)) == "refused"
    assert scqar_headline_case(ch, dict(f, honest_narrative=True, media_contribution_pct=4.0)) == "honest"
    assert scqar_headline_case(ch, dict(f, honest_narrative=True, media_contribution_pct=None)) == "balanced"
    assert scqar_headline_case(ch, dict(f, optimization_converged=None)) == "not_converged"
    assert scqar_headline_case([], f) is None and scqar_headline_case(ch, None) is None


# ─── п.1 (Д1): незначимая переброска при Cut-каналах ────────────────────────

def _syn_portfolio(n, k):
    rows = [("S", "Scale", 5.0)] + [(f"H{i}", "Hold", 1.3) for i in range(1, n - k)]
    rows += [(f"C{i}", "Cut", round(0.1 + 0.1 * i, 2)) for i in range(1, k + 1)]
    return H._syn(*rows)


@pytest.mark.parametrize("n, k, expected", [
    (2, 1, "Крупной переброски нет, но C1 – слабый канал"),
    (3, 1, "Крупной переброски нет, но C1 – слабый канал"),
    (4, 2, "Крупной переброски нет, но C1, C2 – слабые каналы"),
    (5, 2, "Крупной переброски нет, но C1, C2 – слабые каналы"),
    (6, 3, "Крупной переброски нет, но C1, C2 – слабые каналы"),  # не больше двух имён, как у «Риска»
])
def test_d1_headline_names_weak_channels_instead_of_balanced(n, k, expected):
    ch = _syn_portfolio(n, k)
    h = derive_action_headline(ch, H._syn_facts(ch, reallocation_mln=0.1), "scqar")
    assert h == expected
    assert "сбалансирован" not in h


@pytest.mark.parametrize("rows", [
    (("S", "Scale", 5.0), ("H", "Hold", 1.3)),                     # отстающих нет
    (("S", "Scale", 5.0), ("R", "Reduce", 0.9), ("H", "Hold", 1.3)),  # только Reduce – вне Д1
])
def test_d1_without_cut_keeps_balanced_headline(rows):
    ch = H._syn(*rows)
    assert derive_action_headline(ch, H._syn_facts(ch, reallocation_mln=0.1), "scqar") == _BALANCED


def test_d1_does_not_override_uncertain_majority():
    """Большинство вердиктов не определено – прежний «Снять неопределённость…», даже при Cut."""
    ch = H._syn(("S", "Uncertain", 1.3), ("U", "Uncertain", 1.1), ("C", "Cut", 0.3))
    assert derive_action_headline(ch, H._syn_facts(ch, reallocation_mln=0.1), "scqar") == _UNCERTAIN


def test_d1_significant_reallocation_keeps_quantified_headline():
    ch = _syn_portfolio(3, 1)
    assert derive_action_headline(ch, H._syn_facts(ch), "scqar").startswith("Перераспределить 100 млн руб в S")


def test_d1_built_slide_answer_names_weak_channel_and_what_to_do():
    """Kagocel, три канала, TRPs – Cut, переброска незначима. Было: заголовок «Портфель сбалансирован…»,
    ОТВЕТ «Сохранить текущую аллокацию по Social с контролем насыщения.» – TRPs нигде на слайде, кроме
    ПРОБЛЕМЫ. Стало: оба называют TRPs."""
    b = _b("N3 1Cut незн")
    assert b.headline("scqar") == f"Крупной переброски нет, но {_T} – слабый канал"
    assert b.headline("scqar") in b.s09["slide"]
    assert b.s09["ОТВЕТ"] == f"Сохранить аллокацию без переброски; сократить или остановить {_T} после проверки вклада."
    assert "сбалансирован" not in b.s09["slide"]


def test_d1_built_slide_two_weak_channels():
    b = _b("N4 2Cut незн")
    assert b.headline("scqar") == f"Крупной переброски нет, но {_T}, OLV – слабые каналы"
    assert b.s09["ОТВЕТ"] == (
        f"Сохранить аллокацию без переброски; сократить или остановить {_T}, OLV после проверки вклада.")


def test_d1_six_channels_answer_lists_all_weak_even_beyond_headline_two():
    b = _b("N6 3Cut незн")
    assert b.headline("scqar") == f"Крупной переброски нет, но {_T}, Banners – слабые каналы"
    assert f"сократить или остановить {_T}, Banners, OLV после проверки вклада" in b.s09["ОТВЕТ"]


def test_risk_without_reallocation_answer_keeps_cut_source_capitalized():
    """«Риск» при незначимой переброске: источник сокращения в ОТВЕТЕ больше не вычитается
    (было «Сократить или остановить OLV.»), придаточное первым – с заглавной."""
    b = _b("N3 2Cut незн")
    assert b.headline("scqar") == f"Сократить {_T}, OLV и сфокусировать бюджет на Social"
    assert b.s09["ОТВЕТ"] == f"Сократить или остановить {_T}, OLV."


def test_significant_reallocation_answer_still_names_source_once():
    """Регрессия: при значимой переброске источник назван частью «из … в …» и из списка вычитается."""
    b = _b("N3 2Cut")
    assert b.s09["ОТВЕТ"] == f"Перераспределить 61 млн ₽ из {_T} в Social; сократить или остановить OLV."


# ─── п.2: тело слайда при заголовке без получателя ──────────────────────────

def test_guard_body_agrees_with_headline_two_of_two():
    """2 из 2 Cut, переброска значима (получателя нет – «только источник»). Было: ПРОБЛЕМА «Портфель требует
    перебалансировки.», ВОПРОС «Как перераспределить…», 01 «Перераспределить бюджет.», 03 и эффект «+7 пп»,
    находка 3 «+7.1 пп». Стало – см. ниже; ОТВЕТ прежний."""
    b = _b("N2 2Cut")
    s = b.s09
    assert b.headline("scqar") == f"Сократить {_T}, OLV – явного канала для роста нет"
    assert s["ПРОБЛЕМА"].endswith(_NO_GROWTH_TAIL) and "требует перебалансировки" not in s["ПРОБЛЕМА"]
    assert s["ВОПРОС"] == _RESERVE_Q
    assert s["ОТВЕТ"] == f"Сократить {_T} (54 млн ₽); сократить или остановить OLV."
    assert s["01"] == ("Сократить слабые каналы.", s["ОТВЕТ"])
    assert "пп" not in s["03"][1]
    assert s["ЭФФЕКТ"] == "Не определён"
    assert b.s02[1] == _S02_NO_RECIPIENT
    assert not re.search(r"\+\d+(?:[.,]\d+)?\s*пп", s["slide"])


def test_guard_body_without_reallocation_names_every_cut_channel():
    b = _b("N2 2Cut незн")
    s = b.s09
    assert s["ОТВЕТ"] == f"Сократить или остановить {_T}, OLV."
    assert s["01"] == ("Сократить слабые каналы.", s["ОТВЕТ"])
    assert s["ПРОБЛЕМА"].endswith(_NO_GROWTH_TAIL)
    assert s["ЭФФЕКТ"] == "Не определён"
    assert b.s02[1] == _S02_NO_RECIPIENT  # прежде «+7.1 пп» при «сохранить текущую аллокацию»


def test_single_channel_cut_body():
    b = _b("N1 1Cut")
    s = b.s09
    assert b.headline("scqar") == f"Сократить {_T} – явного канала для роста нет"
    assert s["01"] == ("Сократить слабый канал.", f"Сократить или остановить {_T}.")
    assert s["ОТВЕТ"] == f"Сократить или остановить {_T}."
    assert s["ЭФФЕКТ"] == "Не определён"


@pytest.mark.parametrize("key", ["N5 1Cut", "N3 2Cut"])
def test_body_unchanged_when_reallocation_has_recipient(key):
    """Регрессия: значимая переброска с получателем (в т.ч. «Риск» с фокусом на Social) – прежние тексты."""
    b = _b(key)
    s = b.s09
    assert s["ПРОБЛЕМА"].endswith("Портфель требует перебалансировки.")
    assert s["ВОПРОС"] == _REALLOC_Q
    assert s["01"][0] == "Перераспределить бюджет."
    assert s["01"][1].startswith(f"{'130' if key == 'N5 1Cut' else '61'} млн ₽ из {_T} в Social.")
    assert s["03"][1].endswith("Ожидаемый прирост ROAS: +7.1 пп – проверить фактом.")
    assert s["ЭФФЕКТ"] == "+7 пп"
    assert b.s02[1] == "Ожидаемый прирост ROAS: +7.1 пп"


# ─── п.3: слайд mROAS при «все отстающие» ───────────────────────────────────

def test_mroas_slide_guard_when_recipient_is_cut():
    ch = H._syn(("A", "Cut", 0.2), ("B", "Cut", 0.5))
    f = H._syn_facts(ch, scale_destination_channel=None)
    assert derive_action_headline(ch, f, "mroas") == "Сократить неэффективные каналы – явного канала для роста нет"
    three = H._syn(("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7))
    f3 = H._syn_facts(three, hero_channel="C", scale_destination_channel=None)
    assert derive_action_headline(three, f3, "mroas") == "Сократить неэффективные каналы – явного канала для роста нет"


def test_mroas_slide_keeps_focus_when_recipient_is_not_cut():
    """Слабый герой (mROAS < 1.2) – Scale-получатель: «сфокусировать бюджет» остаётся (прежний текст)."""
    ch = H._syn(("S", "Scale", 1.1), ("A", "Cut", 0.2), ("B", "Cut", 0.5))
    assert derive_action_headline(ch, H._syn_facts(ch), "mroas") == "Сократить неэффективные каналы и сфокусировать бюджет"


@pytest.mark.parametrize("key", ["N2 2Cut", "N2 2Cut nc"])
def test_mroas_slide_guard_on_built_deck(key):
    b = _b(key)
    h = "Сократить неэффективные каналы – явного канала для роста нет"
    assert b.headline("mroas") == h and h in b.deck
    assert "сфокусировать" not in b.deck


# ─── п.4: заголовок действия 01 при несошедшейся оптимизации ─────────────────

def test_action_01_title_when_not_converged_is_shared_constant():
    b = _b("N5 1Cut nc")
    assert b.s09["01"][0] == OPT_NOT_CONVERGED_ACTION_01_TITLE
    assert b.html["01"][0] == OPT_NOT_CONVERGED_ACTION_01_TITLE
    assert b.s09["01"][1] == b.html["01"][1]  # тело – прежняя общая константа


def test_action_01_title_when_converged_unchanged():
    b = _b("N5 1Cut")
    assert b.s09["01"][0] == "Перераспределить бюджет."
    assert b.html["01"][0] == "Перебалансировать бюджет."


# ─── п.5: ВОПРОС при несошедшейся оптимизации ───────────────────────────────

@pytest.mark.parametrize("kpi_patch", [
    None,
    {"kpi_kind": "count", "derived_mode": "roi", "kpi_type": "leads"},
    {"kpi_kind": "monetary", "derived_mode": "effectiveness", "kpi_type": "awareness",
     "labels": {"metric_short_label": "Доля", "metric_label": "Доля эффекта"}},
])
def test_question_when_not_converged_html_equals_pptx(kpi_patch):
    b = Built(_data(_ALL, nc=True, kpi_patch=kpi_patch))
    assert b.html["ВОПРОС"] == OPT_NOT_CONVERGED_QUESTION
    assert b.s09["ВОПРОС"] == OPT_NOT_CONVERGED_QUESTION


def test_question_when_converged_unchanged():
    b = _b("N5 1Cut")
    assert b.html["ВОПРОС"] == _HTML_REALLOC_Q
    assert b.s09["ВОПРОС"] == _REALLOC_Q


# ─── п.6: веб-отчёт по сходимости = презентация ─────────────────────────────

@pytest.mark.parametrize("key", ["N5 1Cut nc", "N2 2Cut nc"])
def test_finding_3_and_effect_when_not_converged_html_equals_pptx(key):
    b = _b(key)
    assert b.html["f3"] == (OPT_NOT_CONVERGED_FINDING, OPT_NOT_CONVERGED_FINDING_SUPPORT)
    assert b.s02 == (OPT_NOT_CONVERGED_FINDING, OPT_NOT_CONVERGED_FINDING_SUPPORT)
    assert b.html["ЭФФЕКТ"] == "Не определён" == b.s09["ЭФФЕКТ"]


def test_finding_3_when_not_converged_wins_over_binding_constraints():
    data = _data(_ALL, nc=True)
    data["narrative_facts"]["binding_constraints"] = True
    assert Built(data).html["f3"] == (OPT_NOT_CONVERGED_FINDING, OPT_NOT_CONVERGED_FINDING_SUPPORT)


def test_finding_3_and_effect_when_converged_unchanged():
    b = _b("N5 1Cut")
    assert b.html["f3"] == (f"Рекомендация: перераспределить 130 млн ₽ из {_T} в Social",
                            "Ожидаемый прирост ROAS: +7.1 пп")
    assert b.html["ЭФФЕКТ"] == "+7 пп"


def test_html_insignificant_lift_label_unchanged():
    """Регрессия ветки «Незначим»: сошлась, прирост < 0.5 пп."""
    data = _data(_ALL)
    data["narrative_facts"]["expected_lift_pct"] = 0.2
    assert Built(data).html["ЭФФЕКТ"] == "Незначим (<0.5 пп)"


def test_key_message_signal_when_not_converged_and_hero_reduce_html_equals_pptx():
    """Было: веб-отчёт печатал «Сигнал к перераспределению…» у героя с Reduce при несошедшейся
    оптимизации, презентация – нет. Стало: в обоих фразы нет."""
    b = _b("N5 герой-Reduce nc")
    assert b.html["цитата"] == "Каждый рубль в Social возвращает больше, чем в Performance."
    assert _SIGNAL not in b.deck.replace("\n", " ")


def test_key_message_signal_when_converged_unchanged():
    assert _SIGNAL not in _b("N5 герой-Reduce").html["цитата"]  # герой Reduce, сошлась – как и было
    assert _b("N5 1Cut").html["цитата"].endswith(_SIGNAL)       # герой Scale – фраза на месте
