"""
Aurora Econometrica — KPI/mode-aware UI/report labels (v1.3.0).

Helper для report builders (HTML/PPTX/XLSX/DOCX): возвращает правильные labels
column header / cover metric / chart axis в зависимости от (kpi_kind, mode).

Per ADR-016 + REFACTOR_PLAN_v1.3.0.md матрица 4 базовых режимов.

Usage:
    from utils.kpi_labels import metric_label, target_unit_label, format_metric

    label = metric_label(kpi_kind='count', mode='roi')  # → 'CPU, ₽/ед.'
    target = target_unit_label('count')  # → 'упак / ед.'
    formatted = format_metric(value=120.5, kpi_kind='count', mode='roi')  # → '120 ₽/ед.'
"""
from __future__ import annotations

from typing import Optional


def metric_label(kpi_kind: str = 'monetary', mode: str = 'roi') -> str:
    """Main metric column label per (kpi_kind, mode) matrix.

    Returns:
    - mode='effectiveness' → 'Доля %' (irrespective of kpi_kind).
    - kpi_kind='count' → 'CPU, ₽/ед.'.
    - default (kpi_kind='monetary', mode='roi') → 'ROI'.
    """
    if mode == 'effectiveness':
        return 'Доля %'
    if kpi_kind == 'count':
        return 'CPU, ₽/ед.'
    return 'ROI'


def metric_short_label(kpi_kind: str = 'monetary', mode: str = 'roi') -> str:
    """Short version (для bar charts, sparkline labels). Same logic, shorter strings."""
    if mode == 'effectiveness':
        return 'Доля'
    if kpi_kind == 'count':
        return 'CPU'
    return 'ROI'


def target_unit_label(kpi_kind: str = 'monetary') -> str:
    """Label целевой метрики (для cover slide, chart axis).

    monetary → '₽'.
    count → 'упак / ед.'.
    """
    return 'упак / ед.' if kpi_kind == 'count' else '₽'


def target_axis_label(kpi_kind: str = 'monetary') -> str:
    """Полный axis label для timeline / response curves."""
    return 'Продажи, упак' if kpi_kind == 'count' else 'Продажи, ₽'


def format_metric(
    value: Optional[float],
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    value_per_count_unit: Optional[float] = None,
) -> str:
    """Format metric value per (kpi_kind, mode).

    B4 audit fix (v1.3.2): backend convention — per-channel mroas/roi всегда
    mathematical ratio = KPI_units / ₽_spend. Для count это units/₽ (e.g.
    0.0125). CPU = 1/x = ₽/ед. Invert при display.

    Examples:
    - kpi=monetary, mode=roi: 1.5 → '1.50×' (no transform)
    - kpi=count, mode=roi: 0.0125 → '80 ₽/ед.' (inverted)
    - mode=effectiveness fraction: 0.25 → '25.0%'
    """
    if value is None:
        return '—'
    if mode == 'effectiveness':
        return f'{value * 100:.1f}%'
    if kpi_kind == 'count':
        # B4: invert units/₽ → CPU. Zero/negative → fallback.
        if value > 0:
            return f'{1.0 / value:.0f} ₽/ед.'
        return '—'
    return f'{value:.2f}×'


def cover_metric_summary(
    avg_metric: Optional[float],
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    value_per_count_unit: Optional[float] = None,
) -> str:
    """One-line cover summary per kpi_kind/mode.

    Reserved для PPTX/HTML cover slide когда будет нужен подробный one-liner
    с vpcu reference. Currently не used в production (sections.py и builder.py
    используют свои _weighted_summary_phrase variants для in-body text).

    L1 audit note: alternative «ROI портфеля 1.50×» phrasing implemented в
    sections.py:_weighted_summary_phrase. Различия осознанные — cover line
    более descriptive («Средний CPU: X ₽/ед. (vs ценность Y ₽)»), body line
    более compact.

    Input avg_metric от backend = mathematical KPI/spend ratio. format_metric
    делает inversion для count display.

    monetary roi: 'Средний ROI: 1.50×'
    count roi (avg_metric=0.0125): 'Средний CPU: 80 ₽/ед. (vs ценность 80 ₽)'
    effectiveness: 'Главная метрика: доля канала в продажах'
    """
    if mode == 'effectiveness':
        # avg_metric — share % top-канала.
        return f'Главная метрика: доля канала в продажах'
    if kpi_kind == 'count':
        formatted = format_metric(avg_metric, kpi_kind, mode)
        if value_per_count_unit:
            return f'Средний CPU: {formatted} (vs ценность {value_per_count_unit:.0f} ₽)'
        return f'Средний CPU: {formatted}'
    formatted = format_metric(avg_metric, kpi_kind, mode)
    return f'Средний ROI: {formatted}'


def verdict_loss_threshold_label(kpi_kind: str = 'monetary') -> str:
    """Methodology footnote text для отчётов."""
    if kpi_kind == 'count':
        return (
            'CPU = бюджет канала / прирост продаж в единицах. '
            'Сравнение с value_per_count_unit (маржа на упаковку / ценность лида / MRR подписки). '
            'CPU > 2× value → глубоко убыточный. CPU > value → убыточный. '
            'CPU ≈ value → на грани окупаемости. CPU < value → окупаемый.'
        )
    return (
        'ROI = вклад канала в продажи (₽) / затраты на канал (₽). '
        'ROI > 1.0 = канал окупается. ROI < 0.5 = глубоко убыточный.'
    )
