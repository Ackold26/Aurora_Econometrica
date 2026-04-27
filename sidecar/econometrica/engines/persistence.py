"""Pickle persistence helpers for Aurora Econometrica models.

Trust Level 3 (v1.1.0) added `model_version='1.3'` с polem `channel_categories`.
Этот модуль централизует pickle compat — все downstream consumers (decomposer,
optimizer, scenario, narrative_adapter, backtest, html_export) должны use
`load_model_with_compat()` вместо direct pickle.load().

Migration ladder:
- v1.0       — initial OLS path (rejected by decomposer guard, MODEL_OUTDATED)
- v1.0-ols   — Sprint 2 small-data fallback (point estimates, no posterior CI)
- v1.1       — v1.0.13+ Bayesian baseline (z-score → spend/mean Hill normalization)
- v1.1.1     — Phase 1.1 hierarchical adstock decay (logit-normal, sampled per channel)
- v1.2       — v1.0.16 baseline (post-audit fixes, three-way alignment)
- v1.3       — Trust Level 3 (Brand vs Performance Split, channel_categories field)
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any


def load_model_with_compat(model_path: Path | str) -> dict[str, Any]:
    """Load pickle с backward-compat fields injected.

    Trust Level 3 contract:
    - `channel_categories` always present (empty dict если pre-v1.3 pickle).
    - `model_version` always present (default '1.0' если field missing — legacy).
    - Old fields preserved verbatim.

    NB: Не infers categories автоматически — оставляет `{}` для downstream choice.
    Decomposer/optimizer/etc. могут сами вызвать `infer_categories_heuristic()`
    если им нужны категории, но НЕ persists in pickle (читаем-only access pattern).

    Raises:
        FileNotFoundError если path не существует.
        pickle.UnpicklingError на corrupt files.
    """
    p = Path(model_path)
    with open(p, 'rb') as f:
        model_data = pickle.load(f)

    # Defensive defaults (v1.0 legacy may lack these fields entirely)
    model_data.setdefault('model_version', '1.0')
    model_data.setdefault('channel_categories', {})

    return model_data


def get_channel_categories(
    model_data: dict[str, Any],
    fallback_heuristic: bool = True,
) -> dict[str, str]:
    """Get channel categories из pickle, optionally with heuristic fallback.

    Args:
        model_data: loaded pickle dict
        fallback_heuristic: если True и categories пусты — derive из имён каналов
                          через auto-suggestion confidence ≥ 0.7

    Returns:
        {channel_name: 'brand'|'performance'|'mixed'}
    """
    categories = dict(model_data.get('channel_categories') or {})
    if categories:
        return categories
    if not fallback_heuristic:
        return {}
    # Lazy import (avoid cyclic если utils imports from engines)
    from econometrica.utils.channel_categorization import infer_categories_heuristic
    media_cols = model_data.get('media_columns') or model_data.get('config', {}).get('media_columns', [])
    if not media_cols:
        return {}
    return infer_categories_heuristic(list(media_cols))


def is_hierarchical_model(model_data: dict[str, Any]) -> bool:
    """True если pickle обучен hierarchical (v1.3+ с непустыми categories)."""
    if str(model_data.get('model_version', '')) < '1.3':
        return False
    cats = model_data.get('channel_categories') or {}
    if not cats:
        return False
    n_brand = sum(1 for c in cats.values() if c == 'brand')
    n_perf = sum(1 for c in cats.values() if c == 'performance')
    return n_brand >= 2 or n_perf >= 2
