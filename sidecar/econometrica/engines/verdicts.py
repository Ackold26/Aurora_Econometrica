"""
Aurora Econometrica — KPI-aware verdicts engine (v1.3.0).

Per ADR-016: бинарное разделение monetary vs count для verdict semantics:
- monetary: ROI vs пороги (0.5/0.8/1.0).
- count: CPU vs value_per_count_unit (2x / 1x / 1.1x ratios).

Этот модуль — wrapper над существующим compute_roi_verdict (engines/decomposer.py),
который diapatches по kpi_kind. Backward compat: kpi_kind='monetary' → identical to v1.2.

Usage:
    from engines.verdicts import compute_verdict_kpi_aware

    # Monetary (v1.2 behavior preserved):
    label, tone = compute_verdict_kpi_aware(
        roi=1.5, efficiency_gap=0.05, kpi_kind='monetary',
    )

    # Count (new v1.3):
    label, tone = compute_verdict_kpi_aware(
        cpu=120, value_per_count_unit=80, efficiency_gap=0.05,
        kpi_kind='count',
    )
    # → ('Убыточный (CPU выше ценности единицы)', 'bad')
"""
from __future__ import annotations

from typing import Optional, Tuple


# CPU thresholds (multiplier of value_per_count_unit).
CPU_DEEP_LOSS_MULTIPLIER = 2.0   # CPU > 2x value → deep loss
CPU_LOSS_MULTIPLIER = 1.0        # CPU > 1x value → loss
CPU_BREAKEVEN_MULTIPLIER = 0.9   # CPU in [0.9x, 1.0x) → on the edge


def compute_verdict_count_kpi(
    cpu: float,
    value_per_count_unit: Optional[float],
    *,
    efficiency_gap: float = 0.0,
    cpu_ci_low: Optional[float] = None,
    cpu_ci_high: Optional[float] = None,
    unit_smell: bool = False,
) -> Tuple[str, str]:
    """Count KPI verdict — comparison CPU vs value_per_count_unit.

    Args:
        cpu: cost per unit (₽ затрат / count_unit), e.g. ₽/упаковка, ₽/лид.
        value_per_count_unit: ценность одной единицы (₽). None → fallback на share-based.
        efficiency_gap: share_of_effect - share_of_spend (для fallback).
        cpu_ci_low, cpu_ci_high: posterior 90% CI bounds.
        unit_smell: True если канал в TRP/clicks/impressions (нет денежных бюджетов).

    Returns:
        (verdict_label, verdict_tone) where tone ∈ {good, warn, bad, neutral}.
    """
    # Wide CI suffix logic (parallel to v1.2 ROI).
    wide_ci = (
        cpu_ci_low is not None
        and cpu_ci_high is not None
        and cpu > 0
        and (cpu_ci_high - cpu_ci_low) > cpu
    )

    def _apply_ci_suffix(label, tone):
        if wide_ci:
            return (f"{label} (широкий интервал CPU)", 'warn' if tone == 'good' else tone)
        return (label, tone)

    # Hard caps regardless of value.
    if cpu < 0:
        # Защита от nonsense data.
        return _apply_ci_suffix('CPU отрицателен (артефакт)', 'warn')

    if value_per_count_unit is None or value_per_count_unit <= 0:
        # Fallback: без value не можем сказать «убыточный/окупаемый».
        # Используем efficiency gap для нейтральных тегов.
        if efficiency_gap < -0.10:
            return _apply_ci_suffix('Слабый вклад', 'warn')
        elif efficiency_gap > 0.10:
            return _apply_ci_suffix('Эффективный', 'good')
        return _apply_ci_suffix('Сбалансирован', 'neutral')

    # Main comparison: CPU vs value.
    if unit_smell and cpu < value_per_count_unit * 0.1:
        # CPU подозрительно низкий + канал на physical metrics — возможно artifact.
        return _apply_ci_suffix('CPU подозрительно низкий (проверьте единицы)', 'warn')

    if cpu > value_per_count_unit * CPU_DEEP_LOSS_MULTIPLIER:
        return _apply_ci_suffix(
            f'Глубоко убыточный (CPU > 2× ценности единицы)', 'bad'
        )
    if cpu > value_per_count_unit * CPU_LOSS_MULTIPLIER:
        return _apply_ci_suffix(
            'Убыточный (CPU выше ценности единицы)', 'bad'
        )
    if cpu > value_per_count_unit * CPU_BREAKEVEN_MULTIPLIER:
        return _apply_ci_suffix(
            'На грани окупаемости (CPU близок к ценности)', 'warn'
        )

    # CPU < value → channel прибылен. Уточняем through efficiency gap.
    if efficiency_gap >= 0.10:
        return _apply_ci_suffix('Высокоэффективен (CPU значительно ниже ценности)', 'good')
    if efficiency_gap >= 0.05:
        return _apply_ci_suffix('Эффективен (CPU ниже ценности)', 'good')
    return _apply_ci_suffix('Окупаемый (CPU < ценности)', 'good')


