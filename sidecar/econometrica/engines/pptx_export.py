"""
engines.pptx_export - thin adapter over aurora_pptx (M4 refactor, Session 4).

Previously 703 LOC of manual slide construction. Refactored 2026-04-24 to
delegate rendering to `econometrica.aurora_pptx.build_pptx(data)`, which
produces the tier-1 Hybrid-branded 12-slide deliverable (plus up to 3
conditional insert slides: backtest / quarter-over-quarter comparison /
forecast) defined in `Standards/CLIENT_READY_ANATOMY.md` (file missing from
this repo; current requirements source: `aurora-meta/STANDARDS/REPORTING_STANDARD.md`)
and the wireframe v3.

This module remains the single entry point for `server.py::export_pptx`.
The public signature `build_pptx(model_data, decompose_data, optimize_data,
output_path, scenarios=None, project_id=None)` is preserved for backward
compatibility with Rust callers and server.py.

Responsibilities:
  1. Map Econometrica pipeline data structures (model_data / decompose_data /
     optimize_data / scenarios) → aurora_pptx builder data schema.
  2. Invoke aurora_pptx.build_pptx(data) to render the 12-slide PPTX (plus
     up to 3 conditional insert slides).
  3. Save to output_path, return status dict in the shape server.py expects.

Narrative content (at-a-glance findings, SCQAR body, channel leader story)
remains generic in v1.0.11 - wireframe v3 is structurally Kagocel-specific;
deeper narrative parametrization is scheduled post-pilot. Multi-client
safety is achieved via meta (client/project_id/period) and diagnostic
callouts (MQS/R²/MAPE/R-hat/ESS).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from utils.safe_io import unique_export_path

# Narrative adapter functions promoted to shared module so HTML builder
# consumes the same business-logic (leader/hero/verdict, narrative facts,
# pipeline mapping). Re-exported here for backward compat with callers that
# `from engines.pptx_export import derive_verdict` etc.
from .narrative_adapter import (  # noqa: F401  (re-export)
    MAX_CHANNELS_IN_TABLE,
    _merge_channels,
    derive_verdict,
    _derive_narrative_facts,
    _map_pipeline_to_builder_data,
    _fmt_ru_date,
    _get_nested,
)

logger = logging.getLogger('econometrica')



def build_pptx(
    model_data: dict,
    decompose_data: dict,
    optimize_data: dict,
    output_path: str,
    scenarios: list[dict] | None = None,
    project_id: str | None = None,
    backtest: dict | None = None,
    generation_compare: dict | None = None,
    promises: list[dict] | None = None,
    forecast: dict | None = None,
) -> dict[str, Any]:
    """Build a tier-1 client-ready PPTX from MMM pipeline data.

    Delegates to aurora_pptx.build_pptx which renders the 12-slide Hybrid
    deck (plus up to 3 conditional insert slides) per Standards/CLIENT_READY_ANATOMY.md
    (file missing from this repo; current requirements source:
    aurora-meta/STANDARDS/REPORTING_STANDARD.md).

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
        {"status": "ok", "path": ..., "slides": 13, "renamed": False}
        or {"status": "error", "message": ..., "type": ...} on failure.

        "renamed": True если output_path уже существовал — файл сохранён
        рядом со счётчиком ("имя (2).pptx" и т.д.), "path" отражает
        фактическое итоговое имя (CPD-70: повторная генерация не должна
        молча затирать прежний клиентский документ).
    """
    try:
        from aurora_pptx import build_pptx as _aurora_build
    except ImportError as e:
        msg = f"aurora_pptx package unavailable: {e}"
        logger.error(msg)
        return {"status": "error", "message": msg, "type": "ImportError"}

    try:
        data = _map_pipeline_to_builder_data(
            model_data, decompose_data, optimize_data, scenarios,
            project_id=project_id, backtest=backtest,
            generation_compare=generation_compare, promises=promises,
            forecast=forecast,
        )
        prs = _aurora_build(data=data, lang="ru")
        final_path = unique_export_path(output_path)
        renamed = final_path != Path(output_path)
        if renamed:
            logger.warning(
                f"build_pptx: {output_path} уже существует, сохраняю как {final_path}"
            )
        prs.save(str(final_path))
        slides_count = len(prs.slides)
        logger.info(f"build_pptx OK: slides={slides_count} path={final_path}")
        return {
            "status": "ok",
            "path": str(final_path),
            "slides": slides_count,
            "renamed": renamed,
        }
    except Exception as e:
        logger.exception("build_pptx FAILED")
        return {
            "status": "error",
            "message": str(e),
            "type": type(e).__name__,
        }
