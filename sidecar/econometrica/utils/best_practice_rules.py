"""
Aurora Econometrica - best-practice recommendation rules (v2.0.0).

Per ADR-019: soft-recommendation library для wizard Step 3 (Media inputs confirm).
Surface warn-level warnings без блокировки model fitting.

Standard MMM methodology — каждый media format имеет «preferred» media metric:
- Performance / Search → клики (response indicator)
- Display / Banner advertising → показы (impressions)
- OLV (online video) → просмотры (views)
- TV → TRP (приведённые gross или net consistent)
- OOH → OTS (opportunity to see) / контакты
- Radio → reach + frequency
- Social → engagement (если есть) или impressions

Violation = soft warning, не блок. Customer free to override.

Reference:
- docs/v2_0_0_design/WIZARD_FLOW_v2_FINAL.md §1.2.4
- docs/v2_0_0_design/PRE_FLIGHT_FIXES.md N1
- Robyn / Meta MMM documentation на channel-specific best practices.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class BestPracticeWarning(TypedDict):
    """Schema of a best-practice warning."""
    channel: str
    detected_metric: str
    recommended_metric: str
    severity: str  # 'info' | 'warn'
    message: str


# ─── Best-practice rules table ─────────────────────────────────────────────
# Each rule: {media_format → preferred_metric → severity если violated}

PREFERRED_METRICS_BY_FORMAT: Dict[str, Dict[str, str]] = {
    'performance': {
        'preferred': 'clicks',
        'acceptable': ['clicks', 'conversions'],
        'discouraged': ['impressions', 'views'],
        'severity_violation': 'warn',
        'rationale': 'Performance каналы measure response через клики (action indicator), '
                     'не показы (awareness indicator). Использование показов снижает точность '
                     'attribution для performance каналов.',
    },
    'olv': {
        'preferred': 'views',
        'acceptable': ['views', 'completed_views', 'vtr_50', 'vtr_75'],
        'discouraged': ['clicks', 'impressions'],
        'severity_violation': 'warn',
        'rationale': 'OLV (online video) measure эффективность через completed views '
                     '(50%+ duration). Клики на видео часто misleading, показы (impressions) '
                     'over-count т.к. включают скрытые / fast-scroll.',
    },
    'digital': {  # Display / banner advertising
        'preferred': 'impressions',
        'acceptable': ['impressions', 'viewability_impressions'],
        'discouraged': ['clicks'],
        'severity_violation': 'warn',
        'rationale': 'Display advertising (banners) measure reach + frequency через '
                     'impressions. Click-through rate на больших баннерах низкая и noisy — '
                     'клики не репрезентативны для response.',
    },
    'tv': {
        'preferred': 'trp',
        'acceptable': ['trp', 'grp'],
        'discouraged': ['impressions', 'reach', 'spots'],
        'severity_violation': 'info',  # less strict — TRP/GRP industry standard
        'rationale': 'TV TRP (Target Rating Points) — стандарт РФ медиабаинга. TRP должны '
                     'быть приведёнными (gross или net — consistent). Использование reach или '
                     'spots без TRP лишает модель temporal scale.',
    },
    'ooh': {
        'preferred': 'ots',  # opportunity to see
        'acceptable': ['ots', 'contacts', 'reach'],
        'discouraged': ['impressions', 'spend'],
        'severity_violation': 'warn',
        'rationale': 'OOH (наружная реклама) measure через OTS (opportunity to see) или '
                     'контакты. Impressions для outdoor — устаревший термин, не отражает '
                     'реальный exposure.',
    },
    'radio': {
        'preferred': 'reach',
        'acceptable': ['reach', 'frequency', 'grp'],
        'discouraged': ['clicks'],
        'severity_violation': 'warn',
        'rationale': 'Radio measure через reach × frequency (или GRP). Клики не применимы.',
    },
    'social': {
        'preferred': 'impressions',
        'acceptable': ['impressions', 'engagement', 'reach', 'clicks'],
        'discouraged': [],
        'severity_violation': 'info',  # social — flexible
        'rationale': 'Social media metrics зависят от формата (engagement для blogger '
                     'integration, impressions для paid social).',
    },
}

# Common metric aliases для detection
METRIC_ALIASES = {
    'impressions': ['impressions', 'imps', 'impr', 'показы', 'views_total'],
    'clicks': ['clicks', 'click', 'клики', 'ctr_clicks', 'paid_clicks'],
    'views': ['views', 'просмотры', 'video_views', 'completed_views', 'vtr'],
    'trp': ['trp', 'trps', 'трп', 'target_rating_points'],
    'grp': ['grp', 'grps', 'грп', 'gross_rating_points'],
    'ots': ['ots', 'opportunity_to_see', 'contacts', 'контакты'],
    'reach': ['reach', 'охват', 'unique_reach'],
    'spend': ['spend', 'budget', 'cost', 'бюджет', 'расход'],
    'conversions': ['conversions', 'конверсии', 'goals'],
}


def _normalize_metric(metric_name: str) -> str:
    """Normalize metric column name → canonical metric type."""
    name_lower = metric_name.lower()
    for canonical, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            if alias in name_lower:
                return canonical
    return name_lower


def check_channel_best_practice(
    channel_name: str,
    media_format: str,
    detected_metric: str,
) -> Optional[BestPracticeWarning]:
    """Check single channel против best-practice rule.

    Args:
        channel_name: имя канала (e.g., 'performance_search').
        media_format: detected media format (per `detect_media_format`).
        detected_metric: detected metric type (e.g., 'clicks', 'impressions').

    Returns:
        BestPracticeWarning if violation, else None.

    Examples:
        >>> check_channel_best_practice('olv_pre_roll', 'olv', 'clicks')
        {'channel': 'olv_pre_roll', 'detected_metric': 'clicks',
         'recommended_metric': 'views', 'severity': 'warn',
         'message': 'Для OLV...'}
        >>> check_channel_best_practice('tv_brand', 'tv', 'trp')
        None  # ok
    """
    rule = PREFERRED_METRICS_BY_FORMAT.get(media_format)
    if rule is None:
        return None  # No rule для этого format

    normalized_metric = _normalize_metric(detected_metric)
    if normalized_metric in rule['acceptable']:
        return None  # Acceptable

    if normalized_metric in rule['discouraged']:
        return {
            'channel': channel_name,
            'detected_metric': detected_metric,
            'recommended_metric': rule['preferred'],
            'severity': rule['severity_violation'],
            'message': (
                f'Канал «{channel_name}» ({media_format}) использует «{detected_metric}», '
                f'рекомендуем «{rule["preferred"]}». {rule["rationale"]}'
            ),
        }

    # Unknown metric — info level
    return {
        'channel': channel_name,
        'detected_metric': detected_metric,
        'recommended_metric': rule['preferred'],
        'severity': 'info',
        'message': (
            f'Канал «{channel_name}» использует «{detected_metric}», '
            f'стандарт для {media_format} — «{rule["preferred"]}».'
        ),
    }


def check_all_channels(
    channels_info: List[Dict[str, str]],
) -> List[BestPracticeWarning]:
    """Check all channels против best-practice rules.

    Args:
        channels_info: list of {'channel': name, 'format': media_format, 'metric': detected}.

    Returns:
        List of warnings (empty if все каналы по best-practice).

    Examples:
        >>> channels = [
        ...     {'channel': 'olv_youtube', 'format': 'olv', 'metric': 'clicks'},
        ...     {'channel': 'tv_brand', 'format': 'tv', 'metric': 'trp'},
        ... ]
        >>> check_all_channels(channels)
        [{'channel': 'olv_youtube', ...}]  # only olv warning
    """
    warnings = []
    for info in channels_info:
        warning = check_channel_best_practice(
            channel_name=info['channel'],
            media_format=info['format'],
            detected_metric=info['metric'],
        )
        if warning is not None:
            warnings.append(warning)
    return warnings


def check_mode_consistency(
    channels_input_types: Dict[str, str],
    kpi_kind: str,
) -> Optional[BestPracticeWarning]:
    """Mixed mode + monetary KPI = warn про conversion uncertainty.

    Per INV-30: смешанные единицы media inputs + monetary KPI требуют unit_costs
    ставок, точность ROI ±10-25%. Рекомендуем единый режим.

    Args:
        channels_input_types: {channel: 'monetary' | 'physical'}.
        kpi_kind: 'monetary' | 'count'.

    Returns:
        Warning if mixed input types AND monetary KPI, else None.
    """
    has_monetary = any(t == 'monetary' for t in channels_input_types.values())
    has_physical = any(t == 'physical' for t in channels_input_types.values())

    if has_monetary and has_physical and kpi_kind == 'monetary':
        return {
            'channel': '__all__',
            'detected_metric': 'mixed',
            'recommended_metric': 'single_unit',
            'severity': 'warn',
            'message': (
                'Смешанные единицы media inputs + monetary KPI = mixed mode (Expert only). '
                'Точность ROI зависит от unit_costs ставок (±10-25% дополнительной uncertainty). '
                'Рекомендуем выбрать единый режим — либо все каналы в ₽ (ROI mode), либо все в '
                'физических метриках (Эффективность mode).'
            ),
        }

    return None


def check_trp_normalization_hint(
    channels_info: List[Dict[str, str]],
) -> Optional[BestPracticeWarning]:
    """Detect TV channels с TRP metric — рекомендация про приведённые TRP.

    TV TRP должны быть приведёнными (gross или net consistent across history).
    Customer часто mixes gross + net данные — wizard добавляет hint.

    Args:
        channels_info: list of {'channel', 'format', 'metric'}.

    Returns:
        Info warning если detected TV channels с TRP.
    """
    tv_channels_with_trp = [
        info['channel']
        for info in channels_info
        if info['format'] == 'tv' and _normalize_metric(info['metric']) in ('trp', 'grp')
    ]

    if tv_channels_with_trp:
        return {
            'channel': ', '.join(tv_channels_with_trp),
            'detected_metric': 'trp',
            'recommended_metric': 'trp_normalized',
            'severity': 'info',
            'message': (
                f'TV каналы с TRP detected: {", ".join(tv_channels_with_trp)}. '
                f'Убедитесь что TRP приведённые (gross OR net, consistent across history). '
                f'Mixing gross+net TRP даёт scale artifacts в модели.'
            ),
        }

    return None
