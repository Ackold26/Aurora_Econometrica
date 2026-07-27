"""Пороги уровней MQS — из единого источника на всех клиентских поверхностях.

Инцидент, ради которого источник заводился (L16, 2026-04-29): MQS 70 показывал
«Хорошее» в одном месте и «приемлемо» в другом, потому что слой представления
держал свою копию порогов. Правка 2026-07-25 свела к источнику HTML-ветку, а
слайды сохранили собственную лестницу 80/60 — расхождение вернулось той же
дорогой и жило до 2026-07-26: MQS 70-79 читался как «приемлемо» на слайде и
«Хорошее» в отчёте, MQS 55-59 — как «требует доработки» против «Приемлемое».

Тест держит границы канона поведением: сравнивает подпись слайда с ответом
единого источника на каждом пороге и на значении под ним.
"""
import copy
import json
import os

import pytest

from aurora_pptx.builder import AuroraPPTXBuilder
from utils.diagnostics import mqs_tier_info, resolve_mqs_tier_label

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# Границы канона и значения под ними — там, где расходились шкалы.
_PROBE_SCORES = (92, 85, 84, 75, 70, 69, 60, 55, 54, 45, 40, 39, 12)


def _payload_with_score(score):
    with open(_FIXTURE, encoding="utf-8") as f:
        p = copy.deepcopy(json.load(f))
    p["diagnostics"]["mqs_score"] = score
    # Метка от бэкенда намеренно затирается: проверяется именно то, что слой
    # представления берёт уровень у единого источника, а не носит свою копию.
    p["diagnostics"]["mqs_tier_label"] = None
    return p


@pytest.mark.parametrize("score", _PROBE_SCORES)
def test_slide_label_matches_single_source(score):
    b = AuroraPPTXBuilder(_payload_with_score(score))
    findings = b._build_at_a_glance_findings()
    mqs_lines = [
        text for _, text, _ in findings if "MQS" in text and "/100" in text
    ]
    assert mqs_lines, f"подпись MQS не найдена среди findings при score={score}"

    expected = mqs_tier_info(score)["tier_label"].lower()
    assert expected in mqs_lines[0].lower(), (
        f"MQS {score}: слайд говорит «{mqs_lines[0]}», единый источник – "
        f"«{expected}». Слой представления снова держит свою шкалу"
    )


def test_thresholds_are_not_duplicated_as_own_ladder():
    """Соседние значения по разные стороны порога обязаны различаться подписью.

    Если слайд вернётся к своей лестнице (например 80/60), эта проверка
    покраснеет на границах канона 85/70/55/40 — молча разойтись уже нельзя.
    """
    for threshold in (85, 70, 55, 40):
        above = mqs_tier_info(threshold)["tier_label"]
        below = mqs_tier_info(threshold - 1)["tier_label"]
        assert above != below, f"порог {threshold} не различает уровни в источнике"

        f_above = AuroraPPTXBuilder(
            _payload_with_score(threshold))._build_at_a_glance_findings()
        f_below = AuroraPPTXBuilder(
            _payload_with_score(threshold - 1))._build_at_a_glance_findings()
        t_above = " ".join(t for _, t, _ in f_above if "MQS" in t).lower()
        t_below = " ".join(t for _, t, _ in f_below if "MQS" in t).lower()
        assert above.lower() in t_above and below.lower() in t_below, (
            f"на пороге {threshold} слайд не различает «{above}» и «{below}»"
        )


# ─── Карточка «Оценка качества модели» на отдельном слайде ───────────────────
# Инвариант закрывался для findings, а карточка продолжала брать ярлык из поля
# бэкенда (`mqs_tier_label`). При пришедшем балле и отсутствующем ярлыке одна и
# та же колода противоречила сама себе: слайд 3 — «MQS 70/100 – хорошее»,
# карточка — «уровень не определён». Внешний аудит, седьмая волна, 2026-07-26.

_CARD_MARKER = "ОЦЕНКА КАЧЕСТВА МОДЕЛИ"


def _card_slide_texts(prs):
    """Тексты всех фигур того слайда, где живёт карточка оценки."""
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if any(_CARD_MARKER in t for t in texts):
            return texts
    return []


@pytest.mark.parametrize("score", (92, 85, 82, 70, 69, 55, 40, 12))
def test_card_label_matches_single_source(score):
    """Ярлык на карточке выводится из балла, а не ждётся от бэкенда."""
    prs = AuroraPPTXBuilder(_payload_with_score(score)).build()
    texts = _card_slide_texts(prs)
    assert texts, "слайд с карточкой оценки качества не найден в колоде"
    blob = " ".join(texts).lower()

    assert "уровень не определён" not in blob, (
        f"MQS {score}: балл посчитан, но карточка объявляет уровень неопределённым — "
        f"ярлык снова ждут от бэкенда вместо единого источника"
    )
    expected = mqs_tier_info(score)["tier_label"].lower()
    assert expected in blob, (
        f"MQS {score}: карточка не называет уровень «{expected}» из единого источника; "
        f"тексты слайда: {texts}"
    )


