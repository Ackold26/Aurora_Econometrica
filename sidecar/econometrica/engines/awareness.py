"""
Awareness forecasting engine.
Models media → awareness relationship + S-curve awareness → sales.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any
from scipy.optimize import curve_fit


def s_curve(x: np.ndarray, L: float, k: float, x0: float) -> np.ndarray:
    """Logistic S-curve: models awareness → sales relationship.

    Args:
        x: Awareness level (0-100%)
        L: Maximum effect (saturation ceiling)
        k: Steepness (how fast effect grows)
        x0: Midpoint (awareness level at 50% of max effect)
    """
    return L / (1 + np.exp(-k * (x - x0)))


def forecast_awareness(config: dict, project_dir: str) -> dict[str, Any]:
    """Forecast awareness based on media spend.

    Args:
        config: {
            'data_file': str,             # xlsx with date, awareness_%, spend columns
            'awareness_column': str,      # Column name for awareness
            'media_columns': list[str],   # Spend columns
            'forecast_periods': int,      # Default 12
        }
    """
    project_path = Path(project_dir)
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (merge_rules могут быть и здесь)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    awareness_col = config.get('awareness_column', 'awareness_%')
    media_cols = config.get('media_columns', [])
    forecast_periods = config.get('forecast_periods', 12)

    if awareness_col not in df.columns:
        return {'status': 'error', 'message': f'Столбец {awareness_col} не найден в данных'}

    awareness = df[awareness_col].ffill().values.astype(float)
    n = len(awareness)

    # Simple linear regression: total media spend → awareness change
    if media_cols:
        total_spend = df[media_cols].fillna(0).sum(axis=1).values.astype(float)
    else:
        total_spend = np.ones(n)

    # Fit decay + impact model
    # awareness[t] = decay * awareness[t-1] + impact * spend[t] + noise
    if n >= 10:
        from sklearn.linear_model import LinearRegression
        X = np.column_stack([awareness[:-1], total_spend[1:]])
        y = awareness[1:]
        reg = LinearRegression().fit(X, y)
        decay = float(reg.coef_[0])
        impact = float(reg.coef_[1])
        intercept = float(reg.intercept_)
        r2 = float(reg.score(X, y))
    else:
        decay = 0.95
        impact = 0.001
        intercept = awareness.mean() * 0.05
        r2 = 0.0

    # Forecast
    forecast = list(awareness)
    avg_spend = total_spend.mean()
    for t in range(forecast_periods):
        next_val = decay * forecast[-1] + impact * avg_spend + intercept
        next_val = max(0, min(100, next_val))
        forecast.append(next_val)

    forecast_values = [round(v, 1) for v in forecast[n:]]
    ci_width = np.std(awareness) * 0.5  # simplified CI

    result = {
        'status': 'ok',
        'model': {
            'decay_rate': round(decay, 4),
            'media_impact': round(impact, 6),
            'r_squared': round(r2, 3),
        },
        'historical': [round(v, 1) for v in awareness.tolist()],
        'forecast': forecast_values,
        'ci_lower': [round(max(0, v - ci_width), 1) for v in forecast_values],
        'ci_upper': [round(min(100, v + ci_width), 1) for v in forecast_values],
        'current_awareness': round(float(awareness[-1]), 1),
        'forecast_end': round(forecast_values[-1], 1) if forecast_values else 0,
        'trend': 'рост' if forecast_values and forecast_values[-1] > awareness[-1] else 'снижение',
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'awareness-forecast.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def awareness_to_sales(config: dict, project_dir: str) -> dict[str, Any]:
    """Model the S-curve relationship between awareness and sales.

    Args:
        config: {
            'data_file': str,
            'awareness_column': str,
            'sales_column': str,
        }
    """
    project_path = Path(project_dir)
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)

    awareness_col = config.get('awareness_column', 'awareness_%')
    sales_col = config.get('sales_column', 'sales')

    if awareness_col not in df.columns or sales_col not in df.columns:
        return {'status': 'error', 'message': f'Нужны столбцы {awareness_col} и {sales_col}'}

    x = df[awareness_col].fillna(0).values.astype(float)
    y = df[sales_col].fillna(0).values.astype(float)

    # Fit S-curve
    try:
        popt, pcov = curve_fit(
            s_curve, x, y,
            p0=[y.max(), 0.1, x.mean()],
            maxfev=5000,
        )
        L, k, x0 = popt
        y_pred = s_curve(x, *popt)
        r2 = 1 - np.sum((y - y_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)

        # Elasticity at current awareness
        current_awareness = float(x[-1])
        dx = 1.0  # +1% awareness
        dy = s_curve(np.array([current_awareness + dx]), *popt)[0] - s_curve(np.array([current_awareness]), *popt)[0]
        elasticity = (dy / s_curve(np.array([current_awareness]), *popt)[0]) / (dx / current_awareness) if current_awareness > 0 else 0

    except Exception:
        L, k, x0 = float(y.max()), 0.1, float(x.mean())
        r2 = 0.0
        elasticity = 0.0

    # Generate curve data for plotting
    x_range = np.linspace(0, min(100, x.max() * 1.5), 100)
    y_range = s_curve(x_range, L, k, x0)

    result = {
        'status': 'ok',
        's_curve': {
            'L': round(float(L), 2),
            'k': round(float(k), 4),
            'x0': round(float(x0), 2),
            'r_squared': round(float(r2), 3),
        },
        'elasticity': round(float(elasticity), 3),
        'threshold': round(float(x0 - 2 / k) if k > 0 else 0, 1),  # Point where curve starts rising
        'saturation': round(float(x0 + 2 / k) if k > 0 else 100, 1),  # Point of diminishing returns
        'current_awareness': round(float(x[-1]), 1),
        'curve_data': {
            'x': x_range.tolist(),
            'y': y_range.tolist(),
            'actual_x': x.tolist(),
            'actual_y': y.tolist(),
        },
        'insight': f"Эластичность awareness→sales = {elasticity:.2f}. "
                   f"{'Awareness выше порога насыщения — наращивание даст убывающий эффект.' if current_awareness > x0 else 'Потенциал роста через awareness ещё не исчерпан.'}",
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'awareness-to-sales.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
