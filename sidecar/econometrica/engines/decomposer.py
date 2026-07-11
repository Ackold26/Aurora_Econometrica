"""
Sales decomposition engine.
Breaks down total sales into baseline + channel contributions.

P0-3/4/10 fix (math-fix-v1.0.13, Phase 3):
Pre-fix: contribution = |β|/Σ|β| × (total - baseline) → ignored adstock,
saturation, time. Baseline = sum(actual - predicted) + 0.3 × predicted.mean × n.
Post-fix: contribution_per_period = β × hill(adstock(x)/mean) × y_std.
Baseline = intercept × y_std + y_mean × n + control_effect × y_std.
"""
import json
import logging
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any

# AUD-01 fix (rc2): logger ранее использовался в exception handlers без объявления
# на уровне модуля → NameError при срабатывании except path. Объявляем явно.
logger = logging.getLogger('econometrica')

from utils.adstock import apply_adstock, geometric_adstock_batch
from utils.saturation import hill_function, hill_function_batch, hill_function_batch_2d
from utils.posterior_propagation import (
    compute_ci_hdi,
    load_posterior_samples,
    per_channel_samples,
)


# Hybrid ROI thresholds (Phase 0.2 - plan immutable-bouncing-noodle §0.2, L4).
# Calibration sources documented в docs/ROI_THRESHOLDS.md.
ROI_DEEP_LOSS = 0.5         # < 0.5× = глубоко убыточный
ROI_LOSS = 0.8              # < 0.8× = убыточный
ROI_BREAKEVEN = 1.0         # < 1.0× = на грани окупаемости
ROI_HIGH_ABS = 5.0          # > 5× = высокоэффективен (small-N absolute fallback)
ROI_UNIT_SMELL_FLOOR = 50.0 # > 50× при unit_smell = "не рубли?" (preserved)
ROI_ARTIFACT = 100.0        # > 100× = artifact warning (regardless of unit_smell)
GAP_OVERSAT = -10.0         # пп - перенасыщен
GAP_UNDER = -5.0            # пп - слабее своей доли
GAP_HIGH = 10.0             # пп - высокоэффективен по share
GAP_GOOD = 5.0              # пп - эффективен по share
QUANTILE_MIN_N = 20         # ниже - relative quantile mode disabled


def _fmt_roi(r) -> str:
    """ROI с честной точностью: |ROI|<1 → 2 знака (0.04× не «0.0×»), иначе 1 знак.
    Иначе 0.04× и 0.02× оба печатались «0.0×» → инсайт выглядел противоречиво."""
    try:
        r = float(r or 0)
    except (TypeError, ValueError):
        return '0×'
    return f"{r:.2f}×" if abs(r) < 1 else f"{r:.1f}×"


def _build_channel_insight(
    channels,
    money_roi_unavailable: bool = False,
    kpi_kind: str = 'monetary',
    kpi_type=None,
    derived_mode: str = 'roi',
) -> str:
    """SSOT инсайта «лучший/худший канал» (template, 0 токенов).

    REC-1-GAP (2026-06-03): channels отсортированы по ROI убыв.; channels[0] —
    не-денежный unit_smell-канал (TRP/clicks, ROI-артефакт), если есть. НЕ
    короновать его. Берём лучший среди денежных (clean); fallback если все unit_smell.

    INV-50 (2026-06-03 synthetic-truth аудит): если ЛУЧШИЙ денежный канал сам
    убыточен (ROI < ROI_BREAKEVEN), НЕ называть его «самым эффективным» — это
    прямо противоречит его же вердикту «убыточный/глубоко убыточный» и проецирует
    ложную уверенность (на синтетике с медиа-сигналом ~5% движок честно даёт ROI
    ~0.04× при широких интервалах, но инсайт короновал «самый эффективный (ROI 0.0×)»).
    Также НЕ советовать перераспределять бюджет в убыточный top (та же ROI-1/2 проблема).

    INV-50 (2026-06-06 synthetic-truth retail probe): когда money ROI недоступен
    (`money_roi_unavailable` — count-KPI без kpi_unit_cost), per-channel ROI =
    нативное отношение (упак/₽, визиты/шт) — НЕсопоставимо между каналами разных
    единиц и НЕ является money-«×». Короновать «самый эффективный (ROI X×)» здесь =
    ложная уверенность, противоречащая вердиктам каналов «Задайте ценность единицы».
    REC-1-GAP clean-фильтр детектит unit_smell ПО ИМЕНИ (UNIT_HINTS) и пропускает
    non-money каналы без unit-keyword (binary promo_indicator: spend=9, unit_cost=1 →
    ROI-артефакт 50976× проходил clean и короновался, хотя движок САМ флагнул roi_max
    high-severity). Гейт на money_roi_unavailable закрывает обход независимо от имени.

    KPI-aware форматирование (feat/econ-kpi-units, 2026-07-11):
    - monetary/roi: «ROI X×» — поведение как раньше.
    - count/roi: метка «CPU», format_metric инвертирует ratio → ₽/ед. или ₽/лид.
    - effectiveness: «доля канала в эффекте X%», без «ROI»/«окупается».

    @param channels: list dict с name/roi/efficiency_gap/unit_smell, sorted by ROI desc.
    @param money_roi_unavailable: True если ROI семантически нативное отношение (count
        KPI без kpi_unit_cost) — тогда ранжирование/коронование по ROI невалидно.
    @param kpi_kind: 'monetary' (default) | 'count' | 'effectiveness' — управляет
        словарём и форматированием метрики.
    @param kpi_type: конкретный тип KPI ('leads'|'sales_packs'|...) для паспортных
        подписей (format_metric → cpu_per_label). None — backward-compat.
    @param derived_mode: 'roi' | 'effectiveness' | 'manual' — режим расчёта.
        'effectiveness' меняет словарь на «доля эффекта».
    @returns insight-строка (или '' если нет каналов).
    """
    from utils.kpi_labels import format_metric  # локальный импорт — избегаем circular на уровне модуля

    if not channels:
        return ''

    # Нормализуем effective_mode: effectiveness доминирует над kpi_kind
    _eff_mode = (derived_mode == 'effectiveness')

    if money_roi_unavailable and not _eff_mode:
        return (
            'Денежный ROI каналов недоступен: задайте «ценность единицы» KPI для '
            'money-оценки эффективности. Продажи определяются в основном базовым '
            'спросом, прямой медиа-вклад невелик. Сценарии перераспределения '
            'см. в шаге «Оптимизация».'
        )
    # REC-1-GAP + F-C-extended (аудит 2026-06-06): из коронования исключаем И unit_smell-
    # каналы (name-based, TRP/clicks), И ROI-артефакты (roi >= ROI_ARTIFACT 100×) —
    # НЕЗАВИСИМО от kpi_kind. Артефактный «ROI 50000×» (binary/индикаторный канал
    # unit_cost=1 без unit-hint в имени) коронoвался на МОНЕТАРНОМ пути, где гейт
    # money_roi_unavailable выше молчит (False) и name-based unit_smell промахивается —
    # та же контрадикция «инсайт коронует / движок флагнул roi_max-артефакт», что F-C.
    clean = [c for c in channels if not c.get('unit_smell') and float(c.get('roi') or 0) < ROI_ARTIFACT]
    top = clean[0] if clean else None
    worst = channels[-1]
    if top is None:
        # Все каналы — unit_smell / ROI-артефакты → нет сопоставимого «самого эффективного».
        return (
            'Прямой медиа-вклад невелик: продажи определяются в основном базовым спросом. '
            'Точную оценку отдачи и сценарии перераспределения см. в шаге «Оптимизация».'
        )
    top_roi = float(top.get('roi') or 0)

    # Форматирование метрики и словарь зависят от режима
    if _eff_mode:
        # Effectiveness: доля ВКЛАДА канала в эффект (share_of_effect / contribution_pct),
        # НЕ ROI. Ранжируем по доле, а не по roi (roi для effectiveness невалиден — прогон
        # roi через format_metric дал бы roi×100, т.е. бессмысленные «250% доли»).
        def _share(c):
            return float(c.get('contribution_pct') or c.get('share_of_effect') or 0)
        top_share_ch = max(channels, key=_share)
        worst_share_ch = min(channels, key=_share)
        insight = (
            f"{top_share_ch['name']} - наибольшая доля эффекта ({_share(top_share_ch):.1f}%). "
            f"{worst_share_ch['name']} - наименьшая доля эффекта ({_share(worst_share_ch):.1f}%)."
        )
    elif kpi_kind == 'count':
        # Count/CPU: метка CPU, format_metric инвертирует ratio
        fmt_top = format_metric(top_roi, kpi_kind='count', mode='roi', kpi_type=kpi_type)
        fmt_worst = format_metric(float(worst.get('roi') or 0), kpi_kind='count', mode='roi', kpi_type=kpi_type)
        if top_roi >= ROI_BREAKEVEN:
            insight = (
                f"{top['name']} - самый эффективный канал (CPU {fmt_top}). "
                f"{worst['name']} - наименее эффективный (CPU {fmt_worst})."
            )
            if top.get('efficiency_gap', 0) > GAP_GOOD and worst.get('efficiency_gap', 0) < -GAP_GOOD:
                insight += (
                    f" Канал {worst['name']} использует больше бюджета чем даёт эффекта "
                    f"(gap {worst['efficiency_gap']:+.0f} пп) - рассмотрите перераспределение "
                    f"в {top['name']}. Точную оценку прироста см. в шаге «Оптимизация»."
                )
        else:
            # INV-50 для count: честная формулировка без «окупается»/«ROI»
            if money_roi_unavailable:
                no_roi_phrase = 'стоимость привлечения выше ценности единицы'
            else:
                no_roi_phrase = 'относительно высокая стоимость привлечения'
            insight = (
                f"Каналы показывают {no_roi_phrase} (лучший - {top['name']}, "
                f"CPU {fmt_top}). Точную оценку и сценарии перераспределения "
                f"см. в шаге «Оптимизация»."
            )
    else:
        # Monetary: поведение как раньше (ROI ×)
        if top_roi >= ROI_BREAKEVEN:
            insight = (
                f"{top['name']} - самый эффективный канал (ROI {_fmt_roi(top['roi'])}). "
                f"{worst['name']} - наименее эффективный (ROI {_fmt_roi(worst['roi'])})."
            )
            if top.get('efficiency_gap', 0) > GAP_GOOD and worst.get('efficiency_gap', 0) < -GAP_GOOD:
                insight += (
                    f" Канал {worst['name']} использует больше бюджета чем даёт эффекта "
                    f"(gap {worst['efficiency_gap']:+.0f} пп) - рассмотрите перераспределение "
                    f"в {top['name']}. Точную оценку прироста см. в шаге «Оптимизация»."
                )
        else:
            # INV-50: лучший канал сам не окупается → честная формулировка без «эффективный».
            insight = (
                f"Ни один канал не окупается напрямую (лучший - {top['name']}, "
                f"ROI {_fmt_roi(top['roi'])}). Продажи определяются в основном базовым "
                f"спросом, прямой медиа-вклад невелик. Точную оценку отдачи и сценарии "
                f"перераспределения см. в шаге «Оптимизация»."
            )
    return insight


