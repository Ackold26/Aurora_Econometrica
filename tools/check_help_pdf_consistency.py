#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Линтер PDF-инфраструктуры справки Aurora AI Econometrica.

Область: src-tauri/help-econometrica/*.html + econ-nav.js + собранный
tools/build_help_pdf.py. ⚠️ ОТДЕЛЬНЫЙ файл от tools/check_help_consistency.py -
тот проверяет четверное совпадение команд кабинета econometrist (cabinet.rs
<-> content-packs/cabinets.json <-> New_AI_Agency/econometrist/.claude/commands/
*.md <-> content-packs/command-meta-data.json) - совсем другая область
(промпты чат-кабинета, а не HTML-справка). Портировано из
Dev/Aurora_Oracle/tools/check_help_consistency.py (волна 2 стандарт-свипа,
2026-07-19) - взята ТОЛЬКО PDF-инфраструктурная часть (версия/свежесть/
копирайт/тире/nav<->файлы); слэш-командная сверка команд кабинета НЕ
портирована - у Econometrica её уже делает check_help_consistency.py на
своих четырёх источниках, дублировать не нужно.

Блокирующие проверки (FAIL, exit 1):
1. econ-nav.js: каждый id из PAGES имеет файл <id>.html на диске, и наоборот -
   каждый *.html в src-tauri/help-econometrica/ (кроме служебных ассетов)
   упомянут в PAGES econ-nav.js - иначе страница физически недостижима из
   справочного центра (орфан).
2. U+2014 «—» (литерал + HTML-сущности &mdash;/&#8212;/&#x2014;) запрещён во
   всех src-tauri/help-econometrica/*.html.
3. CPD-09: «Сипович»/«sipovich» запрещены в любом html справки; канон
   «© 2026 ООО «Платформа Аврора»» должен встречаться хотя бы один раз
   (footer) - иначе копирайт откатился на старый.
4. Версия: tauri.conf.json "version" должен равняться "version" из
   package.json (FAIL при расхождении - канон один). Вхождения vX.Y.Z внутри
   *.html - WARN, не FAIL: ревизией контента 2026-07-19 подтверждено, что
   methodology.html/econometrica.html несут ЛЕГИТИМНЫЕ исторические пометки
   версии фичи («Level 3 - Brand vs Performance split (v1.1.0)», «Что нового
   в v1.0.16» - когда фича появилась, часть блоков auto-generated
   tools/sync_help_lists.py, «do not edit manually») - это не заявление
   «текущая версия справки», жёсткий FAIL по ним дал бы перманентный
   ложный красный гейт.
5. Свежесть PDF-справки (WARN, не FAIL, если манифеста ещё нет): sha256 всех
   src-tauri/help-econometrica/*.html + econ-nav.js должны совпадать с
   tools/help_pdf_manifest.json, и econometrica-help.pdf должен существовать
   в src-tauri/help-econometrica/ (Econometrica доставляет справку БАНДЛОМ,
   не content-pack каналом - см. content_pack::help_file_path: content-packs/
   help/ у Econometrica не существует - поэтому здесь только ОДИН канал,
   паритет bundle<->content-pack (как у Oracle/Legal) НЕ проверяется - у
   Econometrica такого второго канала нет).
6. INV-50 (частотный vs байесовский интервал, см. tools/lint_prompt_commands.py
   для той же логики в промптах): «доверительный интервал», отдельно стоящая
   кириллическая аббревиатура «ДИ» и отдельно стоящая латинская «CI» запрещены
   в клиентском тексте *.html - байесовский интервал называется «правдоподобный
   диапазон». Исключения: содержимое HTML-комментариев <!-- ... --> не
   проверяется; строки с разрешённым en-термином «Credible Interval»
   (глоссарий, en-бейдж) пропускаются целиком; IPC-идентификаторы вида
   posterior_ci/#posterior_ci не задеты - паттерн требует границ слова и точного
   регистра «CI», строчное «ci» внутри id/anchor не матчится.

Пустой результат извлечения (0 id в econ-nav.js) - громкий FAIL «парсер
сломан», а не тихий OK.

Вывод - по-русски. Коды выхода: 0 - всё согласовано (WARN не блокирует);
1 - найден хотя бы один FAIL.

Использование:
    python tools/check_help_pdf_consistency.py
"""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HELP_DIR = REPO_ROOT / "src-tauri" / "help-econometrica"
NAV_JS = HELP_DIR / "econ-nav.js"
PDF_MANIFEST = REPO_ROOT / "tools" / "help_pdf_manifest.json"
PDF_NAME = "econometrica-help.pdf"
TAURI_CONF = REPO_ROOT / "src-tauri" / "tauri.conf.json"
PACKAGE_JSON = REPO_ROOT / "package.json"

# Ассеты справки, которые НЕ являются html-страницами и не обязаны быть в
# econ-nav.js PAGES (шаблоны xlsx, лого, скрипт удаления, сам econ-nav.js).
NON_PAGE_ASSETS = {"econ-nav.js"}

EM_DASH = "—"
EM_DASH_ENTITY_RE = re.compile(r"&mdash;|&#8212;|&#x2014;", re.IGNORECASE)
VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b")
COPYRIGHT_RE = re.compile(r"©\s*2026\s*ООО\s*«Платформа Аврора»")
SIPOVICH_RE = re.compile(r"[СS]ипович|sipovich", re.IGNORECASE)

# INV-50: частотный «доверительный интервал»/«ДИ»/«CI» запрещены в клиентском
# тексте - байесовский интервал называется «правдоподобный диапазон» (см.
# tools/lint_prompt_commands.py - тот же запрет для промптов кабинета).
# «ДИ»/«CI» - строго заглавными и с границами слова (не Cyrillic/Latin буква
# по краям), чтобы не ловить «ДИапазон», «видит» или lowercase id/anchor вида
# posterior_ci.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
DOVERIT_RE = re.compile(r"(?i:доверительн\w*)")
DI_ABBR_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])ДИ(?![A-Za-zА-Яа-яЁё])")
CI_ABBR_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])CI(?![A-Za-zА-Яа-яЁё])")
CREDIBLE_INTERVAL_MARK = "Credible Interval"


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── econ-nav.js <-> файлы на диске ─────────────────────────────────────

def parse_nav_pages(text: str) -> list:
    m = re.search(r"const PAGES\s*=\s*\[(.*?)\n\s*\];", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r"id:\s*'([\w-]+)'", m.group(1))


def check_nav_js(all_html_files) -> list:
    if not NAV_JS.exists():
        return [f"{relpath(NAV_JS)}: файл не найден"]

    text = read_text(NAV_JS)
    ids = parse_nav_pages(text)
    fails = []

    if not ids:
        fails.append(f"{relpath(NAV_JS)}: не удалось извлечь ни одного id из PAGES — парсер сломан или структура изменилась")
        return fails

    for page_id in ids:
        if not (HELP_DIR / f"{page_id}.html").exists():
            fails.append(f"{relpath(NAV_JS)}: PAGES содержит id '{page_id}', но файл {page_id}.html не найден")

    id_set = set(ids)
    for path in all_html_files:
        if path.name in NON_PAGE_ASSETS:
            continue
        page_id = path.stem
        if page_id not in id_set:
            fails.append(f"{relpath(path)}: страница есть на диске, но отсутствует в PAGES econ-nav.js (орфан, недостижима из справочного центра)")

    return fails


# ── U+2014 ──────────────────────────────────────────────────────────────

def check_em_dash(all_html_files) -> list:
    fails = []
    for path in all_html_files:
        text = read_text(path)
        count = text.count(EM_DASH)
        if count:
            fails.append(f"{relpath(path)}: найден символ длинного тире «—» ({count}×) — использовать короткое тире «-»")
        entity_matches = EM_DASH_ENTITY_RE.findall(text)
        if entity_matches:
            counts = Counter(m.lower() for m in entity_matches)
            detail = ", ".join(f"{form}×{n}" for form, n in counts.items())
            fails.append(f"{relpath(path)}: найдена HTML-сущность длинного тире ({detail}) — использовать короткое тире «-»")
    return fails


# ── INV-50 (доверительный интервал / ДИ / CI в клиентском тексте) ──────

def _strip_html_comments_keep_lines(text: str) -> str:
    """Вырезает <!-- ... --> целиком, сохраняя число строк (переносы внутри
    комментария заменяются тем же числом переносов) - иначе номера строк
    после многострочного комментария разъедутся с оригиналом файла."""
    return HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def check_inv50_terms(all_html_files) -> list:
    fails = []
    for path in all_html_files:
        text = _strip_html_comments_keep_lines(read_text(path))
        for line_no, line in enumerate(text.splitlines(), start=1):
            if CREDIBLE_INTERVAL_MARK in line:
                continue
            for m in DOVERIT_RE.finditer(line):
                fails.append(
                    f"{relpath(path)}:{line_no}: найден запрещённый термин «{m.group(0)}» — "
                    f"байесовский интервал называется «правдоподобный диапазон» (INV-50): {line.strip()}"
                )
            for _ in DI_ABBR_RE.finditer(line):
                fails.append(
                    f"{relpath(path)}:{line_no}: найдена запрещённая аббревиатура «ДИ» — "
                    f"байесовский интервал называется «правдоподобный диапазон» (INV-50): {line.strip()}"
                )
            for _ in CI_ABBR_RE.finditer(line):
                fails.append(
                    f"{relpath(path)}:{line_no}: найдена запрещённая аббревиатура «CI» — "
                    "байесовский интервал называется «правдоподобный диапазон» (INV-50); "
                    f"en-термин «Credible Interval» разрешён: {line.strip()}"
                )
    return fails


# ── Копирайт / CPD-09 ──────────────────────────────────────────────────

def check_copyright(all_html_files) -> list:
    fails = []
    any_copyright = False
    for path in all_html_files:
        text = read_text(path)
        sipovich_matches = SIPOVICH_RE.findall(text)
        if sipovich_matches:
            fails.append(
                f"{relpath(path)}: найдено «{sipovich_matches[0]}» ({len(sipovich_matches)}×) — "
                "старый копирайт запрещён (CPD-09), канон «© 2026 ООО «Платформа Аврора»»"
            )
        if COPYRIGHT_RE.search(text):
            any_copyright = True
    if not any_copyright:
        fails.append("ни один файл справки не содержит канонический копирайт «© 2026 ООО «Платформа Аврора»»")
    return fails


# ── Версия в справке ──────────────────────────────────────────────────

def check_version_consistency(all_html_files) -> tuple:
    if not TAURI_CONF.exists():
        return [], [f"{relpath(TAURI_CONF)} не найден — проверка версии в справке пропущена"]

    try:
        conf = json.loads(read_text(TAURI_CONF))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{relpath(TAURI_CONF)}: невалидный JSON ({exc})"], []

    current_version = conf.get("version")
    if not current_version:
        return [f"{relpath(TAURI_CONF)}: поле 'version' отсутствует — проверка версии невозможна"], []

    fails = []
    warns = []

    if PACKAGE_JSON.exists():
        try:
            pkg = json.loads(read_text(PACKAGE_JSON))
            pkg_version = pkg.get("version")
            if pkg_version and pkg_version != current_version:
                fails.append(
                    f"{relpath(PACKAGE_JSON)}: версия «{pkg_version}» != tauri.conf.json «{current_version}»"
                )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            warns.append(f"{relpath(PACKAGE_JSON)}: невалидный JSON ({exc}) — сверка версии package.json пропущена")
    else:
        warns.append(f"{relpath(PACKAGE_JSON)} не найден — сверка версии package.json пропущена")

    # WARN, не FAIL - см. докстринг файла, пункт 4: легитимные исторические
    # пометки версии фичи (methodology.html/econometrica.html), не заявление
    # «текущая версия справки».
    for path in all_html_files:
        text = read_text(path)
        for m in VERSION_RE.finditer(text):
            found = m.group(1)
            if found == current_version:
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            warns.append(
                f"{relpath(path)}:{line_no}: версия «v{found}» != текущей версии tauri.conf.json «{current_version}» (проверь: историческая пометка фичи или забытый бамп?)"
            )
    return fails, warns


# ── PDF-свежесть ───────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def check_pdf_freshness() -> tuple:
    """Возвращает (fails, warns). Манифест производит tools/build_help_pdf.py
    из src-tauri/help-econometrica/*.html. Econometrica доставляет справку
    БАНДЛОМ (не content-pack каналом, как Oracle/Legal) - content-packs/help/
    у продукта не существует (content_pack::help_file_path всегда возвращает
    None) - поэтому здесь только ОДИН канал, паритет bundle<->content-pack
    проверять не нужно."""
    if not PDF_MANIFEST.exists():
        return [], [f"{relpath(PDF_MANIFEST)} не найден — PDF-конвейер ещё не построен, проверка свежести PDF пропущена (не блокирует)"]

    fails = []
    try:
        manifest = json.loads(read_text(PDF_MANIFEST))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{relpath(PDF_MANIFEST)}: невалидный JSON манифеста ({exc})"], []

    files_manifest = manifest.get("sources", {})
    if not files_manifest:
        fails.append(f"{relpath(PDF_MANIFEST)}: манифест не содержит секцию 'sources' — PDF устарел, перегенерируй tools/build_help_pdf.py")
        return fails, []

    tracked = sorted(HELP_DIR.glob("*.html")) + ([NAV_JS] if NAV_JS.exists() else [])
    tracked_names = {p.name for p in tracked}

    for p in tracked:
        actual_hash = sha256_file(p)
        expected_hash = files_manifest.get(p.name)
        if expected_hash is None:
            fails.append(f"{p.name}: отсутствует в манифесте PDF — PDF устарел, перегенерируй tools/build_help_pdf.py")
        elif expected_hash != actual_hash:
            fails.append(f"{p.name}: sha256 разошёлся с манифестом — PDF устарел, перегенерируй tools/build_help_pdf.py")

    for tracked_name in files_manifest:
        if tracked_name not in tracked_names:
            fails.append(f"{tracked_name}: в манифесте, но файл отсутствует на диске — перегенерируй tools/build_help_pdf.py")

    bundle_pdf = HELP_DIR / PDF_NAME
    if not bundle_pdf.exists():
        fails.append(f"{relpath(bundle_pdf)}: PDF не найден — перегенерируй tools/build_help_pdf.py")

    return fails, []


# ── Вывод ──────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    if not HELP_DIR.exists():
        print(f"FAIL: не найдена {relpath(HELP_DIR)} — проверка невозможна.")
        return 1

    all_html_files = sorted(HELP_DIR.glob("*.html"))
    if not all_html_files:
        print(f"FAIL: в {relpath(HELP_DIR)} не найдено ни одного *.html — парсер, вероятно, сломан.")
        return 1

    all_fails = []
    all_warns = []

    all_fails.extend(check_nav_js(all_html_files))
    all_fails.extend(check_em_dash(all_html_files))
    all_fails.extend(check_inv50_terms(all_html_files))
    all_fails.extend(check_copyright(all_html_files))

    version_fails, version_warns = check_version_consistency(all_html_files)
    all_fails.extend(version_fails)
    all_warns.extend(version_warns)

    pdf_fails, pdf_warns = check_pdf_freshness()
    all_fails.extend(pdf_fails)
    all_warns.extend(pdf_warns)

    print(f"Линтер PDF-инфраструктуры справки Aurora AI Econometrica: {len(all_html_files)} html-страниц, econ-nav.js, манифест PDF\n")

    if all_warns:
        print(f"WARN ({len(all_warns)}):")
        for w in all_warns:
            print(f"  - {w}")
        print()

    if all_fails:
        print(f"FAIL ({len(all_fails)}):")
        for f in all_fails:
            print(f"  - {f}")
        return 1

    print("OK: econ-nav.js <-> файлы согласованы, U+2014 не найден, «доверительный интервал»/«ДИ»/«CI» "
          "в клиентском тексте не найдены (INV-50), копирайт «Платформа Аврора» на месте, "
          "версия tauri.conf.json = package.json, PDF свежий.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
