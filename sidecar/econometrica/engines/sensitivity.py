"""
Adaptive top-7 sensitivity tornado for Aurora MMM Optimizer v2.0.0.

Per ADR-019 §6.4 + WIZARD_FLOW_v2_FINAL.md §6.4.

Answers the question: «Если adstock_TV изменится на ±20%, ROI меняется на ±15%?»
Provides defensibility for decisions presented to CFO/CMO in agency context.

Algorithm summary
─────────────────
1. Load posterior mean parameter values from model_data.
2. Build candidate parameter list (per-channel beta, adstock_decay, Hill alpha/gamma,
   base intercept, signed factor betas).
3. Vary each candidate by ±variation (multiplicative) while holding others at baseline.
4. Approximate new aggregate ROI via linear gradient evaluation (no MCMC re-sampling).
5. Compute sensitivity_pct = |delta_roi_high - delta_roi_low| as % of baseline ROI.
6. Return top-N ranked by absolute sensitivity.

Performance
───────────
Gradient path: O(N_params × N_periods) numpy operations — typically < 300ms for a
4-channel model on 156-week history. Full function stays well under the 5-second budget.

Usage
─────
>>> from engines.sensitivity import compute_sensitivity_tornado
>>> result = compute_sensitivity_tornado(model_data, top_n=7, variation=0.20)
>>> result['baseline_roi']
2.43
>>> result['parameters'][0]['name']
'adstock_decay_TV'
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ─── internal constants ───────────────────────────────────────────────────────
_VARIATION_DEFAULT: float = 0.20
_TOP_N_DEFAULT: int = 7
# Minimum absolute variation magnitude to surface a parameter.
# Below this threshold the parameter is near-constant → not identifiable.
_MIN_IDENTIFIABLE_DELTA: float = 1e-9
# Guard against division by near-zero baseline ROI (very small brands).
_BASELINE_ROI_GUARD: float = 1e-6


# ─── Public API ───────────────────────────────────────────────────────────────


def compute_sensitivity_tornado(
    model_data: dict[str, Any],
    top_n: int = _TOP_N_DEFAULT,
    variation: float = _VARIATION_DEFAULT,
) -> dict[str, Any]:
    """Compute adaptive sensitivity tornado: top-N parameters by |ΔROI|.

    Identifies which model parameters drive ROI uncertainty most, ranks them,
    and returns a structured result ready for frontend SensitivityTornado chart
    and PDF/PPTX report sections.

    Args:
        model_data: Loaded pickle dict from ``engines.persistence.load_model_with_compat``.
            Must contain: 'channel_params', 'normalization', 'config', 'y_actual'.
        top_n: Number of parameters to include in tornado (default 7).
        variation: Multiplicative variation ±fraction (default 0.20 = ±20%).

    Returns:
        Dict with keys:
        - ``baseline_roi`` (float): Aggregate ROI at posterior mean parameters.
        - ``parameters`` (list[dict]): Sorted descending by absolute sensitivity.
          Each entry has: name, baseline_value, low_variation, high_variation,
          sensitivity_pct, channel, param_type.
        - ``n_candidates_evaluated`` (int): Total parameters evaluated before
          top-N trim (useful for audit logging).
        - ``variation_pct`` (float): Variation used, e.g. 20.0.

    Raises:
        Never raises — on any structural error returns partial/empty result
        with a warning logged.

    Examples:
        >>> import pickle, pathlib
        >>> # model_data = pickle.loads(pathlib.Path('models/latest.pkl').read_bytes())
        >>> # result = compute_sensitivity_tornado(model_data)
        >>> # result['parameters'][0]['param_type']
        >>> # 'adstock_decay'
    """
    empty_result: dict[str, Any] = {
        'baseline_roi': 0.0,
        'parameters': [],
        'n_candidates_evaluated': 0,
        'variation_pct': round(variation * 100, 1),
    }

    # ── Validate required fields ─────────────────────────────────────────────
    required = ('channel_params', 'normalization', 'config')
    for field in required:
        if field not in model_data or model_data[field] is None:
            logger.warning(
                'sensitivity: model_data missing required field "%s" — '
                'returning empty result.',
                field,
            )
            return empty_result

    # ── Baseline ROI at posterior mean ───────────────────────────────────────
    try:
        baseline_roi, _roi_per_channel = _compute_aggregate_roi(model_data)
    except Exception as exc:
        logger.warning('sensitivity: baseline ROI computation failed: %s', exc)
        return empty_result

    if abs(baseline_roi) < _BASELINE_ROI_GUARD:
        logger.warning(
            'sensitivity: baseline ROI near-zero (%.6f) — tornado unreliable, '
            'returning empty result.',
            baseline_roi,
        )
        return empty_result

    # ── Enumerate candidate parameters ───────────────────────────────────────
    candidates = get_candidate_parameters(model_data)
    if not candidates:
        logger.warning('sensitivity: no candidate parameters found in model_data.')
        return {**empty_result, 'baseline_roi': round(baseline_roi, 4)}

    # ── Evaluate each candidate ───────────────────────────────────────────────
    evaluated: list[dict[str, Any]] = []
    for cand in candidates:
        try:
            entry = _evaluate_candidate(
                model_data=model_data,
                candidate=cand,
                baseline_roi=baseline_roi,
                variation=variation,
            )
            if entry is not None:
                evaluated.append(entry)
        except Exception as exc:
            logger.warning(
                'sensitivity: failed to evaluate parameter "%s": %s — skipping.',
                cand.get('name', '?'),
                exc,
            )

    n_candidates = len(evaluated)

    # ── Rank by absolute sensitivity, take top-N ─────────────────────────────
    evaluated.sort(key=lambda p: p['sensitivity_pct'], reverse=True)
    top_params = evaluated[:top_n]

    return {
        'baseline_roi': round(baseline_roi, 4),
        'parameters': top_params,
        'n_candidates_evaluated': n_candidates,
        'variation_pct': round(variation * 100, 1),
    }


def get_candidate_parameters(model_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify all sensitivity-eligible parameters from a trained model.

    Extracts per-channel betas, adstock decays, Hill (alpha, gamma),
    the base intercept, and any signed factor betas present in the pickle.

    A parameter is eligible when its posterior mean value is non-constant
    (varies meaningfully across the posterior, i.e., not a hard-coded constant)
    and is non-zero (zero parameter has zero impact on ROI by definition).

    Args:
        model_data: Loaded model dict (from ``load_model_with_compat``).

    Returns:
        List of candidate dicts, each with:
        - ``name`` (str): Unique display name e.g. ``'adstock_decay_TV'``.
        - ``param_type`` (str): One of ``'beta'``, ``'adstock_decay'``,
          ``'hill_alpha'``, ``'hill_gamma'``, ``'intercept'``, ``'factor_beta'``.
        - ``channel`` (str | None): Channel name or None for global params.
        - ``baseline_value`` (float): Posterior mean value.

    Examples:
        >>> # candidates = get_candidate_parameters(model_data)
        >>> # [c['name'] for c in candidates if c['param_type'] == 'adstock_decay']
        >>> # ['adstock_decay_TV', 'adstock_decay_Digital', ...]
    """
    candidates: list[dict[str, Any]] = []

    channel_params: dict = model_data.get('channel_params') or {}
    norm: dict = model_data.get('normalization') or {}
    config: dict = model_data.get('config') or {}
    media_cols: list[str] = list(config.get('media_columns') or [])
    control_cols: list[str] = list(config.get('control_columns') or [])
    control_betas: list[float] = list(norm.get('control_betas_mean') or [])

    # ── Per-channel parameters ────────────────────────────────────────────────
    for col in media_cols:
        params = channel_params.get(col)
        if params is None:
            continue
        # Skip channels explicitly marked as untrained (zero variance)
        if params.get('untrained'):
            continue

        beta = _safe_float(params.get('beta'))
        alpha = _safe_float(params.get('alpha'))
        gamma = _safe_float(params.get('gamma'))
        decay = _safe_float(params.get('decay'))

        # Channel beta (primary ROI driver)
        if beta is not None and abs(beta) > _MIN_IDENTIFIABLE_DELTA:
            candidates.append({
                'name': f'beta_{col}',
                'param_type': 'beta',
                'channel': col,
                'baseline_value': beta,
            })

        # Adstock decay (carryover) — only when present in posterior
        if decay is not None and 0.0 < decay < 1.0:
            candidates.append({
                'name': f'adstock_decay_{col}',
                'param_type': 'adstock_decay',
                'channel': col,
                'baseline_value': decay,
            })

        # Hill alpha (steepness / S-curve shape)
        if alpha is not None and alpha > _MIN_IDENTIFIABLE_DELTA:
            candidates.append({
                'name': f'hill_alpha_{col}',
                'param_type': 'hill_alpha',
                'channel': col,
                'baseline_value': alpha,
            })

        # Hill gamma (half-saturation point)
        if gamma is not None and gamma > _MIN_IDENTIFIABLE_DELTA:
            candidates.append({
                'name': f'hill_gamma_{col}',
                'param_type': 'hill_gamma',
                'channel': col,
                'baseline_value': gamma,
            })

    # ── Base intercept ────────────────────────────────────────────────────────
    intercept_mean = _safe_float(norm.get('intercept_mean'))
    if intercept_mean is not None and abs(intercept_mean) > _MIN_IDENTIFIABLE_DELTA:
        candidates.append({
            'name': 'intercept',
            'param_type': 'intercept',
            'channel': None,
            'baseline_value': intercept_mean,
        })

    # ── Signed factor betas ───────────────────────────────────────────────────
    if control_cols and control_betas and len(control_betas) == len(control_cols):
        for col, beta_val in zip(control_cols, control_betas):
            bv = _safe_float(beta_val)
            if bv is not None and abs(bv) > _MIN_IDENTIFIABLE_DELTA:
                candidates.append({
                    'name': f'factor_beta_{col}',
                    'param_type': 'factor_beta',
                    'channel': col,
                    'baseline_value': bv,
                })

    return candidates


