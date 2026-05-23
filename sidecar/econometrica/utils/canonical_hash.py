"""Canonical JSON hash (RFC 8785 JCS) — Phase 1.6 / INV-06 compliance.

`Pydantic.model_dump_json()` produces JSON that may vary между minor Pydantic
versions (key ordering, whitespace, escape differences). Cryptographic hashes
computed over such output → false-positive corruption alerts across upgrades.

RFC 8785 (JSON Canonicalization Scheme) defines bit-stable output — same JSON
value always produces same byte string независимо от source library version.

This module exposes:
- compute_project_hash(project_dict) -> sha256_hex
- verify_project_hash(project_dict, expected_sha256) -> bool

Rust counterpart: serde_jcs в aurora-platform-core/c7-web-verifier. Both
producе identical canonical output для shared schema.

Reuse: Phase 1.4 migration backup-with-checksum, future Methodology
Certificate hash payload (currently uses Pydantic model_dump_json which IS
INV-06 violation — separate ticket).
"""
from __future__ import annotations

import hashlib
from typing import Any


def _canonicalize_to_bytes(payload: Any) -> bytes:
    """Serialize to JCS-canonical UTF-8 bytes. Raises if non-JSON-serializable."""
    try:
        import rfc8785
    except ImportError as exc:
        raise ImportError(
            'Пакет rfc8785 не установлен. Добавьте rfc8785>=0.1.2 в requirements.txt '
            'и выполните pip install. INV-06 требует JCS для cryptographic hashes.'
        ) from exc
    # rfc8785.dumps() returns bytes (UTF-8 already)
    return rfc8785.dumps(payload)


def compute_project_hash(project_dict: dict[str, Any]) -> str:
    """SHA-256 over RFC 8785 canonical JSON serialization.

    Same value → same hash, across Pydantic / json library versions.

    Args:
        project_dict: JSON-serializable mapping. Values must be JSON types
            (no datetime / Decimal / numpy types — caller normalizes first).

    Returns:
        SHA-256 hex digest (64 chars).
    """
    canonical = _canonicalize_to_bytes(project_dict)
    return hashlib.sha256(canonical).hexdigest()


def verify_project_hash(project_dict: dict[str, Any], expected_sha256: str) -> bool:
    """True если recompute matches expected. False otherwise.

    Caller decides action (warn vs raise vs revert).
    """
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        return False
    actual = compute_project_hash(project_dict)
    return actual == expected_sha256
