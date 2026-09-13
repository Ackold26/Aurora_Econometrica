#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_to_blank_docx.py — постоянный конвертер клиентских .md-документов на фирменный
бланк ООО «Платформа Аврора» (замена одноразовому скрипту сессии s46, который
пропал вместе с временным каталогом).

Вход:  один или несколько файлов .md (позиционные аргументы — базовые имена без
       расширения, ищутся в --src-dir) или явные пути через --paths.
Выход: рядом с исходником (или в --out-dir) — .docx на бланке с тем же базовым
       именем.

Поддержанная разметка (сознательно узкое подмножество — см. README ниже):
  - Заголовки:      "# текст"  -> стиль "Heading 1" бланка
                     "## текст" -> стиль "MD Heading 2" (добавляется в документ,
                     существующие стили бланка НЕ правятся)
  - Абзацы:          соседние непустые строки без пустой строки между ними
                     склеиваются в один Word-абзац (как одиночный перенос
                     строки в GFM — он не создаёт новую строку).
  - Списки:          "- текст" / "* текст" — маркированный;
                     "1. текст" — нумерованный. Настоящая нумерация/маркеры
                     Word (numbering.xml), не текстовые "-"/"1.". Вложенность —
                     через отступ абзаца (не через w:ilvl — в бланке уровни
                     нумерации ниже 0 не описаны, обращение к ним откатывает
                     список к умолчанию — грабли s46 #3).
  - Таблицы:         GFM pipe-таблицы -> настоящие таблицы Word, стиль
                     "Table Grid", столбцы равной ширины под полосу набора.
  - Форматирование:  "**жирный**" и "`код`" (код — Consolas) внутри абзацев,
                     заголовков и ячеек таблиц.
  - Блок кода:       ```...``` — построчно, шрифтом Consolas, без разбора
                     инлайн-разметки внутри (моноширинный текст как есть).

Инструмент ПАДАЕТ с внятной ошибкой (файл + номер строки + причина), если:
  - бланк не найден по указанному пути;
  - встретилась разметка, которую он не умеет: заголовки уровня 3+, цитаты
    (>), картинки/ссылки ("![...]"/"[...](...)"), горизонтальные линии
    ("---"/"***" вне таблицы), неровные таблицы (разное число столбцов
    в строках), незакрытый блок кода.
Молчаливая потеря содержимого запрещена принципиально — лучше упасть.

Пример запуска (без аргументов — обрабатывает канонические 6 файлов пакета,
ищет .md и пишет .docx в папку передаточного пакета Econometrica):

    python tools/md_to_blank_docx.py

Явный список и другой бланк:

    python tools/md_to_blank_docx.py ЧИТАЙТЕ_ПЕРВЫМ ЗАПИСКА_ДЛЯ_ИТ --blank "D:\\путь\\бланк.docx"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Twips

# --- умолчания -------------------------------------------------------------

DEFAULT_BLANK = Path(r"D:\Документы\ООО Платформа Аврора - документы\Фирменный бланк.docx")
DEFAULT_DIR = Path(r"C:\Users\ackol\Desktop\Передаточный пакет\Econometrica")
DEFAULT_FILES = [
    "ЧИТАЙТЕ_ПЕРВЫМ",
    "УСТАНОВКА_и_первые_30_минут",
    "СЦЕНАРИЙ_ТЕСТА",
    "ЗАПИСКА_ДЛЯ_ИТ",
    "ДАННЫЕ_И_ПРИВАТНОСТЬ",
    "ШАБЛОН_входного_файла",
]

H2_STYLE_NAME = "MD Heading 2"
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class MdConvertError(RuntimeError):
    """Разметка не поддержана или бланк/файл не найден — падаем внятно."""


# --- вспомогательное: инлайн-форматирование --------------------------------

_INLINE_RE = re.compile(r"(\*\*[^*]+?\*\*|`[^`]+?`)")


def _add_inline_runs(paragraph, text: str) -> None:
    """Bold **text** и `code` (Consolas) — прямым форматированием рана."""
    for chunk in _INLINE_RE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            run = paragraph.add_run(chunk[2:-2])
            run.bold = True
        elif chunk.startswith("`") and chunk.endswith("`"):
            run = paragraph.add_run(chunk[1:-1])
            run.font.name = "Consolas"
        else:
            paragraph.add_run(chunk)


# --- проверка на неподдержанную разметку -----------------------------------

_UNSUPPORTED_PATTERNS = [
    (re.compile(r"^\s*>"), "цитата (>) не поддержана"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), "изображение (![]()) не поддержано"),
    (re.compile(r"(?<!\!)\[[^\]]+\]\([^)]*\)"), "ссылка ([]()) не поддержана"),
    (re.compile(r"^\s*(---+|\*\*\*+|___+)\s*$"), "горизонтальная линия / setext-заголовок не поддержаны"),
    (re.compile(r"^#{3,}\s"), "заголовок уровня 3+ не поддержан (только # и ##)"),
]