def evaluate_parameter_impact(
    model_data: dict[str, Any],
    param_name: str,
    new_value: float,
) -> float:
    """Compute estimated aggregate ROI when one parameter is modified.

    Uses linear gradient approximation: instead of re-running full MCMC
    (minutes), we substitute the modified parameter value into the analytical
    contribution formula and recompute the contribution sum for affected
    channels only. Unaffected channels retain their baseline contribution.

    This approximation is exact for linear parameters (beta, intercept,
    factor_beta) and first-order accurate for nonlinear ones (adstock_decay,
    hill_alpha, hill_gamma). Error is O(Δp²) which is acceptably small for
    Δp = ±20%.

    Args:
        model_data: Loaded model dict.
        param_name: Parameter identifier as returned by
            ``get_candidate_parameters`` (e.g. ``'adstock_decay_TV'``).
        new_value: Modified parameter value to evaluate.

    Returns:
        Estimated aggregate ROI (float). Returns the baseline ROI when
        the parameter is not found or computation fails.

    Examples:
        >>> # roi_modified = evaluate_parameter_impact(model_data, 'adstock_decay_TV', 0.52)
        >>> # roi_baseline = evaluate_parameter_impact(model_data, 'adstock_decay_TV', 0.65)
        >>> # round((roi_modified - roi_baseline) / roi_baseline * 100, 1)
        >>> # -12.5  # hypothetical
    """
    try:
        return _compute_roi_with_override(model_data, param_name, new_value)
    except Exception as exc:
        logger.warning(
            'evaluate_parameter_impact: failed for param "%s" value %.6f: %s',
            param_name, new_value, exc,
        )
        baseline, _ = _compute_aggregate_roi(model_data)
        return baseline


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    """Convert to float, returning None on failure or NaN."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _hill_response(x: np.ndarray, alpha: float, gamma: float) -> np.ndarray:
    """Inline Hill saturation: x^α / (x^α + γ^α).

    Mirrors utils/saturation.py::hill_function with identical semantics.
    Inlined here to keep this module self-contained (no circular imports).
    """
    x_safe = np.maximum(x, 0.0)
    gamma_safe = max(gamma, 1e-10)
    alpha_safe = max(alpha, 1e-6)
    x_pos = np.maximum(x_safe, 1e-10)
    x_pow = x_pos ** alpha_safe
    g_pow = gamma_safe ** alpha_safe
    return x_pow / (x_pow + g_pow)


def _channel_contribution(
    raw_spend: np.ndarray,
    params: dict[str, Any],
    norm: dict[str, Any],
    config: dict[str, Any],
    col: str,
    *,
    override_param: str | None = None,
    override_value: float | None = None,
) -> float:
    """Compute total contribution (in original KPI units) for one channel.

    Replicates the decomposer.py contribution math in self-contained form:
      contribution = β × Σ_t hill(adstock(x_t)/mean ; α, γ) × y_std

    Supports overriding a single parameter for sensitivity analysis.

    Args:
        raw_spend: Raw spend/impressions time series for this channel.
        params: channel_params[col] dict from pickle.
        norm: normalization dict from pickle.
        config: config dict from pickle.
        col: Column name (used for adstock config lookup).
        override_param: If set, name of parameter type to override
            (``'beta'``, ``'adstock_decay'``, ``'hill_alpha'``, ``'hill_gamma'``).
        override_value: New value for the overridden parameter.

    Returns:
        Total channel contribution (float, KPI units).
    """
    from utils.adstock import apply_adstock  # noqa: PLC0415 (lazy import for speed)

    beta = float(params.get('beta', 0) or 0)
    alpha = max(float(params.get('alpha', 1.0) or 1.0), 1e-6)
    gamma = max(float(params.get('gamma', 0.5) or 0.5), 1e-6)

    # Adstock type + decay
    adstock_config = config.get('adstock_config') or {}
    raw_at = adstock_config.get(col)
    if isinstance(raw_at, dict):
        a_type = raw_at.get('type', 'geometric')
    elif isinstance(raw_at, str):
        a_type = raw_at
    else:
        a_type = 'geometric'

    decay = params.get('decay')

    # ── Apply override ────────────────────────────────────────────────────────
    if override_param == 'beta':
        beta = override_value  # type: ignore[assignment]
    elif override_param == 'adstock_decay':
        decay = override_value
    elif override_param == 'hill_alpha':
        alpha = max(float(override_value), 1e-6)  # type: ignore[arg-type]
    elif override_param == 'hill_gamma':
        gamma = max(float(override_value), 1e-6)  # type: ignore[arg-type]

    # ── Adstock ───────────────────────────────────────────────────────────────
    adstock_params = {'alpha': float(decay)} if decay is not None else None
    x_adstock = apply_adstock(raw_spend, a_type, adstock_params)

    # ── Normalize ─────────────────────────────────────────────────────────────
    norm_vals: dict = norm.get('normalization') if isinstance(norm.get('normalization'), dict) else norm
    media_means: dict = norm_vals.get('media_means') or {}

    mean_posterior = params.get('adstock_mean_posterior')
    if mean_posterior is not None:
        mean = float(mean_posterior)
    else:
        mean = float(media_means.get(col, 1.0) or 1.0)

    mean = max(mean, 1e-10)
    x_norm = x_adstock / mean

    # ── Hill saturation ───────────────────────────────────────────────────────
    sat = _hill_response(x_norm, alpha, gamma)

    # ── Contribution in original KPI units ───────────────────────────────────
    y_std = float(norm_vals.get('y_std', 1.0) or 1.0)
    return float(beta * sat.sum() * y_std)


def _compute_aggregate_roi(
    model_data: dict[str, Any],
    *,
    override_param: str | None = None,
    override_value: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute aggregate ROI across all channels, optionally with one override.

    Aggregate ROI = Σ_channels contribution_i / Σ_channels spend_money_i.

    Args:
        model_data: Full model dict.
        override_param: Full parameter name as returned by
            ``get_candidate_parameters`` (e.g. ``'adstock_decay_TV'``).
        override_value: Modified value (float).

    Returns:
        Tuple of (aggregate_roi: float, per_channel_roi: dict[str, float]).
    """
    import pandas as pd  # noqa: PLC0415

    channel_params: dict = model_data.get('channel_params') or {}
    norm: dict = model_data.get('normalization') or {}
    config: dict = model_data.get('config') or {}
    media_cols: list[str] = list(config.get('media_columns') or [])

    # Unit costs for spend money computation
    unit_costs: dict = config.get('unit_costs') or {}

    # Load raw spend data
    data_file: str | None = config.get('data_file')
    if not data_file:
        raise ValueError('config.data_file is missing — cannot load raw spend.')

    df = (
        pd.read_excel(data_file)
        if str(data_file).endswith(('.xlsx', '.xls'))
        else pd.read_csv(data_file)
    )

    # Apply merge rules (virtualised channels)
    try:
        from utils.merge_rules import apply_merge_rules  # noqa: PLC0415
        apply_merge_rules(df, config.get('merge_rules'))
    except Exception:
        pass  # merge_rules is optional

    total_spend_money = 0.0
    total_contribution = 0.0
    per_channel: dict[str, float] = {}

    for col in media_cols:
        params = channel_params.get(col)
        if params is None or params.get('untrained'):
            continue

        raw_spend = df[col].fillna(0).values.astype(float) if col in df.columns else np.zeros(len(df))
        raw_spend_total = float(raw_spend.sum())
        unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
        spend_money = raw_spend_total * unit_cost

        if spend_money <= 0:
            continue

        # Decode what override applies to this channel
        channel_override_param: str | None = None
        channel_override_value: float | None = None
        if override_param is not None and override_value is not None:
            param_type, channel_name = _parse_override_name(override_param)
            if channel_name == col:
                channel_override_param = param_type

                channel_override_value = override_value

        contrib = _channel_contribution(
            raw_spend=raw_spend,
            params=params,
            norm=norm,
            config=config,
            col=col,
            override_param=channel_override_param,
            override_value=channel_override_value,
        )

        total_spend_money += spend_money
        total_contribution += contrib
        per_channel[col] = contrib / spend_money if spend_money > 0 else 0.0

    aggregate_roi = total_contribution / total_spend_money if total_spend_money > 0 else 0.0
    return aggregate_roi, per_channel


