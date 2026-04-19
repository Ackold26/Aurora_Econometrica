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
            'media_plan': dict[str, list[float]],  # {channel: [month1, month2, ...]} в native units
            'media_plan_file': str|None,            # Or path to xlsx with plan
            'unit_costs': dict[str, float]|None,    # {channel: ₽/unit}. Ключ для mixed units
                                                    #  (TRP→₽/TRP, рубли→1). Если None — native=money.
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with predicted KPI per period and totals. Включает как native-бюджет
        (`total_spend`, `roas`), так и денежный (`total_spend_money`, `roas_money`) —
        последний рассчитывается когда unit_costs покрывает все каналы. При смешанных
        единицах только `roas_money` имеет смысл для сравнения сценариев.
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
    # Sanitize: отрицательные / NaN unit_costs → отфильтровываются (канал без
    # валидной цены считается не покрытым деньгами, money-mode не включится).
    unit_costs = _sanitize_unit_costs(config.get('unit_costs'))

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

    # Native spend sum (mixed units — informative only, bogus for ROAS across channels)
    per_channel_native = {col: sum(media_plan.get(col, [])) for col in media_cols}
    total_spend_native = sum(per_channel_native.values())
    roas_native = scenario_total / total_spend_native if total_spend_native > 0 else 0

    # Money-denominated spend — only valid if unit_costs cover all active channels
    active_channels = [c for c in media_cols if per_channel_native.get(c, 0) > 0]
    covered = [c for c in active_channels if unit_costs.get(c, 0) > 0]
    per_channel_money = {
        col: per_channel_native[col] * float(unit_costs.get(col, 1.0))
        for col in media_cols
    }
    units_fully_covered = len(covered) == len(active_channels) and len(active_channels) > 0
    total_spend_money = sum(per_channel_money.values()) if units_fully_covered else None
    roas_money = (
        scenario_total / total_spend_money
        if total_spend_money and total_spend_money > 0
        else None
    )

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
            'total_spend': round(total_spend_native, 0),
            'total_spend_money': round(total_spend_money, 0) if total_spend_money else None,
            'roas': round(roas_native, 2),
            'roas_money': round(roas_money, 2) if roas_money else None,
            'units_fully_covered': units_fully_covered,
        },
        'per_channel_spend': {
            'native': {k: round(v, 2) for k, v in per_channel_native.items()},
            'money': {k: round(v, 2) for k, v in per_channel_money.items()} if units_fully_covered else None,
        },
        'unit_costs': unit_costs if unit_costs else None,
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


def _sanitize_unit_costs(raw: dict | None) -> dict:
    """Отфильтровать отрицательные / NaN / нечисленные значения unit_costs."""
    out = {}
    for k, v in (raw or {}).items():
        try:
            val = float(v)
            if val > 0 and val == val:  # NaN-safe
                out[k] = val
        except (TypeError, ValueError):
            pass
    return out


def _migrate_money_fields(data: dict, unit_costs: dict) -> dict:
    """Пересчитать total_spend_money/roas_money для старого scenario.json из media_plan.

    Старые сценарии (session 8-) сохранены без unit_costs → у них только native-ROAS.
    При compare_scenarios передаём текущие project-level unit_costs и мигрируем на лету.
    Файлы на диске НЕ переписываются — миграция только для отображения.
    """
    totals = data.get('totals', {})
    if totals.get('roas_money') is not None:
        return data  # уже мигрирован

    media_plan = data.get('media_plan', {}) or {}
    if not media_plan or not unit_costs:
        return data

    per_channel_native = {col: sum(vals) for col, vals in media_plan.items()}
    active = [c for c in per_channel_native if per_channel_native[c] > 0]
    covered = [c for c in active if unit_costs.get(c, 0) > 0]
    if not active or len(covered) != len(active):
        return data  # не все каналы покрыты — money-mode невозможен

    per_channel_money = {
        col: per_channel_native[col] * float(unit_costs[col]) for col in active
    }
    total_spend_money = sum(per_channel_money.values())
    predicted_kpi = totals.get('predicted_kpi', 0)
    roas_money = predicted_kpi / total_spend_money if total_spend_money > 0 else None

    totals['total_spend_money'] = round(total_spend_money, 0)
    totals['roas_money'] = round(roas_money, 2) if roas_money else None
    totals['units_fully_covered'] = True
    totals['_migrated'] = True  # маркер — legacy-формат, без гарантии совпадения с train
    data['totals'] = totals
    return data


def compare_scenarios(project_dir: str, unit_costs: dict | None = None) -> dict[str, Any]:
    """Load and compare all saved scenarios.

    Args:
        project_dir: путь к проекту
        unit_costs: актуальные стоимости юнитов из проекта. Используются для миграции
                    старых сценариев (session 8-), где не было unit_costs в файле.

    Returns:
        JSON with side-by-side comparison table
    """
    project_path = Path(project_dir)
    scenarios_dir = project_path / 'results' / 'scenarios'

    if not scenarios_dir.exists():
        return {'status': 'error', 'message': 'Нет сохранённых сценариев'}

    uc = _sanitize_unit_costs(unit_costs)

    scenarios = []
    for f in sorted(scenarios_dir.glob('*.json')):
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        scenarios.append(_migrate_money_fields(data, uc))

    if not scenarios:
        return {'status': 'error', 'message': 'Нет сохранённых сценариев'}

    # Use money ROAS if ALL scenarios have it (homogeneous comparison).
    # Mixed native+money across scenarios would be misleading.
    has_money = all(s['totals'].get('roas_money') is not None for s in scenarios)

    if has_money:
        budget_row = ['Бюджет (₽)'] + [s['totals']['total_spend_money'] for s in scenarios]
        roas_row = ['ROAS (₽)'] + [s['totals']['roas_money'] for s in scenarios]
        best = max(scenarios, key=lambda s: s['totals']['roas_money'])
        best_roas = best['totals']['roas_money']
        roas_label = 'ROAS'
    else:
        budget_row = ['Бюджет (native)'] + [s['totals']['total_spend'] for s in scenarios]
        roas_row = ['ROAS (native, смешанные единицы)'] + [s['totals']['roas'] for s in scenarios]
        best = max(scenarios, key=lambda s: s['totals']['roas'])
        best_roas = best['totals']['roas']
        roas_label = 'ROAS (native)'

    comparison = {
        'headers': ['Метрика'] + [s['scenario_name'] for s in scenarios],
        'rows': [
            ['Прогноз KPI'] + [s['totals']['predicted_kpi'] for s in scenarios],
            budget_row,
            roas_row,
            ['Лифт vs baseline'] + [f"+{s['totals']['lift_pct']}%" for s in scenarios],
        ],
        'money_mode': has_money,
    }

    warn = ''
    if not has_money:
        warn = ' ⚠️ Бюджеты в native-единицах (смешанные) — ROAS не сопоставим между сценариями. Укажи стоимость юнита в блоке «Проверка».'

    insight = (
        f"Лучший сценарий по {roas_label}: «{best['scenario_name']}» "
        f"(ROAS {best_roas:.1f}×, лифт +{best['totals']['lift_pct']:.1f}%).{warn}"
    )

    return {
        'status': 'ok',
        'scenarios': scenarios,
        'comparison': comparison,
        'insight': insight,
        'best_scenario': best['scenario_name'],
        'money_mode': has_money,
    }
