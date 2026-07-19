#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Линтер синхронности глоссария Aurora AI Econometrica (SSOT).

Область: docs/GLOSSARY_v2_1_0.md + LEGACY_ONLY (tools/build_glossary.py) —
единый источник, из которого генератор собирает три выхода:
  • docs/glossary.json
  • src-tauri/help-econometrica/glossary.html
  • src/lib/glossary.js

Проблема, которую ловит линтер: правку вносят прямо в выход (json/html/js),
источник не трогают — выход дрейфует, следующая перегенерация даёт тихий
регресс (правка потеряна) или, наоборот, перегенерация из актуального
источника расходится с тем, что реально лежит в репозитории.

Блокирующие проверки (FAIL, exit 1):
1. Синхронность выходов с источником — генератор прогоняется во временную
   директорию (рабочие файлы не трогаются), каждый temp-файл сравнивается
   с соответствующим рабочим выходом. Сравнение нормализовано по переносам
   строк (\\r\\n → \\n): core.autocrlf=true в этом репозитории кладёт CRLF
   в рабочие файлы на диске, а свежесгенерённый Python-файл пишется с LF —
   без нормализации линтер давал бы ложный FAIL после каждого `git checkout`.
2. 0×U+2014 «—» в трёх рабочих выходах — клиентский текст обязан нести
   короткое тире «–». Нормализация `_norm_dash` в генераторе покрывает
   только текстовые поля терминов (term/en/short/what/example/where), но
   НЕ секции/статичные строки HTML-шаблона — этот гейт на выходах ловит
   протечку тире откуда угодно, а не только из полей термина.

Вывод — по-русски. Коды выхода: 0 — выходы синхронны с источником, U+2014
не найден; 1 — найден хотя бы один FAIL.

Использование:
    python tools/check_glossary_sync.py
"""

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"

OUT_JSON = ROOT / "docs" / "glossary.json"
OUT_HTML = ROOT / "src-tauri" / "help-econometrica" / "glossary.html"
OUT_JS = ROOT / "src" / "lib" / "glossary.js"

EM_DASH = "—"


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ── Проверка 1: перегенерация из источника == рабочие выходы ───────────

def _regenerate_to_tempdir():
    """Прогоняет tools/build_glossary.py в temp-выходы (bg.MD — реальный
    источник, bg.OUT_* подменены на tempdir), рабочее дерево не трогает.
    Возвращает (tempdir, {рабочий_путь: temp_путь})."""
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import build_glossary as bg  # noqa: PLC0415 — намеренно поздний импорт

    tempdir = Path(tempfile.mkdtemp(prefix="econ_glossary_check_"))
    tmp_json = tempdir / "glossary.json"
    tmp_html = tempdir / "glossary.html"
    tmp_js = tempdir / "glossary.js"

    orig_out = (bg.OUT_JSON, bg.OUT_HTML, bg.OUT_JS)
    bg.OUT_JSON, bg.OUT_HTML, bg.OUT_JS = tmp_json, tmp_html, tmp_js
    try:
        # генератор печатает свою диагностику (WARN про заголовки без id,
        # [OK] со счётчиком терминов) — линтеру она не нужна, глушим,
        # но не мешаем SystemExit пробиться (guard на CRITICAL_IDS/LEGACY_IDS).
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            bg.build()
    except SystemExit as exc:
        shutil.rmtree(tempdir, ignore_errors=True)
        raise RuntimeError(f"генератор tools/build_glossary.py упал: {exc.code}") from exc
    finally:
        bg.OUT_JSON, bg.OUT_HTML, bg.OUT_JS = orig_out

    return tempdir, {OUT_JSON: tmp_json, OUT_HTML: tmp_html, OUT_JS: tmp_js}


def _normalized_lines(path: Path) -> list:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()


def _first_diff(work: Path, gen: Path) -> str | None:
    """None, если файлы идентичны после нормализации переносов строк —
    иначе описание первого расхождения (номер строки + фрагменты)."""
    work_lines = _normalized_lines(work)
    gen_lines = _normalized_lines(gen)
    if work_lines == gen_lines:
        return None
    for i, (a, b) in enumerate(zip(work_lines, gen_lines), start=1):
        if a != b:
            return (f"первое расхождение на строке {i}: рабочий файл имеет "
                     f"«{a[:120]}», перегенерация из источника даёт «{b[:120]}»")
    return (f"расходится число строк: рабочий {len(work_lines)}, "
            f"перегенерация {len(gen_lines)} (хвост начиная со строки "
            f"{min(len(work_lines), len(gen_lines)) + 1})")


def check_sync() -> list:
    fails = []
    tempdir = None
    try:
        tempdir, mapping = _regenerate_to_tempdir()
        for work, gen in mapping.items():
            if not work.exists():
                fails.append(f"{relpath(work)}: рабочий выход не найден")
                continue
            diff = _first_diff(work, gen)
            if diff:
                fails.append(
                    f"{relpath(work)}: разошёлся с перегенерацией из источника "
                    f"({diff}) — выход правлен вручную либо забыт прогон "
                    "`python tools/build_glossary.py` — правьте ИСТОЧНИК "
                    "(docs/GLOSSARY_v2_1_0.md / LEGACY_ONLY) и пересоберите"
                )
    except RuntimeError as exc:
        fails.append(str(exc))
    finally:
        if tempdir is not None:
            shutil.rmtree(tempdir, ignore_errors=True)
    return fails


# ── Проверка 2: 0×U+2014 в рабочих выходах ──────────────────────────────

def check_no_em_dash() -> list:
    fails = []
    for path in (OUT_JSON, OUT_HTML, OUT_JS):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            count = line.count(EM_DASH)
            if not count:
                continue
            idx = line.index(EM_DASH)
            snippet = line[max(0, idx - 40): idx + 40].strip()
            fails.append(
                f"{relpath(path)}:{line_no}: найден символ длинного тире «—» "
                f"({count}×) — использовать короткое тире «-»: {snippet}"
            )
    return fails


# ── Вывод ──────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    all_fails = []
    all_fails.extend(check_sync())
    all_fails.extend(check_no_em_dash())

    print("Линтер синхронности глоссария Aurora AI Econometrica: "
          "источник (docs/GLOSSARY_v2_1_0.md + LEGACY_ONLY) <-> 3 выхода "
          "(docs/glossary.json, src-tauri/help-econometrica/glossary.html, src/lib/glossary.js)\n")

    if all_fails:
        print(f"FAIL ({len(all_fails)}):")
        for f in all_fails:
            print(f"  - {f}")
        return 1

    print("OK: 3 выхода синхронны с источником, U+2014 не найден.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
