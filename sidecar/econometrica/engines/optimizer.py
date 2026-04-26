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
from utils.posterior_propagation import compute_ci_hdi, load_posterior_samples, per_channel_samples


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
    Берём среднее за период — это эквивалент того что training Hill видел
    усреднённо.

    Phase 1.1: optional decay parameter — when v1.2 pickle, posterior mean decay
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
    """∂(_flat_alloc_adstock_avg)/∂(x_per_period) — sensitivity factor.

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
    # weibull / unknown — central difference (exact for linear convolution).
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
) -> float:
    """Marginal ROAS in money-per-money — single source of truth.

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
        Marginal ROAS — ∂KPI(money)/∂spend(money). Unitless ratio.
        Returns 0.0 for degenerate inputs (zero spend, zero mean, zero beta).
    """
    if current_spend_native <= 0:
        return 0.0
    if mean <= 0 or beta == 0 or n_periods < 1 or unit_cost <= 0:
        return 0.0

    x_pp = current_spend_native / n_periods
    adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, adstock_type, decay)
    x_norm = adstock_avg / max(mean, 1e-10)

    # Hill derivative (normalized space): hill'(x) = α·γ^α·x^(α-1) / (x^α + γ^α)²
    g_safe = max(gamma, 1e-10)
    x_safe = max(x_norm, 1e-10)
    hill_deriv = (alpha * (g_safe ** alpha) * (x_safe ** (alpha - 1))) / (
        (x_safe ** alpha + g_safe ** alpha) ** 2
    )

    af = _adstock_factor(x_pp, n_periods, adstock_type, decay)

    # Chain rule: KPI(money) per native spend
    mroas_native = beta * hill_deriv * af * y_std / max(mean, 1e-10)
    # Convert to per-money axis
    return float(mroas_native / unit_cost)


def _compute_mroas_money_samples(
    *,
    current_spend_native: float,
    n_periods: int,
    mean: float,
    alpha_samples: np.ndarray,
    gamma_samples: np.ndarray,
    beta_samples: np.ndarray,
    adstock_type: str,
    y_std: float,
    unit_cost: float = 1.0,
    decay_samples: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorized mROAS over posterior samples (Phase 1.9 + 1.1).

    Returns array of mROAS values across all posterior draws — caller computes
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
        decay_samples: optional 1D shape (n_samples,) — Phase 1.1 sampled adstock decay.
            None → falls back to library default 0.5 (Phase 1.9 path).

    Returns:
        np.ndarray shape (n_samples,) of mROAS values. All zeros for degenerate inputs.
    """
    n = int(np.asarray(alpha_samples).size)
    if current_spend_native <= 0 or mean <= 0 or n_periods < 1 or unit_cost <= 0 or n == 0:
        return np.zeros(max(n, 1), dtype=np.float64)

    x_pp = current_spend_native / n_periods

    if decay_samples is not None and adstock_type == 'geometric':
        # Phase 1.1: vectorized per-sample adstock_avg + adstock_factor
        decays = np.asarray(decay_samples, dtype=np.float64)
        # adstock_avg(x_pp, n; θ) = x_pp · [n - θ·(1 - θ^n)/(1-θ)] / [n·(1-θ)]
        theta = np.clip(decays, 0.0, 1.0 - 1e-9)
        n_p = n_periods
        with np.errstate(divide='ignore', invalid='ignore'):
            geom_sum = (1.0 - theta ** n_p) / (1.0 - theta)
            af_per_sample = (n_p - theta * geom_sum) / (n_p * (1.0 - theta))
        af_per_sample = np.where(theta < 1e-9, 1.0, af_per_sample)
        adstock_avg_per_sample = x_pp * af_per_sample  # (n_samples,)
        x_norm_per_sample = adstock_avg_per_sample / max(mean, 1e-10)  # (n_samples,)

        # Per-sample Hill derivative — broadcast manually for joint correlation.
        # hill'(x) = α · γ^α · x^(α-1) / (x^α + γ^α)²
        alpha = np.asarray(alpha_samples, dtype=np.float64)
        gamma = np.asarray(gamma_samples, dtype=np.float64)
        x_safe = np.maximum(x_norm_per_sample, 1e-10)
        gamma_safe = np.maximum(gamma, 1e-10)
        x_pow = x_safe ** alpha
        gamma_pow = gamma_safe ** alpha
        hill_deriv_arr = (alpha * gamma_pow * (x_safe ** (alpha - 1.0))) / ((x_pow + gamma_pow) ** 2)
        af_arr = af_per_sample
    else:
        # Phase 1.9 fallback: scalar adstock_avg/factor (decay constant 0.5).
        adstock_avg = _flat_alloc_adstock_avg(x_pp, n_periods, adstock_type)
        x_norm = adstock_avg / max(mean, 1e-10)
        hill_deriv_arr = hill_derivative_batch(
            np.array([x_norm]), alpha_samples, gamma_samples
        ).ravel()
        af_arr = _adstock_factor(x_pp, n_periods, adstock_type)

    # Chain rule per-sample
    beta_arr = np.asarray(beta_samples, dtype=np.float64)
    mroas_native = beta_arr * hill_deriv_arr * af_arr * y_std / max(mean, 1e-10)
    return mroas_native / unit_cost


