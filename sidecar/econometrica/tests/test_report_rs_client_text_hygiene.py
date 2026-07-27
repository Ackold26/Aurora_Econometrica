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

Расширение 2026-07-27 (задача 4, единый источник порогов MQS в Rust):
  1. П8-3: голый литерал "N/A" в клиентском тексте — англицизм, честное
     отсутствие пишется по-русски ("н/д").
  2. Структурная дыра: наивный построчный разбор кавычек (`_join_continued_literals`)
     не понимал сырые строки Rust (`r"..."`, `r#"..."#`). Доказано боем: для
     `r#"...со "N/A кавычками" и текст"#` `_string_literals()` отдавал
     `['клиентский текст со ', ' и текст']` — средний фрагмент между
     вложенными кавычками ПОЛНОСТЬЮ выпадал из проверки, ни одно правило
     П8-1..П8-3 не видело текст внутри него. Тело каждой сырой строки теперь
     маскируется нейтральным символом ДО обычного построчного разбора
     (не мешает счёту кавычек соседних обычных литералов), а её содержимое
     проверяется отдельно, целиком, через `_extract_raw_strings()`.
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
# П8-3 (2026-07-27): "N/A" — англицизм в клиентском тексте, честное отсутствие
# по-русски — "н/д" (см. mqs_tiers::resolve_mqs_label и MQS_ABSENT_TEXT).
NA_LITERAL_RE = re.compile(r"\bN/A\b")

# П8-4 (2026-07-27): дефис-минус в роли ТИРЕ. Правило П8-1 стерегло только длинное
# тире, поэтому пунктуационная ошибка обратного знака была для него невидима: в
# клиентских строках стояло "Базовый спрос - часть KPI" вместо короткого тире «–»,
# и гейт годами оставался зелёным. Тот же корень, что у CPD-29: признак поиска
# (длинное тире) не совпадал с классом дефекта (неверный знак тире вообще).
#
# Правило узкое СОЗНАТЕЛЬНО — только дефис, окружённый пробелами, и только когда
# перед ним есть непробельный символ. Что этим НЕ задевается:
#   * маркер списка в начале литерала или строки ("- **Качество модели:** …") —
#     перед дефисом нет непробельного символа;
#   * составные слова и обозначения ("R-hat", "media-", "TRP/GRP");
#   * числовые диапазоны без пробелов ("0-100", "2.0x") — диапазон тоже стоило бы
#     писать тире, но там дефис встречается и в кодах/версиях, а замер показал
#     ноль настоящих находок этой формы: расширять правило на них — заводить шум
#     без пользы.
# Замер перед введением правила (2026-07-27): 14 срабатываний на production-коде
# report.rs, ВСЕ 14 — настоящие клиентские тире, ни одного ложного. Именно поэтому
# правило принято в гейт, а не оставлено точечной правкой 14 мест: класс закрыт.
SPACED_HYPHEN_RE = re.compile(r"(?<=\S) - (?=\S)")

# Сырая строка Rust: `r"..."` (0 решёток) или `r#"..."#`/`r##"..."##`/...
# (N решёток) — закрывается ПЕРВЫМ `"`, за которым идёт ровно N решёток.
# Незамкнутая группа `#*` жадная — верно берёт максимум решёток перед
# открывающей кавычкой, как того требует сама грамматика Rust.
#
# Негативный lookbehind ОБЯЗАТЕЛЕН: без него префикс `r"`/`r#"` ловится и
# ВНУТРИ обычных литералов, если те заканчиваются на букву "r" перед
# закрывающей кавычкой ("Inter" -> "...te" + "r\"" читается как начало сырой
# строки). Доказано боем при первом прогоне — 9 ложных совпадений вместо 1
# реальной сырой строки (see durable-отчёт). Настоящий префикс сырой строки
# в Rust — токен, ему не предшествует буква/цифра/подчёркивание. Кавычка `"`
# перед `r` тоже исключена: `"r"` (обычный литерал, содержимое — буква "r",
# как в таблице транслитерации) иначе читается как старт сырой строки —
# второй ложный случай, найденный тем же боевым прогоном.
RAW_STRING_RE = re.compile(r'(?<![A-Za-z0-9_"])r(#{0,8})"(.*?)"\1', re.DOTALL)


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


