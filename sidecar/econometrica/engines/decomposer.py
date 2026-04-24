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
    y_actual = np.array(model_data['y_actual'])
    y_predicted = np.array(model_data['y_predicted'])
    media_cols = config['media_columns']
    # Override > config. Передан ли override (даже {}) — клиент управляет явно.
    # None → fallback на pickle (для старых pkl или sessions без знания current state).
    unit_costs = unit_costs_override if unit_costs_override is not None else (config.get('unit_costs', {}) or {})

    # Read original data for spend totals
    data_file = config['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (если были merge_rules при train)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))

    total_sales = float(y_actual.sum())
    baseline = float(y_actual.sum() - y_predicted.sum()) + float(y_predicted.mean() * len(y_actual) * 0.3)

    # Channel contributions (proportional to beta × saturated effect)
    channels = []
    total_media_contribution = 0
    for col in media_cols:
        params = channel_params[col]
        raw_spend = float(df[col].fillna(0).sum())
        # Native-unit spend (TRPs, показы) → денежный эквивалент через CPP/CPM.
        # Для каналов в рублях unit_cost = 1.0 (default) → spend без изменений.
        unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
        spend = raw_spend * unit_cost
        # Contribution proportional to beta (simplified)
        total_beta = sum(abs(channel_params[c]['beta']) for c in media_cols)
        contribution_pct = abs(params['beta']) / total_beta if total_beta > 1e-10 else 0
        contribution = (total_sales - baseline) * contribution_pct
        roi = contribution / spend if spend > 0 else 0
        total_media_contribution += contribution

        channels.append({
            'name': col,
            'spend': round(spend, 0),
            'raw_spend': round(raw_spend, 2),
            'unit_cost': unit_cost,
            'contribution': round(contribution, 0),
            'contribution_pct': round(contribution_pct * 100, 1),
            'roi': round(roi, 2),
            'beta': params['beta'],
            # verdict пересчитывается ниже после efficiency_gap.
            'verdict': '',
            'verdict_tone': 'neutral',
        })

    # Sort by ROI descending
    channels.sort(key=lambda x: x['roi'], reverse=True)

    # Share of Spend vs Share of Effect (нужно ДО verdict, т.к. verdict учитывает gap)
    total_spend = sum(c['spend'] for c in channels) or 1
    for ch in channels:
        ch['share_of_spend'] = round(ch['spend'] / total_spend * 100, 1)
        ch['share_of_effect'] = ch['contribution_pct']
        ch['efficiency_gap'] = round(ch['share_of_effect'] - ch['share_of_spend'], 1)

    # Verdict — комбинирует ROI И efficiency_gap. Раньше использовался только ROI,
    # поэтому каналы с ROI=10× но gap=-23% (перенасыщенные) помечались «Эффективен».
    # Также детектируем подозрительно высокий ROI (>50×) — типично для смешанных
    # единиц (TRPs vs рубли) и помечаем отдельно, чтобы пользователь не доверял слепо.
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
        # unit_smell = «имя подозрительное» ∧ «CPP не задан» (unit_cost == 1.0).
        # Если user настроил CPP — канал уже в money-эквиваленте, smell снимается.
        ch['unit_smell'] = bool(looks_like_non_money and abs(ch['unit_cost'] - 1.0) < 1e-9)

        # «Не рубли?» только когда CPP не задан (unit_cost=1.0). Если CPP задан —
        # канал уже в money, завышенный ROI — про другое (модель сомневается или мало данных).
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

    # Per-period time series contributions
    date_col = config.get('date_column', 'date')
    if date_col in df.columns:
        dates = [str(d)[:10] for d in df[date_col].tolist()]
    else:
        dates = [str(i + 1) for i in range(len(df))]

    n_periods = len(df)
    y_arr = y_actual[:n_periods] if len(y_actual) >= n_periods else y_actual

    # Per-period channel contributions (proportional to spend in each period).
    # ВАЖНО: ratio берётся по RAW spend (df[col]), т.к. unit_cost постоянен для канала
    # во всех периодах → разницы между использованием raw vs money нет математически,
    # но raw — безопаснее (никаких шансов деления money на raw из-за опечатки).
    time_series_channels = {}
    for ch in channels:
        col = ch['name']
        total_raw = float(ch['raw_spend'])
        ch_contribution = ch['contribution']
        if total_raw > 0:
            spend_per_period = df[col].fillna(0).values[:n_periods]
            ts_contrib = [(float(s) / total_raw * ch_contribution) for s in spend_per_period]
        else:
            ts_contrib = [0.0] * n_periods
        time_series_channels[col] = [round(v, 1) for v in ts_contrib]

    # Baseline per period: residual = actual - sum(channel contributions per period)
    baseline_ts = []
    for t in range(n_periods):
        ch_total_t = sum(time_series_channels[ch['name']][t] for ch in channels)
        b_t = float(y_arr[t]) - ch_total_t if t < len(y_arr) else 0.0
        baseline_ts.append(round(b_t, 1))

    # Smell-детектор для banner доверия (Trust Level 1).
    # Модель должна сама предупреждать о своих пределах — это USP vs Robyn/LightweightMMM.
    #
    # Порог ROI > 50 применяется только если есть хоть один канал в не-денежных единицах
    # БЕЗ CPP (unit_smell). Если все каналы в money (unit_cost≠1.0 задан везде где нужно),
    # высокий ROI — честный результат модели, не артефакт единиц → banner не нужен.
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
