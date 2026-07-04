"""У3 (2026-07-04): числовой гейт ролей на Валидации.

media/control-предикторы входят в матрицу X численно (modeler astype(float)).
Текстовый столбец-атрибут с именем-ловушкой (напр. «Промо активность» со
значениями «высокая/средняя/низкая») уронил бы обучение. Гейт _is_numeric_parseable
понижает такие роли до 'unused' с подсказкой; money-строки («3 836 962 ₽»)
парсятся и роль сохраняют. Класс шире точечного F-AUD-5 (голое «категори»).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1] / 'sidecar' / 'econometrica'
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from engines.validator import _is_numeric_parseable, validate_data  # noqa: E402


class TestIsNumericParseable:
    @pytest.mark.parametrize("values", [
        ['3 836 962 ₽', '1 200 000 ₽', '950 000 ₽'],   # money пробелы+₽
        ['3,836,962 ₽', '1,200,000 ₽', '950,000'],       # money запятые-тысячи
        ['1,5', '2,3', '0,8'],                            # ru десятичная
        ['12%', '8%', '15%'],                             # проценты
        [100.0, 200.0, 300.0],                           # числовой dtype
    ])
    def test_numeric_like_passes(self, values):
        assert _is_numeric_parseable(pd.Series(values)) is True

    @pytest.mark.parametrize("values", [
        ['Категория А', 'Категория Б', 'Категория В'],   # чистый текст-классификатор
        ['высокая', 'средняя', 'низкая'],                 # порядковый текст
        ['100', 'текст', '200', 'ещё'],                   # смесь 50% < порога 80%
    ])
    def test_text_like_fails(self, values):
        assert _is_numeric_parseable(pd.Series(values)) is False

    def test_empty_series_is_false(self):
        assert _is_numeric_parseable(pd.Series([], dtype=object)) is False

    def test_threshold_boundary(self):
        # 4 числа + 1 текст = 80% → проходит (≥ threshold).
        assert _is_numeric_parseable(pd.Series(['1', '2', '3', '4', 'x'])) is True
        # 3 числа + 2 текста = 60% → не проходит.
        assert _is_numeric_parseable(pd.Series(['1', '2', '3', 'x', 'y'])) is False


class TestValidateDataNumericGate:
    def test_text_control_column_demoted(self, tmp_path):
        """Текстовая колонка с control-именем → role снят до 'unused' + warning."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'tv_spend': range(10, 22),
            'Промо активность': ['высокая', 'средняя', 'низкая'] * 4,  # текст-ловушка
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        assert r['status'] != 'error'
        promo = next(c for c in r['columns'] if c['name'] == 'Промо активность')
        assert promo['role'] == 'unused', f"текстовый control не снят: {promo['role']}"
        assert any(
            w['column'] == 'Промо активность' and w['type'] == 'non_numeric_role'
            for w in r['warnings']
        ), 'нет подсказки non_numeric_role'

    def test_money_string_control_kept(self, tmp_path):
        """Money-строковая control-колонка парсится → роль control сохраняется."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'tv_spend': range(10, 22),
            'Продажи категории руб': [f'{v} 000 ₽' for v in range(500, 512)],  # money-строка
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        assert r['status'] != 'error'
        cat = next(c for c in r['columns'] if c['name'] == 'Продажи категории руб')
        # Имя: ТЕМА(категории)+ОБЪЁМ(продажи/руб) → control; значения money-строки
        # парсятся → гейт НЕ снимает роль.
        assert cat['role'] == 'control', f"money-строка control ошибочно снята: {cat['role']}"

    def test_numeric_media_unaffected(self, tmp_path):
        """Числовой media-столбец гейт не трогает."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'tv_spend': range(10, 22),
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        tv = next(c for c in r['columns'] if c['name'] == 'tv_spend')
        assert tv['role'] == 'media'
        assert not any(w.get('type') == 'non_numeric_role' for w in r['warnings'])
