#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Линтер четверного совпадения команд кабинета «Эконометрист» (Optimizer MMM).

Портировано из ../ROSST_AI_Legal_commercial/tools/check_help_consistency.py
(аудит промптов 2026-07-13, Батч 5) — тот же код Aurora, конфиг под econometrist:
Legal сверяет текст справки <-> плитки <-> cabinet.rs (три точки); здесь готовой
HTML-справки под econometrist нет, поэтому сверяются четыре источника истины
активных команд кабинета:

  cabinet.rs (src-tauri/src/commands/cabinet.rs, блок "econometrist" => vec![...])
    <-> content-packs/cabinets.json (cabinets[].id == "econometrist" .commands[])
    <-> New_AI_Agency/econometrist/.claude/commands/<имя>.md (файл-владелец промпта)
    <-> content-packs/command-meta-data.json (commands["/<имя>"] — описание для UI)

Блокирующие проверки (FAIL, exit 1):
- множество команд econometrist в cabinet.rs, cabinets.json и
  command-meta-data.json должно СОВПАДАТЬ ровно (никто не лишний, никто не
  пропущен) — расхождение значит, что клиент увидит кнопку без описания,
  описание без кнопки или кнопку без промпта;
- для каждой команды cabinet.rs — файл `<имя-без-слэша>.md` должен существовать
  в New_AI_Agency/econometrist/.claude/commands/ (промпт-владелец);
