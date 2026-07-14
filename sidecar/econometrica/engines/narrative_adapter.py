"""
engines.narrative_adapter - shared narrative adapter for Aurora AI deliverables.

Promoted from engines/pptx_export.py (M1 of HTML tier-1 overhaul) so both
PPTX and HTML exports consume the same business-logic (leader/hero/verdict,
narrative facts, pipeline-to-data mapping). Zero logic duplication between
output formats.

Public surface:
  - MAX_CHANNELS_IN_TABLE: int        # row-vs-footnote pairing invariant
  - _merge_channels(decomp, opt) -> list[dict]
  - derive_verdict(channel) -> str    # Cut | Reduce | Watch | Hold | Scale
  - _derive_narrative_facts(channels, optimize, scenarios) -> dict
  - _map_pipeline_to_builder_data(model, decompose, optimize, scenarios,
      project_id=None, version='1.0.11') -> dict

Changelog:
  - 2026-04-24: extracted from pptx_export.py verbatim (Session S7 + HTML M1).
    PPTX and HTML both import from here; pptx_export keeps its public
    build_pptx() wrapper unchanged.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger('econometrica')

# Cap used by s07 action table + footnote block + any HTML table variant.
# Channels past this index are NOT rendered (row orphan prevention; see
# Session S7 post-audit fix `85d21f6`).
MAX_CHANNELS_IN_TABLE = 10

# Month names for Russian date formatting (locale-independent).
_RU_MONTHS = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_ru_date(dt: datetime) -> str:
    return f"{dt.day} {_RU_MONTHS[dt.month]} {dt.year}"


# Internal-tag tokens that should be dropped from project slugs before they
# become client-facing labels. Applied case-insensitively.
_SLUG_INTERNAL_MARKERS = {
    "исходник", "источник", "dataset", "data", "source",
    "test", "debug", "tmp", "temp", "backup", "bak",
    "ммх", "mmx", "mmm",  # platform/methodology tags - not client name
}


def _sanitize_project_slug(raw: str | None) -> tuple[str, str]:
    """Turn an internal project slug into a human-readable (client_label,
    project_code) tuple suitable for client-facing deliverables.

    Input examples (all live-test seen):
      - "mmx-2021-2025-исходник-ммх-2404-26--4"  → ("2021-2025", "...")
      - "венарус-ммх-2404-26--2"                 → ("Венарус", "...")
      - "Kagocel"                                 → ("Kagocel", "Kagocel")
      - None                                       → ("Client", "PROJECT")

    Rules:
      1. Strip trailing duplicate markers like `--4`, `-v2`, `_tmp`.
      2. Split by hyphens, drop internal markers (see _SLUG_INTERNAL_MARKERS).
      3. Capitalize remaining tokens; prefer the first alphabetic token as
         client_label, with year ranges kept as secondary info.
      4. Fallback: "Client" + "PROJECT" if everything got stripped.
    """
    if not raw:
        return ("Client", "PROJECT")

    s = str(raw).strip()
    # Strip trailing --N / -N / _N revision suffix
    s = re.sub(r'[-_]{1,2}\d+$', '', s)

    parts = [p for p in re.split(r'[-_\s]+', s) if p]
    clean_parts = []
    year_range = None
    for p in parts:
        # Detect year range like "2021-2025" (already a token or captured)
        if re.fullmatch(r'\d{4}', p):
            clean_parts.append(p)
            continue
        if p.lower() in _SLUG_INTERNAL_MARKERS:
            continue
        # Drop pure-digit suffix tokens shorter than 4 chars (revisions)
        if re.fullmatch(r'\d{1,3}', p):
            continue
        clean_parts.append(p)

    # Post-process: collapse adjacent year tokens into ranges
    def _fmt_token(tok: str) -> str:
        if re.fullmatch(r'\d{4}', tok):
            return tok  # year stays as-is
        return tok[:1].upper() + tok[1:]  # gentle capitalization

    if not clean_parts:
        return ("Client", raw or "PROJECT")

    # Group consecutive years into a single range
    labels = []
    i = 0
    while i < len(clean_parts):
        tok = clean_parts[i]
        if re.fullmatch(r'\d{4}', tok) and i + 1 < len(clean_parts) and re.fullmatch(r'\d{4}', clean_parts[i + 1]):
            labels.append(f"{tok}-{clean_parts[i + 1]}")
            i += 2
        else:
            labels.append(_fmt_token(tok))
            i += 1

    client_label = " ".join(labels)
    # Project code: uppercase, hyphen-joined
    project_code = "-".join(labels).upper()
    return (client_label, project_code)


def _get_nested(d: dict, *keys, default=None):
    """Safe nested dict.get chain."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _merge_channels(decomp_chs: list | None, opt_chs: list | None) -> list[dict]:
    """Merge decompose.channels with optimize.channels by case-insensitive name.

    Stage C.1: additionally normalizes channel names by stripping Excel
    column-header noise like "Бюджет", "до НДС", "без НДС", "ДО НДС до АК",
    "Вклад, млн" etc. If normalization produces an empty string, the channel
    is dropped (it was a total-budget column, not an actual media channel).

    Guards against drift like "TV"/"Tv"/"ТВ" via strip+lowercase key. Decompose
    is the source (name + spend + contribution + roi); optimize adds
    current_spend/optimal_spend/mroi_current when present. Orphan optimize
    channels (no decompose match) are dropped with a warning.

    F0.1 fix (Phase 0.1 fix-session 2026-04-25): previously this merged
    `miroas` (typo, with one i) which was never present in optimize JSON
    - the field is `mroi_current` (see optimizer.py). The typo silently
    fell through to `dc.roi` which is AVERAGE ROI from decomposer, not
    marginal. HTML/PPTX reports were showing average ROI in fields
    labeled "mROAS". This is fixed below + `avg_roi` is exposed as a
    separate field so reports can show both metrics.
    """
    def key(name): return (name or "").strip().lower()

    # Post-audit: log when normalization collapses different optimize columns
    # onto the same key (silent overwrite masked real channel data pre-fix).
    opt_by_key: dict[str, dict] = {}
    opt_collisions: list[tuple[str, str]] = []
    for c in (opt_chs or []):
        if not c:
            continue
        clean = _normalize_channel_name(c.get("name")) or c.get("name")
        k = key(clean)
        if k in opt_by_key:
            opt_collisions.append((opt_by_key[k].get("name") or "", c.get("name") or ""))
        opt_by_key[k] = c
    if opt_collisions:
        logger.warning(
            f"optimize channels collapse to same normalized key: {opt_collisions}"
        )

    merged: list[dict] = []
    seen_keys: set[str] = set()
    dropped_empty = []
    collision_pairs: list[tuple[str, str]] = []
    for dc in (decomp_chs or []):
        if not dc:
            continue
        raw_name = dc.get("name")
        clean_name = _normalize_channel_name(raw_name)
        if clean_name is None:
            # Column has only noise tokens (probably a total-budget aggregate
            # column that shouldn't be treated as a media channel).
            dropped_empty.append(raw_name)
            continue
        k = key(clean_name)
        if k in seen_keys:
            # Another decomp row already produced this key. We keep the first
            # (higher-contribution by upstream sort is typical) and surface
            # the collision so downstream analysis isn't silently corrupted.
            prev = next((m["name"] for m in merged if key(m["name"]) == k), "")
            collision_pairs.append((prev, raw_name or ""))
            continue
        seen_keys.add(k)
        oc = opt_by_key.get(k, {}) or {}
        # F0.1: read marginal ROAS from optimizer.json correctly.
        # `mroi_current` is the marginal value (∂KPI/∂spend at current point).
        # `roi` from decomposer is AVERAGE ROI (contribution/spend) - different
        # metric with different semantic. Both are valid; expose them under
        # distinct field names so downstream renderers can show each correctly.
        avg_roi = dc.get("roi") or oc.get("current_roi") or 0.0
        marginal = oc.get("mroi_current") or oc.get("mroas")
        if marginal is None:
            # Fallback policy when optimize hasn't run: use avg_roi as
            # placeholder so verdict logic still produces something, but
            # downstream reports will show both fields and clients can
            # see "(не оптимизировано)" in mROAS column. UI must rerun
            # optimize to get real marginal values.
            marginal = avg_roi
        merged_ch = {
            "name": clean_name,
            "spend": dc.get("spend") or oc.get("current_spend"),
            "contribution": dc.get("contribution"),
            "roi": dc.get("roi") or oc.get("current_roi"),
            "avg_roi": avg_roi,
            "mroas": marginal,
            "current_spend": oc.get("current_spend"),
            "optimal_spend": oc.get("optimal_spend"),
            # verdict filled in after merge by derive_verdict
        }
        # Phase 1.9: preserve posterior CI bounds (None for v1.0/v1.1 pickles).
        # roi_ci_* from decompose (avg ROI = contribution/spend);
        # mroas_ci_* from optimize (marginal ROAS at current allocation).
        for ci_field in ('roi_ci_low', 'roi_ci_high', 'contribution_ci_low', 'contribution_ci_high'):
            if dc.get(ci_field) is not None:
                merged_ch[ci_field] = dc.get(ci_field)
        # Optimizer CI uses 'mroi_current_*' naming → alias to 'mroas_ci_*' for downstream renderers.
        if oc.get('mroi_current_ci_low') is not None:
            merged_ch['mroas_ci_low'] = oc.get('mroi_current_ci_low')
            merged_ch['mroas_ci_high'] = oc.get('mroi_current_ci_high')
        if oc.get('mroi_optimal_ci_low') is not None:
            merged_ch['mroas_optimal_ci_low'] = oc.get('mroi_optimal_ci_low')
            merged_ch['mroas_optimal_ci_high'] = oc.get('mroi_optimal_ci_high')
        merged.append(merged_ch)
    if dropped_empty:
        logger.warning(
            f"Channels dropped (likely total-budget columns): {dropped_empty}"
        )
    if collision_pairs:
        logger.warning(
            f"decompose channels collapse to same normalized key (first wins): {collision_pairs}"
        )
    if opt_chs:
        decomp_keys = {key(c["name"]) for c in merged}
        dropped = [
            c.get("name") for c in opt_chs
            if c and key(_normalize_channel_name(c.get("name")) or c.get("name"))
            not in decomp_keys
        ]
        if dropped:
            logger.warning(f"optimize channels not in decompose: {dropped}")
    return merged


