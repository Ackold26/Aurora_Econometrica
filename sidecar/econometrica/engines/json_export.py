"""
Aurora Econometrica — Model parameters JSON export (v2.0.0).

Per ADR-019 §6: JSON serialization layer для model params. Allows external
validation / audit / integration tools to read Aurora model in standard format.

Pickle хранится в `engines/persistence.py` (binary, Aurora-specific). JSON export
читает pickle через `load_model_with_compat()` и serializes как human-readable
schema.

Usage:
    from engines.json_export import export_model_params_json

    json_str = export_model_params_json(project_id='kagocel_2024')
    # → human-readable JSON string with всеми key params + diagnostics

Reference:
- docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md §7.2
- docs/v2_0_0_design/PRE_FLIGHT_FIXES.md N13 (cached diagnostics)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def export_model_params_json(
    model_data: Dict[str, Any],
    pretty: bool = True,
) -> str:
    """Export trained model parameters as JSON string.

    Args:
        model_data: loaded model dict (from `load_model_with_compat()` or similar).
        pretty: if True, indent JSON for readability. False = compact.

    Returns:
        JSON string with все key params + diagnostics.

    Schema (v2.0.0):
        {
            "version": "2.0.0",
            "kpi_type": "sales_packs",
            "kpi_kind": "count",
            "analysis_mode": "effectiveness",
            "history": {"length": 36, "grain": "monthly"},
            "channels": {
                "TV": {
                    "beta_mean": 0.41,
                    "beta_std": 0.08,
                    "adstock_decay": 0.65,
                    "adstock_type": "geometric",
                    "hill_alpha": 1.20,
                    "hill_gamma": 0.45,
                    "roi_estimate": 2.31,
                    "roi_ci_90": [1.95, 2.78],
                    "category": "brand"
                }, ...
            },
            "signed_factors": {
                "competitor_trp": {
                    "beta_mean": -0.22,
                    "type": "signed_competitor"
                }, ...
            },
            "controls": {...},
            "holidays_injected": [...],
            "normalization": {...},
            "priors_used": {...},
            "mcmc_diagnostics": {"r_hat_max": 1.02, "ess_min": 1240},
            "backtest_results": {"mape": 8.2, "rmse": 1400, "r2": 0.91},
            "ppc_results": {"r2": 0.91, "durbin_watson": 1.95}
        }
    """
    payload: Dict[str, Any] = {
        'version': model_data.get('model_version', '2.0.0'),
        'kpi_type': model_data.get('kpi_type', 'unknown'),
        'kpi_kind': model_data.get('kpi_kind', 'monetary'),
        'analysis_mode': model_data.get('analysis_mode', 'roi'),  # v2.0.0 new field
    }

    # History metadata
    config = model_data.get('config', {})
    payload['history'] = {
        'length': model_data.get('y_length', 0),
        'grain': config.get('data_grain', 'monthly'),
    }

    # Channel parameters
    channel_params = model_data.get('channel_params', {}) or {}
    channel_categories = model_data.get('channel_categories', {}) or {}
    payload['channels'] = {}
    for ch, params in channel_params.items():
        payload['channels'][ch] = {
            'beta_mean': float(params.get('beta_mean', 0)) if params.get('beta_mean') is not None else None,
            'beta_std': float(params.get('beta_std', 0)) if params.get('beta_std') is not None else None,
            'adstock_decay': float(params.get('adstock_decay', 0.5)) if params.get('adstock_decay') is not None else None,
            'adstock_type': params.get('adstock_type', 'geometric'),
            'hill_alpha': float(params.get('hill_alpha', 1.0)) if params.get('hill_alpha') is not None else None,
            'hill_gamma': float(params.get('hill_gamma', 0.5)) if params.get('hill_gamma') is not None else None,
            'roi_estimate': float(params.get('roi', 0)) if params.get('roi') is not None else None,
            'roi_ci_90': params.get('roi_ci_90'),  # may be None for v1.0/v1.1 pickles
            'category': channel_categories.get(ch, 'unknown'),
        }

    # Signed factors + controls
    norm = model_data.get('normalization', {}) or {}
    control_cols = config.get('control_columns', []) or []
    control_betas_mean = norm.get('control_betas_mean', []) or []

    payload['signed_factors'] = {}
    payload['controls'] = {}
    payload['holidays_injected'] = []

    if len(control_betas_mean) == len(control_cols):
        try:
            from utils.column_detection import classify_column
            for i, col in enumerate(control_cols):
                kind = classify_column(col)
                beta = float(control_betas_mean[i])
                entry = {'beta_mean': beta, 'type': kind}
                if kind in ('signed_competitor', 'signed_price', 'signed_weather', 'signed_macro'):
                    payload['signed_factors'][col] = entry
                elif kind == 'holiday':
                    payload['holidays_injected'].append(col)
                    payload['controls'][col] = entry
                else:
                    payload['controls'][col] = entry
        except Exception as e:
            logger.warning('Signed factor classification failed in JSON export: %s', e)

    # Normalization
    payload['normalization'] = {
        'y_mean': float(norm.get('y_mean', 0)) if norm.get('y_mean') is not None else None,
        'y_std': float(norm.get('y_std', 1)) if norm.get('y_std') is not None else None,
        'media_means': {k: float(v) for k, v in (norm.get('media_means', {}) or {}).items()},
    }

    # Priors used (v2.0.0 NEW — for transparency)
    payload['priors_used'] = model_data.get('priors_summary', {}) or {}

    # MCMC diagnostics
    payload['mcmc_diagnostics'] = model_data.get('mcmc_diagnostics', {})

    # Backtest + PPC (v2.0.0 NEW)
    payload['backtest_results'] = model_data.get('backtest_results', {})
    payload['ppc_results'] = model_data.get('ppc_results', {})

    return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)


def export_model_params_to_file(
    model_data: Dict[str, Any],
    output_path: Path,
    pretty: bool = True,
) -> Path:
    """Write JSON export to file.

    Args:
        model_data: loaded model dict.
        output_path: Path где сохранить JSON.
        pretty: indent JSON.

    Returns:
        Path to written file.
    """
    json_str = export_model_params_json(model_data, pretty=pretty)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_str, encoding='utf-8')
    return output_path
