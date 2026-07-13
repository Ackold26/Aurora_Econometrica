#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Линтер структуры промптов slash-команд кабинета «Эконометрист» (Optimizer MMM).

Область:
- New_AI_Agency/econometrist/.claude/commands/*.md (8 активных + 9 legacy /mmm-*);
- New_AI_Agency/econometrist/CLAUDE.md (системный промпт кабинета);
- New_AI_Agency/econometrist/LEGACY_COMMANDS.md (индекс расчётных legacy-команд).

Портировано из ../ROSST_AI_Legal_commercial/tools/lint_prompt_commands.py (аудит
промптов 2026-07-13, Батч 5) — тот же код Aurora, конфиг под econometrist:
периметр один кабинет (не три lawyer-*), без «pip install»-запрета (legacy-команды
по design используют Python/PyMC-Marketing — см. LEGACY_COMMANDS.md), без
мин-строк/секций-стандарта (в этом корпусе не вводились), плюс два новых
econometrist-специфичных правила: запрет «доверительный интервал»/«CI» в
клиентском тексте (байесовские интервалы называются «правдоподобный диапазон»,
Батч 2) и запрет паттернов блокировки диалога.

Режимы:
- без аргументов: проверить все файлы области (полный прогон, CI/вручную);
- с путями файлов аргументами: проверить только переданные файлы (lefthook по staged).

Блокирующие проверки (FAIL, exit 1), по каждому файлу области:
- символ U+2014 «—» (длинное тире) запрещён — клиентский текст использует
  короткое тире «–» (канон Aurora, см. CLAUDE.md репо);
- «доверительный интервал» / отдельное слово «CI» запрещены в клиентском тексте —
  байесовские интервалы называются «правдоподобный диапазон» (Батч 2, INV-50:
  не путать частотный ДИ с байесовским HDI/quantile-интервалом). Вхождение внутри
  кавычек-«ёлочек» `«доверительный интервал»` — исключение: это цитирование
  запрещённого термина внутри самого правила («называй X, а не «Y»»), не
  использование в клиентском тексте;
- языковая шапка первой строкой файла ДОЛЖНА точно совпадать с эталоном
  (единая для всех команд кабинета, проверено дословным сравнением) —
  применяется только к файлам .claude/commands/*.md, не к CLAUDE.md/LEGACY_COMMANDS.md
  (у них своя структура документа, не команда с шапкой);
- паттерн блокировки диалога запрещён: «ОСТАНОВИСЬ», «не продолжай», «жди ввода»,
  «не генерируй» — команда не должна замораживать выполнение (отличать от
  допустимой деградации «сначала выполните /X», которая просто указывает
  порядок команд и не блокирует).

Вывод — по-русски, компактно: OK n файлов / FAIL список.

Использование:
    python tools/lint_prompt_commands.py              # полный прогон области
    python tools/lint_prompt_commands.py <path> ...    # только переданные файлы

Коды выхода: 0 — 0 FAIL; 1 — найден хотя бы один FAIL.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CABINET_DIR = REPO_ROOT / "New_AI_Agency" / "econometrist"
COMMANDS_GLOB = "New_AI_Agency/econometrist/.claude/commands/*.md"
CABINET_CLAUDE_MD = CABINET_DIR / "CLAUDE.md"
LEGACY_COMMANDS_MD = CABINET_DIR / "LEGACY_COMMANDS.md"

EM_DASH = "—"

LANGUAGE_HEADER = (
    "ЯЗЫК ОТВЕТА: РУССКИЙ. Все выводы, таблицы, рекомендации, статусы – на русском "
    "языке. Английский только для устоявшихся терминов: ROI, CPM, GRP, MQS, R-hat, "
    "MAPE, adstock."
)

# Часть «довер…интервал» — регистронезависимо (scoped-флаг (?i:…)): «ДОВЕРИТЕЛЬНЫЙ
# ИНТЕРВАЛ» капсом (заголовок/акцент) обязан ловиться так же (аудит 2026-07-13).
# Часть «CI» — намеренно строго заглавными (не ловить «ci» внутри слов), поэтому
# глобальный IGNORECASE неприменим; регистронезависимость — только на первой ветви.
CI_TERM_RE = re.compile(r"(?i:довер(?:ительн\w*)\s+интервал\w*)|(?<![A-Za-zА-Яа-яЁё])CI(?![A-Za-zА-Яа-яЁё])")
# Термин процитирован внутри кавычек-«ёлочек» («доверительный интервал») —
# это цитата запрещённого слова ВНУТРИ правила, которое само его запрещает
# ("называй X, а не «доверительный интервал»"), не использование в клиентском
# тексте. Ловит ТОЛЬКО термин, обрамлённый «...» без другого текста внутри.
CI_TERM_QUOTED_RE = re.compile(r"«\s*(?i:довер(?:ительн\w*)\s+интервал\w*)\s*»")

BLOCKING_PATTERNS = ["ОСТАНОВИСЬ", "не продолжай", "жди ввода", "не генерируй"]
BLOCKING_RE = re.compile("|".join(re.escape(p) for p in BLOCKING_PATTERNS), re.IGNORECASE)


def discover_command_files():
    """Все файлы команд кабинета econometrist, отсортированные для стабильного вывода."""
    return sorted(REPO_ROOT.glob(COMMANDS_GLOB))


def discover_cabinet_docs():
    """CLAUDE.md + LEGACY_COMMANDS.md кабинета (сокращённая проверка: без шапки)."""
    return [p for p in (CABINET_CLAUDE_MD, LEGACY_COMMANDS_MD) if p.exists()]


def resolve_arg_paths(args):
    """Аргументы (staged-файлы от lefthook) -> абсолютные пути, только существующие .md области."""
    scope_files = set(discover_command_files()) | set(discover_cabinet_docs())
    resolved = []
    for arg in args:
        p = Path(arg)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if p in scope_files:
            resolved.append(p)
    return resolved


def is_command_file(path: Path) -> bool:
    """True для файлов .claude/commands/*.md (проверяется языковая шапка)."""
    return path.parent.name == "commands" and path.parent.parent.name == ".claude"


def _check_common(text: str) -> list[str]:
    """Проверки, общие для всех файлов области: тире + термин CI + блокировка."""
    fails = []

    if EM_DASH in text:
        count = text.count(EM_DASH)
        fails.append(f"найден символ длинного тире «—» ({count}×) — использовать короткое тире «–»")

    text_unquoted = CI_TERM_QUOTED_RE.sub("", text)
    ci_matches = CI_TERM_RE.findall(text_unquoted)
    if ci_matches:
        fails.append(
            "найден запрещённый термин «доверительный интервал»/«CI» — байесовские "
            "интервалы называются «правдоподобный диапазон» (Батч 2, INV-50)"
        )

    blocking_matches = sorted(set(m.group(0) for m in BLOCKING_RE.finditer(text)))
    if blocking_matches:
        fails.append(
            f"найден паттерн блокировки диалога ({', '.join(blocking_matches)}) — "
            f"команда не должна замораживать выполнение"
        )

    return fails


def lint_file(path: Path):
    """Возвращает список причин FAIL для файла (пустой список = OK)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [f"файл не читается как UTF-8 ({exc})"]

    fails = _check_common(text)

    if is_command_file(path):
        first_line = text.splitlines()[0] if text else ""
        if first_line != LANGUAGE_HEADER:
            fails.append(
                "первая строка не совпадает дословно с эталонной языковой шапкой "
                f"(получено: {first_line[:80]!r}...)"
            )

    return fails


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def main():
    args = sys.argv[1:]

    if args:
        files = resolve_arg_paths(args)
        if not files:
            print("Линтер команд econometrist: ни один переданный путь не относится к области "
                  "проверки (New_AI_Agency/econometrist/**) — пропуск.")
            return 0
    else:
        files = discover_command_files() + discover_cabinet_docs()
        if not files:
            print(f"Линтер команд econometrist: файлы области не найдены ({COMMANDS_GLOB}) — пропуск.")
            return 0

    ok_files = []
    fail_files = []  # (path, [fails])

    for path in files:
        fails = lint_file(path)
        if fails:
            fail_files.append((path, fails))
        else:
            ok_files.append(path)

    print(f"Линтер команд econometrist: OK {len(ok_files)} файлов из {len(files)} проверенных.")

    if fail_files:
        print(f"\nFAIL ({len(fail_files)}):")
        for path, fails in fail_files:
            print(f"  {relpath(path)}:")
            for f in fails:
                print(f"    - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
