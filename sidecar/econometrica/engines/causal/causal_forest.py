"""
Causal Forest - Sprint 3 M3.

Heterogeneous Treatment Effects (HTE) via Wager-Athey 2018 honest random
forests. Wraps econml.dml.CausalForestDML - DML (Double Machine Learning)
variant with cross-fitting + honest splits для distribution-free CI на
treatment effects.

Use case: после DiD/SCM established AVERAGE treatment effect, Causal Forest
answers "В каких сегментах эффект сильнее?" - surfaces heterogeneity along
features (regional demographics, market segments, prior brand awareness).

⚠️ Identifiability assumptions (per Wager-Athey 2018):
- Conditional Independence Assumption (CIA / unconfoundedness):
  treatment assignment independent от potential outcomes given features X
- Positivity / Overlap: P(T=1|X) ∈ (ε, 1-ε) for all X в support
- SUTVA: no spillover между units

Reference:
- Wager, Athey 2018 "Estimation and Inference of Heterogeneous Treatment
  Effects using Random Forests" JASA
- Athey, Tibshirani, Wager 2019 "Generalized Random Forests" Annals of Statistics
- Chernozhukov et al. 2018 "Double/debiased machine learning" Econometrics Journal
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
from ._panel_data import load_panel

logger = logging.getLogger(__name__)


def _check_overlap(T: np.ndarray, X: np.ndarray, threshold: float = 0.05) -> dict[str, Any]:
    """Estimate propensity scores P(T=1|X) via logistic regression. Flag overlap violations.

    Threshold: any propensity ∉ [threshold, 1-threshold] indicates positivity violation
    в that region of feature space - HTE there unidentifiable.

    B6 audit fix: cross-validated propensity (5-fold) + StandardScaler. Pre-fix
    fit LogisticRegression on entire X without scaling → overfit propensity scores
    (in-sample fit understates overlap violations for high-dim data) + lbfgs slow
    on unscaled features. Now: honest out-of-sample propensity via cross_val_predict.
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_predict
        if len(np.unique(T)) < 2:
            return {'passed': False, 'detail': 'Treatment имеет только одно значение - overlap не identifiable.'}
        pipe = Pipeline([
            ('scaler', StandardScaler()),
            ('clf', LogisticRegression(max_iter=500, solver='lbfgs')),
        ])
        # B6 fix: cross_val_predict gives honest out-of-sample propensity scores.
        # min(n // 20, 5) folds to avoid stratified-CV issues on small samples.
        n_folds = max(2, min(5, len(T) // 20))
        try:
            propensity = cross_val_predict(pipe, X, T, cv=n_folds, method='predict_proba')[:, 1]
        except Exception:
            # Fallback: in-sample fit (less honest но не crash на degenerate folds)
            pipe.fit(X, T)
            propensity = pipe.predict_proba(X)[:, 1]
        n_violations = int(np.sum((propensity < threshold) | (propensity > 1 - threshold)))
        violation_pct = n_violations / len(propensity)
        return {
            'passed': violation_pct < 0.10,  # <10% violations acceptable
            'propensity_min': round(float(propensity.min()), 4),
            'propensity_max': round(float(propensity.max()), 4),
            'propensity_median': round(float(np.median(propensity)), 4),
            'n_violations': n_violations,
            'violation_pct': round(violation_pct * 100, 2),
            'threshold': threshold,
            'detail': (
                f'Overlap violations {n_violations}/{len(propensity)} ({violation_pct*100:.1f}%). '
                f'{"OK" if violation_pct < 0.10 else "ВНИМАНИЕ"}: propensity range '
                f'[{propensity.min():.3f}, {propensity.max():.3f}].'
            ),
        }
    except Exception as e:
        return {'passed': False, 'detail': f'Overlap check failed: {type(e).__name__}: {e}'}


def estimate_causal_forest(
    file_path: str,
    *,
    project_dir: str,
    kpi_column: str,
    treatment_column: str,
    feature_columns: list[str],
    confounder_columns: list[str] | None = None,
    confidence: float = 0.9,
    n_estimators: int = 200,
    sheet_name: str | None = None,
    random_state: int = 42,
    unit_column: str | None = None,
    time_column: str | None = None,
) -> dict[str, Any]:
    """Estimate ATE + heterogeneous treatment effects via Causal Forest DML.

    Workflow:
        1. Load data + validate features/treatment columns present
        2. Overlap check (logistic propensity score; flag violations)
        3. Fit econml CausalForestDML с honest cross-fitting
        4. Extract ATE (constant marginal effect averaged) с CI
        5. Compute CATE для each observation; surface top/bottom segments
        6. Honest disclosure: CIA, overlap, SUTVA assumptions
        7. Save artifact

    Args:
        kpi_column: outcome variable Y
        treatment_column: binary 0/1 treatment indicator T
        feature_columns: heterogeneity drivers X (features that may modify TE)
        confounder_columns: nuisance variables W (control for confounding,
            не expected to drive HTE)
        unit_column / time_column: optional, для panel context (not used by
            DML internally but stored в metadata)
    """
    # Load - load_panel allows None unit/time for cross-section мode
    if unit_column is None or time_column is None:
        # Load file directly without panel validation
        try:
            path = Path(file_path)
            if not path.exists():
                return error_response('DATA_LOAD_FAILED', f'Файл не найден: {file_path}')
            if path.suffix.lower() in ('.xlsx', '.xls'):
                df = pd.read_excel(file_path, sheet_name=sheet_name) if sheet_name else pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
        except Exception as e:
            return error_response('DATA_LOAD_FAILED', f'{type(e).__name__}: {e}')
    else:
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

    # Validate columns
    required = [kpi_column, treatment_column] + feature_columns
    if confounder_columns:
        required += confounder_columns
    missing = [c for c in required if c not in df.columns]
    if missing:
        return error_response(
            'COLUMNS_MISSING',
            f'Отсутствующие колонки: {missing}. Доступные: {df.columns[:20].tolist()}'
        )

    # n minimum check
    if len(df) < 100:
        return error_response(
            'PANEL_FORMAT_INVALID',
            f'Causal Forest требует n≥100 observations. Got {len(df)}.'
        )

    # Drop rows with NaN in required columns
    df_clean = df[required].dropna()
    if len(df_clean) < 100:
        return error_response(
            'PANEL_FORMAT_INVALID',
            f'После удаления NaN осталось {len(df_clean)} obs (<100).'
        )

    Y = df_clean[kpi_column].values.astype(float)
    T = df_clean[treatment_column].values.astype(float)
    X = df_clean[feature_columns].values.astype(float)
    W = df_clean[confounder_columns].values.astype(float) if confounder_columns else None

    # Overlap check
    overlap_result = _check_overlap(T, X)

    # Honest disclosure setup
    disclosure = HonestDisclosure(
        method='forest_wager_athey',
        assumptions=[
            'Conditional Independence (CIA) - treatment independent от potential outcomes given X',
            'Positivity / Overlap - P(T=1|X) ∈ (0,1) for all X в support',
            'SUTVA - нет spillover между units',
            'Honest splits - sample-splitting между estimation и inference (Wager-Athey 2018)',
        ],
        references=[
            'Wager, Athey 2018 "Estimation and Inference of Heterogeneous Treatment Effects" (JASA)',
            'Athey, Tibshirani, Wager 2019 "Generalized Random Forests" (AoS)',
            'Chernozhukov et al. 2018 "Double/debiased ML" (Econometrics J)',
        ],
    )

    if overlap_result['passed']:
        disclosure.diagnostics_passed.append(
            f'overlap_check (violations {overlap_result["violation_pct"]:.1f}%)'
        )
    else:
        disclosure.diagnostics_failed.append(
            f'overlap_violation ({overlap_result["violation_pct"]:.1f}% propensity на границе)'
        )
        disclosure.caveats.append(overlap_result['detail'])

    # Fit Causal Forest DML
    try:
        from econml.dml import CausalForestDML
        from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier

        cf = CausalForestDML(
            n_estimators=n_estimators,
            random_state=random_state,
            model_y=RandomForestRegressor(n_estimators=100, min_samples_leaf=10, random_state=random_state),
            model_t=RandomForestClassifier(n_estimators=100, min_samples_leaf=10, random_state=random_state),
            discrete_treatment=True,
            cv=2,  # cross-fitting folds
        )

        cf.fit(Y=Y, T=T, X=X, W=W)
        # Average effect
        cate_pred = cf.effect(X)  # per-observation CATE
        ate = float(np.mean(cate_pred))

        # Confidence intervals для ATE
        alpha = confidence_to_alpha(confidence)
        try:
            cate_ci = cf.effect_interval(X, alpha=alpha)
            ate_ci_low = float(np.mean(cate_ci[0]))
            ate_ci_high = float(np.mean(cate_ci[1]))
            ci_method = 'honest_split'
        except Exception as e:
            logger.warning(f'effect_interval failed: {e}, falling back to cate_mean_se proxy')
            # B3 audit fix (audit-of-Sprint3 2026-04-27): RENAME bootstrap →
            # cate_mean_se. Pre-fix code resampled FROM cate_pred (per-obs CATE
            # point estimates) which gives SE of mean of FIXED estimates, NOT
            # bootstrap of estimator. True bootstrap requires refitting Causal
            # Forest on resampled (Y,T,X) - expensive (~minutes per iteration).
            # Honest naming + use simple SE-of-mean which is what's actually
            # computed.
            # Coverage caveat: this CI underestimates uncertainty (ignores
            # estimator variance). Honest_disclosure gets explicit caveat.
            # B8 fix: scipy.stats.norm.ppf для arbitrary confidence values.
            try:
                from scipy.stats import norm as _scipy_norm
                z_crit = float(_scipy_norm.ppf(1.0 - alpha / 2.0))
            except Exception:
                z_crit = float({0.9: 1.6449, 0.95: 1.96, 0.99: 2.5758}.get(confidence, 1.6449))
            ate_se = float(np.std(cate_pred, ddof=1) / np.sqrt(len(cate_pred)))
            ate_ci_low = ate - z_crit * ate_se
            ate_ci_high = ate + z_crit * ate_se
            ci_method = 'cate_mean_se_fallback'
            disclosure.caveats.append(
                'Правдоподобный диапазон посчитан по SE среднего CATE-оценок (cate_mean_se_fallback) - '
                'underestimates true uncertainty because ignores estimator variance. '
                'Используй ATT point estimate как directional, не quantitative.'
            )

    except Exception as e:
        logger.exception(f'Causal Forest fit failed: {e}')
        return error_response('COMPUTATION_FAILED', f'CausalForestDML: {type(e).__name__}: {e}')

    # ATT object
    att_obj = ATT(
        point=round(ate, 4),
        ci_low=round(ate_ci_low, 4),
        ci_high=round(ate_ci_high, 4),
        ci_method=ci_method,
        confidence=confidence,
    )

    # Heterogeneity diagnostics: top/bottom CATE segments
    cate_summary = {
        'mean': round(float(np.mean(cate_pred)), 4),
        'median': round(float(np.median(cate_pred)), 4),
        'std': round(float(np.std(cate_pred)), 4),
        'q10': round(float(np.percentile(cate_pred, 10)), 4),
        'q25': round(float(np.percentile(cate_pred, 25)), 4),
        'q75': round(float(np.percentile(cate_pred, 75)), 4),
        'q90': round(float(np.percentile(cate_pred, 90)), 4),
        'min': round(float(cate_pred.min()), 4),
        'max': round(float(cate_pred.max()), 4),
    }

    heterogeneity_strength = (
        cate_summary['q90'] - cate_summary['q10']
    ) / abs(cate_summary['mean']) if abs(cate_summary['mean']) > 1e-10 else 0.0

    if heterogeneity_strength > 0.5:
        disclosure.diagnostics_passed.append(
            f'meaningful_heterogeneity (q90-q10 / |ate| = {heterogeneity_strength:.2f})'
        )
    else:
        disclosure.caveats.append(
            f'Treatment effect относительно homogeneous (q90-q10 / |ate| = {heterogeneity_strength:.2f}). '
            f'Forest может быть избыточен - ATE достаточно?'
        )

    # Feature importances (если sklearn-style attribute available)
    feature_importance = None
    try:
        # CausalForestDML exposes underlying forests via .feature_importances_
        if hasattr(cf, 'feature_importances_'):
            fi = cf.feature_importances_()
            feature_importance = {
                feature_columns[i]: round(float(fi[i]), 4) for i in range(len(feature_columns))
            }
    except Exception:
        pass

    # Save artifact
    project_path = Path(project_dir)
    causal_dir = project_path / 'causal'
    causal_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    artifact_path = causal_dir / f'forest_{ts}.json'

    payload = {
        'status': 'ok',
        'method': 'forest_wager_athey',
        'att': att_obj.to_dict(),
        'diagnostics': {
            'n_observations': len(df_clean),
            'n_features': len(feature_columns),
            'n_estimators': n_estimators,
            'feature_columns': feature_columns,
            'confounder_columns': confounder_columns or [],
            'overlap_check': overlap_result,
            'cate_summary': cate_summary,
            'heterogeneity_strength': round(heterogeneity_strength, 4),
            'feature_importance': feature_importance,
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