def compute_verdict_effectiveness_mode(
    sales_share: float,
    *,
    median_share: float = 0.0,
    p75_share: float = 0.0,
    p25_share: float = 0.0,
    threshold_share: float = 0.005,
    sales_share_ci_low: Optional[float] = None,
    sales_share_ci_high: Optional[float] = None,
) -> Tuple[str, str]:
    """Effectiveness mode verdict — share-based (когда нет cost-effectiveness данных).

    Per ADR-014 P0.8. В режиме Эффективность ROI/CPU не валидны (нет цены контакта).
    Главная сравнительная метрика — sales contribution share.

    Args:
        sales_share: доля канала в общих продажах (0..1).
        median_share: медиана share между каналами (для relative ranking).
        p75_share: 75-й перцентиль.
        p25_share: 25-й перцентиль.
        threshold_share: пороговая доля для "пренебрежимый вклад" (default 0.5%).
        sales_share_ci_low, sales_share_ci_high: posterior CI on share.

    Returns:
        (verdict_label, verdict_tone).
    """
    wide_ci = (
        sales_share_ci_low is not None
        and sales_share_ci_high is not None
        and sales_share > 0
        and (sales_share_ci_high - sales_share_ci_low) > sales_share
    )

    def _apply_ci_suffix(label, tone):
        if wide_ci:
            return (f"{label} (широкий интервал вклада)", 'warn' if tone == 'good' else tone)
        return (label, tone)

    if sales_share < threshold_share:
        return _apply_ci_suffix('Пренебрежимо малый вклад', 'warn')
    if p75_share > 0 and sales_share > p75_share:
        return _apply_ci_suffix('Топ-драйвер вклада', 'good')
    if median_share > 0 and sales_share > median_share:
        return _apply_ci_suffix('Значимый вклад', 'good')
    if p25_share > 0 and sales_share < p25_share:
        return _apply_ci_suffix('Слабый вклад', 'warn')
    return _apply_ci_suffix('Средний вклад', 'neutral')


def compute_verdict_kpi_aware(
    *,
    kpi_kind: str = 'monetary',
    mode: str = 'roi',
    # Monetary inputs (kpi_kind='monetary', mode='roi'):
    roi: Optional[float] = None,
    efficiency_gap: float = 0.0,
    roi_ci_low: Optional[float] = None,
    roi_ci_high: Optional[float] = None,
    # Count inputs (kpi_kind='count'):
    cpu: Optional[float] = None,
    value_per_count_unit: Optional[float] = None,
    cpu_ci_low: Optional[float] = None,
    cpu_ci_high: Optional[float] = None,
    # Effectiveness inputs (mode='effectiveness'):
    sales_share: Optional[float] = None,
    median_share: float = 0.0,
    p75_share: float = 0.0,
    p25_share: float = 0.0,
    sales_share_ci_low: Optional[float] = None,
    sales_share_ci_high: Optional[float] = None,
    # Common:
    category: str = 'mixed',
    unit_smell: bool = False,
    n_channels: int = 0,
    category_quantiles: Optional[dict] = None,
) -> Tuple[str, str]:
    """Unified KPI/mode-aware verdict dispatch.

    Per ADR-014 (matrix 4 базовых режимов A/B/C/D):
    - mode='roi' & kpi_kind='monetary' (A): delegate к compute_roi_verdict (v1.2 behavior).
    - mode='roi' & kpi_kind='count' (B): CPU vs value_per_count_unit.
    - mode='effectiveness' & kpi_kind=any (C, D): share-based.
    - mode='manual': fallback на best available metric (CPU или share).

    Args: см. individual function signatures.

    Returns:
        (verdict_label, verdict_tone).
    """
    # Mode dispatch.
    if mode == 'effectiveness':
        # C, D: share-based (no ROI/CPU comparison).
        if sales_share is None:
            return ('Недостаточно данных', 'neutral')
        return compute_verdict_effectiveness_mode(
            sales_share,
            median_share=median_share,
            p75_share=p75_share,
            p25_share=p25_share,
            sales_share_ci_low=sales_share_ci_low,
            sales_share_ci_high=sales_share_ci_high,
        )

    # mode='roi' или 'manual' → dispatch по kpi_kind.
    if kpi_kind == 'count':
        if cpu is None:
            return ('Недостаточно данных (нет CPU)', 'neutral')
        return compute_verdict_count_kpi(
            cpu=cpu,
            value_per_count_unit=value_per_count_unit,
            efficiency_gap=efficiency_gap,
            cpu_ci_low=cpu_ci_low,
            cpu_ci_high=cpu_ci_high,
            unit_smell=unit_smell,
        )

    # Default: monetary ROI — delegate к v1.2 compute_roi_verdict (backward compat).
    if roi is None:
        return ('Недостаточно данных (нет ROI)', 'neutral')

    from engines.decomposer import compute_roi_verdict
    return compute_roi_verdict(
        roi=roi,
        efficiency_gap=efficiency_gap,
        category=category,
        unit_smell=unit_smell,
        roi_ci_low=roi_ci_low,
        roi_ci_high=roi_ci_high,
        n_channels=n_channels,
        category_quantiles=category_quantiles,
    )
