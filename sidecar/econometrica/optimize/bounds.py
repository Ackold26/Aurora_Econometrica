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

# Признаки основания. Каждое денежное число коридора подписано СВОИМ признаком:
# общий ключ рядом с несколькими группами чисел читается как подпись ко всем
# сразу и сам создаёт путаницу оснований, против которой заводился.
BUDGET_PER_ACTIVE_PERIOD = 'budget_per_active_period'
BUDGET_TOTAL_OVER_TRAINING = 'budget_total_over_training_period'
SALES_TOTAL_OVER_TRAINING = 'sales_total_over_training_period'

# Имена, по которым движок узнаёт канал в натуральных единицах (пункты рейтинга,
# показы, клики). SSOT эвристики — `engines/optimizer.py` (гейт UNIT_SMELL) и
# `engines/decomposer.py` (UNIT_HINTS); здесь копия, потому что там она объявлена
# внутри функций. Список держать согласованным с ними.
NON_MONEY_NAME_HINTS = (
    'TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ', 'КЛИК',
    'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ',
)


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
        Dict с keys: 'lo', 'hi', 'mu', 'p5', 'p95', 'n_active_periods'.

    🔴 Основание границ (уточнено 2026-08-16): `mu`, `p5`, `p95` считаются ТОЛЬКО
    по периодам с ненулевой тратой, значит `lo`/`hi` — это трата за один АКТИВНЫЙ
    период канала, а не за строку данных. Для флайтовой закупки это разные вещи,
    поэтому число активных периодов отдаётся рядом (`n_active_periods`) — без него
    границы нельзя корректно привести к сумме за весь период обучения.

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
        return {'lo': 0.0, 'hi': 0.0, 'mu': 0.0, 'p5': 0.0, 'p95': 0.0,
                'n_active_periods': 0}

    mu = float(np.mean(spend_positive))
    p5 = float(np.percentile(spend_positive, percentile_lo))
    p95 = float(np.percentile(spend_positive, percentile_hi))
    n_active = int(len(spend_positive))

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
        'n_active_periods': n_active,
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
          'per_channel': {channel: {lo, hi, mu, p5, p95, n_active_periods, current}},
          'aggregate_budget': {lo, hi, current},
          'aggregate_budget_basis': {lo, hi, current},   # основание КАЖДОГО числа
          'aggregate_sales': {...}                       # если задан project_dir
        }

    `aggregate_sales` — продажи при бюджетах границ коридора, считаются двумя
    вызовами прямого прохода `build_proportional_forward` (плюс один в текущей
    точке). Проход фиксирует текущие пропорции каналов и масштабирует общий
    бюджет — те же продажи, что показывает подбор бюджета «от цели». Форма
    ответа — см. `_aggregate_sales_at_bounds`: каждая группа чисел лежит в своём
    словаре со своим полем `basis`, общих признаков основания в словаре нет.

    🔴 Основания в `aggregate_budget` разные, поэтому рядом лежит
    `aggregate_budget_basis` — признак у КАЖДОГО числа отдельно:
    `lo`/`hi` — трата за один АКТИВНЫЙ период канала (`budget_per_active_period`;
    среднее и перцентили берутся по периодам с ненулевой тратой), `current` —
    СУММА за весь период обучения (`budget_total_over_training_period`).
    Само поле `aggregate_budget` не трогаем — им пользуется интерфейс.

    🔴 Единицы: коридор суммирует НАТИВНЫЕ траты каналов, а прямой проход ждёт
    ДЕНЬГИ. Совпадает только когда единица измерения каждого канала — рубль.
    Опасен не только канал с ЗАДАННОЙ стоимостью единицы, но и канал, у которого
    она НЕ ЗАДАНА вовсе: прямой проход подставит 1,0 и сложит пункты рейтинга с
    рублями. Поэтому чисел не даём в обоих случаях — статус `unit_mismatch`
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
            'aggregate_budget_basis': {
                'lo': BUDGET_PER_ACTIVE_PERIOD,
                'hi': BUDGET_PER_ACTIVE_PERIOD,
                'current': BUDGET_TOTAL_OVER_TRAINING,
            },
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
                'n_active_periods': 0, 'current': 0.0,
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
        # Признак основания у КАЖДОГО числа отдельно: в `aggregate_budget` они
        # разные, и один общий признак рядом читался бы как подпись ко всем трём.
        'aggregate_budget_basis': {
            'lo': BUDGET_PER_ACTIVE_PERIOD,
            'hi': BUDGET_PER_ACTIVE_PERIOD,
            'current': BUDGET_TOTAL_OVER_TRAINING,
        },
    }

    if project_dir is not None:
        result['aggregate_sales'] = _aggregate_sales_at_bounds(
            project_dir, config, per_channel, model_data)

    return result