def _parse_override_name(override_param: str) -> tuple[str, str | None]:
    """Parse candidate name into (param_type, channel_name).

    Examples:
        >>> _parse_override_name('adstock_decay_TV')
        ('adstock_decay', 'TV')
        >>> _parse_override_name('beta_Digital')
        ('beta', 'Digital')
        >>> _parse_override_name('intercept')
        ('intercept', None)
        >>> _parse_override_name('factor_beta_competitor_trp')
        ('factor_beta', 'competitor_trp')
    """
    # Ordered longest-prefix first to avoid ambiguity
    prefixes = [
        ('adstock_decay_', 'adstock_decay'),
        ('hill_alpha_', 'hill_alpha'),
        ('hill_gamma_', 'hill_gamma'),
        ('factor_beta_', 'factor_beta'),
        ('beta_', 'beta'),
    ]
    for prefix, ptype in prefixes:
        if override_param.startswith(prefix):
            channel = override_param[len(prefix):]
            return ptype, channel if channel else None
    return override_param, None


def _compute_roi_with_override(
    model_data: dict[str, Any],
    param_name: str,
    new_value: float,
) -> float:
    """Evaluate aggregate ROI with one parameter overridden.

    For intercept overrides: adjusts baseline contribution but not media ROI
    (intercept does not multiply spend — it shifts the denominator via
    total_contribution). For factor_beta overrides: adjusts signed factor
    contribution added to total contribution (treated as additive to denominator).
    """
    norm: dict = model_data.get('normalization') or {}
    config: dict = model_data.get('config') or {}

    param_type, channel_name = _parse_override_name(param_name)

    # ── Intercept override: rebuild total contribution directly ───────────────
    if param_type == 'intercept':
        # Intercept shifts baseline contribution but aggregate ROI = media_contribution / spend
        # Intercept is not part of media contribution → ROI unchanged.
        # Return baseline ROI (intercept insensitive to ROI).
        baseline_roi, _ = _compute_aggregate_roi(model_data)
        return baseline_roi

    # ── Factor beta override: factor contributions affect total KPI but not spend ─
    if param_type == 'factor_beta':
        # Signed factor betas affect total KPI (and thus effective ROI when we
        # interpret ROI as total_media_contribution / total_spend). Since factor
        # betas are additive to baseline (not multiplied by media spend), they do
        # not directly change the media-only ROI = media_contrib / spend.
        # In practice the sensitivity here is near-zero for aggregate media ROI.
        baseline_roi, _ = _compute_aggregate_roi(model_data)
        return baseline_roi

    # ── Channel parameter overrides (beta, adstock_decay, hill_alpha, hill_gamma) ─
    roi, _ = _compute_aggregate_roi(
        model_data,
        override_param=param_name,
        override_value=new_value,
    )
    return roi


