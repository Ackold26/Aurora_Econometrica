"""Сторож паритета шва «текст плашки надёжности unknown»: Python <-> Rust.

Зачем нужен (решение владельца, 2026-08-10). Вердикт надёжности модели
"unknown" (проверка не выполнена / вердикт отсутствовал целиком) несёт
клиентский текст-предупреждение в ДВУХ независимых рендерерах:

- HTML/PPTX читают Python-константу utils.diagnostics.RELIABILITY_UNKNOWN_NOTE
  через Python-мост (aurora_html/sections.py, aurora_pptx/builder.py);
- Markdown/XLSX (Rust, src-tauri/src/commands/report.rs) читают results JSON
  напрямую, мимо Python-моста, и несут СВОЮ копию текста -
  RELIABILITY_UNKNOWN_TEXT.

Разошедшиеся копии значат, что клиент видит два разных объяснения одного и
того же предупреждения в разных форматах ОДНОГО проекта - тот же класс дефекта,
что и test_thinness_caveat_mirror.py / test_glossary_seam_parity.py в этом же
дереве. Сторож ловит расхождение побайтово, не полагаясь на глаза ревьюера.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DIAGNOSTICS = _ROOT / "sidecar" / "econometrica" / "utils" / "diagnostics.py"
_RUST = _ROOT / "src-tauri" / "src" / "commands" / "report.rs"


def _python_note() -> str:
    """Собрать значение RELIABILITY_UNKNOWN_NOTE из конкатенации строковых
    литералов Python (константа объявлена как `(...)` из нескольких строк
    в одинарных кавычках - типичный стиль переноса длинного клиентского
    текста в этом файле, см. PROVENANCE_MISMATCH_NOTE выше по файлу)."""
    src = _DIAGNOSTICS.read_text(encoding="utf-8")
    match = re.search(r"RELIABILITY_UNKNOWN_NOTE\s*=\s*\((.*?)\)\n", src, re.DOTALL)
    assert match, (
        "RELIABILITY_UNKNOWN_NOTE не найдена в diagnostics.py - шов оборван на "
        "Python-конце"
    )
    literals = re.findall(r"'((?:[^'\\]|\\.)*)'", match.group(1))
    assert literals, (
        "не удалось разобрать строковые литералы RELIABILITY_UNKNOWN_NOTE - "
        "формат объявления константы изменился"
    )
    return "".join(literals)


def _rust_text() -> str:
    src = _RUST.read_text(encoding="utf-8")
    match = re.search(r'RELIABILITY_UNKNOWN_TEXT: &str = "((?:[^"\\]|\\.)*)";', src)
    assert match, (
        "RELIABILITY_UNKNOWN_TEXT не найдена в report.rs - шов оборван на "
        "Rust-конце"
    )
    return match.group(1)


def test_reliability_unknown_text_matches_byte_for_byte() -> None:
    python_text = _python_note()
    rust_text = _rust_text()
    assert python_text == rust_text, (
        "текст плашки «Надёжность модели не подтверждена» разошёлся между "
        f"Python (utils.diagnostics.RELIABILITY_UNKNOWN_NOTE) и Rust "
        f"(report.rs::RELIABILITY_UNKNOWN_TEXT):\n"
        f"Python: {python_text!r}\n"
        f"Rust:   {rust_text!r}"
    )


def test_reliability_unknown_text_uses_short_dash_not_em_dash() -> None:
    # Клиентский текст: короткое тире «–» (U+2013), не длинное «—» (U+2014) -
    # линтер продукта валит длинное тире в клиентском тексте.
    text = _rust_text()
    assert "–" in text, "текст обязан нести короткое тире «–» (U+2013)"
    assert "—" not in text, "длинное тире «—» запрещено в клиентском тексте"