def _check_supported(line: str, lineno: int, src: Path) -> None:
    for pat, reason in _UNSUPPORTED_PATTERNS:
        if pat.search(line):
            raise MdConvertError(
                f"{src.name}:{lineno}: неподдержанная разметка — {reason}\n  строка: {line!r}"
            )


# --- numbering.xml: добавление списков --------------------------------------

class NumberingFactory:
    """Заводит новые абстрактные нумерации (маркер/decimal) и по одному w:num
    на каждый непрерывный список в документе (грабли s46 #2: без отдельного
    w:num второй список в файле продолжал счёт первого)."""

    def __init__(self, document: Document):
        self._numbering = document.part.numbering_part.element
        existing_abstract = self._numbering.findall(qn("w:abstractNum"))
        existing_num = self._numbering.findall(qn("w:num"))
        self._next_abstract_id = (
            max((int(a.get(qn("w:abstractNumId"))) for a in existing_abstract), default=-1) + 1
        )
        self._next_num_id = (
            max((int(n.get(qn("w:numId"))) for n in existing_num), default=0) + 1
        )
        self._bullet_abstract_id = self._add_bullet_abstract_num()
        self._decimal_abstract_id = self._add_decimal_abstract_num()

    def _insert_abstract_num(self, xml: str) -> int:
        el = OxmlElement("w:abstractNum")
        # проще: соберём через parse_xml с полным namespace
        from docx.oxml import parse_xml

        el = parse_xml(xml)
        # abstractNum-элементы должны идти ПЕРЕД num-элементами (схема OOXML,
        # грабли s46 #1)
        first_num = self._numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(el)
        else:
            self._numbering.append(el)
        return int(el.get(qn("w:abstractNumId")))

    def _add_bullet_abstract_num(self) -> int:
        aid = self._next_abstract_id
        self._next_abstract_id += 1
        xml = (
            f'<w:abstractNum xmlns:w="{NS_W}" w:abstractNumId="{aid}">'
            f'<w:multiLevelType w:val="hybridMultilevel"/>'
            f'<w:lvl w:ilvl="0">'
            f'<w:start w:val="1"/>'
            f'<w:numFmt w:val="bullet"/>'
            f'<w:lvlText w:val="•"/>'
            f'<w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="432" w:hanging="432"/></w:pPr>'
            f'<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:hint="default"/></w:rPr>'
            f'</w:lvl>'
            f'</w:abstractNum>'
        )
        return self._insert_abstract_num(xml)

    def _add_decimal_abstract_num(self) -> int:
        aid = self._next_abstract_id
        self._next_abstract_id += 1
        xml = (
            f'<w:abstractNum xmlns:w="{NS_W}" w:abstractNumId="{aid}">'
            f'<w:multiLevelType w:val="hybridMultilevel"/>'
            f'<w:lvl w:ilvl="0">'
            f'<w:start w:val="1"/>'
            f'<w:numFmt w:val="decimal"/>'
            f'<w:lvlText w:val="%1."/>'
            f'<w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="432" w:hanging="432"/></w:pPr>'
            f'</w:lvl>'
            f'</w:abstractNum>'
        )
        return self._insert_abstract_num(xml)

    def new_list(self, ordered: bool) -> int:
        """Новый w:num (свой counter) для очередного непрерывного списка —
        нумерация начинается заново, даже если в файле список такого же типа
        уже был."""
        from docx.oxml import parse_xml

        num_id = self._next_num_id
        self._next_num_id += 1
        abstract_id = self._decimal_abstract_id if ordered else self._bullet_abstract_id
        override = (
            f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
            if ordered
            else ""
        )
        xml = (
            f'<w:num xmlns:w="{NS_W}" w:numId="{num_id}">'
            f'<w:abstractNumId w:val="{abstract_id}"/>'
            f"{override}"
            f"</w:num>"
        )
        el = parse_xml(xml)
        self._numbering.append(el)
        return num_id


