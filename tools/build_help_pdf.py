#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a single downloadable PDF from the Aurora AI Econometrica in-app
help pages.

Механика сборки и оформление - по эталону линейки (Стандарт справочной
системы, aurora-meta/STANDARDS/HELP_PDF_STANDARD.md), портировано с Oracle
(волна 2 свипа, 2026-07-19):
D:\\Docs\\Aurora_Ai\\Dev\\Aurora_Oracle\\tools\\build_help_pdf.py

Обложки (передняя и задняя) - ОТДЕЛЬНЫЕ standalone-документы, каждая со своим
Edge-вызовом и собственным @page { size: A4; margin: 0 }, склеиваются в конце
через pypdf: front -> main (оглавление + разделы) -> appendix -> back. Класть
обложку В общий печатаемый документ нельзя - headless Edge ужимает ВСЕ
страницы документа под самый широкий элемент контента (shrink-to-fit): фон
обложки обрезается, лого мельчает.

Как и у Oracle, каждая help-страница Econometrica сама объявляет :root с
тёмной палитрой ЭКРАННОЙ темы - strip_dark_theme_leaks() вырезает :root и
голые теговые селекторы (см. её докстринг).

Отличие от эталона Oracle, найденное ревизией живых файлов (2026-07-19):
1. install.html несёт ОБА раздела - «Установка» и «Удаление программы» - в
   ОДНОМ файле (у Oracle УДАЛЕНИЕ.html - отдельный файл). split_install_body()
   режет извлечённый body по границе <h2>Удаление программы</h2>: раздел
   «Установка» остаётся обычной страницей в PAGE_ORDER, раздел «Удаление»
   уходит в приложение (печатается отдельным вызовом Edge, стыкуется через
   pypdf - тот же приём, что и УДАЛЕНИЕ.html у Oracle).
2. install.html (и весь install-кластер: about/user-guide/system-requirements/
   pipeline/methodology/faq/glossary и др.) несёт ТЁМНЫЙ исходный :root (как у
   Legal Center, НЕ как светлый УДАЛЕНИЕ.html у Oracle) - раздел «Удаление»
   прогоняется через ТОТ ЖЕ print-конвейер (BASE_PRINT_CSS + strip_dark_theme_
   leaks), что и обычные страницы, а не через облегчённую обработку Oracle.
3. Несколько страниц (features/data-preparation/econometrica/whats-new/
   interpretation/methodology) объявляют --purple/--teal в своём :root и
   используют их в СОХРАНЯЕМЫХ (не голых тег-) селекторах - `.badge-expert`,
   `.role-date`, `.naming-card .zone`, `.change.sec`, `details.expert` и т.п.
   :root вырезается per-page, поэтому эти переменные остаются неопределены в
   склеенном документе без явного объявления в общем BASE_PRINT_CSS. Найдено
   ревизией живых файлов - добавлены print-safe значения из того же токен-
   стандарта (Standards/tokens/tokens.json), что и остальная палитра:
   --purple: #6633CC (color-data-purple), --teal: #0E7490
   (color-ui-themes-light-status-info) - без этого `.badge-expert`/
   `.naming-card.date .zone` и т.п. остались бы без акцентного цвета
   (invalid-at-computed-value-time -> currentColor).
4. force_details_open() применяется КО ВСЕМ страницам, не только к faq.html -
   ревизией найдено, что <details> без `open` встречаются также в
   interpretation.html и data-preparation.html («экспертные» вставки), не
   только в FAQ-аккордеоне. Регекс идемпотентен на страницах без <details>,
   поэтому безопасно применять universally.
5. Палитра - src/tokens.generated.css (сгенерирован из Standards/tokens/
   tokens.json) - сверено 1:1 с палитрой Oracle: deep-100/80/60/40,
   gold-primary, bg-quiet, rule, status-success/warning/danger совпадают
   буквально. Взята без изменений.

Requires Microsoft Edge (headless --print-to-pdf) and the pypdf package.
Re-run this after every release - the PDF is a build artifact, not generated
automatically by `npm run tauri build`.

Usage:
  python tools/build_help_pdf.py
  python tools/build_help_pdf.py --product "Aurora AI Econometrica" \\
      --out src-tauri/help-econometrica/econometrica-help.pdf
