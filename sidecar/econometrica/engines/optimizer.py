"""
Budget optimization engine.
Finds optimal spend allocation using scipy.optimize (SLSQP).
"""
import json
import pickle
import numpy as np
from pathlib import Path
from scipy.optimize import minimize
from typing import Any

from utils.adstock import apply_adstock, geometric_adstock_batch, adstock_factor_batch
from utils.saturation import hill_function, response_curve, hill_derivative_batch
from utils.posterior_propagation import (
    compute_ci_hdi,
    compute_train_adstock_mean_samples,
    load_posterior_samples,
    per_channel_samples,
)


def _flat_alloc_adstock_avg(
    raw_per_period: float,
    n_periods: int,
    a_type: str,
    decay: float | None = None,
) -> float:
    """F2 fix (math-audit v1.3): среднее adstocked spend под flat allocation.

    Optimizer оперирует с total spend per channel (scalar). Hill ожидает
    per-period adstocked spend (как в training + scenario). Для flat allocation
    raw_t = const повторяется по периодам, applied adstock декомпозирует carryover.
    Берём среднее за период - это эквивалент того что training Hill видел
    усреднённо.

    Phase 1.1: optional decay parameter - when v1.2 pickle, posterior mean decay
    is used; for v1.0/v1.1/v1.1.5 pickles decay=None falls back to library default 0.5.
    """
    if n_periods < 1 or raw_per_period <= 0:
        return float(raw_per_period)
    flat = np.full(n_periods, float(raw_per_period))
    params = {'alpha': float(decay)} if decay is not None else None
    adstocked = apply_adstock(flat, a_type, params)
    return float(adstocked.mean())


def _adstock_factor(
    x_per_period: float,
    n_periods: int,
    a_type: str,
    decay: float | None = None,
) -> float:
    """∂(_flat_alloc_adstock_avg)/∂(x_per_period) - sensitivity factor.

    F0.2 (Phase 0.1 fix-session): adstock factor is the missing piece in
    chain rule for marginal ROAS. See docs/MATH_AUDIT_v1_3_PHASE_0_1.md §4.

    Phase 1.1: optional decay parameter from posterior mean (v1.2 pickle).
    None falls back to library default 0.5 (v1.0/v1.1/v1.1.5 pickles).

    Args:
        x_per_period: spend per period (≥ 0)
        n_periods: training horizon length
        a_type: 'geometric' | 'weibull' | 'noop' | 'none'
        decay: optional posterior mean decay; None → library default 0.5
    Returns:
        ∂(adstock_avg)/∂(x_per_period). Constant in x for linear adstock.
    """
    if n_periods < 1:
        return 0.0
    if a_type in ('noop', 'none'):
        return 1.0
    if a_type == 'geometric':
        # Analytical (exact for linear adstock with constant input).
        # adstock_avg(x, n) = x · [n - θ·(1-θ^n)/(1-θ)] / [n·(1-θ)]
        # ∂/∂x = [n - θ·(1-θ^n)/(1-θ)] / [n·(1-θ)]   (constant in x)
        theta = float(decay) if decay is not None else 0.5
        if not (0.0 < theta < 1.0):
            return 1.0
        n = n_periods
        return (n - theta * (1.0 - theta ** n) / (1.0 - theta)) / (n * (1.0 - theta))
    # weibull / unknown - central difference (exact for linear convolution).
    if x_per_period <= 0:
        # Use small probe to discover linear factor.
        eps = 1.0
        plus = _flat_alloc_adstock_avg(eps, n_periods, a_type, decay)
        minus = _flat_alloc_adstock_avg(0.0, n_periods, a_type, decay)
        return float(plus - minus) / eps
    eps = max(x_per_period * 1e-4, 1e-9)
    plus = _flat_alloc_adstock_avg(x_per_period + eps, n_periods, a_type, decay)
    minus = _flat_alloc_adstock_avg(max(x_per_period - eps, 1e-12), n_periods, a_type, decay)
    return float(plus - minus) / (2.0 * eps)


def _compute_mroas_money(
    *,
    current_spend_native: float,
    n_periods: int,
    mean: float,
    alpha: float,
    gamma: float,
    beta: float,
    adstock_type: str,
    y_std: float,
    unit_cost: float = 1.0,
    decay: float | None = None,
    uc_at_training: float = 1.0,
) -> float:
    """Marginal ROAS in money-per-money - single source of truth.

    # invariant: I6 (mROAS chain rule) - closed form matches finite-difference
    # within 5e-3 relative error. See docs/OPTIMIZER_INVARIANTS_REGISTRY.md.

    F0.2 (Phase 0.1 fix-session): canonical mROAS computation. Returns
    ∂KPI(money)/∂spend(money) at the current point.

    Math derivation: docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3.

    Final formula:
        mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost

    where:
        x_pp = current_spend_native / n_periods
        x_norm = adstock_avg(x_pp, n) / mean
        adstock_factor = ∂(adstock_avg)/∂(x_pp)

    Args:
        current_spend_native: total spend over n_periods (≥ 0), native units
        n_periods: training horizon
        mean: training-time mean of channel media volume
        alpha, gamma, beta: Hill saturation parameters
        adstock_type: 'geometric' | 'weibull' | 'noop'
        y_std: standard deviation of trained y (KPI scale)
        unit_cost: ₽ per native unit (e.g. CPP for TRPs); use 1.0 for money channels

    Returns:
        Marginal ROAS - ∂KPI(money)/∂spend(money). Unitless ratio.
        Returns 0.0 for degenerate inputs (zero spend, zero mean, zero beta).
    """
    if current_spend_native <= 0:
        return 0.0
    if mean <= 0 or beta == 0 or n_periods < 1 or unit_cost <= 0:
        return 0.0

    # v2.1.0 (ADR-020): pre-multiply media через uc_at_training ДО adstock+normalize,
    # чтобы Hill x_norm в той же scale что media_means в pickle (training-time).
    # Без этого fix: для TRPs канала с unit_cost_train=120000 media_means scaled,
    # но x_pp native → x_norm меньше в 120000× → optimizer думает что канал на 0
    # уровне saturation → перераспределяет в Digital.
    uc_train_safe = max(float(uc_at_training), 1e-10)
    x_pp = (current_spend_native * uc_train_safe) / n_periods
    adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, adstock_type, decay)
    x_norm = adstock_avg / max(mean, 1e-10)

    # Hill derivative (normalized space): hill'(x) = α·γ^α·x^(α-1) / (x^α + γ^α)²
    g_safe = max(gamma, 1e-10)
    x_safe = max(x_norm, 1e-10)
    hill_deriv = (alpha * (g_safe ** alpha) * (x_safe ** (alpha - 1))) / (
        (x_safe ** alpha + g_safe ** alpha) ** 2
    )

    af = _adstock_factor(x_pp, n_periods, adstock_type, decay)

    # Chain rule: KPI per scaled-spend (training-equivalent). x_pp уже включает
    # uc_at_training множитель, поэтому adstock_factor возвращает sensitivity
    # ∂adstock/∂scaled_spend. Convert обратно: ∂KPI/∂native = ∂KPI/∂scaled × uc_train.
    mroas_native = beta * hill_deriv * af * y_std / max(mean, 1e-10) * uc_train_safe
    # Convert to per-money axis (∂money_spent / ∂native_spend = unit_cost current).
    return float(mroas_native / unit_cost)


def _compute_mroas_money_samples(
    *,
    current_spend_native: float,
    n_periods: int,
    mean: float | np.ndarray,
    alpha_samples: np.ndarray,
    gamma_samples: np.ndarray,
    beta_samples: np.ndarray,
    adstock_type: str,
    y_std: float,
    unit_cost: float = 1.0,
    decay_samples: np.ndarray | None = None,
    uc_at_training: float = 1.0,
) -> np.ndarray:
    """Vectorized mROAS over posterior samples (Phase 1.9 + 1.1).

    Returns array of mROAS values across all posterior draws - caller computes
    HDI/percentile for honest CI. Joint correlation preserved: sample i uses
    (alpha_samples[i], gamma_samples[i], beta_samples[i], decay_samples[i])
    from same MCMC draw.

    Math: same chain rule as scalar _compute_mroas_money, applied per-sample.
        mROAS_i = β_i · hill'(x_norm_i; α_i, γ_i) · adstock_factor_i · y_std / mean / unit_cost

    Phase 1.1: when decay_samples provided, adstock_factor and x_norm both vary per
    sample (geometric channels). Phase 1.9 fallback uses default 0.5 decay (constant).

    Args:
        current_spend_native: total spend over n_periods (≥ 0)
        n_periods, mean, adstock_type, y_std, unit_cost: same as scalar variant
        alpha_samples, gamma_samples, beta_samples: 1D arrays shape (n_samples,)
        decay_samples: optional 1D shape (n_samples,) - Phase 1.1 sampled adstock decay.
            None → falls back to library default 0.5 (Phase 1.9 path).

    Returns:
        np.ndarray shape (n_samples,) of mROAS values. All zeros for degenerate inputs.
    """
    n = int(np.asarray(alpha_samples).size)
    # F1 fix (audit 2026-04-27): mean may be scalar (legacy v1.0/v1.1.5 fallback)
    # or per-sample 1D array (Phase 1.1 path with training adstock means).
    # Sanity guard works on either.
    is_arr_mean = isinstance(mean, np.ndarray) and mean.ndim >= 1
    mean_scalar_for_guard = float(np.min(mean)) if is_arr_mean else float(mean)
    if current_spend_native <= 0 or mean_scalar_for_guard <= 0 or n_periods < 1 or unit_cost <= 0 or n == 0:
        return np.zeros(max(n, 1), dtype=np.float64)

    # v2.1.0 (ADR-020): pre-multiply media через uc_at_training ДО adstock+normalize
    # для symmetry с training (mean_arr в pickle scaled).
    uc_train_safe = max(float(uc_at_training), 1e-10)
    x_pp = (current_spend_native * uc_train_safe) / n_periods

    if decay_samples is not None and adstock_type == 'geometric':
        # Phase 1.1: vectorized per-sample adstock_avg + adstock_factor
        # H4 fix (audit 2026-04-26): reuse adstock_factor_batch(...) единый source of
        # truth для analytical formula.
        af_per_sample = adstock_factor_batch(decay_samples, n_periods, adstock_type)
        adstock_avg_per_sample = x_pp * af_per_sample  # (n_samples,)
        # F1 fix: per-sample TRAINING adstock mean. mean_arr varies per sample
        # to match in-model `adstock_full[s,:].mean()` normalization. When caller
        # passed scalar (legacy/fallback), broadcasts across all samples.
        if is_arr_mean:
            mean_arr = np.maximum(np.asarray(mean, dtype=np.float64), 1e-10)
        else:
            mean_arr = np.full(n, max(float(mean), 1e-10), dtype=np.float64)
        x_norm_per_sample = adstock_avg_per_sample / mean_arr  # (n_samples,)

        # Per-sample Hill derivative - broadcast manually for joint correlation.
        # hill'(x) = α · γ^α · x^(α-1) / (x^α + γ^α)²
        alpha = np.asarray(alpha_samples, dtype=np.float64)
        gamma = np.asarray(gamma_samples, dtype=np.float64)
        x_safe = np.maximum(x_norm_per_sample, 1e-10)
        gamma_safe = np.maximum(gamma, 1e-10)
        x_pow = x_safe ** alpha
        gamma_pow = gamma_safe ** alpha
        hill_deriv_arr = (alpha * gamma_pow * (x_safe ** (alpha - 1.0))) / ((x_pow + gamma_pow) ** 2)
        af_arr = np.asarray(af_per_sample, dtype=np.float64)
    else:
        # Phase 1.9 fallback: scalar adstock_avg/factor (decay constant 0.5).
        # mean is scalar в этом path (decay constant → adstock_full constant across samples).
        mean_scalar = mean_scalar_for_guard
        adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, adstock_type)
        x_norm = adstock_avg / max(mean_scalar, 1e-10)
        hill_deriv_arr = hill_derivative_batch(
            np.array([x_norm]), alpha_samples, gamma_samples
        ).ravel()
        af_arr = _adstock_factor(x_pp, n_periods, adstock_type)
        mean_arr = max(mean_scalar, 1e-10)  # Use scalar in chain rule

    # Chain rule per-sample. x_pp уже pre-multiplied на uc_train, поэтому afтор
    # adstock_factor возвращает ∂adstock/∂scaled. Convert обратно к ∂/∂native.
    beta_arr = np.asarray(beta_samples, dtype=np.float64)
    mroas_native = beta_arr * hill_deriv_arr * af_arr * y_std / mean_arr * uc_train_safe
    return mroas_native / unit_cost


