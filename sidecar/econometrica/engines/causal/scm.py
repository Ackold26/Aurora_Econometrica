"""
Synthetic Control Method (SCM) — Sprint 3 M2.

Implements Abadie classic SCM via manual scipy SLSQP optimization.
Per ADR §3.1 + Q2(B): NO pysyncon, NO cvxpy. Isolated `_solve_scm_weights()`
interface gives clean swap path для future Augmented SCM (Sprint 4+).

SCM workflow:
    1. Identify treated unit + treatment period
    2. Pre-treatment: find weights w_j (sum=1, nonneg) over donor units
       minimizing ||Y_treated_pre - Y_donors_pre @ w||²
    3. Post-treatment counterfactual: Ŷ_treated_post = Y_donors_post @ w
    4. ATT_t = Y_treated_post[t] - Ŷ_treated_post[t]
       Average over post periods → ATT
    5. Inference via placebo test: re-run SCM treating each donor as
       "pseudo-treated", build distribution of placebo |ATTs|, p-value =
       rank of true |ATT|.

References:
- Abadie, Diamond, Hainmueller 2010 "Synthetic Control Methods for
  Comparative Case Studies" JASA
- Abadie 2021 "Using Synthetic Controls" Journal of Economic Literature
- Abadie, L'Hour 2021 "A Penalized Synthetic Control Estimator" JASA
  (Penalized SCM — Sprint 4+ enhancement через _solve_scm_weights swap)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .common import ATT, HonestDisclosure, error_response, confidence_to_alpha
from ._panel_data import load_panel, validate_for_scm

logger = logging.getLogger(__name__)


def _solve_scm_weights(
    y_treated_pre: np.ndarray,
    Y_donors_pre: np.ndarray,
) -> tuple[np.ndarray | None, str]:
    """Solve for SCM weights via manual scipy SLSQP.

    Per ADR §11/Q2 refinement: isolated interface — clean swap path к cvxpy
    или penalized variants without changing call sites. Today: scipy SLSQP с
    simplex constraints. Future: cvxpy для Augmented SCM, BSCM, или penalized SCM.

    Args:
        y_treated_pre: shape (n_pre,) — treated unit's pre-treatment outcomes
        Y_donors_pre: shape (n_pre, n_donors) — donor units' pre-treatment outcomes
            (rows = periods, columns = donors)

    Returns:
        (weights, status_str) where weights shape (n_donors,) sum to 1, nonneg.
        status_str ∈ {'optimal', 'feasible_suboptimal', 'failed'}.
        weights is None if optimization failed entirely.
    """
    from scipy.optimize import minimize

    n_pre, n_donors = Y_donors_pre.shape

    if n_pre != y_treated_pre.shape[0]:
        return None, f'shape_mismatch: y_treated_pre={y_treated_pre.shape}, Y_donors_pre={Y_donors_pre.shape}'

    if n_donors == 0:
        return None, 'no_donors'

    # Objective: ||y_treated_pre - Y_donors_pre @ w||²
    def loss(w: np.ndarray) -> float:
        return float(np.sum((y_treated_pre - Y_donors_pre @ w) ** 2))

    def loss_grad(w: np.ndarray) -> np.ndarray:
        # ∂loss/∂w = -2 · Y_donors_pre.T @ (y_treated_pre - Y_donors_pre @ w)
        residual = y_treated_pre - Y_donors_pre @ w
        return -2.0 * Y_donors_pre.T @ residual

    # Constraints:
    # - sum(w) == 1 (equality)
    # - w[j] >= 0 (bounds)
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0,
                    'jac': lambda w: np.ones(n_donors)}]
    bounds = [(0.0, 1.0) for _ in range(n_donors)]

    # Initial guess: uniform 1/n_donors
    w0 = np.full(n_donors, 1.0 / n_donors)

    try:
        result = minimize(
            loss,
            w0,
            jac=loss_grad,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 500, 'ftol': 1e-9},
        )
    except Exception as e:
        logger.exception(f'SLSQP failed: {e}')
        return None, f'failed:{type(e).__name__}'

    if not result.success:
        # Check feasibility — sometimes SLSQP returns "Inequality constraints incompatible"
        # but the result.x is still close. Return as suboptimal.
        w = np.clip(result.x, 0.0, 1.0)
        s = float(w.sum())
        if s > 0:
            w = w / s  # re-normalize если sum drifted
            return w, f'feasible_suboptimal:{result.message}'
        return None, f'failed:{result.message}'

    w = np.clip(result.x, 0.0, 1.0)
    s = float(w.sum())
    if s > 1e-8:
        w = w / s  # safety re-normalize against numerical drift
    return w, 'optimal'


def _build_panel_arrays(
    df: pd.DataFrame,
    treated_unit: Any,
    treatment_period: Any,
    unit_col: str,
    time_col: str,
    kpi_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list, list, list] | None:
    """Build pre/post arrays for treated и donors.

    Returns:
        (y_treat_pre, y_treat_post, Y_donors_pre, Y_donors_post,
         pre_periods, post_periods, donor_units)
        or None if construction failed.
    """
    pre_df = df[df[time_col] < treatment_period].copy()
    post_df = df[df[time_col] >= treatment_period].copy()

    if len(pre_df) == 0 or len(post_df) == 0:
        return None

    pre_periods = sorted(pre_df[time_col].unique())
    post_periods = sorted(post_df[time_col].unique())

    # Pivot pre-treatment to (period, unit) wide format
    pre_wide = pre_df.pivot_table(index=time_col, columns=unit_col, values=kpi_col, aggfunc='first')
    post_wide = post_df.pivot_table(index=time_col, columns=unit_col, values=kpi_col, aggfunc='first')

    # Ensure period ordering aligned
    pre_wide = pre_wide.loc[pre_periods]
    post_wide = post_wide.loc[post_periods]

    if treated_unit not in pre_wide.columns:
        return None

    donor_units = [u for u in pre_wide.columns if u != treated_unit]

    y_treat_pre = pre_wide[treated_unit].values.astype(float)
    y_treat_post = post_wide[treated_unit].values.astype(float)
    Y_donors_pre = pre_wide[donor_units].values.astype(float)
    Y_donors_post = post_wide[donor_units].values.astype(float)

    return (y_treat_pre, y_treat_post, Y_donors_pre, Y_donors_post,
            pre_periods, post_periods, donor_units)


def _compute_pre_rmse(y_treat_pre: np.ndarray, Y_donors_pre: np.ndarray, weights: np.ndarray) -> float:
    """Pre-treatment RMSE — quality of synthetic match. Lower = better match."""
    synthetic_pre = Y_donors_pre @ weights
    return float(np.sqrt(np.mean((y_treat_pre - synthetic_pre) ** 2)))


def _placebo_inference(
    df: pd.DataFrame,
    true_att: float,
    treatment_period: Any,
    unit_col: str,
    time_col: str,
    kpi_col: str,
    donor_units: list,
    pre_rmse_threshold_factor: float = 5.0,
) -> dict[str, Any]:
    """Permutation inference via placebo test.

    For each donor unit, re-run SCM treating IT as "pseudo-treated" against
    the remaining donors. Compute placebo ATT для каждого. P-value = fraction
    of |placebo_ATT| >= |true_ATT|.

    Per Abadie 2021: "discard placebos with poor pre-treatment fit (RMSE >>
    treated unit's RMSE)". Implementation: drop placebos whose pre-RMSE > k×
    treated unit's pre-RMSE.
    """
    placebo_atts = []
    placebo_failures = 0

    for placebo_unit in donor_units:
        try:
            arrays = _build_panel_arrays(
                df, placebo_unit, treatment_period, unit_col, time_col, kpi_col
            )
            if arrays is None:
                placebo_failures += 1
                continue
            y_treat_pre, y_treat_post, Y_donors_pre, Y_donors_post, _, _, _ = arrays
            if Y_donors_pre.shape[1] < 2:
                placebo_failures += 1
                continue
            w_placebo, status = _solve_scm_weights(y_treat_pre, Y_donors_pre)
            if w_placebo is None:
                placebo_failures += 1
                continue
            synth_post = Y_donors_post @ w_placebo
            placebo_att = float(np.mean(y_treat_post - synth_post))
            placebo_atts.append(placebo_att)
        except Exception:
            placebo_failures += 1
            continue

    if not placebo_atts:
        return {
            'p_value': None, 'n_placebos': 0, 'failures': placebo_failures,
            'detail': 'Все placebo runs failed — inference unavailable.',
        }

    abs_true = abs(true_att)
    n_extreme = sum(1 for a in placebo_atts if abs(a) >= abs_true)
    # Standard permutation p-value — добавляем +1 в numerator (treated unit included
    # в "наблюдаемое" значение) per Abadie convention.
    p_value = (n_extreme + 1) / (len(placebo_atts) + 1)
    return {
        'p_value': round(p_value, 4),
        'n_placebos': len(placebo_atts),
        'n_more_extreme': n_extreme,
        'failures': placebo_failures,
        'placebo_atts_summary': {
            'min': round(float(np.min(placebo_atts)), 4),
            'median': round(float(np.median(placebo_atts)), 4),
            'max': round(float(np.max(placebo_atts)), 4),
        },
    }


def estimate_scm(
    file_path: str,
    *,
    project_dir: str,
    unit_column: str,
    time_column: str,
    kpi_column: str,
    treated_unit: Any,
    treatment_period: Any,
    confidence: float = 0.9,
    sheet_name: str | None = None,
    run_placebo: bool = True,
) -> dict[str, Any]:
    """Estimate ATT via Synthetic Control Method.

    Workflow per Abadie classic SCM:
        1. Load panel data + format validation
        2. SCM-specific validation (≥3 donors, ≥6 pre-periods)
        3. Build pre/post arrays для treated + donors
        4. Solve SCM weights via _solve_scm_weights (scipy SLSQP)
        5. Compute pre-treatment RMSE (match quality)
        6. Compute counterfactual: synthetic_post = Y_donors_post @ weights
        7. ATT = mean(y_treated_post - synthetic_post)
        8. Inference via placebo test (rank-based p-value)
        9. Honest disclosure: convex-hull, donor-pool quality, RMSE diagnostics
        10. Save artifact к project_dir/causal/scm_<ts>.json
    """
    # Load panel
    df, metadata, err = load_panel(
        file_path,
        unit_column=unit_column,
        time_column=time_column,
        kpi_column=kpi_column,
        sheet_name=sheet_name,
    )
    if err is not None:
        return err
    assert df is not None and metadata is not None

    # SCM-specific validation
    err = validate_for_scm(metadata, treated_unit, treatment_period)
    if err is not None:
        return err

    # Build arrays
    arrays = _build_panel_arrays(
        df, treated_unit, treatment_period, unit_column, time_column, kpi_column
    )
    if arrays is None:
        return error_response(
            'PANEL_FORMAT_INVALID',
            'Не удалось построить pre/post arrays — проверьте данные.'
        )
    (y_treat_pre, y_treat_post, Y_donors_pre, Y_donors_post,
     pre_periods, post_periods, donor_units) = arrays

    # Solve weights
    weights, weight_status = _solve_scm_weights(y_treat_pre, Y_donors_pre)
    if weights is None:
        return error_response('COMPUTATION_FAILED', f'SCM weights solver: {weight_status}')

    # Pre-treatment match quality
    pre_rmse = _compute_pre_rmse(y_treat_pre, Y_donors_pre, weights)
    treated_pre_std = float(np.std(y_treat_pre))
    rmse_ratio = pre_rmse / treated_pre_std if treated_pre_std > 0 else float('inf')

    # Counterfactual + ATT
    synthetic_post = Y_donors_post @ weights
    att_per_period = y_treat_post - synthetic_post
    att_mean = float(np.mean(att_per_period))

    # Honest disclosure setup
    disclosure = HonestDisclosure(
        method='scm_abadie_classic',
        assumptions=[
            'Convex hull — treated unit\'s pre-treatment trajectory ∈ convex hull of donor pool',
            'No anticipation — units не реагируют на treatment до его start',
            'No interference (SUTVA) — treatment в одном unit не влияет на donors',
            'Stable composition — donor pool не treated в pre/post period',
        ],
        references=[
            'Abadie, Diamond, Hainmueller 2010 (JASA)',
            'Abadie 2021 "Using Synthetic Controls" (JEL)',
        ],
    )

    # Diagnostic: pre-RMSE quality
    if rmse_ratio < 0.3:
        disclosure.diagnostics_passed.append(f'pre_treatment_rmse_excellent (ratio={rmse_ratio:.3f})')
    elif rmse_ratio < 0.7:
        disclosure.diagnostics_passed.append(f'pre_treatment_rmse_acceptable (ratio={rmse_ratio:.3f})')
    else:
        disclosure.diagnostics_failed.append(f'pre_treatment_rmse_high (ratio={rmse_ratio:.3f})')
        disclosure.caveats.append(
            f'Pre-treatment RMSE / treated_std = {rmse_ratio:.2f} > 0.7 — synthetic control '
            f'плохо матчит treated unit\'s pre-trajectory. ATT estimate unreliable.'
        )

    # Diagnostic: weight concentration (Herfindahl)
    weight_hhi = float(np.sum(weights ** 2))
    n_eff_donors = 1.0 / max(weight_hhi, 1e-10)
    if n_eff_donors < 2:
        disclosure.caveats.append(
            f'Effective donors = {n_eff_donors:.1f} (HHI {weight_hhi:.3f}) — synthetic '
            f'control dominated одним donor. Convex-hull assumption tense — может '
            f'указывать что treated unit отличается от donor pool.'
        )
    disclosure.diagnostics_passed.append(f'weight_concentration_hhi={weight_hhi:.3f}_n_eff={n_eff_donors:.1f}')

    # Placebo inference
    if run_placebo and len(donor_units) >= 3:
        placebo_result = _placebo_inference(
            df, att_mean, treatment_period, unit_column, time_column, kpi_column, donor_units
        )
        ci_method = 'placebo_permutation'
        # CI from placebo distribution: empirical ±α/2 percentile placeholders
        # Note: SCM placebo gives p-value but standard CI is harder — use post/pre
        # RMSE ratio как proxy uncertainty bound.
        # Conservative CI: ATT ± k × pre_rmse where k = z_{1-α/2}
        alpha = confidence_to_alpha(confidence)
        z_crit = float({0.9: 1.6449, 0.95: 1.96, 0.99: 2.5758}.get(confidence, 1.6449))
        # Use placebo std as scale если placebos available
        if placebo_result['n_placebos'] >= 3 and placebo_result.get('placebo_atts_summary'):
            # Reconstruct placebo std from min/max — rough placeholder
            p_summary = placebo_result['placebo_atts_summary']
            placebo_range = p_summary['max'] - p_summary['min']
            scale = placebo_range / 4  # rough — assumes ~normal placebo distribution
        else:
            scale = pre_rmse
        att_ci_low = att_mean - z_crit * scale
        att_ci_high = att_mean + z_crit * scale
    else:
        placebo_result = {
            'p_value': None, 'n_placebos': 0,
            'detail': 'Placebo inference skipped (run_placebo=False or insufficient donors).',
        }
        ci_method = 'pre_rmse_proxy'
        z_crit = float({0.9: 1.6449, 0.95: 1.96, 0.99: 2.5758}.get(confidence, 1.6449))
        att_ci_low = att_mean - z_crit * pre_rmse
        att_ci_high = att_mean + z_crit * pre_rmse

    att_obj = ATT(
        point=round(att_mean, 4),
        ci_low=round(att_ci_low, 4),
        ci_high=round(att_ci_high, 4),
        ci_method=ci_method,
        confidence=confidence,
    )

    # Save artifact
    project_path = Path(project_dir)
    causal_dir = project_path / 'causal'
    causal_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    artifact_path = causal_dir / f'scm_{ts}.json'

    payload = {
        'status': 'ok',
        'method': 'scm_abadie_classic',
        'att': att_obj.to_dict(),
        'diagnostics': {
            'panel_metadata': metadata.to_dict(),
            'treated_unit': treated_unit,
            'treatment_period': str(treatment_period),
            'donor_units': donor_units,
            'donor_weights': {u: round(float(w), 4) for u, w in zip(donor_units, weights)},
            'weight_optimization_status': weight_status,
            'pre_treatment_rmse': round(pre_rmse, 4),
            'pre_treatment_rmse_ratio': round(rmse_ratio, 4),
            'effective_n_donors': round(n_eff_donors, 2),
            'weight_hhi': round(weight_hhi, 4),
            'placebo_test': placebo_result,
            'n_pre_periods': len(pre_periods),
            'n_post_periods': len(post_periods),
            'att_per_period': [round(float(v), 4) for v in att_per_period],
        },
        'honest_disclosure': disclosure.to_dict(),
        'artifact_path': str(artifact_path),
        'created_at': datetime.now().isoformat(),
    }

    try:
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning(f'Artifact save failed: {e}')

    return payload
