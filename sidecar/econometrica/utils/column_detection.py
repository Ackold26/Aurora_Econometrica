"""
Aurora Econometrica - column auto-detection (v1.3.0).

Auto-classification колонок Excel/CSV по именам: monetary (бюджет в ₽) vs physical
(показы, клики, GRP). Used by ValidateStep / PerChannelInputSelector для smart defaults.

Per ADR-015 (Mode as derived state) - если auto-detect однозначно определяет тип,
PerChannelInputSelector скрыт (UI showns только при ambiguity).

Usage:
    from utils.column_detection import classify_columns, detect_available_metrics

    columns = ['tv_spend', 'tv_grp', 'olv_impressions', 'performance_clicks', 'sales_rub']
    classified = classify_columns(columns)
    # {'tv_spend': 'monetary', 'tv_grp': 'physical', 'olv_impressions': 'physical',
    #  'performance_clicks': 'physical', 'sales_rub': 'target_monetary'}

    available = detect_available_metrics(columns, channel_name='tv')
    # {'monetary': ['tv_spend'], 'physical': ['tv_grp']}

References:
- ADR-015 (Mode as derived state).
- AURORA_BUNDLE_v1.3.md (schema additive).
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

# Output classification type.
ColumnKind = Literal['monetary', 'physical', 'target_monetary', 'target_count', 'date', 'control', 'unknown']

# ─── Regex patterns (RU + EN, case-insensitive, separator-aware) ────────────

# Helper: pattern matches if surrounded by separator (_-space-hyphen) or start/end.
# Python `\b` word boundary НЕ работает между `_` и letter (оба word chars).
# Используем lookbehind+lookahead для (start|sep) + token + (sep|end|word_suffix).
_SEP = r'(?:^|(?<=[_\s\-]))'    # start of string OR preceded by sep
_END = r'(?=[_\s\-]|$)'         # followed by sep OR end of string


def _sep_pattern(token: str) -> str:
    """Wrap token с separator-aware boundaries для Cyrillic + underscore-prefixed names."""
    return _SEP + token + _END


# Money / budget / spend / cost. Matches: tv_spend, tv_budget, тв_бюджет, costs_tv,
# brand_spend_eur, ad_cost, маркетинг_бюджет, рекл_расходы.
MONETARY_PATTERNS = [
    _sep_pattern(r'spend(?:s|ing)?'),
    _sep_pattern(r'budget'),
    _sep_pattern(r'cost(?:s)?'),
    _sep_pattern(r'expense(?:s)?'),
    _sep_pattern(r'investment(?:s)?'),
    _sep_pattern(r'бюджет(?:ы|а|ов)?'),
    _sep_pattern(r'расход(?:ы|ов|а)?'),
    _sep_pattern(r'затрат(?:ы|а|ов)?'),
    _sep_pattern(r'стоимость'),
    _sep_pattern(r'трат(?:ы|а)?'),
    _sep_pattern(r'инвестиц(?:ии|ия|ий)'),
    # Currency markers в названии колонки = monetary.
    _sep_pattern(r'rub'),
    _sep_pattern(r'usd'),
    _sep_pattern(r'eur'),
    r'₽',  # currency symbol - matches anywhere.
]

# Physical metrics: impressions, clicks, visits, GRP, reach, views.
PHYSICAL_PATTERNS = [
    _sep_pattern(r'impression(?:s)?'),
    _sep_pattern(r'impr(?:s)?'),
    _sep_pattern(r'show(?:s|n)?'),
    _sep_pattern(r'view(?:s)?'),
    _sep_pattern(r'click(?:s)?'),
    _sep_pattern(r'visit(?:s)?'),
    _sep_pattern(r'session(?:s)?'),
    _sep_pattern(r'reach'),
    _sep_pattern(r'contact(?:s)?'),
    _sep_pattern(r'grp(?:s)?'),
    _sep_pattern(r'trp(?:s)?'),
    _sep_pattern(r'open(?:s|ed)?'),
    _sep_pattern(r'delivery'),
    _sep_pattern(r'delivered'),
    _sep_pattern(r'показ(?:ы|ов|а)?'),
    _sep_pattern(r'кликов?'),
    _sep_pattern(r'клики'),
    _sep_pattern(r'визит(?:ы|ов|а)?'),
    _sep_pattern(r'охват(?:ы|ом)?'),
    _sep_pattern(r'просмотр(?:ы|ов|а)?'),
    _sep_pattern(r'контакт(?:ы|ов|а)?'),
    _sep_pattern(r'аудитори(?:я|и|ей)'),
    _sep_pattern(r'трафик'),
    _sep_pattern(r'грп'),
    _sep_pattern(r'трп'),
    _sep_pattern(r'выдач(?:и|а|ам)?'),
]

# Target metrics - monetary (продажи в ₽, выручка, прибыль).
# Эти паттерны проверяются ДО MONETARY_PATTERNS - sales_rub имеет priority над `rub`.
TARGET_MONETARY_PATTERNS = [
    _sep_pattern(r'sales_rub'),
    _sep_pattern(r'sales_revenue'),
    _sep_pattern(r'revenue'),
    _sep_pattern(r'profit'),
    _sep_pattern(r'gmv'),
    _sep_pattern(r'gross_revenue'),
    _sep_pattern(r'sales_money'),
    # Note: bare 'sales' assumed monetary, но только если нет суффикса `_pack` / `_unit` / `_volume`.
    # Pattern matches `sales`, `sales_total`, etc. но не `sales_packs` (т.к. TARGET_COUNT_PATTERNS checked first).
    _sep_pattern(r'sales'),
    _sep_pattern(r'продаж(?:и|ь)_руб'),
    _sep_pattern(r'продаж(?:и|ь)_money'),
    _sep_pattern(r'выручка'),
    _sep_pattern(r'выручки'),
    _sep_pattern(r'выручке'),
    _sep_pattern(r'оборот'),
]

# Target metrics - count (продажи в штуках, лиды, регистрации).
# Проверяются ДО PHYSICAL_PATTERNS (sales_packs не должен попасть в physical).
TARGET_COUNT_PATTERNS = [
    _sep_pattern(r'sales_pack(?:s)?'),
    _sep_pattern(r'sales_unit(?:s)?'),
    _sep_pattern(r'sales_volume'),
    _sep_pattern(r'units_sold'),
    _sep_pattern(r'lead(?:s)?'),
    _sep_pattern(r'registration(?:s)?'),
    _sep_pattern(r'signup(?:s)?'),
    _sep_pattern(r'card(?:s)?_issued'),
    _sep_pattern(r'loyalty_card(?:s)?'),
    _sep_pattern(r'subscription(?:s)?'),
    _sep_pattern(r'install(?:s)?'),
    _sep_pattern(r'download(?:s)?'),
    _sep_pattern(r'продаж(?:и|ь)_шт'),
    _sep_pattern(r'продаж(?:и|ь)_упак'),
    _sep_pattern(r'упаков(?:ки|ок)?'),
    _sep_pattern(r'лид(?:ы|ов|а)?'),
    _sep_pattern(r'лиды'),
    _sep_pattern(r'регистрац(?:ии|ия|ий)'),
    _sep_pattern(r'подписк(?:а|и|ам)?'),
    _sep_pattern(r'подписки'),
    _sep_pattern(r'карт(?:а|ы|ам)?_выдан'),
    _sep_pattern(r'установк(?:а|и)?'),
    _sep_pattern(r'загрузк(?:а|и)?'),
]

# Date columns.
DATE_PATTERNS = [
    _sep_pattern(r'date'),
    _sep_pattern(r'day'),
    _sep_pattern(r'week'),
    _sep_pattern(r'month'),
    _sep_pattern(r'period'),
    _sep_pattern(r'time'),
    _sep_pattern(r'timestamp'),
    _sep_pattern(r'дата'),
    _sep_pattern(r'день'),
    _sep_pattern(r'недел(?:я|и|ю)?'),
    _sep_pattern(r'месяц'),
    _sep_pattern(r'период'),
    _sep_pattern(r'время'),
]


def _matches_any(text: str, patterns: List[str]) -> bool:
    """Test if text matches any regex pattern (case-insensitive)."""
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE | re.UNICODE):
            return True
    return False


def classify_column(column_name: str) -> ColumnKind:
    """Classify single column name → kind.

    Order of precedence:
    1. Date (наиболее однозначно).
    2. Target monetary (sales_rub, revenue).
    3. Target count (sales_packs, leads, registrations).
    4. Monetary input (budget, spend, cost).
    5. Physical input (impressions, clicks, GRP).
    6. Unknown.

    Args:
        column_name: имя колонки из Excel/CSV.

    Returns:
        ColumnKind.

    Examples:
        >>> classify_column('tv_spend')
        'monetary'
        >>> classify_column('olv_impressions')
        'physical'
        >>> classify_column('sales_packs')
        'target_count'
        >>> classify_column('date')
        'date'
        >>> classify_column('something_obscure')
        'unknown'
    """
    # Order matters: more specific patterns (target_count) checked before less specific (target_monetary)
    # чтобы 'sales_packs' классифицировался как count, не как monetary (где matches bare 'sales').
    if _matches_any(column_name, DATE_PATTERNS):
        return 'date'
    if _matches_any(column_name, TARGET_COUNT_PATTERNS):
        return 'target_count'
    if _matches_any(column_name, TARGET_MONETARY_PATTERNS):
        return 'target_monetary'
    if _matches_any(column_name, MONETARY_PATTERNS):
        return 'monetary'
    if _matches_any(column_name, PHYSICAL_PATTERNS):
        return 'physical'
    return 'unknown'


def classify_columns(column_names: List[str]) -> Dict[str, ColumnKind]:
    """Classify all columns в файле.

    Args:
        column_names: список имён колонок.

    Returns:
        Dict {column_name: ColumnKind}.
    """
    return {name: classify_column(name) for name in column_names}


def detect_available_metrics(
    column_names: List[str],
    channel_name: str,
) -> Dict[str, List[str]]:
    """Найти доступные monetary / physical метрики для конкретного канала.

    Соглашение naming: имя канала - префикс колонки (e.g. 'tv_spend', 'tv_grp').

    Args:
        column_names: все колонки в датасете.
        channel_name: имя канала (e.g. 'tv', 'olv', 'performance').

    Returns:
        Dict с keys 'monetary', 'physical' и lists соответствующих имён колонок.

    Examples:
        >>> cols = ['date', 'tv_spend', 'tv_grp', 'olv_impressions', 'sales_rub']
        >>> detect_available_metrics(cols, 'tv')
        {'monetary': ['tv_spend'], 'physical': ['tv_grp']}
        >>> detect_available_metrics(cols, 'olv')
        {'monetary': [], 'physical': ['olv_impressions']}
    """
    channel_lower = channel_name.lower()
    result: Dict[str, List[str]] = {'monetary': [], 'physical': []}

    for col in column_names:
        col_lower = col.lower()
        # Heuristic: канал - префикс или встречается в начале/средине.
        # Допускаем разделители _, -, пробел.
        # Pattern: channel_name + (_|-| ) + остаток.
        if not (col_lower.startswith(channel_lower) or f'_{channel_lower}' in col_lower):
            continue

        kind = classify_column(col)
        if kind == 'monetary':
            result['monetary'].append(col)
        elif kind == 'physical':
            result['physical'].append(col)

    return result


def has_ambiguous_channels(
    column_names: List[str],
    channels: List[str],
) -> bool:
    """True если хотя бы один канал имеет несколько типов метрик доступных.

    Используется UI: если все каналы have single available metric - PerChannelInputSelector
    скрыт; если хотя бы один ambiguous - показывается selector.

    Args:
        column_names: все колонки.
        channels: список имён каналов проекта.

    Returns:
        True if any channel has both monetary AND physical available.
    """
    for channel in channels:
        available = detect_available_metrics(column_names, channel)
        if available['monetary'] and available['physical']:
            return True
    return False


def suggest_default_input_metric(
    column_names: List[str],
    channels: List[str],
) -> Dict[str, str]:
    """Suggest default input metric per канал.

    Логика:
    - Если у канала есть только monetary → 'monetary'.
    - Если только physical → 'physical'.
    - Если оба - приоритет monetary (более точная по бюджету, обычно).
    - Если ни одного - 'monetary' default (fallback).

    Args:
        column_names: все колонки.
        channels: список имён каналов.

    Returns:
        Dict {channel: 'monetary'|'physical'}.

    Examples:
        >>> cols = ['date', 'tv_spend', 'olv_impressions', 'sales_rub']
        >>> suggest_default_input_metric(cols, ['tv', 'olv'])
        {'tv': 'monetary', 'olv': 'physical'}
    """
    defaults = {}
    for channel in channels:
        available = detect_available_metrics(column_names, channel)
        if available['monetary']:
            defaults[channel] = 'monetary'
        elif available['physical']:
            defaults[channel] = 'physical'
        else:
            defaults[channel] = 'monetary'  # fallback
    return defaults
