"""
Data validation engine for MMM.
Reads xlsx/csv, validates structure, computes statistics, detects issues.
Returns JSON for UI display (Traffic Light format).
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any


# Column name patterns for auto-detection
KPI_PATTERNS = ['sales', 'revenue', 'som', 'market_share', 'conversions', 'units', 'volume']
MEDIA_PATTERNS = ['spend', 'budget', 'trp', 'grp', 'impressions', 'clicks', 'views']
DATE_PATTERNS = ['date', 'week', 'month', 'period', 'time']
CONTROL_PATTERNS = ['search', 'queries', 'competitor', 'price', 'distribution', 'promo',
                    'seasonality', 'temperature', 'weather', 'holiday']


def detect_column_role(col_name: str) -> str:
    """Auto-detect column role from name."""
    lower = col_name.lower()
    if any(p in lower for p in DATE_PATTERNS):
        return 'date'
    if any(p in lower for p in KPI_PATTERNS):
        return 'kpi'
    if any(p in lower for p in MEDIA_PATTERNS):
        return 'media'
    if any(p in lower for p in CONTROL_PATTERNS):
        return 'control'
    return 'unknown'


def detect_adstock_type(col_name: str) -> str:
    """Suggest adstock type based on channel name."""
    lower = col_name.lower()
    if any(k in lower for k in ['tv', 'television', 'radio', 'ooh', 'outdoor', 'offline', 'press']):
        return 'weibull'
    return 'geometric'


def validate_data(file_path: str, project_dir: str | None = None) -> dict[str, Any]:
    """Validate dataset for MMM readiness.

    Args:
        file_path: Path to xlsx or csv file
        project_dir: Optional project directory to save results

    Returns:
        JSON-serializable validation result for UI
    """
    path = Path(file_path)
    if not path.exists():
        return {'status': 'error', 'message': f'Файл не найден: {file_path}'}

    # Read data
    try:
        if path.suffix in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        elif path.suffix == '.csv':
            df = pd.read_csv(path)
        else:
            return {'status': 'error', 'message': f'Неподдерживаемый формат: {path.suffix}. Нужен xlsx или csv.'}
    except Exception as e:
        return {'status': 'error', 'message': f'Ошибка чтения файла: {e}'}

    n_rows, n_cols = df.shape
    issues = []
    warnings = []

    # ── Column detection ──
    columns = []
    date_col = None
    kpi_cols = []
    media_cols = []
    control_cols = []

    for col in df.columns:
        role = detect_column_role(col)
        col_info = {
            'name': col,
            'role': role,
            'dtype': str(df[col].dtype),
        }

        if role == 'date':
            date_col = col
        elif role == 'kpi':
            kpi_cols.append(col)
        elif role == 'media':
            media_cols.append(col)
            col_info['adstock_type'] = detect_adstock_type(col)
        elif role == 'control':
            control_cols.append(col)

        # Stats for numeric columns
        if pd.api.types.is_numeric_dtype(df[col]):
            col_series = df[col].fillna(0)
            zeros_pct = round((col_series == 0).sum() / len(col_series) * 100, 1)
            col_info['stats'] = {
                'min': round(float(col_series.min()), 2),
                'max': round(float(col_series.max()), 2),
                'mean': round(float(col_series.mean()), 2),
                'std': round(float(col_series.std()), 2),
                'zeros_pct': zeros_pct,
                'nulls': int(df[col].isna().sum()),
                'cv': round(float(col_series.std() / col_series.mean() * 100), 1) if col_series.mean() != 0 else 0,
            }
            if zeros_pct > 60:
                warnings.append({
                    'column': col,
                    'type': 'high_zeros',
                    'message': f'{col} — {zeros_pct}% нулей. Рекомендуем объединить с другим каналом',
                    'severity': 'warning',
                    'action': 'merge',
                })
            if col_info['stats']['cv'] < 5 and role == 'media':
                warnings.append({
                    'column': col,
                    'type': 'low_variance',
                    'message': f'{col} — вариативность <5%. Канал не информативен для модели',
                    'severity': 'warning',
                    'action': 'exclude',
                })

        columns.append(col_info)

    # ── Structure checks ──
    if not date_col:
        issues.append({
            'type': 'no_date',
            'message': 'Не найден столбец с датами. Переименуйте столбец в "date"',
            'severity': 'critical',
        })

    if not kpi_cols:
        issues.append({
            'type': 'no_kpi',
            'message': 'Не найден KPI-столбец (sales, revenue, som). Укажите вручную',
            'severity': 'critical',
        })

    if not media_cols:
        issues.append({
            'type': 'no_media',
            'message': 'Не найдены медиа-столбцы (spend, trp, impressions). Укажите вручную',
            'severity': 'critical',
        })

    # ── Data volume check ──
    n_predictors = len(media_cols) + len(control_cols)
    ratio = n_rows / max(n_predictors, 1)
    if ratio < 3:
        issues.append({
            'type': 'insufficient_data',
            'message': f'Ratio данных {ratio:.1f}:1 — критически мало (минимум 4:1). Нужно больше наблюдений или меньше переменных',
            'severity': 'critical',
        })
    elif ratio < 4:
        warnings.append({
            'type': 'borderline_data',
            'message': f'Ratio {ratio:.1f}:1 — пограничное (рекомендуем ≥10:1). Модель построится с расширенными доверительными интервалами',
            'severity': 'warning',
        })

    # ── Period check ──
    if date_col and pd.api.types.is_datetime64_any_dtype(df[date_col]):
        pass  # already datetime
    elif date_col:
        try:
            df[date_col] = pd.to_datetime(df[date_col])
        except Exception:
            warnings.append({
                'type': 'date_parse',
                'message': f'Не удалось распознать формат дат в "{date_col}". Убедитесь в формате YYYY-MM-DD',
                'severity': 'warning',
            })

    period_weeks = n_rows  # assume weekly
    if period_weeks < 52:
        warnings.append({
            'type': 'short_period',
            'message': f'{period_weeks} наблюдений — менее 1 года. Рекомендуем ≥52 недели (≥104 для надёжных результатов)',
            'severity': 'warning',
        })

    # ── Correlation matrix (top pairs) ──
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    high_correlations = []
    if len(numeric_cols) >= 2:
        corr_matrix = df[numeric_cols].corr()
        for i, c1 in enumerate(numeric_cols):
            for j, c2 in enumerate(numeric_cols):
                if i < j:
                    r = abs(corr_matrix.loc[c1, c2])
                    if r > 0.8:
                        high_correlations.append({
                            'col1': c1, 'col2': c2,
                            'correlation': round(float(corr_matrix.loc[c1, c2]), 3),
                            'risk': 'Мультиколлинеарность — один из столбцов может быть избыточен',
                        })

    # ── Traffic Light verdict ──
    has_critical = any(i['severity'] == 'critical' for i in issues)
    status = 'error' if has_critical else ('warning' if warnings else 'ok')
    verdict = 'ТРЕБУЕТ ДОРАБОТКИ' if has_critical else (
        'ГОТОВ К МОДЕЛИРОВАНИЮ (с оговорками)' if warnings else 'ГОТОВ К МОДЕЛИРОВАНИЮ'
    )

    result = {
        'status': status,
        'verdict': verdict,
        'file': {
            'name': path.name,
            'rows': n_rows,
            'cols': n_cols,
            'size_kb': round(path.stat().st_size / 1024, 1),
        },
        'columns': columns,
        'detected': {
            'date': date_col,
            'kpi': kpi_cols,
            'media': media_cols,
            'control': control_cols,
            'n_predictors': n_predictors,
            'ratio': round(ratio, 1),
        },
        'issues': issues,
        'warnings': warnings,
        'high_correlations': high_correlations,
    }

    # Save to project dir if provided
    if project_dir:
        out_path = Path(project_dir) / 'results' / 'validation.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result
