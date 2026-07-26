"""Нет числа - нет подписи: MQS отсутствует → честное отсутствие оценки,
не фиктивный 0.

Регресс-тест на дефект (2026-07-25): sections.py render_at_a_glance /
render_executive_summary и aurora_pptx.builder Finding 5 показывали клиенту
правдоподобное «Качество модели: MQS 0/100 - Ненадёжное» (или «... -
требует доработки» в PPTX), когда diagnostics.mqs_score отсутствует (метрика
не была рассчитана для этого прогона) — неотличимо от реального провала
модели. Тест ловит рецидив: полностью убирает mqs_score/mqs_tier_label из
diagnostics и проверяет, что «0/100» нигде не появляется, а появляется
честная формулировка отсутствия оценки.
"""
import copy
import json
import os

import pytest

from aurora_html.sections import render_at_a_glance, render_executive_summary
from aurora_pptx.builder import AuroraPPTXBuilder

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")


def _ctx(payload: dict) -> dict:
    """Минимальный context dict для render_* функций sections.py (см. test_report_text_hygiene.py)."""
    strings_path = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")
    with open(strings_path, encoding="utf-8") as f:
        strings = json.load(f)
    return {
        "meta": payload.get("meta") or {},
        "facts": payload.get("narrative_facts"),
        "channels": payload.get("channels") or [],
        "diagnostics": payload.get("diagnostics") or {},
        "strings": strings,
        "kpi": {},
    }


def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


@pytest.fixture(scope="module")
def payload_no_mqs():
    """Реальный payload (channels+facts присутствуют - модель обучена), но
    diagnostics.mqs_score/mqs_tier_label отсутствуют - метрика не посчитана."""
    with open(_FIXTURE, encoding="utf-8") as f:
        base = json.load(f)
    p = copy.deepcopy(base)
    p["diagnostics"]["mqs_score"] = None
    p["diagnostics"]["mqs_tier_label"] = None
    return p


@pytest.fixture(scope="module")
def payload_with_mqs():
    """Регресс-контроль: с mqs_score метрика по-прежнему показывается числом."""
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


# ─── HTML: render_at_a_glance (findings f5) ──────────────────────────────────

def test_html_findings_no_fake_zero_when_mqs_missing(payload_no_mqs):
    html = render_at_a_glance(_ctx(payload_no_mqs))
    assert "0/100" not in html, (
        "MQS отсутствует, но findings показывают 0/100 - фиктивный ноль "
        "читается клиентом как приговор модели, а не как «не оценивали»"
    )
    assert "не выполнялась" in html, "Ожидалась честная формулировка отсутствия оценки MQS"


def test_html_findings_shows_real_score_when_mqs_present(payload_with_mqs):
    html = render_at_a_glance(_ctx(payload_with_mqs))
    assert "MQS 70/100" in html, "Регресс: при наличии mqs_score findings обязаны показывать реальный балл"


# ─── HTML: render_executive_summary (SCQAR situation) ────────────────────────

def test_html_scqar_no_fake_zero_when_mqs_missing(payload_no_mqs):
    html = render_executive_summary(_ctx(payload_no_mqs))
    assert "MQS модели 0/100" not in html, "MQS отсутствует, но SCQAR situation показывает 0/100"


def test_html_scqar_shows_real_score_when_mqs_present(payload_with_mqs):
    html = render_executive_summary(_ctx(payload_with_mqs))
    assert "MQS модели 70/100" in html, "Регресс: при наличии mqs_score SCQAR обязан показывать реальный балл"


# ─── PPTX: at-a-glance findings (slides) ─────────────────────────────────────

def test_pptx_findings_no_fake_zero_when_mqs_missing(payload_no_mqs):
    prs = AuroraPPTXBuilder(payload_no_mqs).build()
    txt = _pptx_text(prs)
    assert "MQS 0/100" not in txt, "MQS отсутствует, но PPTX findings показывают MQS 0/100"
    assert "не выполнялась" in txt, "Ожидалась честная формулировка отсутствия оценки MQS в PPTX"


def test_pptx_findings_shows_real_score_when_mqs_present(payload_with_mqs):
    prs = AuroraPPTXBuilder(payload_with_mqs).build()
    txt = _pptx_text(prs)
    assert "MQS 70/100" in txt, "Регресс: при наличии mqs_score PPTX findings обязаны показывать реальный балл"


# ─── PPTX: карточка «Оценка качества модели» (Medium-долг, 2026-07-26) ───────

def test_pptx_card_shows_no_empty_scale_when_mqs_missing(payload_no_mqs):
    """Пустая шкала — та же ложь, что ноль: форма измерения без измерения.

    До правки карточка рисовала «— / 100» (длинное тире заглушкой, вдобавок
    нарушая правило клиентской типографики) и оставляла под ним ярлык уровня,
    который читался как толкование этого «значения».
    """
    txt = _pptx_text(AuroraPPTXBuilder(payload_no_mqs).build())
    card = [ln for ln in txt.splitlines() if "/ 100" in ln]
    assert not card, f"MQS отсутствует, но карточка рисует пустую шкалу: {card}"
    assert "—" not in txt, "длинное тире в клиентском тексте PPTX (П8-1)"
    assert "Оценка не выполнялась" in txt, "ожидалась прямая формулировка отсутствия"
    # Ярлык уровня — толкование балла: без балла ему неоткуда взяться.
    # («н/д» в других полях слайда законно — это честная отметка отсутствия
    # у периода, числа наблюдений и т.п., она не выдаёт себя за уровень.)
    tiers = [t for t in ("Отличное", "Хорошее", "Приемлемое", "Слабое", "Ненадёжное")
             if t in txt]
    assert not tiers, f"MQS отсутствует, но уровень качества назван: {tiers}"


def test_pptx_card_shows_scale_and_tier_when_mqs_present(payload_with_mqs):
    """Регресс: с посчитанной метрикой карточка прежняя — число, шкала, уровень."""
    txt = _pptx_text(AuroraPPTXBuilder(payload_with_mqs).build())
    assert "/ 100" in txt, "при наличии метрики шкала обязана остаться"
    assert "Оценка не выполнялась" not in txt