# Stop-tokens stripped from channel names to leave only the media instrument.
# Case-insensitive match; also handles Cyrillic variants. Order matters: longer
# phrases before shorter to avoid leaving orphan fragments.
# Т3-плюс (аудит №3, предложение 1): агрегатные слова «итого/всего/сумма/total» —
# колонка «ИТОГО Бюджет» раньше нормализовалась в канал «ИТОГО» и проходила в
# модель суммарной строкой (задвоение вклада). Критерий ЕДИНЫЙ для таблицы
# (_merge_channels) и гейта валидации (validate_data total_budget_as_media);
# ложное снятие юзер видит warning'ом (В-1) и возвращает роль вручную —
# асимметрия рисков в пользу снятия.
# A6-1 (2026-07-10): добавлены английские агрегатные токены (budget/spend) и
# русские (общий/расходы/затраты). Ранее матчинг через \b не работал для
# snake_case: в строке «total_media_budget» символ _ считается словесным — \b не
# стоит между словом и _, поэтому \btotal\b не матчился. Исправление: перед
# матчингом заменять _ на пробел (только для целей regex).
_CHANNEL_NAME_STOP_PHRASES = [
    r'ДО\s*НДС\s+до\s+АК', r'после\s*АК', r'с\s*НДС', r'без\s*НДС', r'до\s*НДС',
    r'Бюджет', r'Вклад', r'млн\s*₽?', r'руб\.?', r'Доля',
    r'итого', r'всего', r'сумма', r'total',
    r'budget', r'spend',
    r'общий', r'расходы', r'затраты',
]
# A6-1b (аудит 2026-07-11): 'media'/'overall'/'grand'/'gross' — квалификаторы, а
# НЕ самостоятельные стоп-слова. В общем стоп-листе они калечили реальные имена
# каналов: 'social_media'→'social', 'Media Radar'→'Radar', голый 'media'→None
# (тихо, без warning). Теперь роль снимается только когда после вычистки шума
# не осталось НИЧЕГО, кроме одного такого квалификатора (см. _normalize_channel_name):
# 'total_media_budget'→'media'→None, но 'social media' сохраняется целиком.
_AGGREGATE_QUALIFIERS = {'media', 'overall', 'grand', 'gross', 'медиа'}
_CHANNEL_NAME_RE = re.compile(
    r'\b(?:' + '|'.join(_CHANNEL_NAME_STOP_PHRASES) + r')\b',
    re.IGNORECASE,
)


def _normalize_channel_name(raw: str | None) -> str | None:
    """Strip Excel column-header noise from a channel name, leaving only
    the media instrument identifier. Returns None if nothing substantive
    remains (→ treat as a total-budget / non-channel column).

    Examples:
      "Performance Бюджет до НДС"   → "Performance"
      "Спецпроект Бюджет ДО НДС"     → "Спецпроект"
      "Banners Бюджет до НДС до АК"  → "Banners"
      "Бюджет до НДС"                → None  (signals total budget column)
      "TRPs бренд (W 25-50)"         → "TRPs бренд (W 25-50)"  (parentheses kept)
      "TV"                           → "TV"
      "tv_spend"                     → "tv"   (snake_case: _ → пробел для \b)
      "total_media_budget"           → None   (после вычистки остался квалификатор "media")
      "social_media"                 → "social media"  (составное имя, НЕ агрегат)
      "olv_budget"                   → "olv"  (olv — живой канал)

    A6-1 fix: regex применяется к версии строки с заменой _ → пробел, чтобы \b
    корректно работал в snake_case именах. Результат возвращается как clean_label
    (без подчёркиваний — они были разделителями шума, не частью имени канала).
    """
    if not raw:
        return None
    # A6-1: для целей regex-матчинга заменяем _ на пробел — иначе \b не стоит
    # между словом и _, и токены внутри snake_case не матчатся.
    s_match = str(raw).replace('_', ' ')
    cleaned = _CHANNEL_NAME_RE.sub('', s_match)
    # Collapse whitespace + strip punctuation edges, but keep parentheses/
    # hyphens inside (audience quantifiers like "W 25-50" are signal).
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,.;:-_')
    if not cleaned:
        return None
    # A6-1b (уточнено аудитом 2026-07-11): если ВСЁ, что осталось после вычистки
    # денежного/агрегатного шума, — квалификаторы, это агрегатная колонка:
    #   'total_media_budget'→'media'→None; 'gross media budget'→'gross media'→None;
    #   'overall media budget'→'overall media'→None; 'grand_total'→'grand'→None.
    # Но составное имя с реальным инструментом сохраняется целиком:
    #   'social media'→'social media'; 'gross rating points'→'gross rating points'.
    # (Проверка ТОЛЬКО первого слова пропускала двух-квалификаторные агрегаты →
    # задвоение вклада total-budget-as-media.)
    if all(w in _AGGREGATE_QUALIFIERS for w in cleaned.lower().split()):
        return None
    return cleaned


