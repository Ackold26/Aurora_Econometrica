"""Профит-фронтир (2026-08-16): «сколько вообще тратить», а не «как разложить».

Контракт — `Projects/FRONTIER_DESIGN_2026-08-16.md`.

Что считаем: кривая прибыли по суммарному бюджету на сетке 25 точек от 0,2× до 3×
текущего бюджета (точка текущего бюджета включена в сетку всегда), на каждой точке —
бюджет, продажи, прибыль, предельная отдача и выход за наблюдавшийся диапазон
(severity). Дальше — положение максимума прибыли и 90% интервал на это положение
по апостериорным выборкам.

Прямой проход берём готовый — `optimize.inverse.build_proportional_forward`
(монотонен по построению, фиксирует текущие пропорции каналов и масштабирует общий
бюджет). Формула отклика здесь НЕ дублируется (I8-alignment, как в goal-seek и
split_ci).

🔴 Три исхода максимума вместо одного (главное отличие от рынка):
  1. `interior_observed` — максимум внутри наблюдавшегося диапазона: называем числом.
  2. `beyond_observed`   — максимум за правым краем наблюдений: числа НЕ даём,
     говорим «в пределах ваших данных рост бюджета остаётся выгодным, где потолок —
     эти данные не показывают» (Chan & Perry 2017: вне наблюдённого диапазона кривая
     данными не идентифицируется, разные кривые расходятся).
  3. `below_current`     — максимум левее текущего бюджета: «вы уже за точкой
     максимальной прибыли», с величиной теряемой прибыли.

🔴 Экономика обязательна. Без перевода KPI в деньги максимума прибыли не существует
в принципе (оборот растёт с бюджетом всегда), поэтому при её отсутствии — отказ с
причиной, а не нулевая прибыль (INV-50; образец — `money_roi_unavailable` в
engines/channel_action.py).

🔴 Единицы. Прямой проход даёт СУММАРНЫЕ продажи за весь период обучения, и бюджет
суммарный за тот же период. Каждый словарь с числами несёт `basis`, а верхний уровень —
блок `period` (сколько периодов и какой шаг). В продукте уже был дефект ровно этого
рода («260 млн против 2,46 млрд»), второй раз не наступаем.

Цена: ~100 вызовов forward (< 1 мс каждый) + (сетка + 1) вызовов апостериорной
выборки по 0,02 с ≈ 0,6 с суммарно. Считается на лету, отдельного прогона не нужно.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Признак периода: все денежные величины и продажи — СУММА за весь период обучения,
# не за месяц/неделю. Отдельным полем в каждом словаре с числами.
PERIOD_BASIS = 'total_over_training_period'

_GRANULARITY_LABEL_RU = {
    'D': 'по дням', 'W': 'по неделям', 'M': 'по месяцам',
    'Q': 'по кварталам', 'Y': 'по годам',
}

# Доля бюджета для центральной разности при оценке предельной отдачи.
# Кривая гладкая: на реальной модели значение устойчиво в 4 знаках при шаге
# 0,1%–1% (зонд 2026-08-16), 5% уже даёт видимый снос из-за вогнутости.
_MARGINAL_DELTA_PCT = 0.01


def _period_label_ru(granularity: Optional[Dict[str, Any]]) -> str:
    """«по месяцам» / «по периодам» из detect_granularity (канон aurora_html/builder).

    Низкая уверенность в регулярности дат → нейтральное «по периодам»: не врать
    «по неделям» на месячных данных.
    """
    if not granularity:
        return 'по периодам'
    if float(granularity.get('confidence', 0.0) or 0.0) < 0.5:
        return 'по периодам'
    return _GRANULARITY_LABEL_RU.get(granularity.get('granularity'), 'по периодам')


def _money_ru(value: float) -> str:
    """«260 183 663» — разделитель разрядов пробелом.

    Форматируем ИМЕННО число, а не готовую фразу: сквозная замена запятых в строке
    (приём из goal-seek) съела бы запятые русского текста вокруг числа.
    """
    return f'{float(value):,.0f}'.replace(',', ' ')


def _ru_periods(n: int) -> str:
    """«31 период» / «2 периода» / «15 периодов» — согласование в клиентском тексте."""
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return f'{n} периодов'
    last = n % 10
    if last == 1:
        return f'{n} период'
    if 2 <= last <= 4:
        return f'{n} периода'
    return f'{n} периодов'


def _read_json(path: Path) -> Dict[str, Any]:
    """Мягкое чтение json проекта: отсутствие/битый файл не роняют расчёт."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001 - чтение настроек не должно ронять фронтир
        pass
    return {}


