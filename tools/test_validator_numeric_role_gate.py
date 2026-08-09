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
        """Money-строковая control-колонка: численный гейт ролей (497) видит
        число → роль control сохраняется. Но dtype колонки остаётся текстовым
        (Excel не приводит «500 000 ₽» к числу сам) → отдельная critical-проверка
        формата (validator.py:702-718, 2026-08-03) поднимает status='error':
        без неё astype(float) в modeler.py тихо упал бы при обучении, пока
        пользователь не переформатирует файл."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'tv_spend': range(10, 22),
            'Продажи категории руб': [f'{v} 000 ₽' for v in range(500, 512)],  # money-строка
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        cat = next(c for c in r['columns'] if c['name'] == 'Продажи категории руб')
        # Имя: ТЕМА(категории)+ОБЪЁМ(продажи/руб) → control; значения money-строки
        # парсятся → численный гейт ролей НЕ снимает роль.
        assert cat['role'] == 'control', f"money-строка control ошибочно снята: {cat['role']}"
        # Но status обязан стать 'error' — critical-проверка формата видит, что
        # колонка осталась текстовой, и предупреждает ДО обучения.
        assert r['status'] == 'error', f"critical-проверка формата не сработала: status={r['status']}"
        fmt_issues = [
            i for i in r['issues']
            if i['column'] == 'Продажи категории руб' and i['type'] == 'non_numeric_format'
        ]
        assert fmt_issues, 'нет critical issue non_numeric_format для money-строки'
        assert fmt_issues[0]['severity'] == 'critical'
        assert 'формат' in fmt_issues[0]['message'] or 'текст' in fmt_issues[0]['message'], (
            f"сообщение не про формат/текст: {fmt_issues[0]['message']}"
        )

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


class TestValidateDataTotalBudgetGate:
    """Т3-плюс П1: суммарный бюджет как media задваивает вклад (в MMX 6.45%) и
    рвёт согласованность timeline↔таблица. Критерий единый с _merge_channels."""

    def test_total_budget_column_demoted(self, tmp_path):
        """Числовая колонка «Бюджет ДО НДС» (нет инструмента) → role снят + warning."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'OLV Бюджет ДО НДС': range(10, 22),       # реальный канал
            'Бюджет ДО НДС': range(50, 62),           # суммарный агрегат
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        assert r['status'] != 'error'
        total = next(c for c in r['columns'] if c['name'] == 'Бюджет ДО НДС')
        assert total['role'] == 'unused', f"суммарный бюджет не снят: {total['role']}"
        w = next(
            (w for w in r['warnings']
             if w['column'] == 'Бюджет ДО НДС' and w['type'] == 'total_budget_as_media'),
            None,
        )
        assert w is not None, 'нет подсказки total_budget_as_media'
        # Г-1 (аудит №4): роль уже снята — action НЕ 'exclude' (иначе фронт
        # рендерит кнопку «Исключить» на уже исключённой колонке).
        assert w['action'] == 'acknowledge', f"action={w['action']!r}"

    def test_real_channel_with_budget_tokens_kept(self, tmp_path):
        """«OLV Бюджет ДО НДС» — есть инструмент (OLV) → остаётся media."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'OLV Бюджет ДО НДС': range(10, 22),
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        olv = next(c for c in r['columns'] if c['name'] == 'OLV Бюджет ДО НДС')
        assert olv['role'] == 'media', f"реальный канал ошибочно снят: {olv['role']}"
        assert not any(w.get('type') == 'total_budget_as_media' for w in r['warnings'])

    def test_itogo_budget_demoted(self, tmp_path):
        """Аудит №3 п.1: «ИТОГО Бюджет» (агрегатное слово) тоже снимается —
        раньше нормализация оставляла «ИТОГО» и колонка шла в модель каналом."""
        df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=12, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 112),
            'Total TV Бюджет': range(10, 22),   # реальный канал (Total TV → TV)
            'ИТОГО Бюджет': range(50, 62),      # агрегат
        })
        f = tmp_path / 'data.xlsx'
        df.to_excel(f, index=False)
        r = validate_data(str(f))
        itogo = next(c for c in r['columns'] if c['name'] == 'ИТОГО Бюджет')
        assert itogo['role'] == 'unused', f"«ИТОГО Бюджет» не снят: {itogo['role']}"
        assert any(
            w['column'] == 'ИТОГО Бюджет' and w['type'] == 'total_budget_as_media'
            for w in r['warnings']
        )
        tv = next(c for c in r['columns'] if c['name'] == 'Total TV Бюджет')
        assert tv['role'] == 'media', f"«Total TV Бюджет» ошибочно снят: {tv['role']}"


class TestKpiPatternsLeads:
    """Ф-1 (аудит примеров 2026-07-05): leads/лиды/заявки — count-KPI."""

    def test_leads_detected_as_kpi(self):
        from engines.validator import detect_column_role_with_confidence as det
        assert det('leads')[0] == 'kpi'
        assert det('Лиды')[0] == 'kpi'
        assert det('Заявки')[0] == 'kpi'


class TestPairExampleRoles:
    """Аудит №5 (2026-07-05): роли имён парных примеров + честный short_period."""

    def test_apteka_contacts_is_media(self):
        from engines.validator import detect_column_role_with_confidence as det
        assert det('apteka_contacts')[0] == 'media'   # Д-1

    def test_promo_indicator_is_control(self):
        from engines.validator import detect_column_role_with_confidence as det
        assert det('promo_indicator')[0] == 'control'  # Д-2: не медиа-канал с ROI

    def test_short_period_uses_date_span_not_row_count(self, tmp_path):
        """Д-3: 36 МЕСЯЦЕВ (3 года) — предупреждения НЕТ; 6 месяцев — ЕСТЬ."""
        import pandas as pd
        long_df = pd.DataFrame({
            'date': pd.date_range('2022-01-01', periods=36, freq='ME').strftime('%Y-%m-%d'),
            'sales': range(100, 136),
            'tv_spend': range(10, 46),
            'digital_spend': range(5, 41),
        })
        f1 = tmp_path / 'long.xlsx'; long_df.to_excel(f1, index=False)
        r1 = validate_data(str(f1))
        assert not any(w.get('type') == 'short_period' for w in r1['warnings']), \
            '3 года месячных данных не должны пугать «менее 1 года»'

        short_df = long_df.head(6)
        f2 = tmp_path / 'short.xlsx'; short_df.to_excel(f2, index=False)
        r2 = validate_data(str(f2))
        assert any(w.get('type') == 'short_period' for w in r2['warnings'])
