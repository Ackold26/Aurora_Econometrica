"""Длинное тире не может быть заглушкой отсутствующего значения.

Отчётный гейт гигиены текста (`test_report_text_hygiene::EM_DASH_RE`) ищет
тире С ПРОБЕЛАМИ (`" — "`), а интерфейсный и Rust-гейт — любое тире. Из-за этой
асимметрии ячейка со значением «—» проходила отчётную проверку незамеченной:
формально это не пунктуация, а заглушка, и правило клиентской типографики на
неё не срабатывало (внешний аудит седьмой волны, 2026-07-26).

Что именно стережём. Ровно литерал-заглушку — строку, которая ЦЕЛИКОМ состоит
из длинного тире. Пунктуационные тире внутри фраз этот гейт не трогает: они
часть более длинного литерала и остаются предметом отдельной волны, объявленной
в компромиссах блока. Узкая формулировка выбрана намеренно — широкая покрасила
бы сотни мест и была бы заглушена, как это уже случалось с проверкой стиля.

Почему заглушка тире — дефект, а не косметика: клиент видит форму значения там,
где значения нет, и не может отличить «не считали» от «посчитали и получили
прочерк». То же правило, что «нет числа — нет подписи», только в профиль.
Честная отметка отсутствия — «н/д».
"""
import io
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDECAR = os.path.dirname(_HERE)

# Слои представления, которые собирают клиентские артефакты.
_LAYERS = ("aurora_html", "aurora_pptx")

# Литерал, состоящий ЦЕЛИКОМ из длинного тире (в одинарных или двойных кавычках).
_PLACEHOLDER_RE = re.compile(r"""(['"])—\1""")

# Узаконенные исключения — ПО ТЕКСТУ СТРОКИ, а не по номеру: номера сползают
# при любой правке файла. Каждая запись обязана нести обоснование рядом.
_LEGITIMISED: tuple[str, ...] = (
    # сюда — только то, где тире действительно не заглушка значения
)


def _python_files():
    out = []
    for layer in _LAYERS:
        root = os.path.join(_SIDECAR, layer)
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.endswith(".py"):
                    out.append(os.path.join(dirpath, name))
    return sorted(out)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def test_no_em_dash_placeholder_literals():
    files = _python_files()
    # Страховка от тихого нуля: пустой список входов — КРАСНЫЙ, а не «чисто».
    assert len(files) >= 3, (
        f"просмотрено файлов слоя представления: {len(files)} — каталог переехал "
        f"или сканирование сломано"
    )

    offenders = []
    scanned_lines = 0
    for path in files:
        for i, line in enumerate(io.open(path, encoding="utf-8"), start=1):
            scanned_lines += 1
            if _is_comment(line):
                continue
            if any(lit in line for lit in _LEGITIMISED):
                continue
            if _PLACEHOLDER_RE.search(line):
                rel = os.path.relpath(path, _SIDECAR)
                offenders.append(f"{rel}:{i}: {line.strip()[:110]}")

    assert scanned_lines > 1000, (
        f"просмотрено строк: {scanned_lines} — чтение файлов сломано"
    )
    assert not offenders, (
        "длинное тире как заглушка отсутствующего значения — клиент видит форму "
        "значения там, где значения нет. Ставьте честную отметку «н/д»:\n"
        + "\n".join(offenders)
    )
