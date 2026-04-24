"""
engines.narrative_adapter — shared narrative adapter for Aurora AI deliverables.

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
    current_spend/optimal_spend/miroas when present. Orphan optimize channels
    (no decompose match) are dropped with a warning.
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
        merged.append({
            "name": clean_name,
            "spend": dc.get("spend") or oc.get("current_spend"),
            "contribution": dc.get("contribution"),
            "roi": dc.get("roi") or oc.get("current_roi"),
            "mroas": oc.get("miroas") or oc.get("mroas") or dc.get("roi"),
            "current_spend": oc.get("current_spend"),
            "optimal_spend": oc.get("optimal_spend"),
            # verdict filled in after merge by derive_verdict
        })
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
_CHANNEL_NAME_STOP_PHRASES = [
    r'ДО\s*НДС\s+до\s+АК', r'после\s*АК', r'с\s*НДС', r'без\s*НДС', r'до\s*НДС',
    r'Бюджет', r'Вклад', r'млн\s*₽?', r'руб\.?', r'Доля',
]
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
    """
    if not raw:
        return None
    s = str(raw)
    cleaned = _CHANNEL_NAME_RE.sub('', s)
    # Collapse whitespace + strip punctuation edges, but keep parentheses/
    # hyphens inside (audience quantifiers like "W 25-50" are signal).
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,.;:-_')
    return cleaned if cleaned else None


def derive_verdict(channel: dict) -> str:
    """5-way verdict encoding both efficiency (mROAS) and schedule direction
    (optimal vs current spend). Returns one of:
      Cut / Reduce / Watch / Hold / Scale

    Honest signal - Reduce means "profitable but saturation-bound, cut spend"
    (resolves wireframe v3 TV self-contradiction: Scale-table vs Cut-SCQAR).
    """
    curr = channel.get("current_spend") or channel.get("spend") or 0.0
    opt = channel.get("optimal_spend") or curr
    mroas = channel.get("mroas") or 0.0
    try:
        curr = float(curr) or 1e-6
        opt = float(opt)
        mroas = float(mroas)
    except (TypeError, ValueError):
        return "Watch"
    ratio = opt / max(curr, 1e-6)
    if mroas < 0.8 or ratio < 0.5:
        return "Cut"
    if mroas >= 1.2 and ratio >= 1.2:
        return "Scale"
    if ratio < 0.9:
        return "Reduce"
    if mroas >= 1.2:
        return "Hold"
    return "Watch"


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
         + channels + diagnostics). Product version not included — the
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

    # Hero mROAS lookup
    hero_ch = next((c for c in channels if c.get("name") == hero), {}) or {}
    hero_m = float(hero_ch.get("mroas") or 0)

    # Post-audit: positive-lift guard (not abs). Negative lift means the
    # optimizer couldn't find an improvement — emitting "+-1 пп" was broken
    # formatting AND misleading narrative (a promised improvement that isn't).
    try:
        lift_val = float(lift) if lift is not None else None
    except (TypeError, ValueError):
        lift_val = None
    has_lift = lift_val is not None and lift_val >= 0.5
    lift_txt = f"+{lift_val:.0f} пп к ROAS" if has_lift else None

    # Post-audit: strict-majority threshold. Old `>= n//2` triggered "risk"
    # scenario on 1-of-3 underperformers — too aggressive, fabricates a
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
            return f"Защитить лидерство {hero} - mROAS {hero_m:.1f}x устойчив"
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
        # s08: schedule action
        if leader:
            return f"Перейти на пульсирующее размещение {leader} - экономия 15-20% без потери охвата"
        return "Пульсирующее размещение вместо непрерывного - экономия без потери охвата"

    if slide_hint == "scqar":
        # s09 — 3 scenarios: Rebalance / Hold+control / Risk
        if all_underperf and hero:
            # Risk scenario — net portfolio underperformance
            names = ", ".join(underperf[:2])
            return f"Сократить {names} и сфокусировать бюджет на {hero}"
        if has_lift and hero and leader and hero != leader and realloc >= 1:
            # Rebalance scenario — quantified reallocation
            return f"Перераспределить {realloc:.0f} млн руб в {hero} - {lift_txt}"
        if hero and leader and hero != leader and realloc >= 1:
            # Rebalance без верного lift — action без числа
            return f"Перераспределить {realloc:.0f} млн руб из {leader} в {hero}"
        # Hold + control scenario
        return "Портфель сбалансирован - рекомендуется A/B тест перед ре-аллокацией"

    return None


def _derive_narrative_facts(
    channels: list[dict],
    optimize_data: dict,
    scenarios: list[dict] | None,
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
    hero = by_mroas[0] if by_mroas else {}

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
    # to avoid double-counting the same dollar leaving X entering Y)
    reallocation = 0.0
    for c in channels:
        curr = c.get("current_spend")
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

    return {
        "leader_channel": leader.get("name"),
        "hero_channel": hero.get("name"),
        "n_active_channels": n_active,
        "total_budget_mln": total_spend / 1_000_000.0 if total_spend else 0.0,
        "total_contrib_mln": total_contrib / 1_000_000.0 if total_contrib else 0.0,
        "weighted_roi": weighted_roi,
        "leader_share_spend_pct": (leader_spend / total_spend * 100) if total_spend > 0 else None,
        "leader_share_contrib_pct": (leader_contrib / total_contrib * 100) if total_contrib > 0 else None,
        "top_2_names": [c.get("name") for c in top_2],
        "top_2_contrib_pct": (top_2_contrib / total_contrib * 100) if total_contrib > 0 else None,
        "underperformer_names": [c.get("name") for c in underperformers],
        "reallocation_mln": reallocation / 1_000_000.0 if reallocation else 0.0,
        "expected_lift_pct": expected_lift,
    }


def _map_pipeline_to_builder_data(
    model_data: dict | None,
    decompose_data: dict | None,
    optimize_data: dict | None,
    scenarios: list[dict] | None,
    project_id: str | None = None,
    version: str = "1.0.11",
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

    data: dict[str, Any] = {"meta": meta}
    if diagnostics:
        data["diagnostics"] = diagnostics

    # --- Channels + narrative facts ---
    channels = _merge_channels(
        decompose_data.get("channels"),
        optimize_data.get("channels"),
    )
    # Canonical order: contribution desc - keeps tables and narrative consistent
    channels.sort(key=lambda c: float(c.get("contribution") or 0), reverse=True)
    for ch in channels:
        ch["verdict"] = derive_verdict(ch)

    narrative_facts: dict | None = None
    if len(channels) >= 2:
        narrative_facts = _derive_narrative_facts(channels, optimize_data, scenarios)
        data["channels"] = channels
        data["narrative_facts"] = narrative_facts
    elif channels:
        logger.warning(
            f"narrative_adapter: only {len(channels)} channel(s) - "
            f"falling back to preview/wireframe defaults for slide content."
        )

    logger.info(
        f"narrative_adapter: client={client_label!r} "
        f"diagnostics_keys={list(diagnostics.keys())} "
        f"channels={len(channels)} "
        f"facts={'yes' if narrative_facts else 'fallback'} "
        f"scenarios={len(scenarios or [])}"
    )
    return data