# ─── Ярлык, пришедший извне, проверяется по набору канона ────────────────────
# Слой представления доверял полю `mqs_tier_label` как есть — хватало непустой
# строки. Подстановка значения ключа `tier` вместо `tier_label` («excellent»
# вместо «Отличное») печаталась клиенту по-английски и сбивала подбор пояснения
# на «Приемлемо» при отличной модели. Внешний аудит, Medium, 2026-07-26.

def _html_ctx(payload):
    strings_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "econometrica", "aurora_html", "strings_ru.json",
    )
    if not os.path.exists(strings_path):
        strings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "aurora_html", "strings_ru.json",
        )
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


@pytest.mark.parametrize("alien", ["excellent", "GOOD", "уровень-которого-нет", " "])
def test_alien_tier_label_never_reaches_client(alien):
    """Чужой ярлык не показывается: уровень считается из балла."""
    from aurora_html.sections import render_at_a_glance

    p = _payload_with_score(92)
    p["diagnostics"]["mqs_tier_label"] = alien
    html = render_at_a_glance(_html_ctx(p))

    assert alien.strip() == "" or alien not in html, (
        f"ярлык «{alien}» пришёл извне и доехал до клиента — слой представления "
        f"обязан проверять его по набору канона, а не только на непустоту"
    )
    assert mqs_tier_info(92)["tier_label"] in html, (
        "не показан уровень из единого источника при неизвестном ярлыке"
    )


# ─── Ярлык из набора канона, но НЕ для этого балла ───────────────────────────
# Внешний аудит, High, 2026-07-27: `test_alien_tier_label_never_reaches_client`
# выше проверяет ярлык, которого в канone нет вовсе (проверка «непустоты» —
# фикс 2026-07-26). Не проверялось иное: ярлык, который канону ПРИНАДЛЕЖИТ, но
# не соответствует посчитанному баллу (например от старого/частично обновлённого
# расчёта на диске — `results/model-diagnostics.json` не подписан, и в репо уже
# есть прецедент внешней точечной правки этого файла, `tools/recompute_mqs.py`).
# Раньше `resolve_mqs_tier_label(42.0, 'Отличное')` вернул бы 'Отличное' (было:
# такой функции не было вовсе — проверка на членство дублировалась в двух местах
# sections.py). Данные первичны: при расхождении уровень считается из балла.

def test_resolve_mqs_tier_label_matched_label_is_used():
    """Ярлык согласован с баллом — берётся как есть."""
    assert resolve_mqs_tier_label(70.0, "Хорошее") == "Хорошее"


def test_resolve_mqs_tier_label_canon_but_mismatched_is_rejected(caplog):
    """Ярлык принадлежит канону, но не для ЭТОГО балла — уровень из балла,
    расхождение видно в логе (диагностика), не в клиентском тексте."""
    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="utils.diagnostics"):
        result = resolve_mqs_tier_label(42.0, "Отличное")

    assert result == mqs_tier_info(42.0)["tier_label"] == "Слабое", (
        "балл 42.0 (tier weak) обязан дать «Слабое» из канона, а не чужое «Отличное»"
    )
    assert any("42.0" in r.message and "Отличное" in r.message for r in caplog.records), (
        "расхождение обязано уйти в лог диагностики, а не проглатываться молча"
    )


def test_resolve_mqs_tier_label_outside_canon_falls_back_as_before():
    """Ярлык вне набора канона — поведение как раньше (без изменений)."""
    assert resolve_mqs_tier_label(70.0, "excellent") == "Хорошее"
    assert resolve_mqs_tier_label(70.0, None) == "Хорошее"


def test_findings_card_rejects_canon_label_mismatched_with_score():
    """Интеграционно: карточка findings берёт уровень из балла, когда пришедший
    ярлык из канона, но противоречит баллу — не эхом чужого текста."""
    from aurora_html.sections import render_at_a_glance

    p = _payload_with_score(42)
    p["diagnostics"]["mqs_tier_label"] = "Отличное"  # канон-ярлык, но не для 42
    html = render_at_a_glance(_html_ctx(p))

    assert "Слабое" in html, "уровень 42/100 обязан читаться как «Слабое» (канон)"
    assert "Отличное" not in html, (
        "чужой (пусть и канонический) ярлык «Отличное» не должен доехать до "
        "клиента при балле 42 - карточка обязана посчитать уровень сама"
    )
