"""s63 №12 и №14: голое «клик» и знаки `/ | [ ] – '` как разделители слов в детекторе колонок.

№12. Шаблон `кликов?` читался как «клико» + необязательное «в»: слово «клик» не
совпадало, «Контекст (клик)» на основном пути уходило в обучение как рубли.
№14. Класс разделителей `_SEP/_END` не знал `/ | [ ] – '`: «ТВ/GRP», «TV–GRP»,
«TV [GRP]» не узнавались как физические.

Тесты вызывают публичную `classify_column` (поведение), а не читают исходник.
Обратные контроли: денежные имена с теми же знаками остаются денежными, слово
внутри длинного слова не срабатывает (`_END` считает конец слова).
"""
import sys
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

import pytest
from utils.column_detection import classify_column

# Новые разделители из №14 (– = U+2013, короткое тире).
NEW_SEPARATORS = ['/', '|', '[', ']', '–', "'"]


class TestBareClickRu:
    """№12: «клик» – физическая величина (не рубли)."""

    @pytest.mark.parametrize('name', [
        'клик',
        'Клик',
        'КЛИК',
        'клики',
        'кликов',
        'Контекст (клик)',
        'Контекст_клик',
        'Контекст клик',
        'Контекст [клик]',
        'ctx_clicks',
    ])
    def test_click_is_physical(self, name):
        assert classify_column(name) == 'physical'

    @pytest.mark.parametrize('name', [
        'клико',            # прежнее «клико» + «в?» ловилось случайно, словом не является
        'кликабельность',   # слово внутри длинного слова
        'кликер',
        'Контекст_кликнул',
    ])
    def test_click_inside_longer_word_is_not_physical(self, name):
        assert classify_column(name) != 'physical'

    @pytest.mark.parametrize('name', [
        'Клик-бюджет',
        'Бюджет, клик',
        'Бюджет клики',
        'Затраты на клики',
        'Контекст_клик_rub',
        'Контекст (клик), ₽',
        'стоимость клика',
    ])
    def test_click_with_money_marker_stays_monetary(self, name):
        assert classify_column(name) == 'monetary'


class TestNewSeparators:
    """№14: `/ | [ ] – '` – разделители слов. Проверяем каждый знак отдельно с обеих
    сторон слова: слева работает `_SEP`, справа `_END` (в начале и конце строки
    граница даётся «^» и «$», поэтому знак ставится только с проверяемой стороны)."""

    @pytest.mark.parametrize('sep', NEW_SEPARATORS)
    def test_separator_before_token(self, sep):
        assert classify_column(f'TV{sep}GRP') == 'physical'

    @pytest.mark.parametrize('sep', NEW_SEPARATORS)
    def test_separator_after_token(self, sep):
        assert classify_column(f'GRP{sep}TV') == 'physical'

    @pytest.mark.parametrize('name', [
        'ТВ/GRP',
        'ТВ/ГРП',
        'TV–GRP',
        'TV | GRP',
        'TV [GRP]',
        "TV'GRP",
        'ТВ|ГРП',
        'OLV/views',
        'OLV [views]',
        'Контекст/клик',
        'TRP/GRP',
    ])
    def test_issue_names_are_physical(self, name):
        assert classify_column(name) == 'physical'

    @pytest.mark.parametrize('name', [
        'Бюджет ТВ / Москва',
        'TV | spend',
        'ТВ|бюджет',
        'tv/spend',
        'tv/rub',
        'TV–spend',
        "TV'spend",
        'Бюджет/GRP',    # «бюджет на GRP» – деньги: денежный маркер сильнее физического
        'Cost/GRP',
        'Spend [GRP]',
    ])
    def test_money_names_with_new_separators_stay_monetary(self, name):
        assert classify_column(name) == 'monetary'

    @pytest.mark.parametrize('name', [
        'ТВ [руб]',     # «руб» не денежный маркер движка → unknown (фронт отдаёт деньги по умолчанию)
        'ТВ (руб)',
        'ТВ / Москва',
        'TV | OLV',
        'TV/OLV',
    ])
    def test_names_without_physical_word_are_not_physical(self, name):
        assert classify_column(name) != 'physical'

    @pytest.mark.parametrize('name', [
        'TV/GRPX',
        'TV/grpmax',
        'ТВ/ГРПэ',
        'TV|reacher',
        'TV/reachable',
        "TV'impressionist",
        'OLV [viewport]',
        'Контекст/кликабельность',
    ])
    def test_token_inside_longer_word_is_not_physical(self, name):
        assert classify_column(name) != 'physical'

    def test_existing_separators_unchanged(self):
        # прежний класс `_\s\-,.;:()` работает как раньше
        for name in ['tv_grp', 'tv-grp', 'tv grp', 'TV (GRP)', 'OLV.views', 'Digital: показы', 'TV, GRP']:
            assert classify_column(name) == 'physical', name
        for name in ['tv_spend', 'TV (spend)', 'OLV.cost', 'Бюджет, руб.']:
            assert classify_column(name) == 'monetary', name

    def test_em_dash_is_not_a_separator(self):
        # U+2014 в шаблонах запрещён (правило проекта): длинное тире словоразделителем не стало
        assert classify_column('TV—GRP') != 'physical'
