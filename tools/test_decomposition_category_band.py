"""Фаза Б (2026-07-04): доказательство breakout-полосы «Категория» в декомпозиции.

Продажи категории/рынка (kind 'category') — экзогенный контроль спроса — должны
выноситься ОТДЕЛЬНОЙ полосой «Категория» в верхнюю группу ВНЕШНИЕ ФАКТОРЫ (не
растворяться в базовой линии, как positive_control). Проверяем это на SSOT-функции
build_decomposition_series (её зовёт и программа ChannelTimeline, и все отчёты —
HTML/PPTX/XLSX), которую до сих пор ни один тест не дёргал напрямую.

Покрывает три требования хвоста Фазы Б (B3):
  1. с category_sales → полоса «Категория» появляется, top_group = ВНЕШНИЕ ФАКТОРЫ;
  2. без category → полосы нет (не выдумываем фактор на пустом месте);
  3. тождество INV-50 держится (baseline_reduced + Σфакторы + Σмедиа == исходный total).

Контраст category (→ВНЕШНИЕ) vs competitor (→КОНКУРЕНТЫ) фиксирует, что категория
попадает именно во внешние факторы, а не сваливается в общую кучу.
"""
import sys
from pathlib import Path

import pytest

_SIDECAR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from engines.decomposer import build_decomposition_series  # noqa: E402

_DATES = [f'2022-{m:02d}-01' for m in range(1, 7)]        # 6 периодов
_BASELINE = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0]  # уже включает контроли
_MEDIA = {'tv': [100.0, 120.0, 90.0, 110.0, 130.0, 95.0]}
# per_period эффекта категории — положительный (бренд «плывёт» на волне рынка).
_CATEGORY_PP = [50.0, 40.0, 60.0, 45.0, 55.0, 48.0]


def _series_by_name(result, name):
    return next((s for s in result['series'] if s['name'] == name), None)


def _factor(type_, per_period):
    return {'value': round(sum(per_period), 1), 'type': type_, 'per_period': list(per_period)}


def test_category_becomes_external_band():
    """category_sales → полоса «Категория», top_group = ВНЕШНИЕ ФАКТОРЫ."""
    sfc = {'category_sales': _factor('category', _CATEGORY_PP)}
    res = build_decomposition_series(_DATES, _BASELINE, _MEDIA, sfc)
    band = _series_by_name(res, 'category_sales')
    assert band is not None, 'полоса «Категория» не построена — category не вынесена'
    assert band['role'] == 'factor'
    assert band['type'] == 'category'
    assert band['group'] == 'Категория'
    assert band['top_group'] == 'ВНЕШНИЕ ФАКТОРЫ', (
        f"category должна идти в ВНЕШНИЕ ФАКТОРЫ, получили {band['top_group']!r}"
    )
    assert band['side'] == 'positive'  # positive-leaning shared demand
    assert band['data'] == _CATEGORY_PP


def test_no_category_no_band():
    """Без category-фактора нет полосы «Категория» (не выдумываем на пустом месте)."""
    res = build_decomposition_series(_DATES, _BASELINE, _MEDIA, {})
    assert all(s.get('group') != 'Категория' for s in res['series'])
    assert all(s.get('type') != 'category' for s in res['series'])


def test_zero_category_skipped():
    """Нулевой per_period category → полоса пропускается (нет эффекта — нет полосы)."""
    sfc = {'category_sales': _factor('category', [0.0] * 6)}
    res = build_decomposition_series(_DATES, _BASELINE, _MEDIA, sfc)
    assert _series_by_name(res, 'category_sales') is None


def test_identity_holds_with_category():
    """INV-50: сумма всех серий по периоду == исходный total (baseline + медиа).

    baseline вынес category в отдельную полосу (baseline_reduced), полоса вернула
    её обратно — суммарно ряд обязан совпасть с тем, что было до выноса.
    """
    sfc = {'category_sales': _factor('category', _CATEGORY_PP)}
    res = build_decomposition_series(_DATES, _BASELINE, _MEDIA, sfc)
    for t in range(len(_DATES)):
        total_original = _BASELINE[t] + sum(ts[t] for ts in _MEDIA.values())
        total_series = sum(s['data'][t] for s in res['series'])
        assert abs(total_series - total_original) < 1e-6, (
            f'период {t}: тождество нарушено {total_series} != {total_original}'
        )


def test_category_external_competitor_separate():
    """Контраст: category → ВНЕШНИЕ ФАКТОРЫ, competitor → КОНКУРЕНТЫ (не одна куча)."""
    sfc = {
        'category_sales': _factor('category', _CATEGORY_PP),
        'competitor_trp': _factor('signed_competitor', [-30.0, -25.0, -40.0, -20.0, -35.0, -28.0]),
    }
    res = build_decomposition_series(_DATES, _BASELINE, _MEDIA, sfc)
    cat = _series_by_name(res, 'category_sales')
    comp = _series_by_name(res, 'competitor_trp')
    assert cat['top_group'] == 'ВНЕШНИЕ ФАКТОРЫ'
    assert comp['top_group'] == 'КОНКУРЕНТЫ'
    assert comp['side'] == 'negative'  # конкурент давит продажи


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