def optimize(config: dict, project_dir: str) -> dict[str, Any]:
    """Optimize budget allocation across channels.

    Args:
        config: {
            'total_budget': float|None,  # None = use current total
            'min_pct': float,            # Глобальный Min % (default 50). Используется
                                         # как fallback если нет per-channel constraint.
            'max_pct': float,            # Глобальный Max % (default 150).
            'min_per_channel': dict|None,# Опционально: {channel: min_pct} - экспертный режим.
                                         # Если задан для канала, перекрывает глобальный min_pct.
            'max_per_channel': dict|None,# Опционально: {channel: max_pct} - экспертный режим.
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with current vs optimal allocation, response curves, expected lift
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

    # P0-1/2/9 fix: pickle compat detection.
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
    # y_std needed for KPI-scale conversions of mROI and response curves.
    y_std = float(norm.get('y_std', 1.0)) or 1.0

    # v2.1.0 (ADR-021): kpi_unit_cost для money equivalents в result.
    # Override > snapshot из pickle > None (legacy native KPI units).
    _kpi_uc_override = config.get('kpi_unit_cost')
    if _kpi_uc_override is not None and float(_kpi_uc_override) > 0:
        kpi_unit_cost = float(_kpi_uc_override)
    else:
        _snap = model_data.get('kpi_unit_cost_snapshot')
        kpi_unit_cost = float(_snap) if _snap is not None and float(_snap) > 0 else None
    _kpi_kind_cfg = (config_model.get('kpi_kind') or '').lower()
    if _kpi_kind_cfg in ('count', 'monetary'):
        kpi_kind = _kpi_kind_cfg
    else:
        try:
            from utils.column_detection import classify_column
            _kpi_col_classify = classify_column(config_model.get('kpi_column', '') or '')
            kpi_kind = 'count' if _kpi_col_classify == 'target_count' else 'monetary'
        except Exception:
            kpi_kind = 'monetary'

    # Phase 1.9: posterior samples for honest CI on mROAS. None for v1.0/v1.1 pickles.
    # When available, mroi_current/optimal include {mean, ci_low, ci_high} dicts.
    posterior_samples = load_posterior_samples(model_data)

    # A1 fix (post-audit v1.2): exclude untrained channels from optimization domain.
    # Channels with zero training variance have β from prior (uninformative) - optimizer
    # would silently allocate budget to them based on fabricated response curves.
    untrained_channels = set(norm.get('untrained_channels', []) or [])
    if untrained_channels and any(c in untrained_channels for c in media_cols):
        # Filter: remove untrained from optimization scope but warn user.
        active_media_cols = [c for c in media_cols if c not in untrained_channels]
        if not active_media_cols:
            return {
                'status': 'error',
                'error_code': 'NO_TRAINED_CHANNELS',
                'message': (
                    'Все каналы в модели имели нулевую вариативность в обучающих '
                    'данных. Оптимизация невозможна - переобучите модель.'
                ),
            }
        media_cols = active_media_cols
    # Override > pickle-config (аналогично decomposer).
    unit_costs_override = config.get('unit_costs')
    unit_costs = unit_costs_override if unit_costs_override is not None else (config_model.get('unit_costs', {}) or {})

    # Read original data for current spend
    import pandas as pd
    data_file = config_model['data_file']
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (совпадает с train-time merge_rules)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config_model.get('merge_rules'))

    # Phase 2 audit pass 4 - per-channel inflation. Apply BEFORE current_spend
    # money totals computed downstream (current_spend × unit_cost).
    inflation_pct_per_channel = config.get('unit_cost_inflation_pct')
    if inflation_pct_per_channel:
        from utils.unit_cost_inflation import apply_inflation_to_unit_costs
        unit_costs = apply_inflation_to_unit_costs(
            unit_costs=unit_costs,
            inflation_pct_per_channel=inflation_pct_per_channel,
            df=df,
            date_column=config_model.get('date_column', 'date'),
        )

    current_spend = {col: float(df[col].fillna(0).sum()) for col in media_cols}
    total_current = sum(current_spend.values())
    n_periods = max(len(df), 1)

    # ─── Phase 2 (Planning Mode) - forecast horizon decoupling ───
    # Math reference: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis (M9 finding,
    # L1 lock = Option C in planning mode, preserve current Hill-of-mean in
    # analyst mode для byte-exact backward compat).
    #
    # forecast_periods config = None → analyst mode (current behavior preserved).
    # forecast_periods config = int  → planning mode → Option C (per-period
    # Hill summation matching scenario engine).
    forecast_periods_config = config.get('forecast_periods')
    planning_mode = False
    forecast_n_periods = n_periods
    if forecast_periods_config is not None:
        try:
            forecast_n_periods = int(forecast_periods_config)
        except (TypeError, ValueError):
            return {
                'status': 'error',
                'error_code': 'INVALID_FORECAST_PERIODS',
                'message': (
                    f'forecast_periods должно быть целым числом ≥ 1 '
                    f'(получено {forecast_periods_config!r}).'
                ),
            }
        if forecast_n_periods < 1:
            return {
                'status': 'error',
                'error_code': 'INVALID_FORECAST_PERIODS',
                'message': 'forecast_periods должно быть ≥ 1.',
            }
        # M6 (audit doc L2) + S7 (audit pass 2 - KPI-aware cap):
        # Audit pass 3 fix (2026-05-02): hardcoded 2× bypassed S7 для awareness
        # pickles. /compute/forecast-scaling уже использует KPI-aware multiplier;
        # /compute/optimize должен делать то же самое - иначе frontend caller
        # мог бы обойти 1.5× cap (awareness) через direct optimize call.
        from engines.persistence import get_kpi_type
        from utils.forecast_validation import get_forecast_horizon_max_multiplier
        _kpi_type = get_kpi_type(model_data)
        _max_mult = get_forecast_horizon_max_multiplier(_kpi_type)
        _max_horizon = int(n_periods * _max_mult)
        if forecast_n_periods > _max_horizon:
            return {
                'status': 'error',
                'error_code': 'FORECAST_HORIZON_TOO_LONG',
                'message': (
                    f'Период планирования ({forecast_n_periods}) превышает '
                    f'обучающий горизонт более чем в {_max_mult:.1f}× '
                    f'({_max_horizon}). Допущение стационарности коэффициентов '
                    f'нарушено. Переучите модель на расширенных данных или '
                    f'сократите горизонт.'
                ),
            }
        planning_mode = True

    # v2.1.0 F-012 (2026-05-18): horizon scale factor для planner-mode comparisons.
    # Analyst mode: forecast == training, scale=1.0 (no projection).
    # Planner mode: project training-horizon current totals на forecast horizon.
    # Used далее в: money_target default, current_response_real baseline, per-channel
    # delta_pct + mROAS + display fields. Без этого training_total fed в Option C
    # objective с n_periods=forecast → inflated per-period rate → negative lift artifact.
    horizon_scale = (forecast_n_periods / max(n_periods, 1)) if planning_mode else 1.0

    # Phase 2 normalization (spend/mean Robyn-style)
    media_means = norm.get('media_means', {}) or {}

    # F2 fix: adstock config per channel (matches training + scenario)
    adstock_config = config_model.get('adstock_config', {}) or {}

    def _adstock_type(col: str) -> str:
        raw = adstock_config.get(col)
        if isinstance(raw, dict):
            return raw.get('type', 'geometric')
        if isinstance(raw, str):
            return raw
        return 'geometric'

    # Money constraint: если задан total_budget_money, constraint считается в money
    # (Σ x_native × unit_cost == total_budget_money). Иначе - native constraint как раньше.
    total_budget_money_target = config.get('total_budget_money')
    uc_arr = [float(unit_costs.get(col, 1.0) or 1.0) for col in media_cols]

    # v2.1.0 (ADR-020 hardening pilot D 2026-05-17): training-time unit_costs
    # snapshot для Hill normalization symmetry. Если pickle обучен с pre-multiply
    # (unit_costs_applied_at_training=True), все math paths которые делают
    # x_norm = adstock(x) / mean ДОЛЖНЫ pre-multiply x через тот же uc_train.
    # Без этого optimizer перераспределяет бюджет некорректно для mixed units.
    unit_costs_applied_at_training = bool(model_data.get('unit_costs_applied_at_training'))
    unit_costs_snapshot_train: dict[str, float] = (
        model_data.get('unit_costs_snapshot') or {}
    ) if unit_costs_applied_at_training else {}
    uc_train_arr = [
        float(unit_costs_snapshot_train.get(col, 1.0) or 1.0) for col in media_cols
    ]

    # P0-11 fix (math-fix-v1.0.13) + Phase 0.1 live-test refinement:
    # Detect real unit_smell - native-unit channel (TRPs/clicks/impressions) with
    # default uc=1.0 (CPP/CPM не задан). Это арифметически некорректный mix.
    # Если unit_smell нет - auto-compute money budget из current spend × uc и идём
    # в money-mode без error. Это типичный кейс russian client: digital в рублях
    # (uc=1) + TV в TRPs (uc=CPP) - раньше guard блокировал false-positively.
    UNIT_HINTS = ('TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ',
                  'КЛИК', 'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ')
    if total_budget_money_target is None:
        smell_channels = [
            col for col, uc in zip(media_cols, uc_arr)
            if uc == 1.0 and any(h in col.upper() for h in UNIT_HINTS)
        ]
        if smell_channels:
            return {
                'status': 'error',
                'error_code': 'UNIT_SMELL',
                'message': f'Не задана стоимость единицы (CPP/CPM) для каналов: {", ".join(smell_channels)}. Укажите unit_costs или total_budget_money.',
            }
        is_all_money = all(uc == 1.0 for uc in uc_arr)
        is_all_native = all(uc != 1.0 for uc in uc_arr)
        if not (is_all_money or is_all_native):
            # Mixed but all CPP/CPM explicit: auto-derive money budget
            total_budget_money_target = sum(
                current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols)
            )

    if total_budget_money_target is not None:
        # В money-режиме total_budget для логов/insight = native-эквивалент (пропорция).
        total_current_money = sum(current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols))
        ratio = float(total_budget_money_target) / max(total_current_money, 1e-9)
        total_budget = total_current * ratio
    else:
        # Bug fix 2026-05-25 (Goal-Seek): `config.get('total_budget') or total_current`
        # treats 0 как falsy → возвращает total_current когда total_budget=0.
        # Это ломает inverse Goal-Seek bisection: _forward_at_budget(0) actually
        # returns forward(current_spend), bisection thinks budget=0 suffices для
        # любой target ≤ current_sales. Explicit None check сохраняет 0 как valid.
        _cfg_budget = config.get('total_budget')
        total_budget = float(_cfg_budget) if _cfg_budget is not None else total_current

    min_pct_global = config.get('min_pct', 50) / 100
    max_pct_global = config.get('max_pct', 150) / 100

    # ─── D.3 - Per-group constraints (Trust 3) + ConstraintBundle ───────
    # 3-level precedence: per-channel > per-group (brand/perf) > global.
    # Mixed/uncategorized channels → fall back к global (helper handles).
    # Backward compat: brand_*/perf_* unset → behavior identical к pre-D.3.
    from utils.optimizer_constraints import (
        ConstraintBundle,
        FeasibilityError,
        resolve_channel_bounds,
    )
    from engines.persistence import get_channel_categories, is_hierarchical_model

    def _pct_or_none(key: str) -> float | None:
        v = config.get(key)
        return (v / 100) if v is not None else None

    _per_group_supplied = any(
        config.get(k) is not None
        for k in ('brand_min_pct', 'brand_max_pct', 'perf_min_pct', 'perf_max_pct')
    )

    # AUDIT-2 (post-D.3 hardening): gate per-group constraints для non-hierarchical моделей.
    # Pre-Trust3 pickles (model_version < 1.3) обучены flat (single global prior).
    # Heuristic мог бы заполнить categories, но constraints применятся к модели,
    # которая не обучалась с group-conditional structure → semantic mismatch.
    # Если user явно передал per-group → reject с указанием на retrain.
    # Если per-group не передан → behavior identical к pre-D.3 (backward compat).
    if _per_group_supplied and not is_hierarchical_model(model_data):
        return {
            'status': 'error',
            'error_code': 'PER_GROUP_REQUIRES_HIERARCHICAL_MODEL',
            'message': (
                'Per-group ограничения (brand/performance) требуют hierarchical модели '
                '(model_version ≥ 1.3 с ≥2 brand или ≥2 performance каналами). '
                'Текущая модель flat - переучите с brand/perf categorization в шаге '
                '«Валидация» или удалите per-group constraints.'
            ),
        }

    _ch_min = {c: v / 100 for c, v in (config.get('min_per_channel') or {}).items()}
    _ch_max = {c: v / 100 for c, v in (config.get('max_per_channel') or {}).items()}
    constraint_bundle = ConstraintBundle(
        global_min_pct=min_pct_global,
        global_max_pct=max_pct_global,
        brand_min_pct=_pct_or_none('brand_min_pct'),
        brand_max_pct=_pct_or_none('brand_max_pct'),
        perf_min_pct=_pct_or_none('perf_min_pct'),
        perf_max_pct=_pct_or_none('perf_max_pct'),
        channel_min_pct=_ch_min or None,
        channel_max_pct=_ch_max or None,
    )

    # Channel categories из pickle. Heuristic fallback применяется только когда модель
    # hierarchical (выше gate) - для flat моделей heuristic нерелевантен (gate уже rejected).
    channel_categories = get_channel_categories(model_data, fallback_heuristic=True)

    # Pre-flight Check 1 - group hierarchy (group_max ≤ global_max).
    # Check 2 (budget feasibility) делается existing INFEASIBLE_BUDGET_HIGH/LOW guard
    # ниже, чтобы preserve zero-spend fallback semantics в _bounds_money_for.
    try:
        if constraint_bundle.brand_max_pct is not None and constraint_bundle.brand_max_pct > constraint_bundle.global_max_pct:
            raise FeasibilityError(
                f"Brand max ({constraint_bundle.brand_max_pct * 100:.0f}%) превышает global max "
                f"({constraint_bundle.global_max_pct * 100:.0f}%). "
                f"Brand max должен быть ≤ global max - иначе constraint hierarchy нарушается."
            )
        if constraint_bundle.perf_max_pct is not None and constraint_bundle.perf_max_pct > constraint_bundle.global_max_pct:
            raise FeasibilityError(
                f"Performance max ({constraint_bundle.perf_max_pct * 100:.0f}%) превышает global max "
                f"({constraint_bundle.global_max_pct * 100:.0f}%). "
                f"Performance max должен быть ≤ global max - иначе constraint hierarchy нарушается."
            )
    except FeasibilityError as _fe:
        return {
            'status': 'error',
            'error_code': 'INFEASIBLE_GROUP_HIERARCHY',
            'message': str(_fe),
        }

    # ─────────────────────────────────────────────────────────────────────
    # math-fix v1.0.14.1, A1 (audit-of-audit 2026-04-28):
    # Money-axis rescaling. Pre-fix optimizer worked в native units, constraint
    # в money - bounds spread 10⁵× (TRPs ~10⁴ vs OLV ~10⁸), gradient spread
    # 10⁴×, conditioning ужасный. SLSQP застревал в success=True at iter=1
    # стартуя от current. Доказательство: scipy direct repro на Kagocel pickle
    # 2026-04-28: start=current → lift=+0.00%; start=extreme (small=200%, TRPs
    # balance) → lift=+28.30%. Multi-start с random perturbation + clip давал
    # точки слишком близко к current чтобы выбраться.
    # Post-fix: optimize в money axis - uniform scale, well-conditioned.
    # See docs/MATH_AUDIT_v1_4_OPTIMIZER_FIX.md.
    # ─────────────────────────────────────────────────────────────────────
    # F1+F2 fix (math-audit v1.3): per-period averaging + adstock matches
    # training and scenario semantics. Hill input still computed in native units
    # (matches modeler.py training math), но input в objective - money vector.
    n_ch = max(len(media_cols), 1)

    def total_response_money(x_money):
        """Objective: maximize total predicted KPI lift over n_periods.

        Input: x_money[i] = spend per channel в money axis (₽).
        Inside: convert to native via x_native = x_money / unit_cost,
        then pre-multiply на uc_train (ADR-020 symmetry), adstock + Hill.
        Returns: negative total (for scipy minimize).
        """
        total = 0.0
        for i, col in enumerate(media_cols):
            p = channel_params[col]
            # C1 fix: prefer adstock_mean_posterior (v1.2+) for math consistency.
            mean_posterior = p.get('adstock_mean_posterior')
            mean = float(mean_posterior) if mean_posterior is not None else (float(media_means.get(col, 1)) or 1)
            decay_pt = p.get('decay')  # Phase 1.1: None for v1.0/v1.1/v1.1.5 → default 0.5
            x_native_total = x_money[i] / max(uc_arr[i], 1e-10)
            # v2.1.0 (ADR-020): pre-multiply через uc_train для Hill symmetry.
            x_scaled_total = x_native_total * max(uc_train_arr[i], 1e-10)
            x_avg_raw = x_scaled_total / n_periods
            x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, n_periods, _adstock_type(col), decay_pt)
            x_norm = x_avg_adstock / max(mean, 1e-10)
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
            total += p['beta'] * sat[0] * n_periods
        return -total

    # ─── Phase 2 - Option C planning-mode objective (M9 fix) ───
    # Per-period Hill summation matches scenario.py:167-186 + decomposer.py:
    # 289-292 semantics. Restores 3-way alignment в planning mode.
    # Activates only when planning_mode=True (forecast_periods explicitly given).
    # Math: docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md §2bis.
    def total_response_money_planning(x_money):
        """Option C - per-period sum-of-Hill, matches scenario engine."""
        from utils.forecasting import evaluate_flat_allocation_response
        total = evaluate_flat_allocation_response(
            media_cols=media_cols,
            channel_params=channel_params,
            allocation_money=x_money,
            unit_costs=uc_arr,
            media_means=media_means,
            adstock_config=adstock_config,
            n_periods=forecast_n_periods,
            # v2.1.0 (ADR-020): training-time uc для Hill scale symmetry.
            unit_costs_at_training=uc_train_arr,
        )
        return -total

    # Active objective dispatch - planning mode → Option C, analyst → legacy.
    # invariant: I4 (backward compat) - analyst path preserves Hill-of-mean math
    # for byte-exact v1.1.0 pickle reproducibility.
    # invariant: I8 (Option C identity) - planning path matches scenario.py
    # per-period sum-of-Hill semantics.
    _objective_fn = total_response_money_planning if planning_mode else total_response_money

    # ─ Money-axis bounds (replace native bounds + money constraint) ─
    # Constraint trivializes к sum(x_money) == money_target - uniform scale.
    # v2.1.0 F-012: planner-mode default = forecast-horizon-projected current
    # (training_total × horizon_scale). Pre-fix default was training_total which,
    # combined с n_periods=forecast в Option C objective, давал inflated per-period
    # rate → negative lift artifact. Customer explicit total_budget_money unaffected.
    _training_total_money = sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))
    if total_budget_money_target is not None:
        money_target = float(total_budget_money_target)
    else:
        # Bug fix 2026-05-25 (Goal-Seek): когда total_budget (native) задан явно,
        # money_target должен derivative из него, не fallback к training budget.
        # Без этого SLSQP optimizes к одному и тому же training_total независимо
        # от bisection's argument → forward(any X) returns same value → bisection
        # never finds positive budget.
        _cfg_native_budget = config.get('total_budget')
        if _cfg_native_budget is not None and total_current > 0:
            # Scale money proportionally от native ratio.
            money_target = float(_cfg_native_budget) * (_training_total_money / total_current)
        elif _cfg_native_budget is not None:
            # Edge case: no current spend — fallback к native value as money.
            money_target = float(_cfg_native_budget)
        else:
            money_target = _training_total_money * horizon_scale
    fallback_max_money = max(money_target * max_pct_global / n_ch, 1.0)

    def _bounds_money_for(col: str, i: int) -> tuple[float, float]:
        cs_money = current_spend[col] * uc_arr[i]
        if cs_money > 0:
            # D.3: 3-level precedence (per-channel > per-group > global) via helper.
            return resolve_channel_bounds(col, cs_money, channel_categories, constraint_bundle)
        # Zero-spend channel: allow up to fallback_max (preserve existing semantics).
        return (0.0, fallback_max_money)

    bounds_money = [_bounds_money_for(col, i) for i, col in enumerate(media_cols)]

    # O1.3 (Phase 0.1) - pre-flight feasibility (already в money).
    sum_upper_money = sum(b[1] for b in bounds_money)
    sum_lower_money = sum(b[0] for b in bounds_money)
    if money_target > sum_upper_money * 1.001:  # 0.1% float-tolerance
        return {
            'status': 'error',
            'error_code': 'INFEASIBLE_BUDGET_HIGH',
            'message': (
                f'Целевой бюджет {money_target:,.0f} ₽ превышает максимально допустимый '
                f'{sum_upper_money:,.0f} ₽ при текущих границах. Расширьте Макс. % per channel '
                f'или снизьте бюджет.'
            ),
        }
    if money_target < sum_lower_money * 0.999:
        return {
            'status': 'error',
            'error_code': 'INFEASIBLE_BUDGET_LOW',
            'message': (
                f'Целевой бюджет {money_target:,.0f} ₽ ниже минимального '
                f'{sum_lower_money:,.0f} ₽ при текущих границах. Уменьшите Мин. % per channel '
                f'или увеличьте бюджет.'
            ),
        }

    # Money sum constraint (trivial - uniform scale в money axis)
    # invariant: I2 (conservation) - Σ optimal_money == money_target ± 0.5%.
    # invariant: I3 (bounds satisfaction) - bounds_money[i] enforced per channel.
    constraints = [{'type': 'eq', 'fun': lambda x: float(np.sum(x) - money_target)}]

    import logging
    _logger = logging.getLogger('econometrica')

    def _project_to_budget(x: np.ndarray) -> np.ndarray:
        """Scale x then clip to bounds, repeat ≤3 iters until sum(x) ≈ money_target.

        Used for multi-start initialization. SLSQP equality constraint will
        fine-tune anyway, но close-to-feasible start helps convergence.
        """
        x = np.asarray(x, dtype=float).copy()
        for _ in range(3):
            s = float(np.sum(x))
            if s <= 1e-10:
                # Degenerate - distribute evenly within bounds
                x = np.array([(b[0] + b[1]) / 2 for b in bounds_money])
                continue
            x = x * (money_target / s)
            for i in range(len(x)):
                x[i] = max(bounds_money[i][0], min(bounds_money[i][1], x[i]))
        return x

    # ─ Multi-start: channel-pivot extremes + current + all-upper ─
    # Pre-fix (Phase 0.1 hotfix #19): random uniform + scale + clip - точки
    # клипались к current, SLSQP застревал. Audit 2026-04-28 confirmed empirically.
    # Post-fix (math-fix v1.0.14.1): channel-pivot starts - для каждого канала
    # i пробуем «канал i на upper, остальные на lower, project». Это даёт SLSQP
    # стартовые точки в разных корнерах feasible region.
    #
    # math-fix v1.0.16, L10 (Антон's live-test 2026-04-28): SEPARATE real-current
    # from projected-current. Pre-fix (commit fe42e7f) использовал projected x0_money
    # для current_response baseline, что инфлятило lift_pct на What-if scenarios
    # где money_target ≠ current_total_money. Customer testing budget changes
    # получал wrong KPI predictions (e.g. -50% budget → +124% «lift», +100% budget
    # → +10% «lift»). Mathematically невозможно - Hill saturation монотонна.
    # Fix: x0_money_real (real current, never projected) для baseline; projected
    # x0_money - только для SLSQP multi-start initialization.
    x0_money_real = np.array(
        [current_spend[col] * uc_arr[i] for i, col in enumerate(media_cols)],
        dtype=float,
    )
    x0_money = _project_to_budget(x0_money_real.copy())

    starts_money: list[tuple[str, np.ndarray]] = [('current', x0_money)]

    for pivot_idx in range(n_ch):
        # Pivot канал на upper, остальные на lower, project к budget
        extreme = np.array([bounds_money[i][0] for i in range(n_ch)])
        extreme[pivot_idx] = bounds_money[pivot_idx][1]
        starts_money.append((
            f'pivot_up_{pivot_idx}',
            _project_to_budget(extreme),
        ))

    # «others-at-upper, one-balances» - ключевой паттерн для mixed-units money budget.
    # На Kagocel-shape problem (TRPs ≈ 92% бюджета, 5 small money channels) global
    # optimum обычно: small channels at 200%, TRPs balances вниз. Pivot starts (один
    # на upper, остальные на lower) этот корнер не охватывают - projection пропорционально
    # тянет все. Этот паттерн ставит N-1 каналов на upper и точно вычисляет balance.
    for balance_idx in range(n_ch):
        candidate = np.array([bounds_money[i][1] for i in range(n_ch)], dtype=float)
        other_money = float(sum(candidate[i] for i in range(n_ch) if i != balance_idx))
        balance_money = money_target - other_money
        if bounds_money[balance_idx][0] <= balance_money <= bounds_money[balance_idx][1]:
            candidate[balance_idx] = balance_money
            # Точно feasible - projection не требуется, но защитный clip + check.
            starts_money.append((f'others_up_balance_{balance_idx}', candidate))

    # All-upper start - общий рост сценарий (projection scales всех вниз пропорц.)
    all_upper = np.array([bounds_money[i][1] for i in range(n_ch)])
    starts_money.append(('all_upper', _project_to_budget(all_upper)))

    # Phase 2 audit pass 7 (Антон 2026-05-03): «default-bounds anchor» -
    # гарантия monotonic improvement при widening bounds. Customer reported
    # wider bounds (0/500%) дали LIFT=4.6% против narrower (20/200%) с 5.2%.
    #
    # invariant: I1 (monotonicity, paired) + I5a (anchor floor) - wider-than-default
    # bounds always ≥ default(20/200) optimal. See docs/OPTIMIZER_INVARIANTS_REGISTRY.md.
    # invariant: I5b (chain transitive monotonicity) - F1 fix 2026-05-03 added
    # cumulative anchor seeding via `prev_optimal` config field (see code below
    # после default_anchor block).
    # Cause: SLSQP non-convex Hill saturation → wider search space может
    # засосать SLSQP в extreme corners (0% spend на канал) откуда gradient
    # не пускает обратно. Local optimum хуже global.
    #
    # Fix: запустить mini-SLSQP с conservative defaults (20-200%) дополнительно;
    # его result project к user's bounds, use as additional multi-start point.
    # Если default-anchor result better → SLSQP from there окажется хотя бы
    # как минимум default's result в user's wider space. Гарантирует:
    # widening bounds никогда не делает результат хуже narrower bounds.
    DEFAULT_MIN_PCT, DEFAULT_MAX_PCT = 0.20, 2.00
    user_widened_bounds = (
        min_pct_global < DEFAULT_MIN_PCT - 1e-9
        or max_pct_global > DEFAULT_MAX_PCT + 1e-9
    )
    # Audit pass 18 fix (Антон 2026-05-03): initialize ALL anchor variables
    # ДО if-блока. Pre-fix: при user_widened=True но feasibility check fail,
    # code пропускал inside block без _default_anchor_enabled assignment +
    # без exception → UnboundLocalError на post-loop check «if _default_anchor_
    # enabled». Triggered на What-if whatIfMult=0.5 (money_target меньше →
    # default_bounds могут стать infeasible).
    _default_anchor_enabled = False
    _default_anchor_x_seed = None
    _default_anchor_bounds = None
    if user_widened_bounds and n_ch > 0:
        # Compute default-bounds version, intersected с per-channel/per-group
        # для consistency. Каналы с per-channel constraint остаются на тех бюджетах.
        try:
            def _default_bound_for(col: str, i: int) -> tuple[float, float]:
                cs_money = current_spend[col] * uc_arr[i]
                if cs_money <= 0:
                    # Zero-spend channel - match fallback semantics.
                    return (0.0, max(money_target * DEFAULT_MAX_PCT / n_ch, 1.0))
                # Mirror user logic, but cap к conservative defaults.
                lo_pct = max(min_pct_global, DEFAULT_MIN_PCT)
                hi_pct = min(max_pct_global, DEFAULT_MAX_PCT)
                # Per-channel + per-group precedence preserved: take INTERSECTION.
                user_lo, user_hi = resolve_channel_bounds(
                    col, cs_money, channel_categories, constraint_bundle
                )
                lo = max(cs_money * lo_pct, user_lo)
                hi = min(cs_money * hi_pct, user_hi)
                if lo >= hi:
                    lo, hi = user_lo, user_hi  # fallback к user's, infeasible default
                return (lo, hi)
            default_bounds = [_default_bound_for(col, i) for i, col in enumerate(media_cols)]
            # Feasibility check: default bounds support money_target?
            sum_def_lo = sum(b[0] for b in default_bounds)
            sum_def_hi = sum(b[1] for b in default_bounds)
            if sum_def_lo <= money_target * 1.001 and money_target <= sum_def_hi * 1.001:
                # Run SLSQP в default-bounds world from x0_money projected.
                def _project_to_default(x: np.ndarray) -> np.ndarray:
                    x = np.asarray(x, dtype=float).copy()
                    for _ in range(3):
                        s = float(np.sum(x))
                        if s <= 1e-10:
                            x = np.array([(b[0] + b[1]) / 2 for b in default_bounds])
                            continue
                        x = x * (money_target / s)
                        for i in range(len(x)):
                            x[i] = max(default_bounds[i][0], min(default_bounds[i][1], x[i]))
                    return x
                x0_default = _project_to_default(x0_money_real.copy())
                # Audit pass 12 (Антон 2026-05-03): CRITICAL FIX - pass 7/9
                # added anchor as multi-start point + ran SLSQP from там в user's
                # wider bounds. SLSQP non-convex может MOVE AWAY from anchor в
                # худший local optimum → monotonic guarantee broken. Customer
                # reported persistent regression: 4.8% (20/200) → 3.7% (0/500).
                #
                # Correct approach: add default's solution DIRECTLY as candidate
                # (x_default + its objective). Anchor x_default feasible в user's
                # space (default ⊆ user). Final selection min(candidates by .fun)
                # → anchor wins IF user's main runs all gave worse objective.
                # Floor at default's objective guaranteed regardless of SLSQP
                # behavior in wider space.
                # Also kept anchor seed как additional start point (still useful
                # for SLSQP geometry diversity).
                anchor_seed = _project_to_budget(x0_default.copy())
                starts_money.append(('default_anchor_seed', anchor_seed))
                # Stash x0_default + default_bounds для post-loop direct candidate
                _default_anchor_x_seed = x0_default.copy()
                _default_anchor_bounds = default_bounds
                _default_anchor_enabled = True
        except Exception as e:
            import logging as _log
            _log.getLogger('econometrica').warning(
                f"default_anchor setup failed: {e}. User bounds run без anchor."
            )
            _default_anchor_enabled = False
    else:
        _default_anchor_enabled = False

    def _safe_minimize_money(x_start: np.ndarray):
        try:
            r = minimize(
                _objective_fn, x_start,
                method='SLSQP',
                bounds=bounds_money,
                constraints=constraints,
                options={'maxiter': 200, 'ftol': 1e-7, 'disp': False},
            )
            return r
        except (np.linalg.LinAlgError, ValueError, RuntimeError) as e:
            _logger.warning(f"SLSQP attempt failed: {type(e).__name__}: {e}")
            return None

    # Run all starts, collect diagnostics + successful candidates.
    slsqp_attempts: list[dict] = []
    candidates = []
    for name, x_start in starts_money:
        obj_start = float(_objective_fn(x_start))
        r = _safe_minimize_money(x_start)
        success = r is not None and r.success
        attempt = {
            'start_name': name,
            'success': bool(success),
            'iterations': int(getattr(r, 'nit', 0)) if r is not None else 0,
            'objective_at_start': obj_start,
            'objective_at_optimal': float(r.fun) if r is not None else None,
            'message': (str(r.message)[:120] if r is not None else 'minimize raised'),
        }
        slsqp_attempts.append(attempt)
        if success:
            candidates.append(r)

    # Audit pass 17 (Антон 2026-05-03): full main-run-equivalent multi-start
    # для anchor. Pass 16 имел только 4 anchor starts (1 seed + 3 pivots),
    # main run использовал 14 (current + 6 pivot_up + 6 balance + all_upper).
    # Если main's narrow-bounds run finds optimum через специфический start
    # (e.g. balance pattern), anchor с reduced multi-start может miss его.
    # Pass 17: anchor использует ИДЕНТИЧНУЮ multi-start strategy (current +
    # all pivots + all balance + all_upper) projected к default_bounds.
    # Mathematically guaranteed: anchor's best ≥ user's narrow-bounds best.
    if _default_anchor_enabled:
        try:
            def _project_to_default_bounds(x):
                x = np.asarray(x, dtype=float).copy()
                for _ in range(3):
                    s = float(np.sum(x))
                    if s <= 1e-10:
                        x = np.array([(b[0] + b[1]) / 2 for b in _default_anchor_bounds])
                        continue
                    x = x * (money_target / s)
                    for i_ in range(len(x)):
                        x[i_] = max(_default_anchor_bounds[i_][0], min(_default_anchor_bounds[i_][1], x[i_]))
                return x

            # Build full multi-start within default_bounds - ИДЕНТИЧНО main run.
            anchor_starts: list[tuple[str, np.ndarray]] = [
                ('def_current', _project_to_default_bounds(x0_money_real.copy())),
            ]
            # All channel-pivot starts (one channel up, others lower, project)
            for pivot_idx in range(n_ch):
                extreme = np.array([_default_anchor_bounds[i_][0] for i_ in range(n_ch)])
                extreme[pivot_idx] = _default_anchor_bounds[pivot_idx][1]
                anchor_starts.append((f'def_pivot_{pivot_idx}', _project_to_default_bounds(extreme)))
            # All «others-at-upper, one-balances» pattern
            for balance_idx in range(n_ch):
                cand = np.array([_default_anchor_bounds[i_][1] for i_ in range(n_ch)], dtype=float)
                other_money = float(sum(cand[i_] for i_ in range(n_ch) if i_ != balance_idx))
                balance_money = money_target - other_money
                if _default_anchor_bounds[balance_idx][0] <= balance_money <= _default_anchor_bounds[balance_idx][1]:
                    cand[balance_idx] = balance_money
                    anchor_starts.append((f'def_balance_{balance_idx}', cand))
            # All-upper
            all_upper_def = np.array([_default_anchor_bounds[i_][1] for i_ in range(n_ch)])
            anchor_starts.append(('def_all_upper', _project_to_default_bounds(all_upper_def)))

            anchor_candidates_local = []
            for _name, x_anchor_start in anchor_starts:
                try:
                    r_a = minimize(
                        _objective_fn, x_anchor_start,
                        method='SLSQP',
                        bounds=_default_anchor_bounds,
                        constraints=constraints,
                        options={'maxiter': 200, 'ftol': 1e-7, 'disp': False},
                    )
                    if r_a.success:
                        anchor_candidates_local.append(r_a)
                except (np.linalg.LinAlgError, ValueError, RuntimeError):
                    pass

            if anchor_candidates_local:
                # Best within default-anchor subspace (lowest fun = max response).
                r_default = min(anchor_candidates_local, key=lambda r: r.fun)
                # Direct candidate с default's x + default's objective. x_default
                # feasible в user's wider bounds (default ⊆ user) → adding direct
                # NOT re-running SLSQP (which может deteriorate в non-convex space).
                class _AnchorResult:
                    def __init__(self, x, fun):
                        self.x = np.asarray(x, dtype=float)
                        self.fun = float(fun)
                        self.success = True
                        self.message = 'default-bounds anchor (full multi-start)'
                        self.nit = int(getattr(r_default, 'nit', 0))
                anchor_candidate = _AnchorResult(r_default.x, r_default.fun)
                candidates.append(anchor_candidate)
                slsqp_attempts.append({
                    'start_name': 'default_anchor_full',
                    'success': True,
                    'iterations': anchor_candidate.nit,
                    'objective_at_start': float(_objective_fn(_default_anchor_x_seed)),
                    'objective_at_optimal': anchor_candidate.fun,
                    'message': f'{anchor_candidate.message} (best of {len(anchor_candidates_local)}/{len(anchor_starts)})',
                })
        except (np.linalg.LinAlgError, ValueError, RuntimeError) as e:
            _logger.warning(f"default_anchor full multi-start SLSQP raised: {type(e).__name__}: {e}")

    # F1 fix (2026-05-03 - Phase 5 follow-up): Cumulative anchor seeding для
    # transitive chain monotonicity (invariant I5b). UI passes prior optimize
    # call's optimal_spend_money через `prev_optimal` config field когда user
    # widens bounds incrementally. We accept it as direct candidate (no SLSQP
    # rerun) - feasible по конструкции when chain is widening (prev_bounds ⊆
    # current_bounds → prev allocation feasible в current bounds).
    #
    # Floor preserved transitively: if prev's objective ≤ current run's best,
    # min(candidates).fun guarantees current ≥ prev. Если prev infeasible
    # в current bounds (user narrowed) или sum mismatch - silent skip + warning.
    #
    # invariant: I5b (chain transitive monotonicity) - registry §I5b. Test
    # flipped from xfail to passing после this fix ships.
    prev_optimal_money = config.get('prev_optimal_money') or config.get('prev_optimal')
    if prev_optimal_money is not None:
        try:
            prev_arr = np.array([float(v) for v in prev_optimal_money], dtype=float)
            if prev_arr.shape != (n_ch,):
                raise ValueError(
                    f"prev_optimal length {prev_arr.shape} != n_ch {n_ch}"
                )
            all_in_bounds = all(
                bounds_money[i][0] - 1e-3 <= prev_arr[i] <= bounds_money[i][1] + 1e-3
                for i in range(n_ch)
            )
            sum_rel_err = abs(float(np.sum(prev_arr)) - money_target) / max(money_target, 1.0)
            if all_in_bounds and sum_rel_err < 0.01:
                class _PrevSeedResult:
                    def __init__(self, x, fun_val):
                        self.x = np.asarray(x, dtype=float)
                        self.fun = float(fun_val)
                        self.success = True
                        self.message = 'cumulative anchor (prev_optimal seed)'
                        self.nit = 0
                prev_obj = float(_objective_fn(prev_arr))
                candidates.append(_PrevSeedResult(prev_arr, prev_obj))
                slsqp_attempts.append({
                    'start_name': 'prev_optimal_anchor',
                    'success': True,
                    'iterations': 0,
                    'objective_at_start': prev_obj,
                    'objective_at_optimal': prev_obj,
                    'message': 'prev_optimal as direct seed (cumulative anchor F1)',
                })
            else:
                _logger.info(
                    f"prev_optimal seed skipped (infeasible в current bounds): "
                    f"all_in_bounds={all_in_bounds}, sum_rel_err={sum_rel_err:.4f}"
                )
        except (TypeError, ValueError) as e:
            _logger.warning(f"prev_optimal parse failed: {type(e).__name__}: {e}. Ignored.")

    if candidates:
        # Best = lowest -response (since we minimize -response).
        result = min(candidates, key=lambda r: r.fun)
    else:
        # All failed - fallback to current allocation, mark non-converged.
        class _FailResult:
            def __init__(self, x0, msg):
                self.x = x0.copy()
                self.success = False
                self.fun = float(_objective_fn(x0))
                self.message = msg
        result = _FailResult(x0_money, "All SLSQP starts failed")

    if not result.success:
        _logger.warning(f"Optimization did not converge: {result.message}")

    # Convert money result back to native for downstream (mROAS, response curves).
    if result.success:
        optimal_spend = np.array([result.x[i] / max(uc_arr[i], 1e-10) for i in range(n_ch)])
    else:
        optimal_spend = np.array([current_spend[col] for col in media_cols])

    # Unified bounds reference for binding-constraint detection (line 553+).
    # Both bounds and result.x в money axis после refactor.
    bounds = bounds_money

    # O1.3 - binding constraints detection. Relative tolerance scaled by
    # problem magnitude (avoids absolute-eps issues on budgets in billions).
    def _is_binding(x_val: float, bound_val: float, scale: float) -> bool:
        return abs(x_val - bound_val) / max(abs(bound_val), scale * 1e-3, 1.0) < 1e-3

    # math-fix v1.0.14.1 - binding scale в money axis (matches refactored bounds).
    _binding_scale = money_target / max(n_ch, 1)
    _n_at_max = sum(1 for i in range(n_ch) if _is_binding(result.x[i], bounds[i][1], _binding_scale))
    _n_at_min = sum(1 for i in range(n_ch) if _is_binding(result.x[i], bounds[i][0], _binding_scale))
    binding_constraints = (_n_at_max == n_ch) or (_n_at_min == n_ch)

    # Compare current vs optimal - math-fix v1.0.16 L10:
    # current_response computed at REAL current allocation (x0_money_real),
    # NOT projected (x0_money). Pre-fix using projected made lift_pct artifact
    # of scale-down/scale-up baseline shift, не measure of redistribution gain.
    #
    # v2.1.0 F-012 (2026-05-18): в planner mode проектировать x0_money_real на
    # forecast horizon ДО передачи в Option C objective. Без projection
    # evaluate_flat_allocation_response получает training_total с n_periods=forecast,
    # вычисляет x_avg_raw = training_total/forecast_n_periods - inflated rate
    # (e.g. Кагоцел 31→12: ×2.58 over actual rate) → super-saturated Hill →
    # inflated current_response_real → negative lift artifact. Analyst mode
    # horizon_scale=1.0, x0_money_baseline == x0_money_real (unchanged behavior).
    x0_money_baseline = x0_money_real * horizon_scale
    current_response_real = -_objective_fn(x0_money_baseline)
    optimal_response = -_objective_fn(result.x)

    # ─── Phase 2.7 (5a): Canonical lift% formula (2026-05-04 / SSOT 2026-05-24) ─
    # Pre-fix: lift = (optimal_media - current_media) / current_media (media-only ratio).
    # Это давало misleading high values (+4.7% Кагоцел) когда baseline >> media.
    # Three engines (optimizer, scenario, frontend) had three different formulas.
    # Now: canonical formula = (total_optimal - total_current) / total_current
    # где total_kpi = baseline_total + media_total (both в money axis).
    # Selection logic (y_std degeneracy, AURORA_LEGACY_LIFT_FORMULA env, baseline_zero
    # fallback) живёт в engines/lift.py SSOT — identical semantics к scenario.py call.
    # Legacy media-only ratio preserved as `media_only_lift_pct` result field + fallback.
    #
    # CRITICAL SCALE NOTE (2026-05-04 follow-up): `_objective_fn` returns sum
    # `Σ β·hill(...)·n_periods` in NORMALIZED scale (β is normalized coefficient).
    # Multiplied by `y_std` → money-axis value, comparable с baseline_total.
    # Without × y_std mixed-scale bug: baseline (10.4B money) + media (6 norm)
    # → media drowns in float arithmetic, lift_pct = 0.0% даже когда media-only
    # changes на 17.7%. Customer reproduced на Кагоцел project (9): legacy
    # lift_pct=17.7% but canonical=0.0% pre-fix.
    from engines.lift import select_lift_pct as _select_lift_pct
    y_mean_lift = float(norm.get('y_mean', 0.0))
    intercept_mean_lift = float(norm.get('intercept_mean', 0.0))

    baseline_per_period_lift = intercept_mean_lift * y_std + y_mean_lift
    non_media_baseline_total = baseline_per_period_lift * forecast_n_periods

    # Convert media responses (returned in normalized scale by _objective_fn) к money axis.
    current_media_money = float(current_response_real) * y_std
    optimal_media_money = float(optimal_response) * y_std

    # Legacy media-only ratio (engine-specific fallback + result field).
    if current_response_real > 1e-9:
        media_only_lift_pct = (optimal_response - current_response_real) / current_response_real * 100
    else:
        media_only_lift_pct = 0.0
        _logger.warning(
            "current_response_real ≤ 0 - degenerate media baseline. media_only_lift_pct undefined."
        )

    # Canonical: total business KPI ratio (both terms in money axis).
    total_current_kpi = non_media_baseline_total + current_media_money
    total_optimal_kpi = non_media_baseline_total + optimal_media_money

    # SSOT formula application — engines/lift.py.
    # Encapsulates: canonical formula, y_std degeneracy, AURORA_LEGACY_LIFT_FORMULA env,
    # baseline_zero fallback. Diagnostics expose internal state для insight messaging.
    lift_pct, _lift_diag = _select_lift_pct(
        total_optimal_kpi=total_optimal_kpi,
        total_current_kpi=total_current_kpi,
        legacy_fallback_pct=media_only_lift_pct,
        y_std=y_std,
    )
    # baseline_zero + y_std_degenerate consumed downstream (insight messaging line
    # ~1437, result_data flag line ~1505). canonical_lift_pct sole value live в
    # lift_diagnostics['canonical_lift_pct'] field (operator observability).
    baseline_zero = _lift_diag.baseline_zero
    y_std_degenerate = _lift_diag.y_std_degenerate
    # Persist diagnostic trace для downstream observability (env override visibility,
    # selection branch debugging). INV-37: SSOT override comprehensive coverage —
    # operator may flip AURORA_LEGACY_LIFT_FORMULA, optimization.json snapshot tracks
    # which formula path был active при compute.
    lift_diagnostics = _lift_diag.as_dict()

    # math-fix v1.0.14.1 + v1.0.16 - false convergence detector.
    # SLSQP может вернуть success=True at iter=1 если стартовая точка локально
    # стабильна (KKT удовлетворяется тривиально). Этот flag поднимается когда
    # optimizer вернул practically projected-current allocation (i.e. no
    # redistribution found within new money_target).
    #
    # SA6 (audit 2026-04-28): сравниваем result.x с x0_money (projected),
    # NOT x0_money_real. Logic: «no redistribution» = result ≈ scaled-current.
    # When money_target = current_total → x0_money == x0_money_real → unchanged
    # behavior. When money_target ≠ current → projected baseline detects
    # «proportional cut/grow without redistribution» = the meaningful warning.
    _max_abs_delta_money = float(max(
        abs(result.x[i] - x0_money[i]) for i in range(n_ch)
    )) if n_ch else 0.0
    _normalized_delta = _max_abs_delta_money / max(money_target / max(n_ch, 1), 1.0)
    converged_at_current = (
        result.success
        and not binding_constraints
        and abs(lift_pct) < 0.5
        and _normalized_delta < 0.01  # < 1% of average channel money
    )

    channels = []
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        # v2.1.0 F-012: forecast-horizon-projected current для fair comparison
        # с optimal_spend (которое уже forecast-scale через money_target).
        # Analyst mode horizon_scale=1.0 → cur_baseline == cur (unchanged).
        cur_baseline = cur * horizon_scale
        opt = optimal_spend[i]
        delta_pct = (opt - cur_baseline) / cur_baseline * 100 if cur_baseline > 0 else 0

        # F0.2 (Phase 0.1 fix-session 2026-04-25): canonical mROAS chain rule
        # with adstock_factor + unit_cost normalization. See
        # docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3 for full derivation.
        #
        # Pre-fix bugs (closed by F0.2):
        #   #11 missing adstock_factor → mROAS off by 2-15× depending on θ
        #   #12 missing /unit_cost     → TRPs (uc=250000) showed 1780× absurd
        # Both closed by single helper _compute_mroas_money() that returns
        # ∂KPI(money)/∂s(money) - comparable across native and money channels.
        # C1 fix (audit 2026-04-26): prefer adstock_mean_posterior (v1.2+) for math consistency.
        mean_post_opt = p.get('adstock_mean_posterior')
        mean_ch = float(mean_post_opt) if mean_post_opt is not None else (float(media_means.get(col, 1)) or 1)
        a_type = _adstock_type(col)
        uc = float(unit_costs.get(col, 1.0) or 1.0)
        # v2.1.0 (ADR-020): training-time uc per channel (1.0 если pickle pre-fix).
        uc_train_ch = float(uc_train_arr[i])

        decay_pt = p.get('decay')  # Phase 1.1: posterior mean decay; None for legacy pickles
        # G1 fix: planning mode threads forecast_n_periods через mROAS - marginal
        # ROI estimated per planning horizon, не training (analyst mode unchanged).
        # v2.1.0 F-012 sister: current_spend_native=cur_baseline (forecast-projected)
        # для consistent per-period rate. cur (training_total) деленный на forecast_n
        # давал inflated rate → wrong mROAS at current point. Optimal uses opt as-is
        # since result.x already в forecast scale.
        mroi_current = _compute_mroas_money(
            current_spend_native=cur_baseline,
            n_periods=forecast_n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
            decay=decay_pt,
            uc_at_training=uc_train_ch,
        )
        mroi_optimal = _compute_mroas_money(
            current_spend_native=float(opt),
            n_periods=forecast_n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
            decay=decay_pt,
            uc_at_training=uc_train_ch,
        )

        # Phase 1.9: posterior CI on mROAS via vectorized chain rule + arviz.hdi.
        # Defensive: only compute if samples exist AND channel found in samples ordering.
        mroi_current_ci_low = None
        mroi_current_ci_high = None
        mroi_optimal_ci_low = None
        mroi_optimal_ci_high = None
        if posterior_samples is not None:
            ch_samples = per_channel_samples(posterior_samples, col)
            if ch_samples is not None:
                decay_s = ch_samples.get('decay')  # Phase 1.1: per-sample decay or None
                # F1 fix (audit 2026-04-27): per-sample TRAINING adstock mean for math
                # consistency with in-model normalization. df is training data (loaded
                # at line 302 from config_model.data_file). When decay_s is None
                # (legacy pickles), helper returns scalar fallback = mean_ch.
                # v2.1.0 (pilot D2 round 2 R01 2026-05-17): pre-multiply на uc_train
                # ДО compute_train_adstock_mean_samples - mean_for_samples должен
                # быть в той же scaled scale что training (иначе x_norm broken).
                train_raw_for_col = df[col].fillna(0).values.astype(float) if col in df.columns else None
                if train_raw_for_col is not None:
                    if uc_train_ch != 1.0 and uc_train_ch > 0:
                        train_raw_for_col = train_raw_for_col * uc_train_ch
                    mean_for_samples = compute_train_adstock_mean_samples(
                        train_raw_for_col, decay_s, a_type=a_type, fallback_scalar=mean_ch
                    )
                else:
                    mean_for_samples = mean_ch
                cur_arr = _compute_mroas_money_samples(
                    current_spend_native=cur_baseline,  # F-012: forecast-projected
                    n_periods=forecast_n_periods,
                    mean=mean_for_samples,
                    alpha_samples=ch_samples['alpha'],
                    gamma_samples=ch_samples['gamma'],
                    beta_samples=ch_samples['beta'],
                    adstock_type=a_type,
                    y_std=y_std,
                    unit_cost=uc,
                    decay_samples=decay_s,
                    uc_at_training=uc_train_ch,
                )
                _, mroi_current_ci_low, mroi_current_ci_high, _m_cur = compute_ci_hdi(cur_arr)

                opt_arr = _compute_mroas_money_samples(
                    current_spend_native=float(opt),
                    n_periods=forecast_n_periods,
                    mean=mean_for_samples,
                    alpha_samples=ch_samples['alpha'],
                    gamma_samples=ch_samples['gamma'],
                    beta_samples=ch_samples['beta'],
                    adstock_type=a_type,
                    y_std=y_std,
                    unit_cost=uc,
                    decay_samples=decay_s,
                    uc_at_training=uc_train_ch,
                )
                _, mroi_optimal_ci_low, mroi_optimal_ci_high, _m_opt = compute_ci_hdi(opt_arr)

        # L11 (math-fix v1.4 Section C, 2026-04-29): display_name для UI consistency.
        from engines.narrative_adapter import _normalize_channel_name
        display_name = _normalize_channel_name(col) or col
        # v2.1.0 F-012 (2026-05-18 follow-up): SEPARATE display fields from math
        # baseline. current_spend/current_spend_money остаются training-scale (raw
        # cur × uc) для consistent UI display между Decompose / Optimize «Текущий
        # бюджет» cards + ForecastHorizonPicker auto-suggest. Forecast-scale
        # equivalents добавлены как *_baseline fields — frontend может использовать
        # для apples-to-apples per-channel comparison в planner mode.
        # delta_pct + mROAS уже using cur_baseline через math chain (см. выше).
        # Analyst mode horizon_scale=1 → baseline fields == raw fields (byte-exact).
        ch_dict = {
            'name': col,
            'display_name': display_name,
            'current_spend': round(cur, 0),
            'optimal_spend': round(float(opt), 0),
            'current_spend_money': round(cur * uc, 0),
            'optimal_spend_money': round(float(opt) * uc, 0),
            # Forecast-horizon-projected current (= raw в analyst, scaled в planner)
            'current_spend_baseline': round(cur_baseline, 0),
            'current_spend_money_baseline': round(cur_baseline * uc, 0),
            'unit_cost': uc,
            'delta_pct': round(delta_pct, 1),
            'mroi_current': round(mroi_current, 4),
            'mroi_optimal': round(mroi_optimal, 4),
        }
        if mroi_current_ci_low is not None:
            ch_dict['mroi_current_ci_low'] = round(float(mroi_current_ci_low), 4)
            ch_dict['mroi_current_ci_high'] = round(float(mroi_current_ci_high), 4)
            ch_dict['mroi_optimal_ci_low'] = round(float(mroi_optimal_ci_low), 4)
            ch_dict['mroi_optimal_ci_high'] = round(float(mroi_optimal_ci_high), 4)
        channels.append(ch_dict)

    # L4 (math-fix v1.4 Section C, 2026-04-28): decorate с prescriptive action
    # fields через single-source-of-truth compute_channel_action. Replaces old
    # primitive `action: 'увеличить'/'сократить'/'сохранить'` (delta_pct heuristic)
    # с full ACTION_KEYS vocabulary (Scale/Hold/Watch/Reduce/Cut/Uncertain). Same
    # helper used decomposer.py + narrative_adapter.py - three-way alignment.
    from engines.channel_action import compute_channel_action
    for ch in channels:
        # alias mroi_current → mroas + mroi_current_ci_* → mroas_ci_* per
        # compute_channel_action API contract (matches narrative_adapter pattern).
        action_input = {
            **ch,
            'mroas': ch.get('mroi_current'),
            'mroas_ci_low': ch.get('mroi_current_ci_low'),
            'mroas_ci_high': ch.get('mroi_current_ci_high'),
        }
        action = compute_channel_action(action_input)
        ch['action'] = action.key
        ch['action_label'] = action.label_ru
        ch['action_tone'] = action.tone
        ch['action_reasoning'] = action.reasoning
        ch['action_priority'] = action.priority
        ch['action_confidence'] = action.confidence

    # Generate response curves data (for charts)
    # Post-audit fix: response_curve domain in normalized space, displayed against
    # raw spend. Response × y_std → KPI scale (was: y_norm scale, mis-leading numbers).
    response_curves_data = {}
    # Audit pass 15 (Антон 2026-05-03 cont): pass 13 (global_upper) made
    # curves reach uniform x-end, но channels с small relevant range looked
    # squashed/flat за пределами их saturation point. Hill α (крутизна) +
    # γ (half-sat point) обученные posterior могут давать sharp S-curve
    # → channel plateaus в 1-5% of forced global x-range, остальное - flat.
    # Customer asked «уверены ли в shape». Math correct (Hill behavior),
    # но visualization cubicly bad с global axis.
    #
    # Better: per-channel upper = max(2×cur_money, 2×optimal_money,
    # fallback_max_money) / unit_cost. Each channel's curve fits в свой
    # informative range; xAxis frontend adapts (audit pass 9 - channelBudgets
    # × 1.5 max). Cross-channel comparison achieved via shared y-scale,
    # не x-scale forcing.

    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        mean_ch = float(media_means.get(col, 1)) or 1
        a_type = _adstock_type(col)
        uc_col = float(unit_costs.get(col, 1.0) or 1.0)
        # Per-channel reasonable upper: 2× current OR 2× optimal - больший,
        # чтобы curve покрывала и текущий и предлагаемый optimal с headroom.
        # Fallback к fallback_max_money / uc когда нет current spend.
        cur_money = cur * uc_col
        opt_money = float(optimal_spend[i]) * uc_col
        channel_max_money = max(cur_money * 2, opt_money * 2, fallback_max_money)
        channel_upper_native = channel_max_money / max(uc_col, 1e-10)
        if channel_upper_native <= 0:
            channel_upper_native = mean_ch * 2 * forecast_n_periods
        upper = channel_upper_native
        spend_range = np.linspace(0, upper, 50)
        # Per-period equivalent for Hill input
        per_period_avg = spend_range / forecast_n_periods
        # v2.1.0 (pilot D2 round 2 R04 2026-05-17): pre-multiply per_period_avg
        # на uc_train ДО adstock для symmetry с training mean_ch scale. Без этого
        # response curves для TRPs/native каналов давали flat line (response ≈ 0)
        # потому что native_adstock / scaled_mean ≈ 0.
        uc_train_rc = float(uc_train_arr[i]) if i < len(uc_train_arr) else 1.0
        per_period_for_hill = per_period_avg * uc_train_rc if uc_train_rc != 1.0 else per_period_avg
        decay_pt_rc = p.get('decay')  # Phase 1.1: posterior mean decay for response curve adstock
        adstocked_avg = np.array([_flat_alloc_adstock_avg(float(x), forecast_n_periods, a_type, decay_pt_rc) for x in per_period_for_hill])
        spend_range_norm = adstocked_avg / max(mean_ch, 1e-10)
        responses_norm = response_curve(spend_range_norm, p['alpha'], max(p['gamma'], 1e-6), p['beta'])
        # Total contribution = per-period response × forecast_n_periods × y_std
        responses_kpi = responses_norm * y_std * forecast_n_periods
        response_curves_data[col] = {
            'spend': spend_range.tolist(),
            'response': responses_kpi.tolist(),
            'current_x': cur,
            'optimal_x': float(optimal_spend[i]),
        }

    # Money-эквиваленты total_budget: Hill-оптимизация ведётся в нативных единицах
    # каналов (TRP пункты + рубли), но пользователь хочет видеть суммы в валюте KPI.
    total_budget_money = sum(float(optimal_spend[i]) * float(unit_costs.get(col, 1.0) or 1.0)
                             for i, col in enumerate(media_cols))
    total_current_money = sum(current_spend[col] * float(unit_costs.get(col, 1.0) or 1.0)
                              for col in media_cols)

    _sign = '+' if lift_pct >= 0 else ''
    # math-fix v1.0.14.1 + v1.0.16 - narrative-aware insight.
    # baseline_zero (L10 edge case): real current media contribution = 0 → lift_pct
    # undefined. Honest message вместо vacuous «прирост 0%».
    if baseline_zero:
        insight = (
            f"Текущее распределение даёт нулевой медиа-вклад - невозможно "
            f"вычислить прирост в процентах. Оптимизатор предлагает распределение "
            f"({round(total_budget_money, 0):,.0f} ₽), но baseline для сравнения "
            f"degenerate. Проверьте данные media_columns."
        )
    elif converged_at_current:
        insight = (
            f"Оптимизатор сошёлся на текущем распределении (бюджет "
            f"{round(total_budget_money, 0):,.0f} ₽). Это может означать что "
            f"границы Min/Max задают слишком узкий коридор, либо текущая "
            f"аллокация уже близка к локальному оптимуму. Попробуйте расширить "
            f"границы (10/300%) или экспертный режим."
        )
    else:
        insight = f"Оптимальное перераспределение бюджета ({round(total_budget_money, 0):,.0f} ₽) даёт ожидаемый прирост {_sign}{lift_pct:.1f}%."
        top_increase = max(channels, key=lambda x: x['delta_pct'])
        top_decrease = min(channels, key=lambda x: x['delta_pct'])
        if top_increase['delta_pct'] > 5:
            insight += f" Увеличить {top_increase['name']} на {top_increase['delta_pct']:.0f}%."
        if top_decrease['delta_pct'] < -5:
            insight += f" Сократить {top_decrease['name']} на {abs(top_decrease['delta_pct']):.0f}%."

    # A3/OPP-03 (2026-07-03): единый язык extrapolation-тиров на forward-
    # оптимизации. Goal-seek (F-01) и сценарии (F-04) уже помечают выход
    # per-period трат за наблюдавшийся диапазон (канонические тиры p95/p99,
    # Chan & Perry 2017 Fig. 2: кривая вне наблюдённого диапазона не
    # идентифицируется данными) — forward-рекомендация обязана говорить тем же
    # языком: optimal_spend_money канала vs его история в НАТИВНЫХ единицах.
    extrapolation = None
    try:
        from utils.forecast_validation import extrapolation_severity
        _ex_channels = []
        _ex_max = 0
        for _ch in channels:
            _money = float(_ch.get('optimal_spend_money') or 0)
            _name = _ch.get('name')
            if _money <= 0 or _name not in df.columns:
                continue
            _uc_c = float(unit_costs.get(_name, 1.0) or 1.0)
            _pp_native = (_money / _uc_c) / max(int(forecast_n_periods), 1)
            _hist = df[_name].fillna(0).to_numpy(dtype=float)
            _hist_pos = _hist[_hist > 0]
            if _hist_pos.size == 0:
                continue
            _q = {
                'p95': float(np.quantile(_hist_pos, 0.95)),
                'p99': float(np.quantile(_hist_pos, 0.99)),
            }
            _sev = extrapolation_severity(_pp_native, _q)
            _ex_max = max(_ex_max, _sev)
            if _sev > 0:
                _hist_max = float(_hist.max())
                _ex_channels.append({
                    'name': _name,
                    'per_period_native': round(_pp_native, 2),
                    'hist_max_native': round(_hist_max, 2),
                    'ratio_vs_max': round(_pp_native / _hist_max, 2) if _hist_max > 0 else None,
                    'severity': _sev,
                })
        extrapolation = {'severity': _ex_max, 'channels': _ex_channels}
    except Exception:  # noqa: BLE001 - honesty-контур не роняет оптимизацию
        extrapolation = None

    result_data = {
        'status': 'ok',
        'extrapolation': extrapolation,
        'total_budget': round(total_budget, 0),
        'total_budget_money': round(total_budget_money, 0),
        'total_current_money': round(total_current_money, 0),
        'expected_lift_pct': round(lift_pct, 1),
        # 5a (2026-05-04): legacy media-only ratio preserved для expert mode UI
        # + AURORA_LEGACY_LIFT_FORMULA rollback. Canonical formula = total KPI ratio.
        'media_only_lift_pct': round(media_only_lift_pct, 1),
        # SSOT trace (2026-05-24): which formula path was active at compute time.
        # Operator visibility into env override + degeneracy fallback paths.
        'lift_diagnostics': lift_diagnostics,
        'total_current_kpi': round(total_current_kpi, 0),
        'total_optimal_kpi': round(total_optimal_kpi, 0),
        # v2.1.0 (ADR-021): money equivalents для count KPI при kpi_unit_cost задан.
        # Frontend OptimizeStep отображает money primary + count в скобках.
        # None для count KPI без kpi_unit_cost - frontend показывает native count.
        'kpi_unit_cost': kpi_unit_cost,
        'total_current_kpi_money': (
            round(total_current_kpi * kpi_unit_cost, 0)
            if kpi_unit_cost is not None and kpi_kind == 'count'
            else (round(total_current_kpi, 0) if kpi_kind == 'monetary' else None)
        ),
        'total_optimal_kpi_money': (
            round(total_optimal_kpi * kpi_unit_cost, 0)
            if kpi_unit_cost is not None and kpi_kind == 'count'
            else (round(total_optimal_kpi, 0) if kpi_kind == 'monetary' else None)
        ),
        'channels': channels,
        'response_curves': response_curves_data,
        'insight': insight,
        'optimization_converged': result.success,
        # O1.3 (Phase 0.1 fix-session): binding constraints diagnostics. Used by
        # narrative_adapter to surface "оптимизатор упёрся в границы" instead of
        # vacuous "сохранить аллокацию" recommendations.
        'binding_constraints': bool(binding_constraints),
        'n_channels_at_max': int(_n_at_max),
        'n_channels_at_min': int(_n_at_min),
        'min_pct_used': float(min_pct_global * 100),
        'max_pct_used': float(max_pct_global * 100),
        # math-fix v1.0.14.1, A1 (audit-of-audit 2026-04-28):
        # - converged_at_current: SLSQP отдал current allocation без binding (false convergence).
        # - slsqp_diagnostics: per-start outcomes для post-mortem (UI/log debugging).
        'converged_at_current': bool(converged_at_current),
        # math-fix v1.0.16, L10: baseline_zero flag - real current media contribution = 0,
        # lift_pct undefined. UI должен suppress lift display + show diagnostic banner.
        'baseline_zero': bool(baseline_zero),
        # Phase 2 (Planning Mode) metadata - present always (analyst mode echoes
        # n_periods == forecast_n_periods and planning_mode=False для UI consistency).
        'planning_mode': bool(planning_mode),
        'train_n_periods': int(n_periods),
        'forecast_n_periods': int(forecast_n_periods),
        'slsqp_diagnostics': {
            'n_starts': len(slsqp_attempts),
            'n_converged': sum(1 for a in slsqp_attempts if a['success']),
            'best_objective': float(result.fun) if result.success else None,
            'attempts': slsqp_attempts,
        },
    }

    # M2 honesty-gate (2026-06-13, PRD §п2): model-reliability verdict, который
    # оптимизатор обязан нести ДО того, как UI покажет переброску. SSOT =
    # results/model-diagnostics.json (pickle.mcmc_diagnostics пуст; rHat/divergences/
    # ratio живут только там). Гибрид: unreliable→refused (UI прячет переброску),
    # uncertain→caveat+бенды, reliable→как есть. См. utils.optimizer_honesty +
    # tools/probe_optimizer_honesty_kagocel.py (гэп доказан на реальном Кагоцеле).
    from utils.optimizer_honesty import (
        load_model_diagnostics,
        model_reliability_verdict,
    )
    result_data['model_reliability'] = model_reliability_verdict(
        load_model_diagnostics(project_path))

    # Save (NaN-safe 2026-06-04 аудит: NaN→null, иначе Rust serde_json роняет файл).
    from utils.safe_io import sanitize_nonfinite
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'optimization.json', 'w', encoding='utf-8') as f:
        json.dump(sanitize_nonfinite(result_data), f, ensure_ascii=False, indent=2)

    return result_data
