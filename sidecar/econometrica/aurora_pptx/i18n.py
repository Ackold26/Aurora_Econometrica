"""
i18n loader + t(key, lang) for aurora_pptx.

Strings live in strings_ru.json / strings_en.json.
Missing keys fall back to English; missing from both - return key itself (debug mode).

Usage:
    from .i18n import t
    title = t("cover.confidentiality", lang="ru", client="Kagocel")
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent


@lru_cache(maxsize=4)
def _load_strings(lang: str) -> dict:
    path = BASE_DIR / f"strings_{lang}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _lookup(d: dict, path: list[str]) -> Any:
    cursor = d
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def t(key: str, lang: str = "ru", **fmt) -> str:
    """Translate key via dotted-path lookup with {var} interpolation.

    Args:
        key: dotted path, e.g. "cover.confidentiality"
        lang: 'ru' | 'en'
        **fmt: variables for str.format_map substitution

    Fallback chain: requested lang → en → key as literal.
    """
    path = key.split(".")
    for candidate_lang in (lang, "en"):
        strings = _load_strings(candidate_lang)
        value = _lookup(strings, path)
        if isinstance(value, str):
            try:
                return value.format_map(fmt) if fmt else value
            except (KeyError, ValueError):
                return value
    return f"[{key}]"
