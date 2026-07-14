"""Фаза 1a — KPI-паспорт: тесты паспортных подписей (kpi_labels + kpi_view).

Проверяем:
1. target_axis_label берёт метку из паспорта (не из kind-only fallback).
2. Ось count+effectiveness ≠ 'Продажи, ₽' (чинит баг effectiveness→count).
3. metric_label count+roi = 'CPU, ₽/лид' (а не generic 'CPU, ₽/ед.').
4. format_metric count с kpi_type='leads': 0.0125 → '80 ₽/лид'.
5. Backward-compat: вызов без kpi_type не падает, возвращает прежние значения.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.kpi_labels import (  # noqa: E402
    target_axis_label,
    target_unit_label,
    metric_label,
    metric_short_label,
    format_metric,
    cover_metric_summary,
    verdict_loss_threshold_label,
)


class TestTargetAxisLabelPassport:
    """target_axis_label берёт результат из паспорта."""

    def test_leads_axis(self):
        result = target_axis_label(kpi_kind='count', kpi_type='leads')
        assert result == 'Лиды', f"Ожидалось 'Лиды', получили '{result}'"

    def test_sales_packs_axis_contains_upak(self):
        result = target_axis_label(kpi_kind='count', kpi_type='sales_packs')
        assert 'упак' in result.lower(), f"Ожидалось содержание 'упак', получили '{result}'"

    def test_sales_packs_effectiveness_not_rub(self):
        """Ось count-KPI с любым mode = результат паспорта, НЕ 'Продажи, ₽'.

        Баг до Фазы 1a: effectiveness mode с count-KPI мог давать 'Продажи, ₽'.
        target_axis_label теперь ВСЕГДА = P['result_axis_label'] при kpi_type задан.
        """
        result = target_axis_label(kpi_kind='count', kpi_type='sales_packs')
        assert result != 'Продажи, ₽', (
            f"Ось count-KPI не должна быть 'Продажи, ₽', получили '{result}'"
        )

    def test_monetary_axis_no_kpi_type(self):
        """monetary без kpi_type — прежнее поведение."""
        result = target_axis_label(kpi_kind='monetary')
        assert result == 'Продажи, ₽'

    def test_count_axis_no_kpi_type(self):
        """count без kpi_type — прежнее поведение (kind-only fallback)."""
        result = target_axis_label(kpi_kind='count')
        assert result == 'Продажи, упак'


class TestMetricLabelPassport:
    """metric_label count+roi = 'CPU, ₽/лид' (паспортная единица)."""

    def test_count_leads_roi(self):
        result = metric_label(kpi_kind='count', mode='roi', kpi_type='leads')
        assert result == 'CPU, ₽/лид', f"Ожидалось 'CPU, ₽/лид', получили '{result}'"

    def test_count_leads_effectiveness(self):
        """Effectiveness всегда 'Доля %' независимо от kpi_type."""
        result = metric_label(kpi_kind='count', mode='effectiveness', kpi_type='leads')
        assert result == 'Доля %'

    def test_count_sales_packs_roi(self):
        result = metric_label(kpi_kind='count', mode='roi', kpi_type='sales_packs')
        assert 'упак' in result.lower() or '₽/упак' in result, (
            f"Ожидалась паспортная единица для sales_packs, получили '{result}'"
        )

    def test_monetary_roi(self):
        """monetary ROI — прежнее поведение."""
        result = metric_label(kpi_kind='monetary', mode='roi', kpi_type='sales')
        assert result == 'ROI'

    def test_backward_compat_count_no_kpi_type(self):
        """count без kpi_type — прежнее поведение 'CPU, ₽/ед.'."""
        result = metric_label(kpi_kind='count', mode='roi')
        assert result == 'CPU, ₽/ед.'


class TestFormatMetricPassport:
    """format_metric count с kpi_type: 0.0125 → '80 ₽/лид'."""

    def test_count_leads_format(self):
        result = format_metric(0.0125, kpi_kind='count', mode='roi', kpi_type='leads')
        assert result == '80 ₽/лид', f"Ожидалось '80 ₽/лид', получили '{result}'"

    def test_count_sales_packs_format(self):
        result = format_metric(0.01, kpi_kind='count', mode='roi', kpi_type='sales_packs')
        # cpu = 1/0.01 = 100, unit = '₽/упак.'
        assert '100' in result and 'упак' in result.lower(), (
            f"Ожидалось '100 ₽/упак.', получили '{result}'"
        )

    def test_effectiveness_no_invert(self):
        """effectiveness — fraction → %, kpi_type игнорируется."""
        result = format_metric(0.25, kpi_kind='count', mode='effectiveness', kpi_type='leads')
        assert result == '25.0%'

    def test_count_zero_fallback(self):
        """count, value=0 → '-' независимо от kpi_type."""
        result = format_metric(0.0, kpi_kind='count', mode='roi', kpi_type='leads')
        assert result == '-'

    def test_backward_compat_count_no_kpi_type(self):
        """count без kpi_type — прежнее поведение '₽/ед.'."""
        result = format_metric(0.0125, kpi_kind='count', mode='roi')
        assert result == '80 ₽/ед.', f"Ожидалось '80 ₽/ед.', получили '{result}'"

    def test_monetary_roi_no_kpi_type(self):
        """monetary ROI без kpi_type — прежнее поведение '×'."""
        result = format_metric(1.5, kpi_kind='monetary', mode='roi')
        assert result == '1.50×'


class TestBackwardCompat:
    """Все функции вызываются без kpi_type — не падают, дают прежние результаты."""

    def test_target_unit_label_no_kpi_type(self):
        assert target_unit_label('monetary') == '₽'
        assert target_unit_label('count') == 'упак / ед.'

    def test_metric_short_label_no_kpi_type(self):
        assert metric_short_label('count', 'roi') == 'CPU'
        assert metric_short_label('monetary', 'roi') == 'ROI'
        assert metric_short_label('count', 'effectiveness') == 'Доля'

    def test_cover_metric_summary_no_kpi_type(self):
        result = cover_metric_summary(1.5, kpi_kind='monetary', mode='roi')
        assert result == 'Средний ROI: 1.50×'

    def test_verdict_loss_threshold_no_kpi_type(self):
        result = verdict_loss_threshold_label('monetary')
        assert 'ROI' in result
        result_count = verdict_loss_threshold_label('count')
        assert 'CPU' in result_count

    def test_none_kpi_type_explicit(self):
        """Явно None — те же результаты, не падает."""
        assert target_axis_label('count', kpi_type=None) == 'Продажи, упак'
        assert metric_label('count', 'roi', kpi_type=None) == 'CPU, ₽/ед.'
        assert format_metric(0.0125, 'count', 'roi', kpi_type=None) == '80 ₽/ед.'


class TestKpiViewPassport:
    """kpi_view в kpi_helpers читает kpi_type из data['kpi'] и возвращает паспортные подписи."""

    def test_kpi_view_leads_target_axis(self):
        from aurora_pptx.kpi_helpers import kpi_view
        data = {
            'kpi': {
                'kpi_kind': 'count',
                'derived_mode': 'roi',
                'kpi_type': 'leads',
                'labels': {},
            }
        }
        kpi = kpi_view(data)
        assert kpi['target_axis'] == 'Лиды', (
            f"Ожидалось 'Лиды', получили '{kpi['target_axis']}'"
        )
        assert kpi['cpu_per_label'] == '₽/лид', (
            f"Ожидалось '₽/лид', получили '{kpi['cpu_per_label']}'"
        )

    def test_kpi_view_no_kpi_type_backward_compat(self):
        """Без kpi_type — legacy поведение."""
        from aurora_pptx.kpi_helpers import kpi_view
        data = {
            'kpi': {
                'kpi_kind': 'monetary',
                'derived_mode': 'roi',
                'labels': {
                    'target_axis_label': 'Продажи, ₽',
                    'target_unit_label': '₽',
                    'metric_label': 'ROI',
                    'metric_short_label': 'ROI',
                    'methodology_label': '',
                },
            }
        }
        kpi = kpi_view(data)
        assert kpi['target_axis'] == 'Продажи, ₽'
        assert kpi['is_legacy'] is True

    def test_fmt_metric_leads_kpi_view(self):
        """fmt_metric с kpi_view-результатом даёт '80 ₽/лид'."""
        from aurora_pptx.kpi_helpers import kpi_view, fmt_metric
        data = {
            'kpi': {
                'kpi_kind': 'count',
                'derived_mode': 'roi',
                'kpi_type': 'leads',
                'labels': {},
            }
        }
        kpi = kpi_view(data)
        result = fmt_metric(0.0125, kpi)
        assert result == '80 ₽/лид', f"Ожидалось '80 ₽/лид', получили '{result}'"
