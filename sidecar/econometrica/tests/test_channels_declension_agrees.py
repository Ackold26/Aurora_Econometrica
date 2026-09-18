"""Склонение слова «канал» рядом с числом — тот же класс дефекта, что подпись
периода (s49, продолжение находки 18.09.2026, найдено line-подписью с
пересобранным движком: «через 4 активных каналов» вместо «через 4 активных
канала»).

`aurora_html` и `aurora_pptx` печатали «N активных каналов» / «N каналов»
ЖЁСТКОЙ формой множественного числа независимо от N, ИЛИ (в SCQAR-ситуации
`aurora_pptx`) декленировали число СВОИМ локальным кодом (`_ch_word`/`_ch_adj`
в `builder.py`) рядом с уже существующей единой точкой
(`utils.kpi_display.plural`, которой уже пользовался `aurora_html`) — тот же
класс, что «в квартал»/«за период» утром: параллельные копии вместо одного
источника правды.

Починка: `utils.kpi_display.active_channels_phrase(n)` — новая единая точка
для фраз «N активный канал / N активных канала / N активных каналов»,
построенная на уже существующей `plural()` (не второе склонение, обёртка над
тем же примитивом). Все затронутые места в `aurora_html` и `aurora_pptx`
переведены на неё (SCQAR-ситуация) или на уже существовавшую в области
видимости точку (`aurora_html._n_channels`, `aurora_pptx._ru_channels` -
голый носитель без прилагательного, для мест без «активных»).

Тест двухуровневый:
    1. Unit-матрица на `active_channels_phrase` и `_n_channels`/`plural` -
       дёшево и точно проверяет саму грамматику на полном наборе ловушек
       (1, 2, 3, 4, 5, 11-14, 21, 22, 25).
    2. Поведенческие тесты (реальный рендер, не разбор строки по имени) на
       каждом найденном носителе - SCQAR (HTML обе ветки KPI + PPTX),
       «Из N активных каналов» (HTML f4_verdicts_support + PPTX Finding 4),
       «Топ-N каналов» (HTML render_action_table) - доказывают, что число
       реально ДОХОДИТ до central-функции на месте печати, а не осталось
       жёстко зашитым рядом.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aurora_html.sections import (  # noqa: E402
    _n_channels,
    render_at_a_glance,
    render_action_table,
    render_executive_summary,
)
from utils.kpi_display import active_channels_phrase, plural  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_STRINGS_PATH = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")

CLIENT = "Демо-клиент"

# Матрица ловушек русского склонения: 1 (ед.ч.), 2-4 (род.п.ед.ч. + прил.
# род.п.мн.ч.), 5-20 включая 11-14 (искл. — «одиннадцать» и т.п. НЕ канал),
# 21/22/25 (первая цифра числа "возвращается" к 1/2-4/5+ правилу, но 11-14
# внутри второго десятка — нет).
NOUN_MATRIX = {
    1: "канал", 2: "канала", 3: "канала", 4: "канала",
    5: "каналов", 11: "каналов", 12: "каналов", 13: "каналов", 14: "каналов",
    21: "канал", 22: "канала", 25: "каналов",
}


# ─── 1. Unit-матрица (дешёвый и точный уровень) ──────────────────────────────

@pytest.mark.parametrize("n,expected_noun", sorted(NOUN_MATRIX.items()))
def test_plural_noun_matrix(n, expected_noun):
    assert plural(n, ["канал", "канала", "каналов"]) == expected_noun


@pytest.mark.parametrize("n,expected_noun", sorted(NOUN_MATRIX.items()))
def test_active_channels_phrase_matrix(n, expected_noun):
    expected_adj = "активный" if expected_noun == "канал" else "активных"
    assert active_channels_phrase(n) == f"{n} {expected_adj} {expected_noun}"


@pytest.mark.parametrize("n,expected_noun", sorted(NOUN_MATRIX.items()))
def test_n_channels_matrix(n, expected_noun):
    assert _n_channels(n) == f"{n} {expected_noun}"


# ─── 2. Поведенческие тесты по носителям ─────────────────────────────────────

def _channels(count=2):
    return [
        {"name": "Онлайн-видео", "spend": 400_000_000, "contribution": 3_000_000_000,
         "mroas": 2.1, "roi": 2.1, "action": "Scale", "verdict": "Scale"},
        {"name": "Performance", "spend": 200_000_000, "contribution": 1_400_000_000,
         "mroas": 1.9, "roi": 1.9, "action": "Hold", "verdict": "Hold"},
    ][:max(count, 1)] or [{"name": "Единственный", "spend": 100_000_000,
                            "contribution": 500_000_000, "mroas": 1.5, "roi": 1.5,
                            "action": "Hold", "verdict": "Hold"}]


def _facts(n_active_channels, **overrides):
    f = {
        "leader_channel": "Онлайн-видео",
        "hero_channel": "Онлайн-видео",
        "cut_source_channel": "ТВ",
        "scale_destination_channel": "Performance",
        "total_budget_mln": 878.0,
        "n_active_channels": n_active_channels,
        "weighted_roi": 1.6,
        "leader_share_spend_pct": 46.0,
        "leader_share_contrib_pct": 61.0,
        "budget_dominator_channel": "Онлайн-видео",
        "budget_dominator_spend_pct": 46.0,
        "budget_dominator_contrib_pct": 61.0,
        "reallocation_mln": 30.0,
        "expected_lift_pct": 2.0,
        "underperformer_names": [],
        "action_counts": {"Scale": 1, "Hold": 1},
        "binding_constraints": False,
        "optimization_converged": True,
        "converged_at_current": False,
        "honest_narrative": False,
        "model_refused": False,
    }
    f.update(overrides)
    return f


def _ctx(n_active_channels, kpi=None):
    with open(_STRINGS_PATH, encoding="utf-8") as fh:
        strings = json.load(fh)
    ctx = {
        "meta": {"client": CLIENT, "project_id": "DEMO"},
        "facts": _facts(n_active_channels),
        "channels": _channels(2),
        "diagnostics": {"mqs_score": 72},
        "strings": strings,
        "report_id": "DEMO",
        "model_version": "1.0",
        "period_unit": "неделям",
    }
    if kpi is not None:
        ctx["kpi"] = kpi
    return ctx


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _situation_sentence(text: str) -> str:
    m = re.search(re.escape(CLIENT) + r"[^.]*\.", text)
    assert m, f"не нашла предложение с бюджетом в тексте: {text!r}"
    return m.group(0)


@pytest.mark.parametrize("n", [1, 2, 5, 11, 21])
def test_html_scqar_situation_legacy_agrees(n):
    """kpi.is_legacy=True — ветка через JSON-шаблон scqar/situation/template."""
    ctx = _ctx(n, kpi=None)
    sentence = _situation_sentence(_plain(render_executive_summary(ctx)))
    assert active_channels_phrase(n) in sentence, (
        f"N={n}: ожидала {active_channels_phrase(n)!r} в {sentence!r}"
    )


@pytest.mark.parametrize("n", [1, 2, 5, 11, 21])
def test_html_scqar_situation_kpi_aware_agrees(n):
    """kpi.is_legacy=False — ветка через Python f-string (KPI-aware режим)."""
    ctx = _ctx(n, kpi={"kpi_kind": "count", "derived_mode": "roi"})
    sentence = _situation_sentence(_plain(render_executive_summary(ctx)))
    assert active_channels_phrase(n) in sentence, (
        f"N={n}: ожидала {active_channels_phrase(n)!r} в {sentence!r}"
    )


@pytest.mark.parametrize("n", [1, 2, 5, 11, 21])
def test_pptx_scqar_situation_agrees(n):
    pytest.importorskip("pptx")
    from aurora_pptx.builder import AuroraPPTXBuilder

    payload = {
        "meta": {"client": CLIENT, "project_id": "DEMO"},
        "narrative_facts": _facts(n),
        "channels": _channels(2),
        "diagnostics": {"mqs_score": 72},
    }
    prs = AuroraPPTXBuilder(payload).build()
    # СИТУАЦИЯ — слайд SCQAR (индекс 4, тот же порядок, что в соседнем тесте
    # test_reallocation_threshold_single_source.py для этого же payload-профиля).
    texts = [shape.text_frame.text for shape in prs.slides[4].shapes if shape.has_text_frame]
    situation_body = None
    for i, t in enumerate(texts):
        if t.strip() == "СИТУАЦИЯ":
            situation_body = texts[i + 1]
            break
    assert situation_body is not None, f"блок СИТУАЦИЯ не найден: {texts}"
    assert active_channels_phrase(n) in situation_body, (
        f"N={n}: ожидала {active_channels_phrase(n)!r} в {situation_body!r}"
    )


@pytest.mark.parametrize("n", [2, 5, 11])
def test_html_f4_verdicts_support_agrees(n):
    """«Из N активных каналов – чёткий вердикт по каждому» (render_at_a_glance)."""
    ctx = _ctx(2, kpi=None)
    ctx["channels"] = _channels(n) if n <= 2 else (
        _channels(2) + [
            {"name": f"Доп{i}", "spend": 10_000_000, "contribution": 50_000_000,
             "mroas": 1.2, "roi": 1.2, "action": "Hold", "verdict": "Hold"}
            for i in range(n - 2)
        ]
    )
    text = _plain(render_at_a_glance(ctx))
    assert f"Из {active_channels_phrase(n)}" in text, (
        f"N={n}: ожидала 'Из {active_channels_phrase(n)}' в тексте отчёта за 60 секунд"
    )


@pytest.mark.parametrize("n", [2, 5, 11])
def test_pptx_finding4_s4_agrees(n):
    """Slide «Главное», Finding 4 — «Из N активных каналов - чёткая рекомендация»."""
    pytest.importorskip("pptx")
    from aurora_pptx.builder import AuroraPPTXBuilder

    channels = _channels(2) if n <= 2 else (
        _channels(2) + [
            {"name": f"Доп{i}", "spend": 10_000_000, "contribution": 50_000_000,
             "mroas": 1.2, "roi": 1.2, "action": "Hold", "verdict": "Hold"}
            for i in range(n - 2)
        ]
    )
    payload = {
        "meta": {"client": CLIENT, "project_id": "DEMO"},
        "narrative_facts": _facts(2),
        "channels": channels,
        "diagnostics": {"mqs_score": 72},
    }
    prs = AuroraPPTXBuilder(payload).build()
    slide_text = "\n".join(
        shape.text_frame.text for shape in prs.slides[2].shapes if shape.has_text_frame
    )
    assert f"Из {active_channels_phrase(n)}" in slide_text, (
        f"N={n}: ожидала 'Из {active_channels_phrase(n)}' на слайде «Главное»:\n{slide_text}"
    )


def _channels_with_top_n(top_n: int):
    """Строит портфель, где кумулятивный вклад первых top_n каналов пересекает
    85% ровно на top_n-м, а один «хвостовой» канал остаётся вне топа (other_n>0,
    иначе render_action_table уйдёт в ветку s07_balanced, не s07_top_n)."""
    per = 85.0 / top_n + 0.5
    chans = []
    for i in range(top_n):
        chans.append({
            "name": f"Топ{i+1}", "spend": 10_000_000, "contribution": per * 1_000_000,
            "mroas": 1.5, "roi": 1.5, "action": "Hold", "verdict": "Hold",
        })
    remainder = max(100.0 - per * top_n, 1.0)
    chans.append({
        "name": "Хвост", "spend": 1_000_000, "contribution": remainder * 1_000_000,
        "mroas": 0.5, "roi": 0.5, "action": "Cut", "verdict": "Cut",
    })
    return chans


@pytest.mark.parametrize("top_n", [2, 5, 11])
def test_html_s07_top_n_title_agrees(top_n):
    """«Топ-N каналов дают X% продаж» (render_action_table) — N=2..4 требует
    «канала», не «каналов» (родительный ед.ч. при числительном 2-4)."""
    with open(_STRINGS_PATH, encoding="utf-8") as fh:
        strings = json.load(fh)
    ctx = {
        "meta": {"client": CLIENT, "project_id": "DEMO"},
        "facts": _facts(top_n + 1),
        "channels": _channels_with_top_n(top_n),
        "diagnostics": {"mqs_score": 72},
        "strings": strings,
        "report_id": "DEMO",
        "model_version": "1.0",
        "period_unit": "неделям",
    }
    text = _plain(render_action_table(ctx))
    assert f"Топ-{_n_channels(top_n)}" in text, (
        f"top_n={top_n}: ожидала 'Топ-{_n_channels(top_n)}' в заголовке таблицы каналов: {text!r}"
    )
