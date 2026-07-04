"""Фаза Б (2026-07-04): категорийный контроль спроса (продажи рынка/категории).

Экзогенный контроль спроса (Chan & Perry §4.2.2): объём категории не зависит от
медиа одного бренда, но задаёт волну спроса, на которую бренд «плывёт» → сильнейший
прокси (реальный ряд, сильнее гладкого Фурье). classify_column детектит его комбо
ТЕМА+ОБЪЁМ → kind 'category' (positive-leaning prior в modeler); validate_data
подсказывает загрузить его, когда клиент уже отслеживает рынок (есть competitor).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from engines.validator import validate_data  # noqa: E402
from utils.column_detection import classify_column  # noqa: E402


class TestClassifyCategory:
    @pytest.mark.parametrize("name", [
        'Продажи категории руб', 'Продажи рынка в руб', 'Объём рынка',
        'market_sales', 'category_volume', 'Спрос категории шт',
    ])
    def test_category_detected(self, name):
        assert classify_column(name) == 'category', f'{name} → {classify_column(name)}'

    @pytest.mark.parametrize("name,expected", [
        # ТЕМА без ОБЪЁМ — текстовый атрибут-классификатор (F-AUD-5 класс), НЕ category.
        ('Категория А', 'unknown'),
        ('Категория канала', 'unknown'),
        ('Категоризация', 'unknown'),
        # Конкуренты — competitor, не category (проверяется раньше).
        ('Продажи в руб. конкуренты', 'signed_competitor'),
        # Бренд-продажи — не category (нет ТЕМА рынок/категория).
        ('Продажи в руб. бренд', 'unknown'),
    ])
    def test_not_category(self, name, expected):
        assert classify_column(name) == expected, f'{name} → {classify_column(name)}'

    @pytest.mark.parametrize("name", [
        # Аудит 2026-07-04 (F-1): derived-метрики (доля/share/SOM/SOV) = ТЕМА+ОБЪЁМ,
        # но ЭНДОГЕННЫ (производные от KPI) — обязаны НЕ попадать в category, иначе
        # при ручном назначении контролем в Roles UI получают positive-leaning prior.
        'Доля рынка в руб',
        'Доля рынка руб',
        'Доля категории в продажах',
        'Market share value',
        'SOM в руб. категория',
        'share of market total',
        'value share категории',
    ])
    def test_derived_not_category(self, name):
        got = classify_column(name)
        assert got != 'category', (
            f'F-1: derived-метрика {name!r} попала в category ({got}) — '
            f'эндогенная доля получила бы positive prior'
        )


class TestCategorySuggestion:
    def _mk(self, tmp_path, extra_cols):
        cols = {
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'tv_spend': range(10, 22),
        }
        cols.update(extra_cols)
        df = pd.DataFrame(cols)
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        return validate_data(str(f))

    def test_suggests_when_competitor_but_no_category(self, tmp_path):
        """Есть competitor, нет category → подсказка suggest_category."""
        r = self._mk(tmp_path, {'competitor_trp': range(50, 62)})
        assert r['status'] != 'error'
        assert any(w.get('type') == 'suggest_category' for w in r['warnings']), \
            'ожидалась подсказка загрузить продажи категории'

    def test_no_suggestion_when_category_present(self, tmp_path):
        """Category уже есть → подсказки нет (не спамим)."""
        r = self._mk(tmp_path, {
            'competitor_trp': range(50, 62),
            'Продажи рынка руб': range(500, 512),
        })
        assert r['status'] != 'error'
        assert not any(w.get('type') == 'suggest_category' for w in r['warnings'])

    def test_no_suggestion_without_competitor(self, tmp_path):
        """Нет competitor (не конкурентный контекст) → не спамим подсказкой."""
        r = self._mk(tmp_path, {'distribution': range(80, 92)})
        assert r['status'] != 'error'
        assert not any(w.get('type') == 'suggest_category' for w in r['warnings'])
