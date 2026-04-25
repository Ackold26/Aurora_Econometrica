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

    # P0-1/2/9 fix: pickle compat detection. Old z-score models (no model_version
    # or '1.0') used different normalization → can't be reused with spend/mean engine.
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась — переобучите модель в кабинете "Модель".',
        }

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

    # A1 fix (post-audit v1.2): reject spend on channels that had zero variance
    # during training. Without learned signal, β is from prior (uninformative)
    # and any "prediction" is fabrication. Better honest error than fake numbers.
    untrained_channels = norm.get('untrained_channels', []) or []
    spent_untrained = [
        col for col in untrained_channels
        if any(float(v) > 0 for v in media_plan.get(col, []))
    ]
    if spent_untrained:
        return {
            'status': 'error',
            'error_code': 'UNTRAINED_CHANNEL',
            'message': (
                f'Каналы {spent_untrained} имели нулевую вариативность в данных обучения '
                f'(модель не училась на них). Сценарий с тратами на эти каналы дал бы '
                f'фиктивные предсказания из априорного распределения. '
                f'Уберите их из медиаплана либо переобучите модель с реальными данными.'
            ),
            'untrained_channels': spent_untrained,
        }

    # F6+F7 fix (math-audit v1.3): single-period media_plan from UI what-if was
    # zero-padded to training n_periods → effective spend = single-period only,
    # contribution tiny, predicted_kpi ≈ baseline regardless of slider. Now: if
    # plan length == 1, treat scalar as TOTAL annual spend и distribute evenly
    # across training n_periods (matches optimizer flat-alloc semantics + training).
    plan_n = max(len(v) for v in media_plan.values()) if media_plan else 0
    if plan_n == 0:
        return {'status': 'error', 'message': 'Медиаплан не содержит данных'}

    # Determine reference n_periods from training data (length of df).
    data_file = config_model.get('data_file')
    training_n_periods = plan_n
    if data_file and plan_n == 1:
        try:
            ref_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
            training_n_periods = max(len(ref_df), 1)
            # Distribute single-period (total) spend evenly across training periods
            for col in list(media_plan.keys()):
                if len(media_plan[col]) == 1:
                    total_for_channel = float(media_plan[col][0])
                    media_plan[col] = [total_for_channel / training_n_periods] * training_n_periods
        except Exception:
            # Fallback: keep original plan, n_periods=1
            training_n_periods = plan_n
    n_periods = max(training_n_periods, plan_n)

    # P1-5 fix: apply adstock to scenario media plan matching training-time
    # transformation. Pre-fix, scenario received raw spend_t straight to Hill,
    # missing carryover / delayed-effect channels (TV/OOH undercounted).
    adstock_config = config_model.get('adstock_config', {})
    adstocked_plan: dict[str, np.ndarray] = {}
    for col in media_cols:
        raw_arr = np.array(media_plan.get(col, [0.0] * n_periods), dtype=float)
        # Pad / truncate to n_periods
        if len(raw_arr) < n_periods:
            raw_arr = np.concatenate([raw_arr, np.zeros(n_periods - len(raw_arr))])
        elif len(raw_arr) > n_periods:
            raw_arr = raw_arr[:n_periods]
        a_type = adstock_config.get(col, 'geometric')
        adstocked_plan[col] = apply_adstock(raw_arr, a_type)

    # P1-3 fix: baseline = intercept × y_std + y_mean per period (intercept-based
    # counterfactual), not y_mean × n_periods (which excluded model bias).
    # Controls treated as average (z-scored mean=0 → control_effect=0 in absence
    # of scenario-period control values).
    intercept_mean = float(norm.get('intercept_mean', 0.0))
    y_std = float(norm['y_std'])
    y_mean = float(norm['y_mean'])
    baseline_per_period = intercept_mean * y_std + y_mean

    # Predict per period using adstocked spend
    predictions = []
    channel_contributions = {col: [] for col in media_cols}

    for t in range(n_periods):
        total_effect = 0
        for col in media_cols:
            p = channel_params[col]
            spend_t_adstock = float(adstocked_plan[col][t])
            # P0-1/2/9 fix: spend/mean Robyn-style normalization matching training.
            mean = norm['media_means'].get(col, 1)
            x_norm = spend_t_adstock / max(mean, 1e-10) if mean > 0 else 0

            # Saturate (B1 fix: unified gamma floor 1e-6 across modeler/scenario/optimizer/decomposer)
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
            contribution = p['beta'] * sat[0]
            total_effect += contribution
            channel_contributions[col].append(round(float(contribution * y_std), 0))

        # P1-3: predicted = baseline + media contribution (was: total_effect × y_std + y_mean)
        predicted = baseline_per_period + total_effect * y_std
        predictions.append(round(float(predicted), 0))

    baseline_total = baseline_per_period * n_periods
    scenario_total = sum(predictions)
    incremental_total = scenario_total - baseline_total
    lift_pct = (incremental_total / baseline_total * 100) if baseline_total else 0

    # Native spend sum (mixed units — informative only, bogus for ROAS across channels)
    per_channel_native = {col: sum(media_plan.get(col, [])) for col in media_cols}
    total_spend_native = sum(per_channel_native.values())

    # P1-4 fix: PRIMARY ROAS = incremental / spend (industry standard MMM).
    # Legacy total ROAS (= scenario_total / spend) kept under '_total' suffix for
    # backward compat with old scenario.json files и downstream consumers.
    roas_native = incremental_total / total_spend_native if total_spend_native > 0 else 0
    roas_native_total = scenario_total / total_spend_native if total_spend_native > 0 else 0

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
        incremental_total / total_spend_money
        if total_spend_money and total_spend_money > 0
        else None
    )
    roas_money_total = (
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
            'incremental_kpi': round(incremental_total, 0),  # P1-4: incremental as primary
            'lift_pct': round(lift_pct, 1),
            'total_spend': round(total_spend_native, 0),
            'total_spend_money': round(total_spend_money, 0) if total_spend_money else None,
            # P1-4: primary ROAS = incremental / spend (industry-standard MMM)
            'roas': round(roas_native, 2),
            'roas_money': round(roas_money, 2) if roas_money else None,
            # Legacy total ROAS (scenario_total / spend) — back-compat
            'roas_total': round(roas_native_total, 2),
            'roas_money_total': round(roas_money_total, 2) if roas_money_total else None,
            'units_fully_covered': units_fully_covered,
            'roas_method': 'incremental',  # explicit semantic marker
        },
        'per_channel_spend': {
            'native': {k: round(v, 2) for k, v in per_channel_native.items()},
            'money': {k: round(v, 2) for k, v in per_channel_money.items()} if units_fully_covered else None,
        },
        'unit_costs': unit_costs if unit_costs else None,
        'media_plan': media_plan,
        'model_version': model_version,  # for downstream UI badge
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

    P1-4 fix (2026-04-25): новые scenarios save 'roas_money' как INCREMENTAL.
    Старые scenarios saved 'roas_money' как TOTAL. Для consistency в comparison
    также экспортируем roas_money_incremental для legacy если baseline_kpi есть.
    """
    totals = data.get('totals', {})
    media_plan = data.get('media_plan', {}) or {}
    has_money = totals.get('roas_money') is not None

    if not has_money and media_plan and unit_costs:
        per_channel_native = {col: sum(vals) for col, vals in media_plan.items()}
        active = [c for c in per_channel_native if per_channel_native[c] > 0]
        covered = [c for c in active if unit_costs.get(c, 0) > 0]
        if active and len(covered) == len(active):
            per_channel_money = {
                col: per_channel_native[col] * float(unit_costs[col]) for col in active
            }
            total_spend_money = sum(per_channel_money.values())
            predicted_kpi = totals.get('predicted_kpi', 0)
            baseline_kpi = totals.get('baseline_kpi', 0)
            # Legacy old code computed roas as total/spend; preserve to keep
            # backward-compat field semantic where it was already saved.
            roas_money = predicted_kpi / total_spend_money if total_spend_money > 0 else None
            totals['total_spend_money'] = round(total_spend_money, 0)
            totals['roas_money'] = round(roas_money, 2) if roas_money else None
            # Add explicit incremental if we can derive it (post-P1-4)
            if baseline_kpi and total_spend_money > 0:
                inc = (predicted_kpi - baseline_kpi) / total_spend_money
                totals['roas_money_incremental'] = round(inc, 2)
            totals['units_fully_covered'] = True
            totals['_migrated'] = True
            totals.setdefault('roas_method', 'total')  # legacy default

    # If post-P1-4 saved scenario, roas_method='incremental' уже установлен.
    # Если legacy без roas_method — помечаем как 'total' для UI badge.
    totals.setdefault('roas_method', 'total')
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