def derive_verdict(channel: dict) -> str:
    """Prescriptive action key для канала.

    math-fix v1.0.14.1, B refactor (2026-04-28):
        Migrated к engines.channel_action.compute_channel_action - single source
        of truth. Returns one of 6 keys: Scale / Hold / Watch / Reduce / Cut /
        Uncertain. CSS classes verdict-{Key} в HTML/PPTX templates.

    Pre-refactor: ad-hoc mROAS+ratio логика что давала разные ответы относительно
    decomposer.compute_roi_verdict - root cause «Hold table» vs «scale-up
    commentary» противоречий (Kagocel live-test 2026-04-27).

    Post-refactor: тонкий wrapper вокруг compute_channel_action для backward
    compat. Все callers получают same answer. Reasoning + tone доступны через
    channel['action_reasoning'] и channel['action_tone'] (decorated в
    _map_pipeline_to_builder_data).
    """
    from .channel_action import compute_channel_action
    return compute_channel_action(channel).key


def compute_report_id(
    client: str | None,
    project_id: str | None,
    channels: list[dict] | None,
    diagnostics: dict | None,
) -> str:
    """Shared deterministic trace hash for Aurora AI MMM reports.

    Post-audit fix (2026-04-25): HTML and PPTX builders previously each
    computed their own Report ID with subtly different inputs - HTML
    included `version`, PPTX didn't; HTML used dynamic diagnostic keys,
    PPTX used hardcoded 5-key tuple mixed with Kagocel fallback
    defaults. Same pipeline output → different IDs. This helper is now
    the single source of truth both builders delegate to.

    Invariants:
      1. Report ID is ONLY derived from the data itself (client + project
         + channels + diagnostics). Product version not included - the
         ID identifies the *report*, not the software release.
      2. Diagnostics tuple is built dynamically from the dict's items;
         absent keys are genuinely absent (no fallback substitution).
         This matches HTML's prior behaviour and fixes the mixed
         real+pilot hash that PPTX used to compute.
      3. Channel order invariant: sorted by (name, spend, contrib,
         verdict) so dict-ordering across Python builds doesn't affect
         output.
      4. Numeric diagnostics rounded to 3 decimals to tolerate float
         drift from repeated pipeline runs.

    Format: `aurora-mmm-{12hex}` (SHA-256 prefix).
    """
    ch_sig = sorted(
        (
            c.get("name") or "",
            int(round(float(c.get("spend") or 0))),
            int(round(float(c.get("contribution") or 0))),
            c.get("verdict") or "",
        )
        for c in (channels or [])
    )
    diag_sig = sorted(
        (k, round(float(v), 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
        for k, v in (diagnostics or {}).items()
    )
    fp = f"{client or ''}|{project_id or ''}|channels={ch_sig}|diag={diag_sig}"
    h = hashlib.sha256(fp.encode("utf-8")).hexdigest()[:12]
    return f"aurora-mmm-{h}"


def derive_action_headline(
    channels: list[dict],
    facts: dict | None,
    slide_hint: str,
) -> str | None:
    """McKinsey-style action-first headline for a given slide hint.

    Stage C.5: replaces data-describing titles ("Digital опережает TV по
    mROAS") with action+impact formulation ("Нарастить Digital - mROAS 1.9x
    даёт +8 пп к ROAS"). Zero-effect guard: if the quantified impact is
    None / <0.5pp / absent, returns a neutral "portfolio balanced" headline
    rather than fabricating a promise.

    slide_hint: "mroas" | "portfolio" | "timeline" | "scqar"
    Returns None when caller should fall back to preview/wireframe text.
    """
    if not channels or not facts:
        return None

    lift = facts.get("expected_lift_pct")
    realloc = facts.get("reallocation_mln") or 0.0
    leader = facts.get("leader_channel")
    hero = facts.get("hero_channel") or leader
    underperf = facts.get("underperformer_names") or []

    # Honest narrative: baseline-dominated model (media < 10% of total sales).
    # Override slide-specific action headlines with diagnostic/disclosure
    # framing - recommending "grow channel X" makes no sense when total media
    # contribution is microscopic relative to baseline.
    honest = bool(facts.get("honest_narrative"))
    media_pct = facts.get("media_contribution_pct")
    if honest and media_pct is not None:
        if slide_hint == "mroas":
            return f"Низкая инкрементальность медиа ({media_pct:.1f}% от продаж) – проверить отложенный эффект (adstock) и насыщение"  # П8-2 П8-1
        if slide_hint == "portfolio":
            return "Все каналы под breakeven – рассмотреть сокращение медиа или диагностику данных"  # П8-1
        if slide_hint == "timeline":
            return f"Медиа-вклад {media_pct:.1f}% – модель преимущественно объясняет продажи через базовый спрос"  # П8-2 П8-1
        if slide_hint == "scqar":
            return "Перед перераспределением: диагностика низкой инкрементальности медиа"

    # Hero mROAS lookup
    hero_ch = next((c for c in channels if c.get("name") == hero), {}) or {}
    hero_m = float(hero_ch.get("mroas") or 0)

    # Post-audit: positive-lift guard (not abs). Negative lift means the
    # optimizer couldn't find an improvement - emitting "+-1 пп" was broken
    # formatting AND misleading narrative (a promised improvement that isn't).
    try:
        lift_val = float(lift) if lift is not None else None
    except (TypeError, ValueError):
        lift_val = None
    has_lift = lift_val is not None and lift_val >= 0.5
    lift_txt = f"+{lift_val:.0f} пп к ROAS" if has_lift else None

    # Post-audit: strict-majority threshold. Old `>= n//2` triggered "risk"
    # scenario on 1-of-3 underperformers - too aggressive, fabricates a
    # "сократить X" recommendation when portfolio is actually healthy.
    # Now requires at least half the channels to be flagged, with a floor
    # of 2 (a single underperformer out of 2+ is not a "portfolio-wide risk").
    total_ch = len(channels) or 1
    all_underperf = len(underperf) >= max(2, (total_ch + 1) // 2)

    if slide_hint == "mroas":
        # s06: action = grow hero / rebalance against leader
        if hero and leader and hero != leader and hero_m >= 1.2:
            if has_lift:
                return f"Нарастить {hero} и сократить {leader} - {lift_txt}"
            return f"Нарастить {hero} - mROAS {hero_m:.1f}x против {leader}"
        if hero and hero_m >= 1.2:
            # B1-fix R-14-семейство: «устойчив» — только когда нижняя граница
            # CI выше безубыточности; при широком интервале эпитет не заявляем.
            _ci_lo = hero_ch.get("mroas_ci_low")
            try:
                _stable = _ci_lo is not None and float(_ci_lo) >= 1.0
            except (TypeError, ValueError):
                _stable = False
            _sfx = " устойчив" if _stable else ""
            return f"Защитить лидерство {hero} - mROAS {hero_m:.1f}x{_sfx}"
        if all_underperf:
            return "Сократить неэффективные каналы и сфокусировать бюджет"
        return "Сбалансировать портфель по mROAS - один канал не доминирует"

    if slide_hint == "portfolio":
        # s07: action = consolidation recommendation with quantified target share
        contribs = sorted(
            (float(c.get("contribution") or 0) for c in channels),
            reverse=True,
        )
        total = sum(contribs) or 1.0
        if total <= 0:
            return "Перепроверить входные данные - вклад каналов не рассчитывается"
        acc = 0.0
        top_n = 0
        for v in contribs:
            acc += v
            top_n += 1
            if acc / total >= 0.85:
                break
        pct = int(round(acc / total * 100))
        other_n = max(0, len(channels) - top_n)
        if len(channels) == 1:
            return "Портфель состоит из одного канала - рекомендуется диверсификация"
        if other_n == 0:
            return "Все каналы работают - консолидация не требуется"
        if top_n == 1:
            return f"Сфокусировать бюджет на одном канале - он даёт {pct}% продаж"
        return f"Консолидировать до топ-{top_n} каналов - они обеспечивают {pct}% продаж"

    if slide_hint == "timeline":
        # B1-fix R-09 (2026-07-03): прежний заголовок «Перейти на пульсирующее
        # размещение - экономия 15-20% без потери охвата» — выдуманное обещание
        # с числами: модель flighting-стратегии НЕ вычисляет. Честный заголовок
        # строится из реального числа (доля лидера в медиа-вкладе) без обещаний.
        share = facts.get("leader_share_contrib_pct")
        if leader and share is not None:
            return f"{leader} – {share:.0f}% медиа-вклада: контролировать динамику и признаки насыщения"  # П8-1
        if leader:
            return f"Контролировать динамику {leader} – опора медиа-вклада портфеля"  # П8-1
        return "Динамика вкладов: базовый уровень и медиа по периодам"

    if slide_hint == "scqar":
        # s09 - 3 scenarios: Rebalance / Hold+control / Risk
        if all_underperf and hero:
            # Risk scenario - net portfolio underperformance
            names = ", ".join(underperf[:2])
            return f"Сократить {names} и сфокусировать бюджет на {hero}"
        if has_lift and hero and leader and hero != leader and realloc >= 1:
            # Rebalance scenario - quantified reallocation
            return f"Перераспределить {realloc:.0f} млн руб в {hero} - {lift_txt}"
        if hero and leader and hero != leader and realloc >= 1:
            # Rebalance без верного lift - action без числа
            return f"Перераспределить {realloc:.0f} млн руб из {leader} в {hero}"
        # B1-fix R-14: «сбалансирован» при неопределённых вердиктах — не то же
        # самое; сначала снять неопределённость, потом перераспределять.
        _uncertain_n = sum(1 for c in channels if c.get("verdict") == "Uncertain")
        if _uncertain_n >= max(2, (total_ch + 1) // 2):
            return "Снять неопределённость вердиктов перед ре-аллокацией - интервалы эффективности широки"
        # Hold + control scenario
        return "Портфель сбалансирован - рекомендуется A/B тест перед ре-аллокацией"

    return None


def _derive_narrative_facts(
    channels: list[dict],
    optimize_data: dict,
    scenarios: list[dict] | None,
    decompose_data: dict | None = None,
) -> dict:
    """Compute business-logic values used by deliverable templates.

    Assumes channels is non-empty merged list (caller guards). Returns dict
    with keys: leader_channel, hero_channel, n_active_channels,
    total_budget_mln, total_contrib_mln, weighted_roi, leader_share_spend,
    leader_share_contrib, top_2, top_2_contrib_pct, underperformers,
    reallocation_mln, expected_lift_pct.
    """
    # Sort copy by contribution desc (non-destructive)
    by_contrib = sorted(channels, key=lambda c: float(c.get("contribution") or 0), reverse=True)
    by_mroas = sorted(channels, key=lambda c: float(c.get("mroas") or 0), reverse=True)

    leader = by_contrib[0] if by_contrib else {}
    # REC-1-GAP (2026-06-03 audit): hero = канал с макс. mROAS → попадает в клиентский
    # PPTX/HTML «перераспределить N млн в {hero}». unit_smell-канал (TRP, ROI-артефакт) НЕ
    # должен быть hero (та же ROI-1/2). Лучший по mROAS среди денежных; fallback если все unit_smell.
    _by_mroas_clean = [c for c in by_mroas if not c.get("unit_smell")]
    hero = (_by_mroas_clean[0] if _by_mroas_clean else (by_mroas[0] if by_mroas else {}))

    total_spend = sum(float(c.get("spend") or 0) for c in channels)
    total_contrib = sum(float(c.get("contribution") or 0) for c in channels)
    n_active = sum(1 for c in channels if (float(c.get("spend") or 0) > 0))

    weighted_roi = (total_contrib / total_spend) if total_spend > 0 else None

    leader_spend = float(leader.get("spend") or 0)
    leader_contrib = float(leader.get("contribution") or 0)

    top_2 = by_contrib[:2]
    top_2_contrib = sum(float(c.get("contribution") or 0) for c in top_2)

    underperformers = [c for c in channels if c.get("verdict") in ("Cut", "Watch")]

    # Reallocation = net shift between current and optimal (half of absolute sum
    # to avoid double-counting the same dollar leaving X entering Y).
    # 5c followup (2026-05-24): prefer money-axis fields (current_spend_money /
    # optimal_spend_money). Pre-fix sumеt native (TRPs + ₽) → "млн руб" в PPTX/HTML
    # narrative dimensionally wrong на mixed-unit projects. Fallback к native когда
    # money-suffix отсутствует (legacy pickles pre-money-axis schema).
    reallocation = 0.0
    for c in channels:
        curr = c.get("current_spend_money")
        if curr is None:
            curr = c.get("current_spend")
        opt = c.get("optimal_spend_money")
        if opt is None:
            opt = c.get("optimal_spend")
        if curr is None or opt is None:
            continue
        try:
            reallocation += abs(float(opt) - float(curr))
        except (TypeError, ValueError):
            pass
    reallocation /= 2.0

    expected_lift = optimize_data.get("expected_lift_pct")
    if expected_lift is None and scenarios:
        try:
            best = max(scenarios, key=lambda s: float((s.get("totals") or {}).get("lift_pct") or 0))
            expected_lift = float((best.get("totals") or {}).get("lift_pct") or 0)
        except (ValueError, TypeError):
            expected_lift = None

    # Honest narrative mode: when media contribution is small relative to
    # total sales (baseline-dominated model), narrative templates must
    # disclose this rather than claiming "X% sales generated by channel Y"
    # - that phrasing implies media drives sales, but reality is baseline-driven.
    total_sales = 0.0
    baseline_val = 0.0
    media_contrib_total = total_contrib
    if isinstance(decompose_data, dict):
        try:
            total_sales = float(decompose_data.get("total_sales") or 0)
        except (TypeError, ValueError):
            total_sales = 0.0
        try:
            baseline_val = float(decompose_data.get("baseline") or 0)
        except (TypeError, ValueError):
            baseline_val = 0.0
        ds_media = decompose_data.get("media_contribution")
        if ds_media is not None:
            try:
                media_contrib_total = float(ds_media)
            except (TypeError, ValueError):
                pass

    media_contrib_pct = (media_contrib_total / total_sales * 100) if total_sales > 0 else None
    baseline_pct = (baseline_val / total_sales * 100) if total_sales > 0 else None
    honest_narrative = media_contrib_pct is not None and media_contrib_pct < 10.0

    # N3 (Phase 0.1 fix-session): propagate optimizer state to narrative.
    # binding_constraints + optimization_converged drive consistent SCQAR /
    # f3 finding / Action 01 logic - without these, narrative claims
    # "Перебалансировать 0 млн ₽" while real story is "оптимизатор не получил
    # места для манёвра".
    binding = bool(optimize_data.get("binding_constraints", False))
    converged = optimize_data.get("optimization_converged", True)
    optimize_min_pct = optimize_data.get("min_pct_used")
    optimize_max_pct = optimize_data.get("max_pct_used")
    # math-fix v1.0.14.1, A4 (audit-of-audit 2026-04-28): false convergence
    # detection. SLSQP success=True at iter=1 (returns current allocation) -
    # narrative banner объясняет «оптимизатор не нашёл лучшего», не vacuous
    # «Сохранить аллокацию».
    converged_at_current = bool(optimize_data.get("converged_at_current", False))

    # math-fix v1.0.14.1, B (audit-of-audit 2026-04-28): action summary -
    # counts portfolio actions для consistent f4 counts + commentary planning.
    from engines.channel_action import build_action_summary
    action_summary = build_action_summary(channels)

    # L14 (math-fix v1.4 Section C, 2026-04-29): budget_dominator separate from
    # contribution leader. Pre-fix: complication template said «{leader}
    # доминирует бюджет» but `leader = top_contribution_channel` - могло быть
    # Performance с 0.7% бюджета, не overspender. Honest framing requires
    # separate field for budget-share leader.
    by_spend = sorted(channels, key=lambda c: float(c.get("spend") or 0), reverse=True)
    budget_dominator = by_spend[0] if by_spend else {}
    # Audit fix (2026-04-29): clamp negative spend к 0. Negative spend = data
    # corruption (validator should catch, но defensive guard protects narrative
    # template от rendering negative percentages). Same для contribution.
    bd_spend = max(float(budget_dominator.get("spend") or 0), 0.0)
    bd_contrib = max(float(budget_dominator.get("contribution") or 0), 0.0)

    # L15 (math-fix v1.4 Section C, 2026-04-29): cut_source / scale_destination
    # for accurate reallocation narrative.
    # L22 fix (Венарус live-test 2026-04-29): sort by mROAS вместо contribution
    # order - narrative consistency. Pre-fix: customer reads «По mROAS Social
    # опережает (11.1×)» → ANSWER «в OLV» (top contribution Scale, mROAS 3.76×).
    # Disconnect между tweets COMPLICATION (mROAS-based hero) и ANSWER
    # (contribution-based scale_destination). Post-fix: scale_destination = top
    # mROAS Scale (best marginal effectiveness for reallocation), cut_source =
    # worst mROAS Cut/Reduce (deepest cut needed). Action template now reads
    # «Перебалансировать из TRPs (mROAS 0.03×) в Social (mROAS 11.1×)» -
    # consistent с COMPLICATION «Social опережает».
    cut_candidate_chs = [c for c in channels if c.get("action") in ("Cut", "Reduce")]
    cut_candidate_chs.sort(key=lambda c: float(c.get("mroas") or 0))  # asc - worst first
    scale_candidate_chs = [c for c in channels if c.get("action") == "Scale"]
    scale_candidate_chs.sort(key=lambda c: float(c.get("mroas") or 0), reverse=True)  # desc - best first
    cut_source = cut_candidate_chs[0].get("name") if cut_candidate_chs else None
    scale_destination = scale_candidate_chs[0].get("name") if scale_candidate_chs else None

    # L23 fix (Венарус live-test 2026-04-29): dedup cut_source from
    # underperformer_names. Pre-fix: ANSWER «из TRPs в OLV; сократить или
    # остановить TRPs» - TRPs дважды (cut_source AND underperformer overlap).
    # Post-fix: underperf list excludes cut_source (it's already named explicitly
    # в reallocation segment). Если remaining list empty → underperf section
    # пропускается template'ом.
    underperformer_names_raw = [c.get("name") for c in underperformers if c.get("name")]
    underperformer_names_dedup = [n for n in underperformer_names_raw if n != cut_source]

    return {
        "leader_channel": leader.get("name"),
        "hero_channel": hero.get("name"),
        "n_active_channels": n_active,
        "total_budget_mln": total_spend / 1_000_000.0 if total_spend else 0.0,
        # Fix 2026-07-13 (INV-50): «млн» НЕ units-neutral. Прежний комментарий
        # утверждал, что деление на 1e6 корректно для любой метрики, а единицу
        # выбирает consumer — неверно: для count consumer подписывал «лид.» (без
        # «млн»), а значение делилось на 1e6 → «1.3 лид.» вместо «1.3 млн лид.»
        # (занижение в 1e6). Consumer'ы теперь берут raw вклад и масштабируют через
        # _contrib_scale (единица ↔ масштаб вместе). total_contrib_mln оставлен
        # (= raw/1e6) для обратной совместимости; для count consumer домножает
        # обратно на 1e6 и форматирует через _fmt_contrib.
        "total_contrib_mln": total_contrib / 1_000_000.0 if total_contrib else 0.0,
        "weighted_roi": weighted_roi,
        "leader_share_spend_pct": (leader_spend / total_spend * 100) if total_spend > 0 else None,
        "leader_share_contrib_pct": (leader_contrib / total_contrib * 100) if total_contrib > 0 else None,
        "top_2_names": [c.get("name") for c in top_2],
        "top_2_contrib_pct": (top_2_contrib / total_contrib * 100) if total_contrib > 0 else None,
        "underperformer_names": underperformer_names_dedup,
        "reallocation_mln": reallocation / 1_000_000.0 if reallocation else 0.0,
        "expected_lift_pct": expected_lift,
        # Honest narrative inputs (Phase 0.7 - narrative_adapter v2)
        "total_sales": total_sales if total_sales > 0 else None,
        "baseline_pct": baseline_pct,
        "media_contribution_pct": media_contrib_pct,
        "honest_narrative": honest_narrative,
        # Optimizer state (Phase 0.1 fix-session + v1.0.14.1)
        "binding_constraints": binding,
        "optimization_converged": converged,
        "optimize_min_pct": optimize_min_pct,
        "optimize_max_pct": optimize_max_pct,
        "converged_at_current": converged_at_current,
        # Action summary (B refactor) - counts + channels_by_action + top_action
        "action_counts": action_summary["counts"],
        "channels_by_action": action_summary["channels_by_action"],
        "top_action": action_summary["top_action"],
        # L14: budget_dominator separate from contribution leader
        "budget_dominator_channel": budget_dominator.get("name"),
        "budget_dominator_spend_pct": (bd_spend / total_spend * 100) if total_spend > 0 else None,
        "budget_dominator_contrib_pct": (bd_contrib / total_contrib * 100) if total_contrib > 0 else None,
        # L15: action-driven reallocation subjects
        "cut_source_channel": cut_source,
        "scale_destination_channel": scale_destination,
    }


# B1-fix R-02/R-03/R-04 (2026-07-03): честное покрытие данных из time_series.dates
# вместо wireframe-дефолтов билдера («W01 W13 2026», «наблюдений = каналы×13»,
# «Еженедельно»). Считаем ТОЛЬКО из реальных дат; непарсибельные (порядковые
# '1','2',...) → None — билдер покажет «—», НЕ выдумает.
_RU_MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def _derive_data_coverage(decompose_data: dict | None) -> dict | None:
    ts = (decompose_data or {}).get('time_series') or {}
    dates = ts.get('dates') or []
    parsed: list[datetime] = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(str(d)[:10], '%Y-%m-%d'))
        except (ValueError, TypeError):
            return None  # не даты (legacy порядковые метки) — не гадаем
    if len(parsed) < 2:
        return None
    deltas = [(b - a).days for a, b in zip(parsed, parsed[1:])]
    med = sorted(deltas)[len(deltas) // 2]
    if med == 1:
        freq = 'Ежедневно'
    elif 6 <= med <= 8:
        freq = 'Еженедельно'
    elif 27 <= med <= 32:
        freq = 'Ежемесячно'
    elif 88 <= med <= 95:
        freq = 'Поквартально'
    else:
        freq = None
    # Разрывы оси дат: дельта, заметно превышающая типичный шаг.
    date_gaps = sum(1 for d in deltas if d > med * 1.5) if med > 0 else 0

    def _lbl(dt: datetime) -> str:
        return f'{_RU_MONTHS_SHORT[dt.month - 1]} {dt.year}'

    return {
        'window_label': f'{_lbl(parsed[0])} – {_lbl(parsed[-1])}',
        'n_observations': len(parsed),
        'frequency_label': freq,
        'date_gaps': date_gaps,
    }


def _map_pipeline_to_builder_data(
    model_data: dict | None,
    decompose_data: dict | None,
    optimize_data: dict | None,
    scenarios: list[dict] | None,
    project_id: str | None = None,
    version: str = "1.0.11",
    backtest: dict | None = None,
    generation_compare: dict | None = None,
    promises: list[dict] | None = None,
    forecast: dict | None = None,
) -> dict:
    """Translate Econometrica pipeline output into deliverable builder schema.

    Schema (shared between PPTX and HTML tier-1 outputs):

        {
          "meta": {
            "client": str,          # shown on cover, header, sources, copyright
            "project_id": str,      # shown on cover metadata grid
            "version": str,         # shown in source-notes (e.g. "v1.0.11")
            "report_date": str,     # RU-formatted "24 апреля 2026"
            "period_label": str,    # "Q1 2026" - header center label
            "forecast_period_label": str,   # "Q3-Q4 2026" - cover subtitle
            "data_window_label": str,       # "W01 W13 2026" - source notes
          },
          "diagnostics": {
            "mqs_score": float,
            "mqs_tier_label": str,
            "r_squared": float,
            "mape_pct": float,
            "r_hat_max": float,
            "ess_min": int,
            # INV-50 F-DELIVERABLE-1 (2026-06-07): data-thinness disclosure.
            # Эти поля прежде ронялись на этом шве → честная оговорка о
            # переобучении («Данных мало, Ratio 2.4:1») доходила до программы и
            # сопроводительного письма, но НЕ до PPTX/HTML/XLSX. Теперь
            # билдеры получают структуру и сами компонуют локализованную оговорку.
            "thinness_cap": "int|None",     # 50/70 если cap применён, иначе None
            "ratio": float,                 # эффективный (obs/effective_params) — драйвит cap
            "ratio_nominal": float,         # номинальный (obs/n_params) — прозрачность
            "effective_parameters": float,
          },
          "channels": [...],               # merged + verdicts (optional)
          "narrative_facts": {...}          # derived business logic (optional)
        }

    Missing fields fall back to builder's preview/wireframe defaults.
    """
    model_data = model_data or {}
    decompose_data = decompose_data or {}
    optimize_data = optimize_data or {}

    # --- Meta (Stage B.1: sanitize project slug → human-readable client) ---
    client_label, project_code = _sanitize_project_slug(project_id)

    now = datetime.now()
    meta = {
        "client": client_label,
        "project_id": project_code,
        "version": version,
        "report_date": _fmt_ru_date(now),
    }
    # B1-fix R-02 (2026-07-03): честный период данных из реальных дат — прежде
    # билдер рисовал wireframe «Q1 2026» / «W01 W13 2026» на ЛЮБОМ живом отчёте
    # (внутреннее противоречие: timeline-слайд показывал настоящие даты).
    data_coverage = _derive_data_coverage(decompose_data)
    if data_coverage:
        meta["period_label"] = data_coverage["window_label"]
        meta["data_window_label"] = data_coverage["window_label"]

    # --- Diagnostics ---
    diag_src = model_data.get("diagnostics", {}) or {}
    mqs = diag_src.get("mqs", {}) or {}
    metrics = diag_src.get("metrics", {}) or {}

    def _first(*candidates, default=None):
        for c in candidates:
            if c is not None:
                return c
        return default

    mqs_score = _first(mqs.get("score"), default=None)
    mqs_tier = _first(mqs.get("tier_label"), mqs.get("tier"), default=None)
    r_squared = _first(metrics.get("r_squared"), diag_src.get("r_squared"), default=None)
    mape_pct = _first(metrics.get("mape_pct"), diag_src.get("mape"), default=None)
    r_hat_max = _first(metrics.get("r_hat_max"), metrics.get("r_hat"), diag_src.get("r_hat"), default=None)
    ess_min = _first(metrics.get("ess_min"), metrics.get("ess"), diag_src.get("ess"), default=None)
    # B1-fix R-01 (2026-07-03): после F-11 мат-аудита движок отдаёт
    # ess_bulk_min / ess_tail_min (ключа ess_min больше нет) → этот шов терял
    # ESS, и билдер рисовал wireframe-дефолт 1247 в живом отчёте, маскируя
    # реальные значения (Kagocel-зонд: tail 382.7 < 400 по Vehtari et al. 2021).
    # Консервативно берём минимум из bulk/tail — семантика «ESS (min)».
    if ess_min is None:
        _ess_cands = [v for v in (metrics.get("ess_bulk_min"), metrics.get("ess_tail_min"))
                      if isinstance(v, (int, float))]
        ess_min = min(_ess_cands) if _ess_cands else None
    # INV-50 F-DELIVERABLE-1: data-thinness disclosure fields (прежде дропались).
    # thinness_cap читаем из mqs (там его кладёт model_quality_score), ratio —
    # из metrics (эффективный, драйвит cap). None — когда cap не применён.
    thinness_cap = mqs.get("thinness_cap")
    ratio_eff = _first(metrics.get("ratio"), default=None)
    ratio_nom = _first(metrics.get("ratio_nominal"), default=None)
    eff_params = _first(metrics.get("effective_parameters"), default=None)

    diagnostics: dict[str, Any] = {}
    if mqs_score is not None:
        diagnostics["mqs_score"] = float(mqs_score)
    if mqs_tier:
        diagnostics["mqs_tier_label"] = str(mqs_tier)
    if r_squared is not None:
        diagnostics["r_squared"] = float(r_squared)
    if mape_pct is not None:
        diagnostics["mape_pct"] = float(mape_pct)
    if r_hat_max is not None:
        diagnostics["r_hat_max"] = float(r_hat_max)
    if ess_min is not None:
        try:
            diagnostics["ess_min"] = int(ess_min)
        except (TypeError, ValueError):
            pass
    # thinness_cap намеренно может быть None (cap не сработал) — кладём всегда,
    # когда поле присутствует в источнике, чтобы билдер мог отличить «нет cap»
    # от «не знаем». ratio кладём, когда есть, для прозрачности.
    if "thinness_cap" in mqs:
        diagnostics["thinness_cap"] = thinness_cap
    if ratio_eff is not None:
        try:
            diagnostics["ratio"] = float(ratio_eff)
        except (TypeError, ValueError):
            pass
    if ratio_nom is not None:
        try:
            diagnostics["ratio_nominal"] = float(ratio_nom)
        except (TypeError, ValueError):
            pass
    if eff_params is not None:
        try:
            diagnostics["effective_parameters"] = float(eff_params)
        except (TypeError, ValueError):
            pass

    # B1-fix R-16 (2026-07-03): honesty-контур модели в отчёт. Прежде вердикт
    # надёжности и preflight (prior predictive FAIL на Kagocel-зонде: coverage
    # 42%) вычислялись движком, показывались в программе — и НЕ доезжали до
    # клиентского PPTX/HTML вовсе («вычисленная, но не доставленная честность»).
    if diag_src:
        try:
            from utils.optimizer_honesty import model_reliability_verdict
            _verdict = model_reliability_verdict(diag_src)
            diagnostics["honesty_verdict"] = _verdict.get("verdict")
            _reasons = [str(r) for r in (_verdict.get("reasons") or [])]
            if _reasons:
                diagnostics["honesty_reasons"] = _reasons[:3]
        except Exception:  # noqa: BLE001 - honesty-доставка не роняет экспорт
            pass
        _pf = diag_src.get("preflight") or {}
        _pp = _pf.get("prior_predictive") or {}
        _qp = _pf.get("quick_proxy") or {}
        if _pp or _qp:
            diagnostics["preflight"] = {
                "prior_predictive_status": _pp.get("status"),
                "prior_predictive_coverage": _pp.get("coverage"),
                "quick_proxy_tier": _qp.get("tier"),
            }
        # E2 (2026-07-03): калибровка lift-тестами — пометка [CALIBRATED] у
        # канала + честное расхождение модель-vs-тест (within_ci=False НЕ
        # замалчивается — §E2.4 ROADMAP).
        _calib_applied = diag_src.get("calibration_applied") or []
        _calib_checks = diag_src.get("calibration_check") or []
        if _calib_applied or _calib_checks:
            diagnostics["calibration"] = {
                "applied": _calib_applied,
                "checks": _calib_checks,
            }

    data: dict[str, Any] = {"meta": meta}
    if diagnostics:
        data["diagnostics"] = diagnostics
    # B1-fix R-03/R-04: честное покрытие данных (наблюдения/частота/разрывы) —
    # билдер рисует эти строки из факта вместо «каналы×13» и «Еженедельно».
    if data_coverage:
        data["data_coverage"] = data_coverage

    # --- KPI kwargs для compute_channel_action (Фаза 3, пласт 1 — 2026-07-11) ---
    # Читаем из decompose_data ДО декорирования каналов, чтобы прокинуть в action.
    # Дублирует логику блока «v1.3.0: KPI metadata» ниже — намеренно (DRY нарушено
    # минимально: одна переменная-группа _kpi_action_kwargs передаётся в декоратор).
    _kpi_action_kwargs: dict = {}
    if decompose_data:
        _ak_kpi_kind = decompose_data.get('kpi_kind', 'monetary')
        _ak_derived_mode = decompose_data.get('derived_mode', 'roi')
        _ak_vpcu_raw = decompose_data.get('value_per_count_unit')
        try:
            _ak_vpcu = float(_ak_vpcu_raw) if _ak_vpcu_raw is not None else None
        except (TypeError, ValueError):
            _ak_vpcu = None
        # money_roi_unavailable: count без vpcu ИЛИ derived_mode=effectiveness
        # — идентично compute_roi_verdict в decomposer.py
        _ak_mriu = (
            (_ak_kpi_kind == 'count' and (_ak_vpcu is None or _ak_vpcu <= 0))
            or _ak_derived_mode == 'effectiveness'
        )
        # Паспортные подписи для reasoning-строк
        try:
            from utils.kpi_labels import metric_short_label
            _ak_metric_short = metric_short_label(
                _ak_kpi_kind, _ak_derived_mode,
                kpi_type=decompose_data.get('kpi_type') or None,
            )
        except Exception:  # noqa: BLE001
            _ak_metric_short = 'CPU' if _ak_kpi_kind == 'count' else 'ROI'
        try:
            from aurora_pptx.kpi_helpers import kpi_view as _kv
            _kpi_v = _kv({'kpi': {
                'kpi_kind': _ak_kpi_kind,
                'derived_mode': _ak_derived_mode,
                'kpi_type': decompose_data.get('kpi_type') or None,
                'labels': {},
            }})
            _ak_cpu_per_label = _kpi_v.get('cpu_per_label', '₽/ед.')
        except Exception:  # noqa: BLE001
            _ak_cpu_per_label = '₽/ед.'
        _kpi_action_kwargs = {
            'kpi_kind': _ak_kpi_kind,
            'vpcu': _ak_vpcu,
            'money_roi_unavailable': _ak_mriu,
            'metric_short': _ak_metric_short,
            'cpu_per_label': _ak_cpu_per_label,
        }

    # --- Channels + narrative facts ---
    channels = _merge_channels(
        decompose_data.get("channels"),
        optimize_data.get("channels"),
    )
    # Canonical order: contribution desc - keeps tables and narrative consistent
    channels.sort(key=lambda c: float(c.get("contribution") or 0), reverse=True)
    # math-fix v1.0.14.1, B (2026-04-28): decorate с action structured data.
    # Templates (HTML/PPTX) reads ch['action_label']/['action_reasoning'] вместо
    # генерируя свои hardcoded строки → coherence between table + commentary.
    # Фаза 3, пласт 1 (2026-07-11): прокидываем kpi_action_kwargs → честные
    # вердикты для count-метрик (исправляет «огульный Cut» при mROAS=0.01–0.05).
    from engines.channel_action import compute_channel_action
    for ch in channels:
        action = compute_channel_action(ch, **_kpi_action_kwargs)
        ch["verdict"] = action.key
        ch["action"] = action.key
        ch["action_label"] = action.label_ru
        ch["action_reasoning"] = action.reasoning
        ch["action_tone"] = action.tone
        ch["action_priority"] = action.priority
        ch["action_confidence"] = action.confidence

    narrative_facts: dict | None = None
    if len(channels) >= 2:
        narrative_facts = _derive_narrative_facts(channels, optimize_data, scenarios, decompose_data)
        data["channels"] = channels
        data["narrative_facts"] = narrative_facts
    elif channels:
        logger.warning(
            f"narrative_adapter: only {len(channels)} channel(s) - "
            f"falling back to preview/wireframe defaults for slide content."
        )

    ts = decompose_data.get("time_series")
    if isinstance(ts, dict) and ts.get("dates") and ts.get("baseline"):
        data["time_series"] = {
            "dates": list(ts["dates"]),
            "baseline": [float(v) for v in ts["baseline"]],
            "channels": {
                str(name): [float(v) for v in vals]
                for name, vals in (ts.get("channels") or {}).items()
            },
        }

    # Аудит #12 (2026-06-07, INV-50): канонический набор серий timeline-
    # декомпозиции (baseline_reduced + media + вынесенные signed/holiday) —
    # ЕДИНЫЙ источник для всех отчётов. Legacy (нет поля) — считаем той же
    # функцией на лету (SSOT, без дублирования логики).
    ds = decompose_data.get("decomposition_series")
    if not (isinstance(ds, dict) and ds.get("series")) and isinstance(ts, dict) and ts.get("dates"):
        try:
            from engines.decomposer import build_decomposition_series
            ds = build_decomposition_series(
                ts.get("dates"), ts.get("baseline") or [], ts.get("channels") or {},
                decompose_data.get("signed_factor_contributions"),
            )
        except Exception:
            ds = None
    if isinstance(ds, dict) and ds.get("series"):
        data["decomposition_series"] = ds

    # v1.3.0: KPI metadata for downstream report builders (per ADR-016).
    # Reads from decompose_data (which loads project settings/v13_kpi.json).
    # Defaults preserve v1.2 behavior (monetary ROI).
    if decompose_data:
        kpi_kind = decompose_data.get('kpi_kind', 'monetary')
        derived_mode = decompose_data.get('derived_mode', 'roi')
        value_per_count_unit = decompose_data.get('value_per_count_unit')
        value_per_count_unit_label = decompose_data.get('value_per_count_unit_label', '')
        # Фаза 1a: kpi_type для паспортных подписей (kpi_labels/kpi_helpers).
        kpi_type = decompose_data.get('kpi_type') or None
    else:
        kpi_kind = 'monetary'
        derived_mode = 'roi'
        value_per_count_unit = None
        value_per_count_unit_label = ''
        kpi_type = None

    try:
        from utils.kpi_labels import (
            metric_label, metric_short_label,
            target_unit_label, target_axis_label,
            cover_metric_summary, verdict_loss_threshold_label,
        )
        kpi_labels = {
            'metric_label': metric_label(kpi_kind, derived_mode, kpi_type=kpi_type),
            'metric_short_label': metric_short_label(kpi_kind, derived_mode, kpi_type=kpi_type),
            'target_unit_label': target_unit_label(kpi_kind, kpi_type=kpi_type),
            'target_axis_label': target_axis_label(kpi_kind, kpi_type=kpi_type),
            'methodology_label': verdict_loss_threshold_label(kpi_kind, kpi_type=kpi_type),
        }
    except ImportError:
        kpi_labels = {
            'metric_label': 'ROI',
            'metric_short_label': 'ROI',
            'target_unit_label': '₽',
            'target_axis_label': 'Продажи, ₽',
            'methodology_label': '',
        }

    data['kpi'] = {
        'kpi_kind': kpi_kind,
        'derived_mode': derived_mode,
        'value_per_count_unit': value_per_count_unit,
        'value_per_count_unit_label': value_per_count_unit_label,
        # Фаза 1a: протаскиваем kpi_type для паспортных подписей в kpi_helpers/sections.
        'kpi_type': kpi_type,
        'labels': kpi_labels,
    }

    # E1 (2026-07-03): backtest-витрина «модель vs факт» (models/backtest.json).
    # Передаётся билдеру ТОЛЬКО завершённая проверка (status ok + окна) —
    # insufficient/error не рождают слайд (никаких wireframe-суррогатов).
    if backtest and backtest.get('status') == 'ok' and backtest.get('windows'):
        data['backtest'] = backtest

    # E3 (2026-07-03): сравнение поколений («что изменилось с прошлого
    # квартала», models/generation_compare.json) — тот же принцип: только ok.
    if (
        generation_compare
        and generation_compare.get('status') == 'ok'
        and generation_compare.get('channels')
    ):
        data['generation_compare'] = generation_compare

    # E4 (2026-07-03): сбывшиеся рекомендации — в отчёт попадают ТОЛЬКО
    # сверенные обещания (kept/missed): pending нечего показывать клиенту,
    # wireframe-суррогатов нет по построению.
    _checked = [
        p for p in (promises or [])
        if p.get('status') in ('kept', 'missed')
    ]
    if _checked:
        data['promises_summary'] = {
            'kept': sum(1 for p in _checked if p['status'] == 'kept'),
            'missed': sum(1 for p in _checked if p['status'] == 'missed'),
            'examples': [
                {
                    'action_text': p.get('action_text'),
                    'status': p.get('status'),
                    'status_ru': p.get('status_ru'),
                    'verdict_note': p.get('verdict_note'),
                }
                for p in _checked[:2]
            ],
        }

    # E5 (2026-07-10): прогноз-план (results/planning.json + сценарии).
    # Передаётся билдеру ТОЛЬКО завершённый план (status ok + сценарии) —
    # wireframe-суррогатов нет по построению (INV-50).
    if forecast and forecast.get('status') == 'ok' and forecast.get('scenarios'):
        data['forecast'] = forecast

    logger.info(
        f"narrative_adapter: client={client_label!r} "
        f"diagnostics_keys={list(diagnostics.keys())} "
        f"channels={len(channels)} "
        f"facts={'yes' if narrative_facts else 'fallback'} "
        f"scenarios={len(scenarios or [])} "
        f"kpi_kind={kpi_kind!r} mode={derived_mode!r} "
        f"backtest={'yes' if data.get('backtest') else 'no'} "
        f"forecast={'yes' if data.get('forecast') else 'no'}"
    )
    return data
