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


def _safe_int_or_none(v: Any) -> int | None:
    """Coerce v к int если possible, иначе None. Used для frontend-provided
    optional integer fields (forecast_periods) where invalid input должен
    gracefully degrade instead of crashing scenario.json serialization."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def predict_scenario(config: dict, project_dir: str) -> dict[str, Any]:
    """Predict KPI for a given media plan scenario.

    Args:
        config: {
            'scenario_name': str,
            'media_plan': dict[str, list[float]],  # {channel: [month1, month2, ...]} в native units
            'media_plan_file': str|None,            # Or path to xlsx with plan
            'unit_costs': dict[str, float]|None,    # {channel: ₽/unit}. Ключ для mixed units
                                                    #  (TRP→₽/TRP, рубли→1). Если None - native=money.
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with predicted KPI per period and totals. Включает как native-бюджет
        (`total_spend`, `roas`), так и денежный (`total_spend_money`, `roas_money`) -
        последний рассчитывается когда unit_costs покрывает все каналы. При смешанных
        единицах только `roas_money` имеет смысл для сравнения сценариев.
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель в кабинете «Данные и Модель».',
        }

    # Trust Level 3: централизованный pickle compat helper.
    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(model_path)

    # P0-1/2/9 fix: pickle compat detection. Old z-score models (no model_version
    # or '1.0') used different normalization → can't be reused with spend/mean engine.
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась - переобучите модель в кабинете "Модель".',
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
    # CI fix 2026-05-24 (D3): tracking original raw keys (user-attempted unit_costs)
    # для exclusion из _is_money_channel default-monetary fallback. Если user provided
    # invalid unit_cost (negative/NaN), это explicit signal что channel физический и
    # требует валидный unit_cost — не должен auto-cover'иться как default-monetary.
    _raw_unit_costs_attempted = set((config.get('unit_costs') or {}).keys())
    unit_costs = _sanitize_unit_costs(config.get('unit_costs'))

    # Phase 2 audit pass 4 - per-channel inflation. Если customer задал годовой
    # темп инфляции CPP/CPM, scenario money conversion использует weighted-
    # average training cost (не current). ROI остаётся согласованным с decomposer.
    inflation_pct_per_channel = config.get('unit_cost_inflation_pct')
    if inflation_pct_per_channel and unit_costs:
        try:
            from utils.merge_rules import apply_merge_rules
            data_file = config_model.get('data_file')
            if data_file:
                _train_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
                apply_merge_rules(_train_df, config_model.get('merge_rules'))
                from utils.unit_cost_inflation import apply_inflation_to_unit_costs
                unit_costs = apply_inflation_to_unit_costs(
                    unit_costs=unit_costs,
                    inflation_pct_per_channel=inflation_pct_per_channel,
                    df=_train_df,
                    date_column=config_model.get('date_column', 'date'),
                )
        except Exception as _infl_err:
            # Phase 3 audit fix: previously silent - surfaces logged warning так
            # что customer-side issue с inflation_pct config debuggable. Fallback
            # behavior unchanged (current_cost preserved).
            import logging as _logging
            _logging.getLogger('econometrica').warning(
                f"Scenario inflation adjustment failed (falling back к current "
                f"unit_costs): {type(_infl_err).__name__}: {_infl_err}",
                exc_info=True,
            )

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
        return {
            'status': 'error',
            'error_code': 'MEDIA_PLAN_EMPTY',
            'message': 'Медиаплан пуст. Укажите бюджеты по каналам.',
        }

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
        return {
            'status': 'error',
            'error_code': 'MEDIA_PLAN_EMPTY',
            'message': 'Медиаплан не содержит данных.',
        }

    # Determine reference n_periods from training data (length of df).
    # Phase 2 (audit pass 4 2026-05-02): когда config['forecast_periods'] задан,
    # single-period mediaPlan totals распределяются по forecast_periods (не
    # training_n_periods). Matches optimizer planning mode semantics - scenario
    # отражает «бюджет 2026 года», не «бюджет training horizon».
    # C3-N3 (2026-07-03): протухший абсолютный путь из pickle → фолбэк на файл
    # с тем же именем в каталоге проекта; при полном отсутствии — None (мягкие
    # ветки ниже уже умеют жить без него, с логированной деградацией).
    try:
        from utils.data_file_resolver import resolve_data_file
        data_file = str(resolve_data_file(config_model.get('data_file'), project_dir))
    except FileNotFoundError:
        data_file = None
    forecast_periods_cfg = config.get('forecast_periods')
    training_n_periods = plan_n
    if data_file and plan_n == 1:
        try:
            ref_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
            training_n_periods = max(len(ref_df), 1)
        except Exception:
            training_n_periods = plan_n

        # Distribution length: forecast (planning mode) > training fallback
        try:
            distribution_n = int(forecast_periods_cfg) if forecast_periods_cfg is not None else training_n_periods
            if distribution_n < 1:
                distribution_n = training_n_periods
        except (TypeError, ValueError):
            distribution_n = training_n_periods

        # Distribute single-period (total) spend evenly across distribution_n periods.
        for col in list(media_plan.keys()):
            if len(media_plan[col]) == 1:
                total_for_channel = float(media_plan[col][0])
                media_plan[col] = [total_for_channel / distribution_n] * distribution_n
    n_periods = max(training_n_periods, plan_n)
    # When planning mode active, n_periods reflects forecast horizon for downstream
    # adstock series + Hill summation (per-period semantics already in scenario engine).
    if forecast_periods_cfg is not None and plan_n == 1:
        try:
            forecast_n = int(forecast_periods_cfg)
            if forecast_n >= 1:
                # v2.1.0 (pilot E P0-2 2026-05-17): enforce horizon cap symmetrically
                # с optimizer (см. optimizer.py:398-419). Без этого scenario engine
                # обходил FORECAST_HORIZON_TOO_LONG safety gate через ScenarioPlayground
                # save flow и распределял media_plan по любому n_periods.
                try:
                    from engines.persistence import get_kpi_type
                    from utils.forecast_validation import get_forecast_horizon_max_multiplier
                    _kpi_type = get_kpi_type(model_data)
                    _max_mult = get_forecast_horizon_max_multiplier(_kpi_type)
                    _max_horizon = int(training_n_periods * _max_mult)
                    if forecast_n > _max_horizon:
                        return {
                            'status': 'error',
                            'error_code': 'FORECAST_HORIZON_TOO_LONG',
                            'message': (
                                f'Период сценария ({forecast_n}) превышает '
                                f'обучающий горизонт более чем в {_max_mult:.1f}× '
                                f'({_max_horizon}). Допущение стационарности '
                                f'коэффициентов нарушено. Переучите модель на '
                                f'расширенных данных или сократите горизонт.'
                            ),
                        }
                except ImportError:
                    pass  # legacy fallback - проверка disabled
                n_periods = forecast_n
        except (TypeError, ValueError):
            pass

    # P1-5 fix: apply adstock to scenario media plan matching training-time
    # transformation. Pre-fix, scenario received raw spend_t straight to Hill,
    # missing carryover / delayed-effect channels (TV/OOH undercounted).
    # Phase 1.1: use posterior mean decay from channel_params['decay'] when v1.2 pickle.
    adstock_config = config_model.get('adstock_config', {})
    adstocked_plan: dict[str, np.ndarray] = {}
    raw_plan: dict[str, np.ndarray] = {}  # Phase 1.1: keep raw for batch CI propagation
    # v2.1.0 (ADR-020): training-time uc snapshot для pre-multiply media plan ДО
    # adstock+hill. Иначе scenario с TRPs каналом даёт x_norm в 120000× меньше
    # training-equivalent → wrong predicted KPI.
    unit_costs_applied_at_training = bool(model_data.get('unit_costs_applied_at_training'))
    unit_costs_snapshot_train: dict[str, float] = (
        model_data.get('unit_costs_snapshot') or {}
    ) if unit_costs_applied_at_training else {}

    # v2.1.0 (ADR-021 pilot B2/E2 round 2 R2-1 2026-05-17): kpi_unit_cost для
    # money equivalents в scenario totals. Mirror того что optimizer.py делает.
    # Override > pickle snapshot > None (legacy native KPI units). Без этого
    # backend silently ignored IPC payload kpi_unit_cost - count KPI scenarios
    # хранились native count без money conversion.
    _kpi_uc_override = config.get('kpi_unit_cost')
    if _kpi_uc_override is not None and float(_kpi_uc_override) > 0:
        kpi_unit_cost = float(_kpi_uc_override)
    else:
        _snap = model_data.get('kpi_unit_cost_snapshot')
        kpi_unit_cost = float(_snap) if _snap is not None and float(_snap) > 0 else None
    # Detect kpi_kind (same resolver chain как в decomposer/optimizer).
    _kpi_kind_cfg = (config_model.get('kpi_kind') or '').lower()
    if _kpi_kind_cfg in ('count', 'monetary'):
        kpi_kind_scenario = _kpi_kind_cfg
    else:
        _count_types = {
            'sales_packs', 'leads', 'registrations', 'loyalty_cards',
            'subscriptions', 'app_installs', 'count_custom',
        }
        _monetary_types = {'sales', 'revenue', 'profit'}
        _kpi_type_cfg = (config_model.get('kpi_type') or '').lower()
        if _kpi_type_cfg in _count_types:
            kpi_kind_scenario = 'count'
        elif _kpi_type_cfg in _monetary_types:
            kpi_kind_scenario = 'monetary'
        else:
            try:
                from utils.column_detection import classify_column
                _kpi_col_classify = classify_column(config_model.get('kpi_column', '') or '')
                kpi_kind_scenario = 'count' if _kpi_col_classify == 'target_count' else 'monetary'
            except Exception:
                kpi_kind_scenario = 'monetary'

    for col in media_cols:
        raw_arr = np.array(media_plan.get(col, [0.0] * n_periods), dtype=float)
        # Pad / truncate to n_periods
        if len(raw_arr) < n_periods:
            raw_arr = np.concatenate([raw_arr, np.zeros(n_periods - len(raw_arr))])
        elif len(raw_arr) > n_periods:
            raw_arr = raw_arr[:n_periods]
        raw_plan[col] = raw_arr
        # v2.1.0 (ADR-020): pre-multiply через uc_train для Hill symmetry.
        uc_train_col = float(unit_costs_snapshot_train.get(col, 1.0) or 1.0)
        scaled_arr = raw_arr * uc_train_col if uc_train_col != 1.0 else raw_arr
        a_type = adstock_config.get(col, 'geometric')
        decay_point = channel_params.get(col, {}).get('decay')
        adstock_params_override = {'alpha': float(decay_point)} if decay_point is not None else None
        adstocked_plan[col] = apply_adstock(scaled_arr, a_type, adstock_params_override)

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

    # ─── Phase 2.7 (5a): Canonical lift% formula (2026-05-04 / SSOT 2026-05-24) ─
    # Pre-fix: lift = incremental / baseline_only - denominator excluded current
    # media contribution → ratio inflated when media >> baseline.
    # Frontend predictKPI uses (scenario_total - current_total) / current_total
    # → расхождение с UI scenarios block. Optimizer also misaligned (5a fix).
    # Now: canonical formula across optimizer + scenario + frontend = total KPI ratio.
    # Compute current_total_kpi = baseline + media_at_current_spend (same Hill).
    # Selection logic (y_std degeneracy, AURORA_LEGACY_LIFT_FORMULA env, baseline_zero
    # fallback) живёт в engines/lift.py SSOT — identical semantics к optimizer.py call.
    # Legacy `lift_pct_baseline_only` preserved as result field + fallback path.
    from engines.lift import (
        select_lift_pct as _select_lift_pct,
        is_y_std_degenerate as _is_y_std_degenerate,
        is_legacy_env_active as _is_legacy_env_active,
    )
    import logging as _scn_logging
    _scn_logger = _scn_logging.getLogger(__name__)
    # Sprint Buffer #45 (2026-05-23): distinguish baseline_total==0 (pure-media-model edge
    # case — modeller обнулил intercept или brand baseline degenerate) от positive baseline.
    # Pre-fix: silent fallback к 0 maskировал bug class где модель тренировалась на dataset
    # где KPI почти полностью объясняется media variables — диагностически important для
    # operator (signal к пересмотру model spec / control variables).
    if not baseline_total:
        _scn_logger.warning(
            'scenario legacy_lift_pct: baseline_total=%s (incremental_total=%s) → degenerate '
            'pure-media-model edge case, legacy_lift_pct forced к 0. Canonical formula продолжит '
            'работать через current_total_kpi reconstruction. Operator: проверить intercept prior + '
            'control variables в model spec.',
            baseline_total, round(float(incremental_total), 2),
        )
        legacy_lift_pct = 0
    else:
        legacy_lift_pct = incremental_total / baseline_total * 100

    y_std_degenerate = _is_y_std_degenerate(y_std)
    if y_std_degenerate:
        _scn_logger.warning(
            "scenario lift: y_std degenerate (%s) - canonical formula falls back к legacy ratio.",
            y_std,
        )

    # Reconstruct current_total_kpi using same Hill+adstock pipeline as scenario.
    # Current per-period spend = (sum spend column over training) / n_periods (flat avg).
    current_total_kpi = baseline_total  # initialize в degenerate case (logged below if used)
    canonical_reconstruction_ok = False
    if data_file and not y_std_degenerate:
        try:
            cur_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
            from utils.merge_rules import apply_merge_rules as _apply_merge
            _apply_merge(cur_df, config_model.get('merge_rules'))
            current_predictions = []
            current_per_period_spend = {
                col: float(cur_df[col].fillna(0).sum()) / n_periods
                for col in media_cols if col in cur_df.columns
            }
            # Single-period flat allocation → adstock series.
            current_adstocked = {}
            for col in media_cols:
                avg_per_period = current_per_period_spend.get(col, 0.0)
                raw_arr = np.full(n_periods, avg_per_period, dtype=float)
                # v2.1.0 (ADR-020): pre-multiply через uc_train для canonical lift symmetry.
                uc_train_col_lift = float(unit_costs_snapshot_train.get(col, 1.0) or 1.0)
                scaled_arr = raw_arr * uc_train_col_lift if uc_train_col_lift != 1.0 else raw_arr
                a_type = adstock_config.get(col, 'geometric')
                decay_point = channel_params.get(col, {}).get('decay')
                params_override = {'alpha': float(decay_point)} if decay_point is not None else None
                current_adstocked[col] = apply_adstock(scaled_arr, a_type, params_override)
            for t in range(n_periods):
                cur_total_effect = 0.0
                for col in media_cols:
                    p = channel_params[col]
                    spend_t_adstock = float(current_adstocked[col][t])
                    mp = p.get('adstock_mean_posterior')
                    mean = float(mp) if mp is not None else norm['media_means'].get(col, 1)
                    x_norm = spend_t_adstock / max(mean, 1e-10) if mean > 0 else 0
                    sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
                    cur_total_effect += p['beta'] * sat[0]
                current_predictions.append(baseline_per_period + cur_total_effect * y_std)
            current_total_kpi = float(sum(current_predictions))
            canonical_reconstruction_ok = True
        except Exception as _e_lift:
            # AUDIT fix: explicit log при fallback (was silent - debugging customer
            # reports stuck on degenerate canonical lift).
            _scn_logger.warning(
                "scenario lift canonical reconstruction failed (data_file=%s): %s. "
                "Falling back к legacy formula. Customer-facing lift_pct may не align с optimizer.",
                data_file, _e_lift,
            )
            current_total_kpi = baseline_total
    elif not data_file:
        _scn_logger.info(
            "scenario lift: data_file missing in config - canonical reconstruction skipped, "
            "using legacy formula. Common in v1.0/v1.1 legacy pickles."
        )

    # SSOT formula application — engines/lift.py.
    # When reconstruction succeeded → canonical formula on (scenario_total, current_total) ratio.
    # When failed/skipped (or y_std degenerate, or AURORA_LEGACY_LIFT_FORMULA=1)
    # → SSOT helper resolves к legacy ratio (incremental / baseline_only).
    if canonical_reconstruction_ok:
        lift_pct, _lift_diag = _select_lift_pct(
            total_optimal_kpi=scenario_total,
            total_current_kpi=current_total_kpi,
            legacy_fallback_pct=legacy_lift_pct,
            y_std=y_std,
        )
    else:
        # Reconstruction failed/skipped — canonical undefined без current_total_kpi.
        # Legacy formula = lift_pct unconditionally (env override would только swap
        # legacy↔canonical, и canonical здесь не computable).
        lift_pct = legacy_lift_pct

    # Phase 1.9: posterior CI on totals via vectorized per-sample reconstruction.
    # baseline_per_period uses intercept_mean (point) - Phase 1.9 also propagates
    # intercept_samples to make baseline a distribution. Memory: 8000×n_periods×n_channels
    # floats = ~2MB peak per scenario for Kagocel; acceptable, no thinning needed (Vehtari rule).
    # We DON'T persist raw samples per scenario - only summary stats - to avoid RAM blow-up
    # when user creates 5+ scenarios in single session.
    predicted_kpi_ci = None  # tuple (low, high) when computable
    incremental_kpi_ci = None
    roas_native_ci = None
    roas_money_ci = None
    lift_pct_ci = None
    predictions_ci_low = None   # per-period 90% HDI band (forecast fan) для MultiScenarioChart
    predictions_ci_high = None  # None когда posterior недоступен (v1.0-v1.1 pickle)
    # F1 fix (audit 2026-04-27): load training raw spend per channel for per-sample
    # adstock_mean computation. Required to match in-model `adstock_full[s,:].mean()`
    # normalization when adstock decay varies across posterior draws (Phase 1.1).
    # Conditional load: only when posterior_samples available + at least one geometric
    # channel has decay samples. Defensive - fallback to scalar mean when load fails.
    train_raw_per_channel: dict[str, np.ndarray] = {}
    if posterior_samples is not None and data_file:
        try:
            from utils.merge_rules import apply_merge_rules
            train_df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
            apply_merge_rules(train_df, config_model.get('merge_rules'))
            for col in media_cols:
                if col in train_df.columns:
                    # v2.1.0 (ADR-020): pre-multiply через uc_train для symmetry с
                    # in-model adstock_full normalization (mean считалась в scaled scale).
                    _arr = train_df[col].fillna(0).values.astype(float)
                    _uc_t = float(unit_costs_snapshot_train.get(col, 1.0) or 1.0)
                    if _uc_t != 1.0 and _uc_t > 0:
                        _arr = _arr * _uc_t
                    train_raw_per_channel[col] = _arr
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
                    # v2.1.0 (ADR-020): pre-multiply через uc_train ДО adstock_batch
                    # для Hill symmetry с training scale.
                    _uc_train_col = float(unit_costs_snapshot_train.get(col, 1.0) or 1.0)
                    _raw_for_batch = raw_plan[col] * _uc_train_col if _uc_train_col != 1.0 else raw_plan[col]
                    x_adstock_2d = geometric_adstock_batch(_raw_for_batch, decay_samples)
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
            # predicted_kpi_samples - per period sum, then sum over periods
            predicted_per_period_samples = (
                baseline_per_sample_period.reshape(-1, 1)
                + total_contrib_samples * y_std
            )  # (n_samples, n_periods)
            predicted_total_samples = predicted_per_period_samples.sum(axis=1)  # (n_samples,)
            baseline_total_samples = baseline_per_sample_period * n_periods  # (n_samples,)
            incremental_total_samples = predicted_total_samples - baseline_total_samples

            _, p_lo, p_hi, _m_p = compute_ci_hdi(predicted_total_samples)
            predicted_kpi_ci = (p_lo, p_hi)

            # Per-period CI band (forecast fan) — reuse predicted_per_period_samples
            # (n_samples, n_periods). Питает CI-веер MultiScenarioChart. Тот же HDI-метод,
            # что и скалярный predicted_kpi_ci → единый источник честности (INV-50).
            # NB: HDI суммы ≠ сумма по-периодных HDI — band показывает неопределённость
            # КАЖДОГО месяца, скаляр — годового тотала; это разные (обе валидные) меры.
            _pp_low: list[float] = []
            _pp_high: list[float] = []
            for _t in range(n_periods):
                _, _pp_lo, _pp_hi, _m_pp = compute_ci_hdi(predicted_per_period_samples[:, _t])
                _pp_low.append(round(float(_pp_lo), 0))
                _pp_high.append(round(float(_pp_hi), 0))
            predictions_ci_low = _pp_low
            predictions_ci_high = _pp_high
            _, i_lo, i_hi, _m_i = compute_ci_hdi(incremental_total_samples)
            incremental_kpi_ci = (i_lo, i_hi)

            # 5a (2026-05-04): canonical lift CI uses (scenario - current_total_kpi) / current_total_kpi.
            # AUDIT fix 2026-05-04: pre-fix mixed scalar (current_media_total point estimate)
            # с vector baseline_total_samples → degenerate CI when baseline variance large
            # vs media. Также `max(diff, 0.0)` silently hide negative-media reconstruction
            # bug. Now: при canonical reconstruction OK - use point estimate (warning-only,
            # tighter assumptions); при reconstruction failed - fallback к legacy CI.
            # Если current_total_kpi == baseline_total (data_file fail), canonical CI degenerates;
            # use legacy.
            current_media_total = current_total_kpi - baseline_total  # may be ≥0 OR slightly <0
            if not canonical_reconstruction_ok or current_media_total < -1.0:
                # Reconstruction failed OR negative media (anomaly worth surfacing) → legacy CI.
                if current_media_total < -1.0:
                    _scn_logger.warning(
                        "scenario lift CI: current_media_total=%s < 0 - reconstruction yielded "
                        "negative media contribution. Falling back к legacy CI formula.",
                        current_media_total,
                    )
                if baseline_total > 0:
                    lift_samples = incremental_total_samples / baseline_total_samples * 100
                    _, l_lo, l_hi, _m_l = compute_ci_hdi(lift_samples)
                    lift_pct_ci = (l_lo, l_hi)
            elif _is_legacy_env_active():
                if baseline_total > 0:
                    lift_samples = incremental_total_samples / baseline_total_samples * 100
                    _, l_lo, l_hi, _m_l = compute_ci_hdi(lift_samples)
                    lift_pct_ci = (l_lo, l_hi)
            else:
                # Canonical: (scenario - current_total) / current_total per sample.
                # current_total_samples = per-sample baseline + point-estimate media.
                # Acceptable: current spend fixed → media estimate variance much smaller
                # than baseline posterior variance, so per-sample baseline dominates CI width.
                current_total_samples = baseline_total_samples + max(current_media_total, 0.0)
                with np.errstate(divide='ignore', invalid='ignore'):
                    lift_samples = np.where(
                        current_total_samples > 1e-9,
                        (predicted_total_samples - current_total_samples) / current_total_samples * 100,
                        0.0,
                    )
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
            predictions_ci_low = None
            predictions_ci_high = None

    # Native spend sum (mixed units - informative only, bogus for ROAS across channels)
    per_channel_native = {col: sum(media_plan.get(col, [])) for col in media_cols}
    total_spend_native = sum(per_channel_native.values())

    # P1-4 fix: PRIMARY ROAS = incremental / spend (industry standard MMM).
    # Legacy total ROAS (= scenario_total / spend) kept under '_total' suffix for
    # backward compat with old scenario.json files и downstream consumers.
    roas_native = incremental_total / total_spend_native if total_spend_native > 0 else 0
    roas_native_total = scenario_total / total_spend_native if total_spend_native > 0 else 0

    # Money-denominated spend - only valid if unit_costs cover all active channels
    # F-019 fix (2026-05-18 pilot): money-каналы (per_channel_input[ch]=='monetary')
    # уже в ₽ — implicit unit_cost=1.0. Backend требует ИЛИ explicit unit_cost > 0
    # (для physical TRP/GRP/CPM channels) ИЛИ classification 'monetary' в pickle SSOT.
    # Pre-fix: backend требовал explicit > 0 для всех каналов → money channels без
    # unit_cost ломали units_fully_covered → False money_mode → warning «native единицы»
    # при том что ROAS математически в ₽ для них корректен (1.0 fallback в per_channel_money).
    #
    # F-019 hardening (audit 2026-05-18): auto-cover money channels только если
    # юзер интенциально задал хотя бы один unit_cost. Полностью пустой
    # unit_costs={} = legacy pickle где per_channel_input default-monetary мог
    # быть wrong (TRP без unit_cost получил бы false-positive money_mode →
    # silent ROAS corruption). При unit_costs={} keep strict pre-F-019 behavior.
    per_channel_input = model_data.get('per_channel_input') or {}
    has_explicit_unit_costs = any(v > 0 for v in unit_costs.values())
    def _is_money_channel(ch: str) -> bool:
        if not has_explicit_unit_costs:
            return False  # legacy pickle protection
        # CI fix 2026-05-24 (D3): channel что user attempted unit_cost для (но был
        # filtered как invalid negative/NaN) НЕ должен auto-cover'иться через default
        # 'monetary' fallback — user intent сигнализирует physical channel needing
        # explicit unit_cost.
        if ch in _raw_unit_costs_attempted and ch not in unit_costs:
            return False
        return per_channel_input.get(ch, 'monetary') == 'monetary'
    active_channels = [c for c in media_cols if per_channel_native.get(c, 0) > 0]
    covered = [
        c for c in active_channels
        if unit_costs.get(c, 0) > 0 or _is_money_channel(c)
    ]
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
    # Threshold 100₽ - reasonable absolute floor; below this scenario сам по себе degenerate.
    _MIN_SPEND_FOR_ROAS_CI = 100.0
    if incremental_kpi_ci is not None and total_spend_native > _MIN_SPEND_FOR_ROAS_CI:
        roas_native_ci = (incremental_kpi_ci[0] / total_spend_native, incremental_kpi_ci[1] / total_spend_native)
    if incremental_kpi_ci is not None and total_spend_money and total_spend_money > _MIN_SPEND_FOR_ROAS_CI:
        roas_money_ci = (incremental_kpi_ci[0] / total_spend_money, incremental_kpi_ci[1] / total_spend_money)

    scenario_name = config.get('scenario_name', 'custom')

    # ── Мат-аудит 2026-07-02 (F-04): маркер экстраполяции сценария ────────────
    # Machinery экстраполяции существовала (extrapolation_severity, endpoint
    # /compute/forecast-scaling ~12ms), но до пользователя сценариев не доходила
    # (endpoint не подключён к UI, движок план не помечал). Честность INV-50
    # живёт в движке: сценарий сам помечает выход per-period плана за
    # наблюдавшийся диапазон трат канала — канонические тиры p95/p99
    # (Chan & Perry 2017 Fig. 2: кривая отклика вне наблюдённого диапазона
    # не идентифицируется данными). Сбой контура → None, сценарий не роняем.
    extrapolation = None
    try:
        from utils.forecast_validation import extrapolation_severity
        _data_file_ex = config_model.get('data_file')
        if _data_file_ex:
            _hist_df = (pd.read_excel(_data_file_ex)
                        if str(_data_file_ex).endswith(('.xlsx', '.xls'))
                        else pd.read_csv(_data_file_ex))
            try:
                from utils.merge_rules import apply_merge_rules as _amr_ex
                _amr_ex(_hist_df, config_model.get('merge_rules'))
            except Exception:  # noqa: BLE001 - merge_rules опциональны
                pass
            _channels_ex = []
            _max_sev = 0
            for _col in media_cols:
                _plan_vals = media_plan.get(_col)
                if not _plan_vals or _col not in _hist_df.columns:
                    continue
                _peak = max((float(v or 0) for v in _plan_vals), default=0.0)
                if _peak <= 0:
                    continue
                _hist = _hist_df[_col].fillna(0).to_numpy(dtype=float)
                _hist_pos = _hist[_hist > 0]
                if _hist_pos.size == 0:
                    continue
                _q = {
                    'p95': float(np.quantile(_hist_pos, 0.95)),
                    'p99': float(np.quantile(_hist_pos, 0.99)),
                }
                _sev = extrapolation_severity(_peak, _q)
                _max_sev = max(_max_sev, _sev)
                if _sev > 0:
                    _hmax = float(_hist.max())
                    _channels_ex.append({
                        'name': _col,
                        'peak_per_period_native': round(_peak, 2),
                        'hist_max_native': round(_hmax, 2),
                        'ratio_vs_max': round(_peak / _hmax, 2) if _hmax > 0 else None,
                        'severity': _sev,
                    })
            extrapolation = {'severity': _max_sev, 'channels': _channels_ex}
    except Exception:  # noqa: BLE001 - honesty-контур не роняет сценарий
        extrapolation = None

    result = {
        'status': 'ok',
        'scenario_name': scenario_name,
        'n_periods': n_periods,
        'predictions': predictions,
        # Per-period 90% HDI band для CI-веера прогноза (None если posterior недоступен).
        # Длина == len(predictions). Питает MultiScenarioChart ciLowSeries/ciHighSeries.
        'predictions_ci_low': predictions_ci_low,
        'predictions_ci_high': predictions_ci_high,
        'channel_contributions': channel_contributions,
        'totals': {
            'predicted_kpi': round(scenario_total, 0),
            'baseline_kpi': round(baseline_total, 0),
            'incremental_kpi': round(incremental_total, 0),  # P1-4: incremental as primary
            'lift_pct': round(lift_pct, 1),
            # 5a (2026-05-04): legacy formula preserved для backward compat + expert mode.
            'lift_pct_baseline_only': round(legacy_lift_pct, 1),
            'current_total_kpi': round(current_total_kpi, 0),
            'total_spend': round(total_spend_native, 0),
            'total_spend_money': round(total_spend_money, 0) if total_spend_money else None,
            # P1-4: primary ROAS = incremental / spend (industry-standard MMM)
            'roas': round(roas_native, 2),
            'roas_money': round(roas_money, 2) if roas_money else None,
            # Legacy total ROAS (scenario_total / spend) - back-compat
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
            # v2.1.0 (ADR-021 pilot round 2 R2-1 2026-05-17): money equivalents
            # для count KPI. monetary KPI - native уже ₽. Frontend ScenarioCompare
            # читает эти fields для UI с money primary.
            'kpi_unit_cost': kpi_unit_cost,
            'predicted_kpi_money': (
                round(scenario_total * kpi_unit_cost, 0)
                if kpi_unit_cost is not None and kpi_kind_scenario == 'count'
                else (round(scenario_total, 0) if kpi_kind_scenario == 'monetary' else None)
            ),
            'incremental_kpi_money': (
                round(incremental_total * kpi_unit_cost, 0)
                if kpi_unit_cost is not None and kpi_kind_scenario == 'count'
                else (round(incremental_total, 0) if kpi_kind_scenario == 'monetary' else None)
            ),
            'baseline_kpi_money': (
                round(baseline_total * kpi_unit_cost, 0)
                if kpi_unit_cost is not None and kpi_kind_scenario == 'count'
                else (round(baseline_total, 0) if kpi_kind_scenario == 'monetary' else None)
            ),
        },
        # v2.1.0 (pilot R3-E04 round 4 2026-05-17): persist planning context для
        # re-load через compare table - frontend может surface «Прогноз на: 2027 год»
        # badge. Без этого scenario JSON теряет horizon provenance.
        # CI fix 2026-05-24: graceful int() с fallback к None при invalid input
        # (matches result dict с upstream try/except branch line 190-218 что parses
        # forecast_periods_cfg для actual computation. Without this guard, scenario.json
        # serialization crashed на invalid frontend input).
        'forecast_periods': _safe_int_or_none(forecast_periods_cfg),
        'forecast_period_label': config.get('forecast_period_label') or None,
        'per_channel_spend': {
            'native': {k: round(v, 2) for k, v in per_channel_native.items()},
            'money': {k: round(v, 2) for k, v in per_channel_money.items()} if units_fully_covered else None,
        },
        'unit_costs': unit_costs if unit_costs else None,
        'media_plan': media_plan,
        'model_version': model_version,  # for downstream UI badge
        # Мат-аудит 2026-07-02 (F-04): {'severity': 0..3, 'channels': [...]} —
        # выход per-period плана за наблюдавшийся диапазон трат (p95/p99 тиры).
        'extrapolation': extrapolation,
    }

    # Save. NaN-safe (как decomposer.py:1174, rc10-урок 2026-06-04): NaN→null, иначе
    # Rust serde_json (read_scenarios) роняет файл. Особенно важно для per-period CI band
    # (predictions_ci_low/high) — CI-вычисления чувствительнее к численным edge-case'ам.
    from utils.safe_io import sanitize_nonfinite
    results_dir = project_path / 'results' / 'scenarios'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / f'{scenario_name}.json', 'w', encoding='utf-8') as f:
        json.dump(sanitize_nonfinite(result), f, ensure_ascii=False, indent=2)

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
    Файлы на диске НЕ переписываются - миграция только для отображения.

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
    # Если legacy без roas_method - помечаем как 'total' для UI badge.
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

    # B3-E1 (pilot R3 2026-05-17): money primary для count+kpi_unit_cost KPI.
    # Если ВСЕ scenarios имеют non-null predicted_kpi_money (ADR-021 R2-1) -
    # routing через predicted_kpi_money с unit='₽'. Иначе fallback к native
    # predicted_kpi с unit='count' (legacy / monetary без conversion).
    kpi_money_available = all(
        s['totals'].get('predicted_kpi_money') is not None for s in scenarios
    )

    if has_money:
        budget_row = ['Бюджет (₽)'] + [s['totals']['total_spend_money'] for s in scenarios]
        roas_row = ['ROAS (₽)'] + [s['totals']['roas_money'] for s in scenarios]
        best = max(scenarios, key=lambda s: s['totals']['roas_money'])
        best_roas = best['totals']['roas_money']
        roas_label = 'ROAS'
        budget_unit = 'money'
        roas_unit = 'roas'
    else:
        budget_row = ['Бюджет (native)'] + [s['totals']['total_spend'] for s in scenarios]
        roas_row = ['ROAS (native, смешанные единицы)'] + [s['totals']['roas'] for s in scenarios]
        best = max(scenarios, key=lambda s: s['totals']['roas'])
        best_roas = best['totals']['roas']
        roas_label = 'ROAS (native)'
        budget_unit = 'native'
        roas_unit = 'roas'

    # B3-E1: primary KPI row - money если все scenarios имеют predicted_kpi_money,
    # иначе fallback к native count. lift_pct unitless ratio - неизменен.
    if kpi_money_available:
        kpi_row = ['Прогноз KPI (₽)'] + [
            s['totals']['predicted_kpi_money'] for s in scenarios
        ]
        kpi_unit = '₽'
    else:
        kpi_row = ['Прогноз KPI'] + [s['totals']['predicted_kpi'] for s in scenarios]
        kpi_unit = 'count'

    comparison = {
        'headers': ['Метрика'] + [s['scenario_name'] for s in scenarios],
        'rows': [
            kpi_row,
            budget_row,
            roas_row,
            ['Лифт vs baseline'] + [f"+{s['totals']['lift_pct']}%" for s in scenarios],
        ],
        # B3-E1: per-row unit hints для frontend formatter dispatch.
        # 'money' / 'native' = budget, 'roas' = ROAS multiplier, '₽' = money KPI,
        # 'count' = native count KPI, 'pct' = lift percentage.
        'row_units': [kpi_unit, budget_unit, roas_unit, 'pct'],
        'money_mode': has_money,
        'kpi_money_mode': kpi_money_available,
    }

    warn = ''
    if not has_money:
        warn = ' ⚠️ Бюджеты в native-единицах (смешанные) - ROAS не сопоставим между сценариями. Укажи стоимость юнита в блоке «Проверка».'

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
