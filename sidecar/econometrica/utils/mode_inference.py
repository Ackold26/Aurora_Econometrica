"""
Aurora Econometrica — mode inference (v1.3.0).

Per ADR-015 (Mode as derived state): mode (ROI / Эффективность / Вручную) выводится
автоматически из per-channel input metrics, не выбирается юзером.

Usage:
    from utils.mode_inference import derive_mode

    per_channel = {'tv': 'monetary', 'olv': 'physical', 'performance': 'monetary'}
    mode = derive_mode(per_channel)  # → 'manual' (mixed)

    per_channel = {'tv': 'monetary', 'olv': 'monetary', 'performance': 'monetary'}
    mode = derive_mode(per_channel)  # → 'roi'

    per_channel = {'tv': 'physical', 'olv': 'physical', 'performance': 'physical'}
    mode = derive_mode(per_channel)  # → 'effectiveness'

References:
- ADR-015 (Mode as derived state).
- REFACTOR_PLAN_v1.3.0.md — матрица 4 базовых режимов.
"""
from __future__ import annotations

from typing import Dict, Literal, Mapping

# Input metric type per канал. Соответствует ADR-015.
# 'monetary'  — канал измеряется в ₽ (бюджет, spend).
# 'physical'  — канал измеряется в физ. контактах (показы, клики, GRP).
ChannelInputMetric = Literal['monetary', 'physical']

# Derived mode (output type).
# 'roi'            — все каналы в monetary; модель оценивает ROI ₽/₽.
# 'effectiveness'  — все каналы в physical; модель оценивает share-based metrics.
# 'manual'         — mixed: часть каналов в monetary, часть в physical.
DerivedMode = Literal['roi', 'effectiveness', 'manual']


def derive_mode(per_channel_inputs: Mapping[str, str]) -> DerivedMode:
    """Вычислить derived mode из per-channel input metric selection.

    Логика:
    - all 'monetary' → 'roi'
    - all 'physical' → 'effectiveness'
    - mixed → 'manual'
    - empty dict → 'roi' (default, чтобы не блокировать workflow)

    Args:
        per_channel_inputs: dict {channel_name: 'monetary'|'physical'}.

    Returns:
        Derived mode string.

    Raises:
        ValueError: если значения вне {'monetary', 'physical'}.

    Examples:
        >>> derive_mode({'tv': 'monetary', 'olv': 'monetary'})
        'roi'
        >>> derive_mode({'tv': 'physical', 'olv': 'physical'})
        'effectiveness'
        >>> derive_mode({'tv': 'monetary', 'olv': 'physical'})
        'manual'
        >>> derive_mode({})
        'roi'
    """
    if not per_channel_inputs:
        return 'roi'

    valid_values = {'monetary', 'physical'}
    for channel, metric in per_channel_inputs.items():
        if metric not in valid_values:
            raise ValueError(
                f"Channel '{channel}' has invalid metric '{metric}'. "
                f"Must be one of {valid_values}."
            )

    values = set(per_channel_inputs.values())

    if values == {'monetary'}:
        return 'roi'
    if values == {'physical'}:
        return 'effectiveness'
    # Mixed: monetary + physical = manual.
    return 'manual'


def is_mixed_mode(per_channel_inputs: Mapping[str, str]) -> bool:
    """True если каналы в смешанных единицах (= derived_mode == 'manual')."""
    return derive_mode(per_channel_inputs) == 'manual'


def get_input_metrics_summary(per_channel_inputs: Mapping[str, str]) -> Dict[str, int]:
    """Вернуть подсчёт каналов по типу input metric.

    Используется UI для отображения «4 канала в ₽, 3 канала в показах».

    Returns:
        Dict с keys 'monetary', 'physical' и count каждого.
    """
    summary = {'monetary': 0, 'physical': 0}
    for metric in per_channel_inputs.values():
        if metric in summary:
            summary[metric] += 1
    return summary


def derive_mode_with_explanation(
    per_channel_inputs: Mapping[str, str],
) -> Dict[str, str]:
    """Derive mode + plain-text объяснение для UI.

    Используется в `ModeDerivedExplanation.svelte` для отображения юзеру
    почему выведен такой mode.

    Returns:
        Dict с keys 'mode', 'explanation'.

    Examples:
        >>> result = derive_mode_with_explanation({'tv': 'monetary', 'olv': 'monetary'})
        >>> result['mode']
        'roi'
        >>> 'все каналы' in result['explanation'].lower()
        True
    """
    mode = derive_mode(per_channel_inputs)
    summary = get_input_metrics_summary(per_channel_inputs)
    n_monetary = summary['monetary']
    n_physical = summary['physical']
    total = n_monetary + n_physical

    if mode == 'roi':
        explanation = (
            f"Все {total} каналов измеряются в ₽-бюджетах. "
            f"Модель работает в режиме ROI — оценивает возврат на инвестицию (₽ выручки / ₽ затрат)."
        )
    elif mode == 'effectiveness':
        explanation = (
            f"Все {total} каналов измеряются в физических контактах (показы / клики / GRP). "
            f"Модель работает в режиме Эффективность — главная метрика сравнения каналов = доля в продажах. "
            f"Для cost-effectiveness анализа можно добавить ценники контактов (CPM/CPC/CPP)."
        )
    else:  # manual
        explanation = (
            f"Смешанный режим: {n_monetary} канала в ₽-бюджетах, {n_physical} канала в физических контактах. "
            f"Cross-channel сравнение через долю в продажах. "
            f"Для cost-effectiveness можно добавить ценники контактов на physical каналы (переход в virtual ROI)."
        )

    return {'mode': mode, 'explanation': explanation}
