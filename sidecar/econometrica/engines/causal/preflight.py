"""
Causal preflight + list + cross-method consistency — Sprint 3 M4.

Unified pre-flight validation across DiD/SCM/Forest. Analogous к existing
/compute/preflight для MMM training. Returns:
- which causal methods applicable to given data
- panel-data quality breakdown
- recommended method based on data structure
- aggregated honest_disclosure (caveats common across methods)

list_causal_artifacts() — directory listing of causal/*.json для UI history view.

cross_method_consistency() — when DiD + SCM both run on same project, compare
ATT values + CI overlap. Flags concerning divergence (different methods give
different answer → identification problem).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .common import HonestDisclosure, error_response
from ._panel_data import load_panel, validate_for_did, validate_for_scm

logger = logging.getLogger(__name__)


def causal_preflight(
    file_path: str,
    *,
    unit_column: str,
    time_column: str,
    kpi_column: str,
    treatment_column: str | None = None,
    treated_unit: Any = None,
    treatment_period: Any = None,
    feature_columns: list[str] | None = None,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """Validate panel data + recommend applicable causal methods.

    Workflow:
        1. Load panel + format validation (basic)
        2. Per-method validation (DiD, SCM, Forest)
        3. Aggregate findings → recommended_methods list
        4. Common caveats аcross methods (exchangeability, SUTVA)
        5. Method-specific applicability flags

    Returns:
        {
          'status': 'ok'|'error',
          'overall_tier': 'reliable'|'directional'|'insufficient',
          'panel_metadata': {...},
          'methods_applicable': {'did': bool, 'scm': bool, 'forest': bool},
          'method_validation': {'did': {...}, 'scm': {...}, 'forest': {...}},
          'recommended_methods': ['did', 'scm'],  # priority order
          'common_caveats': [...],
          'recommendation': 'human-readable text'
        }
    """
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

    # Per-method validation
    method_validation: dict[str, dict[str, Any]] = {}

    # DiD validation
    if treatment_column:
        did_err = validate_for_did(metadata)
        if did_err:
            method_validation['did'] = {
                'applicable': False, 'reason': did_err.get('message', 'unknown'),
            }
        else:
            method_validation['did'] = {
                'applicable': True, 'reason': 'panel format OK',
                'n_treated_units': len(metadata.treated_units or []),
                'n_control_units': metadata.n_units - len(metadata.treated_units or []),
            }
    else:
        method_validation['did'] = {
            'applicable': False, 'reason': 'treatment_column не указан',
        }

    # SCM validation (требует treated_unit + treatment_period)
    if treated_unit is not None and treatment_period is not None:
        scm_err = validate_for_scm(metadata, treated_unit, treatment_period)
        if scm_err:
            method_validation['scm'] = {
                'applicable': False, 'reason': scm_err.get('message', 'unknown'),
            }
        else:
            pre_periods = [p for p in metadata.periods_list if p < treatment_period]
            method_validation['scm'] = {
                'applicable': True, 'reason': 'SCM setup OK',
                'n_pre_periods': len(pre_periods),
                'n_donors': metadata.n_units - 1,
            }
    else:
        method_validation['scm'] = {
            'applicable': False,
            'reason': 'treated_unit или treatment_period не указан (нужно оба)',
        }

    # Causal Forest validation (требует feature_columns + n>=100)
    if feature_columns and treatment_column:
        if metadata.n_obs < 100:
            method_validation['forest'] = {
                'applicable': False,
                'reason': f'Causal Forest требует n≥100 obs, got {metadata.n_obs}',
            }
        else:
            missing_feat = [f for f in feature_columns if f not in df.columns]
            if missing_feat:
                method_validation['forest'] = {
                    'applicable': False,
                    'reason': f'Feature columns missing: {missing_feat}',
                }
            else:
                method_validation['forest'] = {
                    'applicable': True, 'reason': 'features + n>=100 OK',
                    'n_features': len(feature_columns),
                }
    else:
        method_validation['forest'] = {
            'applicable': False,
            'reason': 'feature_columns или treatment_column не указан',
        }

    # Aggregate
    methods_applicable = {m: v['applicable'] for m, v in method_validation.items()}
    recommended_methods = [m for m, ok in methods_applicable.items() if ok]

    # Determine overall tier
    n_applicable = sum(methods_applicable.values())
    if n_applicable >= 2:
        overall_tier = 'reliable'  # multiple methods → triangulation possible
    elif n_applicable == 1:
        overall_tier = 'directional'  # single method → no cross-validation
    else:
        overall_tier = 'insufficient'

    # Common caveats across methods
    common_caveats = [
        'SUTVA — treatment в одном unit не влияет на others. Marketing campaigns '
        'могут иметь spillover (regional advertising, word-of-mouth) — может нарушать.',
        'Exchangeability в time-series ослаблена (trend, seasonality). Vanilla causal '
        'inference assumes stationary residuals — for non-stationary, weighted variants '
        'preferred (Sprint 4+ enhancement).',
    ]

    # Recommendation text
    if overall_tier == 'reliable':
        rec_text = (
            f'Применимы {n_applicable} causal-методов: {", ".join(recommended_methods)}. '
            f'Рекомендуется запустить все три и сравнить ATT (cross-method consistency). '
            f'Расхождение оценок > 50% указывает на identification issue.'
        )
    elif overall_tier == 'directional':
        rec_text = (
            f'Применим только {recommended_methods[0]}. Cross-method validation недоступна '
            f'— ATT estimate directional only. Рекомендуется собрать данные для второго '
            f'метода (geo-disaggregation для DiD/SCM, more features для Forest).'
        )
    else:
        rec_text = (
            'Ни один causal method не применим к данным. Проверьте: panel format (long), '
            'наличие treatment_column, n≥100 для Forest, geo-disaggregation для DiD/SCM.'
        )

    return {
        'status': 'ok',
        'overall_tier': overall_tier,
        'panel_metadata': metadata.to_dict(),
        'methods_applicable': methods_applicable,
        'method_validation': method_validation,
        'recommended_methods': recommended_methods,
        'common_caveats': common_caveats,
        'recommendation': rec_text,
    }


def list_causal_artifacts(project_dir: str) -> dict[str, Any]:
    """List all causal_<method>_<ts>.json artifacts в project_dir/causal/.

    Returns:
        {
          'status': 'ok',
          'project_dir': '...',
          'count': int,
          'artifacts': [{
            'path': '...',
            'method': 'did_twfe' | 'scm_abadie_classic' | 'forest_wager_athey',
            'created_at': iso timestamp,
            'att_point': float,
            'att_ci_low': float,
            'att_ci_high': float,
            'ci_method': str,
          }]
        }
    """
    causal_dir = Path(project_dir) / 'causal'
    if not causal_dir.exists():
        return {'status': 'ok', 'project_dir': project_dir, 'count': 0, 'artifacts': []}

    artifacts = []
    for f in sorted(causal_dir.glob('*.json')):
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                payload = json.load(fp)
            att = payload.get('att', {})
            artifacts.append({
                'path': str(f),
                'filename': f.name,
                'method': payload.get('method', 'unknown'),
                'created_at': payload.get('created_at', ''),
                'att_point': att.get('point'),
                'att_ci_low': att.get('ci_low'),
                'att_ci_high': att.get('ci_high'),
                'ci_method': att.get('ci_method'),
            })
        except Exception as e:
            logger.warning(f'Failed to read artifact {f}: {e}')
            continue

    # Sort by created_at descending
    artifacts.sort(key=lambda a: a.get('created_at', ''), reverse=True)

    return {
        'status': 'ok',
        'project_dir': project_dir,
        'count': len(artifacts),
        'artifacts': artifacts,
    }


def cross_method_consistency(project_dir: str) -> dict[str, Any]:
    """Compare ATT estimates across DiD/SCM/Forest для same project.

    Triangulation: when multiple methods estimate ATT on same data, they
    should agree (within CI overlap). Substantial disagreement signals
    identification problem (assumption violation, model misspecification).

    Returns:
        {
          'status': 'ok',
          'methods_compared': ['did_twfe', 'scm_abadie_classic'],
          'att_values': {'did_twfe': {...}, ...},
          'ci_overlap': {'did_vs_scm': True/False, ...},
          'max_relative_divergence': 0.42,
          'consistency_verdict': 'agree' | 'disagree' | 'partial',
          'recommendation': 'human-readable'
        }
    """
    listing = list_causal_artifacts(project_dir)
    if listing['count'] < 2:
        return {
            'status': 'ok',
            'consistency_verdict': 'insufficient_data',
            'recommendation': f'Только {listing["count"]} causal artifact(s) в project. '
                              f'Cross-method consistency требует ≥2 разных методов.',
            'methods_compared': [],
            'att_values': {},
            'ci_overlap': {},
        }

    # Get latest artifact per method
    latest_by_method: dict[str, dict] = {}
    for a in listing['artifacts']:
        method = a.get('method', 'unknown')
        if method not in latest_by_method:
            latest_by_method[method] = a

    if len(latest_by_method) < 2:
        return {
            'status': 'ok',
            'consistency_verdict': 'insufficient_methods',
            'recommendation': 'Cross-method consistency требует ≥2 разных методов. '
                              f'В project только {len(latest_by_method)} метод(ов): '
                              f'{list(latest_by_method.keys())}.',
            'methods_compared': list(latest_by_method.keys()),
            'att_values': {m: {'point': a['att_point'], 'ci_low': a['att_ci_low'], 'ci_high': a['att_ci_high']}
                            for m, a in latest_by_method.items()},
            'ci_overlap': {},
        }

    methods = sorted(latest_by_method.keys())
    att_values = {
        m: {
            'point': latest_by_method[m]['att_point'],
            'ci_low': latest_by_method[m]['att_ci_low'],
            'ci_high': latest_by_method[m]['att_ci_high'],
            'ci_method': latest_by_method[m]['ci_method'],
        }
        for m in methods
    }

    # Pairwise CI overlap
    # B9 audit fix (audit-of-Sprint3 2026-04-27): skip pair when CI is None
    # (instead of false-flag overlap=False which biased verdict toward 'disagree'
    # for any CI-missing pair). Now: incomplete pairs marked 'skipped' и не
    # counted в n_pairs/n_overlap denominators.
    ci_overlap: dict[str, bool | str] = {}
    relative_divergences = []
    n_overlap = 0
    n_pairs_with_ci = 0
    for i in range(len(methods)):
        for j in range(i + 1, len(methods)):
            m1, m2 = methods[i], methods[j]
            a1, a2 = att_values[m1], att_values[m2]
            pair_key = f'{m1}_vs_{m2}'
            # Skip pair если CI bounds missing
            if (a1['ci_low'] is None or a1['ci_high'] is None or
                    a2['ci_low'] is None or a2['ci_high'] is None):
                ci_overlap[pair_key] = 'skipped_ci_missing'
                continue
            try:
                overlap = max(a1['ci_low'], a2['ci_low']) <= min(a1['ci_high'], a2['ci_high'])
                ci_overlap[pair_key] = overlap
                n_pairs_with_ci += 1
                if overlap:
                    n_overlap += 1
            except (TypeError, ValueError):
                ci_overlap[pair_key] = 'skipped_invalid_types'
                continue
            try:
                divergence = abs(a1['point'] - a2['point']) / max(abs(a1['point']), abs(a2['point']), 1e-10)
                relative_divergences.append(divergence)
            except (TypeError, ValueError):
                pass

    max_div = max(relative_divergences) if relative_divergences else 0.0

    # Verdict — B9 audit fix: use n_pairs_with_ci (excluding skipped) as denominator
    if n_pairs_with_ci == 0:
        verdict = 'unknown'  # all pairs skipped (insufficient CI data)
    elif n_overlap == n_pairs_with_ci and max_div < 0.30:
        verdict = 'agree'
    elif n_overlap == 0 or max_div > 0.70:
        verdict = 'disagree'
    else:
        verdict = 'partial'

    if verdict == 'agree':
        rec = 'Methods agree (CIs overlap, divergence < 30%). Triangulated estimate надёжен.'
    elif verdict == 'partial':
        rec = (
            'Partial agreement: not all CIs overlap, или divergence 30-70%. '
            'Один из методов может нарушать assumptions — review honest_disclosure.'
        )
    else:
        rec = (
            'Methods disagree (CIs не пересекаются, divergence > 70%). '
            'Identification problem: проверьте assumption violations '
            '(parallel-trends для DiD, convex-hull для SCM, overlap для Forest).'
        )

    return {
        'status': 'ok',
        'consistency_verdict': verdict,
        'methods_compared': methods,
        'att_values': att_values,
        'ci_overlap': ci_overlap,
        'max_relative_divergence': round(max_div, 4),
        'recommendation': rec,
    }
