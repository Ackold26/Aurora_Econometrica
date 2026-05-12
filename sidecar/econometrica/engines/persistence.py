"""Pickle persistence helpers for Aurora Econometrica models.

Trust Level 3 (v1.1.0) added `model_version='1.3'` с polem `channel_categories`.
Этот модуль централизует pickle compat - все downstream consumers (decomposer,
optimizer, scenario, narrative_adapter, backtest, html_export) должны use
`load_model_with_compat()` вместо direct pickle.load().

Migration ladder:
- v1.0       - initial OLS path (rejected by decomposer guard, MODEL_OUTDATED)
- v1.0-ols   - Sprint 2 small-data fallback (point estimates, no posterior CI)
- v1.1       - v1.0.13+ Bayesian baseline (z-score → spend/mean Hill normalization)
- v1.1.1     - Phase 1.1 hierarchical adstock decay (logit-normal, sampled per channel)
- v1.2       - v1.0.16 baseline (post-audit fixes, three-way alignment)
- v1.3       - Trust Level 3 (Brand vs Performance Split, channel_categories field)
- v2.0       - v1.2.0 (Awareness KPI + Weibull learnable). Additive optional fields:
               * kpi_type, kpi_likelihood, ceiling
               * awareness_aggregation_mode
               * channel_adstock_types, weibull_params_per_channel
               * comparison_baseline_posterior (для ROI shift dual-posterior)
               * feature_flags_used (telemetry)
               * Phase 2 additions (Planning Mode, audit pass 2 2026-05-02):
                 - training_granularity: 'D'|'W'|'M'|'Q'|'Y' (auto-detected)
                 - train_x_norm_quantiles: dict[channel, {p50,p75,p90,p95,p99}]
                 - seasonality_detected: dict | None ({period, autocorr})
                 Pickles trained pre-Phase-2 lack these fields; G2 inference
                 helpers (infer_*_at_load) compute lazily on first need.
                 S8 lock - no reserved future fields, additive evolution only.
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

    Returns (0, 0, 0) для unparseable strings (defensive default - treated as
    legacy pre-v1.0).

    Why: string `<` comparison broken - '1.10' < '1.3' lexicographically (audit fix).
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
    - `model_version` always present (default '1.0' если field missing - legacy).
    - Old fields preserved verbatim.

    NB: Не infers categories автоматически - оставляет `{}` для downstream choice.
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

    # Phase 2 (Planning Mode) - pre-Phase-2 pickles get None defaults; G2 inference
    # helpers compute lazily when planning mode actually queries them.
    model_data.setdefault('training_granularity', None)
    model_data.setdefault('train_x_norm_quantiles', None)
    model_data.setdefault('seasonality_detected', None)

    # v1.3.0 additive fields (per ADR-017 - schema bump skipped, in-memory inject only).
    # Defaults match v1.2 behavior: monetary KPI, all channels in ₽, mode=roi, no goal-seek history.
    _inject_v13_defaults(model_data)

    return model_data


def _inject_v13_defaults(model_data: dict[str, Any]) -> None:
    """Inject v1.3.0 additive fields with defaults derived from v1.2 state.

    Per ADR-017 (Bundle schema v1.3 additive). Mutates dict in place.

    - kpi_kind: derived from kpi_type via registry. 'sales' → monetary, 'awareness' → proportional,
      count KPIs → count.
    - per_channel_input: dict {channel: 'monetary'|'physical'}. Derived from старый
      analysisObjective field (frontend) или by default - все каналы как monetary.
    - derived_mode: 'roi'|'effectiveness'|'manual'. Computed from per_channel_input.
    - value_per_count_unit, label, source: None defaults; populated в Validate UI для count KPIs.
    - goal_seek_history: append-only log, empty list default.
    """
    kpi_type = model_data.get('kpi_type') or 'sales'

    # kpi_kind from registry (graceful fallback to 'monetary' if KPI not registered).
    if 'kpi_kind' not in model_data:
        try:
            from utils.kpi_registry import get_kpi_config
            kpi_kind = get_kpi_config(kpi_type).kpi_kind
        except (ValueError, ImportError):
            kpi_kind = 'monetary'  # safe fallback
        model_data['kpi_kind'] = kpi_kind

    # per_channel_input: default - all media columns as 'monetary'.
    if 'per_channel_input' not in model_data:
        config = model_data.get('config') or {}
        # Audit fix v1.3.0: explicit null-check (was: `config.get('media_columns', []) or []`
        # could mask `media_columns: None` corruption).
        media_cols_raw = config.get('media_columns')
        media_cols = list(media_cols_raw) if media_cols_raw else []
        # Старый frontend store analysisObjective не сохранялся в pickle, но мог быть
        # передан через config['analysis_objective'] (legacy field).
        legacy_objective = config.get('analysis_objective', 'roi')
        if legacy_objective == 'effectiveness':
            default_metric = 'physical'
        else:
            default_metric = 'monetary'  # 'roi' и 'manual' → default monetary (manual override приходит из bundle)
        model_data['per_channel_input'] = {ch: default_metric for ch in media_cols}

    # derived_mode: lazy compute через mode_inference if absent.
    if 'derived_mode' not in model_data:
        try:
            from utils.mode_inference import derive_mode
            model_data['derived_mode'] = derive_mode(model_data['per_channel_input'])
        except (ValueError, ImportError):
            model_data['derived_mode'] = 'roi'  # safe fallback

    # value_per_count_unit: None default; populated by user in Validate UI.
    model_data.setdefault('value_per_count_unit', None)
    model_data.setdefault('value_per_count_unit_label', '')
    model_data.setdefault('value_per_count_unit_source', None)  # 'auto'|'manual'|'imported'|None

    # goal_seek_history: append-only log of past goal-seek runs.
    model_data.setdefault('goal_seek_history', [])

    # safe_corridor_cache: lazy invalidate on retrain.
    model_data.setdefault('safe_corridor_cache', None)


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

    Defensive: если adstock_type='weibull' но params missing - log warning
    + return None (downstream silently falls back к geometric - better than crash,
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
        fallback_heuristic: если True и categories пусты - derive из имён каналов
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


# ─── Phase 2 (Planning Mode) - at-load-time inference helpers (G2 plan gap) ───
#
# For pre-Phase-2 customer pickles (v1.3 = current ship), the new Phase 2
# fields are absent. Rather than force re-train, infer lazily when planning
# mode actually queries them. Caller is responsible for caching на pickle
# basis (computation is non-trivial для quantiles + seasonality).
# ──────────────────────────────────────────────────────────────────────────


def get_training_granularity(model_data: dict[str, Any]) -> str | None:
    """Phase 2 - return persisted training_granularity или infer from data_file.

    Persisted-first; falls back к infer_granularity_at_load() для legacy pickles.
    Returns None если cannot infer (no data file accessible, e.g., moved/deleted).
    """
    persisted = model_data.get('training_granularity')
    if persisted:
        return str(persisted)
    return infer_granularity_at_load(model_data)


def infer_granularity_at_load(model_data: dict[str, Any]) -> str | None:
    """G2 - infer granularity from model_data.config.data_file at load time.

    Heavy I/O - каллер should cache. Returns None when data_file inaccessible.
    """
    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    date_col = config.get('date_column', 'date')
    if not data_file:
        return None
    try:
        import pandas as pd
        df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
        if date_col not in df.columns:
            return None
        from utils.forecast_validation import detect_granularity
        result = detect_granularity(df[date_col])
        return result['granularity'] if result['confidence'] >= 0.4 else None
    except Exception:
        return None


def get_seasonality(model_data: dict[str, Any]) -> dict | None:
    """Phase 2 - return persisted seasonality_detected или infer at load.

    Persisted-first; falls back к infer_seasonality_at_load() для legacy pickles.
    """
    persisted = model_data.get('seasonality_detected')
    if persisted is not None:
        return persisted if isinstance(persisted, dict) else None
    return infer_seasonality_at_load(model_data)


def infer_seasonality_at_load(model_data: dict[str, Any]) -> dict | None:
    """G2 - infer seasonality from training y_actual at load time.

    Uses y_actual stored в diagnostics.actual_vs_predicted (always present
    в v1.1+ pickles). Returns None when unavailable.
    """
    diagnostics = model_data.get('diagnostics') or {}
    avp = diagnostics.get('actual_vs_predicted') or {}
    y_actual = avp.get('actual')
    if not y_actual:
        return None
    granularity = get_training_granularity(model_data) or 'W'
    try:
        from utils.forecast_validation import detect_seasonality
        return detect_seasonality(y_actual, granularity=granularity)
    except Exception:
        return None


def get_x_norm_quantiles(
    model_data: dict[str, Any], channel: str,
) -> dict[str, float] | None:
    """Phase 2 - return persisted x_norm quantiles per channel или infer.

    Persisted-first; falls back к infer_x_norm_quantiles_at_load() для legacy.
    Returns None when channel missing OR inference impossible (no posterior + raw spend).
    """
    persisted = model_data.get('train_x_norm_quantiles')
    if persisted and channel in persisted:
        return persisted[channel]
    inferred = infer_x_norm_quantiles_at_load(model_data)
    return inferred.get(channel) if inferred else None


def infer_x_norm_quantiles_at_load(
    model_data: dict[str, Any],
) -> dict[str, dict[str, float]] | None:
    """G2 - recompute x_norm quantiles from training adstock + posterior decay.

    For each channel:
      adstock_series = geometric_adstock(raw_train_spend, decay_posterior_mean)
      x_norm_series = adstock_series / adstock_mean_posterior
      quantiles = {p50, p75, p90, p95, p99}

    Heavy: reads training data, applies adstock per channel. Caller cache.
    Returns None when raw spend OR posterior decay inaccessible.
    """
    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    if not data_file:
        return None
    channel_params = model_data.get('channel_params') or {}
    if not channel_params:
        return None

    try:
        import pandas as pd
        df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
        from utils.merge_rules import apply_merge_rules
        apply_merge_rules(df, config.get('merge_rules'))
        from utils.adstock import apply_adstock
        from utils.forecast_validation import compute_x_norm_quantiles
    except Exception:
        return None

    out: dict[str, dict[str, float]] = {}
    for col, p in channel_params.items():
        if col not in df.columns:
            continue
        raw_spend = df[col].fillna(0).values.astype(float)
        if raw_spend.size == 0:
            continue
        decay = p.get('decay')
        a_type = get_adstock_type(model_data, col)
        params = {'alpha': float(decay)} if decay is not None else None
        try:
            adstock_series = apply_adstock(raw_spend, a_type, params)
        except Exception:
            continue
        # Mean - prefer adstock_mean_posterior, fallback к media_means
        norm = (model_data.get('normalization') or {})
        mean_post = p.get('adstock_mean_posterior')
        if mean_post is not None:
            mean = float(mean_post)
        else:
            mean = float(norm.get('media_means', {}).get(col, 1.0) or 1.0)
        if mean <= 0:
            continue
        out[col] = compute_x_norm_quantiles(adstock_series, mean)
    return out if out else None


def is_hierarchical_model(model_data: dict[str, Any]) -> bool:
    """True если pickle обучен hierarchical (v1.3+ с непустыми categories).

    Audit fix (2026-04-28): semantic version compare - string `<` ломалось на '1.10'
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
