"""M-5 (аудит s55, AUDIT_s55_257.md): у всех каналов mROAS ≤ 0 – слайд
«mROAS по каналам» строил диаграмму без категорий, python-pptx падал
«chart data contains no categories», и выгрузка PPTX не строилась вовсе
(HTML того же набора строился). Дефект был и до 2.5.7 (`a9234fac`).

Стережём: (1) выгрузка строится, на слайде вместо диаграммы – надпись;
(2) при обычных данных диаграмма на месте;
(3) подпись к диаграмме «1.0× = безубыточность» – только при диаграмме
(L-3n, аудит s55: висела над надписью).
"""
from __future__ import annotations

import copy
import json
import os

from aurora_pptx.builder import AuroraPPTXBuilder

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")
_TITLE = "MROAS ПО КАНАЛАМ / МУЛЬТИПЛИКАТОР"
_NOTE = "Ни у одного канала нет положительной отдачи"
_BREAKEVEN = "безубыточность"


def _payload() -> dict:
    with open(_FIXTURE, encoding="utf-8") as f:
        return copy.deepcopy(json.load(f))


def _mroas_slide(prs):
    for slide in prs.slides:
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if any(_TITLE in t for t in texts):
            return slide, texts
    return None, []


def test_all_channels_nonpositive_mroas_builds_with_note():
    p = _payload()
    assert p["channels"]
    for c in p["channels"]:
        c["mroas"] = -0.35
        c["ci_low"] = -1.2
        c["ci_high"] = -0.05
    prs = AuroraPPTXBuilder(p).build()
    slide, texts = _mroas_slide(prs)
    assert slide is not None
    assert any(_NOTE in t for t in texts)
    assert not any(sh.has_chart for sh in slide.shapes)
    assert not any(_BREAKEVEN in t for t in texts)


def test_positive_mroas_keeps_chart():
    prs = AuroraPPTXBuilder(_payload()).build()
    slide, texts = _mroas_slide(prs)
    assert slide is not None
    assert any(sh.has_chart for sh in slide.shapes)
    assert not any(_NOTE in t for t in texts)
    assert any(_BREAKEVEN in t for t in texts)
