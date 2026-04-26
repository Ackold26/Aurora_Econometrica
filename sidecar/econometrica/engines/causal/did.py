"""
Difference-in-Differences (DiD) engine — Sprint 3 M1.

Implements TWFE (two-way fixed effects) DiD via linearmodels.PanelOLS.
For non-staggered (single treatment date) experiments — classic 2x2 design
common в pharma marketing geo-holdout tests.

⚠️ TWFE caveat: для STAGGERED adoption (regions onboard at different dates),
TWFE produces biased ATT estimate per Goodman-Bacon 2021 ("Difference-in-
Differences with variation in treatment timing", Journal of Econometrics).
Callaway-Santanna 2021 estimator deferred к Sprint 4+ для proper staggered
support. Current М1 implementation flags staggered designs via
HonestDisclosure.diagnostics_failed.

References:
- Wooldridge 2010 "Econometric Analysis of Cross Section and Panel Data"
- Callaway, Sant'Anna 2021 "Difference-in-Differences with Multiple Time Periods"
- Goodman-Bacon 2021 "Difference-in-Differences with variation in treatment timing"
- Roth, Sant'Anna, Bilinski, Poe 2023 "What's Trending in Difference-in-Differences"
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
from ._panel_data import load_panel, validate_for_did, PanelMetadata

logger = logging.getLogger(__name__)


def _detect_staggered(df: pd.DataFrame, unit_col: str, time_col: str, treat_col: str) -> bool:
    """True если treated units получают treatment в DIFFERENT periods.

    Goodman-Bacon 2021: TWFE biased для staggered adoption. Detection allows
    HonestDisclosure to flag this caveat upfront.
    """
    treated_first_periods = (
        df[df[treat_col] > 0]
        .groupby(unit_col)[time_col]
        .min()
    )
    return treated_first_periods.nunique() > 1


def _parallel_trends_test(
    df: pd.DataFrame,
    unit_col: str,
    time_col: str,
    kpi_col: str,
    treat_col: str,
    treated_units: list,
) -> dict[str, Any]:
    """Pre-treatment parallel-trends sanity check.

    Method: regress kpi на time × treated_indicator interaction в
    pre-treatment data only. Significant interaction = parallel-trends
    violation.

    Returns:
        {'passed': bool, 'p_value': float, 'detail': str}
    """
    # Find earliest treatment period
    treated_mask = df[treat_col] > 0
    if not treated_mask.any():
        return {'passed': False, 'p_value': None, 'detail': 'Нет treated observations'}
    treatment_start = df.loc[treated_mask, time_col].min()

    pre_df = df[df[time_col] < treatment_start].copy()
    if len(pre_df) < 6:
        return {'passed': False, 'p_value': None, 'detail': f'Недостаточно pre-periods ({len(pre_df)})'}

    # Build is_treated_unit indicator (time-invariant)
    pre_df['_is_treated_unit'] = pre_df[unit_col].isin(treated_units).astype(int)

    # Encode time as numeric (period rank within sorted order)
    period_to_idx = {p: i for i, p in enumerate(sorted(pre_df[time_col].unique()))}
    pre_df['_t_num'] = pre_df[time_col].map(period_to_idx)
    pre_df['_t_x_treated'] = pre_df['_t_num'] * pre_df['_is_treated_unit']

    # OLS: kpi ~ t_num + is_treated_unit + t_num*is_treated_unit
    try:
        from statsmodels.regression.linear_model import OLS
        from statsmodels.tools import add_constant
        X = add_constant(pre_df[['_t_num', '_is_treated_unit', '_t_x_treated']])
        y = pre_df[kpi_col]
        model = OLS(y, X).fit()
        interaction_p = float(model.pvalues['_t_x_treated'])
        # If interaction p < 0.05 → trends differ significantly = violation
        passed = interaction_p > 0.05
        return {
            'passed': passed,
            'p_value': round(interaction_p, 4),
            'detail': (f'p-value interaction t × treated_unit = {interaction_p:.4f}. '
                       f'{"OK" if passed else "ВНИМАНИЕ: trends differ"} (threshold p>0.05)'),
        }
    except Exception as e:
        return {'passed': False, 'p_value': None, 'detail': f'Test failed: {type(e).__name__}: {e}'}


def estimate_did(
    file_path: str,
    *,
    project_dir: str,
    unit_column: str,
    time_column: str,
    kpi_column: str,
    treatment_column: str,
    control_columns: list[str] | None = None,
    confidence: float = 0.9,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """Estimate ATT via TWFE DiD.

    Workflow:
        1. Load panel data + format validation
        2. DiD-specific validation (≥4 units, ≥4 periods, treatment present)
        3. Build TWFE design: kpi ~ treated_dummy × post_dummy + entity_FE + time_FE
        4. Fit linearmodels.PanelOLS
        5. Extract ATT = coef on (treated × post) interaction
        6. Compute CI using cluster-robust SE
        7. Run honest_disclosure diagnostics (staggered? parallel-trends? overlap?)
        8. Save artifact к project_dir/causal/did_<ts>.json
        9. Return ATT + diagnostics

    Per ADR §4.3, response shape uniform across causal endpoints.
    """
    # Step 1: Load + validate format
    df, metadata, err = load_panel(
        file_path,
        unit_column=unit_column,
        time_column=time_column,
        kpi_column=kpi_column,
        treatment_column=treatment_column,
        sheet_name=sheet_name,
    )
    if err is not None:
        return err
    assert df is not None and metadata is not None

    # Step 2: DiD-specific validation
    err = validate_for_did(metadata)
    if err is not None:
        return err

    # Step 3: Honest disclosure diagnostics (run early — surface caveats upfront)
    disclosure = HonestDisclosure(
        method='did_twfe',
        assumptions=[
            'Parallel trends — pre-treatment KPI trajectories треш и control units parallel',
            'No anticipation — units не реагируют на treatment до его old start',
            'SUTVA — treatment в одном unit не влияет на others (no spillover)',
            'Common shocks — time fixed effects capture period-level shocks',
        ],
        references=[
            'Wooldridge 2010 "Econometric Analysis of Cross Section and Panel Data"',
            'Goodman-Bacon 2021 (для staggered adoption caveat)',
        ],
    )

    # Detection 1: Staggered adoption
    is_staggered = _detect_staggered(df, unit_column, time_column, treatment_column)
    if is_staggered:
        disclosure.caveats.append(
            'STAGGERED adoption detected — units get treatment at DIFFERENT periods. '
            'TWFE produces biased ATT под staggered (Goodman-Bacon 2021). Использовать '
            'Callaway-Santanna estimator (deferred к Sprint 4+) для proper staggered. '
            'Текущий ATT — TWFE approximation, treat с caution.'
        )
        disclosure.diagnostics_failed.append('staggered_adoption_twfe_biased')
    else:
        disclosure.diagnostics_passed.append('non_staggered_2x2_design')

    # Detection 2: Parallel trends test
    pt_test = _parallel_trends_test(
        df, unit_column, time_column, kpi_column, treatment_column, metadata.treated_units or []
    )
    if pt_test['passed']:
        disclosure.diagnostics_passed.append(f'parallel_trends_test (p={pt_test["p_value"]})')
    else:
        disclosure.diagnostics_failed.append(f'parallel_trends_test (p={pt_test["p_value"]})')
        disclosure.caveats.append(f'Parallel-trends test: {pt_test["detail"]}')

    # Step 4: Build TWFE design
    # Generate "post" indicator: 1 if period >= treatment_start AND unit is treated
    # Standard TWFE DiD: y = α + β·D + γ·entity_FE + δ·time_FE + ε
    # where D = treated_unit × post indicator (already в treatment_column if user encoded correctly)
    work_df = df.copy()

    # If treatment_column already encodes "currently treated" (D = 1 when post AND treated):
    # use directly. Otherwise need to construct from is_treated_unit × is_post_period.
    # We assume USER provides treatment_column properly (= 1 only when treated AND post).
    # This matches conventional panel data convention.

    # Set MultiIndex для PanelOLS
    try:
        from linearmodels.panel import PanelOLS
        # PanelOLS expects MultiIndex (entity, time)
        work_df = work_df.set_index([unit_column, time_column])

        exog_vars = [treatment_column]
        if control_columns:
            for c in control_columns:
                if c in work_df.columns:
                    exog_vars.append(c)

        y = work_df[kpi_column]
        X = work_df[exog_vars]

        model = PanelOLS(y, X, entity_effects=True, time_effects=True, drop_absorbed=True)
        results = model.fit(cov_type='clustered', cluster_entity=True)

        # ATT = coefficient on treatment_column
        att_coef = float(results.params[treatment_column])
        att_se = float(results.std_errors[treatment_column])
        att_pvalue = float(results.pvalues[treatment_column])

    except Exception as e:
        logger.exception(f'PanelOLS fit failed: {e}')
        return error_response('COMPUTATION_FAILED', f'PanelOLS: {type(e).__name__}: {e}')

    # Step 5: Compute CI using normal approximation (large-N panel)
    # ATT ± z_{α/2} · SE
    alpha = confidence_to_alpha(confidence)
    z_crit = float({0.9: 1.6449, 0.95: 1.96, 0.99: 2.5758}.get(confidence, 1.6449))
    att_ci_low = att_coef - z_crit * att_se
    att_ci_high = att_coef + z_crit * att_se

    att_obj = ATT(
        point=round(att_coef, 4),
        ci_low=round(att_ci_low, 4),
        ci_high=round(att_ci_high, 4),
        ci_method='frequentist_se_clustered',
        confidence=confidence,
    )

    # Step 6: Save artifact
    project_path = Path(project_dir)
    causal_dir = project_path / 'causal'
    causal_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    artifact_path = causal_dir / f'did_{ts}.json'

    payload = {
        'status': 'ok',
        'method': 'did_twfe',
        'att': att_obj.to_dict(),
        'diagnostics': {
            'panel_metadata': metadata.to_dict(),
            'parallel_trends_test': pt_test,
            'is_staggered': is_staggered,
            'p_value': round(att_pvalue, 4),
            'r_squared': round(float(results.rsquared), 4),
            'n_observations': int(results.nobs),
            'n_entities': metadata.n_units,
            'n_periods': metadata.n_periods,
            'cluster_se_by': 'entity',
        },
        'honest_disclosure': disclosure.to_dict(),
        'artifact_path': str(artifact_path),
        'created_at': datetime.now().isoformat(),
    }

    try:
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'Artifact save failed: {e}')
        # Continue without persistence — payload still returns to caller

    return payload
