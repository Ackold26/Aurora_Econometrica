"""
engines.pptx_export — thin adapter over aurora_pptx (M4 refactor, Session 4).

Previously 703 LOC of manual slide construction. Refactored 2026-04-24 to
delegate rendering to `econometrica.aurora_pptx.build_pptx(data)`, which
produces the tier-1 Hybrid-branded 13-slide deliverable defined in
`Standards/CLIENT_READY_ANATOMY.md` and the wireframe v3.

This module remains the single entry point for `server.py::export_pptx`.
The public signature `build_pptx(model_data, decompose_data, optimize_data,
output_path, scenarios=None, project_id=None)` is preserved for backward
compatibility with Rust callers and server.py.

Responsibilities:
  1. Map Econometrica pipeline data structures (model_data / decompose_data /
     optimize_data / scenarios) → aurora_pptx builder data schema.
  2. Invoke aurora_pptx.build_pptx(data) to render the 13-slide PPTX.
  3. Save to output_path, return status dict in the shape server.py expects.

Narrative content (at-a-glance findings, SCQAR body, channel leader story)
remains generic in v1.0.11 — wireframe v3 is structurally Kagocel-specific;
deeper narrative parametrization is scheduled post-pilot. Multi-client
safety is achieved via meta (client/project_id/period) and diagnostic
callouts (MQS/R²/MAPE/R-hat/ESS).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger('econometrica')

# Month names for Russian date formatting (locale-independent).
_RU_MONTHS = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_ru_date(dt: datetime) -> str:
    return f"{dt.day} {_RU_MONTHS[dt.month]} {dt.year}"


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

    Guards against drift like "TV"/"Tv"/"ТВ" via strip+lowercase key. Decompose
    is the source (name + spend + contribution + roi); optimize adds
    current_spend/optimal_spend/miroas when present. Orphan optimize channels
    (no decompose match) are dropped with a warning.
    """
    def key(name): return (name or "").strip().lower()
    opt_by_key = {key(c.get("name")): c for c in (opt_chs or []) if c}
    merged: list[dict] = []
    for dc in (decomp_chs or []):
        if not dc:
            continue
        name = dc.get("name")
        oc = opt_by_key.get(key(name), {}) or {}
        merged.append({
            "name": name,
            "spend": dc.get("spend") or oc.get("current_spend"),
            "contribution": dc.get("contribution"),
            "roi": dc.get("roi") or oc.get("current_roi"),
            "mroas": oc.get("miroas") or oc.get("mroas") or dc.get("roi"),
            "current_spend": oc.get("current_spend"),
            "optimal_spend": oc.get("optimal_spend"),
            # verdict filled in after merge by derive_verdict
        })
    if opt_chs:
        decomp_keys = {key(c["name"]) for c in merged}
        dropped = [c.get("name") for c in opt_chs if c and key(c.get("name")) not in decomp_keys]
        if dropped:
            logger.warning(f"optimize channels not in decompose: {dropped}")
    return merged


