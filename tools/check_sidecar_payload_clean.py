#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка чистоты нагрузки движка перед сборкой установщика (вариант E, s52, 2026-09-27).

Зачем: ресурс движка в `bundle.resources` берёт каталог `_internal/` ЦЕЛИКОМ.
`build_sidecar.py::purge_test_residue` чистит его только сразу после PyInstaller, а
если между сборкой движка и сборкой Tauri запустить exe движка из дерева (numba пишет
кэш в `_internal\\...\\__pycache__`) или тесты, импортирующие из `_internal`, мусор уедет
покупателю. Следы такого уже есть: хвосты от 14.09 08:29 – после сужения ресурса
(Projects/PROBE_s50_leftovers.md §6, «Остаточная щель»).

Что проверяет: только ту часть `sidecar/econometrica/`, что уезжает в поставку, – пути
берутся из `src-tauri/tauri.conf.json` → `bundle.resources` (записи, начинающиеся с
`../sidecar/econometrica/`), а не зашиты здесь. Запрещены каталоги `__pycache__` и
`.hypothesis`, файлы `*.nbi` и `*.nbc` (кэш numba).

Пустой обход – НЕ «чисто»: если ресурсов движка в конфиге нет, хоть одного из них нет на
диске или не нашлось ни одного файла, скрипт падает с кодом 2 – проверка, которая ничего
не увидела, ничего и не доказала.

Использование:
    python tools/check_sidecar_payload_clean.py

Коды выхода: 0 – чисто; 1 – найден мусор (перечень в выводе); 2 – проверять нечего.
Никуда не встроен (ни lefthook, ни CI) – решение о встраивании за оркестратором.
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
TAURI_DIR = REPO_ROOT / "src-tauri"
CONF = TAURI_DIR / "tauri.conf.json"
ENGINE_PREFIX = "../sidecar/econometrica/"

BAD_DIRS = {"__pycache__", ".hypothesis"}
BAD_SUFFIXES = {".nbi", ".nbc"}


def engine_resources() -> list[str]:
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    resources = conf.get("bundle", {}).get("resources", [])
    # resources бывает и словарём {источник: цель} – берём ключи-источники.
    if isinstance(resources, dict):
        resources = list(resources.keys())
    return [r for r in resources if r.replace("\\", "/").startswith(ENGINE_PREFIX)]


def scan(entry: str, bad: list[str]) -> int | None:
    """Обходит одну запись ресурса; возвращает число просмотренных файлов, None – записи нет на диске."""
    path = (TAURI_DIR / entry).resolve()
    if any(ch in entry for ch in "*?["):
        raise SystemExit(f"FAIL: шаблон в ресурсе движка не поддержан: {entry}")
    if not path.exists():
        print(f"  нет на диске: {entry} → {path}")
        return None
    if path.is_file():
        if path.suffix.lower() in BAD_SUFFIXES:
            bad.append(str(path.relative_to(REPO_ROOT)))
        return 1
    seen = 0
    for p in path.rglob("*"):
        rel = p.relative_to(path)
        if p.is_dir():
            if p.name in BAD_DIRS:
                bad.append(str(p.relative_to(REPO_ROOT)) + "\\")
            continue
        seen += 1
        # Файл внутри запрещённого каталога уже покрыт строкой о каталоге.
        if any(part in BAD_DIRS for part in rel.parts[:-1]):
            continue
        if p.suffix.lower() in BAD_SUFFIXES:
            bad.append(str(p.relative_to(REPO_ROOT)))
    return seen


def main() -> int:
    entries = engine_resources()
    if not entries:
        print(f"FAIL(2): в {CONF.relative_to(REPO_ROOT)} нет ресурсов с приставкой {ENGINE_PREFIX}")
        return 2
    print("Ресурсы движка из bundle.resources:")
    bad: list[str] = []
    total = 0
    missing = 0
    for e in entries:
        n = scan(e, bad)
        if n is None:
            missing += 1
            continue
        print(f"  {e}: файлов {n}")
        total += n
    if missing:
        print(f"FAIL(2): {missing} ресурс(а) движка нет на диске – проверка неполна (движок не собран?)")
        return 2
    if total == 0:
        print("FAIL(2): не просмотрено ни одного файла – проверять нечего (движок не собран?)")
        return 2
    if bad:
        print(f"FAIL(1): мусор в нагрузке движка – {len(bad)} шт.:")
        for b in sorted(bad):
            print(f"  {b}")
        return 1
    print(f"OK: просмотрено файлов {total}, __pycache__/.hypothesis/*.nbi/*.nbc нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
