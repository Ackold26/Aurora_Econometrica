"""Тесты профит-фронтира (2026-08-16), контракт Projects/FRONTIER_DESIGN_2026-08-16.md.

Стратегия подмены: `compute_profit_frontier` читает pickle и обучающие данные
(тяжело), поэтому подменяем `optimize.inverse.build_proportional_forward` —
границу, за которой начинается наша логика. Кривая синтетическая с ИЗВЕСТНЫМ
аналитическим ответом:

    S_медиа(B) = K·√B  ⇒  П(B) = v·K·√B − B  ⇒  dП/dB = 0 при B* = (v·K/2)²

то есть положение максимума считается на бумаге и сверяется с расчётом в пределах
шага сетки.

Покрытие по контракту: (а) синтетика с известным ответом, (б) три исхода
максимума по отдельности, (в) отказ при отсутствии экономики, (г) `None` от
апостериорного сэмплера не роняет расчёт, (д) максимум за границей наблюдений
не выдаётся как ответ.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize.frontier import compute_profit_frontier  # noqa: E402

CURRENT = 1.0e6
BASELINE = 5.0e6
# Границы «наблюдавшихся» трат синтетики: до 1,8 млн — severity 0, до 2,4 млн — 1.
SEV_1 = 1.8e6
SEV_2 = 2.4e6


def _prep_model(tmp_path: Path) -> str:
    """Каталог проекта с models/latest.pkl (расчёт проверяет наличие модели)."""
    models_dir = tmp_path / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / 'latest.pkl').write_bytes(b'dummy')
    return str(tmp_path)


def _k_for_optimum(target_budget: float, unit_value: float) -> float:
    """K, при котором максимум прибыли лежит ровно в target_budget: K = 2·√B*/v."""
    return 2.0 * math.sqrt(target_budget) / unit_value


def _install_forward(monkeypatch, k: float, sampler=None, n_periods: int = 31,
                     sev_1: float = SEV_1, sev_2: float = SEV_2,
                     drop_meta_keys=()):
    """Подменяет прямой проход синтетикой S(B) = BASELINE + K·√B.

    `sev_1`/`sev_2` — границы наблюдавшихся трат синтетики (поднимаются, когда
    нужен случай «данные не кончились, кончилась сетка»).
    `drop_meta_keys` — убрать ключи из `meta` (проверка реакции на неполный
    контракт прямого прохода).
    """

    def forward(budget: float):
        b = max(float(budget), 0.0)
        return {
            'expected_sales': BASELINE + k * math.sqrt(b),
            'distribution': {'TV': 0.6 * b, 'Digital': 0.4 * b},
            'status': 'ok',
        }

    def reporter(distribution):
        total = sum(float(v) for v in (distribution or {}).values())
        severity = 0 if total <= sev_1 else (1 if total <= sev_2 else 2)
        return {'severity': severity, 'channels': []}

    meta = {
        'current_total_money': CURRENT,
        'baseline_total': BASELINE,
        'extrapolation_reporter': reporter,
        'posterior_sampler': sampler,
        'n_periods': n_periods,
        'period_granularity': {'granularity': 'M', 'confidence': 0.97},
    }
    for key in drop_meta_keys:
        meta.pop(key, None)
    monkeypatch.setattr(
        'optimize.inverse.build_proportional_forward',
        lambda project_dir, unit_costs_override=None: (forward, meta),
    )


def _sampler_factory(k_values):
    """Апостериорный сэмплер: у каждой выборки свой K (разброс параметров)."""
    arr = np.asarray(k_values, dtype=float)

    def sampler(budget: float, max_samples: int = 200):
        n = min(len(arr), max_samples)
        return BASELINE + arr[:n] * math.sqrt(max(float(budget), 0.0))

    return sampler


# ─── (а) синтетика с известным ответом ───────────────────────────────────────

def test_maximum_matches_analytic_optimum_within_grid_step(monkeypatch, tmp_path):
    """Положение максимума совпадает с аналитическим в пределах шага сетки."""
    project = _prep_model(tmp_path)
    target = 1.4e6           # внутри наблюдений (severity 0) и правее текущего
    margin = 0.3
    _install_forward(monkeypatch, _k_for_optimum(target, margin))

    result = compute_profit_frontier(project, {'kpi_type': 'sales',
                                               'gross_margin': margin})

    assert result['status'] == 'ok'
    maximum = result['maximum']
    assert maximum['reportable'] is True
    step = result['grid']['step']
    assert abs(maximum['budget'] - target) <= step, (
        f"максимум {maximum['budget']:,.0f} против аналитического {target:,.0f} "
        f"при шаге сетки {step:,.0f}")
    # Условие максимума: предельная отдача ≈ 1/маржа (порог из режима экономики).
    assert result['economics']['marginal_threshold'] == pytest.approx(1.0 / margin)
    assert maximum['marginal_return'] == pytest.approx(1.0 / margin, rel=0.15)


def test_current_budget_point_is_always_on_the_grid(monkeypatch, tmp_path):
    """Точка текущего бюджета в сетке ровно (не интерполяцией), точек 25."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['grid']['n_points'] == 25
    idx = result['grid']['current_index']
    assert result['curve'][idx]['budget'] == pytest.approx(CURRENT)
    assert result['curve'][idx]['is_current'] is True
    assert sum(1 for p in result['curve'] if p['is_current']) == 1
    assert result['current']['budget'] == pytest.approx(CURRENT)