def classify_channel_units(
    media_cols: List[str],
    unit_costs: Dict[str, float],
    training_snapshot: Dict[str, float] | None = None,
) -> Dict[str, List[str]]:
    """Разложить каналы по тому, известна ли их единица измерения и рубль ли это.

    Возвращает три непересекающихся списка:
      'priced'  — стоимость единицы ЗАДАНА и не равна 1: канал точно в натуральных
                  единицах (пункты рейтинга, показы), складывать с рублями нельзя.
      'unknown' — стоимость единицы НЕ задана, но есть признак натуральных единиц:
                  имя канала (`NON_MONEY_NAME_HINTS`) или снимок стоимостей,
                  применённых при обучении. Единица неизвестна — считать нельзя.
      'money'   — стоимость задана и равна 1 (явно рубли) либо не задана и признаков
                  натуральных единиц нет; принимается рубль, как и во всём движке
                  (`unit_costs.get(c, 1.0)`).

    🔴 Зачем (находка внешнего аудита 2026-08-16, F-13). Прежняя защита строилась
    на списке каналов с ЗАДАННОЙ стоимостью единицы ≠ 1. Но резолвер
    `_resolve_current_unit_costs` отдаёт только каналы с заданной положительной
    стоимостью, поэтому канал, у которого стоимость не задана ВОВСЕ, в список не
    попадал никогда — а это и есть опасный случай: прямой проход подставит 1,0 и
    сложит пункты рейтинга с рублями. На эталонном проекте (кагоцел) словарь
    стоимостей пуст, среди каналов «TRPs бренд (W 25-54)» — сторож молчал, статус
    был `ok`. Теперь такой канал попадает в 'unknown' и числа не выдаются.
    """
    snapshot = training_snapshot or {}
    priced: List[str] = []
    unknown: List[str] = []
    money: List[str] = []

    for channel in media_cols:
        raw = (unit_costs or {}).get(channel)
        if raw is not None:
            # Заданная стоимость: рубль — только ровно 1.
            if abs(float(raw) - 1.0) > 1e-9:
                priced.append(channel)
            else:
                money.append(channel)
            continue

        trained = snapshot.get(channel)
        if trained is not None and abs(float(trained) - 1.0) > 1e-9:
            # При обучении у канала была стоимость единицы, сейчас её нет:
            # данные натуральные, а перевода в деньги не существует.
            unknown.append(channel)
            continue

        if any(hint in str(channel).upper() for hint in NON_MONEY_NAME_HINTS):
            unknown.append(channel)
            continue

        money.append(channel)

    return {'priced': priced, 'unknown': unknown, 'money': money}


