"""
engines.html_export - thin adapter over aurora_html (v1.0.12 HTML tier-1).

Previously 612 LOC of one-shot HTML generation with generic dark theme.
Refactored 2026-04-24 to delegate rendering to
`econometrica.aurora_html.build_html(data, raw_model, raw_decompose,
raw_optimize, scenarios)`, which produces the tier-1 14-section interactive
HTML deliverable defined in `Standards/CLIENT_READY_ANATOMY_HTML.md`.

Public signature preserved for backward compat with Rust callers and
server.py::export_html.

Responsibilities:
  1. Map Econometrica pipeline data (model/decompose/optimize/scenarios) via
     narrative_adapter._map_pipeline_to_builder_data into the shared schema.
  2. Invoke aurora_html.build_html(data, raw_*=...) to render full tier-1 HTML.
  3. Load raw model_data pickle separately if available (for budget what-if
     slider Hill params).
  4. Save output, return status dict server.py expects.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

from .narrative_adapter import _map_pipeline_to_builder_data

logger = logging.getLogger('econometrica')


def _try_load_pickle_model(decompose_data: dict, explicit_model_data: dict) -> dict:
    """Load full model pickle for channel_params + normalization.

    `model_data` from Rust is the API-level dict (diagnostics etc). For the
    budget what-if slider we need the full pickle with channel_params dict
    containing beta/alpha/gamma/adstock per channel + normalization subtree
    with y_mean/y_std/media_means/media_stds. If the project path is in
    scope, we try to load latest.pkl; otherwise fall back to whatever is in
    explicit_model_data.
    """
    # If model_data already has channel_params (e.g. caller pre-loaded), trust it.
    if explicit_model_data.get('channel_params'):
        return explicit_model_data

    # Heuristic: decompose_data may contain hint of project path through
    # 'project_dir' key emitted by decomposer. Otherwise skip - what-if
    # slider will remain hidden gracefully.
    proj_dir = decompose_data.get('project_dir') or explicit_model_data.get('project_dir')
    if not proj_dir:
        return explicit_model_data

    pkl_path = Path(proj_dir) / 'models' / 'latest.pkl'
    if not pkl_path.exists():
        return explicit_model_data

    try:
        with open(pkl_path, 'rb') as f:
            full = pickle.load(f)
        logger.info(f'html_export: loaded pickle channel_params for what-if slider ({pkl_path})')
        return full
    except Exception as e:
        logger.warning(f'html_export: failed to load pickle {pkl_path}: {e}')
        return explicit_model_data


def build_html(
    model_data: dict,
    decompose_data: dict,
    optimize_data: dict,
    output_path: str,
    scenarios: list[dict] | None = None,
    project_name: str = 'Marketing Mix Model',
    project_id: str | None = None,
    initial_theme: str = 'light',
) -> dict[str, Any]:
    """Build a tier-1 interactive HTML deliverable from MMM pipeline data.

    Delegates to aurora_html.build_html which renders the 14-section report
    per Standards/CLIENT_READY_ANATOMY_HTML.md.

    Args:
        model_data: pipeline model output (diagnostics, metrics, MQS, spec).
        decompose_data: pipeline decomposition (channels, waterfall, time_series).
        optimize_data: pipeline optimizer output (channels, lift, budget).
        output_path: where to save .html.
        scenarios: optional saved scenarios for switcher dropdown.
        project_name: unused (kept for backward compat).
        project_id: internal project slug, used for client_label in header.
        initial_theme: 'light' | 'dark' | 'fun' (default 'light').

    Returns:
        {"status": "ok", "path": ..., "size_kb": ...}
        or {"status": "error", "message": ..., "type": ...} on failure.
    """
    try:
        from econometrica.aurora_html import build_html as _aurora_build
    except ImportError as e:
        msg = f'aurora_html package unavailable: {e}'
        logger.error(msg)
        return {'status': 'error', 'message': msg, 'type': 'ImportError'}

    try:
        model_data = model_data or {}
        decompose_data = decompose_data or {}
        optimize_data = optimize_data or {}
        scenarios = scenarios or []

        # Map pipeline → shared builder schema (same adapter as PPTX)
        data = _map_pipeline_to_builder_data(
            model_data=model_data,
            decompose_data=decompose_data,
            optimize_data=optimize_data,
            scenarios=scenarios,
            project_id=project_id,
        )

        # Load full pickle for budget what-if if available
        raw_model = _try_load_pickle_model(decompose_data, model_data)

        html = _aurora_build(
            data,
            initial_theme=initial_theme,
            raw_model=raw_model,
            raw_decompose=decompose_data,
            raw_optimize=optimize_data,
            scenarios=scenarios,
        )

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding='utf-8')
        size_kb = out_path.stat().st_size / 1024.0
        logger.info(f'HTML export OK: {out_path} ({size_kb:.1f} KB)')
        return {
            'status': 'ok',
            'path': str(out_path),
            'size_kb': round(size_kb, 1),
        }
    except Exception as e:
        logger.exception('HTML export failed')
        return {
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__,
        }