def test_every_number_carries_period_marker(monkeypatch, tmp_path):
    """Единицы: каждое число несёт признак периода (сколько периодов и шаг)."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3), n_periods=31)

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    period = result['period']
    assert period['n_periods'] == 31
    assert period['granularity_label_ru'] == 'по месяцам'
    assert '31 период, по месяцам' in period['note']  # согласование, не «31 периодов»
    assert 'не за один месяц' in period['note']
    assert all(p['basis'] == 'total_over_training_period' for p in result['curve'])
    for block in ('current', 'observed_frontier', 'maximum'):
        assert result[block]['basis'] == 'total_over_training_period'


# ─── (б) три исхода максимума по отдельности ─────────────────────────────────

def test_outcome_interior_observed(monkeypatch, tmp_path):
    """Исход 1: максимум внутри наблюдавшегося диапазона — называем числом."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    maximum = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 0.3})['maximum']

    assert maximum['outcome'] == 'interior_observed'
    assert maximum['reportable'] is True
    assert maximum['severity'] == 0
    assert maximum['profit_gain_vs_current'] > 0
    # Максимум с запасом внутри данных — про границу наблюдений не говорим.
    assert maximum['at_observed_frontier'] is False
    assert 'границу наблюдавшихся трат' not in maximum['message']


def test_maximum_exactly_on_observed_frontier_is_flagged(monkeypatch, tmp_path):
    """Максимум пришёлся на САМУ границу наблюдений — отдельный признак.

    Число честное (severity 0) и остаётся, но за этой точкой данных нет: спад
    прибыли правее опирается на непроверенную область. `at_grid_ceiling` этот
    случай не ловит — он про край расчётной сетки (3× текущего), не про край
    данных. Приёмка ведущей на живой модели: маржа 50% давала максимум ровно
    в `observed_frontier.budget` и подавалась как обычный внутренний.
    """
    project = _prep_model(tmp_path)
    # Последний узел сетки с severity 0: шаг 2,8/24 от 1 млн → узел 13 = 1 716 666,67,
    # следующий (1 833 333) уже за порогом наблюдений SEV_1 = 1,8 млн.
    frontier_budget = 0.2e6 + 13 * (2.8e6 / 24)
    _install_forward(monkeypatch, _k_for_optimum(frontier_budget, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})
    maximum = result['maximum']

    assert maximum['index'] == result['observed_frontier']['index']
    assert maximum['at_observed_frontier'] is True
    assert maximum['at_grid_ceiling'] is False, 'край данных ≠ край сетки'
    # Число остаётся: оно честное.
    assert maximum['reportable'] is True
    assert maximum['budget'] == pytest.approx(result['observed_frontier']['budget'])
    assert maximum['severity'] == 0
    assert ('Максимум пришёлся на саму границу наблюдавшихся трат: за ней '
            'поведение кривой данными не подтверждается.') in maximum['message']


