"""
Data validation engine for MMM.
Reads xlsx/csv, validates structure, computes statistics, detects issues.
Returns JSON for UI display (Traffic Light format).
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Column name patterns for auto-detection
KPI_PATTERNS = ['sales', 'revenue', 'market_share', 'conversions', 'units', 'volume',
                'продажи', 'выручка', 'конверси', 'заказ']
MEDIA_PATTERNS = ['spend', 'budget', 'trp', 'grp', 'impressions', 'clicks', 'views',
                  'бюджет', 'расход', 'показ', 'клик', 'визит', 'прочтен', 'просмотр',
                  'impression', 'click', 'visit', 'cpm', 'cpc', 'cpv',
                  'olv', 'banner', 'social', 'retail media', 'performance',
                  'радио', 'пресса', 'digital', 'programmatic',
                  # Out-of-Home: English (OOH, outdoor) + Russian (ООН, наружная)
                  'ooh', 'outdoor', 'оон', 'наружн',
                  # OTS (Opportunity To See) - impression-like metric for OOH/TV
                  'ots',
                  # TV (television) - English + Russian
                  'tv', 'television', 'тв ', 'тв_', 'тв-',
                  'promo', 'промо']
# NOTE v2.0.0: 'price' removed from MEDIA_PATTERNS — moved to CONTROL_PATTERNS
# (signed control factor per ADR-019, may be positive OR negative coefficient).
# 'цен' also moved.
DATE_PATTERNS = ['date', 'week', 'month', 'period', 'time', 'дата', 'неделя', 'месяц']
CONTROL_PATTERNS = ['search', 'queries', 'competitor', 'distribution',
                    'seasonality', 'temperature', 'weather', 'holiday',
                    'som', 'sov', 'sos', 'share_of', 'share of',
                    'конкурент', 'конк.', 'конк ',
                    'сезон', 'дистрибуц', 'погод', 'праздни',
                    'запрос', 'кол-во запрос',
                    # NEW v2.0.0 — signed control factors (ADR-019 §4)
                    'price', 'цен', 'индекс_цен', 'price_index',
                    'avg_price', 'unit_price', 'mean_price',
                    'cpi', 'consumer_price', 'inflation', 'ипц', 'инфляция',
                    'gdp', 'ввп', 'gdp_growth',
                    'fx_rate', 'exchange_rate', 'usd_rub', 'eur_rub',
                    'курс_рубля', 'курс_доллара', 'курс_евро',
                    'rain', 'snow', 'precipitation', 'осадк',
                    'temp', 'температур',
                    'svok',  # ROSST industry: share_of_voice_konkurentov
                    'event',  # additional holiday/event markers
                    ]


def detect_column_role(col_name: str) -> str:
    """Auto-detect column role from name (backward-compatible)."""
    role, _ = detect_column_role_with_confidence(col_name)
    return role


def detect_column_role_with_confidence(col_name: str) -> tuple[str, float]:
    """Auto-detect column role + confidence score (0.0–1.0).

    Returns:
        (role, confidence) where role is 'kpi'|'media'|'control'|'date'|'unknown'
    """
    # Defensive guard (audit H-19). pandas header parsing на merged cells /
    # blank Excel columns может вернуть NaN (float) или None — без guard'a
    # .lower() raises AttributeError → весь /validate endpoint крашится 500.
    if not isinstance(col_name, str):
        return 'unknown', 0.0
    lower = col_name.lower()

    # Date: high confidence for exact names
    date_exact = ['date', 'week', 'month', 'period', 'quarter']
    if lower in date_exact or any(lower.startswith(p) for p in date_exact):
        return 'date', 0.97
    if any(p in lower for p in DATE_PATTERNS):
        return 'date', 0.80

    # Priority override: "конкурент" always → control (even if contains media keywords)
    COMPETITOR_KEYS = ['конкурент', 'конк.', 'конк ', 'competitor']
    if any(k in lower for k in COMPETITOR_KEYS):
        return 'control', 0.90

    # BUG #3 fix (v2.0.1): derived metrics (SOM / SOV / market_share) — это
    # ratio computed from KPI (brand_sales / total_market). Использование как
    # predictor → endogeneity (predictor зависит от outcome). По умолчанию
    # исключаем из модели. Юзер может explicitly включить через Roles UI.
    # Включён trailing space / suffix чтобы не ловить 'svok'/'mosgorsovet'.
    DERIVED_KEYS = [
        'som в', 'som (', 'som_',
        'sov ', 'sov (', 'sov_',
        'share_of_market', 'share of market', 'market_share', 'market share',
        'share_of_voice', 'share of voice',
        'доля_рынка', 'доля рынка', 'доля_голоса', 'доля голоса',
    ]
    if (any(k in lower for k in DERIVED_KEYS)
            or lower in ('som', 'sov')
            or lower.endswith(' som') or lower.endswith(' sov')):
        return 'unused', 0.85

    # Count pattern matches per category
    kpi_matches = sum(1 for p in KPI_PATTERNS if p in lower)
    media_matches = sum(1 for p in MEDIA_PATTERNS if p in lower)
    control_matches = sum(1 for p in CONTROL_PATTERNS if p in lower)

    max_matches = max(kpi_matches, media_matches, control_matches)
    if max_matches == 0:
        return 'unknown', 0.0

    if kpi_matches == max_matches and kpi_matches >= media_matches:
        conf = min(0.55 + kpi_matches * 0.15, 0.95)
        return 'kpi', round(conf, 2)
    if media_matches == max_matches and media_matches >= control_matches:
        conf = min(0.55 + media_matches * 0.15, 0.95)
        return 'media', round(conf, 2)
    conf = min(0.50 + control_matches * 0.15, 0.90)
    return 'control', round(conf, 2)


def validate_role_compatibility(
    unit_costs: dict,
    media_columns: list,
    classifier_fn=None,
) -> tuple[bool, str, str]:
    """Cross-field validation для KPI settings save (Phase 1.2).

    Checks:
      1. Each channel in unit_costs существует в media_columns.
      2. Channel name doesn't match target/control patterns (would indicate
         user accidentally set unit_cost for non-media role).

    Args:
        unit_costs: {channel: ₽_per_unit} from frontend save request
        media_columns: list of column names classified as media in project state
        classifier_fn: optional callable(name) -> kind для unit-test substitution

    Returns:
        (is_valid: bool, error_code: str, message: str)
        error_code в {'OK', 'UNIT_COST_CHANNEL_NOT_MEDIA', 'UNIT_COST_LIKELY_TARGET'}
    """
    if not unit_costs:
        return True, 'OK', ''
    if not isinstance(media_columns, (list, tuple)):
        media_columns = list(media_columns or [])
    media_set = {str(c) for c in media_columns}

    for channel in unit_costs.keys():
        if channel in media_set:
            continue  # OK
        # Channel not in media list → likely user error (e.g., set unit_cost
        # для column которая помечена как target / control).
        # Optional: use classifier_fn для better диагностики
        kind_hint = ''
        if classifier_fn is not None:
            try:
                kind_hint = f' (classified as {classifier_fn(channel)!r})'
            except Exception:  # noqa: BLE001 — defensive против user input
                kind_hint = ''
        return (
            False,
            'UNIT_COST_CHANNEL_NOT_MEDIA',
            f'unit_cost задан для канала {channel!r}, который не в списке media{kind_hint}. '
            f'Удалите запись или измените role канала в шаге «Роли колонок».',
        )
    return True, 'OK', ''


def detect_adstock_type(col_name: str) -> str:
    """Suggest adstock type based on channel name."""
    lower = col_name.lower()
    if any(k in lower for k in ['tv', 'television', 'radio', 'ooh', 'outdoor', 'offline', 'press']):
        return 'weibull'
    return 'geometric'


def detect_date_frequency(series: 'pd.Series') -> str:
    """Detect time series frequency from a date column.

    Returns: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'unknown'
    """
    try:
        dates = pd.to_datetime(series.dropna()).sort_values()
        if len(dates) < 3:
            return 'unknown'
        diffs = dates.diff().dropna().dt.days
        median_diff = float(diffs.median())
        if median_diff <= 1.5:
            return 'daily'
        elif 5 <= median_diff <= 9:
            return 'weekly'
        elif 28 <= median_diff <= 32:
            return 'monthly'
        elif 85 <= median_diff <= 95:
            return 'quarterly'
        return 'unknown'
    except Exception:
        return 'unknown'


def compute_histogram(series: 'pd.Series', bins: int = 10) -> dict:
    """Compute histogram for a numeric series."""
    clean = series.dropna()
    if len(clean) == 0:
        return {'counts': [], 'edges': []}
    counts, edges = np.histogram(clean, bins=bins)
    return {
        'counts': counts.tolist(),
        'edges': [round(float(e), 4) for e in edges],
    }


def data_preview(file_path: str, n_rows: int = 20) -> dict[str, Any]:
    """Read first n_rows of a file and return preview data.

    Args:
        file_path: Path to xlsx or csv file
        n_rows: Number of rows to preview (default 20)

    Returns:
        {status, headers, rows, dtypes, shape}
    """
    path = Path(file_path)
    if not path.exists():
        return {'status': 'error', 'message': f'Файл не найден: {file_path}'}

    try:
        if path.suffix in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        elif path.suffix == '.csv':
            df = pd.read_csv(path)
        else:
            return {'status': 'error', 'message': f'Неподдерживаемый формат: {path.suffix}'}
    except Exception as e:
        return {'status': 'error', 'message': f'Ошибка чтения файла: {e}'}

    preview_df = df.head(n_rows)

    # Convert to JSON-safe format
    def safe_val(v: Any) -> Any:
        if pd.isna(v) if not isinstance(v, (list, dict)) else False:
            return None
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return round(float(v), 4)
        return str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v

    headers = list(df.columns)
    rows = [[safe_val(cell) for cell in row] for row in preview_df.itertuples(index=False)]
    dtypes = {col: str(df[col].dtype) for col in df.columns}

    return {
        'status': 'ok',
        'headers': headers,
        'rows': rows,
        'dtypes': dtypes,
        'shape': [int(df.shape[0]), int(df.shape[1])],
        'file_name': path.name,
        'size_kb': round(path.stat().st_size / 1024, 1),
    }


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
        role, confidence = detect_column_role_with_confidence(col)
        col_info: dict[str, Any] = {
            'name': col,
            'role': role,
            'confidence': confidence,
            'dtype': str(df[col].dtype),
        }

        if role == 'date':
            date_col = col
            # Phase 2 audit pass 5: per-column year span detection - позволяет
            # frontend (UnitCostsPanel) показать %/год input БЕЗ зависимости от
            # обученного pickle (econ_forecast_context требует model.latest.pkl).
            try:
                _dates = pd.to_datetime(df[col], errors='coerce').dropna()
                if not _dates.empty:
                    _years = _dates.dt.year
                    _unique_years = sorted(set(int(y) for y in _years.unique()))
                    col_info['date_stats'] = {
                        'min_date': _dates.min().strftime('%Y-%m-%d'),
                        'max_date': _dates.max().strftime('%Y-%m-%d'),
                        'unique_years': _unique_years,
                        'n_years': len(_unique_years),
                    }
            except Exception:
                pass  # Non-fatal - date detection still works без stats
        elif role == 'kpi':
            kpi_cols.append(col)
        elif role == 'media':
            media_cols.append(col)
            col_info['adstock_type'] = detect_adstock_type(col)
        elif role == 'control':
            control_cols.append(col)

        # Stats + histogram for numeric columns
        if pd.api.types.is_numeric_dtype(df[col]):
            col_series = df[col].fillna(0)
            zeros_pct = round((col_series == 0).sum() / len(col_series) * 100, 1)
            col_info['stats'] = {
                'min': round(float(col_series.min()), 4),
                'max': round(float(col_series.max()), 4),
                'mean': round(float(col_series.mean()), 4),
                'std': round(float(col_series.std()), 4),
                'sum': round(float(col_series.sum()), 2),
                'zeros_pct': zeros_pct,
                'nulls': int(df[col].isna().sum()),
                'cv': round(float(col_series.std() / col_series.mean() * 100), 1) if col_series.mean() != 0 else 0,
            }
            col_info['histogram'] = compute_histogram(df[col])

            if zeros_pct > 60:
                warnings.append({
                    'column': col,
                    'type': 'high_zeros',
                    'message': f'{col} - {zeros_pct}% нулей. Рекомендуем объединить с другим каналом',
                    'severity': 'warning',
                    'action': 'merge',
                })
            if col_info['stats']['cv'] < 5 and role == 'media':
                warnings.append({
                    'column': col,
                    'type': 'low_variance',
                    'message': f'{col} - вариативность <5%. Канал не информативен для модели',
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
    # v2.1.0 (пилот 2026-05-17, #37): SSOT ratio thresholds + texts с
    # frontend ratio-classifier.js. 5 коридоров:
    #   < 2:1 - error/critical: «Критически мало»
    #   2-3:1 - warning-high: «Ниже минимума»
    #   3-4:1 - warning: «Ниже рекомендуемого»
    #   4-6:1 - info: «Рекомендуемый уровень» (no warning)
    #   ≥ 6:1 - success: «Идеально» (no warning)
    # Labels одинаковые с frontend - юзер видит согласованный текст
    # в Validation, инсайтах и Контроле качества.
    n_predictors = len(media_cols) + len(control_cols)
    ratio = n_rows / max(n_predictors, 1)
    if ratio < 2:
        issues.append({
            'type': 'insufficient_data',
            'message': f'Ratio данных {ratio:.1f}:1 - критически мало. Модель почти наверняка переобучится - β-коэффициенты будут случайными',
            'severity': 'critical',
        })
    elif ratio < 3:
        warnings.append({
            'type': 'low_data',
            'message': f'Ratio {ratio:.1f}:1 - ниже минимума. Модель сойдётся, но доверительные интервалы будут очень широкими - используйте результаты как ориентир',
            'severity': 'warning',
        })
    elif ratio < 4:
        warnings.append({
            'type': 'borderline_data',
            'message': f'Ratio {ratio:.1f}:1 - ниже рекомендуемого. Модель работает, но с широкими доверительными интервалами - результаты как качественные ориентиры',
            'severity': 'warning',
        })

    # ── Date frequency + period check ──
    date_frequency = 'unknown'
    if date_col:
        date_frequency = detect_date_frequency(df[date_col])
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
            'message': f'{period_weeks} наблюдений - менее 1 года. Рекомендуем ≥52 недели (≥104 для надёжных результатов)',
            'severity': 'warning',
        })

    # ── Full correlation matrix ──
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    high_correlations = []
    full_correlation_matrix: dict[str, Any] = {'labels': [], 'matrix': []}

    if len(numeric_cols) >= 2:
        corr_df = df[numeric_cols].corr()
        # Replace NaN with 0 for JSON serialization
        corr_clean = corr_df.fillna(0)

        full_correlation_matrix = {
            'labels': numeric_cols,
            'matrix': [[round(float(v), 3) for v in row] for row in corr_clean.values],
        }

        for i, c1 in enumerate(numeric_cols):
            for j, c2 in enumerate(numeric_cols):
                if i < j:
                    r = abs(corr_df.loc[c1, c2])
                    if not np.isnan(r) and r > 0.8:
                        high_correlations.append({
                            'col1': c1, 'col2': c2,
                            'correlation': round(float(corr_df.loc[c1, c2]), 3),
                            'risk': 'Мультиколлинеарность - один из столбцов может быть избыточен',
                        })

    # ── Traffic Light verdict ──
    has_critical = any(i['severity'] == 'critical' for i in issues)
    status = 'error' if has_critical else ('warning' if warnings else 'ok')
    verdict = 'ТРЕБУЕТ ДОРАБОТКИ' if has_critical else (
        'ГОТОВ К МОДЕЛИРОВАНИЮ (с оговорками)' if warnings else 'ГОТОВ К МОДЕЛИРОВАНИЮ'
    )

    result: dict[str, Any] = {
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
            'date_frequency': date_frequency,
        },
        'issues': issues,
        'warnings': warnings,
        'high_correlations': high_correlations,
        'full_correlation_matrix': full_correlation_matrix,
    }

    # Save to project dir if provided.
    # Под RemoteApp/roaming profile запись может упасть с PermissionError /
    # OSError / invalid path - GUI всё равно получает result через return.
    # default=str страхует numpy-типы, которые json не умеет сериализовать.
    if project_dir:
        try:
            out_path = Path(project_dir) / 'results' / 'validation.json'
            out_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            logger.warning(
                'validation.json write failed, result still returned to GUI',
                exc_info=True,
            )

    return result
