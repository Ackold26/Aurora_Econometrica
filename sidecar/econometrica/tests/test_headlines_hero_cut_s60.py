"""Заголовки и «герой опережает» в отчётах «Optimizer MMM» (s60, пункты (в) и (г); ТЗ редакция 2).

(в) Порог сценария «Риск» в заголовках слайдов (`derive_action_headline`) – только по Cut,
    а не по Cut+Reduce: большинство прибыльных насыщенных Reduce – не убыточный портфель,
    заголовок обязан остаться количественным («Перераспределить N млн руб … – +X пп»).
    Считаются ВСЕ Cut, включая источник сокращения (иначе порог инвертируется), строго «>».
(г) Герой с действием Cut/Reduce не «опережает» молча: в ПРОБЛЕМЕ (презентация) и ЗАТРУДНЕНИИ
    (веб-отчёт) к части «опережает» добавлен хвост «но оптимизатор рекомендует сократить бюджет
    канала»; заголовок слайда mROAS и заголовок раздела рекомендаций (веб-отчёт) не зовут
    «нарастить» этот канал; цитата «Каждый рубль … Сигнал к перераспределению…» теряет вторую
    фразу. Хвост и эти правки – ТОЛЬКО когда отчёт сам не говорит, что рекомендаций нет:
    в веб-отчёте – модель не отказала И оптимизация сошлась; в презентации – так же с s63 №1
    (до s63 её ОТВЕТ читал один `model_refused`, и при несошедшейся оптимизации она оставалась
    директивной – аудит s60, находка 2; расхождение закрыто).

Тексты проверяются ДОСЛОВНО; сценарии строятся штатно (факты – через адаптер поверх фикстуры).
Помощники – из `test_underperformers_unified` (`_scenario_data`, блоки HTML и PPTX).
Мутации – Projects/_s60/EXEC_VG_report.md.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import test_underperformers_unified as U  # noqa: E402
from aurora_html import build_html  # noqa: E402
from aurora_pptx.builder import AuroraPPTXBuilder  # noqa: E402
from engines.channel_action import (  # noqa: E402
    HERO_CUT_CLAUSE,
    VERDICT_DISPLAY_RU,
    hero_cut_clause_applies,
    is_underperformer,
    underperformer_names,
)
from engines.narrative_adapter import derive_action_headline  # noqa: E402

_TRPS = U._TRPS
_CLAUSE = "но оптимизатор рекомендует сократить бюджет канала"
_HERO_CUT_PART = f"По mROAS Social опережает (27.03×), {_CLAUSE}."
_HERO_PLAIN_PART = "По mROAS Social опережает (27.03×)."
_SCQAR_FIXTURE = "Перераспределить 130 млн руб в Social – +7 пп к ROAS"
_RISK_HEADLINE = f"Сократить {_TRPS}, OLV и сфокусировать бюджет на Social"
_MROAS_HERO_CUT = f"Social – лучший канал по mROAS (27.03×), {_CLAUSE}"
_HTML_TITLE_HERO_CUT = f"Social – лучший канал по mROAS, {_CLAUSE}"
_SIGNAL = "Сигнал к перераспределению части бюджета."
_QUOTE_FIRST = "Каждый рубль в Social возвращает больше, чем в Performance."
_REFUSED = {"expected_lift_pct": 7.1, "model_reliability": {"verdict": "unreliable", "refused": True}}


# ─── сборка ─────────────────────────────────────────────────────────────────

def _ch(action, **extra) -> dict:
    """Описание канала для `_scenario_data`: действие и его подпись (action_label) вместе."""
    return {"action": action, "action_label": VERDICT_DISPLAY_RU.get(action, action), **extra}


def _deck_text(prs) -> str:
    """Весь текст колоды: надписи, таблицы и заметки всех слайдов."""
    out = []
    for slide in prs.slides:
        for sh in slide.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                out.extend(cell.text for row in sh.table.rows for cell in row.cells)
        if slide.has_notes_slide:
            out.append(slide.notes_slide.notes_text_frame.text)
    return "\n".join(out)


class Built:
    def __init__(self, data):
        self.data = data
        self.facts = data["narrative_facts"]
        self.channels = data["channels"]
        self.page = build_html(copy.deepcopy(data))
        self.prs = AuroraPPTXBuilder(copy.deepcopy(data)).build()
        self.html = U._html_blocks(self.page)
        self.pptx, self.scqar_slide = U._pptx_blocks(self.prs)
        self.deck = _deck_text(self.prs)
        self.flat = U._flat(self.page)

    def headline(self, hint):
        return derive_action_headline(self.channels, self.facts, hint)


def _build(spec=None, **kw) -> Built:
    return Built(U._scenario_data(spec=spec, **kw))


_ALL_CUT = {n: _ch("Cut") for n in ("Performance", "Social", "Banners", "OLV")}


# ─── (в): порог «Риска» – только Cut ────────────────────────────────────────

def test_scqar_headline_profitable_reduce_majority_stays_quantified():
    """(iii) TRPs Cut + OLV, Banners, Performance Reduce (все mROAS >= 1.5): три из пяти – насыщенные
    прибыльные каналы, не убыточный портфель – заголовок количественный, «сфокусировать» нигде нет."""
    b = _build(spec={"Banners": _ch("Reduce"), "OLV": _ch("Reduce"), "Performance": _ch("Reduce")})
    assert b.headline("scqar") == _SCQAR_FIXTURE
    assert _SCQAR_FIXTURE in b.scqar_slide
    assert "сфокусировать" not in b.deck
    assert "сфокусировать" not in b.flat


def test_scqar_headline_cut_reduce_mix_below_cut_threshold_stays_quantified():
    """(iv) TRPs и Banners (0.6) – Cut, OLV и Performance – Reduce: два Cut из пяти – ниже порога."""
    b = _build(spec={"Banners": _ch("Cut", mroas=0.6), "OLV": _ch("Reduce"), "Performance": _ch("Reduce")})
    assert b.headline("scqar") == _SCQAR_FIXTURE
    assert _SCQAR_FIXTURE in b.scqar_slide
    assert "сфокусировать" not in b.deck


def test_scqar_headline_loss_majority_keeps_risk():
    """(iv-б) честный «Риск»: четыре Cut из пяти (все mROAS < 1) – прежний заголовок."""
    b = _build(spec={"Banners": _ch("Cut", mroas=0.6), "OLV": _ch("Cut", mroas=0.5),
                     "Performance": _ch("Cut", mroas=0.7)})
    assert b.headline("scqar") == _RISK_HEADLINE
    assert _RISK_HEADLINE in b.scqar_slide


def test_mroas_headline_never_calls_profitable_reduce_ineffective():
    """(v) слабый герой (Social 1.15) и три прибыльных Reduce (1.02–1.10): заголовок слайда mROAS не
    называет их «неэффективными» (INV-50); «Сократить неэффективные каналы» нет нигде в колоде."""
    b = _build(balanced=True, spec={
        "Social": {"mroas": 1.15},
        "Performance": _ch("Reduce", mroas=1.10), "Banners": _ch("Reduce", mroas=1.05),
        "OLV": _ch("Reduce", mroas=1.02)})
    assert b.headline("mroas") == "Сбалансировать портфель по mROAS – один канал не доминирует"
    assert "Сбалансировать портфель по mROAS – один канал не доминирует" in b.deck
    assert "неэффективные" not in b.deck


@pytest.mark.parametrize("mroas", [None, 0.0])
def test_risk_threshold_ignores_missing_or_zero_mroas(mroas):
    """(vi), (vii): у трёх Reduce нет mROAS или он нулевой – ключ сортировки даёт 0.0, но это не Cut:
    «Риск» не включается, заголовок начинается с «Перераспределить»."""
    b = _build(spec={n: _ch("Reduce", mroas=mroas) for n in ("Banners", "OLV", "Performance")})
    h = b.headline("scqar")
    assert h == _SCQAR_FIXTURE, h
    assert _SCQAR_FIXTURE in b.scqar_slide
    assert "сфокусировать" not in b.deck


# ─── (в): функция на синтетических портфелях ────────────────────────────────

def _syn(*rows):
    """Каналы без лишних полей: (имя, действие, mROAS). Лидер/герой/получатель – первый канал."""
    return [{"name": n, "action": a, "verdict": a, "mroas": m} for n, a, m in rows]


def _syn_facts(channels, **over):
    cuts = underperformer_names(channels)
    f = {
        "leader_channel": channels[0]["name"], "hero_channel": channels[0]["name"],
        "cut_source_channel": cuts[0] if cuts else None,
        "scale_destination_channel": channels[0]["name"],
        "reallocation_mln": 100.0, "expected_lift_pct": 5.0,
        "underperformer_names_all": cuts,
        "underperformer_names": [n for n in cuts if n != (cuts[0] if cuts else None)],
        "optimization_converged": True, "model_refused": False,
    }
    f.update(over)
    return f


def test_risk_threshold_reads_verdict_when_action_missing():
    """Действие читается из `verdict`, когда `action` нет (как в `underperformer_names`); без обоих –
    «Риска» нет, а не падение."""
    rows = (("S", "Scale", 5.0), ("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7), ("D", "Cut", 0.9))
    only_verdict = [{"name": n, "verdict": a, "mroas": m} for n, a, m in rows]
    facts = {"leader_channel": "S", "hero_channel": "S", "scale_destination_channel": "S",
             "cut_source_channel": "A", "reallocation_mln": 100.0, "expected_lift_pct": 5.0}
    h = derive_action_headline(only_verdict, facts, "scqar") or ""
    assert h == "Сократить A, B и сфокусировать бюджет на S", h
    no_action = [{"name": n, "mroas": m} for n, a, m in rows]
    h2 = derive_action_headline(no_action, facts, "scqar") or ""
    assert h2.startswith("Перераспределить"), h2
    # факт со списком имён есть, а действий у каналов нет – «Риска» тоже нет
    h3 = derive_action_headline(no_action, dict(facts, underperformer_names_all=["A", "B", "C", "D"]), "scqar") or ""
    assert h3.startswith("Перераспределить"), h3


@pytest.mark.parametrize("n_cut, risk", [(4, True), (3, True), (2, False)])
def test_risk_boundary_on_five_channels_three_cut_is_risk_two_is_not(n_cut, risk):
    """Граница порога на пяти каналах. Было (s60): `> max(2, (N + 1) // 2)` – четыре Cut «Риск», три
    нет. Стало (s63, решение владельца 16.10): Cut строго больше половины (3 из 5) – «Риск»; два – нет.
    Три Cut из пяти раньше давали «Перераспределить …», теперь «Сократить A, B и сфокусировать …»."""
    rows = [("S", "Scale", 5.0), ("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7), ("D", "Cut", 0.9)]
    rows = [r if i <= n_cut else (r[0], "Hold", r[2]) for i, r in enumerate(rows)]
    ch = _syn(*rows)
    h = derive_action_headline(ch, _syn_facts(ch), "scqar") or ""
    assert h.startswith("Сократить ") == risk, h
    if risk:
        assert h == "Сократить A, B и сфокусировать бюджет на S"
    else:
        assert h.startswith("Перераспределить"), h


def test_risk_threshold_counts_cut_source_whatever_its_action():
    """Инверсия порога (аудит s60, High-2): прежний порог считал Cut БЕЗ источника сокращения, поэтому
    при источнике-Reduce прибыльные Cut давали «Риск», а убыточные – нет. Считаются ВСЕ Cut, и при любом
    источнике (j: источник Reduce, три прибыльных Cut; k: источник Cut, три убыточных Cut) ответ один.
    Было (s60): три Cut из пяти – не «Риск», оба портфеля «Перераспределить …». Стало (s63): три из
    пяти – строгое большинство, оба «Риск»; нет инверсии – два Cut при источнике-Reduce, как раньше, нет."""
    j = _syn(("S", "Scale", 5.0), ("R", "Reduce", 0.085), ("P", "Cut", 3.0), ("B", "Cut", 2.0), ("O", "Cut", 1.8))
    k = _syn(("S", "Scale", 5.0), ("R", "Cut", 0.085), ("P", "Cut", 0.6), ("B", "Cut", 0.5), ("O", "Hold", 1.8))
    for ch, expected in ((j, "Сократить R, O и сфокусировать бюджет на S"),
                         (k, "Сократить R, B и сфокусировать бюджет на S")):
        assert _syn_facts(ch)["cut_source_channel"] == "R"
        assert derive_action_headline(ch, _syn_facts(ch), "scqar") == expected
    # два Cut из пяти при источнике-Reduce (прибыльные Cut P и B): ниже порога, как и без Reduce
    two = _syn(("S", "Scale", 5.0), ("R", "Reduce", 0.085), ("P", "Cut", 3.0), ("B", "Cut", 2.0), ("O", "Hold", 1.8))
    assert _syn_facts(two)["cut_source_channel"] == "R"
    h = derive_action_headline(two, _syn_facts(two), "scqar") or ""
    assert h.startswith("Перераспределить"), h
    # четыре Cut при источнике-Reduce (шесть каналов): «Риск», источник назван первым, затем Cut
    six = _syn(("S", "Scale", 5.0), ("R", "Reduce", 0.085), ("P", "Cut", 0.6), ("B", "Cut", 0.7),
               ("O", "Cut", 0.8), ("T", "Cut", 0.9))
    assert derive_action_headline(six, _syn_facts(six), "scqar") == "Сократить R, P и сфокусировать бюджет на S"


def test_risk_headline_names_only_cut_channels():
    """Имена в «Сократить X, Y …» – источник и затем Cut; Reduce не называется, даже если его mROAS
    ниже второго Cut (Reduce R: 0.3 – между источником A 0.2 и Cut B 0.5)."""
    ch = _syn(("S", "Scale", 5.0), ("A", "Cut", 0.2), ("R", "Reduce", 0.3), ("B", "Cut", 0.5),
              ("C", "Cut", 0.9), ("D", "Cut", 1.1))
    f = _syn_facts(ch)
    assert f["underperformer_names_all"] == ["A", "R", "B", "C", "D"]  # Reduce в списке отстающих есть
    assert derive_action_headline(ch, f, "scqar") == "Сократить A, B и сфокусировать бюджет на S"


def test_risk_name_list_has_no_duplicate_when_facts_list_contains_the_source():
    """Внешний факт `underperformer_names_all` с источником в голове: источник в заголовке один раз."""
    ch = _syn(("S", "Scale", 5.0), ("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7), ("D", "Cut", 0.9))
    h = derive_action_headline(ch, _syn_facts(ch), "scqar") or ""
    assert h.count("A") == 1 and h == "Сократить A, B и сфокусировать бюджет на S", h


def test_duplicate_channel_name_first_occurrence_decides_the_action():
    """Имена каналов неуникальны: действие по имени – у ПЕРВОГО канала (как герой `hero_ch` везде).
    Шесть каналов, четыре имени Cut (B – первое вхождение Cut, второй B – Scale): «Риск» (4 > 3)."""
    ch = _syn(("S", "Scale", 5.0), ("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7),
              ("D", "Cut", 0.9), ("B", "Scale", 2.0))
    h = derive_action_headline(ch, _syn_facts(ch), "scqar") or ""
    assert h == "Сократить A, B и сфокусировать бюджет на S", h


def test_two_channel_portfolio_all_cut_gets_risk_without_focus():
    """Было (s60): портфель из двух каналов «Риска» не получал никогда (строгое «>» и пол 2). Стало (s63,
    решение владельца 16.10): 2 из 2 Cut – «Риск», но получатель сам Cut, поэтому страж: вместо
    «Сократить A, B и сфокусировать бюджет на B» – «Сократить A, B – явного канала для роста нет».
    Три из трёх – тоже страж (раньше «… и сфокусировать бюджет на C», где C – Cut)."""
    ch = _syn(("A", "Cut", 0.2), ("B", "Cut", 0.5))
    f = _syn_facts(ch, hero_channel="A", leader_channel="A", scale_destination_channel=None)
    assert derive_action_headline(ch, f, "scqar") == "Сократить A, B – явного канала для роста нет"
    f_hero_b = _syn_facts(ch, hero_channel="B", leader_channel="B", scale_destination_channel=None)
    assert derive_action_headline(ch, f_hero_b, "scqar") == "Сократить A, B – явного канала для роста нет"
    three = _syn(("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7))
    h = derive_action_headline(three, _syn_facts(three, hero_channel="C", scale_destination_channel="C"), "scqar") or ""
    assert h == "Сократить A, B – явного канала для роста нет", h


def test_risk_falls_back_to_channels_when_facts_have_no_names_list():
    """Факта `underperformer_names_all` нет – имена по каналам той же функцией (а не «нет Риска»)."""
    ch = _syn(("S", "Scale", 5.0), ("A", "Cut", 0.2), ("B", "Cut", 0.5), ("C", "Cut", 0.7), ("D", "Cut", 0.9))
    f = _syn_facts(ch)
    del f["underperformer_names_all"], f["underperformer_names"]
    assert derive_action_headline(ch, f, "scqar") == "Сократить A, B и сфокусировать бюджет на S"


# ─── (г): хвост у героя с Cut/Reduce ────────────────────────────────────────

def test_hero_cut_clause_text_is_single_and_without_long_dash():
    assert HERO_CUT_CLAUSE == _CLAUSE
    assert "\u2014" not in HERO_CUT_CLAUSE and "Aurora" not in HERO_CUT_CLAUSE


@pytest.mark.parametrize("case", ["Reduce", "Cut"])
def test_hero_cut_clause_same_in_both_formats(case):
    """(ii-б) герой Social – Reduce (TRPs Cut) и «все Cut»: в ПРОБЛЕМЕ и ЗАТРУДНЕНИИ – одна и та же
    дословная фраза с хвостом; длинного тире нет."""
    b = _build(spec={"Social": _ch("Reduce")}) if case == "Reduce" else _build(balanced=True, spec=_ALL_CUT)
    for where, text in (("ЗАТРУДНЕНИЕ", b.html["ЗАТРУДНЕНИЕ"]), ("ПРОБЛЕМА", b.pptx["ПРОБЛЕМА"])):
        assert _HERO_CUT_PART in text, (where, text)
        assert "\u2014" not in text, (where, text)
    assert _HERO_PLAIN_PART not in b.html["ЗАТРУДНЕНИЕ"].replace(_HERO_CUT_PART, "")


@pytest.mark.parametrize("action", ["Scale", "Watch", "Hold"])
def test_hero_scale_or_watch_has_no_clause(action):
    """Герой без Cut/Reduce: часть «опережает» дословно прежняя, хвоста нигде нет."""
    b = _build(spec={"Social": _ch(action)})
    assert _HERO_PLAIN_PART in b.html["ЗАТРУДНЕНИЕ"]
    assert _HERO_PLAIN_PART in b.pptx["ПРОБЛЕМА"]
    for text in (b.html["ЗАТРУДНЕНИЕ"], b.pptx["ПРОБЛЕМА"], b.deck, b.flat):
        assert "рекомендует сократить бюджет канала" not in text


def test_hero_clause_absent_when_action_missing():
    """У героя нет ни `action`, ни `verdict`: сборка не падает, хвоста нет в обоих форматах."""
    b = _build(spec={"Social": {"action": None, "verdict": None}})
    assert _HERO_PLAIN_PART in b.html["ЗАТРУДНЕНИЕ"] and _HERO_PLAIN_PART in b.pptx["ПРОБЛЕМА"]
    assert "рекомендует сократить бюджет канала" not in b.deck + b.flat
    assert "лучший канал по mROAS" not in b.deck + b.flat


@pytest.mark.parametrize("mroas", [None, 0.0])
def test_hero_part_absent_when_hero_mroas_missing_or_zero(mroas):
    """Герой закреплён (Social, Reduce), mROAS нет или 0: части «опережает» нет вовсе, хвоста нет,
    заголовок слайда mROAS – не «лучший канал», сборка не падает (урок s59 п.7)."""
    b = _build(spec={"Social": _ch("Reduce", mroas=mroas)}, facts_patch={"hero_channel": "Social"})
    assert b.facts["hero_channel"] == "Social"
    for text in (b.html["ЗАТРУДНЕНИЕ"], b.pptx["ПРОБЛЕМА"]):
        assert "опережает" not in text, text
    assert "рекомендует сократить бюджет канала" not in b.deck
    assert "лучший канал по mROAS" not in b.deck
    assert not (b.headline("mroas") or "").startswith("Social – лучший")
    # Заголовок раздела рекомендаций в веб-отчёте порога по mROAS не имеет: герой Reduce –
    # не «нарастить» (аудит s60, находка 1).
    assert "нарастить" not in b.flat.casefold()


def test_hero_clause_reads_verdict_fallback():
    """Действие героя – только в `verdict` (порядок ключей важен: помощник копирует `action` в `verdict`)."""
    b = _build(spec={"Social": {"action": None, "verdict": "Reduce", "action_label": "Сократить"}})
    assert b.channels[[c["name"] for c in b.channels].index("Social")]["action"] is None
    assert _HERO_CUT_PART in b.html["ЗАТРУДНЕНИЕ"]
    assert _HERO_CUT_PART in b.pptx["ПРОБЛЕМА"]


def test_hero_clause_agrees_with_answer_and_table():
    """(ii-б) хвост не противоречит остальной колоде: ОТВЕТ в обоих форматах велит «сократить или
    остановить Social», ячейка действия Social в таблице – «Сократить» (у фикстуры «(предв.)»)."""
    b = _build(spec={"Social": _ch("Reduce")})
    for text in (b.html["ОТВЕТ"], b.pptx["ОТВЕТ"]):
        assert "сократить или остановить Social" in text, text
    cells = []
    for slide in b.prs.slides:
        shapes = [sh for sh in slide.shapes if sh.has_text_frame]
        for sh in shapes:
            if sh.text_frame.text.strip() == "Social":
                cells += [o.text_frame.text for o in shapes
                          if o.top == sh.top and o.text_frame.text.startswith("Сократить")]
    assert cells and all(c.startswith("Сократить") for c in cells), cells
    m = re.search(r'data-channel="Social".*?verdict-badge[^>]*>([^<]*)<', b.page, flags=re.S)
    assert m and m.group(1).startswith("Сократить"), m and m.group(1)


# ─── (г): заголовок слайда mROAS ────────────────────────────────────────────

@pytest.mark.parametrize("case", ["not_leader", "hero_is_source", "hero_is_leader"])
def test_mroas_headline_hero_cut(case):
    """Герой с Reduce: заголовок слайда mROAS – «<герой> – лучший канал по mROAS (<m>×), но …»;
    «Нарастить <герой>» и «Защитить лидерство <герой>» нет во всей колоде."""
    if case == "not_leader":
        b, hero, m = _build(spec={"Social": _ch("Reduce")}), "Social", "27.03"
    elif case == "hero_is_source":
        b, hero, m = _build(balanced=True, spec={_TRPS: _ch("Hold"), "Social": _ch("Reduce")}), "Social", "27.03"
    else:
        b, hero, m = _build(balanced=True, spec={"Performance": _ch("Reduce", mroas=40.0)}), "Performance", "40.00"
    assert b.facts["hero_channel"] == hero
    expected = f"{hero} – лучший канал по mROAS ({m}×), {_CLAUSE}"
    assert b.headline("mroas") == expected
    assert expected in b.deck
    assert f"Нарастить {hero}" not in b.deck and f"Защитить лидерство {hero}" not in b.deck
    assert "\u2014" not in expected


def test_mroas_headline_hero_scale_unchanged():
    """Герой – Scale (фикстура): заголовок слайда mROAS прежний, обе фразы цитаты и заголовок раздела
    рекомендаций в веб-отчёте – прежние."""
    b = _build()
    assert b.headline("mroas") == f"Нарастить Social и сократить {_TRPS} – +7 пп к ROAS"
    assert b.headline("mroas") in b.deck
    assert f"{_QUOTE_FIRST} {_SIGNAL}" in b.deck.replace("\n", " ")
    assert f"{_QUOTE_FIRST} {_SIGNAL}" in b.flat
    assert "Aurora рекомендует нарастить Social и пересмотреть позицию Performance" in b.flat
    assert _HTML_TITLE_HERO_CUT not in b.flat


@pytest.mark.parametrize("m, hero_cut", [(1.2, True), (1.19, False)])
def test_mroas_headline_hero_cut_threshold(m, hero_cut):
    """Граница 1.2 – только у заголовка слайда mROAS в презентации (функция). Заголовок раздела
    рекомендаций в веб-отчёте порога не имеет (аудит s60, находка 1): герой Reduce – не «нарастить»
    при любом mROAS."""
    data = U._scenario_data(spec={"Social": _ch("Reduce", mroas=m)}, facts_patch={"hero_channel": "Social"})
    h = derive_action_headline(data["channels"], data["narrative_facts"], "mroas") or ""
    page = U._flat(build_html(copy.deepcopy(data)))
    if hero_cut:
        assert h == f"Social – лучший канал по mROAS ({m:.2f}×), {_CLAUSE}", h
    else:
        assert h == "Сбалансировать портфель по mROAS – один канал не доминирует", h  # ниже порога 1.2
    assert _HTML_TITLE_HERO_CUT in page
    assert "нарастить social" not in page.casefold()


def test_hero_part_count_kpi_real_scale_is_absent():
    """Счётный KPI на реальном масштабе (mROAS героя ~0.027 ед./₽, а ворота – 1.0): части «опережает»
    нет, хвоста нет, текст не падает. (Что герой с лучшим CPU при этом «тянет портфель вниз» – дефект
    ворот, решение владельца, здесь не лечится.)"""
    b = _build(balanced=True, spec={
        "Social": _ch("Reduce", mroas=0.027), "Performance": {"mroas": 0.016}, _TRPS: {"mroas": 0.0001},
        "Banners": {"mroas": 0.0017}, "OLV": {"mroas": 0.0015}},
        kpi_patch={"kpi_kind": "count", "derived_mode": "roi", "kpi_type": "leads"})
    for text in (b.html["ЗАТРУДНЕНИЕ"], b.pptx["ПРОБЛЕМА"]):
        assert "опережает" not in text, text
    assert "рекомендует сократить бюджет канала" not in b.deck
    assert "лучший канал по mROAS" not in b.deck
    # Штучный KPI (аудит s60, находка 1): сырой mROAS ≪ 1.2, но «нарастить» героя Reduce нет
    # нигде на странице веб-отчёта.
    assert "нарастить" not in b.flat.casefold()
    # s63 №2: метрика заголовка – подпись страницы (штучный KPI – CPU), не «mROAS».
    assert _HTML_TITLE_HERO_CUT.replace("по mROAS", "по CPU") in b.flat
    assert _HTML_TITLE_HERO_CUT not in b.flat


# ─── (г): заголовок раздела рекомендаций (веб-отчёт) ────────────────────────

def test_html_recommendation_title_never_says_grow_for_cut_hero():
    """High-1 аудита: «Aurora рекомендует нарастить Social …» рядом с «оптимизатор рекомендует сократить»
    – противоречие в одной странице. Заголовок – из `HERO_CUT_CLAUSE`, без имени бренда."""
    with open(os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json"), encoding="utf-8") as fh:
        tpl = json.load(fh)["action_titles"]["s09_hero_cut"]
    assert "Aurora" not in tpl and "\u2014" not in tpl
    for spec, kw, hero in (({"Social": _ch("Reduce")}, {}, "Social"),
                           ({"Performance": _ch("Reduce", mroas=40.0)}, {"balanced": True}, "Performance")):
        b = _build(spec=spec, **kw)
        assert f"{hero} – лучший канал по mROAS, {_CLAUSE}" in b.flat
        assert f"нарастить {hero}".casefold() not in b.flat.casefold()
        assert "Aurora рекомендует" not in b.flat


# ─── (г): цитата «Каждый рубль … Сигнал к перераспределению …» ──────────────

def test_signal_phrase_dropped_when_hero_is_cut_in_both_formats():
    """Вторая фраза цитаты читается как «переложить в героя» – при герое Cut/Reduce остаётся только
    первая, фактическая; при герое Scale – обе (см. test_mroas_headline_hero_scale_unchanged)."""
    b = _build(spec={"Social": _ch("Reduce")})
    flat_deck = b.deck.replace("\n", " ")
    assert _QUOTE_FIRST in flat_deck and _QUOTE_FIRST in b.flat
    assert _SIGNAL not in flat_deck and _SIGNAL not in b.flat
    assert "Сигнал к перераспределению" not in b.deck + b.flat


# ─── (г): честность – хвост и правки только когда рекомендации есть ──────────

def test_hero_cut_texts_absent_when_model_refused():
    """Модель отказала: ОТВЕТ говорит «рекомендации по переброске отключены», а хвост «оптимизатор
    рекомендует сократить» ему противоречил бы – хвоста, заголовка «лучший канал» и HTML-заголовка нет."""
    b = _build(balanced=True, spec={"Banners": _ch("Reduce"), "Social": _ch("Reduce")}, optimize=_REFUSED)
    assert b.facts["model_refused"] is True
    assert b.pptx["ОТВЕТ"] == "Модель не завершила расчёт корректно – рекомендации по переброске отключены."
    assert _HERO_PLAIN_PART in b.pptx["ПРОБЛЕМА"] and _HERO_PLAIN_PART in b.html["ЗАТРУДНЕНИЕ"]
    assert "рекомендует сократить бюджет канала" not in b.deck + b.flat
    assert "лучший канал по mROAS" not in b.deck + b.flat
    assert b.headline("mroas") == "Модель не завершила расчёт корректно – рекомендации по переброске недоступны"
    assert _HTML_TITLE_HERO_CUT not in b.flat
    assert _SIGNAL in b.deck.replace("\n", " ") and _SIGNAL in b.flat  # цитата прежняя: правка гейтится так же


def test_hero_cut_texts_when_optimization_not_converged_follow_each_answer():
    """Оптимизация не сошлась (аудит s60, находка 2; s63 №1): гейт хвоста повторяет гейт ОТВЕТА, а ОТВЕТ
    презентации теперь, как у веб-отчёта, говорит «Оптимизация не сошлась …». Оба формата: хвоста, заголовка
    «лучший канал … оптимизатор рекомендует» и «нарастить» нет; ответ презентации и веб-отчёта – один текст.
    (До s63 презентация здесь оставалась директивной: «сократить или остановить Social», хвост, заголовок.)"""
    b = _build(spec={"Social": _ch("Reduce")}, facts_patch={"optimization_converged": False})
    # веб-отчёт
    assert b.html["ОТВЕТ"].startswith("Оптимизация не сошлась.")
    assert _HERO_PLAIN_PART in b.html["ЗАТРУДНЕНИЕ"]
    assert "рекомендует сократить бюджет канала" not in b.flat
    assert "лучший канал по mROAS" not in b.flat
    assert _HTML_TITLE_HERO_CUT not in b.flat
    assert "нарастить" not in b.flat.casefold()
    # s63 пакет (п.6): было `_SIGNAL in b.flat` – веб-отчёт печатал «Сигнал к перераспределению…» у героя
    # с Reduce при несошедшейся оптимизации, а презентация (respect_convergence=False) – нет. Стало: гейт
    # цитаты в веб-отчёте тот же, что в презентации, – фразы нет ни там, ни там.
    assert _SIGNAL not in b.flat
    # презентация
    assert _HERO_PLAIN_PART in b.pptx["ПРОБЛЕМА"]
    assert _HERO_CUT_PART not in b.pptx["ПРОБЛЕМА"]
    assert b.pptx["ОТВЕТ"] == b.html["ОТВЕТ"]
    assert "сократить или остановить" not in b.pptx["ОТВЕТ"]
    assert "рекомендует сократить бюджет канала" not in b.deck
    assert b.headline("mroas") == "Social – лучший канал по mROAS (27.03×)"
    assert "Нарастить Social" not in b.deck
    assert _SIGNAL not in b.deck.replace("\n", " ")  # цитата «Ключевого сообщения» – гейт героя Cut/Reduce, прежний


def test_html_title_never_says_grow_for_cut_hero_whatever_the_gate():
    """Герой Cut/Reduce: заголовок раздела рекомендаций не зовёт «нарастить» ни с хвостом (рекомендации
    есть), ни без него (отказ модели, несошедшаяся оптимизация) – `s09_hold_leader`."""
    for kw in ({}, {"facts_patch": {"optimization_converged": False}}, {"optimize": _REFUSED}):
        b = _build(spec={"Social": _ch("Reduce")}, **kw)
        assert "нарастить social" not in b.flat.casefold(), kw
    b = _build(spec={"Social": _ch("Reduce")}, facts_patch={"optimization_converged": False})
    assert "Aurora рекомендует сохранить приоритет Performance с учётом насыщения" in b.flat


@pytest.mark.parametrize("m", [1.1, 1.0, 1.19])
def test_html_title_hero_reduce_below_old_threshold_is_not_grow(m):
    """Находка 1 аудита s60: герой Reduce с mROAS в [1.0; 1.2) получал «нарастить» (порог 1.2) при
    ЗАТРУДНЕНИИ «но оптимизатор рекомендует сократить» – теперь заголовок с хвостом, «нарастить» нет."""
    b = _build(spec={"Social": _ch("Reduce", mroas=m)}, facts_patch={"hero_channel": "Social"})
    assert _HERO_CUT_PART.replace("27.03", f"{m:.2f}") in b.html["ЗАТРУДНЕНИЕ"]
    assert _HTML_TITLE_HERO_CUT in b.flat
    assert "нарастить" not in b.flat.casefold()


# ─── помощники движка ───────────────────────────────────────────────────────

def test_is_underperformer_contract():
    assert is_underperformer({"action": "Cut"}) and is_underperformer({"action": "Reduce"})
    assert is_underperformer({"verdict": "Reduce"}) and is_underperformer({"action": None, "verdict": "Cut"})
    assert not is_underperformer({"action": "Watch"}) and not is_underperformer({"action": "Uncertain"})
    assert not is_underperformer({"action": "Scale", "verdict": "Cut"})  # `action` главнее `verdict`
    assert not is_underperformer(None) and not is_underperformer({})


def test_hero_cut_clause_applies_gates():
    cut, scale = {"action": "Cut"}, {"action": "Scale"}
    ok = {"model_refused": False, "optimization_converged": True}
    assert hero_cut_clause_applies(ok, cut) and hero_cut_clause_applies({}, cut) and hero_cut_clause_applies(None, cut)
    assert not hero_cut_clause_applies(ok, scale) and not hero_cut_clause_applies(ok, None)
    assert not hero_cut_clause_applies({"model_refused": True}, cut)
    assert not hero_cut_clause_applies({"optimization_converged": False}, cut)
    assert not hero_cut_clause_applies({"optimization_converged": None}, cut)  # как `not converged` в ОТВЕТЕ
    # Презентация (аудит s60, находка 2): ОТВЕТ читает один `model_refused`.
    assert hero_cut_clause_applies({"optimization_converged": False}, cut, respect_convergence=False)
    assert hero_cut_clause_applies({"optimization_converged": None}, cut, respect_convergence=False)
    assert not hero_cut_clause_applies({"model_refused": True}, cut, respect_convergence=False)
    assert not hero_cut_clause_applies(ok, scale, respect_convergence=False)