def compute_roi_verdict(
    roi: float,
    efficiency_gap: float,
    *,
    category: str = 'mixed',
    unit_smell: bool = False,
    roi_ci_low: float | None = None,
    roi_ci_high: float | None = None,
    n_channels: int = 0,
    category_quantiles: dict[str, dict[str, float]] | None = None,
    money_roi_unavailable: bool = False,
) -> tuple[str, str]:
    """Hybrid ROI verdict combining absolute + relative + posterior CI.

    Per plan immutable-bouncing-noodle §0.2 (L4 fix), and L2 (math-fix v1.4
    Section C, 2026-04-29) re-ordering:

      Pre-fix (L4): Step 1 - wide CI → 'Высокая неопределённость' (suppressed
        ALL informative labels на small-N data - customer never saw «Перенасыщен»
        / «Высокоэффективен» when CI was wide regardless of point estimate).
      Post-fix (L2): wide CI → suffix « (низкая уверенность)» appended к
        existing label. Keeps informative descriptive verdict (mROAS-derived)
        while honestly disclosing CI uncertainty. Customer sees full picture.

    Order:
      Step 1 - posterior uncertainty flag (computed, applied at end as suffix)
      Step 2 - absolute hard caps (artifact/glubokaya-ubitochnost regardless of category)
      Step 3 - relative quantile (only if N ≥ 20 portfolio data + category mapping)
      Step 4 - efficiency gap fallback (small-N safe per-channel)

    Args:
      roi: канальный ROI (contribution_money / spend_money), unitless.
      efficiency_gap: share_of_effect - share_of_spend (пп).
      category: 'brand_reach' / 'performance' / 'mixed' (для quantile lookup).
      unit_smell: True если канал в TRP/clicks/impressions (не деньги) и unit_cost=1.
      roi_ci_low, roi_ci_high: posterior 90% CI bounds (Phase 1.9 - пока None).
      n_channels: total channels в выборке (для quantile-mode gating).
      category_quantiles: {category: {p10, p25, p75, p90}} portfolio benchmarks.

    Returns:
      (verdict_label, verdict_tone) where tone ∈ {good, warn, bad, neutral}.
    """
    # v2.1.0 (pilot B P0/B-02 2026-05-17): для count KPI без kpi_unit_cost
    # roi = contribution_count / spend_money (size 1/CPU, не money ratio).
    # ROI thresholds в этом fn семантически = money-ratio (₽/₽), поэтому
    # native count ROI почти всегда < 0.5 → false-positive «Глубоко убыточный»
    # для всех каналов. Honest reject: вывод «Не определён» + tone neutral,
    # инструкция задать ценность единицы для proper verdicts.
    if money_roi_unavailable:
        return ('Задайте ценность единицы для оценки', 'neutral')

    # Step 1 (L2 refactor): compute wide-CI flag для последующего suffix.
    # Pre-fix: this was the FIRST gate suppressing all informative labels.
    # Post-fix: descriptive verdict computed first, CI uncertainty added как
    # honest disclosure suffix (customer sees what AND how confident).
    wide_ci = (
        roi_ci_low is not None
        and roi_ci_high is not None
        and roi > 0
        and (roi_ci_high - roi_ci_low) > roi
    )

    def _apply_ci_suffix(label, tone):
        # Подпись смягчена 2026-05-02: было "(низкая уверенность)" - эмоционально
        # воспринималось как недоверие модели целиком (особенно когда R²/MAPE отличные).
        # Стало "(широкий ROI-интервал)" - нейтральное техническое описание:
        # ROI следует трактовать как диапазон, не как точное число. Качество модели
        # оценивается отдельно через R² / MAPE / R-hat (см. Эксперт-панель Train).
        if wide_ci:
            return (f"{label} (широкий ROI-интервал)", 'warn' if tone == 'good' else tone)
        return (label, tone)

    # Step 2 - absolute hard caps (regardless of category)
    if roi > ROI_UNIT_SMELL_FLOOR and unit_smell:
        return _apply_ci_suffix('ROI завышен (не рубли?)', 'warn')
    if roi > ROI_ARTIFACT:
        return _apply_ci_suffix('ROI нереалистичен (артефакт)', 'warn')
    if roi < ROI_DEEP_LOSS:
        return _apply_ci_suffix('Глубоко убыточный', 'bad')
    if roi < ROI_LOSS:
        return _apply_ci_suffix('Убыточный', 'bad')
    if roi < ROI_BREAKEVEN:
        return _apply_ci_suffix('На грани окупаемости', 'warn')

    # Step 3 - category-relative quantile (gated by min N)
    if (
        n_channels >= QUANTILE_MIN_N
        and category_quantiles
        and category in category_quantiles
    ):
        q = category_quantiles[category]
        p10 = q.get('p10')
        p25 = q.get('p25')
        p75 = q.get('p75')
        p90 = q.get('p90')
        if p10 is not None and roi < p10:
            return _apply_ci_suffix('Bottom-10% по категории', 'bad')
        if p90 is not None and roi >= p90:
            return _apply_ci_suffix('Top-10% по категории', 'good')
        if p75 is not None and roi >= p75:
            return _apply_ci_suffix('Top-25% по категории', 'good')
        if p25 is not None and roi < p25:
            return _apply_ci_suffix('Bottom-25% по категории', 'warn')
        return _apply_ci_suffix('Средний по категории', 'neutral')

    # Step 4 - efficiency gap fallback (per-channel small-N safe)
    if roi > ROI_HIGH_ABS and not unit_smell:
        return _apply_ci_suffix('Высокоэффективен', 'good')
    if efficiency_gap <= GAP_OVERSAT:
        return _apply_ci_suffix('Перенасыщен', 'warn')
    if efficiency_gap <= GAP_UNDER:
        return _apply_ci_suffix('Слабее своей доли', 'warn')
    if efficiency_gap >= GAP_HIGH:
        return _apply_ci_suffix('Высокоэффективен', 'good')
    if efficiency_gap >= GAP_GOOD:
        return _apply_ci_suffix('Эффективен', 'good')
    return _apply_ci_suffix('Сбалансирован', 'neutral')