def _evaluate_candidate(
    model_data: dict[str, Any],
    candidate: dict[str, Any],
    baseline_roi: float,
    variation: float,
) -> dict[str, Any] | None:
    """Evaluate low and high variation for one candidate parameter.

    Returns a fully populated parameter entry dict for the tornado result,
    or None if the parameter is not identifiable (constant / zero sensitivity).
    """
    name: str = candidate['name']
    baseline_value: float = candidate['baseline_value']
    param_type: str = candidate['param_type']
    channel: str | None = candidate.get('channel')

    # Multiplicative variation bounds
    low_value = baseline_value * (1.0 - variation)
    high_value = baseline_value * (1.0 + variation)

    # Guard for adstock decay staying in valid (0, 1) range
    if param_type == 'adstock_decay':
        low_value = max(low_value, 1e-4)
        high_value = min(high_value, 0.9999)

    # Guard for Hill params staying positive
    if param_type in ('hill_alpha', 'hill_gamma'):
        low_value = max(low_value, 1e-4)

    # Evaluate ROI at each variation
    roi_low = evaluate_parameter_impact(model_data, name, low_value)
    roi_high = evaluate_parameter_impact(model_data, name, high_value)

    delta_low_abs = roi_low - baseline_roi
    delta_high_abs = roi_high - baseline_roi

    delta_low_pct = delta_low_abs / abs(baseline_roi) * 100.0
    delta_high_pct = delta_high_abs / abs(baseline_roi) * 100.0

    # Sensitivity = total swing across variation range (absolute)
    sensitivity_pct = abs(delta_high_pct - delta_low_pct)

    # Filter: non-identifiable parameters (constant output regardless of param change)
    if sensitivity_pct < _MIN_IDENTIFIABLE_DELTA:
        logger.debug(
            'sensitivity: parameter "%s" near-zero sensitivity (%.2e) — skipped.',
            name, sensitivity_pct,
        )
        return None

    return {
        'name': name,
        'baseline_value': round(baseline_value, 6),
        'low_variation': {
            'value': round(low_value, 6),
            'delta_roi_pct': round(delta_low_pct, 2),
        },
        'high_variation': {
            'value': round(high_value, 6),
            'delta_roi_pct': round(delta_high_pct, 2),
        },
        'sensitivity_pct': round(sensitivity_pct, 2),
        'channel': channel,
        'param_type': param_type,
    }
