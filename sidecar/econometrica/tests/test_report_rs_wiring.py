"""Сторож ПРОВОДКИ перенесённых функций отчёта: вызываются ли они вообще.

Найдено внешним аудитом 2026-08-04 и подтверждено лично. Шесть функций,
возвращённых в `report.rs` при сведении веток, покрыты собственными
юнит-тестами — но НИКТО не проверял, что они реально вызываются из сборщиков
отчёта. Проба: обезвредить проводку (заменить вызовы на исходные значения) —
и **363 теста из 363 остаются зелёными**. Аудитор снял разом семь мутаций
(все шесть функций плюс ветка глоссария) и получил 357 зелёных из 363:
покраснели только собственные юнит-тесты функций, ни один сборщик не заметил.

🔴 Класс дефекта известен этой линии под именем Ф-04: «вынесенная функция
покрыта, а её вызов — нет». Практическое следствие: любой рефакторинг может
молча выбросить вызов, набор останется зелёным, а клиент получит грязные имена
каналов, ROI без пометки «н/д», отчёт без плашки надёжности и без метки режима
анализа — ровно то, ради чего функции и возвращали.

Сторож структурный и дешёвый: берёт тела `build_markdown` и `build_xlsx` из
ПРОДАКШН-части файла и требует, чтобы каждая функция там упоминалась как вызов.

Область строго ограничена кодом продукта: исходник обрезается по `#[cfg(test)]`.
Иначе сторож находит образцы в тексте Rust-тестов и остаётся зелёным при
полностью вырезанной проводке — в этой линии ловушка срабатывала дважды.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RUST = Path(__file__).resolve().parents[3] / "src-tauri" / "src" / "commands" / "report.rs"


def _product_code() -> str:
    src = _RUST.read_text(encoding="utf-8")
    marker = src.find("#[cfg(test)]")
    return src if marker == -1 else src[:marker]


def _fn_body(code: str, name: str) -> str:
    """Тело функции от её сигнатуры до начала следующей функции верхнего уровня.

    Границу ищем по строкам, а не байтовым срезом фиксированной длины: в файле
    кириллица, и срез разрубает многобайтовый символ (в этой линии такое уже
    роняло сторож паникой).
    """
    lines = code.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(pub\s+)?(async\s+)?fn\s+{re.escape(name)}\b", line):
            start = i
            break
    if start is None:
        return ""
    for j in range(start + 1, len(lines)):
        if re.match(r"^(pub\s+)?(async\s+)?fn\s+\w+", lines[j]):
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


# функция → в каких сборщиках обязана вызываться → что теряет клиент без вызова
_WIRING = [
    ("clean_label", ("build_markdown", "build_xlsx"),
     "имена каналов из Excel приходят с переносами строк и рвут текст отчёта"),
    ("reliability_label", ("build_markdown", "build_xlsx"),
     "в XLSX и Markdown пропадает плашка надёжности модели"),
    ("verdict_display", ("build_markdown", "build_xlsx"),
     "вердикт по каналу перестаёт смягчаться при ненадёжной модели"),
    ("analysis_mode_label", ("build_markdown", "build_xlsx"),
     "исчезает метка режима анализа — долю вклада принимают за ROI"),
    ("kpi_kind_label", ("build_markdown", "build_xlsx"),
     "исчезает метка типа KPI (денежный или количественный)"),
    ("roi_unreliable", ("build_markdown", "build_xlsx"),
     "битый ROI снова подаётся числом вместо «н/д» (нарушение INV-50)"),
]


@pytest.mark.parametrize(
    "func,builders,consequence",
    _WIRING,
    ids=[w[0] for w in _WIRING],
)
def test_function_is_wired_into_builders(
    func: str, builders: tuple[str, ...], consequence: str
) -> None:
    """Функция обязана вызываться из каждого сборщика, а не просто существовать."""
    code = _product_code()

    assert re.search(rf"^\s*fn\s+{re.escape(func)}\b", code, re.M), (
        f"функция {func} исчезла из продакшн-кода report.rs"
    )

    for builder in builders:
        body = _fn_body(code, builder)
        assert body, f"сборщик {builder} не найден в report.rs — разметка файла переехала"
        assert re.search(rf"\b{re.escape(func)}\s*\(", body), (
            f"{builder} больше НЕ ВЫЗЫВАЕТ {func}. Юнит-тест самой функции этого не "
            f"заметит — она цела, просто её никто не зовёт. Следствие для клиента: "
            f"{consequence}."
        )


def test_glossary_branch_is_wired_into_xlsx() -> None:
    """Лист «Глоссарий» обязан читать переданный список, а не только запасной.

    Проверяем не наличие параметра (это делает сторож паритета шва), а именно
    ветвление: параметр может приехать и остаться неиспользованным.
    """
    body = _fn_body(_product_code(), "build_xlsx")
    assert body, "build_xlsx не найден"
    assert "glossary" in body, (
        "build_xlsx не упоминает glossary: переданные с фронта 50 терминов "
        "игнорируются, лист собирается из запасных 11."
    )
    assert re.search(r"glossary\s*(\.|\))", body) or "as_array" in body, (
        "параметр glossary в build_xlsx есть, но не разыменовывается — значит "
        "ветка чтения переданных терминов мертва, работает только запасная."
    )
