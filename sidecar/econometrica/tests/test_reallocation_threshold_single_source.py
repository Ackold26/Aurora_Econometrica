"""Один порог значимости переброски — во всех местах одинаково (s48, 14.09.2026).

Разведка s48 (`Projects/THRESHOLDS_s48.md`) нашла не расхождение «отчёт против
колоды», а расхождение колоды с самой собой: `utils.optimizer_honesty.
reallocation_subjects()` называет переброску значимой от 0,5 млн ₽ по умолчанию
(HTML-отчёт и слайд «Главное» колоды используют это значение), но три места
внутри ТОЙ ЖЕ колоды — слайд SCQAR (`aurora_pptx/builder.py:2894,2993`) и все
четыре заголовка слайдов (`engines/narrative_adapter.py:532`) — считают порог
равным 1,0 млн, явно передавая `min_mln=1.0`. Плюс четыре литерала `>= 1`
(`aurora_pptx/builder.py:2873,2905,2907,2909`) дублируют этот же порог в обход
общей функции.

На сумме 0,7 млн ₽ (внутри разрыва 0,5–1,0) один и тот же прогон колоды
одновременно говорит клиенту «перераспределить 0,7 млн из X в Y» (слайд
«Главное», Finding 3) и «сохранить текущую аллокацию, разрыв объясняется
насыщением каналов» (слайд SCQAR, тот же payload, несколькими слайдами дальше).
HTML-отчёт на той же сумме согласен со слайдом «Главное», не со SCQAR.

Тест поведенческий: реально рендерит отчёт (`aurora_html.sections`), реально
собирает колоду (`aurora_pptx.builder.AuroraPPTXBuilder(...).build()`) и реально
зовёт `derive_action_headline` для всех четырёх заголовков — не сравнивает
числа-константы друг с другом (такая проверка была бы зелёной по построению и
ничего не сторожила бы).

До правки (единый порог 0,5 во всех местах) этот тест обязан падать на сумме
0,7 млн — сам по себе факт падения ДО правки и есть проверка, что тест не
формальный.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from aurora_html.sections import (  # noqa: E402
    render_at_a_glance,
    render_executive_summary,
    render_recommendation,
)
from engines.narrative_adapter import derive_action_headline  # noqa: E402

_STRINGS_PATH = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")

# Сумма строго между двумя историческими порогами (0,5 и 1,0 млн) — единственная
# зона, где расхождение вообще наблюдаемо. Ниже 0,5 или выше 1,0 все места
# сегодня и так согласны, тест на этих суммах ничего бы не поймал.
GAP_AMOUNT_MLN = 0.7

LEADER = "Онлайн-видео"          # лидер по вкладу — не сторона переброски
CUT_SOURCE = "Наружная реклама"  # канал, который оптимизатор реально режет
SCALE_DEST = "Performance"


def _channels():
    """Те же имена каналов, что в test_reallocation_source_single_source.py —
    расхождение по СУММЕ, а не по выбору канала, здесь проверяется отдельно."""
    return [
        {"name": LEADER, "spend": 1_212_370_000, "contribution": 10_400_000_000,
         "mroas": 2.1, "roi": 2.1, "action": "Scale", "verdict": "Scale"},
        {"name": SCALE_DEST, "spend": 567_480_000, "contribution": 4_600_000_000,
         "mroas": 4.3, "roi": 4.3, "action": "Scale", "verdict": "Scale"},
        {"name": "ТВ", "spend": 1_026_000_000, "contribution": 2_400_000_000,
         "mroas": 0.8, "roi": 0.8, "action": "Cut", "verdict": "Cut"},
        {"name": CUT_SOURCE, "spend": 729_500_000, "contribution": 600_000_000,
         "mroas": 0.4, "roi": 0.4, "action": "Cut", "verdict": "Cut"},
    ]


def _facts(reallocation_mln=GAP_AMOUNT_MLN, **overrides):
    f = {
        "leader_channel": LEADER,
        "hero_channel": SCALE_DEST,
        "cut_source_channel": CUT_SOURCE,
        "scale_destination_channel": SCALE_DEST,
        "reallocation_mln": reallocation_mln,
        "expected_lift_pct": 5.3,
        "n_active_channels": 4,
        "total_budget_mln": 3535.0,
        "weighted_roi": 1.6,
        "leader_share_spend_pct": 34.0,
        "leader_share_contrib_pct": 45.0,
        "budget_dominator_channel": LEADER,
        "budget_dominator_spend_pct": 34.0,
        "budget_dominator_contrib_pct": 45.0,
        "underperformer_names": ["ТВ"],
        "action_counts": {"Scale": 2, "Cut": 2},
        "binding_constraints": False,
        "optimization_converged": True,
        "converged_at_current": False,
        "honest_narrative": False,
        "model_refused": False,
    }
    f.update(overrides)
    return f


def _payload(reallocation_mln=GAP_AMOUNT_MLN, **overrides):
    return {
        "meta": {"client": "Демо-клиент", "project_id": "DEMO"},
        "narrative_facts": _facts(reallocation_mln=reallocation_mln, **overrides),
        "channels": _channels(),
        "diagnostics": {"mqs_score": 72},
    }


def _ctx(payload):
    with open(_STRINGS_PATH, encoding="utf-8") as fh:
        strings = json.load(fh)
    return {
        "meta": payload["meta"],
        "facts": payload["narrative_facts"],
        "channels": payload["channels"],
        "diagnostics": payload["diagnostics"],
        "strings": strings,
        "report_id": "DEMO",
        "model_version": "1.0",
        "period_unit": "неделям",
    }


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# Канал считается стороной-источником, если текст говорит «из X» / «сократить X»
# / «остановить X» — безотносительно суммы (заголовки слайдов сумму не несут).
_CUT_SIDE_RE_TPL = r"(?:из|[Сс]ократить|[Оо]становить)\s+{name}"


def _names_cut_source(text: str) -> bool:
    return re.search(_CUT_SIDE_RE_TPL.format(name=re.escape(CUT_SOURCE)), text) is not None


# ─── Порядок слайдов колоды на этом payload — детерминирован ─────────────────
# Payload не несёт backtest/generation_compare/forecast/quality_avp/waterfall,
# поэтому все условные вставные слайды build() пропускает (см. builder.py:4674
# AuroraPPTXBuilder.build) — порядок ровно: cover, toc, at_a_glance, key_message,
# scqar, action_chart, action_table, action_timeline, methodology, sources,
# glossary, colophon. Finding 3 живёт на at_a_glance (индекс 2, через
# _build_at_a_glance_findings, builder.py:927/1334); СИТУАЦИЯ/ПРОБЛЕМА/ВОПРОС/
# ОТВЕТ/РЕКОМЕНДАЦИИ — все пять блоков одного слайда scqar (индекс 4).
_SLIDE_AT_A_GLANCE = 2
_SLIDE_SCQAR = 4


def _pptx_slide_text(prs, index: int) -> str:
    parts = []
    for shape in prs.slides[index].shapes:
        if shape.has_text_frame:
            parts.append(shape.text_frame.text)
    return re.sub(r"\s+", " ", "\n".join(parts))


# 🔴 Уточнение разведки s48 (по факту первого прогона этого теста): из четырёх
# заголовков `derive_action_headline` порог значимости переброски реально влияет
# на ТЕКСТ только двух — "mroas" (называет cut_source, только если он есть) и
# "scqar" (ветвится по `subjects["kind"]` явно). "portfolio" и "timeline"
# отвечают на другие вопросы (концентрация топ-N каналов; тренд медиа-вклада
# лидера) и cut_source/scale_dest/subjects в своих ветках не используют вовсе —
# `reallocation_subjects` для них считается, но результат никак не влияет на
# возвращаемую строку. Проверять их на «согласие/несогласие» бессмысленно: они
# не участвуют в вопросе «названа ли переброска значимой», поэтому исключены.
_SIGNIFICANCE_HINTS = ("mroas", "scqar")


def _headline_names_reallocation(hint: str, headline: str) -> bool:
    if hint == "mroas":
        # Ветка со значимой перебросккой прямо называет cut_source стороной,
        # у которой забирают («Нарастить Y и сократить X»).
        return _names_cut_source(headline)
    if hint == "scqar":
        # rebalance/scale_only/cut_only — все три ветки называют сумму («N млн
        # руб»); нейтральные исходы («Портфель сбалансирован», «Снять
        # неопределённость…») числа не несут вовсе.
        return bool(re.search(r"\d+(?:[.,]\d+)?\s*млн\s*руб", headline))
    raise ValueError(f"нет детектора значимости для заголовка {hint!r}")


def test_reallocation_significance_agrees_everywhere_in_the_gap_zone():
    """0,7 млн ₽ — между историческими порогами 0,5 и 1,0. Все места ОБЯЗАНЫ
    сойтись на одном ответе: значима переброска или нет. Сегодня — нет.
    """
    pytest.importorskip("pptx")
    from aurora_pptx.builder import AuroraPPTXBuilder

    ctx = _ctx(_payload())
    prs = AuroraPPTXBuilder(_payload()).build()

    places = {
        "HTML: ОТЧЁТ ЗА 60 СЕКУНД (render_at_a_glance)":
            _names_cut_source(_plain(render_at_a_glance(ctx))),
        "HTML: РЕЗЮМЕ SCQAR (render_executive_summary)":
            _names_cut_source(_plain(render_executive_summary(ctx))),
        "HTML: РЕКОМЕНДАЦИЯ (render_recommendation)":
            _names_cut_source(_plain(render_recommendation(ctx))),
        "PPTX: слайд «Главное», Finding 3":
            _names_cut_source(_pptx_slide_text(prs, _SLIDE_AT_A_GLANCE)),
        "PPTX: слайд SCQAR (ПРОБЛЕМА/ОТВЕТ/РЕКОМЕНДАЦИИ)":
            _names_cut_source(_pptx_slide_text(prs, _SLIDE_SCQAR)),
    }
    for hint in _SIGNIFICANCE_HINTS:
        headline = derive_action_headline(_channels(), _facts(), hint) or ""
        places[f"PPTX: заголовок слайда «{hint}»"] = _headline_names_reallocation(hint, headline)

    verdicts = set(places.values())
    assert len(verdicts) == 1, (
        f"На сумме {GAP_AMOUNT_MLN} млн ₽ места документа расходятся, значима ли "
        f"переброска — один и тот же прогон говорит клиенту разное:\n"
        + "\n".join(f"  {'значима' if v else 'НЕ значима':<12} — {k}"
                     for k, v in places.items())
    )


# ─── Сторож против возврата литерала мимо единого источника ──────────────────

_GUARDED_FILES = (
    os.path.join(os.path.dirname(_HERE), "aurora_pptx", "builder.py"),
    os.path.join(os.path.dirname(_HERE), "engines", "narrative_adapter.py"),
)
# Любое сравнение суммы переброски с числом-литералом мимо
# `utils.optimizer_honesty.reallocation_subjects` / общей константы значимости —
# ровно то, чем сегодня являются builder.py:2873,2905,2907,2909 (```>= 1```
# в обход `_scqar_subjects`/`_rec_subjects`). Разрешённое сравнение —
# только внутри самой функции reallocation_subjects (её файл сюда не входит) и
# только с именованной константой (не с числовым литералом).
_INLINE_THRESHOLD_RE = re.compile(
    r"(?:reallocation_mln|\brealloc\b).{0,20}?>=\s*\d+(?:\.\d+)?"
)


def test_no_inline_reallocation_threshold_literal_outside_shared_source():
    """Порог значимости переброски живёт в одном месте — здесь его быть не должно.

    Формальный вариант этого теста (сравнить два вызова функции с одним и тем же
    параметром) был бы зелёным по построению и не поймал бы найденное в s48:
    поэтому тест читает исходники продакшн-кода, а не вызывает функцию.
    """
    offenders = []
    for path in _GUARDED_FILES:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if _INLINE_THRESHOLD_RE.search(line):
                    offenders.append(f"{os.path.basename(path)}:{n}: {line.strip()}")
    assert not offenders, (
        "Порог значимости переброски снова сравнивается с литералом в обход "
        "единого источника (utils.optimizer_honesty):\n" + "\n".join(offenders)
    )