def test_outcome_beyond_observed_gives_no_number(monkeypatch, tmp_path):
    """Исход 2 + приёмка (д): максимум за границей наблюдений НЕ выдаётся числом."""
    project = _prep_model(tmp_path)
    # B* = 2,8 млн — за severity 0 (1,8 млн), но внутри сетки (до 3 млн).
    _install_forward(monkeypatch, _k_for_optimum(2.8e6, 0.5))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.5})
    maximum = result['maximum']

    assert maximum['outcome'] == 'beyond_observed'
    assert maximum['reportable'] is False
    assert 'budget' not in maximum, 'оптимум за границей данных не называем числом'
    assert 'profit' not in maximum
    assert maximum['still_profitable_within_data'] is True
    # Клиентский текст: число с пробелами между разрядами, запятые русского
    # предложения на месте (форматируем число, а не подменяем запятые в фразе).
    # Число округлено до разряда, соотнесённого с шагом сетки (F-17).
    from optimize.frontier import _round_to_resolution
    expected_number = f'{_round_to_resolution(result["observed_frontier"]["budget"], result["grid"]["step"]):,.0f}'.replace(',', ' ')
    assert f'{expected_number} ₽' in maximum['message']
    assert 'Где проходит потолок, эти данные не показывают' in maximum['message']
    # Честная граница наблюдений — наибольший бюджет с severity 0 — на месте.
    frontier = result['observed_frontier']
    assert frontier['available'] is True
    assert frontier['budget'] <= SEV_1
    assert result['curve'][frontier['index'] + 1]['extrapolation_severity'] > 0


def test_outcome_below_current(monkeypatch, tmp_path):
    """Исход 3: максимум левее текущего бюджета — с величиной потерь."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(0.6e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})
    maximum = result['maximum']

    assert maximum['outcome'] == 'below_current'
    assert maximum['reportable'] is True
    assert maximum['budget'] < CURRENT
    assert maximum['profit_lost_at_current'] > 0
    assert maximum['profit_lost_at_current'] == pytest.approx(
        maximum['profit'] - result['current']['profit'])


def test_outcome_at_grid_floor_is_not_reported_as_a_point(monkeypatch, tmp_path):
    """Red-team №5: максимум на левом краю сетки — не «оптимум = 0,2× текущего»."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(0.05e6, 0.3))

    maximum = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 0.3})['maximum']

    assert maximum['at_grid_floor'] is True
    assert maximum['reportable'] is False
    assert 'budget' not in maximum
    assert maximum['outcome'] == 'below_current'


# ─── (в) отказ при отсутствии экономики ──────────────────────────────────────

def test_refusal_when_margin_missing(monkeypatch, tmp_path):
    """Денежная метрика без валовой маржи — отказ с причиной, не нулевая прибыль."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales'})

    assert result['status'] == 'economics_required'
    assert result['reason'] == 'monetary_margin_missing'
    assert 'маржа' in result['message']
    assert 'curve' not in result and 'maximum' not in result
    assert 0 not in (result.get('profit'), result.get('maximum'))


def test_refusal_when_count_value_missing(monkeypatch, tmp_path):
    """Счётная метрика без ценности единицы — отказ, не «посчитаем по штукам»."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'leads'})

    assert result['status'] == 'economics_required'
    assert result['reason'] == 'count_value_missing'
    assert 'Ценность лида' in result['message']


def test_refusal_when_kpi_kind_unsupported(monkeypatch, tmp_path):
    """Доля (известность) в рубли напрямую не переводится — отказ."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'awareness'})

    assert result['status'] == 'economics_required'
    assert result['reason'] == 'kpi_kind_unsupported'


def test_refusal_when_margin_out_of_range(monkeypatch, tmp_path):
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 1.7})

    assert result['status'] == 'economics_required'
    assert result['reason'] == 'gross_margin_out_of_range'


def test_count_value_mode_reaches_same_optimum(monkeypatch, tmp_path):
    """Счётный режим с ценностью единицы: порог отдачи = 1/v, максимум на месте."""
    project = _prep_model(tmp_path)
    vpcu = 0.3
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, vpcu))

    result = compute_profit_frontier(
        project, {'kpi_type': 'leads', 'value_per_count_unit': vpcu})

    assert result['economics']['mode'] == 'count_value'
    assert result['economics']['marginal_threshold'] == pytest.approx(1.0 / vpcu)
    assert abs(result['maximum']['budget'] - 1.4e6) <= result['grid']['step']


def test_profit_kpi_mode_uses_unit_value_one(monkeypatch, tmp_path):
    """KPI = прибыль: перевод не нужен, условие максимума — отдача = 1."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 1.0))

    result = compute_profit_frontier(project, {'kpi_type': 'profit'})

    assert result['economics']['mode'] == 'profit_kpi'
    assert result['economics']['unit_value'] == 1.0
    assert result['economics']['marginal_threshold'] == 1.0
    assert abs(result['maximum']['budget'] - 1.4e6) <= result['grid']['step']


# ─── (г) апостериорные выборки ───────────────────────────────────────────────

