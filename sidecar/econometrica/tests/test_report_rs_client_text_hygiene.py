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
    """Строки report.rs ДО `#[cfg(test)]` — только код, идущий в сборку
    продукта, не Rust unit-тесты в конце файла."""
    if not os.path.isfile(_REPORT_RS):
        return []
    with open(_REPORT_RS, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for line in lines:
        if line.strip().startswith("#[cfg(test)]"):
            break
        out.append(line)
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
    for lineno, line in enumerate(_production_source_lines(), start=1):
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


# Спорные находки (2026-07-25) — НЕ исключения в regex (не ослабляем правило),
# конкретные строки помечены поимённо и оставлены на решение Антона:
#
# 1) "Лифт vs baseline" (Сценарии/forecast-сравнение) — здесь "baseline"
#    обозначает не MMM-компонент органического спроса (как в "Данные"-листе,
#    который уже переименован в "Базовый спрос"), а сценарий/бюджет сравнения
#    в прогнозе. Неверный перевод хуже отсутствия перевода — нужен домен-контекст.
_KNOWN_BASELINE_SPORNY_LINES = {1657}
#
# 2) "Adstock (geometric)"/"Adstock (Weibull)" — строки таблицы
#    transformations на листе «Спецификация модели»: технический
#    методологический ярлык рядом с формулами (та же строка, что и формулы
#    Hill/Adstock), не клиентская проза. Аналогичная развилка есть в HTML
#    (глоссарий) — решение по расширению исключения тоже за Антоном.
_KNOWN_ADSTOCK_SPORNY_LINES = {135, 136}


def test_rs_report_no_em_dash():
    v = _collect_violations()
    assert not v["em_dash"], f"П8-1: em-dash в report.rs (production): {v['em_dash']}"


def test_rs_report_no_media_latin():
    v = _collect_violations()
    assert not v["media_latin"], f"П8-2: latin media- в report.rs (production): {v['media_latin']}"


def test_rs_report_no_bare_baseline():
    v = _collect_violations()
    unexpected = [(ln, lit) for ln, lit in v["baseline"] if ln not in _KNOWN_BASELINE_SPORNY_LINES]
    assert not unexpected, f"П8-2: голый baseline в report.rs (production, DISPLAY-текст): {unexpected}"
    known = [(ln, lit) for ln, lit in v["baseline"] if ln in _KNOWN_BASELINE_SPORNY_LINES]
    if known:
        pytest.xfail(
            f"Спорная находка («Лифт vs baseline» — не MMM-компонент, а "
            f"forecast-сравнение, перевод нужно уточнить у Антона): {known}"
        )


def test_rs_report_bare_adstock_known_or_none():
    v = _collect_violations()
    unexpected = [(ln, lit) for ln, lit in v["adstock"] if ln not in _KNOWN_ADSTOCK_SPORNY_LINES]
    assert not unexpected, f"П8-2: НОВЫЙ голый adstock в report.rs (production): {unexpected}"
    known = [(ln, lit) for ln, lit in v["adstock"] if ln in _KNOWN_ADSTOCK_SPORNY_LINES]
    if known:
        pytest.xfail(
            f"Спорная находка (спец-таблица transformations, не проза): {known}"
        )


def test_rs_report_coverage_is_reported():
    """Печатает и проверяет ФАКТ охвата — числом, не на глаз."""
    v = _collect_violations()
    summary = (
        f"ОХВАТ Rust XLSX (report.rs, production-код до #[cfg(test)]): "
        f"строк со строковыми литералами проверено {v['checked_lines']}; "
        f"известные спорные строки (baseline) {sorted(_KNOWN_BASELINE_SPORNY_LINES)}, "
        f"(adstock) {sorted(_KNOWN_ADSTOCK_SPORNY_LINES)}"
    )
    print(summary)
    assert v["checked_lines"] > 100, (
        "report.rs: строковых литералов почти не найдено — либо файл переехал, "
        "либо проверка сломана (см. _REPORT_RS путь)"
    )
