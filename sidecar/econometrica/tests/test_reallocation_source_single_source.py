"""Одна сумма переброски — один источник во всех местах отчёта (s47, 14.09.2026).

Дефект, пойманный на готовом отчёте покупателю: сумма 878 млн ₽ шла по документу
трижды с РАЗНЫМИ каналами-источниками.

  блок «ОТЧЁТ ЗА 60 СЕКУНД» (первая страница):
      «Рекомендация: перераспределить 878 млн ₽ из Онлайн-видео в Performance»
  раздел «РЕКОМЕНДАЦИЯ» и резюме SCQAR:
      «878 млн ₽ из Наружная реклама в Performance»

Врала первая страница — та, которую клиент читает первой. Она брала источником
`leader_channel` (лидер по вкладу), а не `cut_source_channel` (канал, который
оптимизатор реально режет). На демо-данных Онлайн-видео даёт 45 % вклада при 34 %
бюджета: совет «забрать из него» противоречил выводу строкой ниже в том же блоке.

Корень — не опечатка, а два разных правила выбора в двух местах. Поэтому тест
сторожит не одну строку, а инвариант: на данных, где лидер по вкладу и канал к
сокращению — РАЗНЫЕ каналы, все места отчёта обязаны назвать ОДИН источник.
Проверяются обе поставки: веб-отчёт (aurora_html) и колода (aurora_pptx).

Правило-источник: utils.optimizer_honesty.reallocation_subjects.
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
from utils.optimizer_honesty import reallocation_subjects  # noqa: E402

_STRINGS_PATH = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")

AMOUNT_MLN = 878.0
LEADER = "Онлайн-видео"          # лидер по вкладу — источником быть НЕ должен
CUT_SOURCE = "Наружная реклама"  # кого режет оптимизатор — единственный источник
SCALE_DEST = "Performance"


def _channels():
    """Лидер по вкладу и канал к сокращению намеренно РАЗНЫЕ — иначе дефект не виден."""
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


def _facts(**overrides):
    f = {
        "leader_channel": LEADER,
        "hero_channel": SCALE_DEST,
        "cut_source_channel": CUT_SOURCE,
        "scale_destination_channel": SCALE_DEST,
        "reallocation_mln": AMOUNT_MLN,
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


def _payload(**overrides):
    return {
        "meta": {"client": "Демо-клиент", "project_id": "DEMO"},
        "narrative_facts": _facts(**overrides),
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


# Источником считается канал, названный во фразе, которая несёт САМУ СУММУ
# переброски: только такая фраза утверждает, откуда идут деньги. Перечни каналов
# по вердиктам («перевести бюджет из ТВ, Наружная реклама согласно вердиктам»)
# суммы не называют и к источнику отношения не имеют.
def _sources_named(text: str, amount_mln: float = AMOUNT_MLN) -> set[str]:
    amount = f"{amount_mln:.0f}"
    found: set[str] = set()
    for sentence in re.split(r"[.;?]", text):
        if amount not in sentence:
            continue
        for ch in (c["name"] for c in _channels()):
            if re.search(r"из " + re.escape(ch), sentence) or \
               re.search(r"[Сс]ократить " + re.escape(ch), sentence):
                found.add(ch)
    return found


# ─── Правило выбора сторон — единственное на всю программу ───────────────────

def test_rule_never_returns_leader_as_source():
    """Лидер по вкладу источником переброски не бывает никогда."""
    subjects = reallocation_subjects(_facts())
    assert subjects["cut_source"] == CUT_SOURCE
    assert subjects["cut_source"] != LEADER


def test_rule_stays_silent_about_source_when_optimizer_named_none():
    """cut_source пуст → про «из» молчим, называем только получателя.

    Молчание честнее, чем назвать канал, который оптимизатор не трогал.
    """
    subjects = reallocation_subjects(_facts(cut_source_channel=None))
    assert subjects["kind"] == "scale_only"
    assert subjects["cut_source"] is None
    assert subjects["scale_destination"] == SCALE_DEST


# ─── Шаблоны: сводка не имеет права подставлять лидера ───────────────────────

def test_findings_template_has_no_leader_placeholder():
    """Шаблон f3_realloc жёстко держал {leader}/{hero} — источник вшивался в текст."""
    with open(_STRINGS_PATH, encoding="utf-8") as fh:
        strings = json.load(fh)
    tpl = strings["findings_templates"]["f3_realloc"]
    assert "{leader}" not in tpl and "{hero}" not in tpl, (
        f"Шаблон сводки снова подставляет лидера/героя как стороны переброски: {tpl!r}"
    )
    assert "{cut_source}" in tpl and "{scale_destination}" in tpl


# ─── Веб-отчёт: три места одного документа — один источник ───────────────────

def test_html_report_names_one_source_everywhere():
    ctx = _ctx(_payload())
    places = {
        "ОТЧЁТ ЗА 60 СЕКУНД": _plain(render_at_a_glance(ctx)),
        "РЕКОМЕНДАЦИЯ": _plain(render_recommendation(ctx)),
        "РЕЗЮМЕ SCQAR": _plain(render_executive_summary(ctx)),
    }
    per_place = {name: _sources_named(text) for name, text in places.items()}
    all_named = set().union(*per_place.values())

    assert all_named, (
        "Ни одно место отчёта не назвало источник переброски — "
        f"сторож ослеп, проверьте фикстуру: {per_place}"
    )
    assert all_named == {CUT_SOURCE}, (
        "Один отчёт называет разные источники одной и той же суммы: "
        f"{ {k: sorted(v) for k, v in per_place.items()} }. "
        f"Источник обязан быть один — канал к сокращению ({CUT_SOURCE}), "
        f"а не лидер по вкладу ({LEADER})."
    )
    assert LEADER not in all_named


def test_html_findings_silent_about_source_when_cut_source_absent():
    """Нет канала к сокращению → сводка не называет источник вовсе."""
    ctx = _ctx(_payload(cut_source_channel=None))
    text = _plain(render_at_a_glance(ctx))
    assert not _sources_named(text), (
        f"Источник назван при пустом cut_source_channel: {text[:400]!r}"
    )
    assert f"{SCALE_DEST}" in text


# ─── Колода: тот же инвариант на другой поставке ─────────────────────────────

def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return re.sub(r"\s+", " ", "\n".join(parts))


def test_pptx_deck_names_one_source_everywhere():
    pptx = pytest.importorskip("pptx")  # noqa: F841
    from aurora_pptx.builder import AuroraPPTXBuilder

    prs = AuroraPPTXBuilder(_payload()).build()
    named = _sources_named(_pptx_text(prs))
    assert named, "Колода не назвала источник переброски — проверьте фикстуру"
    assert named == {CUT_SOURCE}, (
        f"Колода называет разные источники одной суммы: {sorted(named)}. "
        f"Допустим только канал к сокращению ({CUT_SOURCE})."
    )


# ─── Фразы БЕЗ суммы: заголовки слайдов ──────────────────────────────────────
# Детектор выше считает источники только во фразах с суммой — и именно поэтому
# дефект дожил в заголовках колоды («Нарастить Performance и сократить
# Онлайн-видео»): суммы в них нет, счётчик их не видел. Здесь сторожим само
# называние канала СТОРОНОЙ-ИСТОЧНИКОМ, безотносительно числа.
_CUT_SIDE_RE_TPL = r"(?:из|[Сс]ократить|[Оо]становить)\s+{name}"


def _named_as_cut_side(text: str, channel: str) -> bool:
    """Назван ли канал стороной, у которой забирают (а не «против кого» сравнивают)."""
    return re.search(_CUT_SIDE_RE_TPL.format(name=re.escape(channel)), text) is not None


_SLIDE_HINTS = ("mroas", "portfolio", "timeline", "scqar")


@pytest.mark.parametrize("hint", _SLIDE_HINTS)
@pytest.mark.parametrize(
    "overrides, случай",
    [
        ({}, "как в боевом отчёте"),
        ({"expected_lift_pct": 0.1}, "прирост незначим"),
        ({"underperformer_names": ["ТВ", LEADER]}, "половина портфеля отстаёт"),
        ({"cut_source_channel": None}, "источник не определён"),
        ({"scale_destination_channel": None}, "получатель не определён"),
        ({"hero_channel": LEADER, "scale_destination_channel": LEADER}, "лидер и герой совпали"),
    ],
)
def test_slide_headline_never_names_leader_as_cut_side(hint, overrides, случай):
    """Ни один заголовок слайда не смеет назвать лидера по вкладу тем, у кого забирают.

    Заголовки чисел не несут, поэтому основной счётчик источников их пропускает —
    здесь проверка отдельная и прямая.
    """
    headline = derive_action_headline(_channels(), _facts(**overrides), hint) or ""
    assert not _named_as_cut_side(headline, LEADER), (
        f"[{hint} / {случай}] заголовок называет лидера по вкладу каналом к "
        f"сокращению, хотя оптимизатор режет {CUT_SOURCE}: {headline!r}"
    )


def test_slide_headline_stays_silent_about_cut_when_source_unknown():
    """Источник не определён → заголовок вообще не говорит про сокращение."""
    headline = derive_action_headline(
        _channels(), _facts(cut_source_channel=None), "mroas") or ""
    assert "ократить" not in headline, (
        f"Источника нет, а заголовок всё равно кого-то сокращает: {headline!r}"
    )
    assert SCALE_DEST in headline, "Про рост сказать обязаны — содержание теряться не должно"


def test_scqar_headline_agrees_with_answer_when_leader_equals_hero():
    """Лидер и герой совпали — заголовок не смеет объявлять портфель сбалансированным.

    Доказано сборкой колоды: заголовок говорил «Портфель сбалансирован –
    рекомендуется A/B тест», пока ответ того же слайда печатал «Перераспределить
    878 млн ₽ из Наружной рекламы». Директива и её отрицание на одном слайде.
    """
    facts = _facts(hero_channel=LEADER, scale_destination_channel=LEADER)
    headline = derive_action_headline(_channels(), facts, "scqar") or ""
    assert "сбалансирован" not in headline, (
        f"Оптимизатор предлагает переброску, а заголовок слайда её отрицает: {headline!r}"
    )
    assert f"{AMOUNT_MLN:.0f}" in headline


def test_pptx_deck_never_names_leader_as_cut_side():
    """Та же проверка на собранной колоде целиком — включая фразы без суммы."""
    pytest.importorskip("pptx")
    from aurora_pptx.builder import AuroraPPTXBuilder

    text = _pptx_text(AuroraPPTXBuilder(_payload()).build())
    assert not _named_as_cut_side(text, LEADER), (
        f"В колоде лидер по вкладу ({LEADER}) назван каналом к сокращению, "
        f"хотя оптимизатор режет {CUT_SOURCE}"
    )
    assert _named_as_cut_side(text, CUT_SOURCE), (
        "Колода вовсе не называет канал к сокращению — сторож ослеп"
    )


# ─── Легаси-путь не возвращается ─────────────────────────────────────────────

_SOURCE_FILES = (
    os.path.join(os.path.dirname(_HERE), "aurora_html", "sections.py"),
    os.path.join(os.path.dirname(_HERE), "aurora_pptx", "builder.py"),
    os.path.join(os.path.dirname(_HERE), "engines", "narrative_adapter.py"),
)
# «из {leader}» / «сократить {leader}» в f-строке = подстановка лидера/героя
# стороной, у которой забирают. Числа в такой строке может не быть вовсе.
_LEGACY_RE = re.compile(r"(?:из|[Сс]ократить|[Оо]становить) \{(?:leader|hero)[^}]*\}")


def test_no_legacy_leader_as_reallocation_source_in_sources():
    """Запасной путь «из лидера в героя» удалён — следим, чтобы не вернулся.

    Он был помечен «Legacy fallback when cut_source/scale_destination not yet
    populated» и жил в обоих сборщиках; именно он печатал клиенту неверный канал.
    """
    offenders = []
    for path in _SOURCE_FILES:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if line.lstrip().startswith("#"):
                    continue  # пояснение о том, что ветка убрана, — не рецидив
                if _LEGACY_RE.search(line):
                    offenders.append(f"{os.path.basename(path)}:{n}: {line.strip()}")
    assert not offenders, (
        "Вернулась подстановка лидера/героя как стороны переброски:\n" + "\n".join(offenders)
    )