def resolve_economics(
    project_dir: str,
    cfg: Optional[Dict[str, Any]] = None,
    economics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Три режима перевода KPI в деньги, четвёртый исход — отказ.

    | Режим            | Прибыль            | Условие максимума     |
    |------------------|--------------------|-----------------------|
    | `profit_kpi`     | П(B) = S(B) − B    | предельная отдача = 1 |
    | `count_value`    | П(B) = v·S(B) − B  | отдача = 1/v          |
    | `monetary_margin`| П(B) = m·S(B) − B  | отдача = 1/m          |

    Здесь S(B) — прирост продаж ОТ МЕДИА (без базового уровня), см.
    `compute_profit_frontier`: базовый уровень к бюджету не привязан и в прибыль
    от медиа не входит. На положение максимума это не влияет (константа), на
    величину прибыли — влияет, и молчаливое включение базы завышало бы её в разы.

    Цепочка источников (SSOT, как `_resolve_current_unit_costs` в goal-seek):
    запрос > `settings/v13_kpi.json` > `project.json` > конфигурация модели
    (последняя — только если её передали: быстрый путь отказа модель не читает,
    чтобы «не хватает экономики» стоило сотые доли секунды, а не чтения pickle).
    Валовой маржи для денежных метрик сегодня нет ни в одном хранилище — её
    передаёт вызывающая сторона; без неё честный отказ.

    Returns:
        {'mode': str, 'unit_value': float, 'marginal_threshold': float,
         'kpi_type': str, 'kpi_kind': str, 'source': {...}}
        либо {'mode': None, 'reason': str, 'message': str, ...} — отказ.
    """
    economics = economics or {}
    cfg = cfg or {}
    project_path = Path(project_dir)
    proj = _read_json(project_path / 'project.json')
    settings = _read_json(project_path / 'settings' / 'v13_kpi.json')

    # ── тип KPI ──────────────────────────────────────────────────────────────
    kpi_type = (economics.get('kpi_type')
                or proj.get('kpi_type')
                or cfg.get('kpi_type'))
    kpi_kind = None
    if isinstance(kpi_type, str):
        try:
            from utils.kpi_registry import get_kpi_config
            kpi_kind = get_kpi_config(kpi_type).kpi_kind
        except Exception:  # noqa: BLE001 - неизвестный тип обрабатываем ниже
            kpi_kind = None
    if kpi_kind is None:
        # Запасной путь: явное поле проекта (заполняется мастером настройки).
        kpi_kind = settings.get('kpi_kind') or proj.get('kpi_kind')

    if kpi_kind not in ('monetary', 'count'):
        return {
            'mode': None,
            'reason': 'kpi_kind_unsupported',
            'kpi_type': kpi_type,
            'kpi_kind': kpi_kind,
            'message': (
                'Для этой метрики прибыль не считается: её значение не переводится '
                'в рубли напрямую. Профит-фронтир доступен для денежных и счётных '
                'метрик (продажи в рублях, упаковки, лиды и подобные).'
            ),
        }

    # ── режим 1: KPI и есть прибыль ──────────────────────────────────────────
    if kpi_type == 'profit':
        return {
            'mode': 'profit_kpi',
            'unit_value': 1.0,
            'marginal_threshold': 1.0,
            'kpi_type': kpi_type,
            'kpi_kind': kpi_kind,
            'source': {'unit_value': 'kpi_is_profit'},
        }

    # ── режим 2: счётная метрика с ценностью единицы ─────────────────────────
    if kpi_kind == 'count':
        vpcu = economics.get('value_per_count_unit')
        source = 'request'
        if vpcu is None:
            vpcu = settings.get('value_per_count_unit')
            source = 'project_settings'
        if vpcu is None:
            vpcu = proj.get('value_per_count_unit')
            source = 'project_json'
        try:
            vpcu = float(vpcu) if vpcu is not None else None
        except (TypeError, ValueError):
            vpcu = None
        if vpcu is None or vpcu <= 0:
            label = ''
            try:
                from utils.kpi_registry import get_value_per_count_unit_label
                label = get_value_per_count_unit_label(kpi_type)
            except Exception:  # noqa: BLE001 - подпись необязательна
                label = ''
            label_part = f' ({label})' if label else ''
            return {
                'mode': None,
                'reason': 'count_value_missing',
                'kpi_type': kpi_type,
                'kpi_kind': kpi_kind,
                'message': (
                    f'Чтобы посчитать прибыль, нужна ценность одной единицы{label_part}. '
                    'Метрика проекта счётная: без ценности единицы перевести штуки '
                    'в рубли нельзя, а без рублей максимума прибыли не существует. '
                    'Задайте ценность единицы и повторите расчёт.'
                ),
            }
        return {
            'mode': 'count_value',
            'unit_value': vpcu,
            'marginal_threshold': 1.0 / vpcu,
            'kpi_type': kpi_type,
            'kpi_kind': kpi_kind,
            'source': {'unit_value': source},
        }

    # ── режим 3: денежная метрика + валовая маржа ────────────────────────────
    margin = economics.get('gross_margin')
    if margin is None:
        margin = settings.get('gross_margin')
        margin_source = 'project_settings'
    else:
        margin_source = 'request'
    if margin is None:
        return {
            'mode': None,
            'reason': 'monetary_margin_missing',
            'kpi_type': kpi_type,
            'kpi_kind': kpi_kind,
            'message': (
                'Чтобы посчитать прибыль, нужна валовая маржа – доля прибыли '
                'в рубле продаж. Метрика проекта измеряется в рублях выручки: '
                'выручка растёт с бюджетом всегда, поэтому «оптимум по обороту» '
                'был бы неправдой. Задайте валовую маржу и повторите расчёт.'
            ),
        }
    try:
        margin = float(margin)
    except (TypeError, ValueError):
        margin = float('nan')
    if not (0.0 < margin <= 1.0):
        return {
            'mode': None,
            'reason': 'gross_margin_out_of_range',
            'kpi_type': kpi_type,
            'kpi_kind': kpi_kind,
            'message': (
                'Валовая маржа должна быть долей от нуля до единицы '
                '(например, 0,3 для 30%). Проверьте значение и повторите расчёт.'
            ),
        }
    return {
        'mode': 'monetary_margin',
        'unit_value': margin,
        'marginal_threshold': 1.0 / margin,
        'kpi_type': kpi_type,
        'kpi_kind': kpi_kind,
        'source': {'unit_value': margin_source},
    }


def build_budget_grid(
    current_total: float,
    n_points: int = 25,
    lo_multiplier: float = 0.2,
    hi_multiplier: float = 3.0,
) -> Dict[str, Any]:
    """Сетка бюджетов с ОБЯЗАТЕЛЬНОЙ точкой текущего бюджета.

    Равномерная сетка множителей 0,2…3,0 не содержит 1,0 (шаг 2,8/24 = 0,11667),
    поэтому ближайший к текущему узел заменяем ровно на текущий бюджет: число
    точек и порядок сохраняются, а «где я сейчас» не рисуется интерполяцией.

    Returns:
        {'budgets': [...], 'current_index': int, 'step': float, 'multipliers': [...]}
    """
    import numpy as _np

    if n_points < 3:
        n_points = 3
    mult = _np.linspace(float(lo_multiplier), float(hi_multiplier), int(n_points))
    budgets = mult * float(current_total)
    current_index = int(_np.argmin(_np.abs(budgets - float(current_total))))
    budgets[current_index] = float(current_total)
    mult[current_index] = 1.0
    step = float(budgets[1] - budgets[0]) if n_points > 1 else 0.0
    return {
        'budgets': [float(b) for b in budgets],
        'multipliers': [float(m) for m in mult],
        'current_index': current_index,
        'step': step,
    }


def _profit_from_media(unit_value, media_sales, budget):
    """П(B) = v·S_медиа(B) − B — ЕДИНСТВЕННОЕ место, где ценность единицы входит
    в прибыль.

    Работает и на скаляре (точечная кривая), и на матрице апостериорных выборок
    (numpy broadcasting): формула не дублируется, поэтому положение максимума и
    интервал на него не могут разъехаться.
    """
    return unit_value * media_sales - budget


def compute_profit_frontier(
    project_dir: str,
    economics: Optional[Dict[str, Any]] = None,
    *,
    n_points: int = 25,
    lo_multiplier: float = 0.2,
    hi_multiplier: float = 3.0,
    max_samples: int = 200,
    unit_costs_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Кривая прибыли по суммарному бюджету + максимум с честной границей данных.

    Args:
        project_dir: каталог проекта с `models/latest.pkl`.
        economics: {'kpi_type', 'value_per_count_unit', 'gross_margin'} — что задано
            явно, приоритетнее хранилищ проекта (см. `resolve_economics`).
        n_points: точек сетки (25 по контракту).
        lo_multiplier / hi_multiplier: границы сетки в долях текущего бюджета.
        max_samples: апостериорных выборок на точку. ОДИН И ТОТ ЖЕ для всех точек
            сетки — `posterior_sampler` отбирает выборки детерминированным шагом
            `arange(0, n, n // max_samples)`, поэтому при равном max_samples индексы
            и порядок совпадают между точками. Иначе интервал на положение
            максимума превратился бы в шум (аргмаксы считались бы по разным
            выборкам).
        unit_costs_override: стоимость единицы из запроса (цепочка SSOT goal-seek).

    Returns:
        При успехе — словарь со `status='ok'`, блоками `period`, `economics`,
        `grid`, `curve`, `current`, `observed_frontier`, `maximum`,
        `posterior_interval`.
        Без экономики — `status='economics_required'` с причиной и объяснением
        (не нулевая прибыль: INV-50).
    """
    import numpy as _np

    model_path = Path(project_dir) / 'models' / 'latest.pkl'
    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель.',
        }

    # Экономику решаем ДО тяжёлой работы: отказ не должен стоить чтения модели.
    cfg_for_economics: Dict[str, Any] = {}
    econ = resolve_economics(project_dir, cfg_for_economics, economics)
    if econ.get('mode') is None:
        return {
            'status': 'economics_required',
            'error_code': 'ECONOMICS_REQUIRED',
            'reason': econ.get('reason'),
            'message': econ.get('message'),
            'kpi_type': econ.get('kpi_type'),
            'kpi_kind': econ.get('kpi_kind'),
        }

    unit_value = float(econ['unit_value'])

    from optimize.inverse import build_proportional_forward
    forward, meta = build_proportional_forward(
        project_dir, unit_costs_override=unit_costs_override)

    current_total = float(meta.get('current_total_money') or 0.0)
    if current_total <= 0:
        return {
            'status': 'error',
            'error_code': 'NO_CURRENT_BUDGET',
            'message': (
                'Текущий суммарный бюджет по данным равен нулю – сетку «от текущего '
                'бюджета» построить не от чего. Проверьте стоимость единицы '
                'по каналам и данные о тратах.'
            ),
        }
    baseline_total = float(meta.get('baseline_total') or 0.0)

    grid = build_budget_grid(current_total, n_points, lo_multiplier, hi_multiplier)
    budgets: List[float] = grid['budgets']
    current_index: int = grid['current_index']

    reporter = meta.get('extrapolation_reporter')

    curve: List[Dict[str, Any]] = []
    for idx, budget in enumerate(budgets):
        point = forward(budget)
        if point.get('status') != 'ok':
            return {
                'status': 'error',
                'error_code': 'FORWARD_FAILED',
                'message': (
                    f'Не удалось рассчитать продажи при бюджете {_money_ru(budget)} ₽. '
                    f'{point.get("error_message", "")}'
                ).strip(),
            }
        sales_total = float(point['expected_sales'])

        # Предельная отдача — ЛОКАЛЬНАЯ производная dS/dB (центральная разность).
        # Именно производная, а не хорда между узлами сетки: условие максимума
        # прибыли dП/dB = 0 ⇔ v·dS/dB = 1 записано на производной, а хорда на
        # вогнутой кривой систематически её завышает (на реальной модели —
        # на 15–32%, зонд 2026-08-16).
        delta = _MARGINAL_DELTA_PCT * budget
        s_plus = forward(budget + delta)
        s_minus = forward(budget - delta)
        marginal = None
        if s_plus.get('status') == 'ok' and s_minus.get('status') == 'ok':
            marginal = float(
                (s_plus['expected_sales'] - s_minus['expected_sales']) / (2 * delta))

        severity = None
        extrapolation_channels: List[Dict[str, Any]] = []
        if callable(reporter):
            try:
                report = reporter(point.get('distribution') or {})
                severity = int(report.get('severity', 0))
                extrapolation_channels = report.get('channels') or []
            except Exception:  # noqa: BLE001 - честность-контур не роняет расчёт
                severity = None

        media_sales = sales_total - baseline_total
        entry: Dict[str, Any] = {
            'index': idx,
            'multiplier': grid['multipliers'][idx],
            'budget': budget,
            'sales_total': sales_total,
            'sales_from_media': media_sales,
            'profit': float(_profit_from_media(unit_value, media_sales, budget)),
            'is_current': idx == current_index,
            'basis': PERIOD_BASIS,
        }
        if marginal is not None:
            entry['marginal_return'] = marginal
        if severity is not None:
            entry['extrapolation_severity'] = severity
            if severity > 0 and extrapolation_channels:
                entry['extrapolation_channels'] = extrapolation_channels
        curve.append(entry)

    profits = _np.array([p['profit'] for p in curve], dtype=float)
    severities = [p.get('extrapolation_severity') for p in curve]

    # ── честная граница наблюдений: наибольший бюджет с severity 0 ────────────
    observed_idx = None
    for idx, sev in enumerate(severities):
        if sev == 0:
            observed_idx = idx
    if observed_idx is None:
        observed_frontier: Dict[str, Any] = {
            'available': False,
            'reason': ('no_zero_severity_point' if any(s is not None for s in severities)
                       else 'extrapolation_unavailable'),
            'message': (
                'Ни одна точка сетки не укладывается в наблюдавшийся диапазон трат – '
                'граница данных не определяется.'
                if any(s is not None for s in severities) else
                'Выход за наблюдавшийся диапазон не рассчитан – граница данных '
                'не определяется.'
            ),
        }
    else:
        of = curve[observed_idx]
        observed_frontier = {
            'available': True,
            'index': observed_idx,
            'budget': of['budget'],
            'multiplier': of['multiplier'],
            'sales_total': of['sales_total'],
            'profit': of['profit'],
            'basis': PERIOD_BASIS,
        }
        if 'marginal_return' in of:
            observed_frontier['marginal_return'] = of['marginal_return']

    # ── максимум прибыли: один из трёх исходов ───────────────────────────────
    max_idx = int(_np.argmax(profits))
    max_point = curve[max_idx]
    max_severity = severities[max_idx]
    at_grid_floor = max_idx == 0
    at_grid_ceiling = max_idx == len(curve) - 1
    beyond_observed = (max_severity is None) or (max_severity > 0)
    # Максимум пришёлся на САМУ границу наблюдений — последнюю точку, где данные
    # ещё есть. Число честное (severity 0), но убывание прибыли за ним опирается
    # на область, которую данные не проверяют, поэтому потребитель обязан это
    # видеть. `at_grid_ceiling` эту ситуацию НЕ ловит: он про край расчётной
    # сетки (3× текущего), а не про край данных.
    at_observed_frontier = bool(
        observed_frontier.get('available')
        and observed_frontier.get('index') == max_idx
    )
    profit_at_current = float(curve[current_index]['profit'])

    maximum: Dict[str, Any] = {
        'at_grid_floor': at_grid_floor,
        'at_grid_ceiling': at_grid_ceiling,
        'at_observed_frontier': at_observed_frontier,
        'basis': PERIOD_BASIS,
    }
    if beyond_observed or at_grid_ceiling:
        # 🔴 Оптимума, которого не видели в данных, не рисуем: за правым краем
        # наблюдений кривая данными не идентифицируется (Chan & Perry 2017).
        maximum['outcome'] = 'beyond_observed'
        maximum['reportable'] = False
        maximum['still_profitable_within_data'] = True
        if max_severity is not None:
            maximum['severity_at_grid_argmax'] = max_severity
        if observed_frontier.get('available'):
            maximum['message'] = (
                'В пределах ваших данных увеличение бюджета остаётся выгодным: '
                'прибыль растёт до самой границы наблюдавшихся трат '
                f'({_money_ru(observed_frontier["budget"])} ₽ суммарно за период '
                'обучения). Где проходит потолок, эти данные не показывают – модель '
                'за границей наблюдений не проверяется данными, и точку максимума '
                'мы не называем.'
            )
        else:
            maximum['message'] = (
                'Прибыль растёт на всём рассмотренном диапазоне бюджета, а границу '
                'наблюдавшихся трат определить не удалось – точку максимума '
                'мы не называем.'
            )
    elif at_grid_floor:
        # Red-team №5: максимум упёрся в левый край сетки – значит он лежит ниже
        # рассмотренного диапазона, а не «равен 0,2× текущего».
        maximum['outcome'] = 'below_current'
        maximum['reportable'] = False
        maximum['profit_at_current'] = profit_at_current
        maximum['message'] = (
            'Вы уже за точкой максимальной прибыли: она лежит ниже рассмотренного '
            f'диапазона (менее {_money_ru(budgets[0])} ₽ суммарно за период '
            'обучения). Точное положение мы не называем – оно вне расчётной сетки.'
        )
    else:
        maximum['outcome'] = ('below_current' if max_idx < current_index
                              else 'interior_observed')
        maximum['reportable'] = True
        maximum['index'] = max_idx
        maximum['budget'] = max_point['budget']
        maximum['multiplier'] = max_point['multiplier']
        maximum['profit'] = max_point['profit']
        maximum['sales_total'] = max_point['sales_total']
        maximum['severity'] = max_severity
        maximum['grid_step'] = grid['step']
        if 'marginal_return' in max_point:
            maximum['marginal_return'] = max_point['marginal_return']
        if maximum['outcome'] == 'below_current':
            maximum['profit_at_current'] = profit_at_current
            maximum['profit_lost_at_current'] = max_point['profit'] - profit_at_current
            maximum['message'] = (
                'Вы уже за точкой максимальной прибыли: она примерно при '
                f'{_money_ru(max_point["budget"])} ₽ суммарно за период обучения. '
                'На текущем бюджете теряется около '
                f'{_money_ru(max_point["profit"] - profit_at_current)} ₽ прибыли '
                'за тот же период.'
            )
        else:
            maximum['profit_at_current'] = profit_at_current
            maximum['profit_gain_vs_current'] = max_point['profit'] - profit_at_current
            maximum['message'] = (
                'Максимум прибыли лежит внутри наблюдавшегося диапазона – около '
                f'{_money_ru(max_point["budget"])} ₽ суммарно за период обучения '
                f'(шаг сетки {_money_ru(grid["step"])} ₽).'
            )
        if at_observed_frontier:
            # Число оставляем – оно честное (severity 0). Но говорим, что дальше
            # этой точки данных нет, а значит спад прибыли за ней не подтверждён.
            maximum['message'] += (
                ' Максимум пришёлся на саму границу наблюдавшихся трат: за ней '
                'поведение кривой данными не подтверждается.'
            )

    # ── 90% интервал на ПОЛОЖЕНИЕ максимума по апостериорным выборкам ─────────
    posterior_interval = _posterior_maximum_interval(
        meta=meta,
        budgets=budgets,
        severities=severities,
        unit_value=unit_value,
        max_samples=max_samples,
    )

    period = {
        'basis': PERIOD_BASIS,
        'n_periods': meta.get('n_periods'),
        'granularity': (meta.get('period_granularity') or {}).get('granularity'),
        'granularity_label_ru': _period_label_ru(meta.get('period_granularity')),
    }
    n_p = period['n_periods']
    period['note'] = (
        'Бюджет и продажи – суммарные за весь период обучения'
        + (f' ({_ru_periods(n_p)}, {period["granularity_label_ru"]})' if n_p else '')
        + ', не за один месяц.'
    )

    return {
        'status': 'ok',
        'period': period,
        'economics': {
            'mode': econ['mode'],
            'unit_value': unit_value,
            'marginal_threshold': econ['marginal_threshold'],
            'kpi_type': econ.get('kpi_type'),
            'kpi_kind': econ.get('kpi_kind'),
            'source': econ.get('source'),
            'profit_definition': 'media_revenue_minus_budget',
            'note': (
                'Прибыль считается от медиа: базовый уровень продаж (то, что '
                'продаётся без рекламы) в неё не входит – он не зависит от бюджета.'
            ),
        },
        'grid': {
            'n_points': len(curve),
            'lo_multiplier': lo_multiplier,
            'hi_multiplier': hi_multiplier,
            'step': grid['step'],
            'current_index': current_index,
        },
        'current': {
            'budget': current_total,
            'sales_total': curve[current_index]['sales_total'],
            'profit': profit_at_current,
            'basis': PERIOD_BASIS,
            **({'marginal_return': curve[current_index]['marginal_return']}
               if 'marginal_return' in curve[current_index] else {}),
        },
        'baseline_sales_total': baseline_total,
        'curve': curve,
        'observed_frontier': observed_frontier,
        'maximum': maximum,
        'posterior_interval': posterior_interval,
        'marginal_return_method': 'central_difference_1pct',
        # Пропорции каналов фиксированы (масштабируется текущий микс): фронтир
        # отвечает «сколько тратить при нынешнем распределении», а не «сколько
        # тратить, если ещё и переложить» (red-team №1 контракта).
        'allocation_mode': 'proportional',
        'allocation_note': (
            'Расчёт масштабирует текущее распределение бюджета между каналами. '
            'Это ответ на вопрос «сколько тратить при нынешнем распределении», '
            'а не «сколько тратить, если ещё и переложить между каналами».'
        ),
    }