"""

import argparse
import base64
import glob
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import pypdf
except ImportError:
    pypdf = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HELP_DIR = REPO_ROOT / "src-tauri" / "help-econometrica"
DEFAULT_TAURI_CONF = REPO_ROOT / "src-tauri" / "tauri.conf.json"
DEFAULT_OUT = DEFAULT_HELP_DIR / "econometrica-help.pdf"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "help_pdf_manifest.json"
# Обложка (derive_cover_title ниже) показывает "Optimizer MMM", не
# "Econometrica" - решение Антона 2026-07-19: единое имя с productName
# сборки/установщика (tauri.conf.json "productName": "Optimizer MMM",
# сам инсталлятор называется Optimizer MMM_2.4.0_x64-setup.exe). Тело
# документа (apply_brand_naming ниже) по-прежнему говорит "Aurora AI -
# Econometrica" - это разные вещи: обложка = имя продукта на рынке коробки,
# проза = маркетинговое имя линейки, трогать вторую Антон не просил.
DEFAULT_PRODUCT = "Aurora AI Optimizer MMM"
NAV_JS = DEFAULT_HELP_DIR / "econ-nav.js"

# Порядок разделов PDF - логика новичка (директива Антона, ретранслирована
# через team-lead 2026-07-19), НЕ порядок econ-nav.js (тот группирует под
# экранный навбар: Начало/Данные и методология/Интерфейс/Возможности).
# index (справочный центр = обзор) и about (о продукте) открывают документ;
# user-guide/system-requirements - до install (проверить требования и в целом
# ориентироваться в продукте, ДО того как ставить); install - установка
# (раздел «Удаление» вырезан в приложение, см. split_install_body);
# econometrica (Visual Pipeline UI) - экранный тур сразу после установки,
# мост к глубоким методологическим разделам; pipeline/data-preparation/
# methodology/interpretation - ядро продукта; features - каталог функций
# (включает как подразделы «Режимы анализа и типы KPI» и «Отчёты и экспорт» -
# отдельных файлов под них нет); faq/error-codes/glossary - справочные
# разделы; whats-new - закрывает документ. Обновлять вручную при появлении/
# уходе раздела.
PAGE_ORDER = [
    "index",
    "about",
    "user-guide",
    "system-requirements",
    "install",
    "econometrica",
    "pipeline",
    "data-preparation",
    "methodology",
    "interpretation",
    "features",
    "faq",
    "error-codes",
    "glossary",
    "whats-new",
]

# install.html несёт ОБА раздела («Установка» + «Удаление программы») в одном
# файле - в отличие от Oracle, где УДАЛЕНИЕ - отдельный файл. Раздел
# «Удаление» вырезается функцией split_install_body() и печатается в
# приложение отдельным вызовом Edge (см. докстринг файла, пункт 1).
INSTALL_PAGE = "install"
UNINSTALL_H2_RE = re.compile(r"<h2>\s*Удаление программы\s*</h2>")
# Хвост body install.html: `...</div><div class="footer">...</div>` - жадный
# `(?P<inner>.*)` естественно останавливается на ПОСЛЕДНЕМ `</div>` перед
# footer-блоком (footer один и только в самом конце документа).
INSTALL_BODY_TAIL_RE = re.compile(
    r'^(?P<inner>.*)</div>\s*(?P<footer><div class="footer">.*?</div>)\s*\Z', re.S
)

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

# ---------------------------------------------------------------------------
# Палитра - src/tokens.generated.css (Standards/tokens/tokens.json), сверено
# 1:1 при ревизии 2026-07-19: deep-100/80/60/40, gold-primary, bg-quiet,
# rule, status-success/warning/danger - совпадает буквально с эталоном
# Oracle/CH (тот же общий tokens.json линейки).
# --purple/--teal - ДОБАВЛЕНЫ сверх эталона Oracle (тот их не использует):
# несколько страниц Econometrica держат `.badge-expert`/`.role-date`/
# `.naming-card .zone`/`.change.sec`/`details.expert` на var(--purple)/
# var(--teal) в сохраняемых (не голых тег-) селекторах - см. докстринг файла,
# пункт 3. Значения - из того же токен-стандарта: --color-data-purple и
# --color-ui-themes-light-status-info (печатно-безопасные, не экранные
# неоновые #bc8cff/#39d0d8 исходников).
# ---------------------------------------------------------------------------
BASE_PRINT_CSS = """
:root {
  --bg: #FFFFFF;
  --bg2: #F7F5EE;
  --bg3: #F7F5EE;
  --text: #0A1628;
  --text2: #547090;
  --text3: #99ADC2;
  --accent: #1E3A5F;
  --accent2: #C5A46D;
  --gold: #C5A46D;
  --border: #C8CDD4;
  --green: #15803D;
  --amber: #9A4D07;
  --red: #C03030;
  --purple: #6633CC;
  --teal: #0E7490;
}
*, *::before, *::after {
  box-sizing: border-box;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
html, body { margin: 0; padding: 0; }
@page { size: A4; margin: 15mm 15mm 18mm; }

body {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; font-size: 12.5px;
}

.pdf-page { page-break-before: always; break-before: page; }
.pdf-page:first-child { page-break-before: avoid; break-before: avoid; }
h2, h3, h4, tr, table, .note, .card, .hero, .step, .cmd-card, .info-box,
.warning-box, .callout, .term, details { break-inside: avoid; }
h2, h3, h4 { break-after: avoid; }
img { max-width: 100%; }

/* сброс градиентных заголовков (background-clip:text) исходных тёмных страниц -
   без этого текст на белом фоне печати становится невидимым */
* {
  background-image: none !important;
  -webkit-text-fill-color: currentColor !important;
  -webkit-background-clip: border-box !important;
  background-clip: border-box !important;
  text-shadow: none !important;
}

.hero {
  background: var(--bg2); padding: 40px 32px 32px; text-align: center;
  border-bottom: 2px solid var(--gold);
}
.hero h1 { font-size: 24px; font-weight: 600; color: var(--accent); margin: 0; }
.hero h1 span { color: var(--accent); }
.hero .tagline, .hero .sub, .hero p { font-size: 13.5px; color: var(--text2); margin-top: 8px; }

.container { max-width: 860px; margin: 0 auto; padding: 24px 32px 40px; }

h1 { font-size: 24px; font-weight: 600; color: var(--accent); margin: 0 0 8px; }
h2 {
  font-size: 19px; font-weight: 600; color: var(--accent);
  margin-top: 30px; margin-bottom: 15px; padding-bottom: 8px; border-bottom: 2px solid var(--gold);
}
h2:first-of-type { margin-top: 8px; }
h3 { font-size: 15.5px; font-weight: 600; margin-top: 22px; margin-bottom: 9px; color: var(--text); }
h4 { font-size: 13px; font-weight: 600; margin-top: 14px; margin-bottom: 7px; color: var(--accent); }

p { margin: 0 0 11px; }
.subtitle, .tagline { color: var(--text2); font-size: 14px; margin-bottom: 20px; }
.lead { font-size: 14px; color: var(--text); margin-bottom: 13px; }

ul, ol { padding-left: 22px; margin: 0 0 13px; }
li { margin-bottom: 5px; }

a { color: var(--accent); text-decoration: none; }

code {
  background: var(--bg2); padding: 2px 6px; border-radius: 4px;
  font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11.5px;
  color: var(--accent); border: 1px solid var(--border);
}
pre {
  background: var(--bg2); border: 1px solid var(--border); border-radius: 8px;
  padding: 13px; overflow-x: auto; margin: 11px 0;
  font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11.5px; line-height: 1.5; color: var(--text);
}
kbd {
  display: inline-block; background: var(--bg2); border: 1px solid var(--border);
  border-bottom-width: 2px; border-radius: 5px; padding: 1px 7px;
  font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11.5px; color: var(--accent);
}

table { width: 100%; border-collapse: collapse; margin: 13px 0; }
th, td { padding: 9px 11px; text-align: left; border: 1px solid var(--border); font-size: 11.5px; vertical-align: top; }
th { background: var(--accent); color: #FFFFFF; font-weight: 600; }
tr:nth-child(even) td { background: var(--bg2); }

/* карточки/плашки контента - общая светлая заливка + золотой левый бордер
   вместо тёмных поверхностей экранной темы */
.card, .note, .step, .cmd-card, .info-box, .warning-box, .callout, .term {
  background: var(--bg2); border: 1px solid var(--border); border-radius: 8px;
}
.step, .note, .callout { border-left: 3px solid var(--gold); }

.footer { text-align: center; padding: 18px 0; margin-top: 18px; border-top: 1px solid var(--border); }
.footer p { font-size: 10px; color: var(--text2); opacity: 0.8; }

/* печатная версия не запускает JS - принудительно раскрываем свёрнутые
   <details> (force_details_open уже добавляет атрибут open в разметку, это
   дублирующая страховка на случай нестандартной верстки) */
details:not([open]) > summary ~ * { display: block !important; }

/* элементы, осмысленные только с JS/экранной навигацией - в печатном
   документе не нужны (своё оглавление уже даёт переход по разделам) */
nav, #aurora-nav, input, .search, .anav-search-wrap { display: none !important; }
"""

# .pdf-cover - общая navy-подложка на весь разворот (используется и передней,
# и задней обложкой). Позиционирование разное (передняя - контент поднят в
# верхнюю треть; задняя - классическая вертикальная центровка) - вынесено в
# отдельные модификаторы, а не дублированием всего блока.
COVER_CSS = """
.pdf-cover {
  background: #0A1628; width: 100%; min-height: 297mm;
  display: flex; flex-direction: column; align-items: center;
  text-align: center; padding: 0 20mm;
}
.pdf-cover--front { justify-content: flex-start; padding-top: 55mm; }
.pdf-cover--back { justify-content: center; }
.pdf-cover-logo { height: 230px; width: auto; margin-bottom: 30px; }
.pdf-cover-title { font-size: 44px; font-weight: 600; color: #FFFFFF; margin-bottom: 14px; }
.pdf-cover-subtitle { font-size: 16px; color: #99ADC2; margin-bottom: 26px; }
.pdf-cover-sig { width: 64px; height: 3px; background: #CCFF00; margin: 0 0 26px; }
.pdf-cover-meta { font-size: 13px; color: #547090; }
"""

# Standalone-сброс для мини-документов передней/задней обложки и приложения
# (каждая печатается отдельным вызовом Edge - нужен свой @page/box-sizing,
# иначе UA-дефолт body margin 8px сдвигает центровку).
STANDALONE_RESET_CSS = """
*, *::before, *::after {
  box-sizing: border-box;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
html, body { margin: 0; padding: 0; }
@page { size: A4; margin: 0; }
body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
"""

TOC_CSS = """
.pdf-toc-heading {
  font-size: 22px; font-weight: 600; color: #1E3A5F;
  border-bottom: 3px solid #C5A46D; padding-bottom: 12px; margin: 0 0 26px;
}
.pdf-toc-row {
  display: flex; align-items: baseline; gap: 16px;
  padding: 11px 0; border-bottom: 1px dotted #C8CDD4;
}
.pdf-toc-num {
  font-family: 'Cascadia Code', 'Consolas', monospace; font-weight: 700;
  font-size: 13.5px; color: #C5A46D; min-width: 26px;
}
.pdf-toc-title { font-size: 14px; color: #0A1628; }
"""

SECTION_DIVIDER_CSS = """
.pdf-section-head { margin-bottom: 26px; }
.pdf-section-eyebrow {
  font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: #C5A46D; margin-bottom: 6px;
}
.pdf-section-title { font-size: 23px; font-weight: 600; color: #1E3A5F; margin: 0 0 12px; }
.pdf-section-rule { width: 100%; height: 2px; background: #C5A46D; }
"""

_ROOT_BLOCK_RE = re.compile(r":root\s*\{[^}]*\}", re.S)
_TOP_LEVEL_RULE_RE = re.compile(r"([^{}@]+)\{([^{}]*)\}")
_MEDIA_BLOCK_RE = re.compile(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", re.S)
# Голые теговые селекторы - у документа один <body> и общая цепочка
# <table><th>/<code>/<h1>.., поэтому "тегом" красится весь документ, а не
# страница-источник. Набор идентичен эталону Oracle (em/strong включены).
_DANGEROUS_BARE_SELECTORS = {
    "body", "html", "table", "th", "td", "tr", "thead", "tbody",
    "code", "pre", "kbd", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "p", "ul", "ol", "li", "blockquote", "input", "em", "strong", "*",
}


def strip_dark_theme_leaks(css: str) -> str:
    """Вырезает из per-page <style> ровно то, что способно залить тёмным весь
    документ целиком: :root (объявляется на <html>, общий для документа) и
    голые теговые селекторы. См. докстринг файла - точный разбор проблемы,
    портировано из Oracle без изменений (тот же набор _DANGEROUS_BARE_SELECTORS,
    та же логика @media print - откуда её у Econometrica находит econometrica.html,
    см. докстринг файла)."""
    css = _ROOT_BLOCK_RE.sub("", css)

    media_blocks = []

    def stash_media(m):
        block = m.group(0)
        header_match = re.match(r"@media\s*([^{]*)\{", block, re.I)
        condition = header_match.group(1).strip().lower() if header_match else ""
        if condition == "print":
            return ""
        media_blocks.append(block)
        return f"\0MEDIA{len(media_blocks) - 1}\0"

    css_no_media = _MEDIA_BLOCK_RE.sub(stash_media, css)

    def drop_dangerous(m):
        selectors = [s.strip().lower() for s in m.group(1).split(",")]
        if selectors and all(s in _DANGEROUS_BARE_SELECTORS for s in selectors):
            return ""
        return m.group(0)

    css_no_media = _TOP_LEVEL_RULE_RE.sub(drop_dangerous, css_no_media)

    for i, block in enumerate(media_blocks):
        css_no_media = css_no_media.replace(f"\0MEDIA{i}\0", block)

    return css_no_media


_INLINE_STYLE_ATTR_RE = re.compile(r'\s+style="[^"]*"')


def sanitize_error_codes_literals(style: str, body: str) -> tuple:
    """error-codes.html хардкодит ВСЕ цвета напрямую - нет :root, нет var() -
    Oracle уже документировал этот паттерн как известный per-product случай
    ("error-codes.html - тот хардкодит цвета напрямую, тот же случай, что у
    CH"). Бо́льшая часть покрыта голыми тег-селекторами (body/h1/h2/table/th/
    td/code) и вырезается strip_dark_theme_leaks(), но визуальной ревизией
    рендера (2026-07-19) найдено ДВА класса утечки, которые фильтр не ловит:

    1. В <style>: `td:first-child { color: #e6edf3; }`, `.footer p { color:
       #6e7681; }` и `.subtitle { color: #8b949e; ... }` - составные (не
       голые) селекторы, применяются на ВЕСЬ склеенный документ (не только
       к своей странице) - первая колонка ЛЮБОЙ таблицы документа
       (подтверждено рендером - data-preparation.html) становится почти
       нечитаемой (светлый экранный цвет на белой печати), футер и подзаголовки
       (`.subtitle`/`.tagline` - общий класс, есть дефолт в BASE_PRINT_CSS)
       ЛЮБОЙ страницы перекрашиваются в чужой более блёклый серый. Все три
       избыточны - остальные страницы уже получают корректный цвет либо от
       собственного var(--text), либо от дефолта BASE_PRINT_CSS - здесь
       просто вырезаются.
    2. Инлайн `style="..."` на блоке «Обращение в поддержку» (support-box +
       список «Что приложить») - strip_dark_theme_leaks обрабатывает ТОЛЬКО
       <style>, инлайн-атрибуты не трогает вообще. <li><strong
       style="color:#e6edf3"> вне тёмной подложки box'а стали бы почти
       невидимым белым текстом на белой печатной странице. Инлайн-стили
       вырезаются целиком (страница и так наследует print-безопасные
       значения из BASE_PRINT_CSS), для .support-box добавляется компактная
       замена - тот же приём, что и карточки/плашки (.card/.note) у
       остальных страниц."""
    style = re.sub(r"td:first-child\s*\{[^}]*\}", "", style)
    style = re.sub(r"\.footer\s+p\s*\{[^}]*\}", "", style)
    style = re.sub(r"\.subtitle\s*\{[^}]*\}", "", style)
    style += "\n.support-box { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; margin-bottom: 20px; }\n"
    body = _INLINE_STYLE_ATTR_RE.sub("", body)
    return style, body


def force_details_open(html_fragment: str) -> str:
    """Несколько страниц Econometrica (faq.html, interpretation.html,
    data-preparation.html - см. докстринг файла, пункт 4) строят раскрывающиеся
    блоки на нативных <details>/<summary> без атрибута open - без JS браузер
    прячет всё, кроме <summary> (UA-стиль Chromium скрывает их с приоритетом
    !important, авторским CSS не переопределить). Печать "как есть" дала бы
    PDF с вопросами/экспертными вставками без ответов. Применяется КО ВСЕМ
    страницам (не только faq, как у Oracle) - регекс идемпотентен на страницах
    без <details>, поэтому universal-применение безопасно."""
    return re.sub(r"<details(?![\w-])(?![^>]*\bopen\b)", "<details open", html_fragment)


def find_edge() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            return candidate
    print(
        "ERROR: Microsoft Edge (msedge.exe) не найден: "
        + ", ".join(str(c) for c in EDGE_CANDIDATES),
        file=sys.stderr,
    )
    sys.exit(1)


def read_version(tauri_conf: Path, override):
    """Версия читается из src-tauri/tauri.conf.json, НЕ package.json - единый
    канон линейки (package.json может отставать от tauri.conf.json)."""
    if override:
        return override
    if not tauri_conf.exists():
        print(f"ERROR: tauri.conf.json не найден: {tauri_conf}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(tauri_conf.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version:
        print(f"ERROR: Нет поля 'version' в {tauri_conf}", file=sys.stderr)
        sys.exit(1)
    return version


def parse_nav_titles(nav_js_path: Path) -> dict:
    """id -> русское название раздела из массива PAGES в econ-nav.js (SSOT
    человекочитаемых имён страниц для экранного навбара - переиспользуем те
    же названия в PDF, чтобы оглавление не расходилось с приложением)."""
    if not nav_js_path.exists():
        return {}
    js_text = nav_js_path.read_text(encoding="utf-8")
    pages_block_match = re.search(r"const PAGES\s*=\s*\[(.*?)\];", js_text, re.S)
    if not pages_block_match:
        return {}
    entry_re = re.compile(r"\{\s*id:\s*'([^']+)'\s*,\s*title:\s*'([^']+)'", re.S)
    return {m.group(1): m.group(2) for m in entry_re.finditer(pages_block_match.group(1))}


def image_to_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def extract_head_styles(html: str) -> str:
    head_match = re.search(r"<head[^>]*>(.*?)</head>", html, re.S | re.I)
    head = head_match.group(1) if head_match else ""
    return "\n".join(
        m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", head, re.S | re.I)
    )


def extract_title(html: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if not match:
        return fallback
    return re.split(r"\s[-–]\s", match.group(1))[0].strip() or fallback


def extract_body(html: str) -> str:
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.S | re.I)
    body = body_match.group(1) if body_match else html
    return re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.S | re.I)


def inline_local_images(html_fragment: str, help_dir: Path) -> str:
    def repl(match):
        filename = match.group(1)
        img_path = help_dir / filename
        if not img_path.exists():
            return match.group(0)
        return f'src="{image_to_data_uri(img_path)}"'

    return re.sub(r'src="([\w.-]+\.png)"', repl, html_fragment)


def apply_brand_naming(html: str) -> str:
    """Написание имени в прозе печатного руководства: "Aurora AI - Econometrica"
    (короткое тире), вместо голой конкатенации, которой сейчас пользуются
    исходные страницы."""
    return html.replace("Aurora AI Econometrica", "Aurora AI – Econometrica")


def apply_brand_naming_protected(html: str) -> str:
    """То же самое переименование, но не трогает буквальные значения внутри
    <code>...</code> (пути диска, имена exe/ps1, идентификаторы вида
    com.aurora.econometrica) - тире там указало бы на путь/имя, которого не
    существует ни на диске, ни в списке установленных программ Windows.
    В отличие от Oracle (<span class="path">, <div class="cmd-block">) -
    Econometrica хранит такие литералы просто в <code> (см. докстринг файла).
    На живом контенте раздела «Удаление» фраза "Aurora AI Econometrica" внутри
    <code> не встречается ни разу (проверено ревизией 2026-07-19) - защита
    здесь чисто оборонительная, на случай будущей правки контента."""
    protected = []

    def _protect(match):
        protected.append(match.group(0))
        return f"\x00PROTECTED{len(protected) - 1}\x00"

    guarded = re.sub(r"<code>.*?</code>", _protect, html, flags=re.S)
    guarded = apply_brand_naming(guarded)
    for i, original in enumerate(protected):
        guarded = guarded.replace(f"\x00PROTECTED{i}\x00", original)
    return guarded


def split_install_body(body: str, source_name: str) -> tuple:
    """install.html несёт ОБА раздела - «Установка» (до <h2>Удаление
    программы</h2>) и «Удаление программы» (сам заголовок и всё после) - в
    ОДНОМ файле, в отличие от Oracle, где УДАЛЕНИЕ - отдельный файл (см.
    докстринг файла, пункт 1). Возвращает (install_fragment, uninstall_fragment) -
    оба валидные HTML-фрагменты с собственным <div class="container">...</div>,
    install_fragment донашивает <div class="footer"> (он физически идёт СЛЕДОМ
    за разделом «Удаление» в исходном файле, но логически завершает страницу
    «Установка» - приложение печатает без повторного футера, у него меньше
    контента, копирайт уже есть на задней обложке PDF)."""
    tail_match = INSTALL_BODY_TAIL_RE.match(body)
    if not tail_match:
        print(
            f"ERROR: {source_name}: не удалось разобрать структуру body "
            "(ожидался '...</div><div class=\"footer\">...</div>' в конце) - "
            "разметка изменилась?",
            file=sys.stderr,
        )
        sys.exit(1)
    inner = tail_match.group("inner")
    footer_html = tail_match.group("footer")

    h2_match = UNINSTALL_H2_RE.search(inner)
    if not h2_match:
        print(
            f"ERROR: {source_name}: маркер '<h2>Удаление программы</h2>' не "
            "найден - разметка изменилась?",
            file=sys.stderr,
        )
        sys.exit(1)

    install_inner = inner[: h2_match.start()]
    uninstall_inner = inner[h2_match.start() :]

    install_fragment = install_inner + "</div>\n" + footer_html
    uninstall_fragment = '<div class="container">\n' + uninstall_inner + "\n</div>"
    return install_fragment, uninstall_fragment


def derive_cover_title(product: str) -> str:
    """Только название линейки продукта, без родительского бренда "Aurora
    AI" - тот уже присутствует на самом логотипе, повторять его в заголовке
    обложки - дублировать. "Aurora AI Econometrica" -> "Econometrica"."""
    stripped = re.sub(r"^Aurora AI\s*[-–]?\s*", "", product).strip()
    return stripped or product


def build_cover_html(product: str, logo_data_uri: str) -> str:
    """Standalone-документ на одну страницу - печатается отдельным вызовом
    Edge и приклеивается самой первой страницей в merge_pdfs()."""
    cover_title = derive_cover_title(product)
    logo_img = f'<img src="{logo_data_uri}" alt="{product}" class="pdf-cover-logo">' if logo_data_uri else ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>{product}</title>
<style>
{STANDALONE_RESET_CSS}
{COVER_CSS}
</style>
</head>
<body>
<section class="pdf-cover pdf-cover--front">
  {logo_img}
  <h1 class="pdf-cover-title">{cover_title}</h1>
  <p class="pdf-cover-subtitle">Справочное руководство</p>
  <div class="pdf-cover-sig"></div>
</section>
</body>
</html>
"""


def build_back_cover_html(product: str, logo_data_uri: str) -> str:
    """Standalone-документ на одну страницу - печатается отдельным вызовом
    Edge и приклеивается самой последней страницей (после приложения) в
    merge_pdfs(), зеркалирует внешний вид передней обложки."""
    cover_title = derive_cover_title(product)
    logo_img = f'<img src="{logo_data_uri}" alt="{product}" class="pdf-cover-logo">' if logo_data_uri else ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>{product}</title>
<style>
{STANDALONE_RESET_CSS}
{COVER_CSS}
.pdf-cover--back {{ position: relative; }}
.pdf-cover--back .pdf-cover-meta {{ position: absolute; bottom: 18mm; left: 0; right: 0; text-align: center; }}
</style>
</head>
<body>
<section class="pdf-cover pdf-cover--back">
  {logo_img}
  <h1 class="pdf-cover-title">{cover_title}</h1>
  <div class="pdf-cover-sig"></div>
  <p class="pdf-cover-meta">&copy; 2026 ООО «Платформа Аврора»</p>
</section>
</body>
</html>
"""


def build_toc_html(sections_meta) -> str:
    rows = "\n".join(
        f'    <div class="pdf-toc-row">'
        f'<span class="pdf-toc-num">{i:02d}</span>'
        f'<span class="pdf-toc-title">{title}</span>'
        f"</div>"
        for i, (_page_id, title) in enumerate(sections_meta, start=1)
    )
    return f"""
<section class="pdf-page pdf-toc">
  <h2 class="pdf-toc-heading">Содержание</h2>
  {rows}
</section>
"""


def build_section_divider_html(number: int, title: str) -> str:
    return f"""
<div class="pdf-section-head">
  <div class="pdf-section-eyebrow">Раздел {number:02d}</div>
  <div class="pdf-section-title">{title}</div>
  <div class="pdf-section-rule"></div>
</div>
"""


def build_merged_html(help_dir: Path, product: str, version: str, nav_titles: dict) -> tuple:
    """Возвращает (merged_html, appendix_style, appendix_body) - раздел
    «Удаление программы» вырезается из install.html здесь же (одно чтение
    файла), но печатается отдельным вызовом Edge в main()."""
    pages = []
    appendix_style = ""
    appendix_body = ""
    for page_id in PAGE_ORDER:
        page_path = help_dir / f"{page_id}.html"
        if not page_path.exists():
            print(f"ERROR: Help page not found: {page_path}", file=sys.stderr)
            sys.exit(1)
        raw = page_path.read_text(encoding="utf-8")
        title = nav_titles.get(page_id) or extract_title(raw, page_id)
        style = strip_dark_theme_leaks(extract_head_styles(raw))
        body = extract_body(raw)
        body = inline_local_images(body, help_dir)
        body = force_details_open(body)
        if page_id == "error-codes":
            style, body = sanitize_error_codes_literals(style, body)
        if page_id == INSTALL_PAGE:
            body, appendix_body = split_install_body(body, page_path.name)
            appendix_body = force_details_open(appendix_body)
            appendix_style = style
        pages.append({"id": page_id, "title": title, "style": style, "body": body})

    page_styles = [p["style"] for p in pages if p["style"].strip()]

    # Обложка НЕ входит в общий документ - печатается standalone (см. build_cover_html)
    sections = [
        build_toc_html([(p["id"], p["title"]) for p in pages]),
    ]
    for i, p in enumerate(pages, start=1):
        divider = build_section_divider_html(i, p["title"])
        sections.append(f'<section class="pdf-page">{divider}{p["body"]}</section>')

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>{product} - Справка</title>
<style>
{BASE_PRINT_CSS}
</style>
<style>
{chr(10).join(page_styles)}
</style>
<style>
{COVER_CSS}
{TOC_CSS}
{SECTION_DIVIDER_CSS}
</style>
</head>
<body>
{chr(10).join(sections)}
</body>
</html>
"""
    html = apply_brand_naming(html)
    return html, appendix_style, appendix_body


def build_appendix_html(appendix_body: str, appendix_style: str) -> str:
    """Раздел «Удаление программы», вырезанный из install.html
    (split_install_body) - в отличие от Oracle/CH (там УДАЛЕНИЕ - отдельный
    уже светлый файл, обрабатывается легковесно) источник здесь ТЁМНЫЙ
    (:root install.html - тот же случай, что у Legal Center): фрагмент
    прогоняется через ТОТ ЖЕ print-конвейер, что и обычные страницы
    (BASE_PRINT_CSS + уже вычисленный strip_dark_theme_leaks(install-style)),
    оборачивается в standalone-документ и печатается ОТДЕЛЬНЫМ вызовом Edge
    (как УДАЛЕНИЕ у Oracle) - собственные классы install.html (.callout,
    .c-info/.c-warn/.c-ok) не должны попасть в общий merged.html и покрасить
    другие страницы."""
    guarded = apply_brand_naming_protected(appendix_body)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Установка и удаление - Приложение</title>
<style>
{BASE_PRINT_CSS}
</style>
<style>
{appendix_style}
</style>
</head>
<body>
<section class="pdf-page">
{guarded}
</section>
</body>
</html>
"""


def print_to_pdf(edge: Path, html_path: Path, out_pdf: Path) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aurora-help-pdf-profile-", ignore_cleanup_errors=True) as profile_dir:
        # Свой --user-data-dir обязателен: если на машине уже открыт обычный
        # Edge, headless-вызов без изолированного профиля молча делегирует
        # запрос в него и завершается почти мгновенно, не дожидаясь рендера.
        cmd = [
            str(edge),
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={profile_dir}",
            f"--print-to-pdf={out_pdf}",
            "--no-pdf-header-footer",
            html_path.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(
                f"ERROR: msedge exited with code {result.returncode}:\n{result.stderr}",
                file=sys.stderr,
            )
            sys.exit(1)

    # msedge.exe на Windows форкает дочерний процесс и завершает родителя
    # почти сразу, ещё до того как PDF дописан на диск - ждём стабильного,
    # непустого размера файла вместо доверия к моменту возврата процесса.
    for _ in range(20):
        if out_pdf.exists() and out_pdf.stat().st_size > 0:
            size_before = out_pdf.stat().st_size
            time.sleep(0.2)
            if out_pdf.exists() and out_pdf.stat().st_size == size_before:
                return
        time.sleep(0.2)
    print(f"ERROR: Edge did not produce a stable PDF: {out_pdf}", file=sys.stderr)
    sys.exit(1)


def merge_pdfs(
    front_cover_pdf: Path,
    main_pdf: Path,
    appendix_pdf: Path,
    back_cover_pdf: Path,
    out_pdf: Path,
    product: str,
    version: str,
) -> None:
    if pypdf is None:
        print("ERROR: Install pypdf package: pip install pypdf", file=sys.stderr)
        sys.exit(1)
    writer = pypdf.PdfWriter()
    for src in (front_cover_pdf, main_pdf, appendix_pdf, back_cover_pdf):
        reader = pypdf.PdfReader(str(src))
        for page in reader.pages:
            writer.add_page(page)
    writer.add_metadata({
        "/Title": f"{product} - Справка",
        "/Author": "Aurora AI",
        "/Subject": f"Версия {version}",
    })
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        writer.write(f)


def build_manifest(help_dir: Path, version: str) -> dict:
    sources = {}
    for html_file in sorted(glob.glob(str(help_dir / "*.html"))):
        p = Path(html_file)
        sources[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    if NAV_JS.exists():
        sources[NAV_JS.name] = hashlib.sha256(NAV_JS.read_bytes()).hexdigest()
    return {
        "version": version,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": sources,
    }


def add_page_numbers(pdf_path: Path) -> None:
    """Номера страниц внизу по центру: со 2-й страницы; обложки (первая и
    последняя страницы) без номера. Chromium headless не умеет счётчики в
    @page margin-boxes, поэтому номера наносятся пост-обработкой готового
    PDF (PyMuPDF). Цвет - вторичный текст deep-60 из токенов."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[help-pdf] WARN: pymupdf не установлен - PDF собран без номеров страниц")
        return
    doc = fitz.open(str(pdf_path))
    color = (0x54 / 255.0, 0x70 / 255.0, 0x90 / 255.0)  # #547090
    for i in range(1, doc.page_count - 1):
        page = doc[i]
        label = str(i + 1)
        width = fitz.get_text_length(label, fontname="helv", fontsize=9)
        point = fitz.Point((page.rect.width - width) / 2, page.rect.height - 24)
        page.insert_text(point, label, fontname="helv", fontsize=9, color=color)
    last_numbered = doc.page_count - 1
    doc.saveIncr()
    doc.close()
    print(f"[help-pdf] Page numbers: 2..{last_numbered} (обложки без номера)")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--product", default=DEFAULT_PRODUCT, help="Product name for the cover page title")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output PDF path")
    parser.add_argument("--help-dir", type=Path, default=DEFAULT_HELP_DIR, help="Directory with the help HTML pages")
    parser.add_argument("--version", default=None, help="Version for PDF metadata (default: read from src-tauri/tauri.conf.json)")
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST, help="Manifest JSON output path")
    parser.add_argument("--skip-manifest", action="store_true", help="Do not write the manifest JSON")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the intermediate HTML/PDF files for debugging")
    args = parser.parse_args()

    help_dir = args.help_dir.resolve()
    if not help_dir.exists():
        print(f"ERROR: Help directory not found: {help_dir}", file=sys.stderr)
        sys.exit(1)

    edge = find_edge()
    version = read_version(DEFAULT_TAURI_CONF, args.version)
    nav_titles = parse_nav_titles(NAV_JS)

    print(f"[help-pdf] Edge:        {edge}")
    print(f"[help-pdf] Version:     {version}")
    print(f"[help-pdf] Help dir:    {help_dir}")
    print(f"[help-pdf] Output:      {args.out}")

    product_dashed = apply_brand_naming(args.product)

    with tempfile.TemporaryDirectory(prefix="aurora-help-pdf-", ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        merged_html, appendix_style, appendix_body = build_merged_html(help_dir, args.product, version, nav_titles)
        if not appendix_body.strip():
            print(f"ERROR: раздел «Удаление программы» не найден в {INSTALL_PAGE}.html", file=sys.stderr)
            sys.exit(1)

        merged_html_path = tmp_dir / "merged.html"
        merged_html_path.write_text(merged_html, encoding="utf-8")

        main_pdf = tmp_dir / "main.pdf"
        print("[help-pdf] Printing main pages...")
        print_to_pdf(edge, merged_html_path, main_pdf)

        appendix_html_path = tmp_dir / "appendix.html"
        appendix_html_path.write_text(build_appendix_html(appendix_body, appendix_style), encoding="utf-8")
        appendix_pdf = tmp_dir / "appendix.pdf"
        print("[help-pdf] Printing appendix (uninstall section)...")
        print_to_pdf(edge, appendix_html_path, appendix_pdf)

        logo_path = help_dir / "logo-full.png"
        logo_data_uri = image_to_data_uri(logo_path) if logo_path.exists() else ""

        front_cover_html_path = tmp_dir / "front_cover.html"
        front_cover_html_path.write_text(build_cover_html(args.product, logo_data_uri), encoding="utf-8")
        front_cover_pdf = tmp_dir / "front_cover.pdf"
        print("[help-pdf] Printing front cover...")
        print_to_pdf(edge, front_cover_html_path, front_cover_pdf)

        back_cover_html_path = tmp_dir / "back_cover.html"
        back_cover_html_path.write_text(build_back_cover_html(args.product, logo_data_uri), encoding="utf-8")
        back_cover_pdf = tmp_dir / "back_cover.pdf"
        print("[help-pdf] Printing back cover...")
        print_to_pdf(edge, back_cover_html_path, back_cover_pdf)

        print("[help-pdf] Merging into final PDF...")
        merge_pdfs(front_cover_pdf, main_pdf, appendix_pdf, back_cover_pdf, args.out, product_dashed, version)
        add_page_numbers(args.out)

        if args.keep_temp:
            debug_dir = args.out.parent / "_help_pdf_debug"
            debug_dir.mkdir(exist_ok=True, parents=True)
            shutil.copy(merged_html_path, debug_dir / "merged.html")
            shutil.copy(main_pdf, debug_dir / "main.pdf")
            shutil.copy(appendix_html_path, debug_dir / "appendix.html")
            shutil.copy(appendix_pdf, debug_dir / "appendix.pdf")
            shutil.copy(front_cover_html_path, debug_dir / "front_cover.html")
            shutil.copy(front_cover_pdf, debug_dir / "front_cover.pdf")
            shutil.copy(back_cover_html_path, debug_dir / "back_cover.html")
            shutil.copy(back_cover_pdf, debug_dir / "back_cover.pdf")
            print(f"[help-pdf] Debug files kept in {debug_dir}")

    if not args.skip_manifest:
        manifest = build_manifest(help_dir, version)
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[help-pdf] Manifest:    {args.manifest_out}")

    size_kb = args.out.stat().st_size / 1024
    print(f"[help-pdf] Done: {args.out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