def _aggregate_sales_at_bounds(
    project_dir: Any,
    config: Dict[str, Any],
    per_channel: Dict[str, Dict[str, float]],
    model_data: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Продажи на границах агрегатного коридора — тремя вызовами прямого прохода.

    Форма ответа при успехе (каждая группа чисел — со СВОИМ признаком основания,
    общих признаков в словаре нет, находка F-14):
        {
          'status': 'ok',
          'n_periods': N,
          'corridor_budget': {lo, hi, basis='budget_per_active_period'},
          'budget_used':     {lo, hi, current, basis='budget_total_over_training_period'},
          'sales':           {lo, hi, current, basis='sales_total_over_training_period'},
          'active_periods_per_channel': {channel: n},
          'unit_assumption': {...},   # если у части каналов стоимость единицы не задана
          'message': ...
        }
    Иначе {'status': 'unavailable'|'unit_mismatch'|'implausible_bounds', 'reason',
    'message'} — числа не выдумываем (INV-50): нет корректной величины → статус,
    не ноль.
    """
    try:
        from optimize.inverse import _resolve_current_unit_costs, build_proportional_forward

        media_cols = list(config.get('media_columns') or [])

        # Единицы: коридор в нативных тратах, проход — в деньгах. Сопоставимо
        # только когда единица КАЖДОГО канала — рубль, и это ИЗВЕСТНО.
        unit_costs = _resolve_current_unit_costs(str(project_dir), config) or {}
        snapshot = {}
        if model_data and model_data.get('unit_costs_applied_at_training'):
            snapshot = model_data.get('unit_costs_snapshot') or {}
        units = classify_channel_units(media_cols, unit_costs, snapshot)
        priced, unknown = sorted(units['priced']), sorted(units['unknown'])
        if priced or unknown:
            if priced and unknown:
                reason = 'mixed_units'
                detail = ('У части каналов задана стоимость единицы, а у части единица '
                          'измерения вообще неизвестна.')
            elif priced:
                reason = 'non_money_channels'
                detail = 'У части каналов задана стоимость единицы.'
            else:
                reason = 'unknown_unit_channels'
                detail = ('У части каналов единица измерения неизвестна: стоимость '
                          'единицы не задана, а данные не похожи на рубли.')
            return {
                'status': 'unit_mismatch',
                'reason': reason,
                'channels': sorted(set(priced) | set(unknown)),
                'priced_channels': priced,
                'unknown_unit_channels': unknown,
                'message': (
                    'Границы коридора считаются в натуральных единицах каналов, '
                    f'а продажи – от денежного бюджета. {detail} Сложить такие траты '
                    'с рублями нельзя, поэтому продажи на границах коридора '
                    'не показываем. Задайте стоимость единицы для этих каналов – '
                    'и расчёт станет возможен.'
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

        # 🔴 Приведение оснований (находка F-07, 2026-08-16). `lo`/`hi` канала —
        # это трата за один АКТИВНЫЙ период: среднее и перцентили берутся по
        # `spend[spend > 0]`. Умножение на число ВСЕХ периодов завышало суммарную
        # трату флайтового канала в `n_периодов / n_активных` раз (на кагоцеле у
        # OLV активны 23 периода из 31, у ТВ-канала – 22). Поэтому приводим
        # ПОКАНАЛЬНО: граница × число активных периодов этого канала. Для канала,
        # работавшего каждый период, результат совпадает с прежним.
        active: Dict[str, int] = {}
        for channel, bounds in per_channel.items():
            n_active = bounds.get('n_active_periods')
            if n_active is None:
                return {
                    'status': 'unavailable',
                    'reason': 'active_periods_unknown',
                    'message': ('Сколько периодов канал был активен – неизвестно, '
                                'поэтому границы коридора нельзя привести к бюджету '
                                'за весь период обучения.'),
                }
            active[channel] = int(n_active)

        if any(n > n_periods for n in active.values()):
            # Коридор и прямой проход читали разные данные — приведение нечестно.
            return {
                'status': 'unavailable',
                'reason': 'periods_disagree',
                'message': ('Число периодов в данных коридора и в модели расходится – '
                            'приводить границы к суммарному бюджету по ним нельзя.'),
            }

        corridor_lo = sum(float(b.get('lo') or 0.0) for b in per_channel.values())
        corridor_hi = sum(float(b.get('hi') or 0.0) for b in per_channel.values())
        budget_used = {
            'lo': sum(float(b.get('lo') or 0.0) * active[c] for c, b in per_channel.items()),
            'hi': sum(float(b.get('hi') or 0.0) * active[c] for c, b in per_channel.items()),
            'current': sum(float(b.get('current') or 0.0) for b in per_channel.values()),
            'basis': BUDGET_TOTAL_OVER_TRAINING,
        }

        # Дешёвая проверка разумности: коридор обязан накрывать текущую трату –
        # он же построен вокруг неё. Не накрывает → приведение неверно, и числа
        # выдавать нельзя (прежний код молча отдавал их со статусом `ok`).
        tol = 1e-6
        current_total = budget_used['current']
        if current_total <= 0 or budget_used['lo'] > budget_used['hi'] * (1 + tol):
            return {
                'status': 'implausible_bounds',
                'reason': 'corridor_totals_invalid',
                'message': ('Границы коридора, приведённые к бюджету за весь период '
                            'обучения, получились несогласованными – продажи по ним '
                            'не считаем.'),
            }
        if (budget_used['lo'] > current_total * (1 + tol)
                or budget_used['hi'] < current_total * (1 - tol)):
            return {
                'status': 'implausible_bounds',
                'reason': 'corridor_does_not_bracket_current',
                'budget_used': budget_used,
                'message': ('Коридор, приведённый к бюджету за весь период обучения, '
                            'не накрывает текущую трату – значит границы и текущий '
                            'бюджет посчитаны по-разному. Продажи на таких границах '
                            'не показываем.'),
            }

        out: Dict[str, Any] = {
            'status': 'ok',
            'n_periods': n_periods,
            'corridor_budget': {
                'lo': corridor_lo,
                'hi': corridor_hi,
                'basis': BUDGET_PER_ACTIVE_PERIOD,
            },
            'budget_used': budget_used,
            'active_periods_per_channel': active,
            'message': (
                'Границы коридора заданы тратой за один активный период канала, '
                'а текущий бюджет – суммой за весь период обучения. Продажи '
                'посчитаны от суммарных бюджетов: граница каждого канала умножена '
                'на число периодов, когда канал работал. Бюджеты, по которым '
                'считали, приведены в поле budget_used.'
            ),
        }
        assumed = [c for c in units['money'] if unit_costs.get(c) is None]
        if assumed:
            out['unit_assumption'] = {
                'channels': assumed,
                'message': ('У этих каналов стоимость единицы не задана, а признаков '
                            'натуральных единиц нет – их траты приняты за рубли, '
                            'как и в остальном расчёте.'),
            }

        sales: Dict[str, Any] = {'basis': SALES_TOTAL_OVER_TRAINING}
        for key in ('lo', 'hi', 'current'):
            point = forward(budget_used[key])
            if point.get('status') != 'ok':
                return {
                    'status': 'unavailable',
                    'reason': 'forward_failed',
                    'message': ('Продажи на границах коридора рассчитать не удалось.'),
                }
            sales[key] = float(point['expected_sales'])
        out['sales'] = sales
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