def optimize(config: dict, project_dir: str) -> dict[str, Any]:
    """Optimize budget allocation across channels.

    Args:
        config: {
            'total_budget': float|None,  # None = use current total
            'min_pct': float,            # Глобальный Min % (default 50). Используется
                                         # как fallback если нет per-channel constraint.
            'max_pct': float,            # Глобальный Max % (default 150).
            'min_per_channel': dict|None,# Опционально: {channel: min_pct} — экспертный режим.
                                         # Если задан для канала, перекрывает глобальный min_pct.
            'max_per_channel': dict|None,# Опционально: {channel: max_pct} — экспертный режим.
        }
        project_dir: Path to project with models/latest.pkl

    Returns:
        JSON with current vs optimal allocation, response curves, expected lift
    """
    project_path = Path(project_dir)
    model_path = project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {'status': 'error', 'message': 'Модель не найдена'}

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

    config_model = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    media_cols = config_model['media_columns']
    # y_std needed for KPI-scale conversions of mROI and response curves.
    y_std = float(norm.get('y_std', 1.0)) or 1.0

    # Phase 1.9: posterior samples for honest CI on mROAS. None for v1.0/v1.1 pickles.
    # When available, mroi_current/optimal include {mean, ci_low, ci_high} dicts.
    posterior_samples = load_posterior_samples(model_data)

    # A1 fix (post-audit v1.2): exclude untrained channels from optimization domain.
    # Channels with zero training variance have β from prior (uninformative) — optimizer
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
                    'данных. Оптимизация невозможна — переобучите модель.'
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

    current_spend = {col: float(df[col].fillna(0).sum()) for col in media_cols}
    total_current = sum(current_spend.values())
    n_periods = max(len(df), 1)

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
    # (Σ x_native × unit_cost == total_budget_money). Иначе — native constraint как раньше.
    total_budget_money_target = config.get('total_budget_money')
    uc_arr = [float(unit_costs.get(col, 1.0) or 1.0) for col in media_cols]

    # P0-11 fix (math-fix-v1.0.13) + Phase 0.1 live-test refinement:
    # Detect real unit_smell — native-unit channel (TRPs/clicks/impressions) with
    # default uc=1.0 (CPP/CPM не задан). Это арифметически некорректный mix.
    # Если unit_smell нет — auto-compute money budget из current spend × uc и идём
    # в money-mode без error. Это типичный кейс russian client: digital в рублях
    # (uc=1) + TV в TRPs (uc=CPP) — раньше guard блокировал false-positively.
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
        total_budget = config.get('total_budget') or total_current

    min_pct_global = config.get('min_pct', 50) / 100
    max_pct_global = config.get('max_pct', 150) / 100

    # Per-channel constraints (экспертный режим). Если для канала задан явный
    # min/max в процентах — используется он, иначе глобальный.
    min_per_channel = config.get('min_per_channel') or {}
    max_per_channel = config.get('max_per_channel') or {}

    def channel_min(col: str) -> float:
        return min_per_channel.get(col, min_pct_global * 100) / 100

    def channel_max(col: str) -> float:
        return max_per_channel.get(col, max_pct_global * 100) / 100

    # F1+F2 fix (math-audit v1.3): per-period averaging + adstock matches
    # training and scenario semantics. Pre-fix optimizer used:
    #     x_norm = spend_vector[i] / mean    # spend_vector = TOTAL spend over n_periods!
    # → x_norm typically 30-100× для TRPs-heavy → Hill saturated ≈1.0 → SLSQP stuck.
    # Now: per-period avg + adstock factor matching training, contribution × n_periods
    # to scale to total predicted KPI delta units.
    def total_response(spend_vector):
        total = 0
        for i, col in enumerate(media_cols):
            p = channel_params[col]
            # C1 fix: prefer adstock_mean_posterior (v1.2+) for math consistency.
            mean_posterior = p.get('adstock_mean_posterior')
            mean = float(mean_posterior) if mean_posterior is not None else (float(media_means.get(col, 1)) or 1)
            decay_pt = p.get('decay')  # Phase 1.1: None for v1.0/v1.1/v1.1.5 → default 0.5
            x_avg_raw = spend_vector[i] / n_periods
            x_avg_adstock = _flat_alloc_adstock_avg(x_avg_raw, n_periods, _adstock_type(col), decay_pt)
            x_norm = x_avg_adstock / max(mean, 1e-10)
            sat = hill_function(np.array([max(x_norm, 0)]), alpha=p['alpha'], gamma=max(p['gamma'], 1e-6))
            total += p['beta'] * sat[0] * n_periods
        return -total  # Negative for minimization

    # Constraints
    # Post-audit fix: zero-spend channels would have bounds=(0,0) → fixed at zero.
    # Allow optimizer to test channels with current=0 by giving them a default
    # bound = (0, total_budget × max_pct/n_channels) so they CAN receive budget.
    n_ch = max(len(media_cols), 1)
    fallback_max = max(total_budget * max_pct_global / n_ch, 1.0)

    def _bounds_for(col: str) -> tuple[float, float]:
        cs = current_spend[col]
        if cs > 0:
            return (cs * channel_min(col), cs * channel_max(col))
        # Zero-spend channel: allow up to fallback_max
        return (0.0, fallback_max)

    if total_current > 0:
        x0 = np.array([current_spend[col] * total_budget / total_current for col in media_cols])
    else:
        # Even-split fallback if no current spend at all (degenerate but recoverable)
        x0 = np.array([total_budget / n_ch for _ in media_cols])
    bounds = [_bounds_for(col) for col in media_cols]

    # O1.3 (Phase 0.1 fix-session 2026-04-25): pre-flight feasibility check.
    # Without this, infeasible bounds (e.g. budget > sum(upper bounds)) made
    # SLSQP iterate fruitlessly until Tauri 60s timeout, leading to sidecar
    # crash + watchdog respawn. Check in MONEY units (mixed-units safe).
    sum_upper_money = sum(bounds[i][1] * uc_arr[i] for i in range(n_ch))
    sum_lower_money = sum(bounds[i][0] * uc_arr[i] for i in range(n_ch))
    money_target = total_budget_money_target if total_budget_money_target is not None else (
        sum(current_spend[c] * uc_arr[i] for i, c in enumerate(media_cols))
    )
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

    if total_budget_money_target is not None:
        # Money constraint: Σ x × unit_cost == total_budget_money
        constraints = [{
            'type': 'eq',
            'fun': lambda x: float(np.sum(np.asarray(x) * np.asarray(uc_arr)) - total_budget_money_target),
        }]
    else:
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - total_budget}]

    # O2 (Phase 0.1): SLSQP hardening — wrap in try/except, hard maxiter cap.
    # Previously: a divergent SLSQP iteration could hang Python beyond Tauri's
    # 60s timeout → watchdog respawn (90s downtime).
    #
    # Phase 0.1 hotfix #19 (2026-04-26): MULTI-START SLSQP. Live-test revealed
    # that with money_target = current (no budget change), SLSQP starts at
    # current allocation = local minimum для objective и не двигается → lift=0%.
    # Solution: try 3 starting points (current + 2 perturbed) and keep best
    # converged result. Cheap (n_periods × 6 channels × 200 iter × 3 starts =
    # ~20k function evals, sub-second). Catches local optima without UX changes.
    import logging
    _logger = logging.getLogger('econometrica')

    def _safe_minimize(x_start):
        try:
            r = minimize(
                total_response, x_start,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 200, 'ftol': 1e-7, 'disp': False},
            )
            return r
        except (np.linalg.LinAlgError, ValueError, RuntimeError) as e:
            _logger.warning(f"SLSQP attempt failed: {type(e).__name__}: {e}")
            return None

    # Multi-start: current allocation + 2 perturbed (random shifts within bounds,
    # respecting sum constraint via projection).
    rng = np.random.default_rng(42)  # deterministic across calls
    starts = [x0]
    for _ in range(2):
        # Random allocation within bounds, then scale to match sum constraint.
        perturbed = np.array([
            rng.uniform(bounds[i][0], bounds[i][1]) for i in range(n_ch)
        ])
        # Scale to satisfy sum constraint approximately (SLSQP will fine-tune).
        if total_budget_money_target is not None:
            current_money_sum = float(np.sum(perturbed * np.asarray(uc_arr)))
            if current_money_sum > 0:
                scale = float(total_budget_money_target) / current_money_sum
                perturbed = perturbed * scale
        else:
            current_sum = float(np.sum(perturbed))
            if current_sum > 0:
                perturbed = perturbed * (total_budget / current_sum)
        # Clip to bounds (after scaling some may slip outside).
        for i in range(n_ch):
            perturbed[i] = max(bounds[i][0], min(bounds[i][1], perturbed[i]))
        starts.append(perturbed)

    candidates = []
    for x_start in starts:
        r = _safe_minimize(x_start)
        if r is not None and r.success:
            candidates.append(r)

    if candidates:
        # Pick the result with highest objective (= lowest -response since we minimize -response)
        result = min(candidates, key=lambda r: r.fun)
    else:
        # All failed — fallback to current allocation, mark non-converged.
        class _FailResult:
            def __init__(self, x0, msg):
                self.x = x0.copy()
                self.success = False
                self.fun = 0.0
                self.message = msg
        result = _FailResult(x0, "All SLSQP starts failed")

    if not result.success:
        _logger.warning(f"Optimization did not converge: {result.message}")
    optimal_spend = result.x if result.success else np.array([current_spend[col] for col in media_cols])

    # O1.3 — binding constraints detection. Relative tolerance scaled by
    # problem magnitude (avoids absolute-eps issues on budgets in billions).
    def _is_binding(x_val: float, bound_val: float, scale: float) -> bool:
        return abs(x_val - bound_val) / max(abs(bound_val), scale * 1e-3, 1.0) < 1e-3

    _binding_scale = total_budget / max(n_ch, 1)
    _n_at_max = sum(1 for i in range(n_ch) if _is_binding(result.x[i], bounds[i][1], _binding_scale))
    _n_at_min = sum(1 for i in range(n_ch) if _is_binding(result.x[i], bounds[i][0], _binding_scale))
    binding_constraints = (_n_at_max == n_ch) or (_n_at_min == n_ch)

    # Compare current vs optimal
    current_response = -total_response(np.array([current_spend[col] for col in media_cols]))
    optimal_response = -total_response(optimal_spend)
    lift_pct = (optimal_response - current_response) / current_response * 100 if current_response else 0

    channels = []
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        opt = optimal_spend[i]
        delta_pct = (opt - cur) / cur * 100 if cur > 0 else 0

        # F0.2 (Phase 0.1 fix-session 2026-04-25): canonical mROAS chain rule
        # with adstock_factor + unit_cost normalization. See
        # docs/MATH_AUDIT_v1_3_PHASE_0_1.md §3 for full derivation.
        #
        # Pre-fix bugs (closed by F0.2):
        #   #11 missing adstock_factor → mROAS off by 2-15× depending on θ
        #   #12 missing /unit_cost     → TRPs (uc=250000) showed 1780× absurd
        # Both closed by single helper _compute_mroas_money() that returns
        # ∂KPI(money)/∂s(money) — comparable across native and money channels.
        # C1 fix (audit 2026-04-26): prefer adstock_mean_posterior (v1.2+) for math consistency.
        mean_post_opt = p.get('adstock_mean_posterior')
        mean_ch = float(mean_post_opt) if mean_post_opt is not None else (float(media_means.get(col, 1)) or 1)
        a_type = _adstock_type(col)
        uc = float(unit_costs.get(col, 1.0) or 1.0)

        decay_pt = p.get('decay')  # Phase 1.1: posterior mean decay; None for legacy pickles
        mroi_current = _compute_mroas_money(
            current_spend_native=cur,
            n_periods=n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
            decay=decay_pt,
        )
        mroi_optimal = _compute_mroas_money(
            current_spend_native=float(opt),
            n_periods=n_periods,
            mean=mean_ch,
            alpha=p['alpha'],
            gamma=p['gamma'],
            beta=p['beta'],
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=uc,
            decay=decay_pt,
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
                cur_arr = _compute_mroas_money_samples(
                    current_spend_native=cur,
                    n_periods=n_periods,
                    mean=mean_ch,
                    alpha_samples=ch_samples['alpha'],
                    gamma_samples=ch_samples['gamma'],
                    beta_samples=ch_samples['beta'],
                    adstock_type=a_type,
                    y_std=y_std,
                    unit_cost=uc,
                    decay_samples=decay_s,
                )
                _, mroi_current_ci_low, mroi_current_ci_high = compute_ci_hdi(cur_arr)

                opt_arr = _compute_mroas_money_samples(
                    current_spend_native=float(opt),
                    n_periods=n_periods,
                    mean=mean_ch,
                    alpha_samples=ch_samples['alpha'],
                    gamma_samples=ch_samples['gamma'],
                    beta_samples=ch_samples['beta'],
                    adstock_type=a_type,
                    y_std=y_std,
                    unit_cost=uc,
                    decay_samples=decay_s,
                )
                _, mroi_optimal_ci_low, mroi_optimal_ci_high = compute_ci_hdi(opt_arr)

        ch_dict = {
            'name': col,
            'current_spend': round(cur, 0),
            'optimal_spend': round(float(opt), 0),
            'current_spend_money': round(cur * uc, 0),
            'optimal_spend_money': round(float(opt) * uc, 0),
            'unit_cost': uc,
            'delta_pct': round(delta_pct, 1),
            'mroi_current': round(mroi_current, 4),
            'mroi_optimal': round(mroi_optimal, 4),
            'action': 'увеличить' if delta_pct > 5 else ('сократить' if delta_pct < -5 else 'сохранить'),
        }
        if mroi_current_ci_low is not None:
            ch_dict['mroi_current_ci_low'] = round(float(mroi_current_ci_low), 4)
            ch_dict['mroi_current_ci_high'] = round(float(mroi_current_ci_high), 4)
            ch_dict['mroi_optimal_ci_low'] = round(float(mroi_optimal_ci_low), 4)
            ch_dict['mroi_optimal_ci_high'] = round(float(mroi_optimal_ci_high), 4)
        channels.append(ch_dict)

    # Generate response curves data (for charts)
    # Post-audit fix: response_curve domain in normalized space, displayed against
    # raw spend. Response × y_std → KPI scale (was: y_norm scale, mis-leading numbers).
    response_curves_data = {}
    for i, col in enumerate(media_cols):
        p = channel_params[col]
        cur = current_spend[col]
        mean_ch = float(media_means.get(col, 1)) or 1
        a_type = _adstock_type(col)
        # F5 fix (math-audit v1.3): X-axis в total spend (как было), но Hill input
        # — per-period adstocked / mean. Curve теперь показывает realistic S-shape
        # (раньше total/mean = 30+× → asymptotic plateau).
        upper = cur * 2 if cur > 0 else mean_ch * 2 * n_periods
        spend_range = np.linspace(0, upper, 50)
        # Per-period equivalent for Hill input
        per_period_avg = spend_range / n_periods
        decay_pt_rc = p.get('decay')  # Phase 1.1: posterior mean decay for response curve adstock
        adstocked_avg = np.array([_flat_alloc_adstock_avg(float(x), n_periods, a_type, decay_pt_rc) for x in per_period_avg])
        spend_range_norm = adstocked_avg / max(mean_ch, 1e-10)
        responses_norm = response_curve(spend_range_norm, p['alpha'], max(p['gamma'], 1e-6), p['beta'])
        # Total contribution = per-period response × n_periods × y_std
        responses_kpi = responses_norm * y_std * n_periods
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
    insight = f"Оптимальное перераспределение бюджета ({round(total_budget_money, 0):,.0f} ₽) даёт ожидаемый прирост {_sign}{lift_pct:.1f}%."
    top_increase = max(channels, key=lambda x: x['delta_pct'])
    top_decrease = min(channels, key=lambda x: x['delta_pct'])
    if top_increase['delta_pct'] > 5:
        insight += f" Увеличить {top_increase['name']} на {top_increase['delta_pct']:.0f}%."
    if top_decrease['delta_pct'] < -5:
        insight += f" Сократить {top_decrease['name']} на {abs(top_decrease['delta_pct']):.0f}%."

    result_data = {
        'status': 'ok',
        'total_budget': round(total_budget, 0),
        'total_budget_money': round(total_budget_money, 0),
        'total_current_money': round(total_current_money, 0),
        'expected_lift_pct': round(lift_pct, 1),
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
    }

    # Save
    results_dir = project_path / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / 'optimization.json', 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return result_data
