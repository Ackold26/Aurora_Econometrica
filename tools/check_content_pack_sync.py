#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка синхронности content-pack манифеста Aurora AI Optimizer MMM (CI-обёртка).

Портировано из ../ROSST_AI_Legal_commercial/tools/check_content_pack_sync.py
(аудит промптов 2026-07-13, Батч 5) без изменений по существу — тонкая обёртка
над `tools/sign_content_pack.py --check`, который уже умеет сверять фактический
SHA-256 файлов content-packs/*.json с manifest.json и валидировать Ed25519-подпись
manifest.sig (портирован в этот репозиторий ранее, в Батче 0/re-sign).

Зачем отдельным файлом: ловит закоммиченный рассинхрон manifest<->файлы —
правку content-packs/*.json без переподписи (Legal-кейс CRIT-1: изменили JSON,
не пересчитали sha256/подпись, рантайм отклонил пак молча — тот же риск здесь,
т.к. verify_manifest в src-tauri/src/crypto/content_sig.rs общий код).

Использование:
    python tools/check_content_pack_sync.py

Коды выхода: 0 — content-pack синхронен; 1 — рассинхрон, нужен re-sign.
"""

import os
import subprocess
import sys
from pathlib import Path

# CI (Windows GitHub runner) отдаёт stdout в cp1252 → русский print падает с
# UnicodeEncodeError. Принудительно UTF-8 (переносимо: CI + lefthook + ручной запуск).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGN_SCRIPT = REPO_ROOT / "tools" / "sign_content_pack.py"


def main() -> int:
    if not SIGN_SCRIPT.exists():
        print(f"FAIL: не найден {SIGN_SCRIPT.relative_to(REPO_ROOT)} — проверка невозможна.")
        return 1

    # PYTHONIOENCODING=utf-8: без него дочерний процесс на Windows пишет
    # в консольную кодовую страницу (cp1251/cp866), и русский вывод бьётся.
    child_env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(SIGN_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
    )

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)

    if result.returncode == 0:
        print("content-pack синхронен.")
        return 0

    print("content-pack РАССИНХРОН, нужен re-sign "
          "(python tools/sign_content_pack.py --bump или --version N).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
