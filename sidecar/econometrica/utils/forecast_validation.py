"""Forecast validation helpers - Phase 2.1 Step 2.

Detects data characteristics + emits warnings для planning mode forecasts.

Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md
- §3-4 - granularity + seasonality detection methodology
- §7 - locked decisions (M6 cap, M7 calibration boundaries)
- §10 - synergies S2 (Conformal-in-planning), S3 (verdict_tier extension),
       S7 (KPI registry coupling), G3 (warning composition priority)

Helpers exposed:
- detect_granularity(df, date_col) - D/W/M/Q/Y autoderive с confidence.
- detect_seasonality(y_actual, granularity) - autocorr-based detection.
- compute_x_norm_quantiles(adstock_series, mean) - for at-fit-time persistence
  AND at-load-time legacy pickle migration (G2).
- extrapolation_severity(x_norm_forecast, quantiles) - 0/1/2/3 tier (S3 input
  to verdict_tier extension).
- saturation_drift_check(...) - per-channel drift status (M8 raw + adstock ratio).
- horizon_extrapolation_check(forecast_n, train_n) - M6 cap warnings (warn at
  1.5×, hard reject 2× already enforced inline в optimizer).
- conformal_planning_intervals(...) - S2 wrapper around conformal.py для OLS
  pickles (distribution-free P10/P90 в planning mode).
- resolve_warning_priority(warnings) - G3 single critical messaging banner.

KPI-aware (S7): every threshold-bearing helper accepts optional kpi_type to
read kpi_config.forecast_* fields из KPI_REGISTRY.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np

# ─── Granularity codes ──────────────────────────────────────────────────────

Granularity = Literal['D', 'W', 'M', 'Q', 'Y']

# Days-per-period nominal (для horizon labels). Calendar irregularity (e.g. M
# == 28-31 days) accepted с small confidence penalty.
_DAYS_PER_GRANULARITY: dict[Granularity, float] = {
    'D': 1.0,
    'W': 7.0,
    'M': 30.4375,
    'Q': 91.3125,
    'Y': 365.25,
}


def detect_granularity(date_series, fallback: Granularity = 'W') -> dict:
    """Detect data granularity from a pandas datetime-like series.

    Computes median delta between consecutive timestamps and matches к nearest
    standard granularity. Confidence reflects regularity (CV of deltas).

    Args:
        date_series: pandas Series или array of datetime-like values (sorted).
            Accepts non-datetime objects - falls back к 'W' с confidence=0.

    Returns:
        {
            'granularity': 'D'|'W'|'M'|'Q'|'Y',
            'confidence': float in [0, 1],  # 1 = perfectly regular spacing
            'median_days': float,           # observed median delta in days
            'requires_user_confirm': bool,  # confidence < 0.6
        }
    """
    try:
        import pandas as pd
        dates = pd.to_datetime(pd.Series(date_series))
    except Exception:
        return {
            'granularity': fallback,
            'confidence': 0.0,
            'median_days': float(_DAYS_PER_GRANULARITY[fallback]),
            'requires_user_confirm': True,
        }

    if len(dates) < 2:
        return {
            'granularity': fallback,
            'confidence': 0.0,
            'median_days': float(_DAYS_PER_GRANULARITY[fallback]),
            'requires_user_confirm': True,
        }

    deltas_days = dates.diff().dropna().dt.total_seconds().to_numpy() / 86400.0
    if deltas_days.size == 0:
        return {
            'granularity': fallback,
            'confidence': 0.0,
            'median_days': float(_DAYS_PER_GRANULARITY[fallback]),
            'requires_user_confirm': True,
        }

    median_d = float(np.median(deltas_days))

    # Match к nearest granularity by log-ratio (handles all 5 in single pass)
    best_g: Granularity = fallback
    best_log_err = float('inf')
    for g, days in _DAYS_PER_GRANULARITY.items():
        log_err = abs(np.log(median_d / days)) if median_d > 0 and days > 0 else float('inf')
        if log_err < best_log_err:
            best_log_err = log_err
            best_g = g

    # Confidence: CV inverted (низкий CV → high confidence)
    if median_d > 0:
        cv = float(np.std(deltas_days) / median_d) if deltas_days.size > 1 else 0.0
        # Empirical mapping CV → confidence: CV=0 → 1.0, CV=0.5 → 0.5, CV≥1 → 0.0
        confidence = max(0.0, min(1.0, 1.0 - cv))
    else:
        confidence = 0.0

    # Penalize если log-error от nearest granularity > 0.15 (≈ 16% deviation)
    if best_log_err > 0.15:
        confidence *= max(0.0, 1.0 - (best_log_err - 0.15) * 2)

    return {
        'granularity': best_g,
        'confidence': float(confidence),
        'median_days': median_d,
        'requires_user_confirm': confidence < 0.6,
    }


# ─── Seasonality detection ─────────────────────────────────────────────────


def detect_seasonality(
    y_actual,
    granularity: Granularity = 'W',
    *,
    period_candidates: list[int] | None = None,
    autocorr_threshold: float = 0.2,
) -> dict | None:
    """Detect seasonality via autocorrelation на standard period candidates.

    Per audit doc L3: при autocorrelation ≥ 0.2 на period candidate → flag
    seasonality + require start_date input (Phase 2 hardened от plan's
    «warn-only»).

    Args:
        y_actual: 1D array-like of KPI values (assume detrended-friendly,
            but no explicit detrend here - Aurora's training data already
            stationary post-adstock+Hill per Conformal F3 caveat).
        granularity: data granularity (informs default period candidates).
        period_candidates: explicit period lengths to test. Defaults:
            'D' → [7, 30, 365], 'W' → [4, 13, 26, 52], 'M' → [3, 6, 12], etc.
        autocorr_threshold: lag-correlation magnitude triggering detection.

    Returns:
        Dict с {period, autocorr, candidates_tested} when detected.
        None when no period meets threshold.
    """
    y = np.asarray(y_actual, dtype=np.float64)
    y = y[np.isfinite(y)]
    if y.size < 20:
        return None

    if period_candidates is None:
        defaults = {
            'D': [7, 30, 90, 365],
            'W': [4, 13, 26, 52],
            'M': [3, 6, 12],
            'Q': [4],
            'Y': [],
        }
        period_candidates = defaults.get(granularity, [4, 13, 26, 52])

    # Per-lag Pearson correlation на overlap segment (correct normalization
    # независимая от lag - vs full-series var which biases toward short lags).
    candidates_results = []
    for lag in period_candidates:
        if lag <= 0 or lag >= y.size:
            continue
        a = y[:-lag]
        b = y[lag:]
        if a.std() < 1e-12 or b.std() < 1e-12:
            continue
        autocorr = float(np.corrcoef(a, b)[0, 1])
        candidates_results.append({'lag': int(lag), 'autocorr': autocorr})

    # Selection: prefer positive autocorr (real cyclic repetition vs anti-phase
    # half-period). Among positives meeting threshold, pick highest. If no
    # positives qualify, fall back to highest abs negative (signals strong
    # anti-periodicity = potential half-period seasonality).
    pos = [c for c in candidates_results if c['autocorr'] >= autocorr_threshold]
    neg = [c for c in candidates_results if c['autocorr'] <= -autocorr_threshold]
    best = None
    if pos:
        top = max(pos, key=lambda c: c['autocorr'])
        best = {'period': top['lag'], 'autocorr': top['autocorr']}
    elif neg:
        top = max(neg, key=lambda c: -c['autocorr'])  # most negative = strongest anti
        best = {'period': top['lag'], 'autocorr': top['autocorr']}

    if best is None:
        return None
    return {
        'period': best['period'],
        'autocorr': best['autocorr'],
        'candidates_tested': candidates_results,
    }


# ─── x_norm calibration boundaries ──────────────────────────────────────────


def compute_x_norm_quantiles(
    adstock_series, mean: float,
    quantile_levels: tuple[float, ...] = (0.5, 0.75, 0.9, 0.95, 0.99),
) -> dict[str, float]:
    """Compute per-channel x_norm quantiles из training adstock series.

    Used:
    - at-fit-time persistence (modeler.py) для new pickle field
    - at-load-time migration (engines/persistence.py:infer_*_at_load) для
      legacy v1.3 pickles без the field (G2 plan gap)

    Args:
        adstock_series: 1D array of adstocked spend (training period).
        mean: training mean (denominator for x_norm).
        quantile_levels: probability points to compute.

    Returns:
        {'p50': float, 'p75': float, ..., 'p99': float}
    """
    arr = np.asarray(adstock_series, dtype=np.float64)
    arr = arr[np.isfinite(arr) & (arr >= 0)]
    if arr.size == 0 or mean <= 0:
        return {f'p{int(q*100)}': 0.0 for q in quantile_levels}
    x_norm = arr / mean
    return {
        f'p{int(q * 100)}': float(np.quantile(x_norm, q))
        for q in quantile_levels
    }


def extrapolation_severity(
    x_norm_forecast: float,
    quantiles: dict[str, float] | None,
) -> int:
    """Severity tier per audit doc M7 - used by verdict_tier extension (S3).

    Tiers:
        0: in-zone (≤ p95) - calibration valid
        1: p95 boundary (p95 < x ≤ p99) - warn-tier (verdict «Направленная»)
        2: p99 extrapolation (p99 < x ≤ 3× p99) - critical-tier
        3: ≥ 3× p99 - extreme extrapolation (verdict «Высокая неопределённость»)

    Args:
        x_norm_forecast: forecast-period x_norm value (per-channel).
        quantiles: dict с 'p95', 'p99' keys (others ignored). None or missing
            keys → severity 0 (cannot judge - assume in-zone).

    Returns:
        int 0..3.
    """
    if quantiles is None:
        return 0
    p95 = quantiles.get('p95')
    p99 = quantiles.get('p99')
    if p95 is None or p99 is None or p99 <= 0:
        return 0
    if x_norm_forecast <= p95:
        return 0
    if x_norm_forecast <= p99:
        return 1
    if x_norm_forecast <= p99 * 3.0:
        return 2
    return 3


# ─── Saturation drift detection (M8) ───────────────────────────────────────


def saturation_drift_check(
    forecast_per_period_spend: float,
    train_avg_spend: float,
    *,
    forecast_avg_adstock: float | None = None,
    train_avg_adstock: float | None = None,
    drift_warn_ratio: float = 3.0,
    drift_low_ratio: float = 0.3,
) -> dict | None:
    """Per-channel drift detection.

    Implements both:
    - M8 raw spend ratio: forecast_avg / train_avg ≥ 3× → critical, ≤ 0.3× → warn
    - M8 adstock ratio: forecast_adstock_avg / train_adstock_avg ≥ 3× → critical
      (caller passes computed values; helper just compares).

    Args:
        forecast_per_period_spend: per-period spend в forecast (raw, native units).
        train_avg_spend: training period average spend (native units).
        forecast_avg_adstock: optional - forecast-period adstock mean.
        train_avg_adstock: optional - training adstock_mean_posterior.
        drift_warn_ratio: threshold for «high drift» warning (default 3.0).
        drift_low_ratio: threshold for «low spend zone» warning (default 0.3).

    Returns:
        Dict {ratio_spend, ratio_adstock, severity, message_ru} or None в-zone.
    """
    if train_avg_spend <= 0:
        return None
    ratio_spend = float(forecast_per_period_spend / train_avg_spend)

    ratio_adstock = None
    if forecast_avg_adstock is not None and train_avg_adstock is not None and train_avg_adstock > 0:
        ratio_adstock = float(forecast_avg_adstock / train_avg_adstock)

    # Determine severity
    severity = None
    if ratio_spend >= drift_warn_ratio:
        severity = 'critical'
    elif ratio_spend <= drift_low_ratio:
        severity = 'warn'
    if ratio_adstock is not None and ratio_adstock >= drift_warn_ratio:
        severity = 'critical'  # adstock-based critical overrides spend warn

    if severity is None:
        return None

    if severity == 'critical':
        if ratio_spend >= drift_warn_ratio:
            msg = (
                f'Прогнозный per-period spend в {ratio_spend:.1f}× выше обучающего среднего. '
                f'Hill saturation вне калибровочной зоны - оценка ROI может быть занижена.'
            )
        else:
            msg = (
                f'Adstock накопление {ratio_adstock:.1f}× выше обучающего - '
                f'β posterior экстраполируется за пределами наблюдённых данных.'
            )
    else:  # warn
        msg = (
            f'Прогнозный per-period spend всего {ratio_spend:.2f}× от обучающего среднего. '
            f'β плохо калиброван для нижней зоны - увеличьте до ≥30% от обучающего среднего.'
        )

    return {
        'ratio_spend': ratio_spend,
        'ratio_adstock': ratio_adstock,
        'severity': severity,
        'message_ru': msg,
    }


# ─── Horizon extrapolation (M6) - soft warning beyond hard reject ───────────


def horizon_extrapolation_check(
    forecast_n: int, train_n: int, *, warn_factor: float = 1.5,
) -> dict | None:
    """Soft warning at 1.5× horizon (hard reject 2× already enforced inline).

    Returns:
        Dict {ratio, severity, message_ru} when forecast_n / train_n > warn_factor;
        else None.
    """
    if train_n <= 0:
        return None
    ratio = float(forecast_n / train_n)
    if ratio <= warn_factor:
        return None
    return {
        'ratio': ratio,
        'severity': 'warn',
        'message_ru': (
            f'Период планирования ({forecast_n}) в {ratio:.1f}× больше обучающего '
            f'({train_n}). Допущение стационарности коэффициентов на пределе. '
            f'Используйте только пропорции каналов; абсолютные ROI прогнозы менее точны.'
        ),
    }


# ─── Conformal-in-planning (S2 synergy - OLS users get P10/P90) ─────────────


def conformal_planning_intervals(
    model_data: dict,
    *,
    confidence: float = 0.8,
) -> dict | None:
    """Distribution-free P10/P90 для OLS pickles в planning mode (S2 synergy).

    Wraps `utils.conformal.auto_intervals` against training (X, y) stored
    в pickle. Returns symmetric `half_width` to apply вокруг point estimate
    in optimizer planning result.

    Args:
        model_data: loaded pickle dict (must contain 'X_train', 'y_train' or
            equivalent - caller responsibility for backward compat).
        confidence: PI level (default 0.8 = 80% - matches Phase 1.9 90% Bayesian
            HDI choice scaled к customer-friendly 80%).

    Returns:
        {half_width, method, exchangeability_caveat} when computable.
        None when training arrays missing (Bayesian-only pickles use posterior CI).
    """
    X_train = model_data.get('X_train')
    y_train = model_data.get('y_train')
    if X_train is None or y_train is None:
        return None
    try:
        from utils.conformal import auto_intervals
        result = auto_intervals(X_train, y_train, confidence=confidence)
    except Exception:
        return None
    if 'half_width' not in result:
        return None
    return {
        'half_width': float(result['half_width']),
        'method': result.get('auto_choice', 'unknown'),
        'exchangeability_caveat': result.get('exchangeability_caveat'),
    }


# ─── Warning composition priority (G3 plan gap) ────────────────────────────


_PRIORITY_ORDER = {
    'critical': 3,
    'warn': 2,
    'info': 1,
}


def resolve_warning_priority(warnings: list[dict]) -> dict:
    """G3 - compose multiple warnings into single banner с priority order.

    Aurora's UX shouldn't show 5 warning banners simultaneously. Resolve to
    one «top warning» (highest priority) + secondary expandable list.

    Priority order:
    1. Critical (e.g. extrapolation p99+, drift ≥3×, infeasible budget)
    2. Warn (drift 1.5-3×, p95 boundary, horizon >1.5×, seasonality detected)
    3. Info (binding constraints, hierarchical pooling note)

    Within same severity, preserves input order (caller controls ordering).

    Args:
        warnings: list of {severity, message_ru, ...} dicts.

    Returns:
        {top_warning: dict | None, secondary: list[dict], total_count: int}
    """
    valid = [w for w in warnings if isinstance(w, dict) and w.get('severity') in _PRIORITY_ORDER]
    if not valid:
        return {'top_warning': None, 'secondary': [], 'total_count': 0}

    sorted_warnings = sorted(
        valid, key=lambda w: (-_PRIORITY_ORDER[w['severity']],),
        # stable sort preserves input order within same priority
    )
    return {
        'top_warning': sorted_warnings[0],
        'secondary': sorted_warnings[1:],
        'total_count': len(sorted_warnings),
    }


# ─── L5 - Hierarchical extrapolation warning (Phase 2.0 Part 2) ─────────────


def hierarchical_extrapolation_warning(
    model_data: dict,
    *,
    forecast_budget_money: float,
    train_total_money: float,
    brand_drift_threshold: float = 3.0,
) -> dict | None:
    """L5 (Phase 2.0 Part 2 - 2026-05-03): conditional warning about hierarchical
    pooling underestimation при extreme budget extrapolation.

    Replaces planned generic always-shown warning. Quantitative threshold based
    on consistency с M8 drift detection convention (3× ratio = critical zone).

    Mechanism: при hierarchical model + brand-channel budget ratio > 3× training,
    β posterior shrinkage может pull brand top-performer estimates toward group
    mean, underestimating its true contribution. Customer should cross-check с
    flat model OR narrow forecast horizon.

    Args:
        model_data: loaded pickle dict.
        forecast_budget_money: planning budget total (₽).
        train_total_money: training period total spend (₽).
        brand_drift_threshold: ratio threshold (default 3.0, matches M8).

    Returns:
        Dict {severity, message_ru, forecast_ratio, brand_channels} when warning
        applies. None when:
        - Model is not hierarchical (model_version < 1.3 OR use_hierarchical=False)
        - No brand-categorized channels
        - Forecast ratio ≤ threshold
        - Training total invalid (≤ 0)
    """
    if not model_data.get('use_hierarchical'):
        return None
    if train_total_money <= 0:
        return None
    categories = model_data.get('channel_categories') or {}
    brand_channels = sorted(
        c for c, cat in categories.items() if cat == 'brand'
    )
    if not brand_channels:
        return None
    ratio = float(forecast_budget_money) / float(train_total_money)
    if ratio <= brand_drift_threshold:
        return None
    return {
        'severity': 'warn',
        'message_ru': (
            f'Прогнозный бюджет ({ratio:.1f}× от обучающего) выводит brand-каналы '
            f'за калибровочную зону (порог {brand_drift_threshold:.1f}×). '
            f'Иерархическая модель усредняет вклад между brand-каналами '
            f'({", ".join(brand_channels)}) - лидирующий канал может быть занижен '
            f'на 5–15% в зоне экстраполяции. Сократите горизонт до ≤ 2× обучающего '
            f'или сравните с flat-моделью для более точных абсолютных ROI.'
        ),
        'category_filter': 'brand',
        'forecast_ratio': ratio,
        'brand_channels': brand_channels,
        'threshold': brand_drift_threshold,
    }


# ─── KPI registry coupling (S7 synergy) ─────────────────────────────────────


def get_forecast_horizon_max_multiplier(kpi_type: str | None = None) -> float:
    """KPI-specific hard cap multiplier (S7).

    Defaults to 2.0 (sales convention). When KPI_REGISTRY adds awareness with
    `forecast_horizon_max_multiplier` field, returns that value.

    Args:
        kpi_type: 'sales', 'awareness', etc. None returns default 2.0.

    Returns:
        float ≥ 1.0.
    """
    if kpi_type is None:
        return 2.0
    try:
        from utils.kpi_registry import get_kpi_config
        config = get_kpi_config(kpi_type)
    except (ValueError, ImportError):
        return 2.0
    # Backward compat: KPIConfig may не иметь this field yet (Phase 2 partial
    # registry extension). Safe getattr с default.
    return float(getattr(config, 'forecast_horizon_max_multiplier', 2.0))