def _join_continued_literals(pairs):
    """Склеивает литерал, разорванный переносом строки, в одну логическую.

    2026-07-26 (внешний аудит, Medium): разбор шёл построчно, поэтому литерал,
    продолженный через `\\` в конце строки, не имел на своей строке закрывающей
    кавычки и не попадал в выборку ВООБЩЕ — вместе со всем своим текстом.
    Доказано боем: длинное тире, вставленное в клиентское предупреждение про
    ROAS (report.rs, строки 1750-1751), давало ноль находок при зелёном тесте.

    Признак продолжения — нечётное число неэкранированных кавычек в строке.
    Номер логической строки — номер ПЕРВОЙ физической, чтобы сообщение об
    ошибке указывало на начало литерала.
    """
    out = []
    buf_lineno = None
    buf = ""
    for lineno, line in pairs:
        stripped = line.rstrip("\n")
        if buf_lineno is None:
            buf_lineno, buf = lineno, stripped
        else:
            # Перенос внутри литерала: Rust отбрасывает `\` и ведущие пробелы.
            buf = buf.rstrip("\\") + stripped.lstrip()
        # Чётное число неэкранированных кавычек — литерал(ы) закрыты.
        quotes, esc = 0, False
        for ch in buf:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                quotes += 1
        if quotes % 2 == 0:
            out.append((buf_lineno, buf))
            buf_lineno, buf = None, ""
    if buf_lineno is not None:  # незакрытый хвост — отдаём как есть
        out.append((buf_lineno, buf))
    return out


def _mask_raw_strings(pairs):
    """Маскирует тело сырых строк Rust и отдаёт его отдельно для проверки.

    Сырые строки (`r"..."`, `r#"..."#`) не подчиняются правилам экранирования
    обычных строк — символ `"` внутри них не toggle'ит состояние "литерал
    открыт/закрыт" так, как это предполагает `_join_continued_literals`
    (посимвольный счёт НЕэкранированных кавычек). Если внутри сырой строки
    есть вложенная кавычка, наивный разбор рвёт содержимое на куски по этим
    вложенным кавычкам и часть текста МОЛЧА выпадает из проверки (доказано
    боем — см. докстринг модуля).

    Возвращает (замаскированные (lineno, line)-пары, [(lineno, содержимое)]).
    Маскирование заменяет ВЕСЬ матч сырой строки (включая `r`/`#`/кавычки)
    нейтральным символом, сохраняя переносы строк — число и порядок строк
    не меняются, обычный конвейер (`_join_continued_literals` + `_string_literals`)
    после этого сырых кавычек больше не видит.
    """
    linenos = [lineno for lineno, _ in pairs]
    lines = [line for _, line in pairs]
    text = "".join(lines)

    starts = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line)

    def _lineno_at(idx):
        result = linenos[0] if linenos else 1
        for start, ln in zip(starts, linenos):
            if start <= idx:
                result = ln
            else:
                break
        return result

    raw_contents = []
    masked = list(text)
    for m in RAW_STRING_RE.finditer(text):
        raw_contents.append((_lineno_at(m.start()), m.group(2)))
        for i in range(m.start(), m.end()):
            if masked[i] != "\n":
                masked[i] = "x"
    masked_text = "".join(masked)
    masked_lines = masked_text.splitlines(keepends=True)
    # Маскирование не должно менять число физических строк — иначе номера
    # строк у последующих проверок разъедутся с исходником.
    assert len(masked_lines) == len(pairs), (
        "маскирование сырых строк изменило число строк report.rs — не должно"
    )
    return list(zip(linenos, masked_lines)), raw_contents


