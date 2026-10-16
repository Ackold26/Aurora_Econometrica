"""s63 №1: презентация не директивна при несошедшейся оптимизации – как веб-отчёт.

До s63 при `optimization_converged is False` ОТВЕТ веб-отчёта говорил «Оптимизация не сошлась …»,
а презентация писала «Перераспределить 130 млн руб …», «+7 пп к ROAS», «оптимизатор рекомендует
сократить …» (аудит s62, находка 1). Теперь оба формата читают одно условие и один текст
(`engines.channel_action.OPT_NOT_CONVERGED_*`).

Проверки собирают полную презентацию и веб-отчёт штатно (сценарии – помощники из
`test_underperformers_unified` / `test_headlines_hero_cut_s60`) и ищут запрещённые обороты в тексте
ВСЕХ слайдов, надписях, таблицах и заметках. Сходящийся расчёт – прежние тексты (регрессия).
Мутации – Projects/_s63/report_reports.md.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import test_headlines_hero_cut_s60 as H  # noqa: E402
import test_underperformers_unified as U  # noqa: E402
from engines.channel_action import (  # noqa: E402
    OPT_NOT_CONVERGED_ACTION_01,
    OPT_NOT_CONVERGED_ANSWER,
    OPT_NOT_CONVERGED_COMPLICATION_TAIL,
    OPT_NOT_CONVERGED_FINDING,
    OPT_NOT_CONVERGED_FINDING_SUPPORT,
    OPT_NOT_CONVERGED_RECOMMENDATION,
    OPT_NOT_CONVERGED_TITLE,
    hero_cut_clause_applies,
    optimization_not_converged,
)
from engines.narrative_adapter import derive_action_headline  # noqa: E402

# Запрещённые обороты: сумма переброски, прирост «+X пп», «оптимизатор рекомендует»,
# «требует перебалансировки», «из A в B» с суммой.
_FORBIDDEN = [
    re.compile(r"Перераспределить\s+\d"),
    re.compile(r"Нарастить[^.\n]*на ~\d"),
    re.compile(r"Сократить[^.\n]*\(\d[\d.,]* млн"),
    re.compile(r"\d[\d.,]* млн ₽ из "),
    re.compile(r"\+\d+(?:[.,]\d+)?\s*пп"),
    re.compile(r"оптимизатор рекомендует", re.IGNORECASE),
    re.compile(r"требует перебалансировки"),
    re.compile(r"сократить или остановить", re.IGNORECASE),
    re.compile(r"Как перераспределить бюджет"),
]

# Прежние (директивные) тексты фикстуры при сходящемся расчёте.
_CONV_TITLE = "Перераспределить 130 млн руб в Performance – +7 пп к ROAS"
_CONV_ANSWER = "Перераспределить 130 млн ₽ из TRPs бренд (W 25-54) в Performance; сократить или остановить Social."


def _build_nc(value=False, **kw):
    """Презентация и веб-отчёт с несошедшейся оптимизацией через адаптер (факты – штатно)."""
    opt = {"expected_lift_pct": 7.1, "optimization_converged": value}
    return H._build(spec=kw.pop("spec", None), optimize=opt, **kw)


def _hits(text: str) -> list[str]:
    return [p.pattern for p in _FORBIDDEN if p.search(text)]


# ─── условие ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("facts, expected", [
    ({"optimization_converged": False}, True),
    ({"optimization_converged": None}, True),   # как `not converged` в ОТВЕТЕ веб-отчёта
    ({"optimization_converged": True}, False),
    ({}, False), (None, False),                 # признака нет – сошедшаяся
])
def test_not_converged_condition(facts, expected):
    assert optimization_not_converged(facts) is expected


def test_hero_cut_clause_default_gate_includes_convergence():
    cut = {"action": "Cut"}
    assert not hero_cut_clause_applies({"optimization_converged": False}, cut)
    assert hero_cut_clause_applies({"optimization_converged": True}, cut)


# ─── несошедшаяся оптимизация: ни одного директивного оборота ────────────────

@pytest.mark.parametrize("kw", [
    {},                                                # герой Social – Scale, лидер Performance
    {"spec": {"Social": H._ch("Reduce")}},              # герой с Cut/Reduce (хвост «оптимизатор рекомендует»)
    {"balanced": True},                                 # разрыв бюджет/вклад < 5 пп
    {"spec": {"Banners": H._ch("Cut", mroas=0.6), "OLV": H._ch("Cut", mroas=0.5),
              "Performance": H._ch("Cut", mroas=0.7)}},  # «Риск»: большинство Cut
], ids=["hero_scale", "hero_cut", "balanced", "risk"])
@pytest.mark.parametrize("value", [False, None], ids=["false", "none"])
def test_deck_has_no_directive_text_when_not_converged(kw, value):
    b = _build_nc(value, **kw)
    assert b.facts["optimization_converged"] is value
    assert _hits(b.deck) == [], (_hits(b.deck), [l for l in b.deck.split("\n") if any(
        p.search(l) for p in _FORBIDDEN)])
    # презентация несёт текст «не сошлась» на каждом из мест, где раньше была директива
    for text in (OPT_NOT_CONVERGED_TITLE, OPT_NOT_CONVERGED_FINDING, OPT_NOT_CONVERGED_FINDING_SUPPORT,
                 OPT_NOT_CONVERGED_ANSWER, OPT_NOT_CONVERGED_ACTION_01):
        assert text in b.deck, text
    assert OPT_NOT_CONVERGED_COMPLICATION_TAIL in b.pptx["ПРОБЛЕМА"]
    assert "Не определён" in b.deck                       # блок «Ожидаемый эффект»


def test_deck_answer_equals_web_report_answer_when_not_converged():
    """Один текст на оба формата: ОТВЕТ презентации = ОТВЕТ веб-отчёта = общая константа; действие 01 –
    тот же текст, что в разделе рекомендаций веб-отчёта."""
    b = _build_nc()
    assert b.html["ОТВЕТ"] == b.pptx["ОТВЕТ"] == OPT_NOT_CONVERGED_ANSWER
    assert OPT_NOT_CONVERGED_ACTION_01 in b.flat and OPT_NOT_CONVERGED_ACTION_01 in b.deck
    assert OPT_NOT_CONVERGED_RECOMMENDATION in b.flat  # `РЕКОМЕНДАЦИЯ` веб-отчёта


def test_headlines_when_not_converged():
    """Заголовки слайдов: scqar – «не сошлась»; mroas – без «+X пп», без «сократить источник» и без хвоста."""
    b = _build_nc()
    assert b.headline("scqar") == OPT_NOT_CONVERGED_TITLE
    assert b.headline("mroas") == "Нарастить Social – mROAS 27.03× против Performance"
    b2 = _build_nc(spec={"Social": H._ch("Reduce")})
    assert b2.headline("mroas") == "Social – лучший канал по mROAS (27.03×)"
    assert "оптимизатор рекомендует" not in b2.headline("mroas")


def test_honest_narrative_title_keeps_priority_over_not_converged():
    """Модель с медиа < 10 % продаж: заголовок scqar – диагностический (он не содержит директивы)."""
    b = _build_nc(balanced=True, facts_patch={
        "honest_narrative": True, "media_contribution_pct": 5.0, "baseline_pct": 95.0})
    assert b.headline("scqar") == "Перед перераспределением: диагностика низкой инкрементальности медиа"


def test_model_refused_keeps_its_own_text_over_not_converged():
    """Отказ модели важнее: его тексты прежние («рекомендации по переброске отключены»)."""
    b = H._build(optimize={"expected_lift_pct": 7.1, "optimization_converged": False,
                           "model_reliability": {"verdict": "unreliable", "refused": True}})
    assert b.facts["model_refused"] is True
    assert b.pptx["ОТВЕТ"] == "Модель не завершила расчёт корректно – рекомендации по переброске отключены."
    assert b.headline("scqar") == "Модель не завершила расчёт корректно – переброска бюджета отключена"
    assert OPT_NOT_CONVERGED_ANSWER not in b.pptx["ОТВЕТ"]


# ─── сходящийся расчёт: прежние тексты ──────────────────────────────────────

def test_converged_deck_keeps_directive_texts():
    b = H._build(spec={"Social": H._ch("Reduce")})
    assert b.facts["optimization_converged"] is True
    assert b.headline("scqar") == _CONV_TITLE and _CONV_TITLE in b.deck
    assert b.pptx["ОТВЕТ"] == _CONV_ANSWER
    assert H._HERO_CUT_PART in b.pptx["ПРОБЛЕМА"]           # хвост «оптимизатор рекомендует сократить …»
    assert b.headline("mroas") == H._MROAS_HERO_CUT and H._MROAS_HERO_CUT in b.deck
    assert "Портфель требует перебалансировки." in b.pptx["ПРОБЛЕМА"]
    assert "+7 пп" in b.deck and "Не определён" not in b.deck
    assert "Рекомендация: перераспределить 130 млн из " in b.deck
    for text in (OPT_NOT_CONVERGED_TITLE, OPT_NOT_CONVERGED_FINDING, OPT_NOT_CONVERGED_ANSWER,
                 OPT_NOT_CONVERGED_ACTION_01, OPT_NOT_CONVERGED_COMPLICATION_TAIL):
        assert text not in b.deck, text


def test_converged_headlines_hero_scale_unchanged():
    """Герой Scale (Social), сходимость есть: количественные заголовки с «+7 пп к ROAS» – прежние."""
    b = H._build()
    assert b.headline("scqar") == "Перераспределить 130 млн руб в Social – +7 пп к ROAS"
    assert b.headline("mroas") == "Нарастить Social и сократить TRPs бренд (W 25-54) – +7 пп к ROAS"
    assert b.headline("mroas") in b.deck


def test_function_scqar_title_function_level():
    """Сама функция: без канала-данных тоже читает признак (а не только сборка колоды)."""
    ch = [{"name": "A", "action": "Scale", "verdict": "Scale", "mroas": 5.0},
          {"name": "B", "action": "Cut", "verdict": "Cut", "mroas": 0.3}]
    facts = {"leader_channel": "A", "hero_channel": "A", "cut_source_channel": "B",
             "scale_destination_channel": "A", "reallocation_mln": 100.0, "expected_lift_pct": 5.0,
             "optimization_converged": True, "model_refused": False}
    assert derive_action_headline(ch, facts, "scqar").startswith("Перераспределить 100 млн руб")
    assert derive_action_headline(ch, dict(facts, optimization_converged=False), "scqar") == OPT_NOT_CONVERGED_TITLE