def test_none_posterior_sampler_does_not_break_the_curve(monkeypatch, tmp_path):
    """Сэмплер вернул None — кривая и максимум есть, интервала нет, и об этом
    сказано полем, а не нулём.

    Аудит 2026-08-16 (F-02): раньше здесь утверждалось «модель обучена методом
    наименьших квадратов» — на ЛЮБОЙ None, при пяти разных причинах. Тест это
    закреплял. Теперь модель прочитать нельзя (в фикстуре заглушка вместо
    pickle), значит причина неизвестна — и продукт обязан сказать именно это,
    а не приписать чужой модели метод обучения (INV-50).
    """
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3),
                     sampler=lambda budget, max_samples=200: None)

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['status'] == 'ok'
    assert len(result['curve']) == 25
    assert result['maximum']['reportable'] is True
    interval = result['posterior_interval']
    assert interval['available'] is False
    assert interval['reason'] == 'posterior_unavailable_unknown'
    assert 'low' not in interval and 'high' not in interval
    assert 'наименьших квадратов' not in interval['message'], (
        'о методе обучения чужой модели не говорим, пока его не проверили')
    assert 'причину установить' in interval['message']


@pytest.mark.parametrize('model_data, expected_reason, forbidden_in_message', [
    # 1. Выборок нет по природе модели — единственный случай, где мы вправе
    #    говорить о методе обучения.
    ({'posterior_samples': {}, 'config': {}, 'normalization': {}},
     'no_posterior_samples', None),
    ({'config': {}, 'normalization': {}}, 'no_posterior_samples', None),
    # 2. Выборки есть, но форма массивов негодная — техническая причина.
    ({'posterior_samples': {'media_betas': np.zeros(5), 'alphas': np.zeros(5),
                            'gammas': np.zeros(5)},
      'config': {}, 'normalization': {}},
     'posterior_shape_unusable', 'наименьших квадратов'),
    ({'posterior_samples': {'media_betas': np.zeros((2, 1)), 'alphas': np.zeros((2, 1)),
                            'gammas': np.zeros((2, 1))},
      'config': {}, 'normalization': {}},
     'posterior_shape_unusable', 'наименьших квадратов'),
    # 3. Канал модели отсутствует в апостериорных колонках — техническая причина
    #    (частый путь: правка данных развела состав каналов с выборками).
    ({'posterior_samples': {'media_betas': np.zeros((2, 100)),
                            'alphas': np.zeros((2, 100)),
                            'gammas': np.zeros((2, 100)),
                            'media_columns': ['tv', 'digital']},
      'config': {'media_columns': ['tv', 'ooh']}, 'normalization': {}},
     'channel_absent_in_posterior', 'наименьших квадратов'),
    # 4. Состав в порядке — значит не-конечные значения либо исключение внутри.
    ({'posterior_samples': {'media_betas': np.zeros((2, 100)),
                            'alphas': np.zeros((2, 100)),
                            'gammas': np.zeros((2, 100)),
                            'media_columns': ['tv', 'digital']},
      'config': {'media_columns': ['tv', 'digital']}, 'normalization': {}},
     'posterior_compute_failed', 'наименьших квадратов'),
])
def test_posterior_absence_reasons_are_distinguished(
        model_data, expected_reason, forbidden_in_message):
    """F-02: пять причин `None` от сэмплера различаются, а не сводятся к одному
    утверждению о методе обучения чужой модели."""
    from optimize.frontier import _classify_posterior_absence_from_model

    verdict = _classify_posterior_absence_from_model(model_data)

    assert verdict['reason'] == expected_reason
    assert verdict['message']
    if forbidden_in_message:
        assert forbidden_in_message not in verdict['message'], (
            'о методе обучения говорим только там, где его проверили')


def test_too_few_posterior_samples_is_its_own_reason(monkeypatch, tmp_path):
    """Выборки ЕСТЬ, но их меньше четырёх: интервал не считаем, и причина —
    не «модель обучена без байесовского вывода»."""
    project = _prep_model(tmp_path)
    _install_forward(
        monkeypatch, _k_for_optimum(1.4e6, 0.3),
        sampler=lambda budget, max_samples=200: BASELINE + np.full(
            3, 3000.0) * math.sqrt(max(float(budget), 0.0)))

    interval = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 0.3})['posterior_interval']

    assert interval['available'] is False
    assert interval['reason'] == 'too_few_posterior_samples'
    assert interval['n_samples'] == 3
    assert 'наименьших квадратов' not in interval['message']


