"""Сторож зеркала: оговорка о тонких данных звучит одинаково в Python и в Rust.

`utils/diagnostics.py::format_thinness_caveat` — единый источник формулировки
(INV-50 F-DELIVERABLE-1). Его докстринг прямо утверждает: «Rust XLSX зеркалит
дословно, см. report.rs», а комментарий в `report.rs` — «синхрон держим вручную
(тест сверяет)».

🔴 Такого теста НЕ СУЩЕСТВОВАЛО. Оба комментария обещали защиту, которой не
было, — класс «комментарий обещает больше, чем даёт защита».

Цена обнаружилась в тот же день (2026-08-04): Python-сторону переписали на тон
McElreath — «модель сильно опирается на априорные предположения, точечная
надёжность ограничена», — а Rust остался с прежним «высокий риск переобучения,
результаты ненадёжны». Клиент по одной и той же модели получал в HTML и PPTX
одну формулировку, а в XLSX другую, причём XLSX нёс ровно тот алармизм, от
которого сознательно отказались. Ни один гейт этого не увидел: Python-тесты
проверяли Python, Rust-тесты — Rust, а шов между ними не стерёг никто.

Сторож сравнивает не байты файлов, а СМЫСЛОВЫЕ ЯДРА обеих формулировок:
Rust-строка обязана содержать те же ключевые обороты, что и Python-эталон.
Форматирование числа и знаки препинания намеренно не сверяются дословно —
иначе сторож ломался бы от любой мелкой правки и его бы отключили.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_RUST = _ROOT / "src-tauri" / "src" / "commands" / "report.rs"
_SIDECAR = _ROOT / "sidecar" / "econometrica"

if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))


def _rust_product_code() -> str:
    """Исходник Rust без тестового модуля — сторож ищет только в коде продукта."""
    src = _RUST.read_text(encoding="utf-8")
    marker = src.find("#[cfg(test)]")
    return src if marker == -1 else src[:marker]


def _significant_words(text: str) -> set[str]:
    """Смысловые слова формулировки: без чисел, разметки и служебных частей."""
    lowered = text.lower()
    lowered = re.sub(r"\{[^}]*\}", " ", lowered)          # плейсхолдеры формата
    lowered = re.sub(r"[^а-яё\s]", " ", lowered)          # цифры, латиница, знаки
    stop = {"и", "в", "на", "а", "не", "что", "с", "к", "по", "из", "для", "же"}
    return {w for w in lowered.split() if len(w) > 3 and w not in stop}


def _python_variants() -> tuple[str, str]:
    from utils.diagnostics import format_thinness_caveat  # noqa: PLC0415

    critical = format_thinness_caveat(1.5, 10, leading_space=False)
    moderate = format_thinness_caveat(3.0, 10, leading_space=False)
    return critical, moderate


def _rust_variants() -> list[str]:
    code = _rust_product_code()
    return re.findall(r'format!\("(⚠ Данных[^"]+)"\)', code)


def test_rust_has_both_caveat_variants() -> None:
    """В Rust обязаны быть обе ветви оговорки — критическая и умеренная."""
    variants = _rust_variants()
    assert len(variants) >= 2, (
        f"в report.rs найдено {len(variants)} формулировок оговорки о тонких данных, "
        f"ожидается 2 (ratio < 2 и ratio < 4). Зеркало Python-эталона неполно."
    )


@pytest.mark.parametrize("idx,name", [(0, "критическая"), (1, "умеренная")])
def test_rust_mirrors_python_meaning(idx: int, name: str) -> None:
    """Смысловое ядро Rust-формулировки совпадает с Python-эталоном.

    Проверяем пересечение значимых слов: расхождение тона (алармизм против
    честного описания механизма) меняет их радикально и ловится сразу.
    """
    py_critical, py_moderate = _python_variants()
    py_text = (py_critical, py_moderate)[idx]
    rust_variants = _rust_variants()
    if len(rust_variants) <= idx:
        pytest.fail(f"в report.rs нет {name} ветви оговорки")

    py_words = _significant_words(py_text)
    rs_words = _significant_words(rust_variants[idx])
    missing = py_words - rs_words

    # Допускаем небольшое расхождение (перестановка, синоним падежа), но не смену тона.
    overlap = len(py_words & rs_words) / max(len(py_words), 1)
    assert overlap >= 0.7, (
        f"{name} оговорка в Rust разошлась с Python-эталоном: совпадение смысловых "
        f"слов {overlap:.0%}, не хватает {sorted(missing)[:6]}.\n"
        f"  Python: {py_text}\n"
        f"  Rust:   {rust_variants[idx]}\n"
        f"Клиент получит РАЗНЫЙ текст в XLSX и в HTML/PPTX по одной модели. "
        f"Единый источник — utils/diagnostics.py::format_thinness_caveat, правьте его "
        f"и зеркальте сюда."
    )


def _strip_comments(code: str) -> str:
    """Код без комментариев.

    🔴 Обязательный шаг, иначе сторож ловит объяснение вместо дефекта. При
    написании этого файла ловушка сработала немедленно: в комментарии рядом с
    починкой я перечислила обороты, от которых отказались, — и проверка
    покраснела на собственном пояснении. Тот же класс, что «сторож покраснел
    на своей же цитате прежнего кода».
    """
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    return re.sub(r"//[^\n]*", " ", code)


def test_rust_does_not_carry_abandoned_alarmism() -> None:
    """Отброшенные обороты не должны воскресать в клиентском тексте Rust.

    От формулировок про ненадёжность результатов и артефакт переобучения
    отказались сознательно (тон McElreath, Волна 1): они пугают, но не
    объясняют механизм. Проверяем ТОЛЬКО код без комментариев — в пояснениях
    эти обороты законны и нужны, чтобы правку не откатили по незнанию.
    """
    code = _strip_comments(_rust_product_code())
    for banned in ("результаты ненадёжны", "артефактом переобучения", "высокий риск переобучения"):
        assert banned not in code, (
            f"в клиентский текст report.rs вернулся отброшенный оборот «{banned}». "
            f"Единый источник формулировки — utils/diagnostics.py::"
            f"format_thinness_caveat, он описывает механизм, а не пугает."
        )
