"""
Aurora Econometrica - KPI/mode-aware UI/report labels (v1.4.0 — Фаза 1a KPI-паспорт).

Helper для report builders (HTML/PPTX/XLSX/DOCX): возвращает правильные labels
column header / cover metric / chart axis в зависимости от (kpi_kind, mode, kpi_type).

Per ADR-016 + REFACTOR_PLAN_v1.3.0.md матрица 4 базовых режимов.
Фаза 1a (2026-07-11): добавлен параметр kpi_type для паспортных подписей.
При kpi_type=None — полная обратная совместимость (kind-only fallback).

Usage:
    from utils.kpi_labels import metric_label, target_unit_label, format_metric

    # Новый (с паспортом):
    label = metric_label(kpi_kind='count', mode='roi', kpi_type='leads')  # → 'CPU, ₽/лид'
    target = target_axis_label(kpi_kind='count', kpi_type='leads')        # → 'Лиды'
    formatted = format_metric(0.0125, kpi_kind='count', kpi_type='leads') # → '80 ₽/лид'

    # Старый (без kpi_type — поведение как раньше):
    label = metric_label(kpi_kind='count', mode='roi')  # → 'CPU, ₽/ед.'
    target = target_unit_label('count')  # → 'упак / ед.'
    formatted = format_metric(value=120.5, kpi_kind='count', mode='roi')  # → '120 ₽/ед.'
"""
from __future__ import annotations

from typing import Optional


def _get_passport(kpi_type: Optional[str]) -> Optional[dict]:
    """Загружает паспорт KPI из реестра. Возвращает None при kpi_type=None или ошибке."""
    if not kpi_type:
        return None
    try:
        from utils.kpi_display import get_display
        return get_display(kpi_type)
    except Exception:
        return None


def metric_label(kpi_kind: str = 'monetary', mode: str = 'roi', kpi_type: Optional[str] = None) -> str:
    """Main metric column label per (kpi_kind, mode, kpi_type) matrix.

    Матрица (Фаза 1a):
    - mode='effectiveness'  → 'Доля %' (irrespective of kpi_kind).
    - kpi_kind='count'      → 'CPU, ' + P['cpu_per_label']  (напр. 'CPU, ₽/лид').
    - default               → 'ROI'.

    При kpi_type=None — прежнее поведение (backward-compat).
    """
    if mode == 'effectiveness':
        return 'Доля %'
    if kpi_kind == 'count':
        P = _get_passport(kpi_type)
        if P and P.get('cpu_per_label'):
            return f'CPU, {P["cpu_per_label"]}'
        return 'CPU, ₽/ед.'
    return 'ROI'


def metric_short_label(kpi_kind: str = 'monetary', mode: str = 'roi', kpi_type: Optional[str] = None) -> str:
    """Short version (для bar charts, sparkline labels). Same logic, shorter strings."""
    if mode == 'effectiveness':
        return 'Доля'
    if kpi_kind == 'count':
        return 'CPU'
    return 'ROI'


def target_unit_label(kpi_kind: str = 'monetary', kpi_type: Optional[str] = None) -> str:
    """Label целевой метрики (для cover slide, chart axis).

    monetary → '₽'.
    count + kpi_type → P['result_unit_short'] из паспорта.
    count без kpi_type → 'упак / ед.' (backward-compat).
    """
    if kpi_kind == 'count':
        P = _get_passport(kpi_type)
        if P and P.get('result_unit_short'):
            return P['result_unit_short']
        return 'упак / ед.'
    return '₽'


def target_axis_label(kpi_kind: str = 'monetary', kpi_type: Optional[str] = None) -> str:
    """Полный axis label для timeline / response curves.

    ВСЕГДА = P['result_axis_label'] из паспорта (если kpi_type задан).
    Чинит баг: раньше effectiveness давал «Продажи, ₽» даже для count-KPI.
    Fallback: kind-only поведение при kpi_type=None.
    """
    P = _get_passport(kpi_type)
    if P and P.get('result_axis_label'):
        return P['result_axis_label']
    # Backward-compat fallback (kpi_type=None или kpi_type не в реестре)
    return 'Продажи, упак' if kpi_kind == 'count' else 'Продажи, ₽'