def test_posterior_failure_mid_grid_is_technical_not_model_nature(monkeypatch, tmp_path):
    """На нулевом бюджете выборки получились, на точке сетки — нет: причина
    заведомо техническая, о методе обучения не говорим."""
    project = _prep_model(tmp_path)
    calls = {'n': 0}

    def flaky(budget, max_samples=200):
        calls['n'] += 1
        if calls['n'] > 3:
            return None
        return BASELINE + np.full(200, 3000.0) * math.sqrt(max(float(budget), 0.0))

    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3), sampler=flaky)

    interval = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 0.3})['posterior_interval']

    assert interval['available'] is False
    assert interval['reason'] == 'posterior_failed_at_grid_point'
    assert 'наименьших квадратов' not in interval['message']
    assert 'failed_at_budget' in interval


def test_posterior_interval_on_maximum_position(monkeypatch, tmp_path):
    """Интервал на ПОЛОЖЕНИЕ максимума: разброс K → разброс B*, 90% интервал."""
    project = _prep_model(tmp_path)
    margin = 0.3
    k_point = _k_for_optimum(1.4e6, margin)
    rng = np.random.default_rng(7)
    k_values = k_point * (1.0 + 0.12 * rng.standard_normal(200))
    _install_forward(monkeypatch, k_point, sampler=_sampler_factory(k_values))

    result = compute_profit_frontier(project, {'kpi_type': 'sales',
                                               'gross_margin': margin})
    interval = result['posterior_interval']

    assert interval['available'] is True
    assert interval['n_samples'] == 200
    assert interval['low'] < interval['high']
    assert interval['low'] <= result['maximum']['budget'] <= interval['high']
    # Аналитический разброс: B*_s = (v·K_s/2)² — 90% выборок укладываются
    # в интервал по построению; проверяем порядок величины, не подгонку.
    analytic = (margin * k_values / 2.0) ** 2
    assert interval['low'] <= np.median(analytic) <= interval['high']
    assert interval['share_at_grid_floor'] < 0.5
    assert 'неуверенность модели' in interval['note']


def test_posterior_samples_must_be_consistent_across_grid(monkeypatch, tmp_path):
    """Рассогласованные выборки между точками сетки → интервал не считаем
    (иначе аргмаксимумы брались бы по разным наборам параметров = шум)."""
    project = _prep_model(tmp_path)
    calls = {'n': 0}

    def flaky_sampler(budget, max_samples=200):
        calls['n'] += 1
        size = 200 if calls['n'] <= 2 else 137
        return BASELINE + np.full(size, 3000.0) * math.sqrt(max(float(budget), 0.0))

    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3), sampler=flaky_sampler)

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['status'] == 'ok'
    assert result['posterior_interval']['available'] is False
    assert result['posterior_interval']['reason'] == 'inconsistent_samples'


def test_model_not_found(tmp_path):
    result = compute_profit_frontier(str(tmp_path), {'kpi_type': 'sales',
                                                     'gross_margin': 0.3})
    assert result['status'] == 'error'
    assert result['error_code'] == 'MODEL_NOT_FOUND'


# ─── (д) отказ покрывает ВСЕ числа положения максимума (аудит F-01) ──────────

def test_beyond_observed_withholds_posterior_interval_numbers(monkeypatch, tmp_path):
    """F-01: где максимум не называем, там не выдаём и чисел его положения.

    Интервал `low`/`high`/`mean` — рубли про ту же самую точку. Раньше отказ
    стоял только на ветке `maximum`, а рядом безусловно печатался диапазон,
    который клиент читает как ответ на вопрос «сколько тратить» (на живой
    модели: максимум «не называем» и тут же 355–780 млн, центр за границей
    наблюдений).
    """
    project = _prep_model(tmp_path)
    margin = 0.5
    k_point = _k_for_optimum(2.8e6, margin)      # максимум за границей наблюдений
    rng = np.random.default_rng(11)
    _install_forward(monkeypatch, k_point,
                     sampler=_sampler_factory(k_point * (1.0 + 0.1 * rng.standard_normal(200))))

    result = compute_profit_frontier(project, {'kpi_type': 'sales',
                                               'gross_margin': margin})
    maximum, interval = result['maximum'], result['posterior_interval']

    assert maximum['reportable'] is False
    assert interval['available'] is False
    assert interval['status'] == 'withheld'
    assert interval['reason'] == 'maximum_not_reportable'
    for key in ('low', 'high', 'mean'):
        assert key not in interval, f'{key}: числа положения максимума не выдаём'
    # Доли выборок — безразмерные, положения не называют и подпирают сам отказ.
    assert 0.0 <= interval['share_beyond_observed'] <= 1.0
    assert 'не выдаём' in interval['message']


