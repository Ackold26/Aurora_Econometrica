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
- v2.0       — v1.2.0 (Awareness KPI + Weibull learnable). Additive optional fields:
               * kpi_type, kpi_likelihood, ceiling
               * awareness_aggregation_mode
               * channel_adstock_types, weibull_params_per_channel
               * comparison_baseline_posterior (для ROI shift dual-posterior)
               * feature_flags_used (telemetry)
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any

# Semantic version comparison helper (avoids stdlib `packaging` dep)
_VERSION_RE = re.compile(r'(\d+)\.(\d+)(?:\.(\d+))?')


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse 'X.Y' or 'X.Y.Z' (with optional suffix like '1.0-ols') → (X, Y, Z) tuple.

    Returns (0, 0, 0) для unparseable strings (defensive default — treated as
    legacy pre-v1.0).

    Why: string `<` comparison broken — '1.10' < '1.3' lexicographically (audit fix).
    """
    if not isinstance(v, str):
        return (0, 0, 0)
    m = _VERSION_RE.match(v)
    if not m:
        return (0, 0, 0)
    major, minor, patch = m.groups()
    return (int(major), int(minor), int(patch) if patch else 0)


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

    # v2.0 additive fields (default к pre-v2.0 behavior)
    model_data.setdefault('kpi_type', 'sales')
    model_data.setdefault('kpi_likelihood', 'normal')
    model_data.setdefault('awareness_aggregation_mode', None)
    model_data.setdefault('channel_adstock_types', {})       # default per-channel = 'geometric'
    model_data.setdefault('weibull_params_per_channel', {})  # learned (peak_week, tail_decay)
    model_data.setdefault('comparison_baseline_posterior', None)  # для ROI shift toggle
    model_data.setdefault('feature_flags_used', [])          # telemetry

    return model_data


def get_kpi_type(model_data: dict[str, Any]) -> str:
    """Return KPI type из pickle. Default 'sales' для backward compat."""
    return str(model_data.get('kpi_type') or 'sales')


def is_awareness_model(model_data: dict[str, Any]) -> bool:
    """True если pickle обучен в awareness mode."""
    return get_kpi_type(model_data) == 'awareness'


def get_adstock_type(model_data: dict[str, Any], channel: str) -> str:
    """Return adstock type для конкретного канала.

    Returns:
        'geometric' (default) or 'weibull'.
    """
    types = model_data.get('channel_adstock_types') or {}
    return str(types.get(channel) or 'geometric')


def get_weibull_params(
    model_data: dict[str, Any], channel: str
) -> dict[str, float] | None:
    """Return learned Weibull params для канала, None если geometric.

    Defensive: если adstock_type='weibull' но params missing — log warning
    + return None (downstream silently falls back к geometric — better than crash,
    but warning surfaces malformed pickle).

    Returns:
        {'peak_week_median', 'tail_decay_median', 'lam_median', 'k_median'} or None.
    """
    if get_adstock_type(model_data, channel) != 'weibull':
        return None
    params = model_data.get('weibull_params_per_channel') or {}
    channel_params = params.get(channel)
    if channel_params is None:
        # Malformed pickle: declares Weibull но params missing
        import warnings
        warnings.warn(
            f"Channel '{channel}' marked as Weibull в pickle, но params missing в "
            f"weibull_params_per_channel. Falling back к geometric. "
            f"Возможна corrupted pickle или incomplete training.",
            RuntimeWarning,
            stacklevel=2,
        )
    return channel_params


def has_baseline_posterior(model_data: dict[str, Any]) -> bool:
    """True если pickle содержит cached single-prior baseline для ROI shift comparison."""
    return model_data.get('comparison_baseline_posterior') is not None


def get_baseline_posterior(model_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return cached baseline posterior summary, или None."""
    return model_data.get('comparison_baseline_posterior')


def get_feature_flags(model_data: dict[str, Any]) -> list[str]:
    """Return telemetry feature flags used during training."""
    flags = model_data.get('feature_flags_used') or []
    return list(flags)


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
    """True если pickle обучен hierarchical (v1.3+ с непустыми categories).

    Audit fix (2026-04-28): semantic version compare — string `<` ломалось на '1.10'
    vs '1.3' (lex order: '1.10' < '1.3' = True, semantically False).
    """
    version = _parse_version(str(model_data.get('model_version') or ''))
    if version < (1, 3):
        return False
    cats = model_data.get('channel_categories') or {}
    if not cats:
        return False
    n_brand = sum(1 for c in cats.values() if c == 'brand')
    n_perf = sum(1 for c in cats.values() if c == 'performance')
    return n_brand >= 2 or n_perf >= 2
