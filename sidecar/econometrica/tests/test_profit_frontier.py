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


def _install_forward(monkeypatch, k: float, sampler=None, n_periods: int = 31):
    """Подменяет прямой проход синтетикой S(B) = BASELINE + K·√B."""

    def forward(budget: float):
        b = max(float(budget), 0.0)
        return {
            'expected_sales': BASELINE + k * math.sqrt(b),
            'distribution': {'TV': 0.6 * b, 'Digital': 0.4 * b},
            'status': 'ok',
        }

    def reporter(distribution):
        total = sum(float(v) for v in (distribution or {}).values())
        severity = 0 if total <= SEV_1 else (1 if total <= SEV_2 else 2)
        return {'severity': severity, 'channels': []}

    meta = {
        'current_total_money': CURRENT,
        'baseline_total': BASELINE,
        'extrapolation_reporter': reporter,
        'posterior_sampler': sampler,
        'n_periods': n_periods,
        'period_granularity': {'granularity': 'M', 'confidence': 0.97},
    }
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
    expected_number = f'{result["observed_frontier"]["budget"]:,.0f}'.replace(',', ' ')
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
    """Модель малых данных: сэмплер вернул None — кривая и максимум есть,
    интервала нет, и об этом сказано полем, а не нулём."""
    project = _prep_model(tmp_path)
    _install_forward(monkeypatch, _k_for_optimum(1.4e6, 0.3),
                     sampler=lambda budget, max_samples=200: None)

    result = compute_profit_frontier(project, {'kpi_type': 'sales', 'gross_margin': 0.3})

    assert result['status'] == 'ok'
    assert len(result['curve']) == 25
    assert result['maximum']['reportable'] is True
    interval = result['posterior_interval']
    assert interval['available'] is False
    assert interval['reason'] == 'no_posterior_samples'
    assert 'low' not in interval and 'high' not in interval
    assert 'наименьших квадратов' in interval['message']


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