def test_below_grid_floor_also_withholds_interval_numbers(monkeypatch, tmp_path):
    """Отказ на левом краю сетки — тот же класс: чисел положения не даём."""
    project = _prep_model(tmp_path)
    k_point = _k_for_optimum(0.05e6, 0.3)
    _install_forward(monkeypatch, k_point,
                     sampler=_sampler_factory(np.full(200, k_point)))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['maximum']['reportable'] is False
    assert result['posterior_interval']['available'] is False
    assert 'low' not in result['posterior_interval']


def test_reportable_maximum_keeps_its_interval(monkeypatch, tmp_path):
    """Обратная сторона F-01: там, где максимум называем, интервал остаётся –
    отказ не должен превратиться в «прячем всегда»."""
    project = _prep_model(tmp_path)
    margin = 0.3
    k_point = _k_for_optimum(1.4e6, margin)
    rng = np.random.default_rng(3)
    _install_forward(monkeypatch, k_point,
                     sampler=_sampler_factory(k_point * (1.0 + 0.05 * rng.standard_normal(200))))

    result = compute_profit_frontier(project, {'kpi_type': 'sales',
                                               'gross_margin': margin})

    assert result['maximum']['reportable'] is True
    assert result['posterior_interval']['available'] is True
    assert result['posterior_interval']['low'] < result['posterior_interval']['high']


# ─── интервал, усечённый сеткой (аудит F-12) ────────────────────────────────

def test_interval_truncated_by_grid_is_not_probabilistic(monkeypatch, tmp_path):
    """F-12: у выборок, чей оптимум вне сетки, аргмаксимум прижат к краю.

    Тогда граница интервала — артефакт `hi_multiplier`, а не свойство модели
    (на живой модели `high` был РОВНО 3× текущего бюджета при доле прижатых
    0,105). Вероятностным утверждением такой интервал подавать нельзя.
    """
    project = _prep_model(tmp_path)
    margin = 0.3
    k_point = _k_for_optimum(1.4e6, margin)       # точечный максимум внутри данных
    k_values = np.concatenate([
        np.full(160, k_point),                    # 80% выборок — там же
        np.full(40, k_point * 1.7),               # 20% — оптимум за краем сетки
    ])
    _install_forward(monkeypatch, k_point, sampler=_sampler_factory(k_values))

    result = compute_profit_frontier(project, {'kpi_type': 'sales',
                                               'gross_margin': margin})
    interval = result['posterior_interval']

    assert result['maximum']['reportable'] is True, 'точечный максимум внутри данных'
    assert interval['available'] is True
    assert interval['share_at_grid_ceiling'] > 0
    assert interval['high'] == pytest.approx(result['curve'][-1]['budget'])
    assert interval['truncated_by_grid'] is True
    assert interval['truncated_side'] == 'high'
    assert interval['is_probabilistic'] is False, (
        'усечённый сеткой интервал не подаём как вероятностное утверждение')
    assert 'граница нашего расчёта' in interval['caveat']


def test_interval_inside_grid_stays_probabilistic(monkeypatch, tmp_path):
    """Обратная сторона F-12: интервал целиком внутри сетки — вероятностный,
    без оговорки об упоре (признак усечения обязан РАЗЛИЧАТЬ случаи)."""
    project = _prep_model(tmp_path)
    margin = 0.3
    k_point = _k_for_optimum(1.4e6, margin)
    rng = np.random.default_rng(5)
    _install_forward(monkeypatch, k_point,
                     sampler=_sampler_factory(k_point * (1.0 + 0.04 * rng.standard_normal(200))))

    interval = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': margin})['posterior_interval']

    assert interval['available'] is True
    assert interval['truncated_by_grid'] is False
    assert interval['is_probabilistic'] is True
    assert interval['truncated_side'] is None


# ─── край данных против края сетки (аудит F-09) ─────────────────────────────