def format_metric(
    value: Optional[float],
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    value_per_count_unit: Optional[float] = None,
    kpi_type: Optional[str] = None,
) -> str:
    """Format metric value per (kpi_kind, mode, kpi_type).

    B4 audit fix (v1.3.2): backend convention - per-channel mroas/roi всегда
    mathematical ratio = KPI_units / ₽_spend. Для count это units/₽ (e.g.
    0.0125). CPU = 1/x = ₽/ед. Invert при display.

    Фаза 1a: для count с kpi_type — подставляем P['cpu_per_label'] вместо '₽/ед.'.

    Examples:
    - kpi=monetary, mode=roi: 1.5 → '1.50×' (no transform)
    - kpi=count, mode=roi, kpi_type='leads': 0.0125 → '80 ₽/лид' (inverted)
    - kpi=count, mode=roi, kpi_type=None: 0.0125 → '80 ₽/ед.' (backward-compat)
    - mode=effectiveness fraction: 0.25 → '25.0%'
    """
    if value is None:
        return '-'
    if mode == 'effectiveness':
        return f'{value * 100:.1f}%'
    if kpi_kind == 'count':
        # B4: invert units/₽ → CPU. Zero/negative → fallback.
        if value > 0:
            cpu = 1.0 / value
            P = _get_passport(kpi_type)
            unit = P['cpu_per_label'] if (P and P.get('cpu_per_label')) else '₽/ед.'
            return f'{cpu:.0f} {unit}'
        return '-'
    return f'{value:.2f}×'


def cover_metric_summary(
    avg_metric: Optional[float],
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    value_per_count_unit: Optional[float] = None,
    kpi_type: Optional[str] = None,
) -> str:
    """One-line cover summary per kpi_kind/mode/kpi_type.

    Reserved для PPTX/HTML cover slide когда будет нужен подробный one-liner
    с vpcu reference. Currently не used в production (sections.py и builder.py
    используют свои _weighted_summary_phrase variants для in-body text).

    L1 audit note: alternative «ROI портфеля 1.50×» phrasing implemented в
    sections.py:_weighted_summary_phrase. Различия осознанные - cover line
    более descriptive («Средний CPU: X ₽/лид (vs ценность Y ₽)»), body line
    более compact.

    Input avg_metric от backend = mathematical KPI/spend ratio. format_metric
    делает inversion для count display.

    monetary roi: 'Средний ROI: 1.50×'
    count roi (avg_metric=0.0125, kpi_type='leads'): 'Средний CPU: 80 ₽/лид (vs ценность 80 ₽)'
    effectiveness: 'Главная метрика: доля канала в продажах'
    """
    if mode == 'effectiveness':
        # avg_metric - share % top-канала.
        return f'Главная метрика: доля канала в продажах'
    if kpi_kind == 'count':
        formatted = format_metric(avg_metric, kpi_kind, mode, kpi_type=kpi_type)
        if value_per_count_unit:
            return f'Средний CPU: {formatted} (vs ценность {value_per_count_unit:.0f} ₽)'
        return f'Средний CPU: {formatted}'
    formatted = format_metric(avg_metric, kpi_kind, mode, kpi_type=kpi_type)
    return f'Средний ROI: {formatted}'


def verdict_loss_threshold_label(kpi_kind: str = 'monetary', kpi_type: Optional[str] = None) -> str:
    """Methodology footnote text для отчётов."""
    if kpi_kind == 'count':
        P = _get_passport(kpi_type)
        unit = P['cpu_per_label'] if (P and P.get('cpu_per_label')) else '₽/ед.'
        return (
            f'CPU = бюджет канала / прирост продаж в единицах. '
            f'Сравнение с value_per_count_unit (маржа на упаковку / ценность лида / MRR подписки). '
            f'CPU > 2× value → глубоко убыточный. CPU > value → убыточный. '
            f'CPU ≈ value → на грани окупаемости. CPU < value → окупаемый.'
        )
    return (
        'ROI = вклад канала в продажи (₽) / затраты на канал (₽). '
        'ROI > 1.0 = канал окупается. ROI < 0.5 = глубоко убыточный.'
    )
