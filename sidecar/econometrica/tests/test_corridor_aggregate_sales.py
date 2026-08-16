"""Долг коридора закрыт (2026-08-16): `aggregate_sales` считается прямым проходом.

До этого поле было объявлено в докстринге `compute_safe_corridor` как заглушка
«требует forward pass», а в возвращаемом словаре его не было вовсе — интерфейс
из-за этого говорил клиенту, что диапазон продаж модель не рассчитывает. Проход
появился (профит-фронтир), и границы коридора теперь переводятся в продажи двумя
вызовами `forward`.

🔴 Единицы: коридор суммирует НАТИВНЫЕ траты, проход ждёт ДЕНЬГИ. При заданной
стоимости единицы чисел не даём — статус `unit_mismatch` (не переводим молча).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize.bounds import compute_safe_corridor  # noqa: E402

BASELINE = 5.0e6
K = 3000.0


def _model_with_data(tmp_path: Path) -> dict:
    """Модель с двумя каналами и файлом обучающих данных (csv рядом)."""
    data_file = tmp_path / 'data.csv'
    data_file.write_text(
        'TV,Digital\n'
        '100,50\n120,60\n90,40\n110,55\n130,65\n95,45\n105,52\n115,58\n',
        encoding='utf-8',
    )
    return {'config': {'media_columns': ['TV', 'Digital'],
                       'data_file': str(data_file)}}


def _install_forward(monkeypatch, unit_costs=None):
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
                      'n_periods': 31}),
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


def test_aggregate_sales_computed_at_corridor_bounds(monkeypatch, tmp_path):
    """Продажи на границах = прямой проход в тех же точках, с признаком периода.

    🔴 Основания разные: `lo`/`hi` коридора — траты за ОДИН период, `current` —
    сумма за весь период обучения. Продажи считаются от суммарных бюджетов,
    и бюджеты, по которым считали, отдаются явно.
    """
    forward = _install_forward(monkeypatch)
    model_data = _model_with_data(tmp_path)

    corridor = compute_safe_corridor(model_data, project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    budget = corridor['aggregate_budget']
    assert sales['status'] == 'ok'
    assert sales['basis'] == 'total_over_training_period'
    assert sales['n_periods'] == 31
    assert sales['corridor_basis_mismatch'] is True
    # Границы приведены к суммарному бюджету, текущий уже суммарный.
    assert sales['budget_used']['lo'] == pytest.approx(budget['lo'] * 31)
    assert sales['budget_used']['hi'] == pytest.approx(budget['hi'] * 31)
    assert sales['budget_used']['current'] == pytest.approx(budget['current'])
    for key in ('lo', 'hi', 'current'):
        assert sales[key] == pytest.approx(
            forward(sales['budget_used'][key])['expected_sales'])
    assert sales['lo'] < sales['hi']


def test_aggregate_sales_refuses_on_unit_mismatch(monkeypatch, tmp_path):
    """Стоимость единицы задана → коридор в натуральных единицах, продажи от денег:
    числа не показываем, отдаём причину."""
    _install_forward(monkeypatch, unit_costs={'TV': 1500.0, 'Digital': 1.0})

    corridor = compute_safe_corridor(_model_with_data(tmp_path),
                                     project_dir=str(tmp_path))

    sales = corridor['aggregate_sales']
    assert sales['status'] == 'unit_mismatch'
    assert sales['channels'] == ['TV']
    assert not {'lo', 'hi', 'current'} & set(sales)


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
    assert 'lo' not in corridor['aggregate_sales']
