"""
Sales decomposition engine.
Breaks down total sales into baseline + channel contributions.
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any


def decompose(project_dir: str) -> dict[str, Any]:
    """Decompose sales into baseline + channel contributions using trained model.

    Args:
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with waterfall data, ROI, share of spend vs effect
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {'status': 'error', 'message': 'Модель не найдена. Сначала обучите модель в кабинете "Данные и Модель"'}

    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)

    config = model_data['config']
    channel_params = model_data['channel_params']
    y_actual = np.array(model_data['y_actual'])
    y_predicted = np.array(model_data['y_predicted'])
    media_cols = config['media_columns']

    # Read original data for spend totals
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)

    total_sales = float(y_actual.sum())
    baseline = float(y_actual.sum() - y_predicted.sum()) + float(y_predicted.mean() * len(y_actual) * 0.3)

    # Channel contributions (proportional to beta × saturated effect)
    channels = []
    total_media_contribution = 0
    for col in media_cols:
        params = channel_params[col]
        spend = float(df[col].fillna(0).sum())
        # Contribution proportional to beta (simplified)
        total_beta = sum(abs(channel_params[c]['beta']) for c in media_cols)
        contribution_pct = abs(params['beta']) / total_beta if total_beta > 1e-10 else 0
        contribution = (total_sales - baseline) * contribution_pct
        roi = contribution / spend if spend > 0 else 0
        total_media_contribution += contribution

        channels.append({
            'name': col,
            'spend': round(spend, 0),
            'contribution': round(contribution, 0),
            'contribution_pct': round(contribution_pct * 100, 1),
            'roi': round(roi, 2),
            'beta': params['beta'],
            'verdict': 'Эффективен' if roi > 1.5 else ('Приемлемый' if roi > 0.8 else 'Неэффективен'),
        })

    # Sort by ROI descending
    channels.sort(key=lambda x: x['roi'], reverse=True)

    # Share of Spend vs Share of Effect
    total_spend = sum(c['spend'] for c in channels) or 1
    for ch in channels:
        ch['share_of_spend'] = round(ch['spend'] / total_spend * 100, 1)
        ch['share_of_effect'] = ch['contribution_pct']
        ch['efficiency_gap'] = round(ch['share_of_effect'] - ch['share_of_spend'], 1)

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

    # Per-period time series contributions
    date_col = config.get('date_column', 'date')
    if date_col in df.columns:
        dates = [str(d)[:10] for d in df[date_col].tolist()]
    else:
        dates = [str(i + 1) for i in range(len(df))]

    n_periods = len(df)
    y_arr = y_actual[:n_periods] if len(y_actual) >= n_periods else y_actual

    # Per-period channel contributions (proportional to spend in each period)
    time_series_channels = {}
    for ch in channels:
        col = ch['name']
        total_ch_spend = ch['spend']
        ch_contribution = ch['contribution']
        if total_ch_spend > 0:
            spend_per_period = df[col].fillna(0).values[:n_periods]
            ts_contrib = [(float(s) / total_ch_spend * ch_contribution) for s in spend_per_period]
        else:
            ts_contrib = [0.0] * n_periods
        time_series_channels[col] = [round(v, 1) for v in ts_contrib]

    # Baseline per period: residual = actual - sum(channel contributions per period)
    baseline_ts = []
    for t in range(n_periods):
        ch_total_t = sum(time_series_channels[ch['name']][t] for ch in channels)
        b_t = float(y_arr[t]) - ch_total_t if t < len(y_arr) else 0.0
        baseline_ts.append(round(b_t, 1))

    result = {
        'status': 'ok',
        'total_sales': round(total_sales, 0),
        'baseline': round(baseline, 0),
        'baseline_pct': round(baseline / total_sales * 100, 1) if total_sales else 0,
        'media_contribution': round(total_media_contribution, 0),
        'channels': channels,
        'insight': insight,
        'waterfall': {
            'labels': ['Baseline'] + [c['name'] for c in channels] + ['Итого'],
            'values': [round(baseline, 0)] + [round(c['contribution'], 0) for c in channels] + [round(total_sales, 0)],
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
