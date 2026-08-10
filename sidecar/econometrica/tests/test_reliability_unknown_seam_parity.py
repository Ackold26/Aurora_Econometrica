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
_SECTIONS = _ROOT / "sidecar" / "econometrica" / "aurora_html" / "sections.py"


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
    return _rust_const("RELIABILITY_UNKNOWN_TEXT")


def _rust_const(name: str) -> str:
    src = _RUST.read_text(encoding="utf-8")
    match = re.search(rf'{name}: &str = "((?:[^"\\]|\\.)*)";', src)
    assert match, (
        f"{name} не найдена в report.rs - шов оборван на Rust-конце"
    )
    return match.group(1)


def _python_fallback_texts() -> tuple[str, str]:
    """Запасные тексты uncertain/unreliable из sections.py::
    _reliability_disclaimer_html - в отличие от RELIABILITY_UNKNOWN_NOTE это
    не именованные константы, а inline-литералы `note = "..."` внутри
    `if verdict_str == "unreliable": ... else: ...` (единственное место в
    Python-дереве, см. grep sidecar/econometrica/aurora_html/sections.py).
    Возвращает (unreliable_text, uncertain_text)."""
    src = _SECTIONS.read_text(encoding="utf-8")
    match = re.search(
        r'if verdict_str == "unreliable":\s*\n\s*note = "((?:[^"\\]|\\.)*)"'
        r'\s*\n\s*else:\s*\n\s*note = "((?:[^"\\]|\\.)*)"',
        src,
    )
    assert match, (
        "запасные тексты uncertain/unreliable не найдены в "
        "sections.py::_reliability_disclaimer_html - шов оборван на Python-конце"
    )
    return match.group(1), match.group(2)


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


# ── Расширение (находка внешнего аудита, 2026-08-10): гейт `!mr_label.is_empty()
# && !mr_caveat.is_empty()` в report.rs гасил ВСЮ плашку и для verdict ==
# "unreliable"/"uncertain" без собственного caveat_text - заголовок уже был
# непуст, а запасного текста не было ни у кого, кроме "unknown". HTML/PPTX на
# тех же данных печатают запасной текст (sections.py, ветки note = ... ниже),
# Markdown/XLSX молчали. Fallback теперь заведён и в Rust
# (RELIABILITY_UNRELIABLE_FALLBACK_TEXT / RELIABILITY_UNCERTAIN_FALLBACK_TEXT) -
# сторожа ниже держат побайтовый паритет тем же способом, что и unknown-текст
# выше.


def test_reliability_unreliable_fallback_matches_byte_for_byte() -> None:
    python_text, _ = _python_fallback_texts()
    rust_text = _rust_const("RELIABILITY_UNRELIABLE_FALLBACK_TEXT")
    assert python_text == rust_text, (
        "запасной текст оговорки verdict==\"unreliable\" разошёлся между "
        f"Python (aurora_html/sections.py) и Rust "
        f"(report.rs::RELIABILITY_UNRELIABLE_FALLBACK_TEXT):\n"
        f"Python: {python_text!r}\n"
        f"Rust:   {rust_text!r}"
    )


def test_reliability_uncertain_fallback_matches_byte_for_byte() -> None:
    _, python_text = _python_fallback_texts()
    rust_text = _rust_const("RELIABILITY_UNCERTAIN_FALLBACK_TEXT")
    assert python_text == rust_text, (
        "запасной текст оговорки verdict==\"uncertain\" разошёлся между "
        f"Python (aurora_html/sections.py) и Rust "
        f"(report.rs::RELIABILITY_UNCERTAIN_FALLBACK_TEXT):\n"
        f"Python: {python_text!r}\n"
        f"Rust:   {rust_text!r}"
    )


def test_reliability_fallback_texts_use_short_dash_not_em_dash() -> None:
    for name in ("RELIABILITY_UNRELIABLE_FALLBACK_TEXT", "RELIABILITY_UNCERTAIN_FALLBACK_TEXT"):
        text = _rust_const(name)
        assert "–" in text, f"{name}: текст обязан нести короткое тире «–» (U+2013)"
        assert "—" not in text, f"{name}: длинное тире «—» запрещено в клиентском тексте"
