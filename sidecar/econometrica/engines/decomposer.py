"""
Sales decomposition engine.
Breaks down total sales into baseline + channel contributions.

P0-3/4/10 fix (math-fix-v1.0.13, Phase 3):
Pre-fix: contribution = |β|/Σ|β| × (total - baseline) → ignored adstock,
saturation, time. Baseline = sum(actual - predicted) + 0.3 × predicted.mean × n.
Post-fix: contribution_per_period = β × hill(adstock(x)/mean) × y_std.
Baseline = intercept × y_std + y_mean × n + control_effect × y_std.
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any

from utils.adstock import apply_adstock
from utils.saturation import hill_function


def decompose(project_dir: str, unit_costs_override: dict | None = None) -> dict[str, Any]:
    """Decompose sales into baseline + channel contributions using trained model.

    Args:
        project_dir: Path to project with models/latest.pkl
        unit_costs_override: Если задан — используется вместо config.unit_costs из pickle.
            Нужно, когда user изменил CPP/CPM после тренировки модели.

    Returns:
        JSON with waterfall data, ROI, share of spend vs effect
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {'status': 'error', 'message': 'Модель не найдена. Сначала обучите модель в кабинете "Данные и Модель"'}

    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)

    # P0-1/2/9 fix: pickle compat detection.
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась — переобучите модель в кабинете "Модель".',
        }

    config = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    y_actual = np.array(model_data['y_actual'])
    y_predicted_saved = np.array(model_data.get('y_predicted', []) or [])
    media_cols = config['media_columns']
    control_cols = config.get('control_columns', []) or []
    # Override > config. Передан ли override (даже {}) — клиент управляет явно.
    unit_costs = unit_costs_override if unit_costs_override is not None else (config.get('unit_costs', {}) or {})

    # Read original data for spend totals + adstock + control effects
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (если были merge_rules при train)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    n_periods = len(df)
    total_sales = float(y_actual.sum())

    # Normalization params
    y_mean = float(norm.get('y_mean', 0))
    y_std = float(norm.get('y_std', 1)) or 1
    intercept_mean = float(norm.get('intercept_mean', 0))
    control_betas_mean = norm.get('control_betas_mean', []) or []
    media_means = norm.get('media_means', {}) or {}
    control_means = norm.get('control_means', {}) or {}
    control_stds = norm.get('control_stds', {}) or {}

    adstock_config = config.get('adstock_config', {}) or {}

    # ─────────────────────────────────────────────────────────────────────
    # P0-3/4/10 fix: per-channel per-period contribution = β × hill(adstock(x)/mean) × y_std
    # ─────────────────────────────────────────────────────────────────────
    channels = []
    time_series_channels: dict[str, list[float]] = {}
    total_media_contribution = 0.0

    for col in media_cols:
        params = channel_params[col]
        beta = float(params.get('beta', 0))
        alpha = max(float(params.get('alpha', 1)), 1e-6)
        gamma = max(float(params.get('gamma', 0.5)), 1e-6)

        raw_spend_series = df[col].fillna(0).values.astype(float)
        raw_spend_total = float(raw_spend_series.sum())

        # 1. Adstock (matches training)
        a_type = adstock_config.get(col, {}).get('type', 'geometric') if isinstance(adstock_config.get(col), dict) else adstock_config.get(col, 'geometric')
        x_adstock = apply_adstock(raw_spend_series, a_type)

        # 2. Normalize spend/mean (matches Phase 2 fix)
        mean = float(media_means.get(col, 1)) or 1
        x_norm = x_adstock / max(mean, 1e-10)

        # 3. Hill saturation
        sat = hill_function(np.maximum(x_norm, 0), alpha=alpha, gamma=gamma)

        # 4. Per-period contribution in original KPI units
        contrib_per_period = beta * sat * y_std
        channel_total = float(contrib_per_period.sum())
        total_media_contribution += channel_total

        time_series_channels[col] = [round(float(v), 1) for v in contrib_per_period]

        # Money & ROI
        unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
        spend_money = raw_spend_total * unit_cost

        roi = channel_total / spend_money if spend_money > 0 else 0

        channels.append({
            'name': col,
            'spend': round(spend_money, 0),
            'raw_spend': round(raw_spend_total, 2),
            'unit_cost': unit_cost,
            'contribution': round(channel_total, 0),
            'contribution_pct': 0,  # filled after total computed below
            'roi': round(roi, 2),
            'beta': beta,
            'verdict': '',
            'verdict_tone': 'neutral',
        })

    # Fill contribution_pct relative to total media contribution
    for ch in channels:
        ch['contribution_pct'] = round(
            ch['contribution'] / total_media_contribution * 100, 1
        ) if total_media_contribution > 0 else 0

    # ─────────────────────────────────────────────────────────────────────
    # Baseline = intercept_mean × y_std + y_mean (per period) + control effect
    # ─────────────────────────────────────────────────────────────────────
    intercept_per_period = np.full(n_periods, intercept_mean * y_std + y_mean, dtype=float)

    control_effect_per_period = np.zeros(n_periods, dtype=float)
    if control_cols and control_betas_mean and len(control_betas_mean) == len(control_cols):
        # Reconstruct control normalization (z-score retained for controls — non-Hill linear)
        c_means = np.array([float(control_means.get(c, 0)) for c in control_cols])
        c_stds = np.array([float(control_stds.get(c, 1)) or 1 for c in control_cols])
        X_control_raw = df[control_cols].fillna(0).astype(float).values
        X_control_norm = (X_control_raw - c_means) / c_stds
        beta_c = np.array(control_betas_mean, dtype=float)
        # control_effect normalised → multiply by y_std for original-unit
        control_effect_per_period = (X_control_norm @ beta_c) * y_std

    # Energy conservation (post-audit fix): baseline absorbs residual variance
    # so that sum(baseline) + sum(channels) == sum(y_actual) exactly.
    # Standard MMM convention (Robyn, LightweightMMM, Meridian): residual goes
    # into baseline since by construction it's "unexplained by media".
    # Compute model-predicted per period (sum of intercept + media + controls):
    media_contrib_per_period = np.zeros(n_periods, dtype=float)
    for col in media_cols:
        ts = time_series_channels.get(col, [])
        for t, v in enumerate(ts):
            if t < n_periods:
                media_contrib_per_period[t] += float(v)
    raw_baseline = intercept_per_period + control_effect_per_period
    model_predicted_per_period = raw_baseline + media_contrib_per_period
    # Residual = actual - model_predicted; absorbed into baseline
    if len(y_actual) >= n_periods:
        residual_per_period = y_actual[:n_periods] - model_predicted_per_period
    else:
        residual_per_period = np.zeros(n_periods, dtype=float)
    baseline_per_period = raw_baseline + residual_per_period
    baseline_total = float(baseline_per_period.sum())
    baseline_ts = [round(float(v), 1) for v in baseline_per_period]

    # Sort by ROI descending
    channels.sort(key=lambda x: x['roi'], reverse=True)

    # Share of Spend vs Share of Effect
    total_spend = sum(c['spend'] for c in channels) or 1
    for ch in channels:
        ch['share_of_spend'] = round(ch['spend'] / total_spend * 100, 1)
        ch['share_of_effect'] = ch['contribution_pct']
        ch['efficiency_gap'] = round(ch['share_of_effect'] - ch['share_of_spend'], 1)

    # Verdict logic (preserved from pre-fix — depends on roi + efficiency_gap + unit_smell)
    UNIT_HINTS = ('TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ', 'КЛИК', 'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ')
    BRAND_HINTS = ('TRP', 'GRP', 'OTS', 'ОХВАТ', 'РЕЙТИНГ', 'TV', 'ТВ', 'OOH', 'НАРУЖК', 'РАДИО', 'RADIO', 'БРЕНД', 'BRAND')
    PERF_HINTS = ('DIGITAL', 'SEARCH', 'ПОИСК', 'CONTEXT', 'КОНТЕКСТ', 'SOCIAL', 'СОЦ', 'CTR', 'CPC', 'CPA', 'PERFORMANCE', 'ПЕРФ', 'ЯНДЕКС', 'GOOGLE', 'VK', 'ВК', 'TELEGRAM', 'ТЕЛЕГРАМ', 'МЕТА', 'META', 'КЛИК', 'ПРОСМОТР', 'ВИЗИТ')
    for ch in channels:
        roi = ch['roi']
        gap = ch['efficiency_gap']
        name_upper = (ch['name'] or '').upper()
        looks_like_non_money = any(hint in name_upper for hint in UNIT_HINTS)
        is_brand = any(hint in name_upper for hint in BRAND_HINTS)
        is_perf = any(hint in name_upper for hint in PERF_HINTS)
        if is_brand and not is_perf:
            ch['category'] = 'brand_reach'
        elif is_perf and not is_brand:
            ch['category'] = 'performance'
        else:
            ch['category'] = 'mixed'
        ch['unit_smell'] = bool(looks_like_non_money and abs(ch['unit_cost'] - 1.0) < 1e-9)

        if roi > 50 and ch['unit_smell']:
            ch['verdict'] = 'ROI завышен (не рубли?)'
            ch['verdict_tone'] = 'warn'
        elif roi > 50:
            ch['verdict'] = 'ROI подозрительно высок'
            ch['verdict_tone'] = 'warn'
        elif roi < 0.8:
            ch['verdict'] = 'Убыточный'
            ch['verdict_tone'] = 'bad'
        elif roi < 1.0:
            ch['verdict'] = 'На грани окупаемости'
            ch['verdict_tone'] = 'warn'
        elif gap <= -10:
            ch['verdict'] = 'Перенасыщен'
            ch['verdict_tone'] = 'warn'
        elif gap <= -5:
            ch['verdict'] = 'Слабее своей доли'
            ch['verdict_tone'] = 'warn'
        elif gap >= 10:
            ch['verdict'] = 'Высокоэффективен'
            ch['verdict_tone'] = 'good'
        elif gap >= 5:
            ch['verdict'] = 'Эффективен'
            ch['verdict_tone'] = 'good'
        else:
            ch['verdict'] = 'Сбалансирован'
            ch['verdict_tone'] = 'neutral'

    # Insight generation (template, 0 tokens)
    top = channels[0] if channels else None
    worst = channels[-1] if channels else None
    insight = ''
    if top and worst:
        insight = (f"{top['name']} — самый эффективный канал (ROI {top['roi']:.1f}×). "
                   f"{worst['name']} — наименее эффективный (ROI {worst['roi']:.1f}×).")
        if top['efficiency_gap'] > 5:
            lift = abs(worst['efficiency_gap']) * 0.5
            insight += f" Перераспределение {abs(worst['efficiency_gap']):.0f}% бюджета из {worst['name']} в {top['name']} даст ожидаемый прирост +{lift:.1f}% продаж."

    # Per-period dates
    date_col = config.get('date_column', 'date')
    if date_col in df.columns:
        dates = [str(d)[:10] for d in df[date_col].tolist()]
    else:
        dates = [str(i + 1) for i in range(n_periods)]

    # Smell-детектор для banner доверия
    smell_flags = []
    positive_rois = [c['roi'] for c in channels if c['roi'] > 0]
    any_unit_smell = any(c.get('unit_smell') for c in channels)
    if positive_rois and any_unit_smell:
        roi_max = max(positive_rois)
        roi_min = min(positive_rois)
        if roi_max > 50:
            top_ch = max(channels, key=lambda c: c['roi'])
            smell_flags.append({
                'type': 'roi_max',
                'channel': top_ch['name'],
                'value': round(roi_max, 1),
                'severity': 'high' if roi_max > 200 else 'medium',
            })
        if roi_min > 0 and roi_max / roi_min > 50:
            smell_flags.append({
                'type': 'roi_spread',
                'value': round(roi_max / roi_min, 1),
                'severity': 'high' if roi_max / roi_min > 200 else 'medium',
            })
    unit_smell_channels = [c['name'] for c in channels if c.get('unit_smell')]
    if unit_smell_channels:
        smell_flags.append({
            'type': 'unit_smell',
            'channels': unit_smell_channels,
            'severity': 'medium',
        })

    result = {
        'status': 'ok',
        'smell_flags': smell_flags,
        'total_sales': round(total_sales, 0),
        'baseline': round(baseline_total, 0),
        'baseline_pct': round(baseline_total / total_sales * 100, 1) if total_sales else 0,
        'media_contribution': round(total_media_contribution, 0),
        'channels': channels,
        'insight': insight,
        'waterfall': {
            'labels': ['Baseline'] + [c['name'] for c in channels] + ['Итого'],
            'values': [round(baseline_total, 0)] + [round(c['contribution'], 0) for c in channels] + [round(total_sales, 0)],
            'types': ['baseline'] + ['channel'] * len(channels) + ['total'],
        },
        'time_series': {
            'dates': dates,
            'baseline': baseline_ts,
            'channels': time_series_channels,
        },
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'decomposition.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