def _set_list_paragraph(paragraph, num_id: int, level: int) -> None:
    """Подключает абзац к нумерации num_id, всегда через w:ilvl=0 (грабли
    s46 #3), вложенность — через дополнительный левый отступ."""
    pPr = paragraph._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    numId = OxmlElement("w:numId")
    numId.set(qn("w:val"), str(num_id))
    numPr.append(ilvl)
    numPr.append(numId)
    pPr.append(numPr)
    if level:
        paragraph.paragraph_format.left_indent = Pt(18) * level  # ~0.25" на уровень поверх базового


# --- H2-стиль ----------------------------------------------------------------

def _ensure_h2_style(document: Document):
    styles = document.styles
    if H2_STYLE_NAME in [s.name for s in styles]:
        return styles[H2_STYLE_NAME]
    from docx.enum.style import WD_STYLE_TYPE

    style = styles.add_style(H2_STYLE_NAME, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = styles["Heading 1"]
    style.font.size = Pt(13)
    style.font.bold = True
    style.font.name = "Arial"
    style.paragraph_format.space_before = Pt(10)
    style.paragraph_format.space_after = Pt(4)
    return style


# --- парсер markdown --------------------------------------------------------

def _usable_width_twips(document: Document) -> int:
    section = document.sections[0]
    emu = section.page_width - section.left_margin - section.right_margin
    return int(emu / 635)  # 1 twip = 635 EMU


def _parse_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{1,}:?", c) for c in cells)


def convert_markdown(document: Document, md_text: str, src: Path, numbering: NumberingFactory) -> None:
    lines = md_text.split("\n")
    i = 0
    n = len(lines)
    usable_twips = _usable_width_twips(document)

    # текущий непрерывный список: (ordered, num_id) или None
    current_list: tuple[bool, int] | None = None

    def close_list():
        nonlocal current_list
        current_list = None

    while i < n:
        raw = lines[i]
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped == "":
            close_list()
            i += 1
            continue

        # --- блок кода (```...```) — построчно, шрифтом Consolas, без инлайн-разбора ---
        if stripped.startswith("```"):
            close_list()
            j = i + 1
            while j < n and lines[j].strip() != "```":
                j += 1
            if j >= n:
                raise MdConvertError(f"{src.name}:{i+1}: блок кода не закрыт (нет парной ```)")
            for code_line in lines[i + 1 : j]:
                p = document.add_paragraph()
                run = p.add_run(code_line if code_line else " ")  # пустую строку не теряем как абзац
                run.font.name = "Consolas"
            i = j + 1
            continue

        _check_supported(line, i + 1, src)

        # --- таблица ---
        if stripped.startswith("|"):
            close_list()
            header_cells = _parse_table_row(line)
            if i + 1 >= n:
                raise MdConvertError(f"{src.name}:{i+1}: таблица без строки-разделителя")
            sep_cells = _parse_table_row(lines[i + 1])
            if len(sep_cells) != len(header_cells) or not _is_separator_row(sep_cells):
                raise MdConvertError(
                    f"{src.name}:{i+2}: ожидалась строка-разделитель таблицы (|---|---|), получено: {lines[i+1]!r}"
                )
            ncols = len(header_cells)
            rows = [header_cells]
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                row_cells = _parse_table_row(lines[j])
                if len(row_cells) != ncols:
                    raise MdConvertError(
                        f"{src.name}:{j+1}: неровная таблица — {len(row_cells)} столбцов вместо {ncols}: {lines[j]!r}"
                    )
                rows.append(row_cells)
                j += 1
            table = document.add_table(rows=len(rows), cols=ncols)
            table.style = "Table Grid"
            col_width = Twips(usable_twips // ncols)
            for row_idx, row_cells in enumerate(rows):
                for col_idx, cell_text in enumerate(row_cells):
                    cell = table.cell(row_idx, col_idx)
                    cell.width = col_width
                    p = cell.paragraphs[0]
                    p.text = ""
                    _add_inline_runs(p, cell_text)
                    if row_idx == 0:
                        for run in p.runs:
                            run.bold = True
            i = j
            continue

        # --- заголовки ---
        if stripped.startswith("## "):
            close_list()
            p = document.add_paragraph(style=_ensure_h2_style(document))
            _add_inline_runs(p, stripped[3:].strip())
            i += 1
            continue
        if stripped.startswith("# "):
            close_list()
            p = document.add_paragraph(style="Heading 1")
            _add_inline_runs(p, stripped[2:].strip())
            i += 1
            continue

        # --- списки ---
        m_ul = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        m_ol = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if m_ul or m_ol:
            ordered = m_ol is not None
            indent, text = (m_ol or m_ul).groups()
            level = len(indent) // 2
            if current_list is None or current_list[0] != ordered:
                num_id = numbering.new_list(ordered)
                current_list = (ordered, num_id)
            p = document.add_paragraph()
            _set_list_paragraph(p, current_list[1], level)
            _add_inline_runs(p, text.strip())
            i += 1
            continue

        # --- обычный абзац: склеиваем соседние непустые строки ---
        close_list()
        para_lines = [stripped]
        j = i + 1
        while j < n and lines[j].strip() != "" and not _is_block_start(lines[j]):
            _check_supported(lines[j], j + 1, src)
            para_lines.append(lines[j].strip())
            j += 1
        p = document.add_paragraph()
        _add_inline_runs(p, " ".join(para_lines))
        i = j


def _is_block_start(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return True
    if s.startswith("|"):
        return True
    if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
        return True
    return False


# --- сборка одного файла -----------------------------------------------------

def build_docx(md_path: Path, blank_path: Path, out_path: Path) -> Document:
    if not blank_path.exists():
        raise MdConvertError(f"бланк не найден: {blank_path}")
    if not md_path.exists():
        raise MdConvertError(f"исходник не найден: {md_path}")
    document = Document(str(blank_path))  # открываем бланк как шаблон; сохраняем в другой файл — оригинал не трогается
    numbering = NumberingFactory(document)
    md_text = md_path.read_text(encoding="utf-8")
    convert_markdown(document, md_text, md_path, numbering)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    return document


def summarize(md_path: Path, docx_path: Path) -> dict:
    from docx import Document as D

    d = D(str(docx_path))
    body_paras = sum(1 for p in d.paragraphs if p.text.strip() or p.style.name in ("Heading 1", H2_STYLE_NAME))
    n_tables = len(d.tables)
    nonempty_src_lines = sum(1 for l in md_path.read_text(encoding="utf-8").split("\n") if l.strip())
    return {"paragraphs": body_paras, "tables": n_tables, "src_nonempty_lines": nonempty_src_lines}


# --- CLI ---------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="md -> docx на фирменном бланке Aurora")
    parser.add_argument("names", nargs="*", default=None, help="базовые имена файлов (без .md); по умолчанию — 6 канонических файлов пакета")
    parser.add_argument("--blank", type=Path, default=DEFAULT_BLANK, help="путь к фирменному бланку .docx")
    parser.add_argument("--src-dir", type=Path, default=DEFAULT_DIR, help="каталог с исходными .md")
    parser.add_argument("--out-dir", type=Path, default=None, help="каталог для .docx (по умолчанию — тот же, что --src-dir)")
    args = parser.parse_args(argv)

    names = args.names or DEFAULT_FILES
    out_dir = args.out_dir or args.src_dir

    if not args.blank.exists():
        print(f"ОШИБКА: бланк не найден: {args.blank}", file=sys.stderr)
        return 2

    failures = []
    for name in names:
        md_path = args.src_dir / f"{name}.md"
        out_path = out_dir / f"{name}.docx"
        try:
            build_docx(md_path, args.blank, out_path)
            stats = summarize(md_path, out_path)
            print(f"OK  {name}: абзацев={stats['paragraphs']} таблиц={stats['tables']} строк_md={stats['src_nonempty_lines']} -> {out_path}")
        except MdConvertError as e:
            print(f"ОШИБКА {name}: {e}", file=sys.stderr)
            failures.append(name)

    if failures:
        print(f"\nНе собраны: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