- символ U+2014 «—» запрещён в любом content-packs/*.json (клиентская витрина,
  канон Aurora — короткое тире «–»).

Вывод — по-русски, таблицей источник -> счёт команд, с явным diff-списком
при расхождении.

Использование:
    python tools/check_help_consistency.py

Коды выхода: 0 — все четыре источника согласованы, U+2014 не найден;
             1 — найдено расхождение или U+2014.
"""

import json
import re
import sys
from pathlib import Path

# CI (Windows GitHub runner) отдаёт stdout в cp1252 → русский print падает с
# UnicodeEncodeError. Принудительно UTF-8 (переносимо: CI + lefthook + ручной запуск).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
CABINET_RS = REPO_ROOT / "src-tauri" / "src" / "commands" / "cabinet.rs"
CABINETS_JSON = REPO_ROOT / "content-packs" / "cabinets.json"
COMMAND_META_JSON = REPO_ROOT / "content-packs" / "command-meta-data.json"
COMMANDS_DIR = REPO_ROOT / "New_AI_Agency" / "econometrist" / ".claude" / "commands"
LEGACY_COMMANDS_MD = REPO_ROOT / "New_AI_Agency" / "econometrist" / "LEGACY_COMMANDS.md"
CONTENT_PACKS_DIR = REPO_ROOT / "content-packs"

CABINET_ID = "econometrist"
EM_DASH = "—"


def parse_commands_from_rust() -> list:
    """Команды блока "econometrist" => vec![...] из cabinet.rs (с ведущим /)."""
    if not CABINET_RS.exists():
        return []

    text = CABINET_RS.read_text(encoding="utf-8")
    # Тот же паттерн, что в Legal check_help_consistency.py: блок кабинета -> вырезать
    # тело до закрывающего "]," на своей строке.
    block_match = re.search(
        r'"' + re.escape(CABINET_ID) + r'"\s*=>\s*vec!\[(.*?)\n\s*\],',
        text,
        re.DOTALL,
    )
    if not block_match:
        return []
    block = block_match.group(1)
    return re.findall(r'\(\s*"(/[\w\-]+)"', block)


def parse_commands_from_cabinets_json() -> list:
    """Команды кабинета econometrist из cabinets.json (с ведущим /)."""
    if not CABINETS_JSON.exists():
        return []
    data = json.loads(CABINETS_JSON.read_text(encoding="utf-8"))
    for cab in data.get("cabinets", []):
        if cab.get("id") == CABINET_ID:
            return [c["command"] for c in cab.get("commands", [])]
    return []


def parse_commands_from_meta() -> list:
    """Ключи command-meta-data.json, относящиеся к активным командам econometrist
    (пересекаются со множеством cabinet.rs, чтобы не путать с legacy /mmm-* и
    другими кабинетами, у которых те же имена ключей в общем словаре нет)."""
    if not COMMAND_META_JSON.exists():
        return []
    data = json.loads(COMMAND_META_JSON.read_text(encoding="utf-8"))
    return sorted(data.get("commands", {}).keys())


def parse_legacy_command_stems() -> set:
    """Стемы legacy /mmm-* команд из LEGACY_COMMANDS.md (SSOT).

    Скрыты из грида (cabinet.rs их не выводит), но файлы-владельцы в
    .claude/commands/ легитимно существуют — ручной ввод в поле работает
    (backward compat). Нужны для orphan-проверки ниже: без них 9 legacy-файлов
    считались бы мусором и давали ложный FAIL."""
    if not LEGACY_COMMANDS_MD.exists():
        return set()
    text = LEGACY_COMMANDS_MD.read_text(encoding="utf-8")
    return set(re.findall(r"/(mmm-[\w\-]+)", text))


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def check_em_dash() -> list:
    """U+2014 запрещён в любом content-packs/*.json (клиентская витрина)."""
    fails = []
    if not CONTENT_PACKS_DIR.exists():
        return fails
    for path in sorted(CONTENT_PACKS_DIR.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            fails.append(f"{relpath(path)}: файл не читается как UTF-8 ({exc})")
            continue
        count = text.count(EM_DASH)
        if count:
            fails.append(f"{relpath(path)}: найден символ длинного тире «—» ({count}×) — использовать короткое тире «–»")
    return fails


def check_commands() -> tuple:
    """Возвращает (fails: list[str], row: dict) сверки трёх множеств команд + файлов."""
    fails = []

    rust_cmds = set(parse_commands_from_rust())
    json_cmds = set(parse_commands_from_cabinets_json())
    meta_cmds = set(parse_commands_from_meta())

    if not rust_cmds:
        fails.append(f"cabinet.rs: не найден блок \"{CABINET_ID}\" => vec![...] — парсинг невозможен")

    # cabinet.rs <-> cabinets.json: должны совпадать РОВНО (это источники грида).
    only_rust = rust_cmds - json_cmds
    only_json = json_cmds - rust_cmds
    if only_rust:
        fails.append(f"есть в cabinet.rs, отсутствуют в cabinets.json: {', '.join(sorted(only_rust))}")
    if only_json:
        fails.append(f"есть в cabinets.json, отсутствуют в cabinet.rs: {', '.join(sorted(only_json))}")

    # cabinet.rs -> command-meta-data.json: каждая активная команда должна иметь описание
    # (meta_cmds — общий словарь всех кабинетов, поэтому проверяем только подмножество).
    missing_meta = rust_cmds - meta_cmds
    if missing_meta:
        fails.append(
            f"есть в cabinet.rs, нет описания в command-meta-data.json: {', '.join(sorted(missing_meta))}"
        )

    # cabinet.rs -> файл-владелец промпта в .claude/commands/.
    missing_files = []
    for cmd in sorted(rust_cmds):
        fname = cmd.lstrip("/") + ".md"
        if not (COMMANDS_DIR / fname).exists():
            missing_files.append(fname)
    if missing_files:
        fails.append(
            f"есть в cabinet.rs, нет файла-промпта в .claude/commands/: {', '.join(missing_files)}"
        )

    # ОБРАТНАЯ сторона (иначе «четверное совпадение» одностороннее): файл-промпт
    # без активной команды в cabinet.rs И без записи в LEGACY_COMMANDS.md — это
    # осиротевший .md (переименование команды/мусор), который молча попадёт в
    # сборку vault. Legacy /mmm-* легитимны (SSOT — LEGACY_COMMANDS.md).
    grid_stems = {c.lstrip("/") for c in rust_cmds}
    legacy_stems = parse_legacy_command_stems()
    file_stems = {p.stem for p in COMMANDS_DIR.glob("*.md")} if COMMANDS_DIR.exists() else set()
    orphan_files = sorted(file_stems - grid_stems - legacy_stems)
    if orphan_files:
        fails.append(
            "файл-промпт в .claude/commands/ без команды в cabinet.rs и без записи "
            f"в LEGACY_COMMANDS.md (осиротел/переименован?): {', '.join(s + '.md' for s in orphan_files)}"
        )
    # Legacy задокументирована в LEGACY_COMMANDS.md, но файла-владельца нет —
    # документация обещает промпт, которого нет (ручной ввод сломается).
    legacy_missing = sorted(legacy_stems - file_stems)
    if legacy_missing:
        fails.append(
            "команда описана в LEGACY_COMMANDS.md, но нет файла-промпта в "
            f".claude/commands/: {', '.join(s + '.md' for s in legacy_missing)}"
        )

    row = {
        "cabinet_rs": len(rust_cmds),
        "cabinets_json": len(json_cmds),
        "meta_covered": len(rust_cmds & meta_cmds),
    }
    return fails, row


def print_table(row: dict):
    print(f"{'Источник':<32} {'команд':<8}")
    print(f"{'cabinet.rs (econometrist)':<32} {row['cabinet_rs']:<8}")
    print(f"{'cabinets.json (econometrist)':<32} {row['cabinets_json']:<8}")
    print(f"{'command-meta-data.json (покрыто)':<32} {row['meta_covered']:<8}")


def main() -> int:
    if not CABINET_RS.exists():
        print(f"FAIL: не найден {relpath(CABINET_RS)} — проверка невозможна.")
        return 1

    all_fails, row = check_commands()
    all_fails.extend(check_em_dash())

    print("Линтер четверного совпадения (econometrist): cabinet.rs <-> cabinets.json "
          "<-> .claude/commands/*.md <-> command-meta-data.json\n")
    print_table(row)

    if all_fails:
        print(f"\nFAIL ({len(all_fails)}):")
        for f in all_fails:
            print(f"  - {f}")
        return 1

    print("\nOK: команды econometrist согласованы (cabinet.rs = cabinets.json = файлы промптов "
          "= описания в command-meta-data.json), U+2014 не найден в content-packs/*.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
