#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Воспроизводимый перенос PDF «Условия ознакомительного использования» из
эталонного места правового блока в ресурсы поставки Aurora AI Econometrica.

Область: s48 (2026-09-14). Файл условий менялся вручную трижды за один час
правки правовым блоком — разовое копирование "руками" по названным
кем-то цифрам размера/суммы не годится, потому что эти цифры устаревают
быстрее, чем на них успевают сослаться. Вместо этого: одна команда, которая
КАЖДЫЙ РАЗ перед сборкой перечитывает эталон заново, копирует его в ресурсы
и обновляет манифест с суммой - по тому же приёму, что и
`tools/build_help_pdf.py` для справки (см. `build_manifest()` там же:
`hashlib.sha256(p.read_bytes()).hexdigest()`, JSON-манифест рядом со
скриптом).

Сумма хранится РОВНО В ОДНОМ месте - `tools/trial_terms_manifest.json` -
и обновляется только этим скриптом, вручную её нигде не подставлять
(находка по образцу расхождения констант в родственном продукте линейки).
Сторож поставки в `src-tauri/src/commands/user_config.rs`
(`trial_terms_pdf_matches_manifest_hash`) сверяет содержимое бандла с этой
же суммой при каждом прогоне тестов.

Копирование - побайтовое, в двоичном режиме (`shutil.copyfile`, не
затрагивает построчную обработку); после копирования сумма читается ЗАНОВО
с диска копии и сверяется с суммой источника - если они разошлись
(например, файл на сетевом диске записался не до конца), скрипт падает
ДО того, как обновит манифест, а не молча кладёт битую копию.

Использование:
    python tools/sync_trial_terms.py
    python tools/sync_trial_terms.py --source "<путь к другому эталону>"  (для теста)
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 🔴 Единственное место, где живёт путь к эталону правового блока. Эталон вне
# репозитория (Business/Договора) - здесь только ссылка на него, документ там
# правит правовой блок, сюда его только переносят.
DEFAULT_SOURCE = Path(
    r"D:\Docs\Aurora_Ai\Business\Договора\Условия ознакомительного использования.pdf"
)

# Имя файла в ресурсах поставки. ОБЯЗАНО дословно совпадать с
# `TRIAL_TERMS_PDF_FILENAME` в `src-tauri/src/commands/user_config.rs` -
# сторож расхождения: `trial_terms_pdf_filename_matches_sync_script` (там же,
# читает этот файл через include_str! и ищет строку ниже).
TRIAL_TERMS_PDF_FILENAME = "Условия ознакомительного использования.pdf"

DEST_DIR = REPO_ROOT / "src-tauri" / "help-econometrica"
MANIFEST_PATH = Path(__file__).resolve().parent / "trial_terms_manifest.json"

# Редакция документа - должна совпадать с TRIAL_TERMS_REVISION в user_config.rs
# (сторож расхождения: sync_script_revision_matches_rust_constant, там же) и с датой
# в тексте чекбокса TrialConsentOverlay.svelte (свой сторож - trial_terms_revision_
# matches_frontend_checkbox_text). Здесь только для записи в манифест - справочно
# (текст сообщения об ошибке), сторож поставки сверяет СУММУ, а не эту строку.
TRIAL_TERMS_REVISION = "2026-09-14"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE,
        help="Путь к эталонному PDF (по умолчанию - место правового блока)",
    )
    args = parser.parse_args()

    source: Path = args.source
    if not source.exists():
        print(f"[trial-terms] ОШИБКА: эталон не найден: {source}", file=sys.stderr)
        return 1

    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_size = len(source_bytes)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest = DEST_DIR / TRIAL_TERMS_PDF_FILENAME

    # Побайтовая копия в двоичном режиме - никакой построчной обработки.
    shutil.copyfile(source, dest)

    dest_hash = sha256_of(dest)
    dest_size = dest.stat().st_size
    if dest_hash != source_hash or dest_size != source_size:
        print(
            f"[trial-terms] ОШИБКА: копия разошлась с эталоном ПОСЛЕ копирования "
            f"(источник {source_size} б / {source_hash}, копия {dest_size} б / "
            f"{dest_hash}) - манифест НЕ обновлён, копия НЕ считается доставленной.",
            file=sys.stderr,
        )
        return 1

    manifest = {
        "revision": TRIAL_TERMS_REVISION,
        "filename": TRIAL_TERMS_PDF_FILENAME,
        "source_path": str(source),
        "sha256": dest_hash,
        "size_bytes": dest_size,
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[trial-terms] Источник:  {source}")
    print(f"[trial-terms] Копия:     {dest}")
    print(f"[trial-terms] Размер:    {dest_size} б")
    print(f"[trial-terms] SHA-256:   {dest_hash}")
    print(f"[trial-terms] Манифест:  {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
