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
from utils.diagnostics import mqs_tier_info

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
