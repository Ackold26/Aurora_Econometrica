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

from utils.adstock import apply_adstock, geometric_adstock_batch
from utils.saturation import hill_function, hill_function_batch, hill_function_batch_2d
from utils.posterior_propagation import (
    compute_ci_hdi,
    compute_train_adstock_mean_samples,
    load_posterior_samples,
    per_channel_samples,
)


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
    # Phase 1.9: posterior samples → CI on predicted_kpi/roas/lift_pct in totals.
    # None for v1.0/v1.1 pickles → totals stay with point estimates only.
    posterior_samples = load_posterior_samples(model_data)
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
    # Phase 1.1: use posterior mean decay from channel_params['decay'] when v1.2 pickle.
    adstock_config = config_model.get('adstock_config', {})
    adstocked_plan: dict[str, np.ndarray] = {}
    raw_plan: dict[str, np.ndarray] = {}  # Phase 1.1: keep raw for batch CI propagation
    for col in media_cols:
        raw_arr = np.array(media_plan.get(col, [0.0] * n_periods), dtype=float)
        # Pad / truncate to n_periods
        if len(raw_arr) < n_periods:
            raw_arr = np.concatenate([raw_arr, np.zeros(n_periods - len(raw_arr))])
        elif len(raw_arr) > n_periods:
            raw_arr = raw_arr[:n_periods]
        raw_plan[col] = raw_arr
        a_type = adstock_config.get(col, 'geometric')
        decay_point = channel_params.get(col, {}).get('decay')
        adstock_params_override = {'alpha': float(decay_point)} if decay_point is not None else None
        adstocked_plan[col] = apply_adstock(raw_arr, a_type, adstock_params_override)

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
            # C1 fix (audit 2026-04-26): prefer in-model adstock_mean_posterior (v1.2+).
            mean_posterior = p.get('adstock_mean_posterior')
            mean = float(mean_posterior) if mean_posterior is not None else norm['media_means'].get(col, 1)
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

    # Phase 1.9: posterior CI on totals via vectorized per-sample reconstruction.
    # baseline_per_period uses intercept_mean (point) — Phase 1.9 also propagates
    # intercept_samples to make baseline a distribution. Memory: 8000×n_periods×n_channels
    # floats = ~2MB peak per scenario for Kagocel; acceptable, no thinning needed (Vehtari rule).
    # We DON'T persist raw samples per scenario — only summary stats — to avoid RAM blow-up
    # when user creates 5+ scenarios in single session.
    predicted_kpi_ci = None  # tuple (low, high) when computable
    incremental_kpi_ci = None
    roas_native_ci = None
    roas_money_ci = None
    lift_pct_ci = None
    # F1 fix (audit 2026-04-27): load training raw spend per channel for per-sample
    # adstock_mean computation. Required to match in-model `adstock_full[s,:].mean()`
    # normalization when adstock decay varies across posterior draws (Phase 1.1).
    # Conditional load: only when posterior_samples available + at least one geometric
    # channel has decay samples. Defensive — fallback to scalar mean when load fails.
    train_raw_per_channel: dict[str, np.ndarray] = {}
    if posterior_samples is not None and data_file:
        try:
            from utils.merge_rules import apply_merge_rules
            train_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
            apply_merge_rules(train_df, config_model.get('merge_rules'))
            for col in media_cols:
                if col in train_df.columns:
                    train_raw_per_channel[col] = train_df[col].fillna(0).values.astype(float)
        except Exception:
            train_raw_per_channel = {}  # graceful fallback к scalar mean

    if posterior_samples is not None:
        # Audit H1 (2026-04-26): keep defensive try/except для production stability
        # (any numerical edge case in CI math falls back к point estimate без crash),
        # но добавляем structured logger.warning чтобы issues были visible в logs.
        # Pre-fix: silent fallback hid bugs which surfaced только когда client
        # сообщал "почему predicted_kpi_ci всегда null?".
        try:
            n_samples_post = int(posterior_samples['intercept'].shape[0])
            # Sum of media contributions per period × sample → (n_samples, n_periods)
            total_contrib_samples = np.zeros((n_samples_post, n_periods), dtype=np.float64)
            for col in media_cols:
                ch_samples = per_channel_samples(posterior_samples, col)
                if ch_samples is None:
                    continue
                # C1 fix: prefer adstock_mean_posterior for math consistency
                p_ch = channel_params.get(col, {})
                mean_posterior = p_ch.get('adstock_mean_posterior')
                mean = float(mean_posterior) if mean_posterior is not None else (norm['media_means'].get(col, 1) or 1)
                a_type = adstock_config.get(col, 'geometric')
                decay_samples = ch_samples.get('decay')
                if decay_samples is not None and a_type == 'geometric':
                    # Phase 1.1: per-sample adstock varies → Hill on 2D x_norm.
                    x_adstock_2d = geometric_adstock_batch(raw_plan[col], decay_samples)
                    # F1 fix (audit 2026-04-27): per-sample TRAINING adstock mean
                    # (computed from training raw spend × per-sample decay) for math
                    # consistency with in-model normalization. Pre-fix used scalar
                    # `adstock_mean_posterior` for all samples → CI shape distorted
                    # when decay variability high. Same class-of-bug as C1 in samples path.
                    #
                    # A1 audit-of-audit (2026-04-27 second-pass): when training data
                    # unavailable, MUST fall back к scalar mean (training-time stored
                    # `adstock_mean_posterior`). Pre-fix fell back to raw_plan[col]
                    # (scenario data) → normalized scenario by ITSELF, math-incorrect:
                    # x_norm averaged ~1 across samples regardless of how scenario
                    # related к training scale, Hill saturated at constant level →
                    # CI artificially tight. Now: explicit scalar fallback preserves
                    # training-vs-scenario scale relationship correctly.
                    train_raw = train_raw_per_channel.get(col)
                    if train_raw is not None:
                        mean_samples = compute_train_adstock_mean_samples(
                            train_raw, decay_samples, a_type=a_type, fallback_scalar=mean,
                        )
                    else:
                        # Training data unavailable → scalar fallback (NOT scenario plan)
                        mean_samples = mean
                    if isinstance(mean_samples, np.ndarray):
                        denom = np.maximum(mean_samples, 1e-10)[:, None]
                    else:
                        denom = max(float(mean_samples), 1e-10)
                    x_norm_2d = x_adstock_2d / denom
                    sat_samples = hill_function_batch_2d(
                        x_norm_2d, ch_samples['alpha'], ch_samples['gamma']
                    )
                else:
                    # Phase 1.9 fallback: x_norm same across samples (decay constant).
                    x_norm = adstocked_plan[col] / max(mean, 1e-10)
                    sat_samples = hill_function_batch(
                        x_norm, ch_samples['alpha'], ch_samples['gamma']
                    )
                total_contrib_samples += (
                    ch_samples['beta'].reshape(-1, 1).astype(np.float64) * sat_samples
                )

            # baseline distribution: intercept_samples × y_std + y_mean per period
            intercept_samples = np.asarray(posterior_samples['intercept'], dtype=np.float64)
            baseline_per_sample_period = intercept_samples * y_std + y_mean  # (n_samples,)
            # predicted_kpi_samples — per period sum, then sum over periods
            predicted_per_period_samples = (
                baseline_per_sample_period.reshape(-1, 1)
                + total_contrib_samples * y_std
            )  # (n_samples, n_periods)
            predicted_total_samples = predicted_per_period_samples.sum(axis=1)  # (n_samples,)
            baseline_total_samples = baseline_per_sample_period * n_periods  # (n_samples,)
            incremental_total_samples = predicted_total_samples - baseline_total_samples

            _, p_lo, p_hi, _m_p = compute_ci_hdi(predicted_total_samples)
            predicted_kpi_ci = (p_lo, p_hi)
            _, i_lo, i_hi, _m_i = compute_ci_hdi(incremental_total_samples)
            incremental_kpi_ci = (i_lo, i_hi)

            if baseline_total > 0:
                lift_samples = incremental_total_samples / baseline_total_samples * 100
                _, l_lo, l_hi, _m_l = compute_ci_hdi(lift_samples)
                lift_pct_ci = (l_lo, l_hi)
        except Exception as _ci_err:
            # Defensive: any failure in CI computation falls back to point estimates only.
            # H1 (audit 2026-04-26): log warning so issues surface in production logs,
            # not just when client complains. Use exc_info=True для full stack trace.
            import logging as _logging
            _scenario_logger = _logging.getLogger(__name__)
            _scenario_logger.warning(
                f"Scenario CI computation failed (falling back к point estimate only): "
                f"{type(_ci_err).__name__}: {_ci_err}",
                exc_info=True,
            )
            predicted_kpi_ci = None
            incremental_kpi_ci = None
            lift_pct_ci = None

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

    # Phase 1.9: ROAS CI propagation from incremental KPI samples (denominator = scalar spend).
    # C2 fix (audit 2026-04-26): guard против division by near-zero. Pre-fix CI explodes
    # к ±inf когда total_spend_money micro (e.g. user creates "near-zero plan" scenario).
    # Threshold 100₽ — reasonable absolute floor; below this scenario сам по себе degenerate.
    _MIN_SPEND_FOR_ROAS_CI = 100.0
    if incremental_kpi_ci is not None and total_spend_native > _MIN_SPEND_FOR_ROAS_CI:
        roas_native_ci = (incremental_kpi_ci[0] / total_spend_native, incremental_kpi_ci[1] / total_spend_native)
    if incremental_kpi_ci is not None and total_spend_money and total_spend_money > _MIN_SPEND_FOR_ROAS_CI:
        roas_money_ci = (incremental_kpi_ci[0] / total_spend_money, incremental_kpi_ci[1] / total_spend_money)

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
            # Phase 1.9: 90% HDI bounds (None if posterior unavailable / v1.0-v1.1 pickle).
            'predicted_kpi_ci_low': round(predicted_kpi_ci[0], 0) if predicted_kpi_ci else None,
            'predicted_kpi_ci_high': round(predicted_kpi_ci[1], 0) if predicted_kpi_ci else None,
            'incremental_kpi_ci_low': round(incremental_kpi_ci[0], 0) if incremental_kpi_ci else None,
            'incremental_kpi_ci_high': round(incremental_kpi_ci[1], 0) if incremental_kpi_ci else None,
            'roas_ci_low': round(roas_native_ci[0], 2) if roas_native_ci else None,
            'roas_ci_high': round(roas_native_ci[1], 2) if roas_native_ci else None,
            'roas_money_ci_low': round(roas_money_ci[0], 2) if roas_money_ci else None,
            'roas_money_ci_high': round(roas_money_ci[1], 2) if roas_money_ci else None,
            'lift_pct_ci_low': round(lift_pct_ci[0], 1) if lift_pct_ci else None,
            'lift_pct_ci_high': round(lift_pct_ci[1], 1) if lift_pct_ci else None,
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
