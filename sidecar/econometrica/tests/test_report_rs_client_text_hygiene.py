"""Лёгкая проверка гигиены клиентского текста для многолистовой XLSX-таблицы.

Фаза 3 (2026-07-25): третий стек экспортных файлов (после HTML — см.
test_report_text_hygiene.py) — многолистовый Excel-отчёт собирается в Rust,
не в Python (src-tauri/src/commands/report.rs, команда export_report_xlsx).
До этой правки он не был покрыт НИКЕМ — ни одним тестом, ни python-скриптом.

Полноценный разбор Rust (AST/синтаксис) здесь избыточен ("лёгкая проверка"
по заданию Фазы 3). Достаточно строковых образцов на ТЕ ЖЕ 4 правила, что
уже приняты для HTML/PPTX (П8-1: нет em-dash; П8-2: нет голого baseline,
голого media-, голого adstock без скобок) — механика открытия и regex
сознательно не копирует Python-реализацию 1:1 (другой язык, другая форма
строковых литералов), но проверяет тот же смысл.

Область строго ограничена ПРОДАКШН-кодом файла — до `#[cfg(test)]`. Rust
unit-тесты в этом же файле строят внутренние JSON-фикстуры и сравнивают
экспортированные значения ("baseline" как ключ роли, "role" == "baseline")
— это не клиентский текст, а внутренний контракт данных.
"""
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# sidecar/econometrica/tests/ → ../../../src-tauri/src/commands/report.rs
_REPORT_RS = os.path.abspath(os.path.join(
    _HERE, "..", "..", "..", "src-tauri", "src", "commands", "report.rs",
))

EM_DASH_RE = re.compile(r"—")
STRING_LIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_LINE_COMMENT_RE = re.compile(r"^\s*//")

BASELINE_WORD_RE = re.compile(r"\bbaseline\b", re.IGNORECASE)
MEDIA_LATIN_RE = re.compile(r"\bmedia-", re.IGNORECASE)
ADSTOCK_WORD_RE = re.compile(r"\badstock\b", re.IGNORECASE)
# Зеркалит _has_bare_adstock_in_client_text из test_report_text_hygiene.py:
# "(adstock)" wrapped и "adstock(" formula-контекст — не нарушение.
_BARE_ADSTOCK_RE = re.compile(r"(?<!\()\badstock\b(?!\))", re.IGNORECASE)