def _posterior_maximum_interval(
    meta: Dict[str, Any],
    budgets: List[float],
    severities: List[Optional[int]],
    unit_value: float,
    max_samples: int,
) -> Dict[str, Any]:
    """90% интервал на ПОЛОЖЕНИЕ максимума прибыли по апостериорным выборкам.

    Для каждой выборки считаем всю кривую прибыли по той же сетке и берём её
    аргмаксимум → распределение B* → HDI (SSOT `compute_ci_hdi`, как в split_ci).

    Выборки обязаны быть согласованы между точками сетки: `posterior_sampler`
    отбирает их детерминированным шагом от одного и того же `max_samples`,
    поэтому индексы и порядок совпадают. Согласованность проверяем явно по длине
    массивов; расхождение → интервал недоступен, а не молча посчитанный шум.

    Базовый уровень берём из той же апостериорной выборки при нулевом бюджете
    (`sampler(0)`), чтобы прибыль от медиа считалась внутри одной выборки.

    `None` от сэмплера (модель малых данных, МНК/legacy) — законный случай:
    кривая и максимум есть, интервала нет, и об этом сказано полем, а не нулём.
    """
    import numpy as _np

    sampler = meta.get('posterior_sampler')
    if not callable(sampler):
        return {
            'available': False,
            'reason': 'no_posterior_sampler',
            'message': ('Апостериорные выборки для этой модели недоступны – '
                        'интервал на положение максимума не рассчитывается.'),
        }

    unavailable = {
        'available': False,
        'reason': 'no_posterior_samples',
        'message': (
            'Модель обучена без байесовского вывода (малые данные, метод '
            'наименьших квадратов) – апостериорных выборок нет. Кривая прибыли '
            'и положение максимума рассчитаны, интервал на положение максимума – '
            'нет.'
        ),
    }

    try:
        base_arr = sampler(0.0, max_samples=max_samples)
        if base_arr is None or len(base_arr) < 4:
            return unavailable
        n_samples = len(base_arr)
        base_arr = _np.asarray(base_arr, dtype=float)

        sales = _np.empty((len(budgets), n_samples), dtype=float)
        for j, budget in enumerate(budgets):
            arr = sampler(budget, max_samples=max_samples)
            if arr is None:
                return unavailable
            if len(arr) != n_samples:
                # Рассогласование выборок между точками сетки сделало бы интервал
                # шумом: аргмаксимумы считались бы по разным наборам параметров.
                return {
                    'available': False,
                    'reason': 'inconsistent_samples',
                    'message': ('Апостериорные выборки в точках сетки не совпали '
                                'между собой – интервал на положение максимума '
                                'не рассчитывается.'),
                }
            sales[j, :] = _np.asarray(arr, dtype=float)

        budgets_arr = _np.asarray(budgets, dtype=float)
        profits = _profit_from_media(
            unit_value, sales - base_arr[None, :], budgets_arr[:, None])
        arg = _np.argmax(profits, axis=0)
        optimum_budgets = budgets_arr[arg]

        from utils.posterior_propagation import compute_ci_hdi
        mean, low, high, method = compute_ci_hdi(optimum_budgets, hdi_prob=0.9)

        sev_arr = _np.array(
            [(-1 if s is None else int(s)) for s in severities], dtype=int)
        beyond = sev_arr[arg]
        return {
            'available': True,
            'hdi_prob': 0.9,
            'low': float(low),
            'high': float(high),
            'mean': float(mean),
            'method': method,
            'n_samples': int(n_samples),
            'share_at_grid_floor': float(_np.mean(arg == 0)),
            'share_at_grid_ceiling': float(_np.mean(arg == len(budgets) - 1)),
            'share_beyond_observed': float(_np.mean(beyond != 0)),
            'basis': PERIOD_BASIS,
            'note': (
                'Интервал отражает неуверенность модели в параметрах, а не разброс '
                'будущего факта.'
            ),
        }
    except Exception:  # noqa: BLE001 - честность-контур не должен ронять фронтир
        return {
            'available': False,
            'reason': 'posterior_failed',
            'message': ('Не удалось рассчитать интервал на положение максимума '
                        'по апостериорным выборкам. Кривая и максимум рассчитаны.'),
        }
