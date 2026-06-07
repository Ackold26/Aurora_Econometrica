"""SSOT набора факторов timeline-декомпозиции (INV-50, аудит #12).

Источник истины «какие факторы и как показывать на графике динамики продаж»
исторически жил ТОЛЬКО во фронте (ChannelTimeline.svelte). Отчёты (HTML/PPTX/
XLSX) этот набор не воспроизводили → показывали лишь медиа, теряя контроли /
конкурентов / праздники (программа ≠ отчёт).

Этот модуль вычисляет набор ОДИН раз в backend, чтобы и программа, и все
билдеры отчётов читали один результат (см. feedback_single_source_of_truth_
for_displayed_metrics). Логика отбора/знака — дословный порт ChannelTimeline:

  • показываются факторы type ∈ signed_* | holiday;
  • positive_control (запросы, дистрибуция, trade) сворачивается в baseline
    (отдельным фактором НЕ показывается — noise-like);
  • знак (above/below zero) определяется по СРЕДНЕМУ per_period (не по value,
    округление до -0.0 ломало detection — пилот 2026-05-16);
  • для отрицательных факторов baseline «очищается» (baseline -= per_period),
    чтобы они рисовались ниже нуля без двойного счёта.

Чтобы не дублировать тяжёлые per_period-массивы (они уже лежат в
time_series.channels и signed_factor_contributions), структура несёт только
ПРОИЗВОДНОЕ: baseline_adjusted + порядок медиа + метаданные факторов
{name, type, group_label, sign}. Рендерер берёт per_period по name из
существующих полей decomposition.json.
"""
from __future__ import annotations

# Зеркало ChannelTimeline.svelte: FACTOR_LABELS + SIGNED types.
SIGNED_TYPES = frozenset({'signed_competitor', 'signed_price', 'signed_weather', 'signed_macro'})

GROUP_LABELS = {
    'signed_competitor': 'Конкуренты',
    'signed_price': 'Цена',
    'signed_weather': 'Погода',
    'signed_macro': 'Макро-факторы',
    'holiday': 'Праздники',
    'positive_control': 'Внешние факторы',
}


def build_timeline_factors(
    baseline: list | None,
    ts_channels: dict | None,
    signed_factor_contributions: dict | None,
) -> dict:
    """Вернуть SSOT-структуру факторов timeline.

    Args:
        baseline: per-period baseline (time_series.baseline).
        ts_channels: {channel_name: per_period[]} (time_series.channels).
        signed_factor_contributions: {col_name: {value, type, per_period[], ...}}.

    Returns:
        {
          'baseline_adjusted': [float, ...],   # baseline без отриц. факторов
          'media_order': [name, ...],          # порядок стека медиа
          'factors': [                          # signed_*/holiday, в порядке sfc
            {'name': str, 'type': str, 'group_label': str,
             'sign': 'positive'|'negative'},
          ],
        }
    """
    baseline_adj = [float(v or 0.0) for v in (baseline or [])]
    n = len(baseline_adj)
    media_order = [str(name) for name in (ts_channels or {}).keys()]

    factors: list[dict] = []
    for col_name, f in (signed_factor_contributions or {}).items():
        if not isinstance(f, dict):
            continue
        pp = f.get('per_period')
        if not isinstance(pp, list) or not pp:
            continue
        t = str(f.get('type', 'positive_control'))
        if t not in SIGNED_TYPES and t != 'holiday':
            # positive_control → остаётся внутри baseline (как ChannelTimeline).
            continue
        ppf = [float(v or 0.0) for v in pp]
        mean = sum(ppf) / len(ppf) if ppf else 0.0
        sign = 'negative' if mean < 0 else 'positive'
        if sign == 'negative':
            # «Вынести» из baseline, чтобы рисовать ниже нуля без двойного счёта.
            for i in range(min(n, len(ppf))):
                baseline_adj[i] -= ppf[i]
        factors.append({
            'name': str(col_name),
            'type': t,
            'group_label': GROUP_LABELS.get(t, 'Внешние факторы'),
            'sign': sign,
        })

    return {
        'baseline_adjusted': baseline_adj,
        'media_order': media_order,
        'factors': factors,
    }


def resolve_timeline_factors(decompose: dict | None) -> dict:
    """Вернуть timeline_factors из decomposition: готовое поле либо пересчёт
    на лету для legacy-проектов без него (backfill без ретрейна/ре-декомпозиции).

    Builders отчётов вызывают это, чтобы старые decomposition.json (116 проектов,
    созданных до аудита #12) тоже показывали полный набор факторов.
    """
    decompose = decompose or {}
    tf = decompose.get('timeline_factors')
    if isinstance(tf, dict) and ('factors' in tf or 'baseline_adjusted' in tf):
        return tf
    ts = decompose.get('time_series') or {}
    return build_timeline_factors(
        ts.get('baseline'), ts.get('channels'),
        decompose.get('signed_factor_contributions'),
    )
