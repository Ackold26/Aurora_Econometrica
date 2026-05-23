"""Tests для B3-E1 (Pilot R3 2026-05-17): compare_scenarios money primary.

Когда ВСЕ saved scenarios имеют non-null totals.predicted_kpi_money
(count KPI + kpi_unit_cost, ADR-021 R2-1), comparison.rows[0] должен
показывать money primary, не native count.

Fallback к native count - когда хотя бы один scenario без money equivalent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.scenario import compare_scenarios  # noqa: E402


def _write_scenario(scenarios_dir: Path, name: str, totals: dict) -> None:
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'status': 'ok',
        'scenario_name': name,
        'totals': totals,
        'media_plan': {},
    }
    (scenarios_dir / f'{name}.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8'
    )


def _base_totals(**overrides) -> dict:
    base = {
        'predicted_kpi': 12000,
        'baseline_kpi': 10000,
        'incremental_kpi': 2000,
        'lift_pct': 20.0,
        'total_spend': 500.0,
        'total_spend_money': 500_000.0,
        'roas': 24.0,
        'roas_money': 0.024,
        'roas_total': 24.0,
        'units_fully_covered': True,
        'roas_method': 'incremental',
    }
    base.update(overrides)
    return base


def test_compare_money_primary_when_all_scenarios_have_money(tmp_path: Path) -> None:
    """Все scenarios имеют predicted_kpi_money → comparison routes через money."""
    scen_dir = tmp_path / 'results' / 'scenarios'
    _write_scenario(scen_dir, 's1', _base_totals(
        predicted_kpi=10_000,
        predicted_kpi_money=6_000_000,
        incremental_kpi_money=1_000_000,
        baseline_kpi_money=5_000_000,
        kpi_unit_cost=600.0,
    ))
    _write_scenario(scen_dir, 's2', _base_totals(
        predicted_kpi=15_000,
        predicted_kpi_money=9_000_000,
        incremental_kpi_money=4_000_000,
        baseline_kpi_money=5_000_000,
        kpi_unit_cost=600.0,
    ))

    result = compare_scenarios(str(tmp_path))

    assert result['status'] == 'ok'
    comp = result['comparison']
    assert comp['kpi_money_mode'] is True
    # row_units exposes per-row formatter hints для frontend.
    assert comp['row_units'][0] == '₽'
    # KPI row primary - money values, не native count.
    kpi_row = comp['rows'][0]
    assert 'Прогноз KPI (₽)' in kpi_row[0]
    assert kpi_row[1] == 6_000_000
    assert kpi_row[2] == 9_000_000
    # Native count values из scenarios НЕ должны попасть в primary row.
    assert 10_000 not in kpi_row
    assert 15_000 not in kpi_row


def test_compare_falls_back_to_native_when_one_scenario_missing_money(
    tmp_path: Path,
) -> None:
    """Mixed scenarios (один без predicted_kpi_money) → fallback к native count."""
    scen_dir = tmp_path / 'results' / 'scenarios'
    # s1: новый формат с money
    _write_scenario(scen_dir, 's1', _base_totals(
        predicted_kpi=10_000,
        predicted_kpi_money=6_000_000,
        incremental_kpi_money=1_000_000,
        baseline_kpi_money=5_000_000,
        kpi_unit_cost=600.0,
    ))
    # s2: legacy без money - симулирует сохранение до ADR-021 R2-1
    _write_scenario(scen_dir, 's2', _base_totals(
        predicted_kpi=15_000,
        predicted_kpi_money=None,
        incremental_kpi_money=None,
        baseline_kpi_money=None,
    ))

    result = compare_scenarios(str(tmp_path))

    comp = result['comparison']
    assert comp['kpi_money_mode'] is False
    assert comp['row_units'][0] == 'count'
    kpi_row = comp['rows'][0]
    assert kpi_row[0] == 'Прогноз KPI'
    # Native count values.
    assert kpi_row[1] == 10_000
    assert kpi_row[2] == 15_000


def test_compare_row_units_shape(tmp_path: Path) -> None:
    """row_units всегда 4 элемента в порядке rows: kpi/budget/roas/pct."""
    scen_dir = tmp_path / 'results' / 'scenarios'
    _write_scenario(scen_dir, 's1', _base_totals(
        predicted_kpi_money=6_000_000,
        incremental_kpi_money=1_000_000,
        baseline_kpi_money=5_000_000,
        kpi_unit_cost=600.0,
    ))

    result = compare_scenarios(str(tmp_path))
    comp = result['comparison']
    assert len(comp['row_units']) == len(comp['rows']) == 4
    # pct row всегда unitless ratio.
    assert comp['row_units'][3] == 'pct'
    # budget unit consistent с money_mode.
    assert comp['row_units'][1] in {'money', 'native'}
    # roas всегда 'roas' (multiplier).
    assert comp['row_units'][2] == 'roas'
