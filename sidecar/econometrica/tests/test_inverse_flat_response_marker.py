"""Tests для #59 flat-response Goal-Seek marker (2026-06-02).

optimize_inverse должен пробрасывать явный булев `flat_response_fallback`
в результат, когда estimate_budget_ci детектирует плоскую (saturated) кривую
(method='flat_response_fallback'). Без этого UI видит насыщение только как
сырой жаргон «Метод: flat_response_fallback» в футере и не может показать
понятный баннер.

Также non-achievable case должен пробрасывать `error` code
(напр. non_monotonic_forward) для UI-диагностики — раньше терялся.

Mock-стратегия: optimize_inverse читает pickle + forward optimize (тяжело),
поэтому подменяем pipeline-функции, изолируя именно логику проброса маркеров.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize import inverse  # noqa: E402


def _prep_model(tmp_path: Path) -> str:
    """Dummy project dir с models/latest.pkl (optimize_inverse проверяет existence)."""
    models_dir = tmp_path / 'models'
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / 'latest.pkl').write_bytes(b'dummy')
    return str(tmp_path)


def _patch_achievable(monkeypatch, ci_method: str) -> None:
    monkeypatch.setattr(
        'engines.persistence.load_model_with_compat', lambda p: {'dummy': True}
    )
    monkeypatch.setattr(
        'optimize.bounds.compute_safe_corridor',
        lambda md: {'aggregate_budget': {'hi': 1.0e8, 'current': 5.0e7}},
    )
    # GS-1 (2026-06-02): optimize_inverse строит proportional forward до bisection.
    # Изолируем логику маркеров - мокаем forward (bisect_for_target всё равно мокнут).
    monkeypatch.setattr(
        'optimize.inverse.build_proportional_forward',
        lambda pd, unit_costs_override=None: (
            lambda B: {'expected_sales': 0.0, 'distribution': {}, 'status': 'ok'},
            {'current_total_money': 5.0e7, 'baseline_total': 0.0},
        ),
    )
    monkeypatch.setattr(
        'optimize.inverse.bisect_for_target',
        lambda **kw: {
            'achievable': True,
            'budget': 5.0e7,
            'expected_sales': 1.05e8,
            'distribution': {'TV': 3.0e7, 'Digital': 2.0e7},
            'iterations': 7,
        },
    )
    monkeypatch.setattr(
        'optimize.inverse.estimate_budget_ci',
        lambda *a, **k: {'p10': 4.5e7, 'p50': 5.0e7, 'p90': 5.5e7, 'method': ci_method},
    )


def test_flat_response_marker_true_when_saturated(tmp_path, monkeypatch):
    project_dir = _prep_model(tmp_path)
    _patch_achievable(monkeypatch, ci_method='flat_response_fallback')
    result = inverse.optimize_inverse(project_dir, target_sales=1.05e8)
    assert result['achievable'] is True
    assert result['flat_response_fallback'] is True


def test_flat_response_marker_false_for_normal_curve(tmp_path, monkeypatch):
    project_dir = _prep_model(tmp_path)
    _patch_achievable(monkeypatch, ci_method='delta')
    result = inverse.optimize_inverse(project_dir, target_sales=1.05e8)
    assert result['achievable'] is True
    assert result['flat_response_fallback'] is False


def test_non_monotonic_error_propagated(tmp_path, monkeypatch):
    project_dir = _prep_model(tmp_path)
    monkeypatch.setattr(
        'engines.persistence.load_model_with_compat', lambda p: {'dummy': True}
    )
    monkeypatch.setattr(
        'optimize.bounds.compute_safe_corridor',
        lambda md: {'aggregate_budget': {'hi': 1.0e8, 'current': 5.0e7}},
    )
    monkeypatch.setattr(
        'optimize.inverse.build_proportional_forward',
        lambda pd, unit_costs_override=None: (
            lambda B: {'expected_sales': 0.0, 'distribution': {}, 'status': 'ok'},
            {'current_total_money': 5.0e7, 'baseline_total': 0.0},
        ),
    )
    monkeypatch.setattr(
        'optimize.inverse.bisect_for_target',
        lambda **kw: {
            'achievable': False,
            'error': 'non_monotonic_forward',
            'message': 'Forward функция не монотонна.',
            'iterations': 2,
        },
    )
    result = inverse.optimize_inverse(project_dir, target_sales=1.05e8)
    assert result['achievable'] is False
    assert result['error'] == 'non_monotonic_forward'
