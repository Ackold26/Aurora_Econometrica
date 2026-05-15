"""Project.json schema migration — Phase 1.4 / Audit P-03.

Existing v2.0.0 customer projects have SOM/SOV/share_of_* columns classified
as role='control' (legacy validator.py substring matching). BUG #3 fix changes
classifier к role='unused' for these — but existing project.json files cached
old classification. Without migration, BUG #3 fix не applies к saved projects.

This module:
- Detects schema_version mismatch (project.json `schema_version` field)
- Re-classifies SOM/SOV/share_of_* columns from 'control' → 'unused'
- Writes updated project.json atomically (Phase 0.3 safe_io)
- Pre-mutation backup с SHA-256 checksum (recoverable on failure)
- Idempotent (running twice = no-op after first run)

Sync version v2.0.1 (this file). Async progress UI defer к v2.0.2 — modal
с indeterminate spinner + cancel button. Sync migration acceptable для
ship because expected duration <100ms (project.json typically <50KB).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# Constants matching engines/validator.py DERIVED_KEYS check.
DERIVED_KEYS = [
    'som в', 'som (', 'som_',
    'sov ', 'sov (', 'sov_',
    'share_of_market', 'share of market',
    'market_share', 'market share',
    'share_of_voice', 'share of voice',
    'доля_рынка', 'доля рынка',
    'доля_голоса', 'доля голоса',
]

TARGET_SCHEMA_VERSION = '2.0.1'

logger = logging.getLogger(__name__)


def is_derived_metric(column_name: str) -> bool:
    """True если column name matches DERIVED_KEYS (SOM/SOV/share_of_*).

    Mirrors engines/validator.detect_column_role_with_confidence DERIVED check.
    Trailing-space / suffix guards prevent false positives (e.g. 'mosgorsovet').
    """
    if not isinstance(column_name, str):
        return False
    lower = column_name.lower()
    return (
        any(k in lower for k in DERIVED_KEYS)
        or lower in ('som', 'sov')
        or lower.endswith(' som')
        or lower.endswith(' sov')
    )


def needs_migration(project_dict: dict[str, Any]) -> tuple[bool, str]:
    """Decide if project.json needs Phase 1.4 migration.

    Returns:
        (needs_migration, reason). Reason — diagnostic string.
    """
    if not isinstance(project_dict, dict):
        return False, 'invalid project_dict type'
    current = project_dict.get('schema_version', '1.0')
    if current == TARGET_SCHEMA_VERSION:
        return False, f'already at {TARGET_SCHEMA_VERSION}'
    # Check actual content: any SOM/SOV в control_columns?
    control_cols = project_dict.get('control_columns', []) or []
    if not isinstance(control_cols, list):
        return False, 'control_columns malformed'
    misclassified = [c for c in control_cols if is_derived_metric(str(c))]
    if not misclassified:
        # No actual mismatch — just bump version (cheap)
        return True, f'version bump only (no content change): {current} → {TARGET_SCHEMA_VERSION}'
    return True, (
        f'{len(misclassified)} derived metric(s) misclassified as control: '
        f'{", ".join(misclassified[:3])}{"..." if len(misclassified) > 3 else ""}'
    )


def apply_migration(project_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply migration in-memory. Returns new dict (does NOT mutate input).

    Steps:
    1. Move derived metric columns from control_columns → excluded_columns
    2. Update schema_version к TARGET_SCHEMA_VERSION
    3. Stamp `_jcs_sha256` canonical hash (C-03 / INV-06)
    4. Preserve all other fields (additive evolution per ADR-019)

    Idempotent: re-running migration on already-migrated dict = no-op (no
    derived metrics в control_columns after first pass).
    """
    out = dict(project_dict)  # shallow copy — adequate (we replace top fields)
    control_cols = list(out.get('control_columns', []) or [])
    excluded_cols = list(out.get('excluded_columns', []) or [])

    derived_to_move = [c for c in control_cols if is_derived_metric(str(c))]
    if derived_to_move:
        out['control_columns'] = [c for c in control_cols if not is_derived_metric(str(c))]
        # Append to excluded, dedup
        for c in derived_to_move:
            if c not in excluded_cols:
                excluded_cols.append(c)
        out['excluded_columns'] = excluded_cols

    out['schema_version'] = TARGET_SCHEMA_VERSION

    # C-03 (INV-06): stamp JCS canonical hash для tamper detection.
    # Exclude self (`_jcs_sha256`) from hash computation, avoid chicken-egg.
    out.pop('_jcs_sha256', None)
    try:
        from utils.canonical_hash import compute_project_hash
        out['_jcs_sha256'] = compute_project_hash(out)
    except ImportError:
        # rfc8785 absent (dev environment без pip install). Skip stamping;
        # downstream verification will skip too.
        logger.warning('rfc8785 unavailable — _jcs_sha256 not stamped')
    return out