def test_grid_ceiling_outcome_is_separate_from_beyond_observed(monkeypatch, tmp_path):
    """F-09: «кончились данные» и «кончилась наша сетка» — разные утверждения.

    Когда severity 0 во всех точках, `observed_frontier` по построению равен
    последней точке сетки (3× текущего бюджета). Называть это «границей
    наблюдавшихся трат» нельзя: у канала с закупкой волнами траты в данных
    могли быть и выше.
    """
    project = _prep_model(tmp_path)
    # Границы наблюдений уводим за край сетки: данные покрывают весь расчёт.
    _install_forward(monkeypatch, _k_for_optimum(9.0e6, 0.3),
                     sev_1=1.0e12, sev_2=2.0e12)

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})
    maximum = result['maximum']

    assert maximum['outcome'] == 'at_grid_ceiling'
    assert maximum['reportable'] is False
    assert maximum['limited_by'] == 'grid'
    assert maximum['grid_ceiling_multiplier'] == 3.0
    assert maximum['grid_ceiling_budget'] == pytest.approx(3.0 * CURRENT)
    assert 'budget' not in maximum
    assert 'границ' not in maximum['message'] or 'наблюдавшихся трат' not in maximum['message'], (
        'потолок расчёта не называем границей наблюдавшихся трат')
    assert 'верхней границы расчёта' in maximum['message']
    # Сама «граница наблюдений» тоже честно помечена как упор в расчёт.
    assert result['observed_frontier']['limited_by'] == 'grid'
    assert result['observed_frontier']['at_grid_ceiling'] is True
    assert 'верхняя точка расчёта' in result['observed_frontier']['note']


def test_beyond_observed_stays_beyond_observed(monkeypatch, tmp_path):
    """Обратная сторона F-09: когда данные ДЕЙСТВИТЕЛЬНО кончились раньше сетки,
    исход остаётся «за границей наблюдений»."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(2.8e6, 0.5))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.5})

    assert result['maximum']['outcome'] == 'beyond_observed'
    assert result['maximum']['limited_by'] == 'data'
    assert result['observed_frontier']['limited_by'] == 'data'
    assert result['observed_frontier']['at_grid_ceiling'] is False


# ─── ограничение метода границы наблюдений (аудит F-15) ─────────────────────

def test_observed_frontier_states_its_method_limitation(monkeypatch, tmp_path):
    """F-15: признак экстраполяции сравнивает СРЕДНЮЮ трату за период с историей
    по АКТИВНЫМ периодам — для каналов с закупкой волнами он занижен. Клиентское
    утверждение «за этой границей данных нет» не должно быть сильнее метода."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(2.8e6, 0.5))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.5})
    frontier = result['observed_frontier']

    assert frontier['available'] is True
    assert frontier['method_limitation'] == 'per_period_average_vs_active_period_history'
    assert 'волнами' in frontier['method_note']
    assert 'средней траты за период' in frontier['method_note']
    # Оговорка доезжает и до текста, где границу объявляют числом.
    assert 'волнами' in result['maximum']['message']


# ─── признак основания у базового уровня (аудит F-16) ───────────────────────

def test_baseline_sales_carries_basis(monkeypatch, tmp_path):
    """F-16: базовый уровень — блок с признаком периода, как все числа фронтира,
    а не голое число (иначе сумма за 31 период читается как за один)."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['baseline_sales']['total'] == pytest.approx(BASELINE)
    assert result['baseline_sales']['basis'] == 'total_over_training_period'
    assert 'не за один период' in result['baseline_sales']['note']
    assert 'baseline_sales_total' not in result, 'голого числа без признака не остаётся'


# ─── псевдоточность в клиентском тексте (аудит F-17) ────────────────────────

def test_client_text_is_rounded_to_grid_resolution(monkeypatch, tmp_path):
    """F-17: положение максимума — координата УЗЛА сетки, точность равна её шагу.

    «Около 355 584 340 ₽ (шаг сетки 30 354 761 ₽)» — девять значащих цифр там,
    где точность 30 млн: клиент ставит число в медиаплан и обсуждает разницу
    в миллионы, которой в расчёте нет.
    """
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})
    maximum, step = result['maximum'], result['grid']['step']

    exact_text = f'{maximum["budget"]:,.0f}'.replace(',', ' ')
    display_text = f'{maximum["budget_display"]:,.0f}'.replace(',', ' ')
    assert exact_text != display_text, 'фикстура обязана давать неокруглённое число'
    assert display_text in maximum['message']
    assert exact_text not in maximum['message'], 'до рубля клиенту не печатаем'
    # Разряд округления соотнесён с шагом сетки и не грубее самого шага.
    assert abs(maximum['budget_display'] - maximum['budget']) <= step
    assert maximum['display_resolution'] == pytest.approx(
        float(f'{step:.1e}')), 'шаг сетки в тексте — тоже без псевдоточности'
    # Техническое поле остаётся точным.
    assert maximum['budget'] == pytest.approx(result['curve'][maximum['index']]['budget'])


def test_lost_profit_text_is_rounded(monkeypatch, tmp_path):
    """Тот же класс в исходе «вы уже за точкой максимума»: «теряется около X ₽»
    печаталось до рубля."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(0.6e6, 0.3))

    maximum = compute_profit_frontier(
        project, {'kpi_type': 'sales', 'gross_margin': 0.3})['maximum']

    exact_lost = f'{maximum["profit_lost_at_current"]:,.0f}'.replace(',', ' ')
    assert exact_lost not in maximum['message']
    assert 'Числа округлены' in maximum['message']


