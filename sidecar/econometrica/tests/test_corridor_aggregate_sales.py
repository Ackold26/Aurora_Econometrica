"""Долг коридора закрыт (2026-08-16): `aggregate_sales` считается прямым проходом.

До этого поле было объявлено в докстринге `compute_safe_corridor` как заглушка
«требует forward pass», а в возвращаемом словаре его не было вовсе — интерфейс
из-за этого говорил клиенту, что диапазон продаж модель не рассчитывает. Проход
появился (профит-фронтир), и границы коридора теперь переводятся в продажи тремя
вызовами `forward`.

Правки по внешнему аудиту 2026-08-16:
🔴 F-13 · Единицы: коридор суммирует НАТИВНЫЕ траты, проход ждёт ДЕНЬГИ. Отказ
   не только когда стоимость единицы ЗАДАНА и не равна рублю, но и когда она
   НЕ ЗАДАНА, а признак натуральных единиц есть (имя канала, снимок обучения) —
   именно этот случай раньше проходил молча и складывал пункты рейтинга с рублями.
🔴 F-07 · Приведение к сумме за период — ПОКАНАЛЬНО, по числу АКТИВНЫХ периодов
   канала (границы считаются по `spend[spend > 0]`). Плюс дешёвая проверка
   разумности: коридор обязан накрывать текущую трату, иначе чисел не даём.
🔴 F-14 · У каждой группы чисел свой признак основания; общих признаков рядом
   с несколькими группами нет.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize.bounds import (  # noqa: E402
    BUDGET_PER_ACTIVE_PERIOD,
    BUDGET_TOTAL_OVER_TRAINING,
    SALES_TOTAL_OVER_TRAINING,
    _aggregate_sales_at_bounds,
    compute_safe_corridor,
)

BASELINE = 5.0e6
K = 3000.0
N_PERIODS = 8


def _model_with_data(tmp_path: Path, extra_column: str | None = None) -> dict:
    """Модель с файлом обучающих данных (csv рядом), 8 периодов.

    `TV` и `Digital` работают каждый период. `extra_column` — канал, который
    закупался ФЛАЙТОМ: три активных периода из восьми.
    """
    data_file = tmp_path / 'data.csv'
    rows = [(100, 50), (120, 60), (90, 40), (110, 55),
            (130, 65), (95, 45), (105, 52), (115, 58)]
    flight = [0, 0, 300, 0, 320, 0, 280, 0]
    header = 'TV,Digital'
    if extra_column:
        header += f',{extra_column}'
    lines = [header]
    for i, (tv, dg) in enumerate(rows):
        line = f'{tv},{dg}'
        if extra_column:
            line += f',{flight[i]}'
        lines.append(line)
    data_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    media = ['TV', 'Digital'] + ([extra_column] if extra_column else [])
    return {'config': {'media_columns': media, 'data_file': str(data_file)}}


def _install_forward(monkeypatch, unit_costs=None, n_periods=N_PERIODS):
    import math

    def forward(budget: float):
        b = max(float(budget), 0.0)
        return {'expected_sales': BASELINE + K * math.sqrt(b),
                'distribution': {'TV': 0.6 * b, 'Digital': 0.4 * b},
                'status': 'ok'}

    monkeypatch.setattr(
        'optimize.inverse.build_proportional_forward',
        lambda project_dir, unit_costs_override=None: (
            forward, {'current_total_money': 1.0e6, 'baseline_total': BASELINE,
                      'n_periods': n_periods}),
    )
    monkeypatch.setattr(
        'optimize.inverse._resolve_current_unit_costs',
        lambda project_dir, cfg, override=None: dict(unit_costs or {}),
    )
    return forward


def test_aggregate_sales_absent_without_project_dir(tmp_path):
    """Обратная совместимость: без project_dir поля нет (а не ноль)."""
    corridor = compute_safe_corridor(_model_with_data(tmp_path))
    assert 'aggregate_sales' not in corridor
    assert corridor['aggregate_budget']['current'] > 0


def test_aggregate_budget_numbers_carry_basis_each(tmp_path):
    """F-14: у каждого числа агрегатного бюджета — свой признак основания."""
    corridor = compute_safe_corridor(_model_with_data(tmp_path))
    basis = corridor['aggregate_budget_basis']
    assert basis['lo'] == BUDGET_PER_ACTIVE_PERIOD
    assert basis['hi'] == BUDGET_PER_ACTIVE_PERIOD
    assert basis['current'] == BUDGET_TOTAL_OVER_TRAINING


def test_per_channel_reports_active_periods(tmp_path):
    """Число активных периодов канала отдаётся — без него приведение невозможно."""
    corridor = compute_safe_corridor(_model_with_data(tmp_path, extra_column='Radio'))
    assert corridor['per_channel']['TV']['n_active_periods'] == 8
    assert corridor['per_channel']['Radio']['n_active_periods'] == 3


def test_aggregate_sales_computed_at_corridor_bounds(monkeypatch, tmp_path):
    """Продажи на границах = прямой проход в тех же точках, каждая группа чисел —
    со своим признаком основания (F-14).

    🔴 Основания разные: границы коридора — трата за один АКТИВНЫЙ период канала,
    текущий бюджет — сумма за весь период обучения. Продажи считаются от суммарных
    бюджетов, и бюджеты, по которым считали, отдаются явно.
    """
    forward = _install_forward(monkeypatch)
    corridor = compute_safe_corridor(_model_with_data(tmp_path),
                                     project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    budget = corridor['aggregate_budget']
    assert sales['status'] == 'ok'
    assert sales['n_periods'] == N_PERIODS

    # Каждая группа чисел подписана своим основанием.
    assert sales['corridor_budget']['basis'] == BUDGET_PER_ACTIVE_PERIOD
    assert sales['budget_used']['basis'] == BUDGET_TOTAL_OVER_TRAINING
    assert sales['sales']['basis'] == SALES_TOTAL_OVER_TRAINING

    # Неоднозначных признаков, описывающих «что-то из соседнего блока», нет.
    assert 'basis' not in sales
    assert 'corridor_budget_basis' not in sales
    assert 'corridor_basis_mismatch' not in sales
    # И голых чисел без группы на верхнем уровне тоже нет.
    assert not {'lo', 'hi', 'current'} & set(sales)

    assert sales['corridor_budget']['lo'] == pytest.approx(budget['lo'])
    assert sales['corridor_budget']['hi'] == pytest.approx(budget['hi'])
    # Оба канала активны все 8 периодов → приведение = граница × 8.
    assert sales['budget_used']['lo'] == pytest.approx(budget['lo'] * N_PERIODS)
    assert sales['budget_used']['hi'] == pytest.approx(budget['hi'] * N_PERIODS)
    assert sales['budget_used']['current'] == pytest.approx(budget['current'])
    for key in ('lo', 'hi', 'current'):
        assert sales['sales'][key] == pytest.approx(
            forward(sales['budget_used'][key])['expected_sales'])
    assert sales['sales']['lo'] < sales['sales']['hi']


def test_flight_channel_scaled_by_its_own_active_periods(monkeypatch, tmp_path):
    """F-07: флайтовый канал приводится по СВОИМ активным периодам, не по всем.

    Границы канала — среднее и перцентили по периодам с ненулевой тратой. Умножение
    на число ВСЕХ периодов завышало суммарную трату в `n_периодов / n_активных` раз
    (для канала, работавшего 3 периода из 8, — в 2,7 раза).
    """
    _install_forward(monkeypatch)
    corridor = compute_safe_corridor(_model_with_data(tmp_path, extra_column='Radio'),
                                     project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    per_channel = corridor['per_channel']
    assert sales['status'] == 'ok'
    assert sales['active_periods_per_channel'] == {'TV': 8, 'Digital': 8, 'Radio': 3}

    expected_lo = sum(per_channel[c]['lo'] * n
                      for c, n in sales['active_periods_per_channel'].items())
    assert sales['budget_used']['lo'] == pytest.approx(expected_lo)

    naive_lo = corridor['aggregate_budget']['lo'] * N_PERIODS
    assert sales['budget_used']['lo'] < naive_lo, (
        'приведение по всем периодам завышало бы трату флайтового канала')
    # Коридор накрывает текущую трату — иначе числа не выдаются (см. тест ниже).
    assert (sales['budget_used']['lo'] <= sales['budget_used']['current']
            <= sales['budget_used']['hi'])


def test_bounds_not_bracketing_current_are_refused(monkeypatch, tmp_path):
    """F-07: коридор, не накрывающий текущую трату, — признак кривого приведения.

    Раньше такой результат отдавался со статусом `ok`: `budget_used.lo` мог быть
    больше `budget_used.current`, и потребитель получал «зелёную зону» от бюджета,
    которого у клиента никогда не было.
    """
    _install_forward(monkeypatch)
    per_channel = {'TV': {'lo': 500.0, 'hi': 900.0, 'current': 100.0,
                          'n_active_periods': 8}}

    out = _aggregate_sales_at_bounds(str(tmp_path), {'media_columns': ['TV']},
                                     per_channel, None)

    assert out['status'] == 'implausible_bounds'
    assert out['reason'] == 'corridor_does_not_bracket_current'
    assert 'sales' not in out


def test_active_periods_missing_refuses(monkeypatch, tmp_path):
    """Неизвестно число активных периодов → приведения нет, чисел тоже (INV-50)."""
    _install_forward(monkeypatch)
    per_channel = {'TV': {'lo': 10.0, 'hi': 20.0, 'current': 120.0}}

    out = _aggregate_sales_at_bounds(str(tmp_path), {'media_columns': ['TV']},
                                     per_channel, None)

    assert out['status'] == 'unavailable'
    assert out['reason'] == 'active_periods_unknown'
    assert 'sales' not in out


def test_aggregate_sales_refuses_on_priced_unit(monkeypatch, tmp_path):
    """Стоимость единицы задана → коридор в натуральных единицах, продажи от денег:
    числа не показываем, отдаём причину."""
    _install_forward(monkeypatch, unit_costs={'TV': 1500.0, 'Digital': 1.0})

    corridor = compute_safe_corridor(_model_with_data(tmp_path),
                                     project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'unit_mismatch'
    assert sales['reason'] == 'non_money_channels'
    assert sales['channels'] == ['TV']
    assert 'sales' not in sales


def test_aggregate_sales_refuses_when_unit_is_unknown(monkeypatch, tmp_path):
    """🔴 F-13: стоимость единицы НЕ задана, а канал явно в натуральных единицах.

    Опасный случай, который прежний сторож пропускал: словарь стоимостей пуст,
    поэтому канала нет в списке несовпадений, а прямой проход подставит 1,0 и
    посчитает пункты рейтинга рублями. Живой пример — эталонный проект: unit_costs
    пуст, среди каналов «TRPs бренд (W 25-54)», статус был `ok`.
    """
    _install_forward(monkeypatch, unit_costs={})

    corridor = compute_safe_corridor(
        _model_with_data(tmp_path, extra_column='TRPs бренд (W 25-54)'),
        project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'unit_mismatch'
    assert sales['reason'] == 'unknown_unit_channels'
    assert sales['unknown_unit_channels'] == ['TRPs бренд (W 25-54)']
    assert 'sales' not in sales
    assert 'budget_used' not in sales


def test_unknown_unit_detected_by_training_snapshot(monkeypatch, tmp_path):
    """F-13: имя канала нейтрально, но при обучении у него была стоимость единицы.

    Значит данные натуральные, а текущего перевода в деньги нет — считать нельзя.
    """
    _install_forward(monkeypatch, unit_costs={})
    model_data = _model_with_data(tmp_path, extra_column='Radio')
    model_data['unit_costs_applied_at_training'] = True
    model_data['unit_costs_snapshot'] = {'Radio': 1200.0}

    corridor = compute_safe_corridor(model_data, project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'unit_mismatch'
    assert sales['reason'] == 'unknown_unit_channels'
    assert sales['unknown_unit_channels'] == ['Radio']


def test_mixed_units_report_both_groups(monkeypatch, tmp_path):
    """F-13: заданная не-рублёвая стоимость и неизвестная единица — обе названы."""
    _install_forward(monkeypatch, unit_costs={'Digital': 1500.0})

    corridor = compute_safe_corridor(
        _model_with_data(tmp_path, extra_column='Клики сайта'),
        project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'unit_mismatch'
    assert sales['reason'] == 'mixed_units'
    assert sales['priced_channels'] == ['Digital']
    assert sales['unknown_unit_channels'] == ['Клики сайта']


def test_money_channels_without_unit_costs_are_computed_with_assumption(
        monkeypatch, tmp_path):
    """Штатный случай: стоимостей нет, признаков натуральных единиц тоже нет.

    Траты принимаются за рубли — как и во всём движке, — но допущение названо
    явно, а не молчит.
    """
    _install_forward(monkeypatch, unit_costs={})

    corridor = compute_safe_corridor(_model_with_data(tmp_path),
                                     project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'ok'
    assert sales['unit_assumption']['channels'] == ['TV', 'Digital']


def test_aggregate_sales_survives_forward_failure(monkeypatch, tmp_path):
    """Сбой прохода не роняет коридор (он на критическом пути) и не даёт нулей."""
    monkeypatch.setattr(
        'optimize.inverse.build_proportional_forward',
        lambda project_dir, unit_costs_override=None: (_ for _ in ()).throw(
            RuntimeError('модель битая')),
    )

    corridor = compute_safe_corridor(_model_with_data(tmp_path),
                                     project_dir=str(tmp_path))

    assert corridor['aggregate_budget']['current'] > 0
    assert corridor['aggregate_sales']['status'] == 'unavailable'
    assert 'sales' not in corridor['aggregate_sales']
