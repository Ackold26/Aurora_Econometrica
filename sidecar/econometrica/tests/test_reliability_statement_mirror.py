"""Сторож шва: фраза о применимости результата звучит одинаково в Python и Rust.

`utils/diagnostics.py::RELIABILITY_STATEMENT_REFUSED` — единый источник. Rust не
импортирует Python и собирает Markdown и XLSX сам, поэтому синхрон держится
строкой в `src-tauri/src/commands/report.rs`. Тот же приём и та же опасность,
что у оговорки о тонких данных: в августе 2026 Python-сторону переписали, Rust
остался прежним, и клиент получал в XLSX одну формулировку, а в HTML и PPTX
другую. Сторожа тогда не существовало — только комментарии, обещавшие защиту.

Здесь сверка ПОБАЙТОВАЯ, а не «по смыслу»: в строке нет плейсхолдеров формата и
нет чисел, смягчать нечего. Любая правка одной стороны валит проверку сразу.

Второй инвариант, который держит этот файл: **утверждение о надёжности в Rust
не печатается без проверки признака отказа**. Это и есть сигнатура класса
дефекта, ради которого всё делалось — структурная проверка ловит рецидив в
коде, а не только текущее поведение.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_RUST = _ROOT / "src-tauri" / "src" / "commands" / "report.rs"
_JS = _ROOT / "src" / "lib" / "mqs-tiers.js"
_SIDECAR = _ROOT / "sidecar" / "econometrica"

if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

#: Положительные утверждения о применимости в клиентском тексте Rust. Каждое
#: обязано стоять под проверкой признака отказа.
_RUST_ENDORSEMENTS = (
    "результаты модели надёжны для принятия решений",
    "результаты пригодны для ориентировки",
)


def _product_code() -> str:
    """Исходник Rust без тестового модуля — сторож ищет только в коде продукта.

    🔴 Обрезка обязательна: иначе проверка находит образцы в Rust-тестах и
    остаётся зелёной при вырезанной проводке. В этой линии ловушка срабатывала.
    """
    src = _RUST.read_text(encoding="utf-8")
    marker = src.find("#[cfg(test)]")
    return src if marker == -1 else src[:marker]


def _rust_statement() -> str:
    code = _product_code()
    match = re.search(
        r'const\s+RELIABILITY_STATEMENT_REFUSED:\s*&str\s*=\s*"([^"]+)"\s*;', code
    )
    if not match:
        pytest.fail(
            "в report.rs нет константы RELIABILITY_STATEMENT_REFUSED — зеркало "
            "единого источника исчезло, клиент получит в Markdown и XLSX текст, "
            "отличный от программы, веб-отчёта и презентации"
        )
    return match.group(1)


def _js_statement() -> str:
    """Зеркало интерфейса. Программа Python тоже не импортирует — сторон три.

    Найдено финальным приёмом задачи 2026-08-09: панель выводов
    (`src/lib/insights-rules.js`) выводила «Результаты надёжны для принятия
    решений» из одной ступени MQS, и слова «refused» в файле не встречалось
    вовсе. Это была двенадцатая поверхность — её не было в исходной карте мест.
    """
    code = _JS.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+const\s+RELIABILITY_STATEMENT_REFUSED\s*=\s*'([^']+)'\s*;", code
    )
    if not match:
        pytest.fail(
            "в src/lib/mqs-tiers.js нет константы RELIABILITY_STATEMENT_REFUSED — "
            "панель выводов останется без согласованной фразы, и программа снова "
            "будет обещать надёжность там, где оптимизатор отказывает"
        )
    return match.group(1)


def test_rust_mirrors_python_statement_verbatim() -> None:
    from utils.diagnostics import RELIABILITY_STATEMENT_REFUSED  # noqa: PLC0415

    rust = _rust_statement()
    assert rust == RELIABILITY_STATEMENT_REFUSED, (
        "фраза о применимости разошлась между Python и Rust — клиент получит "
        "РАЗНЫЙ текст по одной модели в разных форматах.\n"
        f"  Python: {RELIABILITY_STATEMENT_REFUSED}\n"
        f"  Rust:   {rust}\n"
        "Единый источник — utils/diagnostics.py::RELIABILITY_STATEMENT_REFUSED, "
        "правьте его и зеркальте в report.rs."
    )


@pytest.mark.parametrize("phrase", _RUST_ENDORSEMENTS)
def test_rust_endorsements_are_gated_by_refusal(phrase: str) -> None:
    """Сигнатура класса дефекта: утверждение о надёжности без проверки отказа.

    Проверяем структурно: рядом с каждым положительным утверждением о
    применимости обязана стоять развилка по признаку отказа. Окно намеренно
    узкое — если утверждение вынесут из-под развилки, оно из окна выпадет.
    """
    lines = _product_code().splitlines()
    hits = [i for i, line in enumerate(lines) if phrase in line]
    assert hits, (
        f"в клиентском тексте report.rs больше нет строки «{phrase}» — если её "
        "переформулировали, обновите список в этом стороже, иначе проверка "
        "станет пустой и перестанет что-либо значить"
    )
    for i in hits:
        window = "\n".join(lines[max(0, i - 6):i + 1])
        assert "mr_refused" in window, (
            f"утверждение «{phrase}» (строка {i + 1} report.rs) печатается без "
            "проверки признака отказа — это ровно тот дефект, который чинили: "
            "при несошедшемся расчёте отчёт одновременно отключает переброску и "
            "обещает надёжность."
        )


def test_js_mirrors_python_statement_verbatim() -> None:
    from utils.diagnostics import RELIABILITY_STATEMENT_REFUSED  # noqa: PLC0415

    js = _js_statement()
    assert js == RELIABILITY_STATEMENT_REFUSED, (
        "фраза о применимости разошлась между Python и интерфейсом — клиент "
        "увидит на экране одно, а в отчёте другое по одной и той же модели.\n"
        f"  Python:    {RELIABILITY_STATEMENT_REFUSED}\n"
        f"  Интерфейс: {js}\n"
        "Единый источник — utils/diagnostics.py::RELIABILITY_STATEMENT_REFUSED."
    )


def _strip_js_comments(code: str) -> str:
    """Код без комментариев.

    🔴 Обязательный шаг, иначе сторож ловит объяснение вместо дефекта. При
    написании этого файла ловушка сработала немедленно: в комментариях рядом с
    починкой процитирован прежний текст — и проверка покраснела на собственном
    пояснении. Тот же класс, что уже описан в test_thinness_caveat_mirror.py.
    """
    # Номера строк сохраняем: блочный комментарий заменяем на столько же
    # переводов строки, сколько в нём было. Иначе окно поиска съезжает и
    # сторож краснеет не по адресу (наступила на это при написании).
    code = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), code, flags=re.S)
    return re.sub(r"//[^\n]*", " ", code)


def test_js_endorsement_is_gated_by_refusal() -> None:
    """Панель выводов: «Результаты надёжны» не выводится из одной ступени MQS.

    Область проверки — именно утверждения, выведенные из ПОКАЗАТЕЛЯ КАЧЕСТВА
    (в одной строке с MQS). Соседняя строка про идеальную сходимость
    («R-hat 1.00, дивергенций 0 – результаты надёжны для оценки ROI») сюда не
    относится намеренно: она выведена из самой сходимости, а при R-hat ≤ 1.01 и
    нуле дивергенций отказ невозможен по построению, противоречия быть не может.

    До правки слова «refused» в файле не встречалось вовсе.
    """
    raw = (_ROOT / "src" / "lib" / "insights-rules.js").read_text(encoding="utf-8")
    assert "verdictRefuses" in raw, (
        "src/lib/insights-rules.js снова ничего не знает о признаке отказа — "
        "панель выводов выводит вердикт из одной ступени MQS"
    )
    lines = _strip_js_comments(raw).splitlines()
    hits = [
        i for i, line in enumerate(lines)
        if "Результаты надёжны" in line and ("mqs" in line.lower())
    ]
    assert hits, (
        "в insights-rules.js больше нет утверждений о надёжности, выведенных из "
        "показателя качества — если их переформулировали, обновите этого сторожа, "
        "иначе проверка станет пустой и перестанет что-либо значить"
    )
    for i in hits:
        # Окно щедрое (развилка отказа стоит выше объявления переменных и
        # ветки «оценка не посчитана»), но всё же ограниченное: если
        # утверждение вынесут из-под развилки в другую часть функции, оно из
        # окна выпадет. Поведенческую проверку держит vitest-сторож
        # src/lib/__tests__/insights-rules-refusal-honesty.test.js.
        window = "\n".join(lines[max(0, i - 30):i + 1])
        assert ("modelRefused" in window) or ("reportRefused" in window), (
            f"утверждение о надёжности (строка {i + 1} insights-rules.js) выведено "
            "из ступени MQS без проверки признака отказа — это ровно тот дефект: "
            "при несошедшемся расчёте программа отключает переброску и тут же "
            "обещает надёжность."
        )


def test_statement_is_client_grade_text_on_every_side() -> None:
    """Клиентская типографика зеркал: короткое тире, без длинного."""
    for name, text in (("report.rs", _rust_statement()), ("mqs-tiers.js", _js_statement())):
        assert "—" not in text, (
            f"длинное тире в клиентском тексте {name} — линтер продукта его валит"
        )