def _load_v13_kpi_settings(project_path) -> dict:
    """v1.3.0 (ADR-017): load KPI settings from project state file.

    Looks для settings/v13_kpi.json в проекте. Returns empty dict если file
    отсутствует (legacy v1.2 проект). Backward compat: defaults injected
    в memory при дальнейшей dispatch.

    Audit fix v1.3.0 (red-team review): explicit logging при corrupted JSON
    - silent swallow прятал data corruption.
    """
    settings_file = project_path / 'settings' / 'v13_kpi.json'
    if not settings_file.exists():
        return {}
    try:
        import json as _json
        with open(settings_file, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except (OSError, ValueError) as e:
        # JSON corrupted / read error - log + fallback to defaults.
        import logging as _logging
        _logging.getLogger('econometrica').warning(
            f"v1.3 KPI settings file {settings_file} corrupted "
            f"({type(e).__name__}: {e}). Falling back to monetary defaults."
        )
        return {}


def _resolve_output_kpi_meta(v13_kpi: dict, kpi_kind: str, kpi_unit_cost, derived_mode_default: str = 'roi', kpi_type: str | None = None) -> dict:
    """Выходные kpi-метаданные decompose (kpi_kind/derived_mode/value_per_count_unit/kpi_type).

    F-A (synthetic-truth аудит 2026-06-06): `v13_kpi.json` НЕ создаётся (dead-save path,
    handleContinue мёртв — см. LOAD-1) → раньше эти поля дефолтили в monetary/roi/None
    ВНЕ ЗАВИСИМОСТИ от обученной модели. narrative_adapter:818 читает их из decompose
    result → PPTX/HTML мислейблили count-KPI экспорт как monetary/₽/ROI. Источник истины =
    pickle: `kpi_kind` резолвится из train-конфига kpi_type (decompose:405-429),
    `value_per_count_unit` = kpi_unit_cost (train/override), `derived_mode` берётся из
    `model_data['derived_mode']` (persistence вычисляет из per_channel_input; для count-KPI
    в effectiveness-режиме = 'effectiveness' — иначе labels врут «CPU ₽/ед.» вместо «Доля %»).
    v13_kpi сохраняет ПРИОРИТЕТ-override на случай, если save-path когда-то оживёт.

    @param v13_kpi: содержимое v13_kpi.json (обычно {} — dead path).
    @param kpi_kind: внутренне разрешённый kind ('count'|'monetary') из pickle kpi_type.
    @param kpi_unit_cost: разрешённая ₽-ценность единицы (pickle/override) или None.
    @param derived_mode_default: реальный derived_mode из pickle model_data ('roi'|
        'effectiveness'|'manual'); fallback 'roi' если отсутствует.
    @param kpi_type: конкретный тип KPI из pickle config ('leads'|'sales_packs'|...) или None.
        Фаза 1a: протаскивается в output для паспортных подписей (kpi_labels/kpi_helpers).
    """
    return {
        'kpi_kind': v13_kpi.get('kpi_kind', kpi_kind),
        'derived_mode': v13_kpi.get('derived_mode', derived_mode_default or 'roi'),
        'value_per_count_unit': v13_kpi.get('value_per_count_unit', kpi_unit_cost),
        'value_per_count_unit_label': v13_kpi.get('value_per_count_unit_label', ''),
        'kpi_type': kpi_type,
    }


# Типы signed-факторов, которые выносятся ОТДЕЛЬНЫМИ полосами в timeline-
# декомпозиции (и в программе, и во ВСЕХ отчётах). positive_control
# (запросы/дистрибуция) остаётся внутри baseline (noise-like, не интересен
# отдельно — поведение зеркалит ChannelTimeline.svelte).
_BREAKOUT_TYPES = frozenset({
    'signed_competitor', 'signed_price', 'signed_weather', 'signed_macro', 'holiday',
    'seasonality', 'category',
})
_FACTOR_GROUP_LABELS = {
    'signed_competitor': 'Конкуренты',
    'signed_price': 'Цена',
    'signed_weather': 'Погода',
    'signed_macro': 'Макро-факторы',
    'holiday': 'Праздники',
    'seasonality': 'Сезонность',
    'category': 'Категория',
}

# Верхний уровень 4 групп декомпозиции (решение Антона 2026-07-04): свёртка
# per-factor групп в 4 полосы верхнего уровня для drill-down UI и отчётов.
# БАЗА (базовая линия + сезонность + праздники) · МЕДИА · ВНЕШНИЕ ФАКТОРЫ
# (цена/погода/макро/дистрибуция/категория) · КОНКУРЕНТЫ (отдельная 4-я полоса).
# Методология: Jin 2017 (аддитивная декомпозиция), Wang&Jin §5.2 (конкуренты =
# отдельные control variables), Chan&Perry §4.2.2 (сезонность = контроль спроса).
_TOP_GROUP_MAP = {
    'База': 'БАЗА',
    'Сезонность': 'БАЗА',
    'Праздники': 'БАЗА',
    'Медиа': 'МЕДИА',
    'Цена': 'ВНЕШНИЕ ФАКТОРЫ',
    'Погода': 'ВНЕШНИЕ ФАКТОРЫ',
    'Макро-факторы': 'ВНЕШНИЕ ФАКТОРЫ',
    'Дистрибуция': 'ВНЕШНИЕ ФАКТОРЫ',
    'Категория': 'ВНЕШНИЕ ФАКТОРЫ',
    'Внешние': 'ВНЕШНИЕ ФАКТОРЫ',
    'Конкуренты': 'КОНКУРЕНТЫ',
}

# Порядок и человекочитаемые подписи 4 верхних групп — ЗЕРКАЛО фронта
# (decomposition-view.js TOP_GROUP_ORDER / TOP_GROUP_DISPLAY); согласованность
# держит канарейка decomposition-view-parity.test.js.
_TOP_GROUP_ORDER = ('БАЗА', 'МЕДИА', 'ВНЕШНИЕ ФАКТОРЫ', 'КОНКУРЕНТЫ')
_TOP_GROUP_DISPLAY = {
    'БАЗА': 'База',
    'МЕДИА': 'Медиа',
    'ВНЕШНИЕ ФАКТОРЫ': 'Внешние факторы',
    'КОНКУРЕНТЫ': 'Конкуренты',
}


def collapse_series_to_top_groups(series: list, *, eps: float = 1e-6) -> list:
    """Свёртка канонических серий в ≤4 агрегата верхнего уровня — ЗЕРКАЛО
    свёрнутого режима фронта (decomposition-view.js planViewSeries с пустым
    expanded). Обзорный timeline «4 группы» для отчётов (двухуровневость Т3-плюс).

    Тождество (гарантия конструкции): поэлементная сумма data всех агрегатов ==
    сумма data всех исходных серий (свёртка НЕ меняет значения). Стек-сторона
    агрегата (side) — по знаку суммарного вклада группы.

    Args:
        series: список серий из build_decomposition_series (у каждой top_group|group).
    Returns:
        list[{'top_group', 'name'(display), 'side', 'data', 'member_count'}]
        в каноническом порядке _TOP_GROUP_ORDER (только непустые группы).
    """
    if not series:
        return []
    n = max((len(s.get('data') or []) for s in series), default=0)

    buckets: dict[str, list] = {}
    for s in series:
        tg = s.get('top_group') or _TOP_GROUP_MAP.get(s.get('group'), 'ВНЕШНИЕ ФАКТОРЫ')
        buckets.setdefault(tg, []).append(s)

    ordered = [g for g in _TOP_GROUP_ORDER if g in buckets]
    ordered += [g for g in buckets if g not in _TOP_GROUP_ORDER]

    out = []
    for tg in ordered:
        members = buckets[tg]
        agg = [0.0] * n
        for s in members:
            d = s.get('data') or []
            for t in range(min(n, len(d))):
                v = d[t]
                agg[t] += float(v) if v is not None else 0.0
        total = sum(agg)
        out.append({
            'top_group': tg,
            'name': _TOP_GROUP_DISPLAY.get(tg, tg),
            'side': 'negative' if total < -eps else 'positive',
            'data': [round(v, 1) for v in agg],
            'member_count': len(members),
        })
    return out


def build_decomposition_series(
    dates: list,
    baseline_ts: list,
    time_series_channels: dict,
    signed_factor_contributions: dict | None,
    *,
    eps: float = 1e-6,
) -> dict:
    """Канонический набор серий timeline-декомпозиции — ЕДИНЫЙ источник истины
    для программы (ChannelTimeline) и всех отчётов (HTML/PPTX/XLSX).

    Аудит #12 (2026-06-07, INV-50): раньше каждый потребитель сам решал, какие
    факторы показывать. Программа выносила signed/holiday полосами, отчёты — нет
    (показывали меньше факторов). Хуже: программа вычитала из baseline только
    отрицательные факторы, а положительные праздники добавляла сверху НЕ вычитая
    → double-count. Здесь это считается ОДИН раз и честно.

    Честность тождества: `baseline` уже включает все control_effect. Каждый
    выносимый фактор (любого знака) ВЫЧИТАЕТСЯ из baseline и показывается своей
    полосой, поэтому per-period:
        baseline_reduced + Σ(вынесенные факторы) + Σ(медиа) == исходный total.
    positive_control не выносится (остаётся в baseline). all-zero per_period
    пропускаются (нет эффекта — нет полосы; применяется ко ВСЕМ потребителям,
    значит наборы остаются согласованными).

    Returns:
        {"dates": [...], "series": [{name, role, type, group, top_group, side, data[]}]}
        role ∈ {baseline, media, factor}; side ∈ {positive, negative}.
        top_group ∈ {БАЗА, МЕДИА, ВНЕШНИЕ ФАКТОРЫ, КОНКУРЕНТЫ} — верхний уровень
        4-групповой декомпозиции (решение Антона 2026-07-04) для drill-down UI/отчётов.
        Полоса «Сезонность» дополнительно несёт pct_of_base[] (сезонность помесячно
        в % к базовой линии — мультипликативная подача «февраль +60% к базе»).
    """
    n = len(baseline_ts or [])
    baseline_reduced = [float(v or 0) for v in (baseline_ts or [])]
    bands = []
    for name, fact in (signed_factor_contributions or {}).items():
        if not isinstance(fact, dict):
            continue
        ftype = fact.get('type')
        if ftype not in _BREAKOUT_TYPES:
            continue
        pp = fact.get('per_period') or []
        if not any(abs(float(v or 0)) > eps for v in pp):
            continue  # нулевой фактор — без полосы
        for t in range(min(n, len(pp))):
            baseline_reduced[t] -= float(pp[t] or 0)  # тождество: вычитаем любой знак
        mean = (sum(float(v or 0) for v in pp) / len(pp)) if pp else 0.0
        bands.append({
            'name': name,
            'role': 'factor',
            'type': ftype,
            'group': _FACTOR_GROUP_LABELS.get(ftype, 'Внешние'),
            'side': 'negative' if mean < 0 else 'positive',
            'data': [round(float(v or 0), 1) for v in pp],
        })

    # Помесячная сезонность как % к базе (решение Антона 2026-07-04): для полосы
    # «Сезонность» относительный ряд pct_of_base[t] = 100·эффект[t]/base[t], где
    # base — ФИНАЛЬНАЯ базовая линия после выноса всех факторов (baseline_reduced
    # уже досчитан циклом выше). Подача «февраль +60% к базе» — мультипликативная,
    # хотя модель аддитивна.
    # Guard (аудит 2026-07-04, INV-50): не только ~0, но и ВЫРОЖДЕННО МАЛАЯ база —
    # деление на базу, упавшую в шум (<1% от среднего |base| по ряду), даёт
    # дезинформирующие «+4000% к базе». Такие периоды честно получают 0.0.
    _base_scale = (
        sum(abs(v) for v in baseline_reduced) / len(baseline_reduced)
        if baseline_reduced else 0.0
    )
    _base_floor = max(eps, 0.01 * _base_scale)
    for b in bands:
        if b['type'] == 'seasonality':
            b['pct_of_base'] = [
                round(b['data'][t] / baseline_reduced[t] * 100, 1)
                if t < len(baseline_reduced) and abs(baseline_reduced[t]) > _base_floor else 0.0
                for t in range(len(b['data']))
            ]

    series = [{
        'name': 'Базовый уровень', 'role': 'baseline', 'type': 'baseline',
        'group': 'База', 'side': 'positive',
        'data': [round(v, 1) for v in baseline_reduced],
    }]
    for nm, ts in (time_series_channels or {}).items():
        series.append({
            'name': nm, 'role': 'media', 'type': 'media', 'group': 'Медиа',
            'side': 'positive',
            'data': [round(float(v or 0), 1) for v in (ts or [])],
        })
    # Порядок стека зеркалит ChannelTimeline: media → positive bands → negative bands.
    series.extend(b for b in bands if b['side'] == 'positive')
    series.extend(b for b in bands if b['side'] == 'negative')
    # Верхний уровень 4 групп (аддитивно — потребители старого формата не сломаются).
    for s in series:
        s['top_group'] = _TOP_GROUP_MAP.get(s.get('group'), 'ВНЕШНИЕ ФАКТОРЫ')
    return {'dates': list(dates or []), 'series': series}


def decompose(
    project_dir: str,
    unit_costs_override: dict | None = None,
    unit_cost_inflation_pct: dict | None = None,
    kpi_unit_cost_override: float | None = None,
    model_path: str | None = None,
    save_results: bool = True,
) -> dict[str, Any]:
    """Decompose sales into baseline + channel contributions using trained model.

    Args:
        project_dir: Path to project with models/latest.pkl
        unit_costs_override: Если задан - используется вместо config.unit_costs из pickle.
            Нужно, когда user изменил CPP/CPM после тренировки модели.
        kpi_unit_cost_override: v2.1.0 (ADR-021) override средней цены единицы count KPI
            для money ROI conversion. None = используем snapshot из pickle.
        model_path: E3 (2026-07-03) - явный путь к модели (архивное поколение из
            models/history/). None = models/latest.pkl (прежнее поведение).
        save_results: E3 - False у сравнения поколений: расчёт по архивной модели
            НЕ должен перетирать results/decomposition.json текущей.

    Returns:
        JSON with waterfall data, ROI, share of spend vs effect
    """
    project_path = Path(project_dir)
    model_path = Path(model_path) if model_path else project_path / 'models' / 'latest.pkl'

    if not model_path.exists():
        return {
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не найдена. Сначала обучите модель в кабинете «Данные и Модель».',
        }

    # Trust Level 3: централизованный pickle compat helper.
    # Auto-injects channel_categories={} для pre-v1.3 pickles.
    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(model_path)

    # P0-1/2/9 fix: pickle compat detection.
    # Sprint 2: '1.0-ols' accepted as small-data fallback path (treats как v1.1
    # downstream - point estimates only, no posterior CI, frequentist β CI на channel level).
    model_version = model_data.get('model_version', '1.0')
    if model_version == '1.0':
        return {
            'status': 'error',
            'error_code': 'MODEL_OUTDATED',
            'message': 'Модель обучена до v1.0.13. Нормализация изменилась - переобучите модель в кабинете "Модель".',
        }

    config = model_data['config']
    channel_params = model_data['channel_params']
    norm = model_data['normalization']
    # Phase 1.9: posterior samples for honest CI on contribution/ROI per channel.
    # None for v1.0/v1.1 pickles → ch dict skips ci_low/ci_high → compute_roi_verdict
    # Step 1 silently falls through (point-estimate verdict path preserved).
    posterior_samples = load_posterior_samples(model_data)
    y_actual = np.array(model_data['y_actual'])
    y_predicted_saved = np.array(model_data.get('y_predicted', []) or [])
    media_cols = config['media_columns']
    control_cols = config.get('control_columns', []) or []
    # A1 fix (post-audit v1.2): for decomposition we still report untrained channels
    # but their contribution will be ~0 (training data was constant → β·sat·y_std≈0).
    # No need to filter - they self-zero in the per-period contribution math.
    untrained_channels = set(model_data.get('normalization', {}).get('untrained_channels', []) or [])
    # Override > config. Передан ли override (даже {}) - клиент управляет явно.
    unit_costs = unit_costs_override if unit_costs_override is not None else (config.get('unit_costs', {}) or {})

    # Read original data for spend totals + adstock + control effects
    # C3-N3 (2026-07-03): протухший путь из pickle → фолбэк/понятная ошибка.
    from utils.data_file_resolver import resolve_data_file
    data_file = str(resolve_data_file(config.get('data_file'), project_dir))
    df = pd.read_excel(data_file) if data_file.endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
    # Материализация виртуальных каналов (если были merge_rules при train)
    from utils.merge_rules import apply_merge_rules
    apply_merge_rules(df, config.get('merge_rules'))
    # Аудит 2026-07-10 (High): хвост-медиаплан (KPI пуст) искажал декомпозицию —
    # n_periods=len(df) с хвостом при y_actual по истории; будущие траты текли
    # в исторические вклады каналов. Файл без хвоста → no-op. Симметрично modeler.
    _kpi_d = config.get('kpi_column')
    if _kpi_d and _kpi_d in df.columns:
        df = df[df[_kpi_d].notna()].reset_index(drop=True)

    # v2.1.0 (pilot 2026-05-16 fix B-01): re-inject holiday dummies для матча
    # с обученной моделью. modeler.py инжектирует 12 РФ holiday колонок в df
    # при тренировке (ADR-019 §5), они попадают в control_cols, но в исходном
    # Excel/CSV их нет — поэтому df[control_cols] на стр.521 падал с
    # `['holiday_newyear_preshop', ...] not in index`. Список injected
    # колонок сохранён в normalization.holiday_cols_injected (v2.0.0 ADR).
    holiday_cols_to_inject = (
        model_data.get('normalization', {}).get('holiday_cols_injected') or []
    )
    if holiday_cols_to_inject:
        date_col = config.get('date_column', 'Дата')
        if date_col in df.columns:
            try:
                from utils.holiday_calendar_ru import generate_holiday_dummies
                # v2.1 (2026-07-05): воспроизводим РЕЖИМ train-инжекта — β модели
                # согласованы с теми X. Старые pickle (без ключа) обучались на
                # binary_point; новые — на fraction (доля дней периода в окне
                # подготовки к событию).
                _hmode = (
                    model_data.get('normalization', {}).get('holiday_dummies_mode')
                    or 'binary_point'
                )
                holiday_df = generate_holiday_dummies(df[date_col], mode=_hmode)
                for hcol in holiday_cols_to_inject:
                    if hcol not in df.columns and hcol in holiday_df.columns:
                        df[hcol] = holiday_df[hcol].values
            except Exception as exc:
                # Graceful degradation: если re-inject failed - пытаемся декомпозицию
                # без holiday dummies (β-коэффициенты для них останутся - но соответствующие
                # X-значения будут нулевыми → контроль NaN-protect ниже).
                logger.warning(
                    'Decomposer: re-injection holiday dummies failed (%s). '
                    'Will proceed with df, controls без holidays may be 0.', exc,
                )
                # Защитная мера: убираем holiday cols из control_cols чтобы
                # df[control_cols] не падал. β для них останется в model_data
                # но без X-данных вклад будет 0.
                control_cols = [c for c in control_cols if c not in holiday_cols_to_inject]
        else:
            # AUD-02 fix (rc2): если date_col отсутствует в df (пользователь
            # переименовал колонку даты после тренировки), невозможно
            # re-injectit holidays - убираем их из control_cols, чтобы
            # df[control_cols] на стр.548 не упал с KeyError.
            logger.warning(
                'Decomposer: date_col %r отсутствует в df.columns - re-injection '
                'holidays невозможна. Убираем %d holiday колонок из control_cols '
                '(β для них останутся в model_data, но без X-данных вклад будет 0).',
                date_col, len(holiday_cols_to_inject),
            )
            control_cols = [c for c in control_cols if c not in holiday_cols_to_inject]

    # Автосезонность (2026-07-04): re-inject Фурье-контролей сезонной волны.
    # modeler инжектил sin/cos гармоники периода в df при тренировке (control_cols),
    # в исходном Excel их нет → df[control_cols] упал бы. Фурье по t-ИНДЕКСУ (не
    # датам) — воспроизводим по длине ряда + period/K из fourier_seasonality;
    # бит-в-бит с обучением (декомпозиция на тех же обучающих строках, тот порядок).
    fourier_meta = model_data.get('fourier_seasonality')
    if fourier_meta:
        try:
            from utils.fourier_seasonality import generate_fourier_terms
            _fdf = generate_fourier_terms(
                len(df), int(fourier_meta['period']), int(fourier_meta['n_harmonics'])
            )
            for _fc in fourier_meta.get('columns', []) or []:
                if _fc not in df.columns and _fc in _fdf.columns:
                    df[_fc] = _fdf[_fc].values
        except Exception as exc:
            logger.warning(
                'Decomposer: re-injection Fourier seasonality failed (%s). '
                'Убираем сезонные колонки из control_cols (β останутся, вклад 0).', exc,
            )
            _fcols = fourier_meta.get('columns', []) or []
            control_cols = [c for c in control_cols if c not in _fcols]

    # Phase 2 audit pass 4 - per-channel inflation: customer entered current
    # cost (latest training year) + annual_inflation_pct → adjust к training-
    # period weighted average. ROI/mROAS теперь reflect actual training prices.
    if unit_cost_inflation_pct:
        from utils.unit_cost_inflation import apply_inflation_to_unit_costs
        unit_costs = apply_inflation_to_unit_costs(
            unit_costs=unit_costs,
            inflation_pct_per_channel=unit_cost_inflation_pct,
            df=df,
            date_column=config.get('date_column', 'date'),
        )

    n_periods = len(df)
    total_sales = float(y_actual.sum())

    # Normalization params
    y_mean = float(norm.get('y_mean', 0))
    y_std = float(norm.get('y_std', 1)) or 1
    intercept_mean = float(norm.get('intercept_mean', 0))
    control_betas_mean = norm.get('control_betas_mean', []) or []
    media_means = norm.get('media_means', {}) or {}
    control_means = norm.get('control_means', {}) or {}
    control_stds = norm.get('control_stds', {}) or {}

    adstock_config = config.get('adstock_config', {}) or {}

    # v2.1.0 (ADR-020): unit_costs которые modeler применил при тренировке.
    # Нужно для симметричного pre-multiply raw media при decompose - иначе
    # media_means (scaled) не совпадёт с X_media (raw). Pickles без флага
    # → пустой dict → no-op (legacy backward compat).
    unit_costs_applied_at_training = bool(model_data.get('unit_costs_applied_at_training'))
    unit_costs_at_training: dict[str, float] = (
        model_data.get('unit_costs_snapshot') or {}
    ) if unit_costs_applied_at_training else {}

    # v2.1.0 (ADR-021): kpi_unit_cost для money ROI conversion при count KPI.
    # Override из request > snapshot из pickle > None (legacy native units).
    kpi_unit_cost: float | None
    if kpi_unit_cost_override is not None and float(kpi_unit_cost_override) > 0:
        kpi_unit_cost = float(kpi_unit_cost_override)
    else:
        _snap = model_data.get('kpi_unit_cost_snapshot')
        kpi_unit_cost = float(_snap) if _snap is not None and float(_snap) > 0 else None
    # Detect kpi_kind для условной активации money conversion. Resolution chain:
    # 1) Explicit kpi_kind в config (ADR-016+ pickles)
    # 2) Derive из kpi_type (ADR-020+ pickles: 'sales_packs'/'leads'/... → count)
    # 3) Fallback classify_column(kpi_column) для legacy pickles до ADR-016
    _kpi_kind_cfg = (config.get('kpi_kind') or '').lower()
    if _kpi_kind_cfg in ('count', 'monetary'):
        kpi_kind = _kpi_kind_cfg
    else:
        _count_types = {
            'sales_packs', 'leads', 'registrations', 'loyalty_cards',
            'subscriptions', 'app_installs', 'count_custom',
        }
        _monetary_types = {'sales', 'revenue', 'profit'}
        _kpi_type_cfg = (config.get('kpi_type') or '').lower()
        if _kpi_type_cfg in _count_types:
            kpi_kind = 'count'
        elif _kpi_type_cfg in _monetary_types:
            kpi_kind = 'monetary'
        else:
            try:
                from utils.column_detection import classify_column
                _kpi_col_classify = classify_column(config.get('kpi_column', '') or '')
                kpi_kind = 'count' if _kpi_col_classify == 'target_count' else 'monetary'
            except Exception:
                kpi_kind = 'monetary'  # safe default - legacy behaviour

    # ─────────────────────────────────────────────────────────────────────
    # P0-3/4/10 fix: per-channel per-period contribution = β × hill(adstock(x)/mean) × y_std
    # ─────────────────────────────────────────────────────────────────────
    channels = []
    time_series_channels: dict[str, list[float]] = {}
    total_media_contribution = 0.0

    for col in media_cols:
        params = channel_params[col]
        # H-OLS-2 (audit 2026-04-27): explicit guard для untrained channels.
        # OLS engine marks channels with zero training variance via 'untrained': True flag.
        # Pre-fix: such channels могли silently get spurious contribution когда production
        # spend non-zero (mean fallback к 1.0 → x_norm = adstocked/1.0 = full raw → Hill saturation).
        # Post-fix: explicit zero contribution + skip CI computation.
        #
        # Phase 5 follow-up audit (2026-05-03): Bayesian engine marks untrained channels
        # only через `normalization.untrained_channels` list (not channel_params.untrained).
        # OLS marks both. Без поддержки norm-list path, Bayesian-trained pickles с zero-
        # variance channels gave spurious contributions (decomposer не skipped). Fix:
        # secondary check - col в untrained_channels list.
        if params.get('untrained') or col in untrained_channels:
            from engines.narrative_adapter import _normalize_channel_name as _norm
            ch_dict_untr = {
                'name': col,
                'display_name': _norm(col) or col,
                'spend': 0.0,
                'raw_spend': 0.0,
                'unit_cost': float(unit_costs.get(col, 1.0) or 1.0),
                'contribution': 0.0,
                'contribution_pct': 0,
                'roi': 0.0,
                'beta': 0.0,
                'verdict': 'Не обучен',
                'verdict_tone': 'neutral',
                'untrained': True,
                'ci_skip_reason': 'untrained_channel',
                'mroi_current': 0.0,
            }
            channels.append(ch_dict_untr)
            continue
        beta = float(params.get('beta', 0))
        alpha = max(float(params.get('alpha', 1)), 1e-6)
        gamma = max(float(params.get('gamma', 0.5)), 1e-6)

        raw_spend_series_native = df[col].fillna(0).values.astype(float)
        raw_spend_total = float(raw_spend_series_native.sum())

        # v2.1.0 (ADR-020): симметрия с training pre-multiply. Если pickle
        # обучался с unit_costs applied — media_means в normalization тоже
        # scaled. Без симметричного pre-multiply здесь X_norm построится
        # на raw spend → mismatch с обученной нормализацией → broken hill.
        # Важно: raw_spend_total (native units) сохранён ДО pre-multiply -
        # это используется для downstream spend_money = raw × unit_cost
        # (line ~421). Без backup получалось бы double-multiply.
        uc_train = float(unit_costs_at_training.get(col, 1.0))
        if uc_train > 0 and uc_train != 1.0:
            raw_spend_series = raw_spend_series_native * uc_train
        else:
            raw_spend_series = raw_spend_series_native

        # 1. Adstock (matches training).
        # adstock_config schema: dict[channel, str] - type only ('geometric' or 'weibull').
        # Defensive read: tolerate dict-with-'type' format from older pickles or
        # rare configs, but standardize on str. Hyperparameters use library defaults
        # (matching modeler.py training-time apply_adstock signature).
        raw_at = adstock_config.get(col)
        if isinstance(raw_at, dict):
            a_type = raw_at.get('type', 'geometric')
        elif isinstance(raw_at, str):
            a_type = raw_at
        else:
            a_type = 'geometric'

        # Phase 1.1: when v1.2 pickle, use posterior mean decay from channel_params.
        # Falls back to library default (0.5/2.0/3.0) для v1.0/v1.1/v1.1.5 pickles.
        decay_point = params.get('decay')  # None for legacy pickles
        adstock_params_override = {'alpha': float(decay_point)} if decay_point is not None else None
        x_adstock = apply_adstock(raw_spend_series, a_type, adstock_params_override)

        # 2. Normalize spend/mean (matches Phase 2 fix).
        # C1 fix (audit 2026-04-26): prefer in-model adstock_mean_posterior (Phase 1.1+ v1.2 pickles)
        # for math consistency with training. Fallback to pre-computed media_means для legacy
        # pickles (v1.0-ols, v1.1, v1.1.5) where this field absent.
        mean_posterior = params.get('adstock_mean_posterior')
        mean = float(mean_posterior) if mean_posterior is not None else float(media_means.get(col, 1)) or 1
        x_norm = x_adstock / max(mean, 1e-10)

        # 3. Hill saturation
        sat = hill_function(np.maximum(x_norm, 0), alpha=alpha, gamma=gamma)

        # 4. Per-period contribution in original KPI units
        contrib_per_period = beta * sat * y_std
        channel_total = float(contrib_per_period.sum())
        total_media_contribution += channel_total

        time_series_channels[col] = [round(float(v), 1) for v in contrib_per_period]

        # Money & ROI
        unit_cost = float(unit_costs.get(col, 1.0) or 1.0)
        spend_money = raw_spend_total * unit_cost

        # v2.1.0 (ADR-021): money ROI conversion для count KPI.
        # channel_total всегда в native KPI units (β × hill × y_std).
        # Для count KPI с заданным kpi_unit_cost → contribution_money =
        # channel_total × kpi_unit_cost → roi = money/money безразмерный.
        # Для monetary KPI или count без kpi_unit_cost → legacy native ratio.
        if kpi_kind == 'count' and kpi_unit_cost is not None:
            contribution_money = channel_total * kpi_unit_cost
            roi = contribution_money / spend_money if spend_money > 0 else 0
        else:
            contribution_money = channel_total if kpi_kind == 'monetary' else None
            roi = channel_total / spend_money if spend_money > 0 else 0

        # L4 (math-fix v1.4 Section C, 2026-04-28): mroi_current at current allocation
        # via single-source-of-truth helper. Optimize UI miROASMap reads this field
        # in idle state (pre-optimize) instead of broken JS fallback `marginalROI`
        # which was missing /unit_cost /mean /adstock_factor → mixed units (Kagocel
        # TRPs showed 110.93× pre-optimize vs 0.0285× post-optimize).
        from engines.optimizer import _compute_mroas_money
        # v2.1.0 (ADR-020): pass training-time uc для Hill symmetry mROAS consistency.
        mroi_current_pt = float(_compute_mroas_money(
            current_spend_native=raw_spend_total,
            n_periods=n_periods,
            mean=mean,
            alpha=alpha,
            gamma=gamma,
            beta=beta,
            adstock_type=a_type,
            y_std=y_std,
            unit_cost=unit_cost,
            decay=decay_point,
            uc_at_training=uc_train,
        ))

        # L11 (math-fix v1.4 Section C, 2026-04-29): display_name strips Excel
        # column-header noise («Performance Бюджет до НДС до АК» → «Performance»).
        # `name` field preserved for data lookups; `display_name` для UI rendering
        # consistency (interpretation block, charts, narrative tooltips).
        from engines.narrative_adapter import _normalize_channel_name
        display_name = _normalize_channel_name(col) or col

        ch_dict = {
            'name': col,
            'display_name': display_name,
            'spend': round(spend_money, 0),
            'raw_spend': round(raw_spend_total, 2),
            'unit_cost': unit_cost,
            'contribution': round(channel_total, 0),  # native KPI units (count для count KPI)
            # v2.1.0 (ADR-021): money equivalent contribution когда применимо.
            # None для count KPI без kpi_unit_cost → frontend показывает native.
            'contribution_money': (
                round(contribution_money, 0) if contribution_money is not None else None
            ),
            'contribution_pct': 0,  # filled after total computed below
            'roi': round(roi, 2),
            'mroi_current': round(mroi_current_pt, 4),
            'beta': beta,
            'verdict': '',
            'verdict_tone': 'neutral',
            # Trust Level 3 (v1.1.0): adstock decay posterior summary для UI display.
            # Decompose grouping panel показывает effective half-life per channel.
            'adstock_decay_mean': float(decay_point) if decay_point is not None else None,
        }

        # F1 fix (audit 2026-04-27): per-sample training adstock mean for math
        # consistency with in-model `adstock_full[s,:].mean()` normalization.
        # Pre-fix used scalar `adstock_mean_posterior` for all samples → CI
        # distribution shape distorted when decay varies across draws (which is
        # the whole point of hierarchical learnable adstock - Phase 1.1).
        # Same class-of-bug as C1 (audit 2026-04-26), but missed by C1 fix
        # which closed only the POINT estimate path.
        # Phase 1.9 + 1.1: posterior CI on contribution and ROI via vectorized chain.
        # C3 fix (audit 2026-04-26): explicit CI semantics для spend=0 channels.
        # Pre-fix: spend=0 channels skipped from CI (asymmetric - point estimate populated
        # как roi=0 но без ci_low/ci_high → UI shows "ROI 0× (no CI)" without explanation).
        # Post-fix: explicit ci_low=ci_high=0 with marker 'ci_skip_reason' = 'zero_spend'
        # so UI can render "Канал без бюджета - ROI = 0 (CI неприменим)".
        if posterior_samples is not None and spend_money <= 0:
            ch_dict['contribution_ci_low'] = 0.0
            ch_dict['contribution_ci_high'] = 0.0
            ch_dict['roi_ci_low'] = 0.0
            ch_dict['roi_ci_high'] = 0.0
            ch_dict['ci_skip_reason'] = 'zero_spend'
            ch_dict['ci_method'] = 'unavailable_zero_spend'

        # Sprint 2 extension (small-data path): for '1.0-ols' pickles, populate
        # roi_ci_low/high from stored bootstrap CI (no posterior_samples available).
        # This gives OLS path same UI semantics as Bayesian - UI renders brackets
        # uniformly without engine-specific code paths.
        if posterior_samples is None and spend_money > 0:
            roi_ci_low_boot = params.get('roi_ci_low_bootstrap')
            roi_ci_high_boot = params.get('roi_ci_high_bootstrap')
            if roi_ci_low_boot is not None and roi_ci_high_boot is not None:
                ch_dict['roi_ci_low'] = round(float(roi_ci_low_boot), 4)
                ch_dict['roi_ci_high'] = round(float(roi_ci_high_boot), 4)
                ch_dict['ci_method'] = 'frequentist_bootstrap'
        # Phase 1.1 path: when ch_samples has 'decay', x_norm varies per sample
        # via geometric_adstock_batch - use hill_function_batch_2d.
        # Phase 1.9 path (v1.1.5 pickles): decay constant, use hill_function_batch (1D x_norm).
        if posterior_samples is not None and spend_money > 0:
            ch_samples = per_channel_samples(posterior_samples, col)
            if ch_samples is not None:
                decay_samples = ch_samples.get('decay')
                if decay_samples is not None and a_type == 'geometric':
                    # Phase 1.1: per-sample adstock + Hill, joint correlation preserved.
                    x_adstock_2d = geometric_adstock_batch(raw_spend_series, decay_samples)
                    # F1 fix: in decomposer, raw_spend_series IS training data (df reloaded
                    # from config.data_file at line 180), so x_adstock_2d.mean(axis=1) is
                    # the per-sample training adstock mean - exactly what model used during
                    # training. Use as per-sample divisor to restore math consistency.
                    mean_per_sample = np.maximum(
                        x_adstock_2d.mean(axis=1, keepdims=True), 1e-10
                    )
                    x_norm_2d = x_adstock_2d / mean_per_sample
                    sat_samples = hill_function_batch_2d(
                        x_norm_2d, ch_samples['alpha'], ch_samples['gamma']
                    )
                else:
                    # Phase 1.9 fallback (v1.1.5 pickles or weibull channels) - decay
                    # constant across samples, so scalar `mean` is consistent with training.
                    sat_samples = hill_function_batch(
                        x_norm, ch_samples['alpha'], ch_samples['gamma']
                    )
                # contribution per period × sample, summed over time → (n_samples,)
                contrib_total_samples = (
                    ch_samples['beta'].reshape(-1, 1).astype(np.float64)
                    * sat_samples
                    * y_std
                ).sum(axis=1)
                _, contrib_ci_low, contrib_ci_high, _method_c = compute_ci_hdi(contrib_total_samples)
                ch_dict['contribution_ci_low'] = round(float(contrib_ci_low), 0)
                ch_dict['contribution_ci_high'] = round(float(contrib_ci_high), 0)

                # ROI distribution: contribution / spend_money (constant denominator)
                roi_samples = contrib_total_samples / spend_money
                _, roi_ci_low, roi_ci_high, _method_r = compute_ci_hdi(roi_samples)
                ch_dict['roi_ci_low'] = round(float(roi_ci_low), 4)
                ch_dict['roi_ci_high'] = round(float(roi_ci_high), 4)
                # F5 fix: ci_method reflects ACTUAL HDI computation (not silent fallback).
                # A2 audit-of-audit (2026-04-27): conservative OR semantic - flag '_pct'
                # if EITHER contrib OR roi fell back к percentile (in case arviz fails on
                # one but not the other due to numerical edge cases).
                _is_pct = (_method_c == 'percentile_fallback') or (_method_r == 'percentile_fallback')
                if decay_samples is not None:
                    base = 'bayesian_hdi_phase11_pct' if _is_pct else 'bayesian_hdi_phase11'
                    # Trust Level 3: 50% CI для decay (Critical Audit issue M).
                    # 95% would показывать decay 0.30-0.95 → uninterpretable. 50% (q25/q75) tighter.
                    try:
                        import numpy as _np2
                        ds = _np2.asarray(decay_samples, dtype=float)
                        ch_dict['adstock_decay_mean'] = float(_np2.mean(ds))
                        ch_dict['adstock_decay_ci_low'] = float(_np2.quantile(ds, 0.25))
                        ch_dict['adstock_decay_ci_high'] = float(_np2.quantile(ds, 0.75))
                    except Exception:
                        pass
                else:
                    base = 'bayesian_hdi_pct' if _is_pct else 'bayesian_hdi'
                ch_dict['ci_method'] = base

        channels.append(ch_dict)

    # Fill contribution_pct relative to total media contribution
    for ch in channels:
        ch['contribution_pct'] = round(
            ch['contribution'] / total_media_contribution * 100, 1
        ) if total_media_contribution > 0 else 0

    # ─────────────────────────────────────────────────────────────────────
    # Baseline = intercept_mean × y_std + y_mean (per period) + control effect
    # ─────────────────────────────────────────────────────────────────────
    intercept_per_period = np.full(n_periods, intercept_mean * y_std + y_mean, dtype=float)

    control_effect_per_period = np.zeros(n_periods, dtype=float)
    # v2.0.0 (ADR-019 §4): signed factor contributions output для UI WaterfallChart
    # с поддержкой negative bars (signed factors могут уменьшать продажи —
    # competitor activity, price effects).
    signed_factor_contributions: dict = {}
    if control_cols and control_betas_mean and len(control_betas_mean) == len(control_cols):
        # Reconstruct control normalization (z-score retained for controls - non-Hill linear)
        c_means = np.array([float(control_means.get(c, 0)) for c in control_cols])
        c_stds = np.array([float(control_stds.get(c, 1)) or 1 for c in control_cols])
        X_control_raw = df[control_cols].fillna(0).astype(float).values
        X_control_norm = (X_control_raw - c_means) / c_stds
        beta_c = np.array(control_betas_mean, dtype=float)
        # control_effect normalised → multiply by y_std for original-unit
        control_effect_per_period = (X_control_norm @ beta_c) * y_std

        # v2.0.0: per-factor contribution breakdown using column_detection classifier
        try:
            from utils.column_detection import classify_column
            # Use y_actual.sum() для % normalization (вне цикла — нужно и для агрегата).
            _y_total = float(y_actual.sum()) if len(y_actual) else 0.0
            # Аккумулятор Фурье-гармоник → ОДИН агрегированный фактор «Сезонность».
            season_effect_agg = None
            for i, col in enumerate(control_cols):
                col_effect = (X_control_norm[:, i] * beta_c[i]) * y_std
                col_kind = classify_column(col)
                # Сезонность: 2K колонок sin/cos агрегируются в ОДИН фактор «Сезонность»
                # (не 6 полос отдельных гармоник — они не интерпретируемы поодиночке).
                # Суммируем эффект поэлементно; beta_mean для суммы не осмыслен (опускаем).
                if col_kind == 'seasonality':
                    season_effect_agg = (
                        col_effect if season_effect_agg is None
                        else season_effect_agg + col_effect
                    )
                    continue
                col_total = float(col_effect.sum())
                # Map kind → factor_type для UI rendering
                factor_type_map = {
                    'signed_competitor': 'signed_competitor',
                    'signed_price': 'signed_price',
                    'signed_weather': 'signed_weather',
                    'signed_macro': 'signed_macro',
                    'holiday': 'holiday',
                    'seasonality': 'seasonality',  # агрегируется выше (continue) — sanity
                    'category': 'category',  # Фаза Б: продажи рынка — полоса «Категория» (ВНЕШНИЕ)
                    'control': 'positive_control',
                    'unknown': 'positive_control',  # legacy fallback
                }
                factor_type = factor_type_map.get(col_kind, 'positive_control')
                signed_factor_contributions[col] = {
                    'value': round(col_total, 1),
                    'pct': round(col_total / (_y_total + 1e-10) * 100, 1) if _y_total > 0 else 0.0,
                    'type': factor_type,
                    'beta_mean': float(beta_c[i]),
                    'per_period': [round(float(v), 1) for v in col_effect],
                }
            # Один агрегированный фактор «Сезонность» из всех Фурье-гармоник. Суммарное
            # value за целое число циклов ≈ 0 (сезон перераспределяет, не добавляет) —
            # ценность в per_period-волне и pct_of_base (build_decomposition_series).
            if season_effect_agg is not None:
                season_total = float(season_effect_agg.sum())
                signed_factor_contributions['Сезонность'] = {
                    'value': round(season_total, 1),
                    'pct': round(season_total / (_y_total + 1e-10) * 100, 1) if _y_total > 0 else 0.0,
                    'type': 'seasonality',
                    'per_period': [round(float(v), 1) for v in season_effect_agg],
                }
        except Exception as e:
            logger.warning('signed_factor_contributions computation failed: %s', e)
            signed_factor_contributions = {}

    # Energy conservation (post-audit fix): baseline absorbs residual variance
    # so that sum(baseline) + sum(channels) == sum(y_actual) exactly.
    # Standard MMM convention (Robyn, LightweightMMM, Meridian): residual goes
    # into baseline since by construction it's "unexplained by media".
    # Compute model-predicted per period (sum of intercept + media + controls):
    media_contrib_per_period = np.zeros(n_periods, dtype=float)
    for col in media_cols:
        ts = time_series_channels.get(col, [])
        for t, v in enumerate(ts):
            if t < n_periods:
                media_contrib_per_period[t] += float(v)
    raw_baseline = intercept_per_period + control_effect_per_period
    model_predicted_per_period = raw_baseline + media_contrib_per_period
    # Residual = actual - model_predicted; absorbed into baseline
    if len(y_actual) >= n_periods:
        residual_per_period = y_actual[:n_periods] - model_predicted_per_period
    else:
        residual_per_period = np.zeros(n_periods, dtype=float)
    baseline_per_period = raw_baseline + residual_per_period
    baseline_total = float(baseline_per_period.sum())
    baseline_ts = [round(float(v), 1) for v in baseline_per_period]

    # Sort by ROI descending
    channels.sort(key=lambda x: x['roi'], reverse=True)

    # Share of Spend vs Share of Effect
    total_spend = sum(c['spend'] for c in channels) or 1
    for ch in channels:
        ch['share_of_spend'] = round(ch['spend'] / total_spend * 100, 1)
        ch['share_of_effect'] = ch['contribution_pct']
        ch['efficiency_gap'] = round(ch['share_of_effect'] - ch['share_of_spend'], 1)

    # Category + unit_smell detection (used by hybrid verdict)
    # Trust Level 3: prefer explicit channel_categories из pickle (training-time
    # decision); fallback к heuristic для pre-v1.3 pickles.
    from engines.persistence import get_channel_categories
    explicit_categories = get_channel_categories(model_data, fallback_heuristic=False)

    UNIT_HINTS = ('TRP', 'GRP', 'OTS', 'IMPRESSION', 'CLICK', 'ПОКАЗ', 'КЛИК', 'ПРОСМОТР', 'ВИЗИТ', 'ПУНКТ', 'ОХВАТ', 'РЕЙТИНГ')
    # Heuristic fallback hints - single source of truth = utils/channel_categorization.py.
    from utils.channel_categorization import auto_suggest_category

    # Optional portfolio quantiles (Phase 1+ groundwork - None until aggregator ships).
    category_quantiles = config.get('category_quantiles') if isinstance(config, dict) else None
    n_channels = len(channels)

    for ch in channels:
        # Phase 5 follow-up audit (2026-05-03): untrained channels preserve their
        # honest 'Не обучен' verdict - without skip, downstream compute_roi_verdict
        # overwrote с 'Глубоко убыточный' (roi=0 < 0.5 threshold), which is wrong
        # diagnostic (no data ≠ deep loss).
        if ch.get('untrained'):
            ch.setdefault('category', 'mixed')
            ch.setdefault('unit_smell', False)
            ch.setdefault('share_of_spend', 0.0)
            ch.setdefault('share_of_effect', 0.0)
            ch.setdefault('efficiency_gap', 0.0)
            continue
        name = ch['name'] or ''
        name_upper = name.upper()
        looks_like_non_money = any(hint in name_upper for hint in UNIT_HINTS)
        # Trust Level 3 mapping: 'brand' → 'brand_reach' (preserves verdict thresholds API).
        if name in explicit_categories:
            cat_v3 = explicit_categories[name]
            if cat_v3 == 'brand':
                ch['category'] = 'brand_reach'
            elif cat_v3 == 'performance':
                ch['category'] = 'performance'
            else:
                ch['category'] = 'mixed'
        else:
            # Heuristic fallback for pre-v1.3 pickles (single source = utils/channel_categorization).
            sug = auto_suggest_category(name)
            if sug['category'] == 'brand' and sug['confidence'] >= 0.7:
                ch['category'] = 'brand_reach'
            elif sug['category'] == 'performance' and sug['confidence'] >= 0.7:
                ch['category'] = 'performance'
            else:
                ch['category'] = 'mixed'
        ch['unit_smell'] = bool(looks_like_non_money and abs(ch['unit_cost'] - 1.0) < 1e-9)

        # Hybrid verdict (absolute + relative + posterior CI) - see compute_roi_verdict docstring.
        # v2.1.0 (B-02 pilot 2026-05-17): pass money_roi_unavailable flag для count KPI
        # без kpi_unit_cost - предотвращает ложные «Глубоко убыточный» verdicts
        # когда roi семантически = упак/₽ (1/CPU), не money ratio.
        _money_roi_na = bool(kpi_kind == 'count' and kpi_unit_cost is None)
        verdict_label, verdict_tone = compute_roi_verdict(
            roi=ch['roi'],
            efficiency_gap=ch['efficiency_gap'],
            category=ch['category'],
            unit_smell=ch['unit_smell'],
            roi_ci_low=ch.get('roi_ci_low'),
            roi_ci_high=ch.get('roi_ci_high'),
            n_channels=n_channels,
            category_quantiles=category_quantiles,
            money_roi_unavailable=_money_roi_na,
        )
        ch['verdict'] = verdict_label
        ch['verdict_tone'] = verdict_tone

    # L4 (math-fix v1.4 Section C, 2026-04-28): decorate каждый channel с
    # prescriptive action fields через single-source-of-truth helper. Same
    # compute_channel_action used в optimizer.py + narrative_adapter.py →
    # three-way alignment (decompose UI ↔ optimize UI ↔ HTML/PPTX commentary).
    # При idle state (pre-optimize) optimal_spend отсутствует → action falls back
    # к mROAS-only heuristic. После optimize backend overrides с optimizer signal.
    from engines.channel_action import compute_channel_action
    for ch in channels:
        # Phase 5 follow-up audit: untrained channels - fixed action vocabulary
        # вместо compute_channel_action которая инфер из mROAS=0 (low confidence).
        if ch.get('untrained'):
            ch.setdefault('action', 'Uncertain')
            ch.setdefault('action_label', 'Не обучен')
            ch.setdefault('action_tone', 'neutral')
            ch.setdefault('action_reasoning', 'Канал имел нулевую вариативность в обучающих данных - модель не обучилась на нём.')
            ch.setdefault('action_priority', 0)
            ch.setdefault('action_confidence', 'high')
            continue
        # alias mroi_current → mroas для compute_channel_action API contract
        action_input = {**ch, 'mroas': ch.get('mroi_current')}
        action = compute_channel_action(action_input)
        ch['action'] = action.key
        ch['action_label'] = action.label_ru
        ch['action_tone'] = action.tone
        ch['action_reasoning'] = action.reasoning
        ch['action_priority'] = action.priority
        ch['action_confidence'] = action.confidence

    # Insight generation (template, 0 tokens).
    # B3 fix (post-audit v1.2): removed magic-0.5 lift estimate. Pre-fix code computed
    # `lift = |efficiency_gap| × 0.5` then claimed "ожидаемый прирост +X% продаж" -
    # without basis in model. Replaced with descriptive text only; for actual lift
    # estimate user should run scenario or optimize step (which DO compute against model).
    # REC-1-GAP (2026-06-03 audit): channels отсортированы по ROI убыв. (:715), поэтому
    # channels[0] — не-денежный unit_smell-канал (TRP/clicks, ROI-артефакт 12186×), если он
    # есть. НЕ короновать его «самым эффективным» и НЕ советовать перераспределять в него
    # (та же ROI-1/2 проблема). Берём лучший среди денежных; fallback если все unit_smell.
    # _money_roi_na (count-KPI без kpi_unit_cost) вычислен в per-channel loop выше;
    # пересчитываем явно для надёжности (loop мог не выполниться при 0 каналах).
    _insight_money_roi_na = bool(kpi_kind == 'count' and kpi_unit_cost is None)
    insight = _build_channel_insight(
        channels,
        money_roi_unavailable=_insight_money_roi_na,
        kpi_kind=kpi_kind,
        kpi_type=config.get('kpi_type'),
        derived_mode=model_data.get('derived_mode') or 'roi',
    )

    # Per-period dates
    date_col = config.get('date_column', 'date')
    if date_col in df.columns:
        dates = [str(d)[:10] for d in df[date_col].tolist()]
    else:
        dates = [str(i + 1) for i in range(n_periods)]

    # Smell-детектор для banner доверия
    smell_flags = []
    positive_rois = [c['roi'] for c in channels if c['roi'] > 0]
    any_unit_smell = any(c.get('unit_smell') for c in channels)
    if positive_rois and any_unit_smell:
        roi_max = max(positive_rois)
        roi_min = min(positive_rois)
        if roi_max > 50:
            top_ch = max(channels, key=lambda c: c['roi'])
            smell_flags.append({
                'type': 'roi_max',
                'channel': top_ch['name'],
                'value': round(roi_max, 1),
                'severity': 'high' if roi_max > 200 else 'medium',
            })
        if roi_min > 0 and roi_max / roi_min > 50:
            smell_flags.append({
                'type': 'roi_spread',
                'value': round(roi_max / roi_min, 1),
                'severity': 'high' if roi_max / roi_min > 200 else 'medium',
            })
    unit_smell_channels = [c['name'] for c in channels if c.get('unit_smell')]
    if unit_smell_channels:
        smell_flags.append({
            'type': 'unit_smell',
            'channels': unit_smell_channels,
            'severity': 'medium',
        })

    # Phase 1.1: model_version warning - flag legacy pickles for re-training.
    # v1.1.5 pickles use hardcoded adstock decay (0.5) - CI not honest about
    # carryover uncertainty. UI can render banner suggesting re-train for v1.2.
    # Sprint 2: '1.0-ols' = small-data fallback, frequentist semantics (no posterior CI).
    model_warning = None
    if model_version == '1.0-ols':
        n_obs_ols = len(y_actual) if isinstance(y_actual, (list, np.ndarray)) else 0
        model_warning = (
            f'OLS-режим (small data fallback): n={n_obs_ols} наблюдений. '
            f'Hill α=1.5, γ=0.5, decay=0.5 - фиксированы (не обучаются). '
            f'Доверительные интервалы - frequentist на β-коэффициенты + predictive '
            f'intervals на y. Posterior CI на ROI/mROAS недоступны (нужен n≥30 для '
            f'Bayesian). Соберите больше данных для премиум-модели.'
        )
    elif model_version == '1.1.5':
        model_warning = (
            'Эта модель обучена с фиксированным adstock-затуханием (0.5). '
            'Доверительные интервалы не учитывают неопределённость carryover. '
            'Переобучите модель для получения honest CI на adstock (Phase 1.1, v1.2).'
        )
    elif model_version == '1.1':
        model_warning = (
            'Эта модель обучена до Phase 1.9 - посterior samples отсутствуют. '
            'Доверительные интервалы недоступны. Переобучите модель для CI поддержки.'
        )

    # v1.3.0: load KPI settings from project state (per ADR-016, ADR-017).
    v13_kpi = _load_v13_kpi_settings(project_path)
    # F-A (2026-06-06): источник kpi-метаданных = pickle (v13_kpi.json мёртв, LOAD-1),
    # иначе count-KPI экспорт мислейблится monetary (narrative_adapter→PPTX/HTML).
    # derived_mode — реальный из model_data (а не хардкод 'roi'): иначе count+effectiveness
    # экспорт показал бы «CPU ₽/ед.» вместо «Доля %» (аудит 2026-06-06).
    _kpi_meta = _resolve_output_kpi_meta(
        v13_kpi, kpi_kind, kpi_unit_cost,
        derived_mode_default=model_data.get('derived_mode') or 'roi',
        kpi_type=config.get('kpi_type') or None,
    )

    result = {
        'status': 'ok',
        'model_version': model_version,
        'model_warning': model_warning,  # None for v1.2 (current production), banner string for legacy
        'smell_flags': smell_flags,
        # v1.3.0 KPI metadata for downstream UI / reports (per ADR-016). Источник —
        # pickle config (F-A fix), не мёртвый v13_kpi.json.
        'kpi_kind': _kpi_meta['kpi_kind'],
        'derived_mode': _kpi_meta['derived_mode'],
        'value_per_count_unit': _kpi_meta['value_per_count_unit'],
        'value_per_count_unit_label': _kpi_meta['value_per_count_unit_label'],
        # Фаза 1a: конкретный тип KPI для паспортных подписей (kpi_labels/kpi_helpers).
        'kpi_type': _kpi_meta['kpi_type'],
        'total_sales': round(total_sales, 0),
        'baseline': round(baseline_total, 0),
        'baseline_pct': round(baseline_total / total_sales * 100, 1) if total_sales else 0,
        'media_contribution': round(total_media_contribution, 0),
        # v2.1.0 (ADR-021): money equivalent для count KPI when kpi_unit_cost задан.
        # Frontend выбирает primary display (money если набор полный).
        'kpi_unit_cost': kpi_unit_cost,
        'total_sales_money': (
            round(total_sales * kpi_unit_cost, 0)
            if kpi_unit_cost is not None and kpi_kind == 'count'
            else (round(total_sales, 0) if kpi_kind == 'monetary' else None)
        ),
        'baseline_money': (
            round(baseline_total * kpi_unit_cost, 0)
            if kpi_unit_cost is not None and kpi_kind == 'count'
            else (round(baseline_total, 0) if kpi_kind == 'monetary' else None)
        ),
        'media_contribution_money': (
            round(total_media_contribution * kpi_unit_cost, 0)
            if kpi_unit_cost is not None and kpi_kind == 'count'
            else (round(total_media_contribution, 0) if kpi_kind == 'monetary' else None)
        ),
        'channels': channels,
        'insight': insight,
        'waterfall': {
            'labels': ['Baseline'] + [c['name'] for c in channels] + ['Итого'],
            'values': [round(baseline_total, 0)] + [round(c['contribution'], 0) for c in channels] + [round(total_sales, 0)],
            'types': ['baseline'] + ['channel'] * len(channels) + ['total'],
        },
        'time_series': {
            'dates': dates,
            'baseline': baseline_ts,
            'channels': time_series_channels,
        },
        # Trust Level 3 (v1.1.0): hierarchical metadata для UI banner.
        # Empty / use_hierarchical=False для legacy + non-hierarchical models.
        'hierarchical': {
            'enabled': bool(model_data.get('use_hierarchical')),
            'channel_categories': dict(model_data.get('channel_categories') or {}),
            'categorization_warnings': list(model_data.get('categorization_warnings') or []),
            'priors_summary': dict(model_data.get('hierarchical_priors') or {}),
        },
        # v2.0.0 (ADR-019 §4): signed factor contributions для UI WaterfallChart
        # с negative bars + Report narrative.
        # Schema: { factor_col_name: { value, pct, type, beta_mean, per_period[] } }
        # type ∈ {'signed_competitor', 'signed_price', 'signed_weather', 'signed_macro',
        #         'holiday', 'seasonality', 'positive_control'}
        # Спец-ключ 'Сезонность' (агрегат Фурье sin/cos) — без beta_mean (сумма гармоник).
        'signed_factor_contributions': signed_factor_contributions,
        # Аудит #12 (2026-06-07, INV-50): канонический набор серий timeline-
        # декомпозиции — ЕДИНЫЙ источник для программы (ChannelTimeline) и всех
        # отчётов (HTML/PPTX/XLSX). baseline_reduced + Σфакторы + Σмедиа == total.
        'decomposition_series': build_decomposition_series(
            dates, baseline_ts, time_series_channels, signed_factor_contributions,
        ),
    }

    # Save (NaN-safe 2026-06-04 аудит: NaN→null, иначе Rust serde_json роняет файл).
    # E3: save_results=False у сравнения поколений — расчёт по архивной модели
    # не должен подменять результаты текущей.
    if save_results:
        from utils.safe_io import sanitize_nonfinite
        results_dir = project_path / 'results'
        results_dir.mkdir(parents=True, exist_ok=True)
        with open(results_dir / 'decomposition.json', 'w', encoding='utf-8') as f:
            json.dump(sanitize_nonfinite(result), f, ensure_ascii=False, indent=2)

    return result