def verify_project_integrity(project_dict: dict[str, Any]) -> tuple[bool, str]:
    """Verify project.json `_jcs_sha256` matches recomputed canonical hash.

    Soft check — caller decides action (warn vs raise). Phase 1.6 ships
    as warning-only; future Phase 2+ may strict-enforce.

    Returns:
        (ok, reason). ok=True если hash matches or field absent (no-op for
        pre-1.6 projects). reason describes match/mismatch.
    """
    stored = project_dict.get('_jcs_sha256')
    if not stored:
        return True, 'no _jcs_sha256 field (pre-Phase-1.6 project)'
    if not isinstance(stored, str) or len(stored) != 64:
        return False, f'malformed _jcs_sha256: {stored!r}'
    try:
        from utils.canonical_hash import compute_project_hash
    except ImportError:
        return True, 'rfc8785 unavailable, skipping verify'
    # Recompute excluding self.
    payload = {k: v for k, v in project_dict.items() if k != '_jcs_sha256'}
    actual = compute_project_hash(payload)
    if actual == stored:
        return True, 'integrity OK'
    return False, f'hash mismatch: stored={stored[:8]}.., actual={actual[:8]}..'


def migrate_project_file(project_json_path: Path) -> dict[str, Any]:
    """Atomic migration of project.json file. Pre-mutation backup + checksum.

    Args:
        project_json_path: Path к project.json file.

    Returns:
        Dict с keys:
        - status: 'ok' | 'no_migration_needed' | 'error'
        - from_version, to_version
        - migrated_columns: list[str]
        - backup_path: str | None
        - backup_sha256: str | None
        - new_sha256: str | None
        - reason: str

    Raises на parse errors (caller wraps в HTTP handler).
    """
    import json
    from utils.safe_io import atomic_write_json, safe_backup_with_checksum

    if not project_json_path.exists():
        return {
            'status': 'error',
            'reason': f'project.json not found: {project_json_path}',
        }

    # Read current state
    with open(project_json_path, encoding='utf-8') as f:
        project_dict = json.load(f)

    # C-03 / INV-06: soft hash verify (warn-only в Phase 1).
    integrity_ok, integrity_msg = verify_project_integrity(project_dict)
    if not integrity_ok:
        logger.warning(
            'project.json hash verify FAILED before migration: %s. '
            'Proceeding anyway (Phase 1 soft enforcement).',
            integrity_msg,
        )

    needs, reason = needs_migration(project_dict)
    if not needs:
        return {
            'status': 'no_migration_needed',
            'from_version': project_dict.get('schema_version', '1.0'),
            'to_version': TARGET_SCHEMA_VERSION,
            'migrated_columns': [],
            'reason': reason,
        }

    from_version = project_dict.get('schema_version', '1.0')

    # Pre-mutation backup
    backup_path, backup_sha = safe_backup_with_checksum(
        project_json_path,
        suffix=f'.pre_{TARGET_SCHEMA_VERSION}',
    )

    try:
        # Apply migration in-memory
        migrated = apply_migration(project_dict)

        # Track what was moved
        control_before = set(project_dict.get('control_columns', []) or [])
        control_after = set(migrated.get('control_columns', []) or [])
        moved = sorted(control_before - control_after)

        # Atomic write through Phase 0.3 safe_io
        new_sha = atomic_write_json(project_json_path, migrated)

        logger.info(
            'project.json migrated %s → %s, moved %d cols, sha=%s',
            from_version, TARGET_SCHEMA_VERSION, len(moved), new_sha[:8],
        )

        return {
            'status': 'ok',
            'from_version': from_version,
            'to_version': TARGET_SCHEMA_VERSION,
            'migrated_columns': moved,
            'backup_path': str(backup_path),
            'backup_sha256': backup_sha,
            'new_sha256': new_sha,
            'reason': reason,
        }
    except Exception as exc:  # noqa: BLE001 — restore on any error
        # Restore from backup
        try:
            import shutil
            shutil.copy2(backup_path, project_json_path)
            logger.exception('Migration FAILED, restored from backup: %s', exc)
        except Exception:
            logger.exception('Migration FAILED + backup restore ALSO FAILED')
        return {
            'status': 'error',
            'from_version': from_version,
            'to_version': TARGET_SCHEMA_VERSION,
            'backup_path': str(backup_path),
            'backup_sha256': backup_sha,
            'reason': f'migration failed (restored from backup): {exc}',
        }