def derive_verdict(channel: dict) -> str:
    """5-way verdict encoding both efficiency (mROAS) and schedule direction
    (optimal vs current spend). Returns one of:
      Cut / Reduce / Watch / Hold / Scale

    Honest signal — Reduce means "profitable but saturation-bound, cut spend"
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


def _derive_narrative_facts(
    channels: list[dict],
    optimize_data: dict,
    scenarios: list[dict] | None,
) -> dict:
    """Compute business-logic values used by slide templates (s02/s04/s05/s07/s09).

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
        # Pick scenario with max lift_pct
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
    """Translate Econometrica pipeline output into aurora_pptx builder schema.

    Schema (Session 4 M4, meta + diagnostics only — see module docstring
    on narrative scope):

        {
          "meta": {
            "client": str,          # shown on cover, header, sources, copyright
            "project_id": str,      # shown on cover metadata grid
            "version": str,         # shown in source-notes (e.g. "v1.0.11")
            "report_date": str,     # RU-formatted "24 апреля 2026"
            "period_label": str,    # "Q1 2026" — header center label
            "forecast_period_label": str,   # "Q3-Q4 2026" — cover subtitle, SCQAR question
            "data_window_label": str,       # "W01 W13 2026" — used in source notes
          },
          "diagnostics": {
            "mqs_score": float,
            "mqs_tier_label": str,
            "r_squared": float,
            "mape_pct": float,
            "r_hat_max": float,
            "ess_min": int,
          }
        }

    Missing fields fall back to builder's Kagocel pilot defaults.
    """
    model_data = model_data or {}
    decompose_data = decompose_data or {}
    optimize_data = optimize_data or {}

    # --- Meta ---
    # project_id is the internal UUID/slug from the Econometrica pipeline.
    # Use it for both `client` (displayed name) and `project_id` field until
    # a dedicated client_name lands in pipeline metadata.
    client_label = project_id or "Client"

    now = datetime.now()
    meta = {
        "client": client_label,
        "project_id": project_id or "PROJECT",
        "version": version,
        "report_date": _fmt_ru_date(now),
        # Period labels remain defaults for now — pipeline does not yet
        # surface start/end period metadata in a stable shape.
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

    # --- Channels + narrative facts (Session C, Path C narrative parametrization) ---
    # Adapter merges decompose + optimize channel lists by name (normalized),
    # derives verdicts per 5-way rule (Cut/Reduce/Watch/Hold/Scale) with
    # optimize direction, then computes narrative_facts used by slide
    # templates (s02/s04/s05/s06/s07/s08/s09). When channels list is
    # <2 entries, skip — builder falls back to Kagocel pilot defaults.
    channels = _merge_channels(
        decompose_data.get("channels"),
        optimize_data.get("channels"),
    )
    # Canonical order: contribution desc — keeps table and narrative consistent
    # (chart still sorts by mROAS locally for display discipline).
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
            f"pptx_export adapter: only {len(channels)} channel(s) - "
            f"falling back to Kagocel narrative defaults for slide content."
        )

    logger.info(
        f"pptx_export adapter: client={client_label!r} "
        f"diagnostics_keys={list(diagnostics.keys())} "
        f"channels={len(channels)} "
        f"facts={'yes' if narrative_facts else 'fallback'} "
        f"scenarios={len(scenarios or [])}"
    )
    return data


def build_pptx(
    model_data: dict,
    decompose_data: dict,
    optimize_data: dict,
    output_path: str,
    scenarios: list[dict] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build a tier-1 client-ready PPTX from MMM pipeline data.

    Delegates to aurora_pptx.build_pptx which renders the 13-slide Hybrid
    deck per Standards/CLIENT_READY_ANATOMY.md.

    Args:
        model_data: pipeline model output (diagnostics, metrics, MQS, spec)
        decompose_data: pipeline decomposition (channels, waterfall)
        optimize_data: pipeline optimizer output (channels, lift, budget)
        output_path: where to save .pptx
        scenarios: optional saved scenarios (currently not rendered; deeper
                   narrative integration is post-pilot scope)
        project_id: internal project slug, used for client_label in header /
                    cover until pipeline exposes a dedicated display name.

    Returns:
        {"status": "success", "path": ..., "slides": 13}
        or {"status": "error", "message": ..., "type": ...} on failure.
    """
    try:
        from econometrica.aurora_pptx import build_pptx as _aurora_build
    except ImportError as e:
        msg = f"aurora_pptx package unavailable: {e}"
        logger.error(msg)
        return {"status": "error", "message": msg, "type": "ImportError"}

    try:
        data = _map_pipeline_to_builder_data(
            model_data, decompose_data, optimize_data, scenarios, project_id=project_id
        )
        prs = _aurora_build(data=data, lang="ru")
        prs.save(output_path)
        slides_count = len(prs.slides)
        logger.info(f"build_pptx OK: slides={slides_count} path={output_path}")
        return {
            "status": "success",
            "path": output_path,
            "slides": slides_count,
        }
    except Exception as e:
        logger.exception("build_pptx FAILED")
        return {
            "status": "error",
            "message": str(e),
            "type": type(e).__name__,
        }