# ─── настоящий контракт прямого прохода (аудит F-10) ────────────────────────

def test_missing_baseline_total_is_refused_not_silently_zeroed(monkeypatch, tmp_path):
    """F-10: исчезновение `baseline_total` подставляло ноль, и базовые продажи
    попадали в «прибыль от медиа» — завышение в шесть раз на живой модели,
    при зелёных тестах. Числа, которого нет, не выдумываем: отказ."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3),
                     drop_meta_keys=('baseline_total',))

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['status'] == 'error'
    assert result['error_code'] == 'FORWARD_META_INCOMPLETE'
    assert result['missing_meta_keys'] == ['baseline_total']
    assert 'базового уровня продаж' in result['message']
    assert 'curve' not in result and 'maximum' not in result


def test_real_forward_meta_contract_is_honoured(tmp_path):
    """F-10: все остальные тесты подменяют `build_proportional_forward` своим
    словарём, поэтому НАСТОЯЩИЙ контракт `meta` не проверял никто. Здесь модель
    обучается по-настоящему (МНК, ~2 с), и фронтир идёт по живому контракту.

    Заодно это единственная живая проверка ветки F-02 «выборок нет по природе
    модели»: у МНК-модели апостериорных выборок действительно нет, и только
    здесь продукт вправе говорить о методе обучения.
    """
    import pandas as pd
    from engines.ols_modeler import train_ols
    from optimize.inverse import build_proportional_forward

    rng = np.random.RandomState(42)
    n = 36
    dates = pd.date_range('2022-01-01', periods=n, freq='MS')
    tv = rng.uniform(1e6, 3e6, n)
    digital = rng.uniform(5e5, 2e6, n)
    sales = 5_000_000 + 0.3 * tv + 0.2 * digital + rng.normal(0, 2e5, n)
    data_file = tmp_path / 'data.xlsx'
    pd.DataFrame({'date': dates, 'tv': tv, 'digital': digital,
                  'sales': sales}).to_excel(data_file, index=False)

    trained = train_ols({
        'data_file': str(data_file), 'kpi_column': 'sales',
        'media_columns': ['tv', 'digital'], 'control_columns': [],
        'date_column': 'date',
        'adstock_config': {'tv': 'geometric', 'digital': 'geometric'},
        'unit_costs': {}, 'kpi_type': 'sales', 'kpi_unit_cost': None,
        'merge_rules': {}, 'channel_categories': {},
    }, str(tmp_path))
    assert trained['status'] == 'ok', trained

    # 1. Ключи, на которые опирается фронтир, в настоящем `meta` есть.
    _, meta = build_proportional_forward(str(tmp_path))
    for key in ('current_total_money', 'baseline_total', 'n_periods',
                'extrapolation_reporter', 'posterior_sampler'):
        assert key in meta, f'контракт прямого прохода потерял ключ {key}'
    assert isinstance(meta['baseline_total'], float)
    assert meta['n_periods'] == n

    # 2. Расчёт по живому контракту доходит до конца.
    result = compute_profit_frontier(str(tmp_path), {'kpi_type': 'sales',
                                                     'gross_margin': 0.3})
    assert result['status'] == 'ok', result
    assert result['baseline_sales']['total'] == pytest.approx(meta['baseline_total'])
    assert len(result['curve']) == 25
    assert result['current']['budget'] == pytest.approx(meta['current_total_money'])

    # 3. Прибыль считается ОТ МЕДИА: базовый уровень в неё не входит.
    for point in result['curve']:
        assert point['sales_from_media'] == pytest.approx(
            point['sales_total'] - meta['baseline_total'])

    # 4. У МНК-модели апостериорных выборок нет по природе модели — и только
    #    здесь мы вправе назвать метод обучения (F-02).
    interval = result['posterior_interval']
    assert interval['available'] is False
    assert interval['reason'] == 'no_posterior_samples'
    assert 'наименьших квадратов' in interval['message']
