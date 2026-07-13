#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пересчёт SHA-256 и Ed25519-переподпись content-pack манифеста Aurora AI Legal Center.

Зачем: файлы `content-packs/*.json` (cabinets.json, command-meta-data.json, …) —
это source. Рантайм грузит установленный пак из `%LOCALAPPDATA%\\<id>\\content-packs\\`
и проверяет целостность `crypto::content_sig::verify_manifest`:
  1) Ed25519-подпись manifest.sig над СЫРЫМИ байтами manifest.json;
  2) version >= MIN_CONTENT_VERSION (защита от отката);
  3) SHA-256 каждого файла из manifest.files.
После правки любого JSON его SHA-256 в манифесте устаревает → verify падает →
пак не сеется/не ставится → правки НЕ доедут клиенту (закоммиченный рассинхрон = тихий провал).
Руками manifest.json/manifest.sig НЕ править — только этим инструментом.

Приватный ключ (32-байтный Ed25519 seed): `~/.secrets/rosst_content_private.key`.
Соответствует публичному ключу, вшитому в `src-tauri/src/crypto/content_sig.rs`
(проверяется при подписи; несоответствие → отказ).

Использование:
    python tools/sign_content_pack.py --check          # только проверить sync sha256 + валидность подписи (для CI)
    python tools/sign_content_pack.py --bump           # пересчитать sha256, version +1, переподписать
    python tools/sign_content_pack.py --version 7       # то же, version = 7
    python tools/sign_content_pack.py                   # пересчитать sha256, version не менять, переподписать

Коды выхода: 0 — успех/синхронно; 1 — рассинхрон (в --check) или ошибка.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACK_DIR = REPO_ROOT / "content-packs"
MANIFEST_PATH = PACK_DIR / "manifest.json"
SIG_PATH = PACK_DIR / "manifest.sig"
KEY_PATH = Path.home() / ".secrets" / "rosst_content_private.key"

# Публичный ключ, вшитый в src-tauri/src/crypto/content_sig.rs (CONTENT_MASKED_KEY ^ 0x55).
# Держим здесь для сверки приватного ключа — если разойдётся, подпись бесполезна (verify упадёт).
_MASKED = [12, 115, 12, 138, 188, 191, 97, 208, 212, 134, 246, 164, 87, 142, 200, 116,
           179, 179, 195, 225, 111, 69, 229, 147, 229, 237, 234, 63, 44, 116, 224, 43]
EMBEDDED_PUBLIC_KEY = bytes(b ^ 0x55 for b in _MASKED)


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_private_key():
    """Ed25519PrivateKey из seed; сверка с вшитым публичным ключом (ABORT при расхождении)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    if not KEY_PATH.exists():
        sys.exit(f"FAIL: приватный ключ не найден: {KEY_PATH}")
    seed = KEY_PATH.read_bytes()
    if len(seed) != 32:
        sys.exit(f"FAIL: ключ должен быть 32 байта (Ed25519 seed), получено {len(seed)}")
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    derived_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if derived_pub != EMBEDDED_PUBLIC_KEY:
        sys.exit("FAIL: приватный ключ НЕ соответствует вшитому публичному ключу "
                 "(content_sig.rs) — подпись была бы отклонена клиентом. Проверь ключ.")
    return priv


def read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def compute_actual_hashes(manifest: dict) -> dict:
    """Фактические sha256 файлов, перечисленных в manifest.files."""
    result = {}
    for rel in manifest["files"]:
        fpath = PACK_DIR / rel
        if not fpath.exists():
            sys.exit(f"FAIL: файл из манифеста отсутствует: {rel}")
        result[rel] = sha256_of(fpath)
    return result


def check() -> int:
    """--check: sha256 файлов ↔ manifest + валидность подписи. 0 если синхронно."""
    manifest = read_manifest()
    actual = compute_actual_hashes(manifest)
    problems = []
    for rel, expected in manifest["files"].items():
        if actual[rel] != expected:
            problems.append(f"  MISMATCH {rel}: manifest={expected[7:19]} факт={actual[rel][7:19]}")

    # Подпись над сырыми байтами manifest.json
    sig_ok = False
    if SIG_PATH.exists():
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pub = Ed25519PublicKey.from_public_bytes(EMBEDDED_PUBLIC_KEY)
        try:
            pub.verify(SIG_PATH.read_bytes(), MANIFEST_PATH.read_bytes())
            sig_ok = True
        except InvalidSignature:
            problems.append("  подпись manifest.sig НЕ валидна над текущим manifest.json")
    else:
        problems.append("  manifest.sig отсутствует")

    if problems:
        print(f"content-pack РАССИНХРОН (version {manifest.get('version')}):")
        print("\n".join(problems))
        return 1
    print(f"content-pack синхронен: version {manifest['version']}, "
          f"{len(manifest['files'])} файлов, подпись валидна.")
    return 0


def sign(new_version: int | None, bump: bool) -> int:
    """Пересчитать sha256, при необходимости изменить version, переподписать."""
    priv = load_private_key()
    manifest = read_manifest()

    manifest["files"] = compute_actual_hashes(manifest)
    if bump:
        manifest["version"] = int(manifest["version"]) + 1
    elif new_version is not None:
        manifest["version"] = new_version
    manifest["timestamp"] = int(time.time())

    # Детерминированная сериализация (sort_keys) — сохраняем исходный компактный стиль.
    manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    MANIFEST_PATH.write_bytes(manifest_bytes)

    # Подпись над РОВНО теми байтами, что записаны в файл (verify_manifest читает fs::read).
    signature = priv.sign(manifest_bytes)
    SIG_PATH.write_bytes(signature)

    # Само-верификация: как это сделает клиент.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    pub = Ed25519PublicKey.from_public_bytes(EMBEDDED_PUBLIC_KEY)
    try:
        pub.verify(SIG_PATH.read_bytes(), MANIFEST_PATH.read_bytes())
    except InvalidSignature:
        sys.exit("FAIL: само-верификация подписи не прошла — не публиковать.")

    print(f"OK: manifest подписан. version={manifest['version']}, "
          f"timestamp={manifest['timestamp']}, файлов={len(manifest['files'])}.")
    for rel, h in manifest["files"].items():
        print(f"  {rel:26} {h[7:19]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Подпись content-pack манифеста Legal Center.")
    ap.add_argument("--check", action="store_true", help="только проверить синхронность+подпись")
    ap.add_argument("--bump", action="store_true", help="version += 1")
    ap.add_argument("--version", type=int, default=None, help="установить version = N")
    args = ap.parse_args()

    if args.check:
        return check()
    if args.bump and args.version is not None:
        sys.exit("FAIL: --bump и --version взаимоисключающие.")
    return sign(args.version, args.bump)


if __name__ == "__main__":
    sys.exit(main())
