"""
Aurora Econometrica - safe corridor bounds (v1.3.0).

Per ADR-014: вычисляет MVP формулу для безопасного диапазона бюджета per канал
+ агрегатный коридор по total budget + по target sales.

MVP per канал (default):
    X_i^lo = max(P5(X_i_observed), 0.5 · µ_i)
    X_i^hi = min(P95(X_i_observed), 1.5 · µ_i)

Expert mode (Phase B): posterior-based bounds через bootstrap-сэмплирование.

Usage:
    from optimize.bounds import compute_safe_corridor

    corridor = compute_safe_corridor(model_data)
    # {
    #   'per_channel': {ch: {'lo': X_lo, 'hi': X_hi, 'mu': avg, 'p5': P5, 'p95': P95}},
    #   'aggregate_budget': {'lo': sum_lo, 'hi': sum_hi, 'current': sum_current},
    #   'aggregate_sales': {'lo': S_at_lo, 'hi': S_at_hi, 'current': S_current},
    # }
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def compute_per_channel_bounds(
    spend_history: np.ndarray,
    relative_lo_factor: float = 0.5,
    relative_hi_factor: float = 1.5,
    percentile_lo: float = 5.0,
    percentile_hi: float = 95.0,
) -> Dict[str, float]:
    """Compute safe corridor bounds для одного канала.

    Args:
        spend_history: array of historical spend values (np.array).
        relative_lo_factor: множитель к среднему для нижней границы (default 0.5x).
        relative_hi_factor: множитель к среднему для верхней границы (default 1.5x).
        percentile_lo: lower percentile threshold (default 5).
        percentile_hi: upper percentile threshold (default 95).

    Returns:
        Dict с keys: 'lo', 'hi', 'mu', 'p5', 'p95'.

    MVP формула:
        lo = max(P5, lo_factor * mu)
        hi = min(P95, hi_factor * mu)

    Защищает от extrapolation за пределы observed range, но достаточно гибко
    для actionable рекомендаций.
    """
    spend = np.asarray(spend_history, dtype=float)
    spend_positive = spend[spend > 0]

    if len(spend_positive) == 0:
        # Канал без активности - corridor [0, 0].
        return {'lo': 0.0, 'hi': 0.0, 'mu': 0.0, 'p5': 0.0, 'p95': 0.0}

    mu = float(np.mean(spend_positive))
    p5 = float(np.percentile(spend_positive, percentile_lo))
    p95 = float(np.percentile(spend_positive, percentile_hi))

    lo = max(p5, relative_lo_factor * mu)
    hi = min(p95, relative_hi_factor * mu)

    # Sanity: lo не больше hi.
    # Audit fix v1.3.0 (red-team review): silent swap скрывал inverted corridor.
    # Если lo > hi, это симптом very low CV (P5 ≈ P95) + relative_lo > relative_hi.
    # Honest fix: set lo = hi = mu (point estimate), без свапа. Warning через
    # narrow_corridor flag для downstream UI.
    if lo > hi:
        lo = hi = mu

    return {
        'lo': lo, 'hi': hi, 'mu': mu, 'p5': p5, 'p95': p95,
        'narrow_corridor': p95 - p5 < 0.01 * mu,  # flag для UI warning
    }


def compute_safe_corridor(
    model_data: Dict[str, Any],
    relative_lo_factor: float = 0.5,
    relative_hi_factor: float = 1.5,
    project_dir: Any = None,
) -> Dict[str, Any]:
    """Compute safe corridor for all channels + aggregate.

    Args:
        model_data: loaded model pickle (через `load_model_with_compat`).
        relative_lo_factor / relative_hi_factor: see compute_per_channel_bounds.
        project_dir: каталог проекта. Задан — считаем `aggregate_sales` прямым
            проходом на границах агрегатного бюджета (2026-08-16, профит-фронтир:
            прямой проход теперь есть, заглушку закрываем). None — поля нет.

    Returns:
        Dict:
        {
          'mode': 'mvp',
          'formula': 'max(P5, 0.5*mu), min(P95, 1.5*mu)',
          'per_channel': {channel: {lo, hi, mu, p5, p95, current}},
          'aggregate_budget': {lo, hi, current},
          'aggregate_sales': {lo, hi, current, basis, n_periods}  # если задан project_dir
        }

    `aggregate_sales` — СУММАРНЫЕ продажи за весь период обучения при бюджетах
    границ коридора (`basis='total_over_training_period'`), считаются двумя
    вызовами прямого прохода `build_proportional_forward` (плюс один в текущей
    точке). Проход фиксирует текущие пропорции каналов и масштабирует общий
    бюджет — те же продажи, что показывает подбор бюджета «от цели».

    🔴 Основания в `aggregate_budget` разные: `lo`/`hi` — траты ЗА ОДИН ПЕРИОД
    (перцентили и среднее по строкам данных), `current` — СУММА за весь период
    обучения. Продажи считаются от суммарных бюджетов, и бюджеты, по которым
    считали, отдаются полем `aggregate_sales.budget_used` вместе с флагом
    `corridor_basis_mismatch` — чтобы число на экране нельзя было подписать
    не тем основанием.

    🔴 Единицы: коридор суммирует НАТИВНЫЕ траты каналов, а прямой проход ждёт
    ДЕНЬГИ. Совпадает только когда стоимость единицы у всех каналов = 1 (данные
    уже в рублях). Иначе чисел не даём — отдаём статус `unit_mismatch`
    (тот же принцип, что UNIT_SMELL в оптимизаторе: смешанные единицы лучше
    не показывать вовсе, чем показать неправильно).
    """
    config = model_data.get('config', {})
    media_cols = config.get('media_columns', [])
    data_file = config.get('data_file')

    if not data_file:
        # Cannot compute без training data. Return empty corridor.
        return {
            'mode': 'mvp',
            'formula': f'max(P{int(5)}, {relative_lo_factor}*mu), min(P{int(95)}, {relative_hi_factor}*mu)',
            'per_channel': {},
            'aggregate_budget': {'lo': 0.0, 'hi': 0.0, 'current': 0.0},
            'error': 'No data_file in model config',
        }

    # Load training data.
    if str(data_file).endswith(('.xlsx', '.xls')):
        df = pd.read_excel(data_file)
    else:
        df = pd.read_csv(data_file)

    # Apply merge_rules если есть (consistent с optimizer/decomposer).
    try:
        from utils.merge_rules import apply_merge_rules
        apply_merge_rules(df, config.get('merge_rules'))
    except Exception:
        pass  # merge_rules optional; continue без них.

    per_channel: Dict[str, Dict[str, float]] = {}
    sum_lo = 0.0
    sum_hi = 0.0
    sum_current = 0.0

    for channel in media_cols:
        if channel not in df.columns:
            # Канал в media_cols, но нет колонки в data - skip с пустым corridor.
            per_channel[channel] = {
                'lo': 0.0, 'hi': 0.0, 'mu': 0.0, 'p5': 0.0, 'p95': 0.0,
                'current': 0.0,
            }
            continue

        spend_array = df[channel].fillna(0).values
        bounds = compute_per_channel_bounds(
            spend_array,
            relative_lo_factor=relative_lo_factor,
            relative_hi_factor=relative_hi_factor,
        )

        # Current spend - сумма по всему периоду obs.
        current_total = float(spend_array.sum())
        bounds['current'] = current_total

        per_channel[channel] = bounds
        sum_lo += bounds['lo']
        sum_hi += bounds['hi']
        sum_current += current_total

    aggregate_budget = {
        'lo': sum_lo,
        'hi': sum_hi,
        'current': sum_current,
    }

    result = {
        'mode': 'mvp',
        'formula': f'max(P5, {relative_lo_factor}*mu), min(P95, {relative_hi_factor}*mu)',
        'per_channel': per_channel,
        'aggregate_budget': aggregate_budget,
    }

    if project_dir is not None:
        result['aggregate_sales'] = _aggregate_sales_at_bounds(
            project_dir, config, aggregate_budget)

    return result


def _aggregate_sales_at_bounds(
    project_dir: Any,
    config: Dict[str, Any],
    aggregate_budget: Dict[str, float],
) -> Dict[str, Any]:
    """Продажи на границах агрегатного коридора — двумя вызовами прямого прохода.

    Возвращает либо {'status': 'ok', 'lo', 'hi', 'current', 'basis', 'n_periods'},
    либо {'status': 'unavailable'|'unit_mismatch', 'reason', 'message'} — числа
    не выдумываем (INV-50): нет корректной величины → статус, не ноль.
    """
    try:
        from optimize.inverse import _resolve_current_unit_costs, build_proportional_forward

        # Единицы: коридор в нативных тратах, проход — в деньгах. Совпадают
        # только при стоимости единицы = 1 у всех каналов коридора.
        unit_costs = _resolve_current_unit_costs(str(project_dir), config)
        mismatched = sorted(
            c for c, v in (unit_costs or {}).items()
            if c in (config.get('media_columns') or []) and abs(float(v) - 1.0) > 1e-9
        )
        if mismatched:
            return {
                'status': 'unit_mismatch',
                'reason': 'non_money_channels',
                'channels': mismatched,
                'message': (
                    'Границы коридора считаются в натуральных единицах каналов, '
                    'а продажи – от денежного бюджета. У части каналов задана '
                    'стоимость единицы, поэтому сопоставить их напрямую нельзя: '
                    'продажи на границах коридора не показываем.'
                ),
            }

        forward, meta = build_proportional_forward(str(project_dir))
        n_periods = int(meta.get('n_periods') or 0)
        if n_periods <= 0:
            return {
                'status': 'unavailable',
                'reason': 'n_periods_unknown',
                'message': ('Число периодов обучения неизвестно – привести границы '
                            'коридора к суммарному бюджету нельзя.'),
            }

        # 🔴 Основания разные (находка 2026-08-16): `lo`/`hi` коридора — это траты
        # ЗА ОДИН ПЕРИОД (перцентили и среднее по строкам данных), а `current` в том
        # же словаре — СУММА за весь период обучения. Прямой проход ждёт суммарный
        # бюджет. Поэтому границы приводим к тому же основанию (× число периодов) и
        # ЯВНО отдаём бюджеты, по которым считали, — иначе продажи «зелёной зоны»
        # оказались бы почти базовым уровнем и читались бы как обвал (на реальной
        # модели: 5,1 млн против текущих 260,2 млн). Само поле aggregate_budget
        # не трогаем — им пользуется интерфейс.
        budget_used = {
            'lo': float(aggregate_budget.get('lo', 0.0) or 0.0) * n_periods,
            'hi': float(aggregate_budget.get('hi', 0.0) or 0.0) * n_periods,
            'current': float(aggregate_budget.get('current', 0.0) or 0.0),
        }
        out: Dict[str, Any] = {
            'status': 'ok',
            'basis': 'total_over_training_period',
            'n_periods': n_periods,
            'budget_used': budget_used,
            'corridor_budget_basis': 'per_period',
            'corridor_basis_mismatch': True,
            'message': (
                'Границы коридора заданы тратами за один период, а текущий бюджет – '
                'суммой за весь период обучения. Продажи посчитаны от суммарных '
                'бюджетов (границы × число периодов); эти бюджеты приведены '
                'в поле budget_used.'
            ),
        }
        for key in ('lo', 'hi', 'current'):
            point = forward(budget_used[key])
            if point.get('status') != 'ok':
                return {
                    'status': 'unavailable',
                    'reason': 'forward_failed',
                    'message': ('Продажи на границах коридора рассчитать не удалось.'),
                }
            out[key] = float(point['expected_sales'])
        return out
    except Exception as exc:  # noqa: BLE001 - коридор на критическом пути, не роняем
        return {
            'status': 'unavailable',
            'reason': 'forward_unavailable',
            'message': f'Продажи на границах коридора рассчитать не удалось: {exc}',
        }


def is_in_safe_corridor(
    value: float,
    bounds: Dict[str, float],
    yellow_zone_pct: float = 0.10,
) -> str:
    """Classify value as 'green', 'yellow', or 'red' based on bounds.

    Per ADR-014 UX:
    - 🟢 Внутри [lo, hi] - safe.
    - 🟡 ±10% за пределами - extrapolation warning.
    - 🔴 > 10% за пределами - заблокировано.

    Args:
        value: тестируемое значение (бюджет, цель).
        bounds: {'lo': float, 'hi': float}.
        yellow_zone_pct: relative ширина жёлтой зоны (default 10%).

    Returns:
        'green' | 'yellow' | 'red'.
    """
    lo = bounds['lo']
    hi = bounds['hi']
    if lo <= value <= hi:
        return 'green'

    if value < lo:
        delta_relative = (lo - value) / lo if lo > 0 else float('inf')
    else:  # value > hi
        delta_relative = (value - hi) / hi if hi > 0 else float('inf')

    if delta_relative <= yellow_zone_pct:
        return 'yellow'
    return 'red'
