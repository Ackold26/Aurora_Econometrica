"""Atomic JSON write + integrity verification — Phase 0.3.

Reused в Phase 1.4 (migration с pre-mutation backup + checksum) и
Phase 1.6 (JCS canonical hash для project.json).

Pattern:
    1. Serialize data к bytes (UTF-8)
    2. Compute SHA-256 hash
    3. Write к sibling .tmp file
    4. os.fsync(fd) — guarantee bytes на disk
    5. os.replace(.tmp, target) — atomic rename
    6. Return (path, sha256)

Power-loss / disk-full safety: если step 3-4 fails — target untouched.
Если step 5 fails (rare) — .tmp leftover может be cleaned up на next call.

Cross-platform: os.replace() atomic on POSIX + Windows (Python 3.3+).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


class IntegrityError(Exception):
    """Raised когда disk content не matches expected hash."""


def sanitize_nonfinite(obj: Any) -> Any:
    """Рекурсивно заменяет NaN / Inf / -Inf на None (валидный JSON).

    Bug (2026-06-04 fresh-train аудит): result-JSON'ы (model-diagnostics.json и др.)
    писались голым `json.dump` (allow_nan=True по умолчанию) → при вырожденной модели
    (r_hat_max=NaN, intercept=NaN, sigma=NaN) в файл попадали литералы `NaN`. Это
    нарушение RFC 8259: Python json их читает, но Rust `serde_json` (strict) ПАДАЕТ →
    `project_load_results.read_json` молча возвращает null → Отчёт «модель не загружена»,
    хотя обучение прошло. Применять перед записью любого result-JSON, читаемого Rust.

    numbers.Real покрывает Python float И numpy float32/float64/int*. bool исключён.
    """
    import math
    import numbers
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, numbers.Real):
        try:
            return obj if math.isfinite(float(obj)) else None
        except (ValueError, OverflowError, TypeError):
            return None
    if isinstance(obj, dict):
        return {k: sanitize_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_nonfinite(v) for v in obj]
    return obj


def _compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(path: Path) -> str:
    """Stream SHA-256 of file content (chunked для large files)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(64 * 1024):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> str:
    """Atomic write JSON + return SHA-256 hex.

    Strategy:
      1. Serialize data (UTF-8 bytes)
      2. Compute hash of bytes
      3. Write к sibling .tmp file (same FS → rename is atomic)
      4. fsync directory entry
      5. os.replace() — atomic rename

    Returns:
        SHA-256 hex of written content.

    Raises:
        OSError on disk failure (caller should handle).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False rejects float('inf') / float('nan') / -inf.
    # Default Python json.dumps(allow_nan=True) emits non-standard tokens
    # `Infinity` / `NaN` (RFC 8259 violation). Subsequent json.load on такого
    # файла raises JSONDecodeError. Audit H-02.
    serialized = json.dumps(
        data,
        indent=indent,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
        allow_nan=False,
    ).encode('utf-8')
    sha = _compute_sha256_bytes(serialized)
    tmp = target.with_suffix(target.suffix + '.tmp')
    # Use os.open with binary flag (Windows translates \n→\r\n in text mode).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    fd = os.open(tmp, flags, 0o644)
    try:
        os.write(fd, serialized)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return sha


def verify_json_integrity(path: Path | str, expected_sha256: str) -> bool:
    """True если file content sha256 matches expected. False иначе.

    Doesn't raise — caller decides action (warn vs raise).
    """
    p = Path(path)
    if not p.exists():
        return False
    actual = compute_file_sha256(p)
    return actual == expected_sha256


def safe_backup_with_checksum(src: Path | str, *, suffix: str = '.bak') -> tuple[Path, str]:
    """Copy src к sibling <name><suffix> + return (backup_path, sha256).

    Used pre-mutation в Phase 1.4 migration. Caller can verify backup
    integrity later via verify_json_integrity(backup_path, returned_sha).

    Raises:
        FileNotFoundError если src not exists.
    """
    source = Path(src)
    if not source.exists():
        raise FileNotFoundError(f'Backup source not exists: {source}')
    backup = source.with_suffix(source.suffix + suffix)
    shutil.copy2(source, backup)
    sha = compute_file_sha256(backup)
    return backup, sha


def unique_export_path(path: Path | str) -> Path:
    """Вернуть свободный путь для сохранения клиентского документа (CPD-70).

    Если `path` уже занят — подбирает `<имя> (2)<расширение>`,
    `<имя> (3)<расширение>` и т.д., пока не найдётся свободное имя. Свободный
    путь возвращается как есть, без изменений.

    Не создаёт и не блокирует файл — только вычисляет путь; вызывающая
    сторона решает, что с ним делать (save/write/replace). Каталог `path`
    может не существовать — .exists() тогда просто вернёт False.

    Используется перед сохранением ГОТОВОГО документа клиента (pptx/xlsx/html
    и т.п.), чтобы повторная генерация не затирала прежний результат молча —
    класс дефекта «молчаливая потеря результата клиента» (CPD-70).
    """
    target = Path(path)
    if not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    n = 2
    while True:
        candidate = parent / f'{stem} ({n}){suffix}'
        if not candidate.exists():
            return candidate
        n += 1


def cleanup_stale_backups(
    project_dir: Path | str,
    *,
    pattern: str = '*.pre_*',
    keep_last: int = 3,
) -> list[Path]:
    """Удалить старые backup files, keep last N per project.

    Returns list of removed paths. Idempotent.
    """
    pdir = Path(project_dir)
    if not pdir.exists():
        return []
    candidates = sorted(
        pdir.rglob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    to_remove = candidates[keep_last:]
    removed = []
    for p in to_remove:
        try:
            p.unlink()
            removed.append(p)
        except OSError:
            continue
    return removed
