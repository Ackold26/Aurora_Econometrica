"""
Automatic adstock type selection per channel using BIC.
Fits quick OLS models with geometric vs weibull adstock,
compares Bayesian Information Criterion, returns best per channel.
"""
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any

from utils.adstock import apply_adstock

logger = logging.getLogger('econometrica')


def select_adstock(file_path: str, kpi_column: str, media_columns: list[str],
                   date_column: str | None = None) -> dict[str, Any]:
    """Auto-select best adstock type per media channel using BIC.

    Fits OLS: y ~ intercept + adstock(x) for each channel × each type.
    Returns the type with lower BIC per channel.

    Args:
        file_path: Path to data file (xlsx/csv)
        kpi_column: Target variable column name
        media_columns: List of media channel column names
        date_column: Optional date column (unused, for API consistency)

    Returns:
        {status, selections: {channel: {type, bic_geometric, bic_weibull, confidence}}}
    """
    path = Path(file_path)
    if not path.exists():
        return {'status': 'error', 'message': f'File not found: {file_path}'}

    try:
        if path.suffix in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
    except Exception as e:
        return {'status': 'error', 'message': f'Read error: {e}'}

    if kpi_column not in df.columns:
        return {'status': 'error', 'message': f'KPI column "{kpi_column}" not found'}

    y = df[kpi_column].fillna(0).values.astype(float)
    n = len(y)

    if n < 10:
        return {'status': 'error', 'message': f'Too few observations ({n}) for adstock selection'}

    selections = {}

    for col in media_columns:
        if col not in df.columns:
            selections[col] = {'type': 'geometric', 'reason': 'column not found, using default'}
            continue

        x_raw = df[col].fillna(0).values.astype(float)

        # Skip if all zeros
        if np.sum(np.abs(x_raw)) < 1e-10:
            selections[col] = {'type': 'geometric', 'reason': 'all zeros, using default'}
            continue

        bic_results = {}

        for adstock_type in ['geometric', 'weibull']:
            try:
                x_transformed = apply_adstock(x_raw, adstock_type)

                # OLS: y = a + b * x_transformed
                X = np.column_stack([np.ones(n), x_transformed])
                # Solve via least squares
                beta, residuals, _, _ = np.linalg.lstsq(X, y, rcond=None)

                y_pred = X @ beta
                rss = np.sum((y - y_pred) ** 2)
                k = 2  # intercept + slope

                # BIC = n * ln(RSS/n) + k * ln(n)
                bic = n * np.log(max(rss / n, 1e-10)) + k * np.log(n)
                bic_results[adstock_type] = bic

            except Exception as e:
                logger.warning(f"Adstock selection failed for {col}/{adstock_type}: {e}")
                bic_results[adstock_type] = float('inf')

        # Select type with lower BIC
        geo_bic = bic_results.get('geometric', float('inf'))
        wei_bic = bic_results.get('weibull', float('inf'))

        if wei_bic < geo_bic:
            best = 'weibull'
            diff = geo_bic - wei_bic
        else:
            best = 'geometric'
            diff = wei_bic - geo_bic

        # Confidence: how much better is the winner
        # BIC diff > 10 = very strong, > 6 = strong, > 2 = positive, < 2 = weak
        if diff > 10:
            confidence = 'very_strong'
        elif diff > 6:
            confidence = 'strong'
        elif diff > 2:
            confidence = 'positive'
        else:
            confidence = 'weak'

        selections[col] = {
            'type': best,
            'bic_geometric': round(geo_bic, 2),
            'bic_weibull': round(wei_bic, 2),
            'bic_difference': round(diff, 2),
            'confidence': confidence,
        }

    # Summary
    types_used = [s['type'] for s in selections.values()]
    summary = f"{types_used.count('geometric')} geometric, {types_used.count('weibull')} weibull"

    logger.info(f"Adstock auto-select: {summary}")

    return {
        'status': 'ok',
        'selections': selections,
        'summary': summary,
    }