def _scan_text(lineno, text, hits):
    """Прогоняет один фрагмент текста (обычный литерал или тело сырой строки)
    через все правила П8-1..П8-3 и складывает находки в `hits`."""
    if EM_DASH_RE.search(text):
        hits["em_dash"].append((lineno, text))
    # Точное нижнерегистровое совпадение — внутренний data-key
    # (role == "baseline", ts.get("baseline")), не клиентский текст.
    if BASELINE_WORD_RE.search(text) and text.strip() != "baseline":
        hits["baseline"].append((lineno, text))
    if MEDIA_LATIN_RE.search(text):
        hits["media_latin"].append((lineno, text))
    # headword-строка (глоссарий-стиль "Adstock" ровно) — тот же прецедент,
    # что уже разрешён в HTML-глоссарии.
    if (
        ADSTOCK_WORD_RE.search(text)
        and text.strip() != "Adstock"
        and _BARE_ADSTOCK_RE.search(text)
    ):
        hits["adstock"].append((lineno, text))
    if NA_LITERAL_RE.search(text):
        hits["na_literal"].append((lineno, text))
    if SPACED_HYPHEN_RE.search(text):
        hits["spaced_hyphen"].append((lineno, text))


def _collect_violations():
    hits = {
        "em_dash": [], "baseline": [], "media_latin": [], "adstock": [],
        "na_literal": [], "spaced_hyphen": [],
    }
    checked_lines = 0

    pairs = _production_source_lines()
    masked_pairs, raw_contents = _mask_raw_strings(pairs)

    for lineno, content in raw_contents:
        _scan_text(lineno, content, hits)

    for lineno, line in _join_continued_literals(masked_pairs):
        lits = _string_literals(line)
        if not lits:
            continue
        checked_lines += 1
        for lit in lits:
            _scan_text(lineno, lit, hits)

    return {
        "checked_lines": checked_lines,
        "raw_strings_checked": len(raw_contents),
        **hits,
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


def test_rs_report_no_na_literal():
    """П8-3 (2026-07-27): "N/A" — англицизм. Честное отсутствие ярлыка/значения
    в клиентском тексте пишется по-русски ("н/д"), см. mqs_tiers::resolve_mqs_label
    и top_ch в build_markdown — оба места переведены с "N/A" на "н/д"."""
    v = _collect_violations()
    assert not v["na_literal"], f"П8-3: литерал N/A в report.rs (production): {v['na_literal']}"


def test_rs_report_no_spaced_hyphen_as_dash():
    """П8-4 (2026-07-27): дефис-минус между пробелами — это тире, записанное не тем знаком.

    Клиентский канон: короткое тире «–». Правило П8-1 стерегло ДЛИННОЕ тире, и
    обратная ошибка (дефис вместо тире) была для гейта невидима — «Базовый спрос -
    часть KPI» проходило годами при зелёном тесте. Признак поиска не совпадал с
    классом дефекта; тот же корень, что у CPD-29.
    """
    v = _collect_violations()
    assert not v["spaced_hyphen"], (
        "П8-4: дефис между пробелами вместо короткого тире «–» в report.rs "
        f"(production): {v['spaced_hyphen']}"
    )


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
        f"сырых строк (r\"...\"/r#\"...\"#) проверено {v['raw_strings_checked']}; "
        f"узаконенных терминов {len(_LEGITIMISED_LITERALS)} — "
        f"{sorted(_LEGITIMISED_LITERALS)}"
    )
    print(summary)
    assert v["checked_lines"] > 100, (
        "report.rs: строковых литералов почти не найдено — либо файл переехал, "
        "либо проверка сломана (см. _REPORT_RS путь)"
    )
    assert v["raw_strings_checked"] >= 1, (
        "report.rs: ни одной сырой строки не найдено — либо XML-регулярка "
        "(около строки 1910) переехала/удалена, либо разбор сырых строк сломан "
        "(защита от тихого нуля новой ветки проверки)"
    )
