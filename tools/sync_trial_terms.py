#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Воспроизводимый перенос правовых PDF из эталонного места правового блока в ресурсы
поставки Aurora AI Econometrica: «Условия ознакомительного использования» и «Порядок
обработки данных - Aurora AI Econometrica».

Область: s48 (2026-09-14). Файл условий менялся вручную трижды за один час правки
правовым блоком - разовое копирование "руками" по названным кем-то цифрам размера/суммы
не годится, потому что эти цифры устаревают быстрее, чем на них успевают сослаться.
Вместо этого: одна команда, которая КАЖДЫЙ РАЗ перед сборкой перечитывает оба эталона
заново, копирует их в ресурсы и обновляет манифест с суммами - по тому же приёму, что и
`tools/build_help_pdf.py` для справки (см. `build_manifest()` там же:
`hashlib.sha256(p.read_bytes()).hexdigest()`, JSON-манифест рядом со скриптом).

Второй документ добавлен по требованию правового блока
(Business/Projects/СИГНАЛ_сессиям_правовой_комплект_2026-09-14.md, раздел 3.2): без
«Порядка обработки данных» пункты 6.2, 6.5, 6.8 «Условий» ведут в пустоту.

Суммы хранятся РОВНО В ОДНОМ месте - `tools/trial_terms_manifest.json`, объект
`documents` с ключами `terms` и `data_processing` - и обновляются только этим скриптом,
вручную их нигде не подставлять (находка по образцу расхождения констант в родственном
продукте линейки). Сторож поставки в `src-tauri/src/commands/user_config.rs`
(`trial_terms_delivery_guard::{trial_terms_pdf_matches_manifest_hash,
data_processing_pdf_matches_manifest_hash}`) сверяет содержимое бандла с этими же суммами
при каждом прогоне тестов.

Копирование - побайтовое, в двоичном режиме (`shutil.copyfile`, не затрагивает
построчную обработку); после копирования каждого файла сумма читается ЗАНОВО с диска
копии и сверяется с суммой источника - если они разошлись (например, файл на сетевом
диске записался не до конца), скрипт падает ДО того, как обновит манифест, а не молча
кладёт битую копию. Манифест пишется одним куском ПОСЛЕ успешной проверки обоих
документов - частичное обновление (один документ синхронизирован, другой нет) исключено.

Использование:
    python tools/sync_trial_terms.py
    python tools/sync_trial_terms.py --terms-source "<путь>" --data-processing-source "<путь>"  (для теста)
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 🔴 Единственное место, где живут пути к эталонам правового блока. Эталоны вне
# репозитория (Business/Договора) - здесь только ссылки на них, документы там правит
# правовой блок, сюда их только переносят.
DEFAULT_TERMS_SOURCE = Path(
    r"D:\Docs\Aurora_Ai\Business\Договора\Условия ознакомительного использования.pdf"
)
DEFAULT_DATA_PROCESSING_SOURCE = Path(
    r"D:\Docs\Aurora_Ai\Business\Договора\Порядок обработки данных - Aurora AI Econometrica.pdf"
)

# Имена файлов в ресурсах поставки. ОБЯЗАНЫ дословно совпадать с
# `TRIAL_TERMS_PDF_FILENAME`/`DATA_PROCESSING_PDF_FILENAME` в
# `src-tauri/src/commands/user_config.rs` - сторож расхождения:
# `sync_script_filename_matches_rust_constant` (там же, читает этот файл через
# include_str! и ищет обе строки ниже).
TRIAL_TERMS_PDF_FILENAME = "Условия ознакомительного использования.pdf"
DATA_PROCESSING_PDF_FILENAME = "Порядок обработки данных - Aurora AI Econometrica.pdf"

# Ключи документов в манифесте (объект `documents`) - общие с Rust-константами
# `TRIAL_TERMS_MANIFEST_KEY`/`DATA_PROCESSING_MANIFEST_KEY`.
TRIAL_TERMS_MANIFEST_KEY = "terms"
DATA_PROCESSING_MANIFEST_KEY = "data_processing"

DEST_DIR = REPO_ROOT / "src-tauri" / "help-econometrica"
MANIFEST_PATH = Path(__file__).resolve().parent / "trial_terms_manifest.json"

# Редакция документов - должна совпадать с TRIAL_TERMS_REVISION в user_config.rs
# (сторож расхождения: sync_script_revision_matches_rust_constant, там же) и с датой
# в тексте чекбокса TrialConsentOverlay.svelte (свой сторож - trial_terms_revision_
# matches_frontend_checkbox_text). Здесь только для записи в манифест - справочно
# (текст сообщения об ошибке), сторож поставки сверяет СУММУ, а не эту строку.
TRIAL_TERMS_REVISION = "2026-09-14.02"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_one(source: Path, dest_filename: str) -> dict:
    """Копирует один документ source → DEST_DIR/dest_filename, возвращает его запись
    манифеста. Падает (raise), не обновив ничего, если источник отсутствует или копия
    разошлась с эталоном после копирования - вызывающий код решает, что делать дальше."""
    if not source.exists():
        raise FileNotFoundError(f"эталон не найден: {source}")

    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_size = len(source_bytes)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest = DEST_DIR / dest_filename

    # Побайтовая копия в двоичном режиме - никакой построчной обработки.
    shutil.copyfile(source, dest)

    dest_hash = sha256_of(dest)
    dest_size = dest.stat().st_size
    if dest_hash != source_hash or dest_size != source_size:
        raise RuntimeError(
            f"копия «{dest_filename}» разошлась с эталоном ПОСЛЕ копирования "
            f"(источник {source_size} б / {source_hash}, копия {dest_size} б / {dest_hash})"
        )

    return {
        "revision": TRIAL_TERMS_REVISION,
        "filename": dest_filename,
        "source_path": str(source),
        "sha256": dest_hash,
        "size_bytes": dest_size,
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--terms-source", type=Path, default=DEFAULT_TERMS_SOURCE,
        help="Путь к эталонному PDF «Условий» (по умолчанию - место правового блока)",
    )
    parser.add_argument(
        "--data-processing-source", type=Path, default=DEFAULT_DATA_PROCESSING_SOURCE,
        help="Путь к эталонному PDF «Порядка обработки данных» (по умолчанию - место "
             "правового блока)",
    )
    args = parser.parse_args()

    documents = {}
    for doc_key, source, dest_filename, label in (
        (TRIAL_TERMS_MANIFEST_KEY, args.terms_source, TRIAL_TERMS_PDF_FILENAME,
         "Условия ознакомительного использования"),
        (DATA_PROCESSING_MANIFEST_KEY, args.data_processing_source, DATA_PROCESSING_PDF_FILENAME,
         "Порядок обработки данных"),
    ):
        try:
            entry = sync_one(source, dest_filename)
        except (FileNotFoundError, RuntimeError) as e:
            # 🔴 Манифест НЕ обновляется частично: если один документ не синхронизировался,
            # выходим ДО записи manifest.json - иначе сторож поставки увидит для второго
            # документа старую (или отсутствующую) сумму и будет путать её причину.
            print(f"[trial-terms] ОШИБКА ({label}): {e}", file=sys.stderr)
            return 1
        documents[doc_key] = entry
        print(f"[trial-terms] {label}:")
        print(f"[trial-terms]   Источник:  {source}")
        print(f"[trial-terms]   Копия:     {DEST_DIR / dest_filename}")
        print(f"[trial-terms]   Размер:    {entry['size_bytes']} б")
        print(f"[trial-terms]   SHA-256:   {entry['sha256']}")

    manifest = {"documents": documents}
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[trial-terms] Манифест:  {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