def _production_source_lines() -> list[str]:
    """Строки report.rs без тестовых модулей — только код, идущий в сборку.

    2026-07-26: прежняя версия обрывала чтение на ПЕРВОМ `#[cfg(test)]` и
    молча теряла весь остаток файла. Сейчас тестовый модуль в этом файле
    один и стоит в конце, поэтому вреда не было, — но появись
    вспомогательный тестовый модуль в середине, охват сузился бы без единого
    слова, а сужение читается как «проверено всё». Теперь пропускается ровно
    тело каждого `#[cfg(test)]`-модуля (по глубине фигурных скобок), а код
    после него снова проверяется. Возвращаются пары (номер строки, строка),
    чтобы номера оставались верными после пропусков.
    """
    if not os.path.isfile(_REPORT_RS):
        return []
    with open(_REPORT_RS, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("#[cfg(test)]"):
            # Найти открывающую скобку модуля и пройти его целиком.
            depth = 0
            opened = False
            while i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                if "{" in lines[i]:
                    opened = True
                i += 1
                if opened and depth <= 0:
                    break
            continue
        out.append((i + 1, lines[i]))
        i += 1
    return out


def _string_literals(line: str) -> list[str]:
    """Строковые литералы одной строки кода, комментарии исключены."""
    if _LINE_COMMENT_RE.match(line):
        return []
    if "//" in line:
        before, after = line.split("//", 1)
        # Осторожно: не резать URL/строки с "//" внутри литерала — если
        # после "//" на строке нет открывающей кавычки, считаем что это
        # реальный line-comment хвост и отрезаем его.
        if '"' not in after:
            line = before
    return STRING_LIT_RE.findall(line)


def _collect_violations():
    em_dash_hits, baseline_hits, media_hits, adstock_hits = [], [], [], []
    checked_lines = 0
    for lineno, line in _production_source_lines():
        lits = _string_literals(line)
        if not lits:
            continue
        checked_lines += 1
        for lit in lits:
            if EM_DASH_RE.search(lit):
                em_dash_hits.append((lineno, lit))
            # Точное нижнерегистровое совпадение — внутренний data-key
            # (role == "baseline", ts.get("baseline")), не клиентский текст.
            if BASELINE_WORD_RE.search(lit) and lit.strip() != "baseline":
                baseline_hits.append((lineno, lit))
            if MEDIA_LATIN_RE.search(lit):
                media_hits.append((lineno, lit))
            if ADSTOCK_WORD_RE.search(lit):
                # headword-строка (глоссарий-стиль "Adstock" ровно) —
                # тот же прецедент, что уже разрешён в HTML-глоссарии.
                if lit.strip() == "Adstock":
                    continue
                if _BARE_ADSTOCK_RE.search(lit):
                    adstock_hits.append((lineno, lit))
    return {
        "checked_lines": checked_lines,
        "em_dash": em_dash_hits,
        "baseline": baseline_hits,
        "media_latin": media_hits,
        "adstock": adstock_hits,
    }


# Узаконенные термины (решение владельца 2026-07-26): принятые обозначения
# отрасли остаются как есть, механический перевод читался бы хуже и разошёлся
# бы с литературой. Реестр — по ТЕКСТУ литерала, а НЕ по номеру строки:
# номера сползают при первой же правке report.rs и исключение молча
# перестаёт совпадать (либо начинает прикрывать чужую строку).
_LEGITIMISED_LITERALS = {
    "Лифт vs baseline": (
        "лист «Сценарии»: baseline здесь — сценарий сравнения в прогнозе, а не "
        "MMM-компонент органического спроса (тот уже назван «Базовый спрос»)"
    ),
    "Adstock (geometric)": (
        "лист «Спецификация модели», таблица преобразований: методологический "
        "ярлык рядом с формулой, не клиентская проза"
    ),
    "Adstock (Weibull)": (
        "лист «Спецификация модели», таблица преобразований: методологический "
        "ярлык рядом с формулой, не клиентская проза"
    ),
}


def test_rs_report_no_em_dash():
    v = _collect_violations()
    assert not v["em_dash"], f"П8-1: em-dash в report.rs (production): {v['em_dash']}"


def test_rs_report_no_media_latin():
    v = _collect_violations()
    assert not v["media_latin"], f"П8-2: latin media- в report.rs (production): {v['media_latin']}"


def test_rs_report_no_bare_baseline():
    v = _collect_violations()
    unexpected = [
        (ln, lit) for ln, lit in v["baseline"]
        if lit.strip() not in _LEGITIMISED_LITERALS
    ]
    assert not unexpected, f"П8-2: голый baseline в report.rs (production, DISPLAY-текст): {unexpected}"


def test_rs_report_no_bare_adstock():
    v = _collect_violations()
    unexpected = [
        (ln, lit) for ln, lit in v["adstock"]
        if lit.strip() not in _LEGITIMISED_LITERALS
    ]
    assert not unexpected, f"П8-2: НОВЫЙ голый adstock в report.rs (production): {unexpected}"


def test_legitimised_literals_are_all_alive():
    """Узаконенный литерал обязан существовать в файле.

    Иначе исключение переживает собственный повод (строку переименовали, а
    разрешение осталось) и молча прикрывает будущее нарушение с тем же текстом.
    """
    v = _collect_violations()
    present = {lit.strip() for _, lit in v["baseline"] + v["adstock"]}
    dead = sorted(set(_LEGITIMISED_LITERALS) - present)
    assert not dead, (
        f"узаконенные литералы больше не встречаются в report.rs {dead} — "
        f"повод исчез, удалить запись из _LEGITIMISED_LITERALS"
    )


def test_rs_report_coverage_is_reported():
    """Печатает и проверяет ФАКТ охвата — числом, не на глаз."""
    v = _collect_violations()
    summary = (
        f"ОХВАТ Rust XLSX (report.rs, production-код до #[cfg(test)]): "
        f"строк со строковыми литералами проверено {v['checked_lines']}; "
        f"узаконенных терминов {len(_LEGITIMISED_LITERALS)} — "
        f"{sorted(_LEGITIMISED_LITERALS)}"
    )
    print(summary)
    assert v["checked_lines"] > 100, (
        "report.rs: строковых литералов почти не найдено — либо файл переехал, "
        "либо проверка сломана (см. _REPORT_RS путь)"
    )
