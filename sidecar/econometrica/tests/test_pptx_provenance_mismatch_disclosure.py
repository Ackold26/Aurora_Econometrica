"""2026-08-07: предупреждение о разном происхождении данных в PPTX-отчёте.

Риск: переобучение не удаляет results/optimization.json — файл остаётся на
диске и воскресает при открытии проекта (src-tauri/src/commands/project.rs).
Тогда клиентский отчёт может тихо склеиться из ДВУХ моделей: живая
диагностика новой модели рядом с числами переброски бюджета старой.
Markdown/XLSX/HTML уже несут это предупреждение текстом
diagnostics["provenance_note"] при diagnostics["provenance_mismatch"]
(см. aurora_html.sections._reliability_disclaimer_html — тот же приём).
Этот тест — сторож для PPTX (aurora_pptx.builder.AuroraPPTXBuilder.s11_sources),
который прежде молчал.

Гейт: показ управляется ТОЛЬКО provenance_mismatch/provenance_note, а НЕ
honesty_verdict — модель может быть сколь угодно надёжной, но если
диагностика рядом посчитана на другой модели, предупреждение обязано
доехать всё равно.
"""
import json
import os

from aurora_pptx.builder import AuroraPPTXBuilder
from utils.diagnostics import PROVENANCE_MISMATCH_NOTE

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")


def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


def _payload(honesty_verdict, mismatch):
    with open(_FIXTURE, encoding="utf-8") as f:
        p = json.load(f)
    p["diagnostics"]["honesty_verdict"] = honesty_verdict
    if mismatch:
        p["diagnostics"]["provenance_mismatch"] = True
        p["diagnostics"]["provenance_note"] = PROVENANCE_MISMATCH_NOTE
    return p


def test_pptx_shows_provenance_note_when_mismatch_and_unreliable():
    p = _payload("unreliable", mismatch=True)
    txt = _pptx_text(AuroraPPTXBuilder(p).build())
    assert PROVENANCE_MISMATCH_NOTE in txt


def test_pptx_shows_provenance_note_when_mismatch_and_reliable():
    """Показ НЕ зависит от вердикта надёжности — доезжает и у надёжной модели."""
    p = _payload("reliable", mismatch=True)
    txt = _pptx_text(AuroraPPTXBuilder(p).build())
    assert PROVENANCE_MISMATCH_NOTE in txt


def test_pptx_no_provenance_note_when_no_mismatch():
    p = _payload("reliable", mismatch=False)
    txt = _pptx_text(AuroraPPTXBuilder(p).build())
    assert PROVENANCE_MISMATCH_NOTE not in txt
    assert "Разное происхождение данных" not in txt
