"""
Scenario prediction engine.
Predicts KPI from a custom media plan using trained model.
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any

from utils.adstock import apply_adstock
from utils.saturation import hill_function


def predict_scenario(config: dict, project_dir: str) -> dict[str, Any]:
    """Predict KPI for a given media plan scenario.

    Args:
        config: {
            'scenario_name': str,
            'media_plan': dict[str, list[float]],  # {channel: [month1, month2, ...]}
            'media_plan_file': str|None,            # Or path to xlsx with plan
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with predicted KPI per period and totals
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {'status': 'error', 'message': 'Модель не найдена'}

    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)

    config_model = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    media_cols = config_model['media_columns']

    # Load media plan
    media_plan = config.get('media_plan', {})
    if config.get('media_plan_file'):
        plan_file = config['media_plan_file']
        if plan_file.endswith('.csv'):
            plan_df = pd.read_csv(plan_file)
        else:
            plan_df = pd.read_excel(plan_file)
        for col in media_cols:
            if col in plan_df.columns:
                media_plan[col] = plan_df[col].fillna(0).tolist()

    if not media_plan:
        return {'status': 'error', 'message': 'Медиаплан пуст. Укажите бюджеты по каналам'}

    # Determine periods
    n_periods = max(len(v) for v in media_plan.values()) if media_plan else 0
    if n_periods == 0:
        return {'status': 'error', 'message': 'Медиаплан не содержит данных'}

    # Apply adstock + saturation → predict
    predictions = []
    channel_contributions = {col: [] for col in media_cols}

    for t in range(n_periods):
        total_effect = 0
        for col in media_cols:
            spend = media_plan.get(col, [0] * n_periods)
            spend_t = spend[t] if t < len(spend) else 0

            p = channel_params[col]
            # Normalize like training
            mean = norm['media_means'].get(col, 0)
            std = norm['media_stds'].get(col, 1)
            x_norm = (spend_t - mean) / std if std > 0 else 0

            # Saturate
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 0.01))
            contribution = p['beta'] * sat[0]
            total_effect += contribution
            channel_contributions[col].append(round(float(contribution * norm['y_std']), 0))

        predicted = total_effect * norm['y_std'] + norm['y_mean']
        predictions.append(round(float(predicted), 0))

    # Baseline comparison
    baseline_total = norm['y_mean'] * n_periods
    scenario_total = sum(predictions)
    lift_pct = (scenario_total - baseline_total) / baseline_total * 100 if baseline_total else 0
    total_spend = sum(sum(media_plan.get(col, [])) for col in media_cols)
    roas = scenario_total / total_spend if total_spend > 0 else 0

    scenario_name = config.get('scenario_name', 'custom')

    result = {
        'status': 'ok',
        'scenario_name': scenario_name,
        'n_periods': n_periods,
        'predictions': predictions,
        'channel_contributions': channel_contributions,
        'totals': {
            'predicted_kpi': round(scenario_total, 0),
            'baseline_kpi': round(baseline_total, 0),
            'lift_pct': round(lift_pct, 1),
            'total_spend': round(total_spend, 0),
            'roas': round(roas, 2),
        },
        'media_plan': media_plan,
    }

    # Save
    results_dir = project_path / 'results' / 'scenarios'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / f'{scenario_name}.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def delete_scenario(project_dir: str, scenario_name: str) -> dict[str, Any]:
    """Delete a saved scenario JSON file by name."""
    project_path = Path(project_dir)
    target = project_path / 'results' / 'scenarios' / f'{scenario_name}.json'
    if not target.exists():
        return {'status': 'error', 'message': f'Сценарий «{scenario_name}» не найден'}
    try:
        target.unlink()
        return {'status': 'ok', 'deleted': scenario_name}
    except OSError as e:
        return {'status': 'error', 'message': f'Не удалось удалить: {e}'}


def compare_scenarios(project_dir: str) -> dict[str, Any]:
    """Load and compare all saved scenarios.

    Returns:
        JSON with side-by-side comparison table
    """
    project_path = Path(project_dir)
    scenarios_dir = project_path / 'results' / 'scenarios'

    if not scenarios_dir.exists():
        return {'status': 'error', 'message': 'Нет сохранённых сценариев'}

    scenarios = []
    for f in sorted(scenarios_dir.glob('*.json')):
        with open(f, 'r', encoding='utf-8') as fh:
            scenarios.append(json.load(fh))

    if not scenarios:
        return {'status': 'error', 'message': 'Нет сохранённых сценариев'}

    # Build comparison table
    comparison = {
        'headers': ['Метрика'] + [s['scenario_name'] for s in scenarios],
        'rows': [
            ['Прогноз KPI'] + [s['totals']['predicted_kpi'] for s in scenarios],
            ['Бюджет'] + [s['totals']['total_spend'] for s in scenarios],
            ['ROAS'] + [s['totals']['roas'] for s in scenarios],
            ['Лифт vs baseline'] + [f"+{s['totals']['lift_pct']}%" for s in scenarios],
        ],
    }

    # Best scenario
    best = max(scenarios, key=lambda s: s['totals']['roas'])
    insight = f"Лучший сценарий по ROAS: «{best['scenario_name']}» (ROAS {best['totals']['roas']:.1f}×, лифт +{best['totals']['lift_pct']:.1f}%)."

    return {
        'status': 'ok',
        'scenarios': scenarios,
        'comparison': comparison,
        'insight': insight,
        'best_scenario': best['scenario_name'],
    }
