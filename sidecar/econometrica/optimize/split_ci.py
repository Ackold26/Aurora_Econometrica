"""A4/OPP-04 (2026-07-03): интервалы неопределённости оптимального сплита.

Канон — Jin et al. 2017 (Bayesian MMM, Carryover and Shape Effects): «the
posterior distribution … shows the variation of the estimated optimal mix.
The variation … is very important and informs the user how much he should
trust the model in guiding budget allocation».

Метод: пере-оптимизация SLSQP на подвыборке posterior-draws (точечные
параметры каждого draw → оптимальные доли) → распределение долей → 90% HDI
(SSOT compute_ci_hdi). Формула отклика НЕ дублируется — per-draw вызов
evaluate_flat_allocation_response (I8-alignment, как posterior_sampler
goal-seek). Дорого (~секунды) → отдельная кнопка/фон, не интерактив.

Выход: per-channel {share_mean, share_ci_low, share_ci_high} + пары каналов
с перекрывающимися HDI («разница статистически не выделяется»).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def optimal_split_ci(
    project_dir: str,
    total_budget_money: Optional[float] = None,
    n_draws: int = 60,
    unit_costs_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Распределение оптимальных долей по posterior-draws.

    Args:
        project_dir: каталог проекта с models/latest.pkl.
        total_budget_money: бюджет в деньгах; None → текущий суммарный.
        n_draws: размер подвыборки draws (50–100 по OPP-04).
        unit_costs_override: CPP из запроса (SSOT-цепочка как в goal-seek).
    """
    import numpy as np
    import pandas as pd
    from scipy.optimize import minimize

    from engines.persistence import load_model_with_compat
    from utils.forecasting import evaluate_flat_allocation_response
    from utils.merge_rules import apply_merge_rules
    from utils.posterior_propagation import compute_ci_hdi
    from utils.data_file_resolver import resolve_data_file
    from optimize.inverse import _resolve_current_unit_costs

    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {'status': 'error', 'error_code': 'MODEL_NOT_FOUND',
                'message': 'Модель не найдена. Сначала обучите модель.'}

    model_data = load_model_with_compat(model_path)
    cfg = model_data['config']
    norm = model_data['normalization']
    channel_params = model_data['channel_params']
    ps = model_data.get('posterior_samples') or {}
    betas = ps.get('media_betas')
    if betas is None:
        return {'status': 'error', 'error_code': 'NO_POSTERIOR',
                'message': ('Для интервалов оптимального сплита нужны апостериорные '
                            'выборки — модель обучена без байесовского вывода (OLS/legacy).')}

    media_cols = [c for c in cfg['media_columns']
                  if c not in set(norm.get('untrained_channels', []) or [])]
    y_std = float(norm.get('y_std', 1.0)) or 1.0
    media_means = norm.get('media_means', {}) or {}
    adstock_config = cfg.get('adstock_config', {}) or {}
    unit_costs = _resolve_current_unit_costs(project_dir, cfg, unit_costs_override)

    data_file = resolve_data_file(cfg.get('data_file'), project_dir)
    df = (pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls'))
          else pd.read_csv(data_file))
    apply_merge_rules(df, cfg.get('merge_rules'))
    n_periods = max(len(df), 1)

    uc_applied = bool(model_data.get('unit_costs_applied_at_training'))
    uc_snap = (model_data.get('unit_costs_snapshot') or {}) if uc_applied else {}
    uc_arr = [float(unit_costs.get(c, 1.0) or 1.0) for c in media_cols]
    uc_train_arr = [float(uc_snap.get(c, 1.0) or 1.0) for c in media_cols] if uc_applied else None

    current_money = {
        c: float(df[c].fillna(0).sum()) * float(unit_costs.get(c, 1.0) or 1.0)
        for c in media_cols
    }
    budget = float(total_budget_money) if total_budget_money else sum(current_money.values())
    if budget <= 0:
        return {'status': 'error', 'error_code': 'NO_BUDGET',
                'message': 'Суммарный бюджет равен нулю — сплит не определён.'}

    betas_a = np.asarray(betas, dtype=float)
    alphas_a = np.asarray(ps.get('alphas'), dtype=float)
    gammas_a = np.asarray(ps.get('gammas'), dtype=float)
    ps_cols = list(ps.get('media_columns') or media_cols)
    try:
        row_idx = [ps_cols.index(c) for c in media_cols]
    except ValueError:
        return {'status': 'error', 'error_code': 'POSTERIOR_MISMATCH',
                'message': 'Каналы модели не совпадают с апостериорными выборками.'}
    decay_raw = ps.get('adstock_decay')
    decay_a = np.asarray(decay_raw, dtype=float) if decay_raw is not None else None
    per_sample_decay = (decay_a is not None and decay_a.ndim == 2
                        and decay_a.shape == betas_a.shape)

    n_total = betas_a.shape[1]
    n_draws = max(10, min(int(n_draws), 200))
    step = max(1, n_total // n_draws)
    sel = np.arange(0, n_total, step)[:n_draws]

    n_ch = len(media_cols)
    x0 = np.full(n_ch, budget / n_ch)
    bounds = [(0.0, budget)] * n_ch
    constraints = [{'type': 'eq', 'fun': lambda a: float(np.sum(a) - budget)}]

    shares = np.empty((sel.size, n_ch), dtype=float)
    n_failed = 0
    for j, s in enumerate(sel):
        cp: Dict[str, Dict[str, Any]] = {}
        for k_i, c in enumerate(media_cols):
            r = row_idx[k_i]
            point = channel_params.get(c, {}) or {}
            cp[c] = {
                'beta': float(betas_a[r, s]),
                'alpha': float(alphas_a[r, s]),
                'gamma': float(gammas_a[r, s]),
                'decay': (float(decay_a[r, s]) if per_sample_decay else point.get('decay')),
                'adstock_mean_posterior': point.get('adstock_mean_posterior'),
            }

        def neg_response(alloc, _cp=cp):
            return -float(evaluate_flat_allocation_response(
                media_cols=media_cols, channel_params=_cp,
                allocation_money=np.asarray(alloc, dtype=float),
                unit_costs=uc_arr, media_means=media_means,
                adstock_config=adstock_config, n_periods=n_periods,
                unit_costs_at_training=uc_train_arr,
            )) * y_std

        res = minimize(neg_response, x0, method='SLSQP', bounds=bounds,
                       constraints=constraints,
                       options={'maxiter': 120, 'ftol': 1e-9})
        alloc = np.clip(res.x, 0, None)
        total = float(alloc.sum()) or 1.0
        shares[j] = alloc / total
        if not res.success:
            n_failed += 1

    channels_out = []
    for k_i, c in enumerate(media_cols):
        _, lo, hi, method = compute_ci_hdi(shares[:, k_i])
        channels_out.append({
            'name': c,
            'share_mean': round(float(shares[:, k_i].mean()), 4),
            'share_ci_low': round(float(lo), 4),
            'share_ci_high': round(float(hi), 4),
            'ci_method': method,
        })

    # Пары с перекрывающимися HDI: разница долей статистически не выделяется
    # (Jin 2017: пользователь должен видеть, где модель НЕ различает каналы).
    overlaps = []
    for i in range(n_ch):
        for k in range(i + 1, n_ch):
            a, b = channels_out[i], channels_out[k]
            if a['share_ci_low'] <= b['share_ci_high'] and b['share_ci_low'] <= a['share_ci_high']:
                overlaps.append([a['name'], b['name']])

    return {
        'status': 'ok',
        'budget_money': round(budget, 2),
        'n_draws': int(sel.size),
        'n_failed': int(n_failed),
        'hdi_prob': 0.9,
        'channels': channels_out,
        'overlapping_pairs': overlaps,
        'note': ('Интервалы показывают разброс оптимального сплита по апостериорным '
                 'сценариям модели (Jin et al., 2017). Перекрытие интервалов — '
                 'разница долей статистически не выделяется.'),
    }
