#!/usr/bin/env python
"""Генератор release notes для Aurora Econometrica.

Usage:
  python tools/release-notes.py 1.0.11 --prev v1.0.10-rc1.4 --exe "path/to/setup.exe"
  python tools/release-notes.py 1.0.11-rc2 --prev v1.0.10-rc1 --exe path --prerelease

Вычисляет SHA256 installer'а, размер в MB, git log между тегами,
подставляет в шаблон. Output идёт в stdout — redirect в /tmp/notes.md
или используй `--out /path/to/notes.md`.
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

TEMPLATE = """# Aurora AI Econometrica v{version}

{prefix}

## Новое

{new_items}

## Фиксы

{fix_items}

## Артефакт

| Поле | Значение |
|------|----------|
| SHA256 | `{sha256}` |
| Размер | {size_mb:.2f} MB |
| Tag | `v{version}` |
| Предыдущий tag | `{prev}` |
| Коммитов с `{prev}` | {commit_count} |

## Commits since {prev}

```
{commit_log}
```

## Rollback

При проблеме: см. [`memory/reference_econometrica_rollback.md`](../memory/reference_econometrica_rollback.md)
и `tools/rollback.sh`.
"""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_log_between(prev_tag: str) -> tuple[str, int]:
    # Ensure tags are fetched locally
    subprocess.run(["git", "fetch", "--tags"], capture_output=True, check=False)
    out = subprocess.run(
        ["git", "log", "--oneline", f"{prev_tag}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        sys.stderr.write(
            f"warn: git log failed — tag '{prev_tag}' not found locally?\n"
            f"      {out.stderr.strip()}\n"
        )
        return "(git log unavailable)", 0
    log = out.stdout.strip()
    count = len([ln for ln in log.splitlines() if ln.strip()])
    return log or "(no new commits)", count


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("version", help="Новая версия без префикса 'v' (например 1.0.11 или 1.0.11-rc2)")
    p.add_argument("--prev", required=True, help="Предыдущий tag (например v1.0.10-rc1.4)")
    p.add_argument("--exe", required=True, help="Путь к .exe installer для SHA256 + size")
    p.add_argument("--prerelease", action="store_true", help="Помечать как pre-release в header")
    p.add_argument("--out", help="Записать в файл (иначе stdout)")
    p.add_argument("--new", default="- TODO: fill", help="Bullet list новых фич (multiline OK)")
    p.add_argument("--fix", default="- TODO: fill", help="Bullet list фиксов (multiline OK)")
    args = p.parse_args()

    exe = Path(args.exe)
    if not exe.exists():
        sys.stderr.write(f"error: installer not found: {exe}\n")
        return 2

    sha = sha256_of(exe)
    size_mb = exe.stat().st_size / (1024 * 1024)
    log, count = git_log_between(args.prev)

    text = TEMPLATE.format(
        version=args.version,
        prefix="**Pre-release candidate.**" if args.prerelease else "**Stable release.**",
        new_items=args.new,
        fix_items=args.fix,
        sha256=sha,
        size_mb=size_mb,
        prev=args.prev,
        commit_count=count,
        commit_log=log,
    )

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        sys.stderr.write(f"✓ written to {args.out}\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
